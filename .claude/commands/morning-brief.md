---
allowed-tools: mcp__supabase__*, mcp__telegram__*, Read(*)
description: Send the Wingmen daily morning briefing to Musa via Telegram — queries latest brain snapshot and formats a concise CTO brief
---

# morning-brief

Send the daily 6AM SGT morning briefing to Musa via Telegram.

## Context

- Current time: !`date`
- TELEGRAM_CHAT_ID: !`echo ${TELEGRAM_CHAT_ID:-NOT SET}`

## Step 1 — Query Latest Snapshot

```sql
SELECT products, context_notes, confidence_score, created_at,
  EXTRACT(EPOCH FROM (now() - created_at)) / 60 AS age_minutes
FROM wingmen_brain
ORDER BY created_at DESC
LIMIT 1;
```

## Step 2 — Freshness Check

- age < 300 min (5h): Proceed normally
- age 300-720 min (5-12h): Include warning "⚠️ Data is X hours old"
- age > 720 min (12h): Include alert "🚨 Brain sync hasn't run in X hours — check Mac Mini"

## Step 3 — Compose Brief

Format as Telegram message (max 4096 chars):

```
🌅 Morning Brief — {date} {time} SGT

📊 Portfolio Status ({confidence}% confidence)

{for each product}
• {repo_name} [{status}]
  {current_focus}
  {blockers if any: ⚠️ blocker}

💡 Context
{context_notes}

{freshness_warning if applicable}
```

## Step 4 — Send via Telegram MCP

Send one-way message to TELEGRAM_CHAT_ID. No response expected.

## Hard Constraints

- Never skip sending even if data is stale — just flag it
- Keep message under 4096 chars (Telegram limit)
- Timezone is Asia/Singapore (UTC+8)
