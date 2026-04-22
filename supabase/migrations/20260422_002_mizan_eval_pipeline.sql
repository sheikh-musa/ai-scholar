-- MIZAN-EVAL-001 evaluation pipeline (as amended by CAI-RESP-062)
--
-- Ships Phase 0 (log every interaction) + Phase 1 (LLM-as-judge auto-scoring)
-- + Phase 2 (CAI human review queue) + Phase 3 (eval set growth).
--
-- Retract-block amendment: NO retract DM emitted until judge-human agreement
-- vs ≥30-item scholar gold set is documented in mizan_eval_runs. Flagged
-- interactions queue silently for CAI review; no user-facing corrections until
-- EVAL-002 self-audit lands.
--
-- Madhab-pluralism amendment: judge prompt declares madhab-awareness; rubric
-- accepts madhab-pluralism as valid. Shafi'i-default narrowed to default-
-- recommendation-selection only (see judge prompt versioning in eval_runs).

BEGIN;

-- ---------------------------------------------------------------------------
-- Table 1: mizan_interactions — every query → response audit row
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mizan_interactions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_id_hash   text NOT NULL,              -- SHA-256 of telegram user id (no PII, per MIZAN-EVAL-001 constraint)
  thread_id          uuid,                       -- conversation grouping

  bot_variant        text NOT NULL               -- 'al-bayan' | 'al-mizan' (per CAI-RESP-048 two-bot arch)
    CHECK (bot_variant IN ('al-bayan','al-mizan')),

  query_type         text NOT NULL               -- see 4-tier-transparency skill, T-4
    CHECK (query_type IN ('ruling','definition','biography','language-clarification','madhhab-identification','tafsir','other')),

  query_text         text NOT NULL,
  query_lang         text NOT NULL DEFAULT 'en',

  response_text      text NOT NULL,
  output_tier        text NOT NULL               -- 4-tier-transparency T-1
    CHECK (output_tier IN ('quoted','paraphrased','inferred','ai-generated')),
  matched_passage_id uuid,                       -- reference to tafsir_entries or null
  retrieval_ids      uuid[] NOT NULL DEFAULT '{}',
  scholar_of_record  text,                       -- null if AI-generated, named if scholar-paired

  model_name         text NOT NULL,              -- 'claude-opus-4-7' etc.
  prompt_version     text NOT NULL,              -- pinned per MIZAN-EVAL-001 reproducibility constraint

  retraction_of      uuid REFERENCES mizan_interactions(id),  -- 4-tier-transparency T-6: retraction is a new row

  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON mizan_interactions (telegram_id_hash);
CREATE INDEX ON mizan_interactions (created_at DESC);
CREATE INDEX ON mizan_interactions (query_type);
CREATE INDEX ON mizan_interactions (output_tier);

-- ---------------------------------------------------------------------------
-- Table 2: mizan_user_feedback — user flag / rating on an interaction
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mizan_user_feedback (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  interaction_id    uuid NOT NULL REFERENCES mizan_interactions(id) ON DELETE RESTRICT,
  telegram_id_hash  text NOT NULL,
  rating            smallint CHECK (rating BETWEEN 1 AND 5),
  flag              text CHECK (flag IN ('incorrect','misattributed','hallucinated','offensive','other')),
  comment           text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON mizan_user_feedback (interaction_id);

-- ---------------------------------------------------------------------------
-- Table 3: mizan_auto_scores — LLM-as-judge 8-axis scores
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mizan_auto_scores (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  interaction_id           uuid NOT NULL REFERENCES mizan_interactions(id) ON DELETE RESTRICT,
  judge_model              text NOT NULL,             -- 'claude-opus-4-7'
  judge_prompt_version     text NOT NULL,             -- versioned prompt per MIZAN-EVAL-001

  -- 8 axes per CAI-MIZAN-EVAL-001 rubric, 0–5 each
  tier_integrity           smallint NOT NULL CHECK (tier_integrity BETWEEN 0 AND 5),
  source_attribution       smallint NOT NULL CHECK (source_attribution BETWEEN 0 AND 5),
  scholar_humility         smallint NOT NULL CHECK (scholar_humility BETWEEN 0 AND 5),
  ikhtilaf_surface         smallint NOT NULL CHECK (ikhtilaf_surface BETWEEN 0 AND 5),
  ilm_amal_link            smallint NOT NULL CHECK (ilm_amal_link BETWEEN 0 AND 5),
  fitnah_avoidance         smallint NOT NULL CHECK (fitnah_avoidance BETWEEN 0 AND 5),
  hallucination            smallint NOT NULL CHECK (hallucination BETWEEN 0 AND 5),   -- 0 = none, 5 = severe
  aqeedah_integrity        smallint NOT NULL CHECK (aqeedah_integrity BETWEEN 0 AND 5),

  composite_score          numeric(4,2),              -- derived; nullable while formula stabilizes
  auto_flagged             boolean NOT NULL DEFAULT false,  -- true iff hallucination ≥ 1 per MIZAN-EVAL-001
  judge_rationale          text,

  created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON mizan_auto_scores (interaction_id);
CREATE INDEX ON mizan_auto_scores (auto_flagged) WHERE auto_flagged = true;

-- Automatic flag rule: hallucination ≥ 1 triggers auto_flag regardless of composite
CREATE OR REPLACE FUNCTION mizan_auto_flag_hallucination()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.hallucination >= 1 THEN
    NEW.auto_flagged := true;
  END IF;
  RETURN NEW;
END; $$;

CREATE TRIGGER mizan_auto_scores_flag_hallucination
  BEFORE INSERT ON mizan_auto_scores
  FOR EACH ROW EXECUTE FUNCTION mizan_auto_flag_hallucination();

-- ---------------------------------------------------------------------------
-- Table 4: mizan_human_reviews — CAI/scholar retract verdicts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mizan_human_reviews (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  interaction_id    uuid NOT NULL REFERENCES mizan_interactions(id) ON DELETE RESTRICT,
  reviewer          text NOT NULL,                -- 'cai' | '<scholar-of-record-name>'
  verdict           text NOT NULL CHECK (verdict IN ('ok','minor-correction','retract','escalate')),
  correction_text   text,                         -- used on 'minor-correction' / 'retract'
  rationale         text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON mizan_human_reviews (interaction_id);
CREATE INDEX ON mizan_human_reviews (verdict);

-- ---------------------------------------------------------------------------
-- Table 5: mizan_eval_set + mizan_eval_runs — gold set + runs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mizan_eval_set (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provenance          text NOT NULL,               -- 'corrected-from-flagged' | 'curated-by-cai' | 'scholar-authored'
  source_interaction  uuid REFERENCES mizan_interactions(id),
  query_text          text NOT NULL,
  expected_tier       text NOT NULL CHECK (expected_tier IN ('quoted','paraphrased','inferred','ai-generated')),
  expected_answer     text NOT NULL,
  scholar_grader      text,                         -- filled on scholar-graded items
  scholar_grade       smallint CHECK (scholar_grade BETWEEN 1 AND 5),
  active              boolean NOT NULL DEFAULT true,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mizan_eval_runs (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_model          text NOT NULL,
  candidate_prompt_version text NOT NULL,
  judge_model              text NOT NULL,
  judge_prompt_version     text NOT NULL,
  gold_set_size            integer NOT NULL,            -- rows sampled from mizan_eval_set where active=true
  judge_human_agreement    numeric(4,3),                -- 0.000–1.000; REQUIRED ≥ threshold to unlock retract-DM (see below)
  composite_summary        jsonb,                       -- per-axis mean + std
  notes                    text,
  created_at               timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RETRACT-BLOCK CONSTRAINT (CAI-RESP-062 amendment, P1)
-- ---------------------------------------------------------------------------

-- Hard rule: no retract DM to user until judge-human agreement is documented
-- against ≥30-item scholar gold set. Enforced at DB level via a config-table
-- + trigger pair that blocks insertion of user-facing retraction rows while
-- the gate is closed.

CREATE TABLE IF NOT EXISTS mizan_retract_gate (
  id                          smallint PRIMARY KEY DEFAULT 1,
  unlocked                    boolean NOT NULL DEFAULT false,
  unlocked_at                 timestamptz,
  unlocked_by_run_id          uuid REFERENCES mizan_eval_runs(id),
  minimum_gold_set_size       integer NOT NULL DEFAULT 30,
  minimum_judge_human_agreement numeric(4,3) NOT NULL DEFAULT 0.800,
  CONSTRAINT mizan_retract_gate_singleton CHECK (id = 1)
);

INSERT INTO mizan_retract_gate (id, unlocked) VALUES (1, false)
  ON CONFLICT DO NOTHING;

-- Function + trigger: retract interactions (retraction_of IS NOT NULL) only
-- insertable when the gate is unlocked. Flagged interactions still flow
-- to mizan_auto_scores and mizan_human_reviews silently.
CREATE OR REPLACE FUNCTION mizan_retract_block()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  g_unlocked boolean;
BEGIN
  IF NEW.retraction_of IS NOT NULL THEN
    SELECT unlocked INTO g_unlocked FROM mizan_retract_gate WHERE id = 1;
    IF NOT g_unlocked THEN
      RAISE EXCEPTION 'mizan_retract_gate closed: judge-human agreement not yet documented per MIZAN-EVAL-001 amendment (CAI-RESP-062). Cannot insert user-facing retraction.'
        USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END; $$;

CREATE TRIGGER mizan_interactions_retract_block
  BEFORE INSERT ON mizan_interactions
  FOR EACH ROW EXECUTE FUNCTION mizan_retract_block();

-- Unlock procedure: call AFTER a successful eval run satisfies the thresholds.
-- Procedure checks the gate config against the run, and only unlocks if both
-- satisfied. Manual override is deliberately unavailable.
CREATE OR REPLACE FUNCTION mizan_unlock_retract_gate(run_id uuid)
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
  r           mizan_eval_runs%ROWTYPE;
  g           mizan_retract_gate%ROWTYPE;
BEGIN
  SELECT * INTO r FROM mizan_eval_runs WHERE id = run_id;
  SELECT * INTO g FROM mizan_retract_gate WHERE id = 1;

  IF r.gold_set_size < g.minimum_gold_set_size THEN
    RETURN false;
  END IF;
  IF r.judge_human_agreement IS NULL OR r.judge_human_agreement < g.minimum_judge_human_agreement THEN
    RETURN false;
  END IF;

  UPDATE mizan_retract_gate
    SET unlocked = true, unlocked_at = now(), unlocked_by_run_id = run_id
    WHERE id = 1;
  RETURN true;
END; $$;

-- ---------------------------------------------------------------------------
-- RLS — scholar-role + super-admin only on reviews; users own their feedback
-- ---------------------------------------------------------------------------

ALTER TABLE mizan_interactions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_user_feedback     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_auto_scores       ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_human_reviews     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_eval_set          ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_eval_runs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE mizan_retract_gate      ENABLE ROW LEVEL SECURITY;

-- Service role only for interactions/auto_scores writes; read by super-admin
CREATE POLICY mizan_interactions_service_all ON mizan_interactions
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY mizan_auto_scores_service_all ON mizan_auto_scores
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- User feedback: users can insert their own; read own only
CREATE POLICY mizan_user_feedback_insert_own ON mizan_user_feedback
  FOR INSERT TO authenticated
  WITH CHECK (telegram_id_hash = (auth.jwt() ->> 'telegram_id_hash'));

CREATE POLICY mizan_user_feedback_read_own ON mizan_user_feedback
  FOR SELECT TO authenticated
  USING (telegram_id_hash = (auth.jwt() ->> 'telegram_id_hash'));

-- Human reviews: scholar-role + super-admin only (no anon / authenticated read)
CREATE POLICY mizan_human_reviews_scholar_read ON mizan_human_reviews
  FOR SELECT TO authenticated
  USING (auth.jwt() ->> 'role' IN ('scholar','super_admin'));

CREATE POLICY mizan_human_reviews_scholar_write ON mizan_human_reviews
  FOR INSERT TO authenticated
  WITH CHECK (auth.jwt() ->> 'role' IN ('scholar','super_admin'));

-- Eval set + runs: super-admin only
CREATE POLICY mizan_eval_set_admin ON mizan_eval_set
  FOR ALL TO authenticated
  USING (auth.jwt() ->> 'role' = 'super_admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'super_admin');

CREATE POLICY mizan_eval_runs_admin ON mizan_eval_runs
  FOR ALL TO authenticated
  USING (auth.jwt() ->> 'role' = 'super_admin')
  WITH CHECK (auth.jwt() ->> 'role' = 'super_admin');

-- Retract gate: read-only to authenticated, write via procedure only
CREATE POLICY mizan_retract_gate_read ON mizan_retract_gate
  FOR SELECT TO authenticated USING (true);

COMMIT;
