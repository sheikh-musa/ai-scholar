---
name: query_job_state
type: tool
description: >
  Query the Wingmen Orchestrator's job queue and build_runs tables to produce
  wingmen_state JSONB and recent_activity events for the brain snapshot.
---

# Tool: query_job_state

## Purpose

Read the current state of the Wingmen Orchestrator's job queue. Produce two outputs:
1. A `wingmen_state` summary (queue depth, running jobs, completions, failures)
2. A `recent_activity` array of notable events from the last 24h across all repos

---

## Input

None. This tool runs its own Supabase queries.

---

## Output

```
{
  wingmen_state: {
    queue_depth: integer,          // jobs with status = 'pending'
    running_jobs: JobSummary[],    // jobs with status = 'running'
    completed_24h: integer,        // build_runs completed in last 24h
    failed_24h: integer,           // build_runs failed in last 24h
    worker_status: string          // 'healthy' | 'degraded' | 'down' — see rules below
  },
  recent_activity: ActivityEvent[]
}
```

Where:

```
JobSummary = {
  id: string,
  repo: string,
  description: string,
  started_at: string
}

ActivityEvent = {
  repo: string,
  type: 'commit' | 'deploy' | 'job_complete' | 'job_failed' | 'blocker_added' | 'blocker_resolved',
  summary: string,
  timestamp: string
}
```

---

## Steps

### 1. Query job queue state

```sql
-- Current queue depth (pending jobs)
SELECT COUNT(*) as queue_depth
FROM jobs
WHERE status = 'pending';

-- Currently running jobs
SELECT id, repo, description, started_at
FROM jobs
WHERE status = 'running'
ORDER BY started_at ASC;
```

### 2. Query build_runs (last 24h)

```sql
-- Completions in last 24h
SELECT COUNT(*) as completed_24h
FROM build_runs
WHERE status = 'completed'
  AND completed_at > now() - interval '24 hours';

-- Failures in last 24h
SELECT COUNT(*) as failed_24h
FROM build_runs
WHERE status = 'failed'
  AND completed_at > now() - interval '24 hours';

-- Recent completions for recent_activity (last 24h, last 10)
SELECT id, repo, summary, completed_at, status
FROM build_runs
WHERE completed_at > now() - interval '24 hours'
ORDER BY completed_at DESC
LIMIT 10;
```

### 3. Determine worker_status

```
IF failed_24h > completed_24h AND failed_24h >= 3:
  → worker_status = 'degraded'

ELSE IF no build_runs at all in last 24h AND queue_depth > 0:
  → worker_status = 'down'   # queue is building up but nothing completing

ELSE:
  → worker_status = 'healthy'
```

### 4. Build recent_activity from build_runs

For each build_run from Step 2's completions query:

```
{
  repo: [build_run.repo],
  type: 'job_complete' if status = 'completed', else 'job_failed',
  summary: [build_run.summary],
  timestamp: [build_run.completed_at]
}
```

Include both completed and failed builds.

### 5. Handle query failures

If any Supabase query fails:
- Set the affected fields to null or 0
- Set worker_status = 'degraded'
- Continue — do not abort brain_sync

Do NOT throw an exception. Return whatever data was collected.

### 6. Return

Return `wingmen_state` and `recent_activity` as specified in the output contract.

If `recent_activity` is empty (no builds in 24h), return an empty array `[]` — do not return null.
