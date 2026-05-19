import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { classifyQueryType } from "../_shared/query-type-classifier.ts";
import {
  persistRulingEmission,
  type PersistRulingFields,
} from "../_shared/persist-ruling.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

if (!SUPABASE_SERVICE_ROLE_KEY) {
  // Hard-fail at boot rather than soft-fail on every request — service role
  // is the entire reason this function exists (RLS bypass on insert).
  throw new Error("SUPABASE_SERVICE_ROLE_KEY required for persist-mizan-ruling");
}

const persistClient = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

const PROMPT_VERSION = "mizan-bot-v1-2026-05-06";
const MODEL_NAME = "claude-cli-sonnet";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

/** SHA-256 hex of the input. */
async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Infer output_tier from response_text content.
 *
 * Heuristics (mizan_bot uses tier badges in the response per its prompt):
 *   - response contains 📖 (Quran/hadith verbatim) → quoted
 *   - response contains 📝 (paraphrased tafsir) → paraphrased
 *   - response contains 💭 (AI synthesis/framing) → ai-generated
 *   - else → ai-generated (conservative — mizan synthesizes by default)
 *
 * If multiple badges present, use the "narrowest" tier:
 *   quoted > paraphrased > inferred > ai-generated
 *
 * NOTE: This is a producer-side inference. The bot's prompt instructs the model
 * to use these badges; if it doesn't, we default to ai-generated rather than
 * silently picking "quoted" (which would be a worse failure mode).
 */
export function inferOutputTier(responseText: string): "quoted" | "paraphrased" | "inferred" | "ai-generated" {
  const hasQuoted = responseText.includes("📖");
  const hasParaphrased = responseText.includes("📝");
  const hasAIGen = responseText.includes("💭");
  if (hasQuoted) return "quoted";
  if (hasParaphrased) return "paraphrased";
  return "ai-generated";
}

interface PersistMizanRequest {
  telegram_id?: string | number;
  telegram_id_hash?: string;
  thread_id?: string;
  query_text: string;
  response_text: string;
  query_lang?: string;
  retrieval_ids?: string[];
  // F-2 (tafsir-defense-funnel): top tafsir-FTS hit's ayah_id when retrieval
  // included tafsir matches, else null. NEVER omitted from the audit row.
  matched_passage_id?: string | null;
  scholar_of_record?: string | null;
  retraction_of?: string | null;
}

async function resolveTelegramIdHash(body: PersistMizanRequest): Promise<string> {
  if (typeof body.telegram_id_hash === "string" && body.telegram_id_hash.length === 64) {
    return body.telegram_id_hash;
  }
  if (body.telegram_id !== undefined && body.telegram_id !== null) {
    return await sha256Hex(String(body.telegram_id));
  }
  return await sha256Hex("anonymous");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), {
      status: 405,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }

  let body: PersistMizanRequest;
  try {
    body = await req.json();
  } catch (_e) {
    return new Response(JSON.stringify({ error: "invalid json" }), {
      status: 400,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }

  if (!body.query_text || !body.response_text) {
    return new Response(JSON.stringify({ error: "query_text and response_text required" }), {
      status: 400,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }

  const telegram_id_hash = await resolveTelegramIdHash(body);
  const classification = classifyQueryType(body.query_text);
  const output_tier = inferOutputTier(body.response_text);

  const fields: PersistRulingFields = {
    telegram_id_hash,
    thread_id: body.thread_id ?? null,
    bot_variant: "al-mizan",
    query_type: classification.type,
    query_text: body.query_text,
    query_lang: body.query_lang,
    response_text: body.response_text,
    output_tier,
    retrieval_ids: body.retrieval_ids ?? [],
    matched_passage_id: body.matched_passage_id ?? null,
    scholar_of_record: body.scholar_of_record ?? null,
    model_name: MODEL_NAME,
    prompt_version: PROMPT_VERSION,
    retraction_of: body.retraction_of ?? null,
  };

  try {
    const result = await persistRulingEmission(persistClient, fields);
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error("persist-mizan-ruling failed:", msg, { query_type: classification.type, output_tier });
    return new Response(JSON.stringify({ error: "persistence failed", detail: msg }), {
      status: 500,
      headers: { ...CORS_HEADERS, "content-type": "application/json" },
    });
  }
});
