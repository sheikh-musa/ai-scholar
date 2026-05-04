import { assertEquals, assertStringIncludes } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { compose } from "../compose.ts";
import { StubAdapter } from "../stub-adapter.ts";

const PASSAGES = [
  { passage_id: "p1", english_text: "Patience is a key Quranic theme.", scholar_name: "Ibn Kathir", output_tier: "paraphrased" as const },
  { passage_id: "p2", english_text: "Allah loves those who are patient.", scholar_name: "Al-Sa'di", output_tier: "paraphrased" as const },
];

Deno.test("compose with stub adapter — returns paraphrased tier and cited passages", async () => {
  const result = await compose(
    { query: "What does the Quran say about patience?", passages: PASSAGES, prompt_version: "test-v1" },
    new StubAdapter(),
  );
  assertEquals(result.tier, "paraphrased");
  assertEquals(result.ayah_violations.length, 0);
  assertEquals(result.cited_passage_ids.length >= 1, true);
});

Deno.test("compose times out — falls back with timeout marker", async () => {
  class SlowAdapter {
    name = "slow";
    async generate() {
      await new Promise((r) => setTimeout(r, 9000));
      return { text: "never reached", latency_ms: 9000 };
    }
  }
  const result = await compose(
    { query: "x", passages: PASSAGES, prompt_version: "test-v1" },
    new SlowAdapter() as any,
    { timeoutMs: 100 },
  );
  assertStringIncludes(result.text, "[compose-timeout]");
  assertEquals(result.tier, "paraphrased");
  assertEquals(result.timed_out, true);
});

Deno.test("tier rule — quoted iff verbatim substring of single passage", async () => {
  const verbatim = PASSAGES[0].english_text;
  class VerbatimAdapter {
    name = "verbatim";
    async generate() { return { text: verbatim + " [p1]", latency_ms: 5 }; }
  }
  const result = await compose(
    { query: "x", passages: PASSAGES, prompt_version: "test-v1" },
    new VerbatimAdapter() as any,
  );
  assertEquals(result.tier, "quoted");
});

Deno.test("tier rule — inferred when synthesizing across ≥3 passages", async () => {
  const threePassages = [
    ...PASSAGES,
    { passage_id: "p3", english_text: "Sabr means restraint of the soul.", scholar_name: "Al-Ghazali", output_tier: "paraphrased" as const },
  ];
  class TriAdapter {
    name = "tri";
    async generate() { return { text: "Combining themes from p1 and p2 and p3 — patience is a virtue.", latency_ms: 5 }; }
  }
  const result = await compose(
    { query: "x", passages: threePassages, prompt_version: "test-v1" },
    new TriAdapter() as any,
  );
  assertEquals(result.tier, "inferred");
});

Deno.test("compose populates ayah_violations when adapter emits Arabic not in passages", async () => {
  // Adapter fabricates a 3-word Arabic phrase (Surah Al-Ikhlas opening)
  // that is NOT present in any passage's arabic_text. The validator
  // should detect this and surface it in ayah_violations. compose() must
  // thread the violations through to the result.
  const fabricatedArabic = "قُلْ هُوَ اللَّهُ"; // 3-word run, not in PASSAGES
  class FabricatingAdapter {
    name = "fabricator";
    async generate() { return { text: `Allah is One — ${fabricatedArabic} — as revealed.`, latency_ms: 5 }; }
  }
  const passagesWithArabic = [
    { passage_id: "p1", english_text: "x", scholar_name: "Ibn Kathir", arabic_text: "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ", output_tier: "paraphrased" as const },
  ];
  const result = await compose(
    { query: "x", passages: passagesWithArabic, prompt_version: "test-v1" },
    new FabricatingAdapter() as any,
  );
  assertEquals(result.ayah_violations.length, 1);
  assertStringIncludes(result.ayah_violations[0], "قُلْ");
  assertEquals(result.timed_out, false);
});
