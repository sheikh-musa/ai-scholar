-- Server-side pgvector RPC for juridical (Shafi'i fiqh) semantic retrieval.
-- Authorized by CAI-RESP-220 (B-then-A); APPLY only after the RESP-220
-- challenge window closes (2026-06-13T22:41:23Z).
--
-- Replaces the brute-force "fetch every juridical_embeddings row over PostgREST
-- and cosine in Python" path in fiqh_semantic.search_semantic. That path silently
-- truncated at PostgREST max-rows (1000) while the corpus is 1211 chunks, hiding
-- the tail of the corpus — in a fiqh matn, the late chapters (muʿāmalāt /
-- munakahat / jināyāt). The stopgap (CAI-RESP-220 B) paginated the fetch; this is
-- the proper fix: top-K ranked in Postgres against an HNSW index, never fetching
-- the whole table.
--
-- Mirrors the hadith/tafsir/asbab match_* RPCs from 20260605_001 (same encoder,
-- same shape), but uses an HNSW index + inner-product operator (<#>) per the
-- RESP-220 spec. bge-m3 outputs are L2-normalized (normalize_embeddings=True in
-- encoder_service.py), so inner product == cosine similarity; pgvector's <#>
-- returns the NEGATED inner product, hence score = (embedding <#> q) * -1 and we
-- ORDER BY the raw <#> ascending (most-negative = highest cosine first).
--
-- Per-corpus config (RESP-220 constraint): this touches ONLY the juridical
-- surface. hadith/tafsir/asbab RPCs are unchanged.
--
-- Idempotent: CREATE INDEX IF NOT EXISTS, CREATE OR REPLACE FUNCTION.

BEGIN;

-- HNSW inner-product index for top-K nearest. Better recall than the existing
-- lists=10 ivfflat (built when the table held 5 mean-pooled rows; far too few
-- lists for 1211 per-chunk rows). The old ivfflat index is left in place — it is
-- harmless and the planner picks this HNSW index for <#> ordering.
CREATE INDEX IF NOT EXISTS juridical_embeddings_hnsw_ip_idx
  ON public.juridical_embeddings
  USING hnsw (embedding vector_ip_ops);

-- match_juridical_embeddings — top-K chunks by cosine (via <#>), returning the
-- raw chunk rows. Diversification (max_per_text_id) + the 0.50 relevance gate
-- stay in fiqh_semantic.search_semantic so the RPC is a pure ranked candidate
-- source; default match_count is a wide pool (40) for the reranker to reorder.
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

COMMENT ON FUNCTION public.match_juridical_embeddings IS
  'CAI-RESP-220 (A): server-side top-K juridical chunk retrieval via HNSW + <#>. Replaces the brute-force Python cosine path that truncated at PostgREST max-rows (1000 of 1211 chunks). Diversification + 0.50 gate stay client-side in fiqh_semantic.';

COMMIT;
