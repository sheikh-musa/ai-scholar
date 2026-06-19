-- Adds human-scholar review flagging to mizan_interactions.
--
-- OPERATOR FEATURE REQUEST relayed via cc-orchestrator agent_messages #2746
-- (mizanbot scholar-review verification loop, v1). Religious answers must be
-- verifiable by a human scholar: ANY user can tap "🔖 Flag for scholar review"
-- under an answer (operator-confirmed scope — surface doubtful answers broadly),
-- and an admin-only /review command compiles the flagged Q&A into a spreadsheet
-- for a scholar to verify and tick off.
--
-- Columns (all additive; bool defaults false, the rest nullable):
--   flagged_for_review  bool NOT NULL DEFAULT false  — flag state (toggle on re-tap)
--   flagged_by          text                          — sha256(telegram_id) of the
--                                                        flagger (who, without a raw id)
--   flagged_at          timestamptz                   — when last flagged (cleared on unflag)
--   reviewer_note       text                          — v2 home for the scholar verdict
--                                                        loop (correct/nuance/wrong +
--                                                        correction). NOT built in v1
--                                                        (anti-takalluf) — column reserved
--                                                        so v2 has a landing spot.
--
-- Does NOT touch output_tier or any 4-tier-transparency invariant (T-1 holds:
-- output_tier stays NOT NULL CHECK). This is orthogonal review metadata only.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS). Additive — pre-update bot builds and
-- al-bayan omit these and rows keep their defaults. No backfill: historical
-- rows predate the flagging contract and legitimately carry the false default.

ALTER TABLE public.mizan_interactions
  ADD COLUMN IF NOT EXISTS flagged_for_review boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS flagged_by text,
  ADD COLUMN IF NOT EXISTS flagged_at timestamptz,
  ADD COLUMN IF NOT EXISTS reviewer_note text;

-- Partial index for the /review admin query — keeps the hot flagged subset
-- cheap to scan/order without indexing the whole table.
CREATE INDEX IF NOT EXISTS idx_mizan_interactions_flagged
  ON public.mizan_interactions (flagged_at DESC)
  WHERE flagged_for_review;
