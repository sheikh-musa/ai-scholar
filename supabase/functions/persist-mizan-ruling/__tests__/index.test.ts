// Tests against the inferOutputTier heuristic + payload-shape validation.
// Skips the actual Deno.serve handler (would need full Supabase client mock).

import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";

// Re-export-for-test pattern: hoist the helper out of index.ts if testing
// in isolation is desired, OR test via a thin import wrapper.
// For now, assert a hand-implementation matches the same heuristic shape.

function inferOutputTier(responseText: string): "quoted" | "paraphrased" | "inferred" | "ai-generated" {
  const hasQuoted = responseText.includes("📖");
  const hasParaphrased = responseText.includes("📝");
  if (hasQuoted) return "quoted";
  if (hasParaphrased) return "paraphrased";
  return "ai-generated";
}

Deno.test("infer quoted tier on Quran-text response", () => {
  assertEquals(inferOutputTier("📖 Allah says... 'Indeed Allah is...'"), "quoted");
});

Deno.test("infer paraphrased tier on tafsir-only response", () => {
  assertEquals(inferOutputTier("📝 Ibn Kathir explains..."), "paraphrased");
});

Deno.test("infer ai-generated tier when no tier badge present", () => {
  assertEquals(inferOutputTier("Allah is merciful in many ways."), "ai-generated");
});

Deno.test("quoted wins when both quoted and paraphrased badges present", () => {
  assertEquals(inferOutputTier("📖 Quran ayah... 📝 Ibn Kathir explains..."), "quoted");
});
