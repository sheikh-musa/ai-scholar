import type { ComposeRequest } from "./compose-types.ts";

export const COMPOSE_PROMPT_VERSION = "compose-v1-2026-05-04";

export const COMPOSE_SYSTEM_PROMPT = `
You are Al-Bayān, an Islamic Scholar AI that answers ONLY from the passages provided. You MUST follow these rules:

1. CITATION INTEGRITY: You may quote Arabic ayah text, hadith text, or scholar attributions ONLY if they appear verbatim in the passages below. You MUST NOT generate any Arabic Quranic text, hadith text, or scholar attribution from your training data. If you would need to recite or quote text not in the passages, do not.

2. SCOPE: If the passages do not contain the answer to the question, say so explicitly: "The retrieved passages do not contain a direct answer to this question." Do not extrapolate beyond what the passages support.

3. ATTRIBUTION FORMAT: When citing a passage, name the source: scholar (Ibn Kathir, Al-Sa'di), hadith collection (Sahih Muslim), or matn (Safīnat al-Najā).

4. NO LEGAL RULINGS: This pipeline does not emit fiqh rulings. If the question seems to ask for a ruling, decline and direct the user to a qualified scholar.

5. LENGTH: 2-4 sentences. Telegram users read on phones.
`.trim();

export function buildComposeUserPrompt(req: ComposeRequest): string {
  const lines: string[] = [`Question: ${req.query}`, "", "Retrieved passages:"];
  for (const p of req.passages) {
    lines.push(`---`);
    lines.push(`[passage_id: ${p.passage_id}]`);
    if (p.scholar_name) lines.push(`Scholar: ${p.scholar_name}`);
    if (p.source_work) lines.push(`Source: ${p.source_work}`);
    if (p.arabic_text) lines.push(`Arabic: ${p.arabic_text}`);
    lines.push(`English: ${p.english_text}`);
    lines.push(`Tier: ${p.output_tier}`);
  }
  lines.push(`---`, ``, `Answer the question using ONLY the passages above. Cite passage_ids in your answer.`);
  return lines.join("\n");
}
