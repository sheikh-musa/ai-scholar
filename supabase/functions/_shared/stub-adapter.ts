import type { LLMProvider, ComposeRequest } from "./compose-types.ts";

/**
 * Deterministic stub adapter — proves Constraint 3 (vendor-portability)
 * by demonstrating that ≤1 file diff plugs in a non-Anthropic provider.
 * Also used as test fixture so compose orchestration can be tested
 * without external network calls.
 *
 * Output format: concatenates first sentence of each passage with citation.
 * Designed to never trigger ayah-validator violations (passages-only echo).
 */
export class StubAdapter implements LLMProvider {
  readonly name = "stub";

  async generate(req: ComposeRequest): Promise<{ text: string; latency_ms: number }> {
    const start = Date.now();
    const lines: string[] = [];
    for (const p of req.passages.slice(0, 3)) {
      const firstSentence = p.english_text.split(/[.!?]/)[0]?.trim() ?? "";
      const cite = p.scholar_name ? `(${p.scholar_name})` : `(${p.passage_id})`;
      if (firstSentence) lines.push(`${firstSentence}. ${cite}`);
    }
    const text = lines.join(" ") || "Stub: no passages provided.";
    return { text, latency_ms: Date.now() - start };
  }
}
