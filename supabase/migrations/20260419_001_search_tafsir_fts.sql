-- Phase 1 — Tafsir FTS RPC
-- Adds a GIN index on tafsir_entries.english_text and an RPC that
-- returns ayah-joined matches ranked by ts_rank. Excludes rows whose
-- english_text begins with "[Arabic tafsir" (no-translation placeholder).

CREATE INDEX IF NOT EXISTS idx_tafsir_entries_english_fts
  ON tafsir_entries
  USING GIN (to_tsvector('english', english_text));

CREATE OR REPLACE FUNCTION search_tafsir_fts(query text, lim int DEFAULT 5)
RETURNS TABLE (
  ayah_id              uuid,
  surah_number         int,
  ayah_number          int,
  arabic_text          text,
  english_translation  text,
  translator           text,
  scholar_name         text,
  source_work          text,
  english_text         text,
  output_tier          text,
  rank                 real
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    a.id            AS ayah_id,
    a.surah_number,
    a.ayah_number,
    a.arabic_text,
    a.english_translation,
    a.translator,
    t.scholar_name,
    t.source_work,
    t.english_text,
    t.output_tier,
    ts_rank(
      to_tsvector('english', t.english_text),
      websearch_to_tsquery('english', query)
    ) AS rank
  FROM tafsir_entries t
  JOIN ayat a ON a.id = t.ayah_id
  WHERE to_tsvector('english', t.english_text)
        @@ websearch_to_tsquery('english', query)
    AND t.english_text NOT LIKE '[Arabic tafsir%'
  ORDER BY rank DESC
  LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION search_tafsir_fts(text, int) TO anon, authenticated;
