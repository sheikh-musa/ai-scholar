-- AL-BAYAN-003-AMEND-ENGLISH-FIRST-002 (decision id 756, CAI-RESP-136 ruling)
-- Path B refined: new juridical_translations table FK to juridical_texts,
-- 1:N cardinality, supports multi-translator coexistence on same matn.
--
-- Apply timing: cc-scholar runs `supabase migration up` post window-close
-- (2026-05-08T01:32:09Z) OR with explicit Musa early-close consent. Do NOT
-- pre-apply.

BEGIN;

CREATE TABLE IF NOT EXISTS public.juridical_translations (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  juridical_text_id        uuid NOT NULL REFERENCES public.juridical_texts(id) ON DELETE CASCADE,
  language_code            text NOT NULL,
  translator_name          text NOT NULL,
  translation_source_work  text NOT NULL,
  translation_text         text NOT NULL,
  translation_text_sha256  text NOT NULL,
  output_tier              text NOT NULL CHECK (output_tier IN ('quoted','paraphrased')),
  page_start               integer,
  page_end                 integer,
  edition_label            text,
  ingestion_provenance_id  uuid NOT NULL REFERENCES public.ingestion_provenance(id) ON DELETE RESTRICT,
  created_at               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (juridical_text_id, language_code, translator_name, translation_source_work)
);

CREATE INDEX IF NOT EXISTS juridical_translations_text_lang_idx
  ON public.juridical_translations (juridical_text_id, language_code);

CREATE INDEX IF NOT EXISTS juridical_translations_translator_idx
  ON public.juridical_translations (translator_name);

ALTER TABLE public.juridical_translations ENABLE ROW LEVEL SECURITY;

CREATE POLICY juridical_translations_read ON public.juridical_translations
  FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY juridical_translations_service_all ON public.juridical_translations
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;
