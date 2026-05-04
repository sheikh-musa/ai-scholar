import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { validateAyahCitations } from "../ayah-validator.ts";

const PASSAGES = [
  { english_text: "The Throne Verse explains Allah's sovereignty.", arabic_text: "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ" },
];

Deno.test("compose output with no Arabic — passes", () => {
  const r = validateAyahCitations("Allah is the source of all power.", PASSAGES);
  assertEquals(r.valid, true);
  assertEquals(r.violations.length, 0);
});

Deno.test("compose output with Arabic that matches passage — passes", () => {
  const r = validateAyahCitations(
    "As Allah says: اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ — there is no god but He.",
    PASSAGES,
  );
  assertEquals(r.valid, true);
});

Deno.test("compose output with Arabic NOT in passages — fails", () => {
  const r = validateAyahCitations(
    "And Allah says: قُلْ هُوَ اللَّهُ أَحَدٌ — Say: He is Allah, the One.",
    PASSAGES,
  );
  assertEquals(r.valid, false);
  assertEquals(r.violations.length, 1);
});

Deno.test("compose output with Arabic differing only in NFC form — passes", () => {
  // U+0623 (ALEF WITH HAMZA ABOVE) decomposes to U+0627 + U+0654 in NFD.
  // Three Arabic words; passage in NFC, compose-text in NFD. Validator must
  // normalize both before substring match.
  const nfcArabic = "أللَّهُ لَا إِلَٰهَ"; // 3 words, NFC
  const nfdArabic = nfcArabic.normalize("NFD"); // decomposed form
  // Guard: forces fixture to be non-vacuous. If the chosen Arabic ever lacks
  // decomposable characters, this assertion fails loudly rather than the test
  // silently passing for the wrong reason.
  assertEquals(nfcArabic === nfdArabic, false);
  const passage = { english_text: "x", arabic_text: nfcArabic };
  const r = validateAyahCitations(`He said: ${nfdArabic} — and that is true.`, [passage]);
  assertEquals(r.valid, true);
  assertEquals(r.violations.length, 0);
});
