-- INV-8 Hardening A (decision INV-8-FORWARD-SCHEDULER-001, CAI msg #2006 §2).
--
-- The forward attestation publisher runs as a scheduled GitHub Action. CAI
-- requires it to authenticate with a DEDICATED, LEAST-PRIVILEGE Postgres role
-- over a direct connection string — NEVER the service-role key. A GitHub
-- compromise must, at worst, be able to forge a daily seal; it must never be
-- able to read or alter anything beyond the audit surface (ruling_audit_log
-- read + daily_attestations write).
--
-- This role's accepted worst-case blast radius IS seal-forgery on
-- daily_attestations (insert/overwrite a root). That is intentional and
-- bounded: it cannot touch ruling_audit_log (read-only, and append-only is
-- additionally enforced by RULE + REVOKE in 20260423_003), cannot read
-- mizan_interactions or any other table, and cannot read/write
-- audit_key_registry.
--
-- PASSWORD IS SET OUT-OF-BAND. This migration creates the role WITHOUT a
-- password; the role cannot log in until the operator runs (not committed):
--   ALTER ROLE attestation_publisher WITH PASSWORD '<generated>';
-- The resulting direct connection string is set as the GitHub Actions secret
-- ATTESTATION_DB_URL. See .github/workflows/attestation-publish.yml.

BEGIN;

-- Idempotent role creation (Supabase migrations may re-run).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'attestation_publisher') THEN
    CREATE ROLE attestation_publisher WITH LOGIN NOINHERIT;
  END IF;
END
$$;

COMMENT ON ROLE attestation_publisher IS
  'INV-8 forward attestation publisher (GitHub Action). Least-privilege: '
  'SELECT ruling_audit_log; SELECT/INSERT/UPDATE daily_attestations. '
  'Password set out-of-band; never service-role. See INV-8-FORWARD-SCHEDULER-001.';

-- Schema usage only; no CREATE.
GRANT USAGE ON SCHEMA public TO attestation_publisher;

-- Read the audit leaves to recompute the Merkle root.
GRANT SELECT ON public.ruling_audit_log TO attestation_publisher;

-- Write the daily seal (INSERT new + UPDATE for upsert / git_commit_hash patch).
GRANT SELECT, INSERT, UPDATE ON public.daily_attestations TO attestation_publisher;

-- Explicitly NOT granted: audit_key_registry, mizan_interactions, anything else.
-- A fresh role inherits no table privileges by default.

-- RLS is enabled on all three audit tables (20260423_003). Existing policies
-- target anon/authenticated only, so the custom role matches none of them and
-- would be denied without these explicit, scoped policies.

CREATE POLICY attestation_publisher_read_audit
  ON public.ruling_audit_log
  FOR SELECT TO attestation_publisher
  USING (true);

CREATE POLICY attestation_publisher_attest_select
  ON public.daily_attestations
  FOR SELECT TO attestation_publisher
  USING (true);

CREATE POLICY attestation_publisher_attest_insert
  ON public.daily_attestations
  FOR INSERT TO attestation_publisher
  WITH CHECK (true);

CREATE POLICY attestation_publisher_attest_update
  ON public.daily_attestations
  FOR UPDATE TO attestation_publisher
  USING (true)
  WITH CHECK (true);

COMMIT;
