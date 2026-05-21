-- Ihsan-grade ingestion pipeline — schema extensions + manifest table
-- 2026-05-22 — operator directive: automated pipeline with auditable trail
--
-- Adds:
--   (a) cross_attested_with / parent_provenance_id / levenshtein_to_attestor /
--       ihsan_pipeline_manifest_id columns to ingestion_provenance
--   (b) ingestion_manifest table — pre-ingest staging with operator approval
--
-- All additions are NULL-defaulting / NOT-required, so existing rows + code
-- paths keep working. Existing ingest scripts (ingest_safinat_marbuqi.py,
-- ingest_kashifat_hajj.py, ingest_quran.py) continue to function unchanged.
-- The new pipeline (scripts/ingest_pipeline.py — forthcoming) writes through
-- the manifest path; legacy direct-write scripts are honored for backward
-- compat but discouraged for new corpus material.

BEGIN;

-- ---------------------------------------------------------------------------
-- (a) ingestion_provenance extensions
-- ---------------------------------------------------------------------------

ALTER TABLE public.ingestion_provenance
  ADD COLUMN IF NOT EXISTS cross_attested_with uuid[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.ingestion_provenance.cross_attested_with IS
  'Other ingestion_provenance.id values that independently confirm this row''s '
  'content (e.g., second OpenITI edition with ≥0.95 Levenshtein match). Empty '
  'array = no cross-attestation performed (legacy / single-source / low-bar).';

ALTER TABLE public.ingestion_provenance
  ADD COLUMN IF NOT EXISTS parent_provenance_id uuid
    REFERENCES public.ingestion_provenance(id);

COMMENT ON COLUMN public.ingestion_provenance.parent_provenance_id IS
  'Chain-of-custody: when this row supersedes an earlier ingest (e.g., '
  'source-side updated, re-OCR with cleaner output), parent_provenance_id '
  'points to the prior row. NULL = root of chain.';

ALTER TABLE public.ingestion_provenance
  ADD COLUMN IF NOT EXISTS levenshtein_to_attestor numeric;

COMMENT ON COLUMN public.ingestion_provenance.levenshtein_to_attestor IS
  'For cross_attested_with rows: average Levenshtein ratio (0.0-1.0, higher = '
  'closer match) across the attestor set. NULL if not cross-attested.';

-- ---------------------------------------------------------------------------
-- (b) ingestion_manifest — pre-ingest staging
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.ingestion_manifest (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identifying label, free-text. e.g. "kashifa-hajj-2026-05-22"
  manifest_label text NOT NULL,

  -- Target shape — what tables this manifest will populate on approval
  target_tables text[] NOT NULL,              -- e.g. ['ingestion_provenance','juridical_texts','juridical_translations']
  target_corpus_label text,                   -- e.g. "Nihāyat al-Zayn, Hajj baab"

  -- Source artifacts — each adapter run's output
  source_artifacts jsonb NOT NULL,            -- [{adapter,url,sha256,bytes,metadata,content_preview}, ...]

  -- Authenticity gate results — pass/fail per gate per source
  authenticity_gates jsonb NOT NULL,          -- {gate_name: {pass: bool, value, threshold}}

  -- Cross-attestation results (if multi-source)
  attestation jsonb,                          -- {pairs: [...], levenshtein: 0.97, diffs_excerpt: "..."}

  -- Proposed DB writes (operator reviews before --approve fires)
  proposed_provenance_rows jsonb NOT NULL,    -- array of ingestion_provenance row payloads
  proposed_content_rows jsonb NOT NULL,       -- array of juridical_texts / juridical_translations payloads

  -- Lifecycle
  status text NOT NULL DEFAULT 'awaiting_approval',
  approved_by text,                           -- e.g. "musa" / "cc-scholar"
  approved_at timestamptz,
  approved_via text,                          -- e.g. "cli", "telegram", "manifest_review_cron"

  -- Post-approval results
  committed_provenance_ids uuid[] DEFAULT '{}',
  committed_content_ids uuid[] DEFAULT '{}',
  committed_at timestamptz,

  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ingestion_manifest_status_check CHECK (
    status IN ('awaiting_approval','approved','committed','rejected','superseded')
  )
);

COMMENT ON TABLE public.ingestion_manifest IS
  'Pre-ingest staging for the Ihsan ingestion pipeline. Adapter runs write here '
  'with status=awaiting_approval; operator reviews proposed_provenance_rows + '
  'proposed_content_rows + attestation, then approves via CLI flag → ingest '
  'commits to target tables atomically. Auditable trail of what was proposed '
  'vs what was committed.';

CREATE INDEX IF NOT EXISTS idx_ingestion_manifest_status
  ON public.ingestion_manifest (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_manifest_label
  ON public.ingestion_manifest (manifest_label);

-- ---------------------------------------------------------------------------
-- (c) wire ingestion_provenance back to its originating manifest (optional FK)
-- ---------------------------------------------------------------------------

ALTER TABLE public.ingestion_provenance
  ADD COLUMN IF NOT EXISTS ihsan_pipeline_manifest_id uuid
    REFERENCES public.ingestion_manifest(id);

COMMENT ON COLUMN public.ingestion_provenance.ihsan_pipeline_manifest_id IS
  'If this provenance row was committed via the Ihsan ingestion pipeline, '
  'points back to the manifest. NULL = ingested via legacy direct-write '
  'scripts (ingest_safinat_marbuqi.py, ingest_quran.py, etc.).';

COMMIT;
