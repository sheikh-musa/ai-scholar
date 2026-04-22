/**
 * Query-type classifier for INV-6 'ilm→'amal CI gate carve-out.
 *
 * Per VISION-003 INV-6 (as amended by CAI-RESP-062): the action_prompt
 * requirement fires ONLY on query_type === "ruling". For definition,
 * biography, language-clarification, and madhhab-identification queries,
 * action_prompt is explicitly null (not a fabricated pad).
 *
 * Used by:
 *  - supabase/functions/ask-scholar/index.ts (Edge Function)
 *  - scripts/mizan_bot.py via the Edge Function response shape
 *  - 4-tier-transparency skill T-4 classifier surface
 */

export type QueryType =
  | "ruling"
  | "definition"
  | "biography"
  | "language-clarification"
  | "madhhab-identification"
  | "tafsir"
  | "other";

export interface ClassificationResult {
  type: QueryType;
  confidence: "high" | "medium" | "low";
  matched: string[]; // which patterns fired (for audit + debugging)
}

// ---------------------------------------------------------------------------
// Pattern tables
// ---------------------------------------------------------------------------

const RULING_KEYWORDS = new Set([
  "halal", "haram", "permissible", "allowed", "forbidden",
  "fard", "wajib", "makruh", "mustahab", "fatwa", "ruling",
  "obligatory", "sinful", "bid'ah", "sunnah",
]);

const RULING_PHRASES = [
  /is\s+it\s+(halal|haram|permissible|allowed|forbidden)\s+to/i,
  /can\s+i\s+.+\s+in\s+islam/i,
  /ruling\s+on/i,
  /is\s+it\s+ok(ay)?\s+to/i,
  /am\s+i\s+allowed\s+to/i,
  /do\s+i\s+have\s+to/i,
  /what\s+is\s+the\s+punishment\s+for/i,
  /must\s+i/i,
  /is\s+it\s+permissible/i,
];

const DEFINITION_PHRASES = [
  /^what\s+(is|are)\s+(the\s+)?(meaning\s+of\s+)?[a-z؀-ۿ\s'"-]+\??$/i,
  /^(what\s+does|meaning\s+of)\s+[a-z؀-ۿ\s'"-]+\??$/i,
  /define\s+[a-z؀-ۿ\s'"-]+/i,
  /^explain\s+(the\s+term|the\s+word|the\s+concept)/i,
];

const BIOGRAPHY_PHRASES = [
  /^who\s+(is|was|were)\s+(imam\s+|sheikh\s+|shaykh\s+)?[a-z؀-ۿ'"\s-]+\??$/i,
  /biography\s+of/i,
  /tell\s+me\s+about\s+(imam|sheikh|shaykh|companion|sahabi|tabi)/i,
];

const LANGUAGE_PHRASES = [
  /^(how\s+do\s+you\s+say|translate|translation\s+of)\s+/i,
  /what\s+does\s+['"]?[a-z؀-ۿ'"\s-]+['"]?\s+mean\s+in\s+arabic/i,
  /^how\s+is\s+['"]?[a-z؀-ۿ'"\s-]+['"]?\s+(written|spelled|pronounced)/i,
  /(root|morphology|grammar)\s+of\s+[a-z؀-ۿ'"\s-]+/i,
  /what\s+is\s+the\s+(root|jizm|jazm|i'rab)\s+/i,
];

const MADHHAB_PHRASES = [
  /(shafi|hanafi|maliki|hanbali|ja'fari)/i,
  /which\s+madh(a|e)b/i,
  /difference\s+between\s+(shafi|hanafi|maliki|hanbali)/i,
  /what\s+do\s+(the\s+)?(shafi|hanafi|maliki|hanbali)s?\s+say/i,
];

const TAFSIR_PHRASES = [
  /tafsir\s+(of|on)/i,
  /what\s+does\s+(this|that)\s+(ayah|verse)\s+(mean|say|teach)/i,
  /meaning\s+of\s+(surah|ayah|verse)/i,
  /explain\s+(surah|ayah)\s+\d+/i,
  /\[?\d+:\d+\]?/,          // surah:ayah notation
  /surah\s+\w+\s+(ayah|verse)/i,
];

// ---------------------------------------------------------------------------
// Core classifier
// ---------------------------------------------------------------------------

/**
 * Classify a user query into one of the INV-6 types.
 *
 * Priority when multiple patterns match:
 *   ruling > tafsir > madhhab-identification > language-clarification >
 *   biography > definition > other
 *
 * This priority encodes that "amanah risk" rises toward ruling — if we're
 * unsure between ruling and definition, we prefer the stricter classification
 * so the INV-6 gate fires and the action_prompt requirement holds.
 */
export function classifyQueryType(text: string): ClassificationResult {
  const matched: string[] = [];
  const lower = text.toLowerCase();
  const tokens = lower.split(/\s+/);

  const hasRulingKeyword = tokens.some((t) => RULING_KEYWORDS.has(t.replace(/[?.,!'"]/g, "")));
  if (hasRulingKeyword) matched.push("ruling:keyword");
  for (const p of RULING_PHRASES) {
    if (p.test(text)) matched.push(`ruling:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("ruling:"))) {
    return { type: "ruling", confidence: matched.length > 1 ? "high" : "medium", matched };
  }

  for (const p of TAFSIR_PHRASES) {
    if (p.test(text)) matched.push(`tafsir:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("tafsir:"))) {
    return { type: "tafsir", confidence: "high", matched };
  }

  for (const p of MADHHAB_PHRASES) {
    if (p.test(text)) matched.push(`madhhab:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("madhhab:"))) {
    return { type: "madhhab-identification", confidence: "high", matched };
  }

  for (const p of LANGUAGE_PHRASES) {
    if (p.test(text)) matched.push(`language:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("language:"))) {
    return { type: "language-clarification", confidence: "high", matched };
  }

  for (const p of BIOGRAPHY_PHRASES) {
    if (p.test(text)) matched.push(`biography:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("biography:"))) {
    return { type: "biography", confidence: "high", matched };
  }

  for (const p of DEFINITION_PHRASES) {
    if (p.test(text)) matched.push(`definition:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("definition:"))) {
    return { type: "definition", confidence: "medium", matched };
  }

  return { type: "other", confidence: "low", matched };
}

// ---------------------------------------------------------------------------
// INV-6 gate
// ---------------------------------------------------------------------------

const INV6_EXEMPT: ReadonlySet<QueryType> = new Set([
  "definition",
  "biography",
  "language-clarification",
  "madhhab-identification",
]);

/**
 * Returns true iff an action_prompt is required on this query type.
 * Per CAI-RESP-062, ruling queries require action_prompt; the listed
 * exempt types explicitly do NOT require one (action_prompt === null).
 * Tafsir and "other" still require action_prompt because they can
 * shade into ruling-class content.
 */
export function requiresActionPrompt(type: QueryType): boolean {
  return !INV6_EXEMPT.has(type);
}
