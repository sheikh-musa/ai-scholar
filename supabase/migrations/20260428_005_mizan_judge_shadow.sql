-- MIZAN-JUDGE-SHADOW-001 (system_layer L2 retrieval-substrate measurement)
--
-- Shadow-mode logging table for the mizan_judge pipeline running over
-- fused (semantic + FTS) retrieval candidates BEFORE retract-gate
-- unlock cutover.
--
-- Per CAI-RESP-094 Q10 HARD GATE: the existing judge calibrated against
-- FTS-only retrieval is structurally blind to semantic-only failure modes
-- (e.g., Mu'tazili tafsir on a content_layer interpretive item surfacing
-- where Ash'ari grounding is required). Shipping retract-unlock on
-- uncalibrated judge IS the ulama-su' failure in production. Sequenced
-- gate: shadow → diff audit → gold-set augment (50-200 human-labeled
-- items per AL-BAYAN-003 extension) → recalibrate → unlock.
--
-- This table captures shadow-mode runs so the diff audit (step iii) has
-- mechanically-comparable data: same query, two retrieval surfaces, same
-- judge, score deltas inspected.
--
-- Filed because: ARCH-AL-BAYAN-ENCODER-EVAL + EMBED_PIPELINE_v02 backfill
-- need this table to exist before they can write shadow scores.
--
-- Layering terminology per docs/LAYERING.md (ARCH-AL-BAYAN-LAYERING-RECONCILE):
--   - This migration provisions infrastructure for system_layer L2
--     (retrieval substrate measurement)
--   - The candidate sets it logs reference content_layer primary (ayat)
--     and content_layer interpretive (tafsir_entries). Once juridical
--     retrieval activates per AL-BAYAN-003 Phase E, content_layer juridical
--     references will also appear in candidate_set jsonb.

BEGIN;

CREATE TABLE IF NOT EXISTS mizan_judge_shadow (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  -- The interaction being scored (links back to the user-facing emission)
  interaction_id           uuid NOT NULL REFERENCES mizan_interactions(id) ON DELETE RESTRICT,

  -- Which retrieval surface produced the candidates this judge run scored
  retrieval_mode           text NOT NULL
    CHECK (retrieval_mode IN ('fts_only', 'semantic_only', 'fused_rrf')),

  -- Identifies the encoder + corpus version when retrieval_mode includes semantic
  -- Null for retrieval_mode='fts_only'
  encoder_sha              text,
  corpus_version           text,

  -- Identifies the RRF parameters when retrieval_mode='fused_rrf'
  -- e.g., {"k": 60, "fts_top_n": 50, "semantic_top_n": 50}
  -- Null for non-fused modes
  rrf_params               jsonb,

  -- The retrieved candidate set the judge actually scored
  -- Array of {ayah_id, source ('fts'|'semantic'|'both'), rank, similarity}
  candidate_set            jsonb NOT NULL,

  -- Standard 8-axis judge scores (mirrors mizan_auto_scores schema)
  judge_model              text NOT NULL,
  judge_prompt_version     text NOT NULL,
  tier_integrity           smallint NOT NULL CHECK (tier_integrity BETWEEN 0 AND 5),
  source_attribution       smallint NOT NULL CHECK (source_attribution BETWEEN 0 AND 5),
  scholar_humility         smallint NOT NULL CHECK (scholar_humility BETWEEN 0 AND 5),
  ikhtilaf_surface         smallint NOT NULL CHECK (ikhtilaf_surface BETWEEN 0 AND 5),
  ilm_amal_link            smallint NOT NULL CHECK (ilm_amal_link BETWEEN 0 AND 5),
  fitnah_avoidance         smallint NOT NULL CHECK (fitnah_avoidance BETWEEN 0 AND 5),
  hallucination            smallint NOT NULL CHECK (hallucination BETWEEN 0 AND 5),
  aqeedah_integrity        smallint NOT NULL CHECK (aqeedah_integrity BETWEEN 0 AND 5),
  composite_score          numeric(4,2),
  auto_flagged             boolean NOT NULL DEFAULT false,
  judge_rationale          text,

  -- Diff-audit support: did this shadow score produce a different verdict than the prod
  -- (FTS-only) score? Populated by audit step, not the writer.
  diff_vs_prod_verdict     text
    CHECK (diff_vs_prod_verdict IN ('same', 'shadow_stricter', 'shadow_lenient', 'shadow_only_flag', 'prod_only_flag', NULL)),

  created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX mizan_judge_shadow_interaction_idx ON mizan_judge_shadow (interaction_id);
CREATE INDEX mizan_judge_shadow_mode_idx ON mizan_judge_shadow (retrieval_mode);
CREATE INDEX mizan_judge_shadow_flagged_idx ON mizan_judge_shadow (auto_flagged) WHERE auto_flagged = true;
CREATE INDEX mizan_judge_shadow_created_idx ON mizan_judge_shadow (created_at DESC);

-- Apply same hallucination >= 1 → auto_flag rule as production scores
CREATE OR REPLACE FUNCTION mizan_judge_shadow_flag_hallucination()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.hallucination >= 1 THEN
    NEW.auto_flagged := true;
  END IF;
  RETURN NEW;
END; $$;

CREATE TRIGGER mizan_judge_shadow_flag_hallucination_trg
  BEFORE INSERT ON mizan_judge_shadow
  FOR EACH ROW EXECUTE FUNCTION mizan_judge_shadow_flag_hallucination();

ALTER TABLE mizan_judge_shadow ENABLE ROW LEVEL SECURITY;

-- service_role writes; super_admin reads (same pattern as mizan_human_reviews)
CREATE POLICY mizan_judge_shadow_service_all ON mizan_judge_shadow
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY mizan_judge_shadow_admin_read ON mizan_judge_shadow
  FOR SELECT TO authenticated
  USING (auth.jwt() ->> 'role' IN ('scholar', 'super_admin'));

COMMIT;
