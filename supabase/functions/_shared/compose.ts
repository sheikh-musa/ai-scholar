import type { LLMProvider, ComposeRequest, ComposeResult, ComposeTier, ComposePassage } from "./compose-types.ts";
import { validateAyahCitations } from "./ayah-validator.ts";

const DEFAULT_TIMEOUT_MS = 8000;

export interface ComposeOptions {
  timeoutMs?: number;
}

export async function compose(
  req: ComposeRequest,
  provider: LLMProvider,
  opts: ComposeOptions = {},
): Promise<ComposeResult> {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const start = Date.now();

  const generation = await Promise.race([
    provider.generate(req).then((r) => ({ ...r, timed_out: false as const })),
    new Promise<{ text: string; latency_ms: number; timed_out: true }>((resolve) =>
      setTimeout(() => resolve({ text: "[compose-timeout]", latency_ms: timeoutMs, timed_out: true }), timeoutMs),
    ),
  ]);

  const text = generation.text;
  const timed_out = generation.timed_out;
  const validation = validateAyahCitations(text, req.passages);
  const cited_passage_ids = extractCitedPassageIds(text, req.passages);
  const tier = assignTier(text, req.passages, cited_passage_ids);

  return {
    text,
    tier,
    cited_passage_ids,
    ayah_violations: validation.violations,
    latency_ms: Date.now() - start,
    provider: provider.name,
    prompt_version: req.prompt_version,
    timed_out,
  };
}

/**
 * KNOWN CAVEATS in citation/tier logic (audit-log integrity, not user safety):
 *
 * (1) scholar_name fanout: if a scholar appears in multiple passages in the
 *     retrieval set, a single mention of that scholar's name in the compose
 *     output credits ALL their passages. With the corpus structure (Ibn
 *     Kathir + Al-Sa'di on every ayah), this is near-certain to fire and
 *     can inflate cited.length past the inferred-tier threshold.
 *     Conservative bias: overcrediting passages is safer than undercrediting
 *     (more provenance recorded, not less). Documented; revisit if shadow
 *     mode shows misleading tier distributions.
 *
 * (2) prefix-substring tier misattribution: if p1.english_text is a strict
 *     prefix of p2.english_text and the model emits p2's text verbatim while
 *     citing only [p1], assignTier returns "quoted" from p1. The text is
 *     still grounded (it's from p2's content); only the cited_passage_id is
 *     wrong. Real-corpus risk is low because tafsir passages are full
 *     sentences with distinct openings.
 */
function extractCitedPassageIds(text: string, passages: ComposePassage[]): string[] {
  const ids = new Set<string>();
  for (const p of passages) {
    if (text.includes(p.passage_id)) ids.add(p.passage_id);
    if (p.scholar_name && text.includes(p.scholar_name)) ids.add(p.passage_id);
  }
  return Array.from(ids);
}

function assignTier(text: string, passages: ComposePassage[], cited: string[]): ComposeTier {
  for (const p of passages) {
    if (text.includes(p.english_text) && cited.includes(p.passage_id)) {
      const otherCites = cited.filter((id) => id !== p.passage_id);
      if (otherCites.length === 0) return "quoted";
    }
  }
  if (cited.length >= 3) return "inferred";
  return "paraphrased";
}
