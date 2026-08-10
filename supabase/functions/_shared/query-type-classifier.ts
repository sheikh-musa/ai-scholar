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
  // FIQH-PRIMER-01 under-gate fix (CAI-RESP-813 amendment, SAFETY-CRITICAL):
  // "can a <descriptor> <person> <worship act>" is a situational/person-specific
  // permissibility verdict and MUST route to ruling (F-3), never escape to
  // 'other' and thus reach the primer. The line-below `can a (muslim|woman|...)`
  // set omitted descriptor-prefixed subjects ("breastfeeding mother", "nursing
  // woman", "traveller", "sick person"), so these were classified 'other'
  // (not F-3-gated). This catches any "can a <up to 3 words> <permissibility
  // verb>". Enumerations never start "can a", so no over-gate risk.
  /can\s+an?\s+[\w'-]+(?:\s+[\w'-]+){0,2}\s+(fast|pray|prey|marry|divorc\w*|combin\w*|shorten|qasr|jama|wear|eat|drink|trade|sell|buy|invest|listen|watch|use|touch|hold|kiss|recit\w*|delay|skip|miss|join|give|take|travel|wipe|attend|lead|perform|make\s+up)\b/i,
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

  // 2026-07-05 mizan quality review (#6489): ruling-class queries carrying NO
  // explicit halal/haram/must vocabulary were classified 'definition'/'other',
  // leaving the F-3 scholar-gate + INV-6 action_prompt DARK (0 'ruling' across
  // 27 recent Qs). These target the intent classes the keyword + first-person
  // patterns miss. Ruling keeps top priority, so they also win over the greedy
  // DEFINITION /^what (is|are) .../ pattern that was swallowing "what are the
  // intimacy limits ..." into 'definition'.
  // (a) Validity / invalidation of an act of worship ("do eyelash extensions
  //     prevent wudhu", "does X break the fast", "is my wudu valid if ...").
  /\b(prevent|invalidat|nullif|break|breaks|voids?|annul|dissolve|violate|spoil)\w*\b[^?.]{0,45}\b(wudu|wudhu|wudoo|ablution|salah|salat|solat|prayer|fast(ing)?|sawm|saum|siyam|ghusl|tayammum|hajj|umrah|i'?tikaf)\b/i,
  /\b(wudu|wudhu|ablution|salah|salat|solat|prayer|fast(ing)?|sawm|ghusl|hajj)\b[^?.]{0,45}\b(valid|invalid|nullified|broken|void|counts?|acceptable|still\s+count)\b/i,
  // (b) Quantity of an obligation ("do i pray 2 rakaats or 4", "how many rakaat").
  /\bhow\s+many\s+(rak'?ah|rakah|rakat|raka'?at|rakaat|times)\b/i,
  /\bdo\s+i\s+(pray|fast|repeat|make\s+up|perform)\b[^?.]{0,30}\b(rak'?ah|rakah|rakat|rakaat|\d)\b/i,
  /\b\d\s+or\s+\d\b[^?.]{0,20}\b(rak'?ah|rakah|rakat|rakaat)\b/i,
  // (c) Marital-intimacy boundaries tied to a ritual state (menses/nifas/ihram/fast).
  /\b(intimacy|intimate|touch(ing)?|sex(ual)?|relations|conjugal|marital|foreplay)\b[^?.]{0,55}\b(period|menstruat\w*|menses|haid|hayd|hayz|nifas|ihram|fasting|while\s+fast)\b/i,
  /\b(period|menstruat\w*|menses|haid|hayd|hayz|nifas)\b[^?.]{0,55}\b(intimacy|intimate|touch(ing)?|sex(ual)?|relations|conjugal|marital)\b/i,
  /\b(limits?|boundar(y|ies)|rules?|conditions?)\b[^?.]{0,20}\b(of|on|for|to|with|during|when)\b[^?.]{0,45}\b(intimacy|sex|touch|fast\w*|prayer|wudu|menstruat\w*|period|ihram|nikah|marriage)\b/i,
  // (d) Canonically permissibility-defining consumables ("hadith on eating
  //     donkey meat"). Scoped to a closed set of prohibition-defining items +
  //     an adjacent consumption verb, so ordinary food queries ("hadith on
  //     eating dates") stay 'other' and "rivers of wine in Paradise" does not fire.
  /\b(eat\w*|drink\w*|consum\w*|meat\s+of|flesh\s+of|slaughter\w*)\b[^?.]{0,25}\b(donkey|mule|pork|swine|pig|khinzir|khamr|alcohol|wine|liquor|carrion|maytah|maitah|dog|predator|reptile|frog|crocodile|blood)\b/i,
  /\b(donkey|pork|swine|khinzir|khamr|alcohol|carrion|maytah)\b[^?.]{0,25}\b(halal|haram|permissible|forbidden|allowed|eat\w*|meat|flesh)\b/i,

  // ----- cc-scholar 40-answer self-review additions (msg #10510) -----
  // Validity-of-my-own-act: "is my wudu valid", "is my asr (prayed 5 min before
  // maghrib) valid", "was my prayer correct/complete". The generic
  // /is\s+it\s+(...valid...)/ above only caught the bare pronoun "it"; users
  // routinely ask about a possessed act ("is MY asar ... valid") — ruling-class
  // (a personal-consequence verdict is sought). Window is generous (.{0,60})
  // because users interpose the circumstances ("prayed 5 minutes before maghrib").
  /\b(is|was)\s+(my|his|her|their|our|the|this|that|a|an)\b.{0,60}?\b(valid|invalid|correct|acceptable|accepted|complete|incomplete|sufficient|enough|broken|nullified|voided|void)\b/i,
  // Mubtilat / nawaqid question — does X nullify/break/invalidate/void/prevent an
  // act of worship. Ruling-class regardless of grammatical subject. Was 'other'
  // for #15 ("do eyelash extensions prevent wudhu") and #37 ("does it nullify my
  // fast to hold a non mahram's hands").
  /\b(nullif|invalidat|breaks?|breaking|voids?|voiding|cancel(s|ling|ing)?|prevent(s|ing)?|affects?\s+(my|the)|invalid)\b.{0,40}?\b(wudu|wuduʾ|wudhu|ghusl|tayammum|salah|salat|solat|prayer|fast|fasting|sawm|siyam|saum|tahara|taharah|purity|ablution|nikah|marriage|hajj|umrah)\b/i,
  /\bdoes\s+(it|this|that|.{0,30}?)\s+(nullify|invalidate|break|void|cancel|prevent|count|affect)\b/i,
  // "can i <worship/permissibility verb>" — extend the verb set (incl. the common
  // misspelling prey→pray) so worship-permission questions route to ruling not
  // 'other'. Was 'other' for #13/#14 ("can i prey non stop").
  /can\s+i\s+(get\s+)?(marr|divorc|combine|shorten|qasr|jama|wear|eat|drink|trade|sell|buy|invest|listen|watch|use|pray|prey|fast|touch|hold|kiss|recite|delay|skip|miss|join|make\s+up)/i,
  // Rakaat-count of an obligatory prayer — "do i pray 2 rakaats or 4",
  // "how many rakaats do i pray". Was 'other' for #19 (masbuk Jumu'ah).
  /\b(do\s+i\s+pray|how\s+many\s+rak)\b.{0,20}?(\d|rak)/i,
  // Marital-intimacy / menstruation permissibility — sensitive ruling-class. The
  // definitional "what are the ... limits" phrasing otherwise captured #35 as
  // 'definition' (a marital-relations verdict tagged as a vocabulary lookup).
  /\b(intimacy|intimate|touch(ing)?|kiss(ing)?|relations?|be\s+with|sleep\s+with|contact)\b.{0,30}?\b(wife|husband|spouse|non[-\s]?mahram|mahram)\b/i,
  /\b(menstruat|hayd|haid|nifas|istihadah|on\s+(her|my)\s+period|during\s+(her|my)\s+period|while\s+(she|i)\s+(is|am)\s+menstruat)\b/i,
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
  /tell\s+me\s+about\s+(the\s+)?(imam|sheikh|shaykh|companion|sahabi|sahaba|tabi)/i,
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

// FIQH-PRIMER-01 over-gate fix (CAI-RESP-813 amendment). A BARE enumeration of
// the settled nawaqid/mubtilat of an act of worship ("what breaks the fast",
// "nullifiers of fasting") is definition-class and should reach the primer —
// but the nawaqid RULING regexes (F-3) were swallowing it. This carve-out is
// TIGHTLY anchored (^...$, generic ibadah object only, NO personal/possessive
// subject and NO specific act) so it is PROVABLY not situational: any query
// with a specific act ("does eyelash extension break the fast") or possessive
// ("what breaks MY fast if ...") or trailing clause fails the anchor and falls
// through to the ruling-first flow. Per the amendment's HARD RULE, ambiguity
// defaults to F-3-gate — so this only fires on the unambiguous bare form.
const _IBADAH =
  "(?:fast|fasting|sawm|siyam|wudu|wudhu|wudoo|ablution|ghusl|salah|salat|solat|prayer|tayammum|hajj|umrah)";
const BARE_ENUMERATION = new RegExp(
  `^(?:what|which)\\s+(?:are\\s+the\\s+)?(?:things?\\s+that\\s+)?` +
    `(?:nullif\\w*|invalidat\\w*|break\\w*|void\\w*|annul\\w*|cancel\\w*|mubtil\\w*|mufsid\\w*|naqid\\w*|nawaqid)\\s+` +
    `(?:the\\s+|a\\s+)?${_IBADAH}\\s*\\??$` +
    `|^(?:the\\s+)?(?:nullifiers?|invalidators?|breakers?|voiders?|cancellers?|mubtilat|mufsidat|nawaqid)\\s+` +
    `(?:of\\s+)?(?:the\\s+)?${_IBADAH}\\s*\\??$`,
  "i",
);

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

  // FIQH-PRIMER-01 over-gate carve-out — checked BEFORE ruling so a BARE, tightly
  // anchored enumeration ("what breaks the fast", "nullifiers of fasting") reaches
  // the primer as 'definition'. Provably not situational (see BARE_ENUMERATION);
  // anything ambiguous fails the anchor and falls through to the ruling-first
  // fail-safe below. Ordering exception is deliberate and bounded.
  if (BARE_ENUMERATION.test(text)) {
    return { type: "definition", confidence: "high", matched: ["definition:bare-enumeration"] };
  }

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
