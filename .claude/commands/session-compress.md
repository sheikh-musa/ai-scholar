---
allowed-tools: Bash(git log:*), Read(*), Write(*), mcp__telegram__*
description: Assess Claude Code session entropy and save a checkpoint if needed — run daily at 2AM SGT to prevent context drift
---

# session-compress

Daily 2AM SGT task: detect if the current Claude Code session is getting stale or context-heavy, save a checkpoint, and recommend restart if needed.

## Context

- Current time: !`date`
- Session start: !`echo ${WINGMEN_SESSION_START:-unknown}`
- GAZZABYTE_HOME: !`echo ${GAZZABYTE_HOME:-/Users/haikusmesh}`
- BRAIN.md exists: !`test -f ${GAZZABYTE_HOME:-/Users/haikusmesh}/gazzabyte/BRAIN.md && echo "yes" || echo "no"`

## Step 1 — Calculate Entropy Score

Score 0-6 based on signals (each signal = +1):

1. Session age > 24 hours
2. Session age > 72 hours (+2 instead of +1 if > 72h)
3. BRAIN.md age > 5 hours (stale context)
4. MEMORY_SYNC_LOG.md exists and is from today (pending memory updates)
5. SESSION_CHECKPOINT.md already exists and is > 24h old

## Step 2 — Decision

- entropy_score 0-1: Log "Session healthy" and exit
- entropy_score 2-3: Save checkpoint, log "Checkpoint saved"
- entropy_score 4+: Save checkpoint, send Telegram alert recommending restart

## Step 3 — Write SESSION_CHECKPOINT.md

Path: ~/gazzabyte/SESSION_CHECKPOINT.md

```markdown
# Session Checkpoint — {ISO datetime}

## Entropy Score: {score}/6

## Active Context

**Current Focus:** {derive from BRAIN.md context_notes if available}
**Pending Items:** {any items from recent Telegram conversation}

## Resume Instructions

When starting a new session, read this file first, then read BRAIN.md.
The brain_sync runs every 4 hours — check its age before trusting BRAIN.md.

## Signals That Triggered Checkpoint

{list of triggered signals}
```

## Step 4 — Telegram Alert (only if entropy >= 4)

```
🔄 Session Compress — {date}

Entropy score: {score}/6
Checkpoint saved to SESSION_CHECKPOINT.md

Recommend restarting Claude Code session for clean context.
New session will auto-load checkpoint + BRAIN.md.
```

## Hard Constraints

- Always save checkpoint before recommending restart
- Never delete old checkpoints — append with timestamp suffix
- If BRAIN.md is missing, note it in the checkpoint
