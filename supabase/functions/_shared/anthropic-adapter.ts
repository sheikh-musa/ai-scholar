import type { LLMProvider, ComposeRequest } from "./compose-types.ts";
import { COMPOSE_SYSTEM_PROMPT, buildComposeUserPrompt } from "./compose-prompt.ts";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_MODEL = "claude-sonnet-4-6";
const ANTHROPIC_VERSION = "2023-06-01";
const MAX_TOKENS = 800;
const TEMPERATURE = 0.3;

/**
 * AnthropicAdapter — Constraint 2 Satr posture: reads ANTHROPIC_API_KEY_ALBAYAN_COMPOSE
 * (dedicated key, not shared with other surfaces). Quarterly rotation per runbook.
 *
 * Uses direct fetch rather than @anthropic-ai/sdk to keep the Edge Function bundle
 * small and avoid import-time failures on cold starts. Trade-off: no automatic
 * retry/backoff. Acceptable because compose has 8s hard timeout that falls back
 * to retrieve-only — retries would only burn the timeout window.
 */
export class AnthropicAdapter implements LLMProvider {
  readonly name = "anthropic-claude-sonnet-4-6";
  private apiKey: string;

  constructor() {
    const key = Deno.env.get("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE");
    if (!key) {
      throw new Error("ANTHROPIC_API_KEY_ALBAYAN_COMPOSE not set in env (Constraint 2 Satr posture)");
    }
    this.apiKey = key;
  }

  async generate(req: ComposeRequest): Promise<{ text: string; latency_ms: number }> {
    const start = Date.now();
    const body = {
      model: ANTHROPIC_MODEL,
      max_tokens: MAX_TOKENS,
      temperature: TEMPERATURE,
      system: COMPOSE_SYSTEM_PROMPT,
      messages: [{ role: "user", content: buildComposeUserPrompt(req) }],
    };
    const response = await fetch(ANTHROPIC_API_URL, {
      method: "POST",
      headers: {
        "x-api-key": this.apiKey,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`Anthropic API error: ${response.status} ${await response.text()}`);
    }
    const data = await response.json();
    const text = data.content?.[0]?.text ?? "";
    return { text, latency_ms: Date.now() - start };
  }
}
