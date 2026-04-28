-- EMBED_PIPELINE_v02 — ayah_embeddings table per CAI-RESP-094 + CAI-RESP-095
--
-- system_layer L2 retrieval substrate (per docs/LAYERING.md).
-- pgvector cosine + HNSW index. Single embedding per ayah at v0.2 (per
-- CAI-RESP-094 Q2 ruling; reopen if recall@10 < 0.85 on augmented gold-set).
--
-- Encoder: BGE-M3 default (1024-dim) per CAI-RESP-094, may switch to
-- jina-v3 (also 1024-dim) per ARCH-AL-BAYAN-ENCODER-EVAL measurement.
-- Hosting: Modal-first per CAI-RESP-095 (A); Mac Mini deferred to v0.2.5.
--
-- DO NOT APPLY until:
--   1. MIZAN-JUDGE-SHADOW-001 migration (20260428_005) applied first
--      (per CAI-RESP-095 (B) order-locked sequencing)
--   2. ARCH-AL-BAYAN-ENCODER-EVAL measurement complete (encoder choice
--      codified)
--   3. Modal privacy verification (5 checks) complete per
--      docs/MODAL_PRIVACY_VERIFICATION.md

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- Per CAI-RESP-094 Q5: surface encoder_sha + corpus_version on every row
-- so re-embed triggers (tafsir update / encoder bump / chunking change)
-- can be detected mechanically.
CREATE TABLE IF NOT EXISTS public.ayah_embeddings (
  ayah_id              uuid PRIMARY KEY REFERENCES public.ayat(id) ON DELETE CASCADE,
  embedding            vector(1024),                  -- BGE-M3 / jina-v3 dimension
  embedding_model      text NOT NULL,                 -- e.g. 'bge-m3@<commit-sha>' or 'jina-v3@<commit-sha>'
  encoder_sha          text NOT NULL,                 -- model commit SHA for reproducibility
  corpus_version       text NOT NULL,                 -- e.g. '2026-04-28-tafsir-v1' — bumps trigger re-embed
  embedded_source_hash text NOT NULL,                 -- SHA-256 of the canonical source-text input
  source_token_count   integer NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

-- HNSW index per CAI-RESP-094 — fast cosine search, sub-50ms p99 expected
-- m=16 ef_construction=64 are pgvector defaults; tune later if recall warrants
CREATE INDEX IF NOT EXISTS ayah_embeddings_hnsw_cosine
  ON public.ayah_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Bump updated_at on UPDATE so re-embed runs are auditable
CREATE OR REPLACE FUNCTION public.ayah_embeddings_set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS ayah_embeddings_set_updated_at_trg ON public.ayah_embeddings;
CREATE TRIGGER ayah_embeddings_set_updated_at_trg
  BEFORE UPDATE ON public.ayah_embeddings
  FOR EACH ROW EXECUTE FUNCTION public.ayah_embeddings_set_updated_at();

-- RLS: read-only for anon + authenticated (public corpus); writes via
-- service_role only (the embed-backfill script + the periodic re-embed cron)
ALTER TABLE public.ayah_embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY ayah_embeddings_read ON public.ayah_embeddings
  FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY ayah_embeddings_service_all ON public.ayah_embeddings
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Retrieval RPC per EMBED_PIPELINE_v02 design — cosine similarity search
-- via HNSW, returns top-K with similarity score
CREATE OR REPLACE FUNCTION public.search_ayat_semantic(
  query_embedding vector(1024),
  lim int DEFAULT 10,
  threshold float DEFAULT 0.0
)
RETURNS TABLE (
  ayah_id              uuid,
  surah_number         int,
  ayah_number          int,
  arabic_text          text,
  english_translation  text,
  similarity           real
)
LANGUAGE sql STABLE AS $$
  SELECT
    a.id            AS ayah_id,
    a.surah_number,
    a.ayah_number,
    a.arabic_text,
    a.english_translation,
    1 - (e.embedding <=> query_embedding) AS similarity
  FROM public.ayat a
  JOIN public.ayah_embeddings e ON e.ayah_id = a.id
  WHERE 1 - (e.embedding <=> query_embedding) > threshold
  ORDER BY e.embedding <=> query_embedding
  LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION public.search_ayat_semantic(vector, int, float) TO anon, authenticated;

COMMIT;
