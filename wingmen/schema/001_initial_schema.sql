-- ============================================================
-- WINGMEN NERVOUS SYSTEM — Supabase Schema
-- Version: 2
-- Deploy order: run this file top to bottom, once.
-- Safe to re-run: uses IF NOT EXISTS and ON CONFLICT DO UPDATE.
-- ============================================================

-- MIGRATION VERSIONING
-- Future schema changes should be added as new numbered files:
--   002_add_indexes.sql
--   003_add_knowledge_schema.sql
-- Never modify this file after initial deployment — create a new migration instead.

-- ============================================================
-- TABLE 1: wingmen_brain_config
-- Repo registry. brain_sync reads this to know what to scan.
-- brain_sync_enabled is the feature flag for rollout.
-- ============================================================

CREATE TABLE IF NOT EXISTS wingmen_brain_config (
  repo_key           TEXT PRIMARY KEY,
  repo_path          TEXT        NOT NULL,
  display_name       TEXT        NOT NULL,
  vercel_project_id  TEXT,
  status_category    TEXT        NOT NULL
    CHECK (status_category IN ('active', 'done', 'paused', 'backlog')),
  track_revenue      BOOLEAN     NOT NULL DEFAULT false,
  is_open_source     BOOLEAN     NOT NULL DEFAULT false,
  brain_sync_enabled BOOLEAN     NOT NULL DEFAULT false,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed: all repos start with brain_sync_enabled = false except wingmen and ihsandms.
-- Do NOT change brain_sync_enabled here after initial deploy — manage it manually.
INSERT INTO wingmen_brain_config
  (repo_key, repo_path, display_name, vercel_project_id,
   status_category, track_revenue, is_open_source, brain_sync_enabled, notes)
VALUES
  ('wingmen',
   '~/gazzabyte/wingmen',
   'Wingmen Orchestrator',
   NULL,
   'active', false, false, true,
   'Validate brain_sync against this repo first.'),

  ('ihsandms',
   '~/gazzabyte/ihsandms',
   'IhsanDMS',
   'prj_hDx9LayBrCSigSdcECYJFsejjaEO',
   'active', true, false, true,
   'Mosque/madrasah donation management. Active sales. Enable second.'),

  ('candy_motors',
   '~/gazzabyte/candy-motors',
   'Candy Motors',
   NULL,
   'active', true, false, false,
   'WhatsApp chatbot. PAYING CLIENT. Enable after first two validated.'),

  ('hifz_companion',
   '~/gazzabyte/hifz-companion',
   'Hifz Companion',
   NULL,
   'active', false, true, false,
   'Quran memorization PWA. Open-source waqf. Phase 1 complete.'),

  ('dookana',
   '~/gazzabyte/dookana',
   'Dookana',
   NULL,
   'done', false, false, false,
   'Telegram-first micro-merchant platform. SHIPPED.'),

  ('al_mizan',
   '~/gazzabyte/al-mizan',
   'Al-Mīzān',
   NULL,
   'backlog', false, false, false,
   'Islamic knowledge ontology. Foundation layer.'),

  ('tadabbur',
   '~/gazzabyte/tadabbur',
   'Tadabbur',
   NULL,
   'backlog', false, true, false,
   'Visual/interactive Quran experience. Open-source waqf.'),

  ('deenseeker',
   '~/gazzabyte/deenseeker',
   'DeenSeeker',
   NULL,
   'paused', false, false, false,
   'Muslim Q&A with scholar verification.')

ON CONFLICT (repo_key) DO UPDATE SET
  repo_path         = EXCLUDED.repo_path,
  display_name      = EXCLUDED.display_name,
  vercel_project_id = EXCLUDED.vercel_project_id,
  status_category   = EXCLUDED.status_category,
  track_revenue     = EXCLUDED.track_revenue,
  is_open_source    = EXCLUDED.is_open_source,
  notes             = EXCLUDED.notes,
  updated_at        = now();
-- brain_sync_enabled intentionally excluded from ON CONFLICT UPDATE
-- to preserve manual rollout state across re-deploys.


-- ============================================================
-- TABLE 2: wingmen_brain
-- Operational snapshots. Append-only. Never UPDATE or DELETE
-- rows (except scheduled cleanup of rows older than 30 days).
-- ============================================================

CREATE TABLE IF NOT EXISTS wingmen_brain (
  id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_type      TEXT        NOT NULL CHECK (snapshot_type IN ('full', 'delta')),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  brain_sync_version INTEGER     NOT NULL DEFAULT 2,

  -- Overall sync health for this snapshot
  -- 'ok'       = all enabled repos scanned successfully
  -- 'degraded' = some repos failed to scan but run completed
  -- 'stale'    = this snapshot is itself > 6h old (set by query, not stored)
  sync_health        TEXT        NOT NULL DEFAULT 'ok'
    CHECK (sync_health IN ('ok', 'degraded')),
  sync_health_reason TEXT,

  -- Product-level operational state.
  -- Keys are repo_key values from wingmen_brain_config.
  -- Each value conforms to the product entry structure in the spec.
  products           JSONB       NOT NULL DEFAULT '{}'::jsonb,

  -- Last 24h notable activity across all repos.
  -- Array of: { repo, type, summary, timestamp }
  -- type: commit | deploy | job_complete | job_failed | blocker_added | blocker_resolved
  recent_activity    JSONB       NOT NULL DEFAULT '[]'::jsonb,

  -- Flat list of all active blockers across all products.
  -- Convenience field for claude.ai — duplicates data from products.
  active_blockers    TEXT[]      NOT NULL DEFAULT '{}',

  -- Revenue pipeline summary.
  -- { active_pitches, paying_clients, next_revenue_action }
  revenue_pipeline   JSONB       NOT NULL DEFAULT '{}'::jsonb,

  -- Wingmen orchestrator job queue state.
  -- { queue_depth, running_jobs, completed_24h, failed_24h, worker_status }
  wingmen_state      JSONB       NOT NULL DEFAULT '{}'::jsonb,

  -- Free-form synthesis from the consolidation pass.
  -- Contradictions, confidence reasoning, anything flagged for Musa.
  context_notes      TEXT,

  -- Which repos were attempted and which succeeded.
  repos_scanned      TEXT[]      NOT NULL DEFAULT '{}',
  repos_failed       TEXT[]      NOT NULL DEFAULT '{}'
);

-- Primary access pattern: latest snapshot first
CREATE INDEX IF NOT EXISTS idx_wingmen_brain_created_at
  ON wingmen_brain (created_at DESC);

-- RLS
ALTER TABLE wingmen_brain ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access" ON wingmen_brain;
CREATE POLICY "Service role full access"
  ON wingmen_brain FOR ALL
  USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Authenticated read"  ON wingmen_brain;
CREATE POLICY "Authenticated read"
  ON wingmen_brain FOR SELECT
  USING (auth.role() = 'authenticated');


-- ============================================================
-- TABLE 3: brain_sync_log
-- Audit trail. One row per brain_sync run (success or failure).
-- ============================================================

CREATE TABLE IF NOT EXISTS brain_sync_log (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  run_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  trigger               TEXT        NOT NULL
    CHECK (trigger IN ('scheduled', 'manual', 'on_demand')),
  duration_ms           INTEGER,
  snapshot_id           UUID        REFERENCES wingmen_brain(id),
  repos_attempted       INTEGER     NOT NULL DEFAULT 0,
  repos_scanned         INTEGER     NOT NULL DEFAULT 0,
  repos_failed          INTEGER     NOT NULL DEFAULT 0,
  contradictions_found  INTEGER     NOT NULL DEFAULT 0,
  sync_health           TEXT        NOT NULL,
  error_detail          TEXT        -- set if entire run failed before snapshot was written
);

-- Access pattern: recent runs first
CREATE INDEX IF NOT EXISTS idx_brain_sync_log_run_at
  ON brain_sync_log (run_at DESC);

ALTER TABLE brain_sync_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access" ON brain_sync_log;
CREATE POLICY "Service role full access"
  ON brain_sync_log FOR ALL
  USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Authenticated read" ON brain_sync_log;
CREATE POLICY "Authenticated read"
  ON brain_sync_log FOR SELECT
  USING (auth.role() = 'authenticated');


-- ============================================================
-- CLEANUP QUERY (run by brain_sync write_snapshot tool)
-- Keeps 30 days of snapshots. Not a cron — brain_sync does this.
-- ============================================================
-- DELETE FROM wingmen_brain WHERE created_at < now() - interval '30 days';

-- NOTE: Retention cleanup is handled by the write_snapshot tool
-- (see wingmen/scheduled-tasks/brain_sync/tools/write_snapshot.md)
-- which runs: DELETE FROM wingmen_brain WHERE created_at < now() - interval '30 days'
-- after each successful snapshot write.


-- ============================================================
-- VERIFICATION QUERIES
-- Run these after deploy to confirm everything is correct.
-- ============================================================

-- Should return 8 rows
-- SELECT repo_key, brain_sync_enabled, status_category FROM wingmen_brain_config ORDER BY repo_key;

-- Should return 2 rows with brain_sync_enabled = true
-- SELECT repo_key FROM wingmen_brain_config WHERE brain_sync_enabled = true;

-- Should return empty (no snapshots yet — brain_sync hasn't run)
-- SELECT count(*) FROM wingmen_brain;

-- Should return empty (no runs yet)
-- SELECT count(*) FROM brain_sync_log;
