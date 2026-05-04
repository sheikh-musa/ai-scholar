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
    provider.generate(req),
    new Promise<{ text: string; latency_ms: number; timeout: true }>((resolve) =>
      setTimeout(() => resolve({ text: "[compose-timeout]", latency_ms: timeoutMs, timeout: true }), timeoutMs),
    ),
  ]);

  const text = generation.text;
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
  };
}

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
