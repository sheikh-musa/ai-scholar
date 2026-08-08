// al-bayan-bot / index.ts
//
// Al-Bayān Telegram *webhook* receiver (INV: egress-reroute durable fix, op#11306).
// Replaces the long-poll bot (scripts/mizan_bot.py / albayan_bot.py) whose
// getUpdates long-poll black-holed on the Studio->Telegram idle-socket drop
// (docs/BAYAN-EGRESS-REROUTE-SCOPE.md). Telegram *pushes* updates here over
// Supabase's always-on ingress, removing the idle-long-poll failure mode and
// making Bayān independent of any host's uptime.
//
// This is a THIN adapter — every scholar invariant (F-1..F-6, T-1..T-6) and
// mizan_interactions persistence is inherited from ask-scholar. See handler.ts.
//
// Required function secrets (set via `supabase secrets set` before deploy):
//   TELEGRAM_BOT_TOKEN     — @mzninterfacebot token (or MIZAN_BOT_TOKEN fallback)
//   BAYAN_WEBHOOK_SECRET   — must equal the secret_token passed to setWebhook
// Auto-injected by Supabase: SUPABASE_URL, SUPABASE_ANON_KEY.
//
// setWebhook (deploy step, HELD pending operator go):
//   curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
//     -d url="https://<ref>.supabase.co/functions/v1/al-bayan-bot" \
//     -d secret_token="<BAYAN_WEBHOOK_SECRET>" \
//     -d allowed_updates='["message"]'

import { AskScholarResponse, handleUpdate, TelegramUpdate } from "./handler.ts";

const BOT_TOKEN =
  Deno.env.get("TELEGRAM_BOT_TOKEN") || Deno.env.get("MIZAN_BOT_TOKEN") || "";
const WEBHOOK_SECRET = Deno.env.get("BAYAN_WEBHOOK_SECRET") || "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") || "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") || "";
const ASK_SCHOLAR_URL = `${SUPABASE_URL}/functions/v1/ask-scholar`;
const TELEGRAM_API = `https://api.telegram.org/bot${BOT_TOKEN}`;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-telegram-bot-api-secret-token",
};

async function callAskScholar(
  query: string,
  chatId: number | string
): Promise<AskScholarResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const resp = await fetch(ASK_SCHOLAR_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        query,
        telegram_id: String(chatId),
        chat_id: String(chatId),
        bot_variant: "al-bayan",
      }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`ask-scholar HTTP ${resp.status}`);
    }
    return (await resp.json()) as AskScholarResponse;
  } finally {
    clearTimeout(timer);
  }
}

async function tgRequest(method: string, data: Record<string, unknown>): Promise<void> {
  const resp = await fetch(`${TELEGRAM_API}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  // Telegram returns 200 with {ok:false} on logical errors — surface for logging.
  if (!resp.ok) {
    throw new Error(`Telegram ${method} HTTP ${resp.status}`);
  }
  const body = await resp.json().catch(() => ({}));
  if (body && body.ok === false) {
    throw new Error(`Telegram ${method} ok=false: ${JSON.stringify(body).slice(0, 200)}`);
  }
}

async function sendMessage(
  chatId: number | string,
  text: string,
  parseMode?: "Markdown"
): Promise<void> {
  const truncated = text.length > 4000 ? text.slice(0, 4000) + "..." : text;
  const payload: Record<string, unknown> = {
    chat_id: chatId,
    text: truncated,
    disable_web_page_preview: true,
  };
  if (parseMode) payload.parse_mode = parseMode;
  try {
    await tgRequest("sendMessage", payload);
  } catch (e) {
    console.error("sendMessage failed:", e instanceof Error ? e.message : e);
  }
}

async function sendTyping(chatId: number | string): Promise<void> {
  await tgRequest("sendChatAction", { chat_id: chatId, action: "typing" });
}

// deno-lint-ignore no-explicit-any
const edgeRuntime = (globalThis as any).EdgeRuntime;

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed. Use POST." }), {
      status: 405,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }

  // Telegram secret-token validation. When BAYAN_WEBHOOK_SECRET is configured,
  // reject anything whose header does not match (spoof / misconfig surfaces
  // loudly during the supervised cutover). When unset, process but warn — lets a
  // first deploy be smoke-tested before the secret is wired.
  const gotSecret = req.headers.get("x-telegram-bot-api-secret-token") || "";
  if (WEBHOOK_SECRET) {
    if (gotSecret !== WEBHOOK_SECRET) {
      return new Response("unauthorized", { status: 401, headers: CORS_HEADERS });
    }
  } else {
    console.warn("BAYAN_WEBHOOK_SECRET not set — webhook is UNAUTHENTICATED");
  }

  let update: TelegramUpdate;
  try {
    update = (await req.json()) as TelegramUpdate;
  } catch {
    // Not JSON — ack so Telegram does not retry, but do nothing.
    return new Response("ok", { headers: CORS_HEADERS });
  }

  const work = handleUpdate(update, {
    callAskScholar,
    sendMessage,
    sendTyping,
    log: (m) => console.log(m),
  });

  // Fast-ack pattern: return 200 immediately and finish processing in the
  // background so a slow ask-scholar call never makes Telegram retry (which
  // would double-answer). Falls back to awaiting inline where waitUntil is
  // unavailable (e.g. local `deno test`).
  if (edgeRuntime && typeof edgeRuntime.waitUntil === "function") {
    edgeRuntime.waitUntil(work.catch((e: unknown) => console.error("handleUpdate:", e)));
  } else {
    await work.catch((e: unknown) => console.error("handleUpdate:", e));
  }

  return new Response("ok", { headers: CORS_HEADERS });
});
