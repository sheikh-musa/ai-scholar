// Tests for inferOutputTier FLOOR semantics (4-tier-transparency T-3).
// The floor fix (msg #10510/#10515, commit d35c6a0) shipped without a unit test;
// this locks it. Run with `deno test`.
//
// FLOOR RULE: output_tier records the MOST-SYNTHETIC tier present, never the
// least. Priority (floor-first): ai-generated → paraphrased → quoted. A mixed
// body that quotes an ayah (📖) AND paraphrases tafsir (📝) is `paraphrased`,
// NOT `quoted` — under-tiering a synthesized answer as `quoted` under-reports
// synthesis to the audit chain / retract-gate / judge (op#5975: the live
// 'ayat kursi tafsir' reply persisted `quoted` while carrying 📝 tafsir).

import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { inferOutputTier, bodyHasAIGenerated } from "../output-tier.ts";

// [body, expectedTier, label]
const CASES: [string, string, string][] = [
  ['📖 "verbatim ayah" (2:255) — nothing else', "quoted", "pure quoted → quoted"],
  ['📖 "ayah" (2:255)\n\n📝 [Paraphrased: Ibn Kathir] explanation', "paraphrased",
    "MIXED quoted+paraphrased → paraphrased (FLOOR — the op#5975 regression)"],
  ["📝 [Paraphrased: Al-Sa'di] only paraphrased tafsir here", "paraphrased",
    "pure paraphrased → paraphrased"],
  ["💭 machine-translated matn with a 📖 quote and 📝 note", "ai-generated",
    "any AI-generated marker dominates the floor"],
  ["auto-translated matn, plus 📖 and 📝 badges", "ai-generated",
    "textual auto-translate marker → ai-generated even with 📖/📝 present"],
  ["a plain answer with no badge at all", "ai-generated",
    "no badge → ai-generated (conservative default: mizan synthesizes)"],
];

Deno.test("inferOutputTier — floor semantics (most-synthetic tier wins)", () => {
  for (const [body, expected, label] of CASES) {
    assertEquals(inferOutputTier(body), expected, label);
  }
});

Deno.test("bodyHasAIGenerated — emoji AND textual markers", () => {
  assertEquals(bodyHasAIGenerated("has 💭 badge"), true, "💭 badge");
  assertEquals(bodyHasAIGenerated("this is AI-generated content"), true, "ai-generated prose");
  assertEquals(bodyHasAIGenerated("auto-translated from Arabic"), true, "auto-translate prose");
  assertEquals(bodyHasAIGenerated("machine translation of the matn"), true, "machine-translate prose");
  assertEquals(bodyHasAIGenerated('📖 "quote" and 📝 paraphrase, no AI marker'), false, "quoted+paraphrased is not AI-generated");
});
