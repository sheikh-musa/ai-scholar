---
allowed-tools: mcp__supabase__*, mcp__telegram__*, Write(*), Read(*)
description: Diff the last two Wingmen brain snapshots, detect portfolio-level changes, and write MEMORY_SYNC_LOG.md with suggestions for claude.ai memory updates
---

# memory-sync

Daily midnight task: detect meaningful portfolio-level changes between the last two brain snapshots and log them for claude.ai memory updates.

## Context

- Current time: !`date`
- GAZZABYTE_HOME: !`echo ${GAZZABYTE_HOME:-/Users/haikusmesh}`

## Step 1 — Fetch Last 2 Snapshots

```sql
SELECT id, products, context_notes, confidence_score, created_at
FROM wingmen_brain
ORDER BY created_at DESC
LIMIT 2;
```

If fewer than 2 snapshots exist, exit gracefully with a log entry.

## Step 2 — Diff Products

Compare snapshot[0] vs snapshot[1] for each repo:

**Changes to flag (portfolio-level, slow-moving):**
- Status change: active → shipped (product launched)
- Status change: active → paused (product shelved)
- New repo appeared in products
- Repo disappeared from products
- Revenue signal appeared or disappeared
- Context notes mention: new client, contract signed, domain change, pivot

**Changes to IGNORE (operational, fast-moving):**
- Commit messages and code activity
- Current focus shifts
- Minor blocker changes

## Step 3 — Write MEMORY_SYNC_LOG.md

Only write if meaningful changes detected. Path: ~/gazzabyte/MEMORY_SYNC_LOG.md

Format:
```markdown
# Memory Sync Log — {ISO datetime}

## Portfolio Changes Detected

### {repo_name}
- **Change:** {description}
- **Memory Update Suggested:** {what to update in claude.ai memory}

## Suggested claude.ai Memory Edits

{Numbered list of specific memory additions/removals for Musa to apply}
```

## Step 4 — Telegram Notification

If changes detected, send via Telegram:
```
🧠 Memory Sync — {date}

{N} portfolio change(s) detected.
Check ~/gazzabyte/MEMORY_SYNC_LOG.md for suggested claude.ai memory updates.
```

## Hard Constraints

- Only update claude.ai memory for identity-level changes (slow-moving)
- Never write log if no meaningful changes
- All operational state stays in Supabase
