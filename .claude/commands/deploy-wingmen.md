---
allowed-tools: Bash(*), Read(*), Write(*), Edit(*), mcp__supabase__*, Agent(*), WebFetch(*)
description: Full deployment of the Wingmen Nervous System — deploy schema, configure repos, set up scheduled tasks, validate end-to-end
---

# deploy-wingmen

Deploy the complete Wingmen Nervous System to production. This command launches multiple specialized agents to execute the 10-step migration in the correct order.

## Pre-flight Checks

Verify before proceeding:
- !`echo "SUPABASE_URL: ${SUPABASE_URL:-❌ NOT SET}"`
- !`echo "SUPABASE_SERVICE_ROLE_KEY: ${SUPABASE_SERVICE_ROLE_KEY:+✅ SET}${SUPABASE_SERVICE_ROLE_KEY:-❌ NOT SET}"`
- !`echo "TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:+✅ SET}${TELEGRAM_BOT_TOKEN:-❌ NOT SET}"`
- !`echo "TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID:-❌ NOT SET}"`
- !`echo "GAZZABYTE_HOME: ${GAZZABYTE_HOME:-/Users/haikusmesh}"`

If any critical env var is missing, STOP and list what's needed.

## Deployment Steps (execute sequentially)

### Step 1 — Deploy Supabase Schema

Read the schema file and execute via Supabase MCP:
`/Users/haikusmesh/documents/github/ai scholar/wingmen/schema/001_initial_schema.sql`

Verify all 3 tables created: wingmen_brain_config, wingmen_brain, brain_sync_log

### Step 2 — Create STATUS.md Stubs

For each enabled repo in wingmen_brain_config, create STATUS.md if it doesn't exist:
```markdown
# {repo_name} Status

## Current State
active

## Current Focus
{brief description}

## Blockers
none

## Last Updated
{date}
```

### Step 3 — Update ~/gazzabyte/CLAUDE.md

Apply the additions from:
`/Users/haikusmesh/documents/github/ai scholar/wingmen/GLOBAL_CLAUDE_MD_ADDITIONS.md`

### Step 4 — Validate Scheduled Tasks

Check that these 4 tasks are configured:
- brain-sync (every 4 hours)
- morning-brief (daily 6:00 AM SGT)
- memory-sync (daily midnight SGT)
- session-compress (daily 2:00 AM SGT)

### Step 5 — Run brain-sync Manually

Execute /brain-sync and verify:
- At least 1 repo scanned successfully
- Snapshot written to Supabase
- BRAIN.md generated at ~/gazzabyte/BRAIN.md

### Step 6 — Send Validation Telegram

Send: "✅ Wingmen Nervous System deployed. Running first brain sync..."

### Step 7 — Enable Repos One at a Time

Order:
1. wingmen (this repo)
2. ihsandms (active revenue)
3. candy_motors (paying client)
4. hifz_companion, tadabbur (open source, last)

### Step 8 — Validate End-to-End

Checklist:
- [ ] brain_sync_log has at least 1 successful entry
- [ ] wingmen_brain has at least 1 snapshot
- [ ] BRAIN.md exists and is < 1 hour old
- [ ] Telegram morning-brief can be triggered manually
- [ ] No consecutive failures in brain_sync_log

## Rollback

If deployment fails at any step:
1. Note the failed step
2. Query brain_sync_log for error details
3. Fix the issue, resume from the failed step (do not re-run completed steps)
