-- AL-BAYAN-003 (decision id 568) — content_layer juridical corpus schema
--
-- Two new enums (dalil_strength_tier, madhab_label) + two new tables
-- (juridical_texts, ingestion_provenance). Multi-madhab schema from day
-- one per AL-BAYAN-003 constraint; v0.2 populates Shafi'i only but
-- Hanafi/Mālikī/Ḥanbalī additions need NO migration.
--
-- DO NOT APPLY until AL-BAYAN-003 challenge window closes
-- (2026-04-28 21:00 UTC) without challenge.
--
-- This migration ONLY ships schema. Data ingestion is a separate workstream
-- per docs/AL_BAYAN_003_PHASE_1_RUNBOOK.md (gates on operator source
-- verification — cc-scholar's WebFetch attempts on Wikisource AR 404'd).

BEGIN;

-- Per AL-BAYAN-003 dalil_strength tiers. NEVER 'binding_fatwa' — that
-- requires L7 living scholar (Q 16:43 fas'alū ahl al-dhikr — ask the
-- people of remembrance, not the texts directly).
DO $$ BEGIN
  CREATE TYPE public.dalil_strength_tier AS ENUM (
    'primer_juridical',     -- e.g. Safīnat al-Najā
    'standard_juridical',   -- e.g. Fath al-Mu'īn
    'spine_juridical'       -- e.g. Minhāj al-Ṭālibīn (Phase 3 deferred)
    -- NOT 'binding_fatwa' — see comment above
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Multi-madhab schema from day one per AL-BAYAN-003 — v0.2 populates
-- Shafi'i only but other madhahib do not need migration to add later.
DO $$ BEGIN
  CREATE TYPE public.madhab_label AS ENUM (
    'shafii', 'hanafi', 'maliki', 'hanbali'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Mandatory audit trail per AL-BAYAN-003 constraint. Every ingested text
-- gets a row here for source provenance + license declaration + SHA.
CREATE TABLE IF NOT EXISTS public.ingestion_provenance (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_url               text NOT NULL,
  source_maintainer        text NOT NULL,            -- 'al-Maktaba al-Shamela' / 'Wikisource AR' / 'KSU' / 'archive.org'
  license_declaration      text NOT NULL,            -- 'public domain' + reasoning
  ingestion_timestamp      timestamptz NOT NULL DEFAULT now(),
  source_file_sha256       text NOT NULL,            -- 64-char hex
  verified_by_identity     text NOT NULL,            -- 'musa' / '<scholar-name>' / 'cc-scholar'
  notes                    text
);

CREATE INDEX IF NOT EXISTS ingestion_provenance_source_idx
  ON public.ingestion_provenance (source_url);

ALTER TABLE public.ingestion_provenance ENABLE ROW LEVEL SECURITY;
CREATE POLICY ingestion_provenance_read ON public.ingestion_provenance
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY ingestion_provenance_service_all ON public.ingestion_provenance
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- juridical_texts — content_layer juridical (per LAYERING.md), NOT primary,
-- NOT tafsir-equivalent. Citation-rendering rule (AL-BAYAN-003 LOAD-BEARING
-- constraint) enforced at response-shape layer using these columns.
CREATE TABLE IF NOT EXISTS public.juridical_texts (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  text_name                text NOT NULL,                    -- e.g. 'Safīnat al-Najā'
  author_name              text NOT NULL,                    -- e.g. 'Sālim b. Sumayr al-Ḥaḍramī'
  author_death_hijri       integer,                          -- e.g. 1271
  author_death_gregorian   integer,                          -- e.g. 1855
  madhab                   public.madhab_label NOT NULL,
  dalil_strength           public.dalil_strength_tier NOT NULL,
  baab_or_section          text NOT NULL,                    -- e.g. 'Bāb al-Wuḍū''
  baab_order               integer NOT NULL,                 -- stable ordering within text
  arabic_text              text NOT NULL,                    -- the matn passage
  arabic_text_sha256       text NOT NULL,                    -- SHA-256 of NFC-normalized arabic_text
                                                              -- (per quranic-text-integrity Q-1 transposed)
  ingestion_provenance_id  uuid NOT NULL REFERENCES public.ingestion_provenance(id) ON DELETE RESTRICT,
  created_at               timestamptz NOT NULL DEFAULT now(),

  -- Per AL-BAYAN-003: never tier as binding_fatwa — guard via CHECK in case
  -- the enum gets extended in future
  CONSTRAINT juridical_texts_no_binding_fatwa CHECK (
    dalil_strength IN ('primer_juridical', 'standard_juridical', 'spine_juridical')
  )
);

CREATE INDEX IF NOT EXISTS juridical_texts_madhab_idx
  ON public.juridical_texts (madhab);
CREATE INDEX IF NOT EXISTS juridical_texts_text_baab_idx
  ON public.juridical_texts (text_name, baab_order);
CREATE INDEX IF NOT EXISTS juridical_texts_dalil_strength_idx
  ON public.juridical_texts (dalil_strength);

ALTER TABLE public.juridical_texts ENABLE ROW LEVEL SECURITY;
CREATE POLICY juridical_texts_read ON public.juridical_texts
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY juridical_texts_service_all ON public.juridical_texts
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Per AL-BAYAN-003: juridical_embeddings ships parallel to ayah_embeddings
-- when EMBED_PIPELINE_v02 backfill kicks off. Schema here is forward-
-- compatible — same dimension, same encoder, same RLS posture.
CREATE TABLE IF NOT EXISTS public.juridical_embeddings (
  juridical_text_id        uuid PRIMARY KEY REFERENCES public.juridical_texts(id) ON DELETE CASCADE,
  embedding                vector(1024),
  embedding_model          text NOT NULL,
  encoder_sha              text NOT NULL,
  corpus_version           text NOT NULL,
  embedded_source_hash     text NOT NULL,
  source_token_count       integer NOT NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS juridical_embeddings_hnsw_cosine
  ON public.juridical_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

ALTER TABLE public.juridical_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY juridical_embeddings_read ON public.juridical_embeddings
  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY juridical_embeddings_service_all ON public.juridical_embeddings
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Retrieval RPC for juridical-layer semantic search.
-- ACTIVATION GATE per AL-BAYAN-003: this function is callable by anon /
-- authenticated when migration applies, but ask-scholar Edge Function MUST
-- NOT call it until Quran retrieval is calibrated and retract-gate
-- unlocked (Phase E in EMBED_PIPELINE_v02 §migration-plan).
CREATE OR REPLACE FUNCTION public.search_juridical_semantic(
  query_embedding vector(1024),
  filter_madhab public.madhab_label DEFAULT NULL,
  lim int DEFAULT 10,
  threshold float DEFAULT 0.0
)
RETURNS TABLE (
  juridical_text_id        uuid,
  text_name                text,
  author_name              text,
  madhab                   public.madhab_label,
  dalil_strength           public.dalil_strength_tier,
  baab_or_section          text,
  arabic_text              text,
  similarity               real
)
LANGUAGE sql STABLE AS $$
  SELECT
    t.id            AS juridical_text_id,
    t.text_name,
    t.author_name,
    t.madhab,
    t.dalil_strength,
    t.baab_or_section,
    t.arabic_text,
    1 - (e.embedding <=> query_embedding) AS similarity
  FROM public.juridical_texts t
  JOIN public.juridical_embeddings e ON e.juridical_text_id = t.id
  WHERE 1 - (e.embedding <=> query_embedding) > threshold
    AND (filter_madhab IS NULL OR t.madhab = filter_madhab)
  ORDER BY e.embedding <=> query_embedding
  LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION public.search_juridical_semantic(vector, public.madhab_label, int, float)
  TO anon, authenticated;

COMMIT;
