-- MIZAN-REENGAGE-01 — short-retention failure re-queue (CAI-RESP-396, Option C)
--
-- DESIGN: docs/MIZAN-REENGAGE-01-followup-requeue-spec.md (+ the CAI-RESP-396
-- addendum in §8). Lets a user whose question got a genuinely failed answer be
-- re-answered through the now-fixed pipeline and sent ONE courteous follow-up —
-- WITHOUT a durable raw-telegram-id store. The durable audit (mizan_interactions)
-- stays hash-only, so MIZAN-EVAL-001 (no PII) holds; a raw chat_id lands ONLY in
-- this transient, short-TTL, auto-purged queue and never for long.
--
-- ⚠️ DO-NOT-APPLY UNTIL SCHEMA REVIEW. Per CAI-RESP-396 this migration introduces
-- raw PII and therefore gets its own independent schema-review pass before apply
-- (same bar as CAI-RESP-394). Committed build-gated; cc-scholar replies on the
-- CAI-RESP-396 thread when ready for that review. Nothing enqueues or sends in
-- the live bot until the table exists AND the reviewer signs off.
--
-- CAI-RESP-396 BINDING BOUNDS encoded here:
--   §2  TTL = 24h BACKSTOP only; chat_id purged at TERMINAL (sent/skipped/expired)
--       IMMEDIATELY — enforced in-DB by the BEFORE UPDATE trigger below, not left
--       to the app.
--   §3  failure_class ∈ {timeout-stub, evidence-fallback} ONLY. weak-corpus-gap
--       is EXCLUDED at enqueue (CHECK) — re-running the same corpus yields the same
--       honest non-answer; re-queuing risks manufacturing a confident religious
--       claim the evidence doesn't carry. Honest "we don't have this" is correct.
--   §5  Cooldown = max ONE follow-up per user per 30 days (enforced in app at
--       enqueue via the telegram_id_hash + created_at index; see mizan_followup.py).
--   §6c Opt-out stored HASH-KEYED (mizan_followup_optout) so suppression is
--       permanent without reintroducing raw PII.
--   G2  VERIFIABLE purge: purge_mizan_followup_queue() returns an audit row
--       (purged_count, oldest_surviving_chat_id_age) so TTL enforcement is
--       provable each run, not assumed.
--   G4  RLS service-role-only deny-all (013-pattern).
--
-- Non-goals (unchanged): mizan_interactions stays hash-only; retract-gate
-- untouched (a follow-up to a never-answered question is NOT a retraction);
-- historical users are unrecoverable (forward-only, §7).

-- ---------------------------------------------------------------------------
-- Table 1: mizan_followup_queue — the transient raw-chat_id re-queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.mizan_followup_queue (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  interaction_id     uuid REFERENCES public.mizan_interactions(id),  -- audit joint (hash-only there)
  telegram_id_hash   text NOT NULL,          -- SHA-256(chat_id); survives purge for cooldown + opt-out join (NO raw id)
  chat_id            bigint,                  -- TRANSIENT raw id; the ONLY place it lives; NULLed at terminal/TTL.
                                              -- NOT NULL is enforced at enqueue by the app, not the column, precisely
                                              -- so the purge path can null it in place.
  query_text         text NOT NULL,
  failure_class      text NOT NULL
                       CHECK (failure_class IN ('timeout-stub', 'evidence-fallback')),  -- §3: weak-corpus-gap excluded
  status             text NOT NULL DEFAULT 'queued'
                       CHECK (status IN ('queued', 'reanswered', 'sent', 'skipped', 'expired')),
  attempts           int  NOT NULL DEFAULT 0,
  reanswer_text      text,                    -- send-worthy re-answer; cleared at terminal
  skip_reason        text,                    -- why skipped (not-send-worthy / opted-out / cooldown / ruling-gate)
  created_at         timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),  -- §2 backstop ceiling
  sent_at            timestamptz,
  chat_id_purged_at  timestamptz              -- proves the raw id was cleared (G2)
);

COMMENT ON TABLE public.mizan_followup_queue IS
  'MIZAN-REENGAGE-01 (CAI-RESP-396): transient re-queue of genuinely-failed answers. '
  'The ONLY place a raw chat_id lands; purged at terminal state and by a 24h backstop. '
  'Durable audit stays in mizan_interactions (hash-only).';
COMMENT ON COLUMN public.mizan_followup_queue.chat_id IS
  'Transient raw telegram chat_id. Non-null only while queued/reanswered; NULLed in place '
  'at terminal state (trigger) or TTL (purge job). Never logged (G3).';
COMMENT ON COLUMN public.mizan_followup_queue.failure_class IS
  'CAI-RESP-396 §3: timeout-stub | evidence-fallback ONLY. weak-corpus-gap is not eligible.';

-- Cooldown support (§5: one follow-up / user / 30d) + queue drain + TTL sweep.
CREATE INDEX IF NOT EXISTS mizan_followup_queue_hash_created_idx
  ON public.mizan_followup_queue (telegram_id_hash, created_at DESC);
CREATE INDEX IF NOT EXISTS mizan_followup_queue_status_idx
  ON public.mizan_followup_queue (status) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS mizan_followup_queue_live_chatid_idx
  ON public.mizan_followup_queue (expires_at) WHERE chat_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Table 2: mizan_followup_optout — permanent, hash-keyed suppression (§6c)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.mizan_followup_optout (
  telegram_id_hash text PRIMARY KEY,          -- SHA-256(chat_id); permanent suppression, NO raw id
  created_at       timestamptz NOT NULL DEFAULT now(),
  source           text NOT NULL DEFAULT 'stop-reply'
                     CHECK (source IN ('stop-reply', 'admin'))
);

COMMENT ON TABLE public.mizan_followup_optout IS
  'MIZAN-REENGAGE-01 (CAI-RESP-396 §6c): permanent follow-up opt-out, keyed by '
  'SHA-256(chat_id). Checked before every enqueue and every send. Hash-keyed so '
  'suppression outlives the transient queue without retaining raw PII.';

-- ---------------------------------------------------------------------------
-- Terminal purge trigger — §2: null the raw id the moment a row goes terminal.
-- DB-enforced so a forgetful app path cannot leave PII behind.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.mizan_followup_purge_pii_on_terminal()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.status IN ('sent', 'skipped', 'expired')
     AND OLD.status NOT IN ('sent', 'skipped', 'expired') THEN
    IF NEW.status = 'sent' AND NEW.sent_at IS NULL THEN
      NEW.sent_at := now();
    END IF;
    NEW.chat_id := NULL;             -- purge the transient raw id in place
    NEW.reanswer_text := NULL;       -- and the drafted answer text
    NEW.chat_id_purged_at := now();
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS mizan_followup_terminal_purge ON public.mizan_followup_queue;
CREATE TRIGGER mizan_followup_terminal_purge
  BEFORE UPDATE ON public.mizan_followup_queue
  FOR EACH ROW
  EXECUTE FUNCTION public.mizan_followup_purge_pii_on_terminal();

-- ---------------------------------------------------------------------------
-- Purge job (backstop + audit) — G2: expire any row past TTL that never reached
-- a terminal state, and RETURN a provable audit row every run.
--   purged_count                  = rows expired this run (each nulls its chat_id
--                                   via the terminal trigger)
--   oldest_surviving_chat_id_age  = age of the oldest row STILL holding a raw
--                                   chat_id; MUST stay < 24h if TTL is enforced.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.purge_mizan_followup_queue()
RETURNS TABLE (purged_count int, oldest_surviving_chat_id_age interval)
LANGUAGE plpgsql
AS $$
DECLARE
  n int;
BEGIN
  WITH expired AS (
    UPDATE public.mizan_followup_queue
       SET status = 'expired'
     WHERE expires_at < now()
       AND status IN ('queued', 'reanswered')
    RETURNING 1
  )
  SELECT count(*) INTO n FROM expired;

  purged_count := n;
  SELECT max(now() - created_at) INTO oldest_surviving_chat_id_age
    FROM public.mizan_followup_queue
   WHERE chat_id IS NOT NULL;
  RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.purge_mizan_followup_queue() IS
  'MIZAN-REENGAGE-01 G2: TTL backstop sweep. Expires rows past expires_at (trigger '
  'nulls their chat_id) and returns (purged_count, oldest_surviving_chat_id_age) as '
  'provable evidence of TTL enforcement. Run on a schedule; alert if the age nears 24h.';

-- ---------------------------------------------------------------------------
-- RLS — G4: service-role-only, deny-all to anon/authenticated (013-pattern).
-- Extra-explicit because these tables hold raw PII (transient) + suppression.
-- ---------------------------------------------------------------------------
ALTER TABLE public.mizan_followup_queue  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mizan_followup_optout ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.mizan_followup_queue  FROM anon, authenticated;
REVOKE ALL ON public.mizan_followup_optout FROM anon, authenticated;

CREATE POLICY mizan_followup_queue_service_all
  ON public.mizan_followup_queue
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY mizan_followup_optout_service_all
  ON public.mizan_followup_optout
  FOR ALL TO service_role USING (true) WITH CHECK (true);
