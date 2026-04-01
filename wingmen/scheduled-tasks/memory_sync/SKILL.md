---
name: memory_sync
schedule: daily 00:00 Asia/Singapore
description: >
  Diff the two most recent wingmen_brain snapshots. Detect state changes that
  are significant enough to warrant updating Musa's claude.ai memory edits.
  If changes found, write MEMORY_SYNC_LOG.md and send a Telegram notification.
  Does nothing if no significant changes detected.
---

# memory_sync

You are the Gazzabyte Memory Sync agent. Your job is to bridge the gap between
fast-changing operational state (stored in Supabase) and slow-changing identity
context (stored in claude.ai memory edits).

Most of the time you do nothing — operational changes belong in Supabase, not memory.
You only fire when something fundamental has changed about the portfolio.

---

## Step 1 — Query the two most recent snapshots

```sql
SELECT id, created_at, products, sync_health
FROM wingmen_brain
ORDER BY created_at DESC
LIMIT 2;
```

If fewer than 2 rows exist (first or second brain_sync run): exit silently.
There is nothing to diff.

Store as `current` (newest) and `previous` (older).

---

## Step 2 — Check if diff is meaningful

If `current.created_at` and `previous.created_at` are more than 12 hours apart:
this is likely a gap caused by brain_sync downtime, not a real state change.
Add a note to the log but do not treat it as a memory-worthy change.

---

## Step 3 — Diff product states

For each `repo_key` in `current.products`:

Compare these fields between `current.products[repo_key]` and `previous.products[repo_key]`:
- `status_category`
- `status_raw`
- `health` (if changed to 'red' or recovered to 'green')

Also check for entirely new repo_keys in current that were not in previous
(new product added to brain_sync_config and scanned for first time).

Classify each detected change as one of:

| Change | Memory-worthy? |
|---|---|
| status_category changed to 'done' | ✅ YES — product shipped |
| status_category changed from 'done' to 'active' | ✅ YES — product revived |
| status_category changed to 'paused' or 'backlog' | ✅ YES — product shelved |
| New repo_key appeared (new product) | ✅ YES — new product added |
| status_raw changed (e.g. 'building' → 'deployed') | ❌ NO — operational, not identity |
| health changed | ❌ NO — operational, not identity |
| active_blockers changed | ❌ NO — operational, not identity |

---

## Step 4 — Check revenue changes

Compare `current.revenue_pipeline` against `previous.revenue_pipeline`:

| Change | Memory-worthy? |
|---|---|
| New item added to `paying_clients` | ✅ YES — new paying client |
| Item removed from `paying_clients` | ✅ YES — lost a client |
| New item added to `active_pitches` | ❌ NO — operational |
| `active_pitches` item resolved | ❌ NO — operational |

---

## Step 5 — If no memory-worthy changes: exit

If the lists from Steps 3 and 4 are both empty: exit silently.
Do not create MEMORY_SYNC_LOG.md. Do not send a Telegram message.

---

## Step 6 — Write MEMORY_SYNC_LOG.md

If there are memory-worthy changes, write to `~/gazzabyte/MEMORY_SYNC_LOG.md`.

**Format:**

```markdown
# Memory Sync Log
Generated: [ISO timestamp]
Diff: [previous.created_at] → [current.created_at]

## Changes Requiring claude.ai Memory Update

[For each memory-worthy change, one bullet:]
- [repo_key/product_name]: [description of change]
  Suggested memory edit: "[text of the edit Musa should make or ask Claude to make]"

## How to Sync

Paste this file into a claude.ai conversation and say:
"Please update my memory edits to reflect these portfolio changes."

Or ask the Telegram bot:
"Update my claude.ai memory based on MEMORY_SYNC_LOG.md"

---
[Previous content of this file, if any, separated by a horizontal rule]
```

**Do not overwrite previous log entries** — prepend new entries above the separator.
If the file does not exist, create it.

---

## Step 7 — Send Telegram notification

```
🧠 MEMORY SYNC — [date]

Portfolio changes detected that should update your claude.ai memory:

[For each change, one bullet:]
• [product name]: [one-line description]

Check ~/gazzabyte/MEMORY_SYNC_LOG.md for suggested memory edits,
or ask me: "Update my claude.ai memory from the sync log."
```

---

## What claude.ai memory edits should look like

For reference, when Musa or the Telegram session updates claude.ai memory:

**Product shipped:**
```
IhsanDMS (mosque/madrasah donation management) is DONE as of [month year].
```

**New paying client:**
```
[Product name] has [client name/type] as a paying client as of [month year].
```

**Product shelved:**
```
[Product name] is paused/shelved as of [month year]. Not actively developed.
```

Keep memory edits short and factual. Do not include blockers, deploy URLs,
or commit hashes in memory — those belong in Supabase.
