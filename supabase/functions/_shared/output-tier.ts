/**
 * output_tier inference for mizan_interactions (4-tier-transparency T-1/T-3).
 *
 * Extracted from persist-mizan-ruling/index.ts so it is dependency-free and
 * unit-testable outside Deno (no Deno.env / remote imports at module scope).
 *
 * FLOOR SEMANTICS (fix per cc-scholar 40-answer self-review, msg #10510):
 * On a MIXED body the single output_tier column records the MOST-SYNTHETIC
 * tier present, never the highest. Per 4-tier-transparency T-3, `ai-generated`
 * is the floor — a response that quotes an ayah (📖) AND surfaces a
 * machine-translated matn is `ai-generated` at the floor. The previous
 * heuristic returned `quoted` whenever a 📖 was present, so answers carrying an
 * AI-translated fiqh matn (e.g. review #35 "intimacy limits", #02 "asr timing")
 * were persisted as `quoted` — under-reporting synthesis and misleading any
 * downstream consumer (audit chain, retract-gate, judge, analytics) that trusts
 * output_tier. This raises disclosed synthesis; it never lowers it (tightening).
 */
export type OutputTier = "quoted" | "paraphrased" | "inferred" | "ai-generated";

/**
 * True when the body contains AI-generated / machine-translated content.
 *
 * Detects both the inline 💭 badge AND textual tier markers, because the
 * AI-translated matn passages (Nihāyat al-Zayn / Mukhtaṣar al-Qudūrī via
 * OpenITI + Claude auto-translation) are frequently labelled in prose
 * ("tier: AI-generated translation", "auto-translated", "machine translation")
 * WITHOUT the 💭 emoji — which is exactly how #35 evaded the old emoji-only check.
 */
export function bodyHasAIGenerated(responseText: string): boolean {
  if (responseText.includes("💭")) return true;
  return /\bai[-\s]?generated\b/i.test(responseText)
    || /\bauto[-\s]?translat/i.test(responseText)
    || /\bmachine[-\s]?translat/i.test(responseText)
    || /\bClaude(-|\s)(sonnet|cli|auto)/i.test(responseText);
}

/**
 * Infer output_tier as the FLOOR (most-synthetic tier present).
 *
 * Priority (floor-first): ai-generated → paraphrased → quoted.
 * Default `ai-generated` when no badge/marker is present (conservative — mizan
 * synthesizes by default; a silent "quoted" default would be the worse failure).
 *
 * `inferred` is intentionally not emitted by this heuristic: the badge scheme
 * has no distinct 'inferred' marker, so multi-source synthesis lands in
 * `ai-generated` (floor), which is the honest conservative choice.
 */
export function inferOutputTier(responseText: string): OutputTier {
  if (bodyHasAIGenerated(responseText)) return "ai-generated";
  if (responseText.includes("📝")) return "paraphrased";
  if (responseText.includes("📖")) return "quoted";
  return "ai-generated";
}
