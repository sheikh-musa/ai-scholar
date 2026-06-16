-- Widen first-stage recall on the semantic-retrieval RPCs (task #51).
--
-- The four match_* RPCs all run at pgvector's DEFAULT index-probe settings,
-- which are tuned for latency, not recall:
--   - match_juridical_embeddings  → HNSW   (hnsw.ef_search default = 40)
--   - search_hadith_semantic      → ivfflat (ivfflat.probes default = 1)
--   - search_tafsir_semantic      → ivfflat (ivfflat.probes default = 1)
--   - search_asbab_semantic       → ivfflat (ivfflat.probes default = 1)
--
-- ivfflat.probes = 1 is the sharp one: with lists in {400,300,50}, a probe of
-- 1 scans a single list (1/400 .. 1/50 of the space), so a chunk whose nearest
-- centroid is a hair off the query's centroid is invisible regardless of true
-- cosine. This is first-stage recall loss BEFORE the reranker / 0.50 gate ever
-- see the candidate — the same "content is in the corpus but never surfaced"
-- failure class as the PostgREST 1000-row truncation fixed in 20260613_002.
--
-- Knob values (standard pgvector heuristics):
--   - ivfflat.probes ≈ sqrt(lists), the usual recall/latency sweet spot:
--       hadith lists=400 → probes=20 ; tafsir lists=300 → probes=18 ;
--       asbab  lists=50  → probes=8.
--   - hnsw.ef_search = 120: comfortable headroom over the wide match_count=40
--     candidate pool (ef_search must be >= match_count to return a full pool;
--     40/40 was marginal). 3x pool is the conventional reranker-feed setting.
--
-- Scoped via function-level SET (baked onto each function), so the wider search
-- applies ONLY to these retrieval RPCs — no global GUC change, no effect on any
-- other query on the database. Purely a recall widening: ranking, the rerank
-- stage, and the relevance gates are all unchanged; this only enlarges the
-- candidate set those later stages get to choose from.
--
-- Idempotent: CREATE OR REPLACE FUNCTION re-defines bodies verbatim from
-- 20260605_001 / 20260613_002 with the SET clause added. Additive + reversible
-- (drop the SET clause to revert to defaults). No schema or data change.

BEGIN;

-- ── juridical (HNSW) ─────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.match_juridical_embeddings(
  query_embedding vector(1024),
  match_count int DEFAULT 40,
  min_score float DEFAULT 0.0
)
RETURNS TABLE (
  juridical_text_id uuid,
  chunk_index int,
  chunk_text text,
  score float
)
LANGUAGE sql STABLE
SET hnsw.ef_search = 120
AS $$
  SELECT
    je.juridical_text_id,
    je.chunk_index,
    je.chunk_text,
    (je.embedding <#> query_embedding) * -1.0 AS score
  FROM public.juridical_embeddings je
  WHERE ((je.embedding <#> query_embedding) * -1.0) >= min_score
  ORDER BY je.embedding <#> query_embedding
  LIMIT match_count;
$$;

-- ── hadith (ivfflat, lists=400) ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.search_hadith_semantic(
  query_embedding vector(1024),
  match_count int DEFAULT 5,
  collection_filter text DEFAULT NULL,
  min_score float DEFAULT 0.45
)
RETURNS TABLE (
  hadith_id uuid,
  hadith_number text,
  collection_name text,
  english_text text,
  arabic_text text,
  grading text,
  narrator text,
  score float
)
LANGUAGE sql STABLE
SET ivfflat.probes = 20
AS $$
  SELECT
    h.id AS hadith_id,
    h.hadith_number,
    c.name AS collection_name,
    h.english_text,
    h.arabic_text,
    h.grading,
    h.narrator,
    1.0 - (he.embedding <=> query_embedding) AS score
  FROM public.hadith_embeddings he
  JOIN public.hadiths h ON h.id = he.hadith_id
  LEFT JOIN public.hadith_collections c ON c.id = h.collection_id
  WHERE (collection_filter IS NULL OR c.name = collection_filter)
    AND (1.0 - (he.embedding <=> query_embedding)) >= min_score
  ORDER BY he.embedding <=> query_embedding
  LIMIT match_count;
$$;

-- ── tafsir (ivfflat, lists=300) ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.search_tafsir_semantic(
  query_embedding vector(1024),
  match_count int DEFAULT 5,
  scholar_filter text DEFAULT NULL,
  min_score float DEFAULT 0.45
)
RETURNS TABLE (
  tafsir_entry_id uuid,
  ayah_id uuid,
  scholar_name text,
  source_work text,
  english_text text,
  arabic_text text,
  output_tier text,
  score float
)
LANGUAGE sql STABLE
SET ivfflat.probes = 18
AS $$
  SELECT
    te.id AS tafsir_entry_id,
    te.ayah_id,
    te.scholar_name,
    te.source_work,
    te.english_text,
    te.arabic_text,
    te.output_tier,
    1.0 - (tem.embedding <=> query_embedding) AS score
  FROM public.tafsir_embeddings tem
  JOIN public.tafsir_entries te ON te.id = tem.tafsir_entry_id
  WHERE (scholar_filter IS NULL OR te.scholar_name = scholar_filter)
    AND (1.0 - (tem.embedding <=> query_embedding)) >= min_score
  ORDER BY tem.embedding <=> query_embedding
  LIMIT match_count;
$$;

-- ── asbab (ivfflat, lists=50) ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.search_asbab_semantic(
  query_embedding vector(1024),
  match_count int DEFAULT 5,
  surah_filter int DEFAULT NULL,
  min_score float DEFAULT 0.45
)
RETURNS TABLE (
  asbab_id bigint,
  surah_number int,
  ayah_number_surah int,
  text_en text,
  source text,
  score float
)
LANGUAGE sql STABLE
SET ivfflat.probes = 8
AS $$
  SELECT
    a.id AS asbab_id,
    a.surah_number,
    a.ayah_number_surah,
    a.text_en,
    a.source,
    1.0 - (ae.embedding <=> query_embedding) AS score
  FROM public.asbab_embeddings ae
  JOIN public.asbab_nuzul a ON a.id = ae.asbab_id
  WHERE (surah_filter IS NULL OR a.surah_number = surah_filter)
    AND (1.0 - (ae.embedding <=> query_embedding)) >= min_score
  ORDER BY ae.embedding <=> query_embedding
  LIMIT match_count;
$$;

COMMIT;
