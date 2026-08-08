# al-bayan-bot — Al-Bayān Telegram webhook receiver

Durable fix for the recurring getUpdates wedge (op#10339 / op#11306,
`docs/BAYAN-EGRESS-REROUTE-SCOPE.md`). The Studio→Telegram NAT path black-holed
idle long-poll sockets; Telegram now **pushes** updates to this always-on
Supabase endpoint instead, removing the idle-long-poll failure mode and making
Bayān independent of any host's uptime.

## Design — thin adapter, zero invariant duplication

This receiver only: validates the Telegram secret → formats a tiered reply →
`sendMessage`. **All** scholar logic is inherited from the `ask-scholar` Edge
Function, exactly as the poll bot `scripts/albayan_bot.py` already delegates:

- F-1 tafsir-FTS-before-synthesis, F-2 matched_passage overlay, F-3 scholar-gate,
  F-4 no-hallucinated-isnad, F-5 ikhtilaf, 4-tier tiering (T-1/T-2) — all in ask-scholar.
- `mizan_interactions` + `ruling_audit_log` persistence — ask-scholar's `tryPersist`,
  with `bot_variant: "al-bayan"`. This receiver does **not** persist (no double-write).

`handler.ts` is a 1:1 port of `albayan_bot.py:format_response` + command routing,
kept free of `Deno.serve` so it is unit-testable. `index.ts` is the serve wrapper.

## Files
- `index.ts` — `Deno.serve` wrapper: OPTIONS/method guard, secret validation, fast-ack
  (200 immediately, process via `EdgeRuntime.waitUntil` so a slow ask-scholar call
  never triggers a Telegram retry / double-answer), Telegram + ask-scholar I/O.
- `handler.ts` — pure logic: static messages, `formatResponse`, `handleUpdate`.
- `__tests__/handler.test.ts` — Deno test (runs in CI deno suite).

## Required function secrets
```
TELEGRAM_BOT_TOKEN     @mzninterfacebot token (falls back to MIZAN_BOT_TOKEN)
BAYAN_WEBHOOK_SECRET   must equal the secret_token given to setWebhook
```
Auto-injected by Supabase: `SUPABASE_URL`, `SUPABASE_ANON_KEY`.

## Deploy (HELD pending operator: deploy-access + al-bayan-bot placeholder-ownership)
```bash
supabase functions deploy al-bayan-bot --project-ref tscuymavysscrvoberrr
supabase secrets set TELEGRAM_BOT_TOKEN=<token> BAYAN_WEBHOOK_SECRET=<random-32> \
  --project-ref tscuymavysscrvoberrr
```

### Cutover — MUST stop the Studio poll side first (route to Studio-reach owner)
Otherwise the poll bot / watchdog will 409-conflict with the webhook:
1. `pkill -f mizan_bot.py` on the Studio (kill the long-poller).
2. Stop + disable the watchdog LaunchAgent so it stops relaunching a poller:
   `launchctl bootout gui/$(id -u)/dev.wingmen.bot-healthcheck` (and unload its plist).

### setWebhook
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url="https://tscuymavysscrvoberrr.supabase.co/functions/v1/al-bayan-bot" \
  -d secret_token="<BAYAN_WEBHOOK_SECRET>" \
  -d allowed_updates='["message"]'
# confirm:
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"   # url set, 0 pending errors
```

### Verify end-to-end (not just "setWebhook ok")
- Send a real query to @mzninterfacebot; confirm a tiered reply arrives.
- Confirm a fresh `mizan_interactions` row: `bot_variant='al-bayan'`, non-null
  `output_tier`, populated `retrieval_ids` — i.e. the audit/eval substrate still fills.
- Send a ruling-class query (e.g. "is X halal?"); confirm the scholar-gate refusal (F-3).

### Rollback (reversible, seconds)
```bash
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"    # back to long-poll
```
Then restart the Studio poll bot if needed.

## Tests
- CI: `deno test supabase/functions/al-bayan-bot/__tests__/handler.test.ts`
- Local (no deno): the pure logic was verified via Node type-stripping against
  `handler.ts` (11 checks: routing, F-3 gate passthrough, tier-marker preservation,
  error-floor, ignore-non-text).
