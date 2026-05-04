/**
 * AL-BAYAN-COMPOSE-001 Amendment 3 layer (b): post-generation ayah validation.
 *
 * Every Arabic ayah string detected in compose output must substring-match
 * Arabic text in the retrieved passages, NFC-normalized against KFGQPC
 * canonical (Q-1). On miss, the emission is rejected; ask-scholar falls
 * back to retrieve-only with 4-tier refusal.
 */

/**
 * Arabic-run detector — matches sequences of ≥3 whitespace-separated Arabic
 * tokens spanning core Arabic + Supplement + Extended-A + Presentation Forms-A/B
 * Unicode blocks.
 *
 * KNOWN GAP: 1- and 2-word Quranic ayat (e.g., الْحَاقَّةُ from Surah 69:1,
 * الطَّامَّةُ from 79:34) are NOT detected by this regex. The threshold
 * exists to avoid false-positives on transliterated names and single Arabic
 * terms, but it is structurally under-strict on short ayat. Deferred to a
 * follow-up plan amendment that pairs this with an ayah-text dictionary
 * lookup keyed on the corpus.
 */
const ARABIC_RUN = /[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+(?:\s+[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+){2,}/g;

function nfc(s: string): string {
  return s.normalize("NFC");
}

export interface ValidationResult {
  valid: boolean;
  violations: string[];
}

export function validateAyahCitations(
  composeText: string,
  passages: { arabic_text?: string }[],
): ValidationResult {
  const haystack = passages
    .map((p) => p.arabic_text ? nfc(p.arabic_text) : "")
    .filter((s) => s.length > 0)
    .join(" ");

  const composeNFC = nfc(composeText);
  const matches = composeNFC.match(ARABIC_RUN) ?? [];

  const seen = new Set<string>();
  const violations: string[] = [];
  for (const m of matches) {
    if (!haystack.includes(m) && !seen.has(m)) {
      seen.add(m);
      violations.push(m);
    }
  }
  return { valid: violations.length === 0, violations };
}
