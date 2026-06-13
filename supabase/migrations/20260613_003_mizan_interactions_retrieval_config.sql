-- Adds retrieval_config to the mizan_interactions audit row.
--
-- Authorized by CAI-RESP-220 (the "A" leg): "stamp retrieval config
-- (limit/cap/reranker version/path) into the evidence-audit record for
-- reproducibility." APPLY only after the RESP-220 challenge window closes
-- (2026-06-13T22:41:23Z), alongside 20260613_002.
--
-- The column holds the dict returned by fiqh_semantic._retrieval_meta():
--   { retriever, path (rpc|bruteforce|none), rerank, limit,
--     max_per_text_id, gate_min_score }
-- threaded through mizan_bot.RetrievalMeta.retrieval_config →
-- persist_emission → persist-mizan-ruling Edge Function → persistRulingEmission.
--
-- Reproducibility metadata only — deliberately NOT folded into the INV-8
-- content_hash (see persist-ruling.ts canonicalContent note): the config is
-- deployment-deterministic and recoverable from retriever version + git, so
-- binding it into the per-row hash chain would add lockstep audit-verify
-- coupling for no integrity gain.
--
-- Nullable + additive: pre-update callers (al-bayan, older mizan_bot builds)
-- omit the field and the column stays NULL. No backfill — historical rows
-- predate the config-stamp contract and legitimately have no value.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS.

BEGIN;

ALTER TABLE public.mizan_interactions
  ADD COLUMN IF NOT EXISTS retrieval_config jsonb;

COMMENT ON COLUMN public.mizan_interactions.retrieval_config IS
  'CAI-RESP-220: retrieval-substrate config (retriever version / path / reranker / limit / max_per_text_id / gate) for the evidence set in retrieval_ids. Reproducibility metadata; intentionally excluded from the ruling_audit_log content_hash.';

COMMIT;
