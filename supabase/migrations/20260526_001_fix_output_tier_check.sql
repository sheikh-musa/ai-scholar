-- Fix output_tier CHECK on juridical_translations + mizan_interactions
-- 2026-05-26 — discovered 2026-05-22 attempt to insert ai-generated tier:
--   ERROR 23514: violates check constraint "juridical_translations_output_tier_check"
--
-- Per CLAUDE.md T-1 invariant + 4-tier-transparency skill:
--   "Output tier NOT NULL (T-1): every output-bearing table has
--    output_tier text NOT NULL CHECK (output_tier IN
--    ('quoted','paraphrased','inferred','ai-generated'))"
--
-- The constraint as deployed was missing 'inferred' and 'ai-generated'
-- (only allowing 'quoted','paraphrased'), which silently blocked auto-
-- translated content from being filed under the correct tier.

BEGIN;

-- juridical_translations
ALTER TABLE public.juridical_translations
  DROP CONSTRAINT IF EXISTS juridical_translations_output_tier_check;

ALTER TABLE public.juridical_translations
  ADD CONSTRAINT juridical_translations_output_tier_check
  CHECK (output_tier IN ('quoted', 'paraphrased', 'inferred', 'ai-generated'));

COMMENT ON CONSTRAINT juridical_translations_output_tier_check
  ON public.juridical_translations IS
  'Per CLAUDE.md T-1 / 4-tier-transparency skill: output_tier must be one of '
  'quoted | paraphrased | inferred | ai-generated. ai-generated is used for '
  'machine-translated translations (e.g., the Nihāyat al-Zayn auto-translation '
  'via Claude Sonnet 2026-05-26).';

-- mizan_interactions — same invariant applies
ALTER TABLE public.mizan_interactions
  DROP CONSTRAINT IF EXISTS mizan_interactions_output_tier_check;

ALTER TABLE public.mizan_interactions
  ADD CONSTRAINT mizan_interactions_output_tier_check
  CHECK (output_tier IN ('quoted', 'paraphrased', 'inferred', 'ai-generated'));

COMMIT;
