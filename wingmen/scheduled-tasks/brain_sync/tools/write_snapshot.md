---
name: write_snapshot
type: tool
description: >
  Write the compiled snapshot object to wingmen_brain in Supabase, then
  prune snapshots older than 30 days. Returns the new snapshot's UUID.
---

# Tool: write_snapshot

## Purpose

Atomically write one new row to `wingmen_brain`. Never update existing rows.
After writing, prune old snapshots. Return the new row's UUID to the orchestrator.

---

## Input

The full snapshot object as compiled by the brain_sync orchestrator:

```
{
  snapshot_type: 'full',
  brain_sync_version: 2,
  sync_health: 'ok' | 'degraded',
  sync_health_reason: string | null,
  products: { [repo_key]: ProductEntry },
  recent_activity: ActivityEvent[],
  active_blockers: string[],
  revenue_pipeline: {
    paying_clients: string[],
    active_pitches: string[],
    next_revenue_action: string
  },
  wingmen_state: WingmenState,
  context_notes: string | null,
  repos_scanned: string[],
  repos_failed: string[]
}
```

---

## Output

```
{
  snapshot_id: string | null,    // UUID of the new row, null if write failed
  write_succeeded: boolean,
  error: string | null
}
```

---

## Steps

### 1. Validate input

Before writing, check:
- `products` is a non-empty object (at least one key)
- `snapshot_type` is 'full' or 'delta'
- `brain_sync_version` is an integer

If validation fails:
- Return `{ snapshot_id: null, write_succeeded: false, error: "Validation failed: [reason]" }`
- Do NOT write to Supabase

### 2. Write to Supabase

```sql
INSERT INTO wingmen_brain (
  snapshot_type,
  brain_sync_version,
  sync_health,
  sync_health_reason,
  products,
  recent_activity,
  active_blockers,
  revenue_pipeline,
  wingmen_state,
  context_notes,
  repos_scanned,
  repos_failed
)
VALUES (
  '[snapshot_type]',
  [brain_sync_version],
  '[sync_health]',
  [sync_health_reason or NULL],
  '[products as JSON string]'::jsonb,
  '[recent_activity as JSON string]'::jsonb,
  ARRAY[repos_scanned items as text],
  '[revenue_pipeline as JSON string]'::jsonb,
  '[wingmen_state as JSON string]'::jsonb,
  [context_notes or NULL],
  ARRAY[repos_scanned items as text],
  ARRAY[repos_failed items as text]
)
RETURNING id;
```

Capture the returned `id` as `snapshot_id`.

If this INSERT fails:
- Return `{ snapshot_id: null, write_succeeded: false, error: "[postgres error message]" }`
- Do NOT attempt retry — let the orchestrator handle it

### 3. Prune old snapshots

After a successful write, clean up old snapshots:

```sql
DELETE FROM wingmen_brain
WHERE created_at < now() - interval '30 days';
```

This is best-effort. If it fails, log it but do NOT fail the write.
The data stays — it's just not cleaned up this cycle.

### 4. Return

```
{
  snapshot_id: "[uuid from RETURNING clause]",
  write_succeeded: true,
  error: null
}
```

---

## Idempotency Note

This tool is NOT idempotent — each call creates a new row.
The orchestrator is responsible for calling this tool exactly once per run.
Do not call this tool directly outside of brain_sync.
