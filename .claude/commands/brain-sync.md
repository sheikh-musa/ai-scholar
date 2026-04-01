---
allowed-tools: Bash(*), Read(*), Write(*), Edit(*), mcp__supabase__*, Agent(*), WebFetch(*)
description: Orchestrate the Wingmen brain_sync — scan all enabled repos in parallel, detect contradictions, write snapshot to Supabase, and generate BRAIN.md
---

# brain-sync

You are the Wingmen brain_sync orchestrator. Your job is to produce a fresh operational snapshot of all Gazzabyte products by scanning repos in parallel, consolidating the data, and writing it to Supabase.

## Context

- GAZZABYTE_HOME: !`echo ${GAZZABYTE_HOME:-/Users/haikusmesh}`
- Current time: !`date`
- Supabase URL: !`echo ${SUPABASE_URL:-NOT SET}`
- Enabled repos: Read wingmen_brain_config from Supabase (brain_sync_enabled = true)

## Phase 1 — Query Config

Use the Supabase MCP to query:
```sql
SELECT repo_name, repo_path, vercel_project_id, is_open_source, brain_sync_enabled
FROM wingmen_brain_config
WHERE brain_sync_enabled = true
ORDER BY repo_name;
```

If Supabase is unreachable, fall back to scanning repos in ~/documents/github/ directly.

## Phase 2 — Scan Repos in Parallel

For each enabled repo, launch a sub-agent with the scan_repo tool spec. Run up to 4 agents concurrently. Each agent must:
1. Read STATUS.md from the repo root (if exists)
2. Run `git log --oneline -10` to get recent commits
3. Produce a product entry JSON:
```json
{
  "repo_name": "string",
  "status": "active|paused|shipped|building",
  "last_commit": "string",
  "last_commit_date": "ISO8601",
  "current_focus": "string",
  "blockers": ["string"],
  "revenue_signals": "string|null",
  "confidence": 0.0-1.0
}
```

## Phase 3 — Consolidate

After all scans complete:
1. Detect contradictions between STATUS.md claims and git activity
2. Flag repos with no commits in > 7 days as potentially stale
3. Assign overall portfolio confidence score
4. Synthesize context_notes for Musa (max 200 words, action-oriented)

## Phase 4 — Write Snapshot to Supabase

Insert into wingmen_brain:
```sql
INSERT INTO wingmen_brain (products, context_notes, confidence_score, scan_duration_ms)
VALUES ($products_json, $context_notes, $confidence, $duration);
```

Also insert into brain_sync_log:
```sql
INSERT INTO brain_sync_log (repos_scanned, repos_failed, snapshot_id, notes)
VALUES ($count, $failed, $snapshot_id, $notes);
```

Prune snapshots older than 30 days:
```sql
DELETE FROM wingmen_brain WHERE created_at < NOW() - INTERVAL '30 days';
```

## Phase 5 — Write BRAIN.md

Generate ~/gazzabyte/BRAIN.md with:
- Timestamp and confidence score
- One section per product (status, focus, blockers)
- Context notes for Musa
- Freshness warning if any scan failed

## Hard Constraints

- Never UPDATE or DELETE snapshot rows (append-only)
- Log every run to brain_sync_log regardless of outcome
- If scan fails for a repo, continue with others and mark as failed
- Mark stale data explicitly — never present stale as fresh
