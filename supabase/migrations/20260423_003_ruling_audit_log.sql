-- INV-8 audit-trail substrate — Postgres + git Merkle fallback
-- Per docs/INV-8-postgres-merkle-fallback.md; ships as v0.1 audit substrate
-- independent of the pending scholar-of-record ruling on Solana PoS
-- (docs/INV-8-scholar-question.md).
--
-- Design properties:
--   - append-only: UPDATE/DELETE revoked at GRANT level and at RULE level
--   - hash chain: prev_hash = previous row's content_hash (genesis = 64 zeros)
--   - merkle_leaf: SHA-256(content_hash || prev_hash || id::text || created_at::text)
--   - per-row signatures NOT required: nightly Merkle root signature covers
--     every leaf transitively (see scripts/audit/publish-daily-attestation.ts)

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- ruling_audit_log — one row per ruling emission, append-only, hash-chained
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.ruling_audit_log (
  id                  bigserial PRIMARY KEY,
  ruling_id           uuid NOT NULL,                           -- FK to mizan_interactions or future bayan_rulings
  ruling_source       text NOT NULL                             -- which table the ruling row lives in
                        CHECK (ruling_source IN ('mizan_interactions','bayan_rulings')),
  content_hash        text NOT NULL,                           -- SHA-256 hex of canonical serialized ruling JSON
  prev_hash           text NOT NULL,                           -- previous row's content_hash; genesis = 64 zeros
  merkle_leaf         text NOT NULL,                           -- SHA-256(content_hash || prev_hash || id || created_at)
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ruling_audit_log_ruling_id_idx
  ON public.ruling_audit_log (ruling_id);

CREATE INDEX ruling_audit_log_created_at_idx
  ON public.ruling_audit_log (created_at DESC);

-- ---------------------------------------------------------------------------
-- Append-only enforcement
-- ---------------------------------------------------------------------------

-- RULE-level: UPDATE / DELETE are silently no-ops (defense in depth with GRANT).
CREATE RULE ruling_audit_log_no_update AS
  ON UPDATE TO public.ruling_audit_log DO INSTEAD NOTHING;

CREATE RULE ruling_audit_log_no_delete AS
  ON DELETE TO public.ruling_audit_log DO INSTEAD NOTHING;

-- GRANT-level: only service_role can INSERT; no one can UPDATE/DELETE.
REVOKE UPDATE, DELETE ON public.ruling_audit_log FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- Insert-time hash-chain fill trigger
-- ---------------------------------------------------------------------------
--
-- Application provides ruling_id + ruling_source + content_hash (computed
-- client-side from canonically-serialized ruling JSON). Trigger fills
-- prev_hash from the most recent row's content_hash, then computes
-- merkle_leaf. NEW.id is bigserial so it's available at BEFORE INSERT via
-- the sequence (nextval called by default expression evaluation).

CREATE OR REPLACE FUNCTION public.ruling_audit_log_fill_chain()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  genesis       text := repeat('0', 64);
  prev          text;
BEGIN
  -- Content hash must be provided and must be SHA-256 hex (64 chars).
  IF NEW.content_hash IS NULL OR length(NEW.content_hash) <> 64 THEN
    RAISE EXCEPTION 'ruling_audit_log: content_hash must be 64-char SHA-256 hex (received length %)',
      coalesce(length(NEW.content_hash), 0);
  END IF;

  -- Find previous row's content_hash. No previous → genesis.
  SELECT content_hash INTO prev
    FROM public.ruling_audit_log
   ORDER BY id DESC
   LIMIT 1;
  NEW.prev_hash := COALESCE(prev, genesis);

  -- Compute merkle_leaf.
  NEW.merkle_leaf := encode(
    digest(
      NEW.content_hash || NEW.prev_hash || NEW.id::text || to_char(NEW.created_at, 'YYYY-MM-DD"T"HH24:MI:SS.USOF'),
      'sha256'
    ),
    'hex'
  );

  RETURN NEW;
END; $$;

CREATE TRIGGER ruling_audit_log_fill_chain_trg
  BEFORE INSERT ON public.ruling_audit_log
  FOR EACH ROW EXECUTE FUNCTION public.ruling_audit_log_fill_chain();

-- ---------------------------------------------------------------------------
-- daily_attestations — per-day Merkle root + signature record
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.daily_attestations (
  attestation_date    date PRIMARY KEY,
  row_count_end       bigint NOT NULL,                         -- id of the last row included
  root_hash           text NOT NULL,
  root_signature      text NOT NULL,                           -- Ed25519 over root_hash, base64
  key_id              text NOT NULL,                           -- identifies which audit key signed
  git_commit_hash     text,                                    -- nullable until publish completes
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX daily_attestations_created_at_idx
  ON public.daily_attestations (created_at DESC);

-- ---------------------------------------------------------------------------
-- key_registry — audit signing keys with validity windows (rotation support)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.audit_key_registry (
  key_id              text PRIMARY KEY,
  public_key_b64      text NOT NULL,
  valid_from          timestamptz NOT NULL DEFAULT now(),
  valid_until         timestamptz,                             -- null = current
  rotation_reason     text,
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------

ALTER TABLE public.ruling_audit_log     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_attestations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_key_registry   ENABLE ROW LEVEL SECURITY;

-- Anon + authenticated: read-only on all three. Writes via service_role.
CREATE POLICY ruling_audit_log_read ON public.ruling_audit_log
  FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY daily_attestations_read ON public.daily_attestations
  FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY audit_key_registry_read ON public.audit_key_registry
  FOR SELECT TO anon, authenticated USING (true);

COMMIT;
