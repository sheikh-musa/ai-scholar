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
  // Third-person obligation: the bare "must i" / "do i have to" patterns above
  // only catch first-person phrasing. Users routinely ask the verdict about a
  // third party — "must a woman return her mahr", "does the husband have to
  // pay", "is she required to fast". These are ruling-class (a personal
  // consequence is being sought) and were classified 'other' pre-2026-06-10.
  /\bmust\s+(i|we|you|she|he|they|one|a|an|the|every|each|both|either)\b/i,
  /\b(she|he|they|one|a\s+\w+|an\s+\w+|the\s+\w+)\s+(has\s+to|have\s+to|needs?\s+to|is\s+(required|obliged|obligated|entitled|allowed|permitted)\s+to|are\s+(required|obliged|obligated|entitled|allowed|permitted)\s+to)\b/i,
  // Inverted-question obligation: "is she required to", "are they allowed to",
  // "does he have to" — auxiliary precedes the third-person subject.
  /\b(is|are|does|do|was|were)\s+(i|we|you|she|he|they|one|a|an|the|every|each)\b.{0,30}?\b(required|obliged|obligated|entitled|allowed|permitted|supposed|expected|have\s+to|has\s+to|need(s)?\s+to)\s+to?\b/i,
  // Broader "can/should I ..." patterns without requiring "in Islam" suffix
  // (added 2026-05-27 after self-test showed "can i marry a non-muslim" classified as 'other')
  /can\s+i\s+(get\s+)?(marr|divorc|combine|wear|eat|drink|trade|sell|buy|invest|listen|watch|use)/i,
  /can\s+a\s+(muslim|woman|man|wife|husband|child|believer|mu'?min|mu?slim)/i,
  /should\s+i\s+(do|perform|fast|pray|give|take|stop|avoid|continue|repeat|combine|shorten)/i,
  /is\s+it\s+(required|necessary|enough|sufficient|valid|invalid)/i,
  // Direct "is X haram/halal" with the predicate-form (not just preceded by "to")
  /^(is|are)\s+\S+(\s+\S+)*\s+(halal|haram|permissible|forbidden|allowed)\b/i,
];

const DEFINITION_PHRASES = [
  /^what\s+(is|are)\s+(the\s+)?(meaning\s+of\s+)?[a-z؀-ۿ\s'"-]+\??$/i,
  /^(what\s+does|meaning\s+of)\s+[a-z؀-ۿ\s'"-]+\??$/i,
  /define\s+[a-z؀-ۿ\s'"-]+/i,
  /^explain\s+(the\s+term|the\s+word|the\s+concept)/i,
  // Compact fiqh-vocab queries: "rukun solat", "wajibat of sawm", "arkan of wudu",
  // "fard of ghusl", "shurut of salah", "nullifiers of fasting" — Malay/Arabic-transliteration
  // noun phrases that are definitional in nature. Added 2026-05-27 after self-test showed
  // these classified as 'other'.
  /^(rukn|rukun|arkan|wajib|wajibat|wajibate|fard|fardu|furud|furudh|farudh|sunan|mubtilat|mufsidat|nawaqid|nullifi|invalid|shart|shurut|aqsam|sifat|asnaf|maqasid)\b/i,
  /\b(of|al-|ul-|li|fi)\s+(salah|salat|solat|sawm|siyam|saum|zakat|zakah|hajj|wudu|wuduʾ|ghusl|tayammum|taharah)\b/i,
];

const BIOGRAPHY_PHRASES = [
  /^who\s+(is|was|were)\s+(imam\s+|sheikh\s+|shaykh\s+)?[a-z؀-ۿ'"\s-]+\??$/i,
  /biography\s+of/i,
  /tell\s+me\s+about\s+(imam|sheikh|shaykh|companion|sahabi|tabi)/i,
  // Arabic-name prefixes (Ibn/Abu/Al-/Umm/Abd/Hafiz/etc.) without requiring imam/sheikh title
  // (added 2026-05-27 after self-test showed "tell me about ibn taymiyyah" classified as 'other')
  /tell\s+me\s+about\s+(ibn|abu|al-|umm|abd|ʿabd|hafiz|sayyid|sayyida|mulla|allamah|allama|ustadh|ustaz|hadrat|h\.\s)/i,
  /^who\s+(is|was|were)\s+(ibn|abu|al-|umm|abd|hafiz|sayyid|mulla|allamah|ustadh|hadrat)\s+/i,
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
 *   ruling > tafsir > biography > madhhab-identification >
 *   language-clarification > definition > other
 *
 * Biography precedes madhhab-identification (2026-06-02 fix) because
 * madhhab founders share their names with their schools, and the bare
 * MADHHAB_PHRASES regex would false-positive on "Imam al-Shāfiʿī".
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

  // Biography checked BEFORE madhhab-identification (2026-06-02). Madhhab
  // founders share their names with their schools (Imam al-Shāfiʿī ↔ Shafi'i
  // school; Imam Mālik ↔ Maliki; Abū Ḥanīfa ↔ Hanafi; Ibn Ḥanbal ↔ Hanbali),
  // and the bare MADHHAB_PHRASES regex /(shafi|hanafi|...)/i was firing on
  // the FOUNDER's name when the user clearly asked for a biography. The fix:
  // biographical patterns ("tell me about Imam X", "who was X") are explicit
  // signals of intent; if they fire, the query is a bio regardless of whether
  // the imam's name overlaps with a school name. Comparison queries like
  // "what do the Hanafis say" or "Shafi'i vs Hanafi" do NOT match biography
  // patterns, so madhhab-identification still wins for those.
  for (const p of BIOGRAPHY_PHRASES) {
    if (p.test(text)) matched.push(`biography:${p.source.slice(0, 40)}`);
  }
  if (matched.some((m) => m.startsWith("biography:"))) {
    return { type: "biography", confidence: "high", matched };
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
