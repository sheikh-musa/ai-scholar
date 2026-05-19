-- Phase 3 schema migration per CAI-PROCESS-GLUE-AUDIT-MIZANBOT-001-LIFT-001 id 896
-- "P2: Phase 3 schema migration (chunk_index column, composite PK, re-backfill
-- at per-chunk granularity) — unlocks fine-grained retrieval".
--
-- Phase 2 had PK on juridical_text_id alone, forcing chunk-then-mean-pool. Real
-- queries (e.g. "arkan of wudu" 2026-05-11) hit the coarse-rank ambiguity case
-- where Siyam ranked above Taharah because both chapters have enumeration
-- semantics. Per-chunk rows + chunk_text storage fix this in one move:
--   - Top-K retrieval ranks specific paragraphs, not whole chapters
--   - Returned chunk_text IS the snippet (no [:2500] prefix slice)
--
-- Idempotent if re-run: ADD COLUMN IF NOT EXISTS, ALTER PK conditional.

BEGIN;

-- Drop old single-column PK (juridical_embeddings_pkey on juridical_text_id)
ALTER TABLE public.juridical_embeddings
  DROP CONSTRAINT IF EXISTS juridical_embeddings_pkey;

-- Per-chunk columns
ALTER TABLE public.juridical_embeddings
  ADD COLUMN IF NOT EXISTS chunk_index integer NOT NULL DEFAULT 0;

ALTER TABLE public.juridical_embeddings
  ADD COLUMN IF NOT EXISTS chunk_text text;

-- Backfill chunk_text from existing rows would be lossy (mean-pooled rows had
-- no chunk_text stored). Easier: DELETE existing 5 mean-pooled rows; backfill
-- script will repopulate at per-chunk granularity.
DELETE FROM public.juridical_embeddings;

-- Now safe to enforce NOT NULL on chunk_text since table is empty
ALTER TABLE public.juridical_embeddings
  ALTER COLUMN chunk_text SET NOT NULL;

-- New composite PK
ALTER TABLE public.juridical_embeddings
  ADD CONSTRAINT juridical_embeddings_pkey
  PRIMARY KEY (juridical_text_id, chunk_index);

-- Optional: ivfflat index on embedding for future RPC-based search (not used
-- by current client-side cosine, but cheap to create now)
CREATE INDEX IF NOT EXISTS idx_juridical_embeddings_embedding
  ON public.juridical_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

COMMIT;
