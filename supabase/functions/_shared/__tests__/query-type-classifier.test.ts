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
