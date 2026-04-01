---
allowed-tools: Bash(*), Read(*), Write(*), Edit(*), mcp__supabase__*, mcp__telegram__*, Agent(*), WebFetch(*), WebSearch(*)
description: Launch maximum parallel sub-agents to build, deploy, and validate the complete AI Scholar system (Al-Bayān + Wingmen Nervous System) from specs to production
---

# build-ai-scholar

Master build command. Spawns the maximum number of parallel sub-agents to simultaneously build every component of AI Scholar.

## Pre-flight

- Specs location: /Users/haikusmesh/documents/github/ai scholar/
- !`echo "SUPABASE_URL: ${SUPABASE_URL:-❌ NOT SET}"`
- !`echo "TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:+✅ SET}${TELEGRAM_BOT_TOKEN:-❌ NOT SET}"`
- !`echo "GAZZABYTE_HOME: ${GAZZABYTE_HOME:-/Users/haikusmesh}"`

If any env var is missing, list exactly what's needed and stop.

## Parallel Agent Wave 1 — Foundation (launch all simultaneously)

**Agent A — Supabase Schema Deployer**
Spec: /ai scholar/wingmen/schema/001_initial_schema.sql
Task: Deploy Wingmen schema (wingmen_brain_config, wingmen_brain, brain_sync_log)
Also create Phase 1 ayat schema (ayat, tafsir_entries, topics, ayat_topics)
Validate: all tables exist, RLS enabled, seed data inserted

**Agent B — North Star Ayat Ingestion (Part 1)**
Spec: /ai scholar/north-star/PHASE_1_IMPLEMENTATION.md
Task: Ingest ayat 2:153, 14:7, 51:56, 39:53, 2:45 with dual tafsir
Use /ingest-ayat command logic

**Agent C — North Star Ayat Ingestion (Part 2)**
Spec: /ai scholar/north-star/PHASE_1_IMPLEMENTATION.md
Task: Ingest ayat 4:135, 65:3, 20:114, 94:5-6, 98:5 with dual tafsir
Use /ingest-ayat command logic

**Agent D — Supabase Edge Function: ask-scholar**
Spec: /ai scholar/north-star/PHASE_1_IMPLEMENTATION.md (API endpoint section)
Task: Write Deno/TypeScript Supabase Edge Function that implements the scholar-ask query logic
Output: supabase/functions/ask-scholar/index.ts
Include: keyword extraction, fiqh gate, 4-tier response format, CORS headers

**Agent E — STATUS.md Creator**
Spec: /ai scholar/wingmen/WINGMEN_NERVOUS_SYSTEM_SPEC_v2.md
Task: Create STATUS.md files in all 8 repos listed in wingmen_brain_config
Repos: ~/documents/github/{wingmen,ihsandms,candy_motors,hifz_companion,tadabbur,cosem,bayt,dookana}

**Agent F — CLAUDE.md Updater**
Spec: /ai scholar/wingmen/GLOBAL_CLAUDE_MD_ADDITIONS.md
Task: Apply context protocol additions to ~/gazzabyte/CLAUDE.md

## Parallel Agent Wave 2 — Orchestration Layer (after Wave 1 completes)

**Agent G — brain_sync Validator**
Task: Run /brain-sync manually and validate end-to-end
Check: snapshot in Supabase, BRAIN.md generated, brain_sync_log entry

**Agent H — LaunchAgent Setup**
Spec: /ai scholar/wingmen/WINGMEN_NERVOUS_SYSTEM_SPEC_v2.md (LaunchAgent section)
Task: Create ~/Library/LaunchAgents/com.gazzabyte.wingmen-cto.plist
Create ~/gazzabyte/logs/ directory
Verify launchctl can load it

**Agent I — Scheduled Task Configuration**
Task: Configure all 4 Claude Code scheduled tasks:
- brain-sync every 4 hours
- morning-brief daily 06:00 SGT
- memory-sync daily 00:00 SGT
- session-compress daily 02:00 SGT

**Agent J — Acceptance Tests**
Spec: /ai scholar/north-star/SAMPLE_INTERACTIONS.md
Task: Run all 4 sample interaction flows against the deployed system
Test: factual query, inference query, fiqh gate redirect, out-of-scope
Report pass/fail for each

## Wave 3 — Validation & Go-Live

After all Wave 2 agents complete:

1. Query brain_sync_log for any failures
2. Verify all 10 ayat ingested with dual tafsir
3. Send Telegram go-live message:
```
✅ AI Scholar deployed successfully.

📖 Al-Bayān: {N} ayat ingested, scholar gate active
🧠 Wingmen: {N} repos tracked, brain_sync running
🌅 Morning brief starts tomorrow 6:00 AM SGT

بسم الله
```

## Failure Handling

- If Wave 1 agent fails: log failure, continue other Wave 1 agents
- If schema fails: STOP all agents — everything depends on schema
- If ayat ingestion fails: retry once, then report partial success
- Never mark as complete if scholar gate test fails

## Hard Constraints

- Maximize parallelism — all independent agents run simultaneously
- Never block Wave 2 on individual Wave 1 failures (only schema is blocking)
- All Supabase writes use RLS service_role
- Open-source repos (hifz_companion, tadabbur) get clean commit messages
