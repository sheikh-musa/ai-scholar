import { assertEquals, assertRejects } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { AnthropicAdapter } from "../anthropic-adapter.ts";

Deno.test("AnthropicAdapter throws when env key missing", () => {
  const original = Deno.env.get("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE");
  Deno.env.delete("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE");
  try {
    let threw = false;
    try { new AnthropicAdapter(); } catch (_e) { threw = true; }
    assertEquals(threw, true);
  } finally {
    if (original) Deno.env.set("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE", original);
  }
});

Deno.test("AnthropicAdapter posts to /v1/messages with temp=0.3", async () => {
  Deno.env.set("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE", "test-key");
  let captured: { url: string; body: any } | null = null;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (url: any, init: any) => {
    captured = { url: String(url), body: JSON.parse(init.body) };
    return new Response(JSON.stringify({ content: [{ type: "text", text: "ok" }] }), { status: 200 });
  }) as any;
  try {
    const adapter = new AnthropicAdapter();
    const result = await adapter.generate({
      query: "q",
      passages: [{ passage_id: "p1", english_text: "x", output_tier: "paraphrased" }],
      prompt_version: "test",
    });
    assertEquals(result.text, "ok");
    assertEquals(captured!.body.temperature, 0.3);
    assertEquals(captured!.url.includes("api.anthropic.com"), true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
