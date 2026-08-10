// Quick sanity tests for the INV-6 classifier. Run with `deno test`.
// Expands into a proper eval harness under CAI-MIZAN-EVAL-002 later.

import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { classifyQueryType, requiresActionPrompt } from "../query-type-classifier.ts";

const cases: Array<[string, string]> = [
  ["Is it halal to pay interest on a student loan?",   "ruling"],
  ["Can I eat at a non-halal certified restaurant?",    "ruling"],
  ["Ruling on celebrating birthdays",                   "ruling"],
  // 2026-06-10: third-person obligation cases — were classified 'other'
  // because only first-person "must i" / "do i have to" were covered.
  ["Must a woman return her mahr if she initiated the divorce?", "ruling"],
  ["Does the husband have to pay for separate housing?",         "ruling"],
  ["Is she required to fast the missed days before next Ramadan?", "ruling"],
  ["Are they allowed to combine prayers while travelling?",        "ruling"],
  // 2026-07-05 mizan quality review (#6489): ruling-class queries carrying NO
  // explicit halal/haram/must vocabulary were falling to 'definition'/'other',
  // leaving the F-3 scholar-gate + INV-6 action_prompt dark (0 'ruling' across
  // 27 recent Qs). New intent classes: invalidation-of-ibadah, quantity-of-
  // obligation, intimacy-during-a-ritual-state, permissibility-defining consumables.
  ["do eyelash extensions prevent wudhu",              "ruling"],
  ["if i masbuk the friday prayer in tashahud do i pray 2 rakaats or 4", "ruling"],
  ["what are the intimacy limits with my wife when she is on her period", "ruling"],
  ["hadith on eating donkey meat",                     "ruling"],
  // Guards: ordinary food + non-consumption mentions must NOT become 'ruling'.
  ["hadith on eating dates",                           "other"],
  ["rivers of wine in paradise",                       "other"],

  ["What is the meaning of tawakkul?",                  "definition"],
  ["Define ijma",                                       "definition"],
  ["What is tawheed?",                                  "definition"],

  ["Who is Imam Shafi'i?",                              "biography"],
  ["Tell me about the companion Abu Bakr",              "biography"],
  // 2026-06-02: regression cases — madhhab founders share their names with
  // their schools, so the bare MADHHAB_PHRASES regex was false-positiving
  // on these. Fix: biography priority moved above madhhab-identification.
  ["Tell me about Imam al-Shafi'i",                     "biography"],
  ["Tell me about Imam Malik",                          "biography"],
  ["Who was Abu Hanifa?",                               "biography"],
  ["Tell me about Ibn Hanbal",                          "biography"],

  ["What does 'rahmah' mean in Arabic?",                "language-clarification"],
  ["How is 'bismillah' spelled?",                       "language-clarification"],
  ["What is the root of 'kitab'?",                      "language-clarification"],

  ["What do the Hanafis say about wiping over socks?",  "madhhab-identification"],
  ["Difference between Shafi'i and Hanafi on ablution", "madhhab-identification"],

  ["What does ayah 2:255 mean?",                        "tafsir"],
  ["Tafsir of Surah Al-Ikhlas",                         "tafsir"],
  ["Explain ayah 112:1",                                "tafsir"],

  ["Hello there",                                       "other"],
  ["Can you help?",                                     "other"],
];

Deno.test("classifyQueryType: expected types on anchor cases", () => {
  for (const [text, expected] of cases) {
    const { type } = classifyQueryType(text);
    assertEquals(type, expected, `"${text}" classified as ${type}, expected ${expected}`);
  }
});

Deno.test("requiresActionPrompt: INV-6 carve-out honored", () => {
  assertEquals(requiresActionPrompt("ruling"), true);
  assertEquals(requiresActionPrompt("tafsir"), true);       // not carved out; can shade ruling
  assertEquals(requiresActionPrompt("other"), true);        // not carved out by design
  assertEquals(requiresActionPrompt("definition"), false);
  assertEquals(requiresActionPrompt("biography"), false);
  assertEquals(requiresActionPrompt("language-clarification"), false);
  assertEquals(requiresActionPrompt("madhhab-identification"), false);
});

Deno.test("priority: ruling-class keywords win over definition shape", () => {
  const { type } = classifyQueryType("What is the ruling on insurance?");
  assertEquals(type, "ruling");
});

// ---------------------------------------------------------------------------
// FIQH-PRIMER-01 boundary (CAI-RESP-813 + amendment): the classifier must
// IMPLEMENT the confirmed boundary — enumeration=primer(definition),
// situational=F-3(ruling), AMBIGUITY defaults to F-3-gate. Ships WITH the
// primer corpus (§6.6 bundle). These are the eval-both-ways cases cai required.
// ---------------------------------------------------------------------------

// SAFETY-CRITICAL (under-gate): a situational / person-specific verdict must
// NEVER route to definition/primer — that would ship a quasi-fatwa. Adversarial
// set incl. near-misses of the enumeration form. ALL must be 'ruling'.
const SITUATIONAL_MUST_GATE: string[] = [
  "can a breastfeeding mother fast during ramadan",
  "can a breastfeeding mother fast during ramadan?",
  "can a nursing woman skip fasting",
  "can a pregnant woman skip fasting",
  "can a traveller shorten his prayer",
  "can a sick person combine prayers",
  "can a menstruating woman recite quran",
  // near-misses of the enumeration form — a SPECIFIC act or POSSESSIVE subject
  // makes it situational; must fall through to the F-3 fail-safe, not the primer:
  "does eyelash extension break the fast",
  "does coffee break the fast",
  "what breaks my fast if i brush my teeth",
  "what nullifies the fast if i swallow water while doing wudu",
];

Deno.test("boundary: situational verdicts NEVER reach the primer (adversarial, must gate)", () => {
  for (const q of SITUATIONAL_MUST_GATE) {
    const { type } = classifyQueryType(q);
    assertEquals(
      type,
      "ruling",
      `SAFETY: "${q}" -> ${type}; a situational verdict must route to ruling (F-3), never definition/primer`,
    );
  }
});

// UX (over-gate): bare enumerations of settled ruling-facts should reach the
// primer — i.e. route to 'definition' (INV-6-exempt, not F-3-gated).
const ENUMERATION_TO_PRIMER: string[] = [
  "what nullifies the fast",
  "what breaks the fast",
  "what nullifies wudu",
  "what invalidates wudu",
  "what breaks wudu",
  "nullifiers of fasting",
  "breakers of the fast",
  // already-correct Arabic noun-phrase forms — keep them green (guard):
  "mubtilat of sawm",
  "nawaqid of wudu",
  "arkan of wudu",
  "nisab of zakat",
];

Deno.test("boundary: bare enumerations route to the primer (definition)", () => {
  for (const q of ENUMERATION_TO_PRIMER) {
    const { type } = classifyQueryType(q);
    assertEquals(
      type,
      "definition",
      `"${q}" -> ${type}; a bare enumeration of settled facts should route to definition (primer)`,
    );
  }
});
