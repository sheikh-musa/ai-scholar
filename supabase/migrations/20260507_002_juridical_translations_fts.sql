-- juridical_translations FTS — v1 retrieval upgrade per operator direction
-- 2026-05-07. Replaces ILIKE+keyword-expansion-treadmill in mizan_bot.lookup_fiqh
-- with PostgreSQL English FTS (stemming, stop-words, punctuation/hyphens
-- handled natively, ts_rank-based relevance scoring).
--
-- Pattern mirrors 20260419_001_search_tafsir_fts.sql exactly.
-- websearch_to_tsquery handles natural-language queries (multi-word, phrases,
-- OR, negation, etc.) more robustly than plainto_tsquery.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_juridical_translations_text_fts
  ON public.juridical_translations
  USING GIN (to_tsvector('english', translation_text));

CREATE OR REPLACE FUNCTION public.search_juridical_translations_fts(
  query text,
  lim int DEFAULT 5
)
RETURNS TABLE (
  id                       uuid,
  juridical_text_id        uuid,
  language_code            text,
  translator_name          text,
  translation_source_work  text,
  translation_text         text,
  output_tier              text,
  page_start               integer,
  page_end                 integer,
  edition_label            text,
  rank                     real
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    jt.id,
    jt.juridical_text_id,
    jt.language_code,
    jt.translator_name,
    jt.translation_source_work,
    jt.translation_text,
    jt.output_tier,
    jt.page_start,
    jt.page_end,
    jt.edition_label,
    ts_rank(
      to_tsvector('english', jt.translation_text),
      websearch_to_tsquery('english', query)
    ) AS rank
  FROM public.juridical_translations jt
  WHERE to_tsvector('english', jt.translation_text)
        @@ websearch_to_tsquery('english', query)
  ORDER BY rank DESC
  LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION public.search_juridical_translations_fts(text, int) TO anon, authenticated;

COMMIT;
