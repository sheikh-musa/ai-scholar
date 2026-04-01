---
name: brain_sync
schedule: every 4 hours
description: >
  Scan all brain_sync_enabled repos in wingmen_brain_config, run the consolidation
  pass to detect contradictions, and write a full operational snapshot to Supabase
  wingmen_brain. Also writes ~/gazzabyte/BRAIN.md for local reference.
  Logs every run (success or failure) to brain_sync_log.
---

# brain_sync — Orchestrator

You are the Gazzabyte Brain Sync orchestrator. You coordinate four discrete tools
to produce an operational snapshot of all Gazzabyte products.

**IMPORTANT**: Never skip a step. Never proceed if a step fails silently. If a step
fails, record the failure and continue to the next step — do not abort the entire run.
Graceful degradation is a hard requirement.

---

## Pre-flight

Record the run start time. You will need it for duration_ms in brain_sync_log.

Determine trigger type:
- If this is running from /schedule: trigger = 'scheduled'
- If Musa ran it manually: trigger = 'manual'
- If another task triggered it: trigger = 'on_demand'

---

## Step 0 — Check for Concurrent Run

Before starting, check if a previous brain_sync is still running:

```sql
SELECT run_at, duration_ms
FROM brain_sync_log
ORDER BY run_at DESC
LIMIT 1;
```

If the result has `duration_ms IS NULL` AND `run_at > now() - interval '30 minutes'`:
- Log: `"Skipped — previous brain_sync still in progress (started at {run_at})"`
- Exit gracefully. Do not proceed to Step 1.

If no rows exist or the most recent run has completed (`duration_ms IS NOT NULL`), proceed normally.

---

## Step 1 — Read Repo Registry

Query Supabase:

```sql
SELECT
  repo_key,
  repo_path,
  display_name,
  vercel_project_id,
  status_category,
  track_revenue,
  is_open_source,
  notes
FROM wingmen_brain_config
WHERE brain_sync_enabled = true
ORDER BY repo_key;
```

If this query fails: write a brain_sync_log entry with error_detail set,
send a Telegram message "🔴 brain_sync failed at Step 1 — cannot read repo registry.
Check Supabase connection.", and stop.

Store the result as `enabled_repos`. If `enabled_repos` is empty, log a warning
and stop — nothing to scan.

---

## Step 2 — Scan Repos (Parallel, up to 4 at a time)

For each repo in `enabled_repos`, invoke the `scan_repo` tool with the repo config.

Run up to 4 scans in parallel. If a repo scan times out after 45 seconds or throws
an error:
- Mark that repo as scan_failed
- Set scan_error to a description of what failed
- Continue with other repos — do not abort the entire batch

Collect all scan results (successful and failed) into `scan_results`.

**Tool**: `~/.claude/scheduled-tasks/brain_sync/tools/scan_repo.md`
**Input per call**: one row from `enabled_repos`
**Output per call**: a product entry conforming to the products JSONB structure in the spec

---

## Step 3 — Read Previous Snapshot

Query Supabase for the most recent snapshot:

```sql
SELECT id, created_at, products, sync_health
FROM wingmen_brain
ORDER BY created_at DESC
LIMIT 1;
```

Store as `previous_snapshot`. If no previous snapshot exists (first run),
set `previous_snapshot` to null — the consolidation pass handles this case.

---

## Step 4 — Consolidation Pass

Invoke the `consolidate` tool.

**Tool**: `~/.claude/scheduled-tasks/brain_sync/tools/consolidate.md`

**Input**:
- `scan_results`: array of product entries from Step 2
- `previous_snapshot`: the previous wingmen_brain row (or null)

**Output**:
- `consolidated_products`: the finalized products JSONB with confidence scores and contradiction flags
- `context_notes`: free-form text summarising contradictions and flags for Musa
- `contradictions_count`: integer

---

## Step 5 — Query Wingmen Job State

Invoke the `query_job_state` tool.

**Tool**: `~/.claude/scheduled-tasks/brain_sync/tools/query_job_state.md`

**Output**:
- `wingmen_state`: JSONB matching the wingmen_state column structure
- `recent_activity`: array of recent activity events from jobs and build_runs

---

## Step 6 — Compile Full Snapshot

Build the complete snapshot object:

```
snapshot = {
  snapshot_type: 'full',
  brain_sync_version: 2,
  sync_health: (if any repos_failed AND repos_failed.length > 0) ? 'degraded' : 'ok',
  sync_health_reason: (if degraded) list the failed repos and their errors,
  products: consolidated_products from Step 4,
  recent_activity: recent_activity from Step 5,
  active_blockers: flatten all products[*].active_blockers into a single deduplicated array,
  revenue_pipeline: {
    paying_clients: list repo_keys where track_revenue = true and status_category = 'active',
    active_pitches: extract from revenue_signals across all products,
    next_revenue_action: the single most important revenue action (your judgment based on signals)
  },
  wingmen_state: wingmen_state from Step 5,
  context_notes: context_notes from Step 4,
  repos_scanned: list of repo_keys that scan_succeeded = true,
  repos_failed: list of repo_keys that scan_succeeded = false
}
```

---

## Step 7 — Write Snapshot to Supabase

Invoke the `write_snapshot` tool.

**Tool**: `~/.claude/scheduled-tasks/brain_sync/tools/write_snapshot.md`

**Input**: the full snapshot object from Step 6

**Output**:
- `snapshot_id`: UUID of the newly inserted row (or null if write failed)
- `write_succeeded`: boolean

If write fails: log to brain_sync_log with error_detail, send Telegram alert,
stop. Do NOT attempt to write BRAIN.md with potentially corrupt data.

---

## Step 8 — Write BRAIN.md

Invoke the `write_brain_md` tool.

**Tool**: `~/.claude/scheduled-tasks/brain_sync/tools/write_brain_md.md`

**Input**: the full snapshot object from Step 6

This step is best-effort. If it fails, log the failure but do not treat it
as a brain_sync failure — Supabase is the source of truth.

---

## Step 9 — Write brain_sync_log Entry

```sql
INSERT INTO brain_sync_log
  (trigger, duration_ms, snapshot_id, repos_attempted, repos_scanned,
   repos_failed, contradictions_found, sync_health, error_detail)
VALUES
  ('[trigger from pre-flight]',
   [now() - start_time in ms],
   '[snapshot_id from Step 7]',
   [length of enabled_repos],
   [length of repos_scanned],
   [length of repos_failed],
   [contradictions_count from Step 4],
   '[sync_health from Step 6]',
   NULL);
```

---

## Step 10 — Completion Summary

Print to console (visible in logs):

```
✅ brain_sync complete — [timestamp]
   Repos scanned: [n] | Failed: [n] | Contradictions: [n]
   Sync health: [ok|degraded]
   Snapshot ID: [uuid]
   Duration: [ms]ms
```

If sync_health is 'degraded', additionally send a Telegram message:
"⚠️ brain_sync completed with degraded health. [n] repo(s) failed to scan:
[list failed repos]. Check ~/gazzabyte/BRAIN.md for details."

Do NOT send a Telegram message for healthy runs — morning_brief handles
the daily summary. Only alert on degradation.

---

## Failure Recovery

If the entire run fails catastrophically (unhandled exception before Step 7):

1. Write a brain_sync_log entry with snapshot_id = null and error_detail = exception message
2. Send Telegram: "🔴 brain_sync CRASHED before writing snapshot. Run /task run brain_sync
   to retry. Error: [short description]"
3. Do not write BRAIN.md
4. Exit

The Telegram session and morning_brief will continue to work with the previous
(stale) snapshot. They will surface the staleness via the freshness check.

---

## Consecutive Failure Detection

After writing the `brain_sync_log` entry, query the last 3 entries:

```sql
SELECT error_detail, sync_health
FROM brain_sync_log
ORDER BY run_at DESC
LIMIT 3;
```

If all 3 rows have `error_detail IS NOT NULL` OR `sync_health = 'degraded'`:
- Send Telegram alert: `"ALERT: 3 consecutive brain_sync runs failed or degraded. Investigate Mac Mini immediately."`
- This is a post-run check — it does not affect the current run's outcome.
