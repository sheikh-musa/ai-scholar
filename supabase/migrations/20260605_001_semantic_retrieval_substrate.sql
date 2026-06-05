-- Semantic retrieval substrate for hadith + tafsir + asbab corpora.
--
-- Retires the SYNONYM_MAP / CONCEPT_MAP treadmill in mizan_bot.py by
-- moving these retrieval surfaces from Postgres FTS (surface-token
-- matching) to bge-m3 1024-dim semantic vectors (the same encoder
-- already running for juridical_embeddings on the Mac Studio).
--
-- Why this matters: every time a user phrases a question in words that
-- don't share enough surface tokens with the hadith English ("afdhal
-- supplication" vs "Praise be to Allah Who has fed me"), the bot misses
-- the right hadith despite it being in the corpus. Adding SYNONYM_MAP /
-- CONCEPT_MAP entries one-by-one for every miss is a slow leak, not
-- a path to scale. bge-m3 bridges these semantically without keyword
-- entries.
--
-- Per Musa direction 2026-06-05. CC-side work is this migration plus
-- backfill scripts + new semantic-retrieval modules. Embedding compute
-- happens on the Mac Studio after this migration applies.

BEGIN;

-- =============================================================
-- hadith_embeddings (PK = hadith_id; one vector per hadith)
-- =============================================================
CREATE TABLE IF NOT EXISTS public.hadith_embeddings (
  hadith_id            uuid PRIMARY KEY REFERENCES public.hadiths(id) ON DELETE CASCADE,
  embedding            vector(1024) NOT NULL,
  embedding_model      text NOT NULL,
  encoder_sha          text NOT NULL,
  corpus_version       text NOT NULL,
  embedded_source_hash text NOT NULL,
  source_token_count   integer NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS hadith_embeddings_corpus_version_idx
  ON public.hadith_embeddings(corpus_version);

-- ivfflat cosine index for top-K nearest. lists=400 is a reasonable
-- starting point for ~36K rows (sqrt(36000) ≈ 190, doubled for headroom).
-- Re-tune to lists=600-800 if recall drops after we add more hadith.
CREATE INDEX IF NOT EXISTS hadith_embeddings_vector_idx
  ON public.hadith_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 400);

ALTER TABLE public.hadith_embeddings ENABLE ROW LEVEL SECURITY;
-- service_role only (matches juridical_embeddings posture).

COMMENT ON TABLE public.hadith_embeddings IS
  'bge-m3 1024-dim semantic vectors for hadith retrieval. Replaces the surface-token FTS treadmill in mizan_bot.';


-- =============================================================
-- tafsir_embeddings (PK = tafsir_entry_id)
-- =============================================================
CREATE TABLE IF NOT EXISTS public.tafsir_embeddings (
  tafsir_entry_id      uuid PRIMARY KEY REFERENCES public.tafsir_entries(id) ON DELETE CASCADE,
  embedding            vector(1024) NOT NULL,
  embedding_model      text NOT NULL,
  encoder_sha          text NOT NULL,
  corpus_version       text NOT NULL,
  embedded_source_hash text NOT NULL,
  source_token_count   integer NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tafsir_embeddings_corpus_version_idx
  ON public.tafsir_embeddings(corpus_version);

CREATE INDEX IF NOT EXISTS tafsir_embeddings_vector_idx
  ON public.tafsir_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 300);

ALTER TABLE public.tafsir_embeddings ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.tafsir_embeddings IS
  'bge-m3 1024-dim semantic vectors for tafsir retrieval. NOTE: matched_passage F-2 invariant still derives from search_tafsir_fts (surface-token primary key into the ayah). Semantic results supplement, do not replace, that anchor for the audit row.';


-- =============================================================
-- asbab_embeddings (PK = asbab_id; bigint not uuid)
-- =============================================================
CREATE TABLE IF NOT EXISTS public.asbab_embeddings (
  asbab_id             bigint PRIMARY KEY REFERENCES public.asbab_nuzul(id) ON DELETE CASCADE,
  embedding            vector(1024) NOT NULL,
  embedding_model      text NOT NULL,
  encoder_sha          text NOT NULL,
  corpus_version       text NOT NULL,
  embedded_source_hash text NOT NULL,
  source_token_count   integer NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS asbab_embeddings_vector_idx
  ON public.asbab_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);

ALTER TABLE public.asbab_embeddings ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.asbab_embeddings IS
  'bge-m3 1024-dim semantic vectors for asbab al-nuzul. Caveat: ~19% of the 1187 rows are mislabeled per docs/ASBAB_NUZUL_CORRUPTION_2026-06-05.md; semantic search will surface them regardless of label. Do not use source attribution from asbab_nuzul.source field downstream until task #46 cleanup lands.';


-- =============================================================
-- Cosine-similarity search RPCs (PostgREST-callable from mizan_bot)
-- =============================================================

-- search_hadith_semantic — top-K nearest by cosine, with optional
-- collection filter for /collection routing.
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

-- search_tafsir_semantic — top-K nearest, scholar-attributed.
-- Does NOT replace search_tafsir_fts; supplements it. F-2 (matched_passage)
-- still derives from the FTS ayah-anchor when present.
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

-- search_asbab_semantic — top-K nearest occasions of revelation.
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
