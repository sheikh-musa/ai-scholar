/**
 * AL-BAYAN-COMPOSE-001 Amendment 3 layer (b): post-generation ayah validation.
 *
 * Every Arabic ayah string detected in compose output must substring-match
 * Arabic text in the retrieved passages, NFC-normalized against KFGQPC
 * canonical (Q-1). On miss, the emission is rejected; ask-scholar falls
 * back to retrieve-only with 4-tier refusal.
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
    .join("\n");

  const violations: string[] = [];
  const composeNFC = nfc(composeText);
  const matches = composeNFC.match(ARABIC_RUN) ?? [];

  for (const m of matches) {
    if (!haystack.includes(m)) {
      violations.push(m);
    }
  }
  return { valid: violations.length === 0, violations };
}
