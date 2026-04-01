---
name: session_compress
schedule: daily 02:00 Asia/Singapore
description: >
  Detect and handle context entropy in the long-running Telegram Claude Code session.
  Saves a SESSION_CHECKPOINT.md if entropy is detected. Signals restart if needed.
  Runs at 2AM SGT — before morning_brief — so morning_brief always starts from a clean context.
---

# session_compress

You are the Gazzabyte Session Health agent. Context entropy is real: long-running
AI sessions drift, hallucinate stale facts, and become inconsistent over time.
Your job is to detect this early and checkpoint the session before it causes problems.

**This task runs inside the persistent Telegram Claude Code session.**
**It has direct access to the session's current context.**

---

## Step 1 — Assess session age

Check how long the current Claude Code session has been running.

Heuristics (use whichever is available):
- Check the modification time of `~/gazzabyte/logs/wingmen-cto.log`
- Look for the oldest message timestamp in the current session context
- Check `WINGMEN_SESSION_START` environment variable (set by LaunchAgent if configured)

Determine `session_age_hours` as your best estimate.

---

## Step 2 — Run entropy checks

Evaluate each signal independently. Set a flag for each that is true.

| Signal | Check | Flag name |
|---|---|---|
| Session age | session_age_hours > 72 | `old_session` |
| brain_sync failures | Query brain_sync_log: any sync_health = 'degraded' in last 12h? | `recent_degradation` |
| Latest snapshot stale | Query wingmen_brain: freshness_minutes of latest row > 300? | `stale_brain` |
| Failed jobs accumulating | Query jobs: failed jobs in last 6h > 5? | `job_failures` |
| Low confidence products | Query wingmen_brain: any product with confidence = 'low' in latest snapshot? | `low_confidence` |

Count total flags set. This is `entropy_score`.

---

## Step 3 — Decide action

| entropy_score | Action |
|---|---|
| 0 | Healthy — do nothing. Exit silently. |
| 1 | Monitor — write a brief note to console. Do NOT send Telegram. |
| 2–3 | Checkpoint — save SESSION_CHECKPOINT.md. Send Telegram advisory. |
| 4–5 | Critical — save SESSION_CHECKPOINT.md. Send Telegram restart recommendation. |

---

## Step 4 — Write SESSION_CHECKPOINT.md (if entropy_score ≥ 2)

Write to `~/gazzabyte/SESSION_CHECKPOINT.md`:

```markdown
# Session Checkpoint
Generated: [ISO timestamp]
Session age (estimated): [session_age_hours]h
Entropy score: [entropy_score]/5
Flags: [list flags that are true]

## Active Jobs
[Query jobs WHERE status IN ('pending', 'running') — list id, repo, description]
[If none: "No active jobs"]

## Pending Decisions
[List any messages in the session where Musa asked a question but did not
 receive a final answer, or where you were asked to do something and it
 is unclear if it was completed]
[If none: "No pending decisions identified"]

## Last 5 Significant Actions
[From session context or build_runs — list the 5 most recent completed actions
 in format: "[relative time] — [repo] — [what was done]"]

## Uncommitted Work in Progress
[Check each active repo for uncommitted changes:]
[Run: git -C /Users/musa/gazzabyte/[repo_key] status --porcelain 2>/dev/null]
[List any repos with uncommitted changes]
[If none: "No uncommitted changes detected"]

## Brain Snapshot Status
[Latest snapshot created_at and freshness_minutes]
[sync_health of latest snapshot]

## On Restart
After the session restarts, Claude Code will automatically:
1. Read this file (SESSION_CHECKPOINT.md)
2. Read ~/gazzabyte/BRAIN.md
3. Confirm: "Context restored from checkpoint [timestamp]. Continuing."
```

---

## Step 5 — Send Telegram message (if entropy_score ≥ 2)

**If entropy_score = 2–3 (advisory):**

```
🔄 SESSION HEALTH CHECK — [time]

Session has been running ~[session_age_hours]h. Detected [entropy_score] entropy signal(s):
[list true flags, one per line with • bullet]

Checkpoint saved to SESSION_CHECKPOINT.md.

You can continue normally. If responses feel off, send /restart to refresh context.
All state is preserved in the checkpoint.
```

**If entropy_score = 4–5 (critical):**

```
⚠️ SESSION CONTEXT ALERT — [time]

High entropy detected ([entropy_score]/5 signals):
[list true flags, one per line with • bullet]

RECOMMENDATION: Send /restart now to refresh context.
Checkpoint saved — all state will be restored on restart.

After restart, first message will confirm: "Context restored from checkpoint."
```

---

## Step 6 — Handle /restart command

When Musa sends `/restart` to the Telegram bot:

1. Confirm: "Saving checkpoint and preparing restart..."
2. Write/update SESSION_CHECKPOINT.md with current state
3. Signal the LaunchAgent to restart the process (the KeepAlive: true in the plist handles this — just exit the process)

On the new session's first message (any message from Musa after restart):

1. Check if `~/gazzabyte/SESSION_CHECKPOINT.md` exists and was written within the last 30 minutes
2. If yes: read it and BRAIN.md, then respond:
   "Context restored from checkpoint ([timestamp]). Session was [X]h old.
   [brief summary of what was in progress from the checkpoint]
   Continuing. What's next?"
3. If no: respond normally (no checkpoint to restore)

---

## Exit Conditions

- entropy_score = 0: exit immediately with no output
- entropy_score = 1: print to console only, exit
- entropy_score ≥ 2: write checkpoint, send Telegram, exit

Never block or wait for input. This task runs autonomously.
