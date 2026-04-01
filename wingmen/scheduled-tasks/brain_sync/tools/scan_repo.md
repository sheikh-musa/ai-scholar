---
name: scan_repo
type: tool
description: >
  Scan a single repo and return a product entry conforming to the
  wingmen_brain products JSONB structure. Called by brain_sync orchestrator
  for each repo in parallel. Fully self-contained — no Supabase access.
---

# Tool: scan_repo

## Input

You receive one repo config object:

```
{
  repo_key: string,          // e.g. "ihsandms"
  repo_path: string,         // e.g. "~/gazzabyte/ihsandms" (expand ~ to /Users/musa)
  display_name: string,      // e.g. "IhsanDMS"
  vercel_project_id: string | null,
  status_category: string,   // active | done | paused | backlog
  track_revenue: boolean,
  is_open_source: boolean,
  notes: string | null
}
```

## Output Contract

Return EXACTLY this structure (no extra fields, no missing fields):

```jsonc
{
  "repo_key": "ihsandms",
  "display_name": "IhsanDMS",
  "status_category": "active",
  "deploy_url": "https://ihsandms.vercel.app",   // null if not found

  // Git state
  "last_commit_msg": "fix: PayNow QR dynamic generation",
  "last_commit_sha": "a1b2c3d",
  "last_commit_at": "2026-03-30T14:22:00Z",      // ISO 8601, null if no commits
  "commits_last_24h": 3,
  "commits_last_7d": 12,

  // STATUS.md parsed fields
  "current_phase": "Active sales",
  "status_raw": "deployed",    // building|testing|deployed|blocked|done — from STATUS.md
  "active_blockers": [
    "UEN for dynamic QR — awaiting Syukor"
  ],
  "next_milestones": [
    "Dynamic QR with UEN",
    "Multi-mosque support"
  ],
  "revenue_signals": [
    "Syukor requesting UEN — buying signal"
  ],
  "cto_questions": [           // from "Questions for CTO" section — pass to context_notes
    "Should we prioritise multi-mosque before closing deal?"
  ],

  // Health (computed in this tool — consolidation pass may override)
  "health": "green",           // green|yellow|red|archived — see rules below
  "confidence": "medium",      // placeholder — consolidate.md sets final value
  "confidence_reason": "Scan complete — awaiting consolidation pass",

  // Contradiction flags — empty at scan time, consolidate.md populates
  "contradictions": [],

  // Scan metadata — always present
  "status_md_found": true,
  "status_md_last_updated": "2026-03-30T14:25:00Z",  // null if STATUS.md not found
  "scan_succeeded": true,
  "scan_error": null           // string if scan_succeeded = false
}
```

---

## Steps

### 1. Resolve repo path

Expand `~/` using the `GAZZABYTE_HOME` environment variable (default: `/Users/musa`). Example: if `GAZZABYTE_HOME=/Users/haikusmesh`, then `~/gazzabyte/wingmen` resolves to `/Users/haikusmesh/gazzabyte/wingmen`.

### 2. Check repo exists

```bash
test -d /Users/musa/gazzabyte/[repo_key]
```

If the directory does not exist:
- Set `scan_succeeded = false`
- Set `scan_error = "Repo directory not found at [resolved_path]"`
- Return the output structure with all other fields set to null/empty/false
- STOP — do not attempt further steps

### 3. Read STATUS.md

```bash
cat /Users/musa/gazzabyte/[repo_key]/STATUS.md 2>/dev/null
```

If STATUS.md does not exist:
- Set `status_md_found = false`
- Set all STATUS.md-sourced fields (current_phase, status_raw, active_blockers,
  next_milestones, revenue_signals, cto_questions, deploy_url) to null/empty
- Continue to Step 4 (git data is still valuable without STATUS.md)

If STATUS.md exists, parse these fields:

| STATUS.md line pattern | Output field |
|---|---|
| `Last Updated: [value]` | `status_md_last_updated` |
| `Phase: [value]` | `current_phase` |
| `Status: [value]` | `status_raw` |
| `Deploy URL: [value]` | `deploy_url` |
| `Health: [value]` | Read but do NOT use — health is computed below |
| Lines under `## Blocked` | `active_blockers` array (one entry per bullet/line) |
| Lines under `## Next Up` | `next_milestones` array |
| Lines under `## Revenue Signals` | `revenue_signals` array |
| Lines under `## Questions for CTO` | `cto_questions` array |
| Lines under `## Completed` | Ignore — not stored in snapshot |

**Parsing rules**:
- Strip leading `-` and whitespace from bullet items
- Ignore empty lines within sections
- A section ends when the next `##` heading is encountered
- If a section heading exists but has no items: return empty array

### 4. Read git log

```bash
cd /Users/musa/gazzabyte/[repo_key]

# Last commit
git log --oneline -1 --format="%H|%s|%aI" 2>/dev/null

# Commits in last 24h
git log --oneline --since="24 hours ago" --format="%H" 2>/dev/null | wc -l

# Commits in last 7 days
git log --oneline --since="7 days ago" --format="%H" 2>/dev/null | wc -l
```

If git commands fail (not a git repo, no commits):
- Set `last_commit_msg = null`, `last_commit_sha = null`, `last_commit_at = null`
- Set `commits_last_24h = 0`, `commits_last_7d = 0`
- Do NOT fail the scan — a repo with no git history is still scannable

Parse the first git log output:
- Split on `|`
- `[0]` → `last_commit_sha` (first 7 chars only)
- `[1]` → `last_commit_msg`
- `[2]` → `last_commit_at` (ISO 8601 format — use as-is)

### 5. Compute health

Apply these rules in order (first match wins):

```
IF status_category IN ('done', 'paused', 'backlog'):
  → health = 'archived'

ELSE IF status_raw = 'done':
  → health = 'archived'

ELSE IF last_commit_at is null OR (now - last_commit_at) > 14 days:
  AND status_category = 'active':
  → health = 'red'

ELSE IF (now - last_commit_at) > 7 days:
  AND status_category = 'active':
  → health = 'yellow'

ELSE:
  → health = 'green'
```

"now" = current UTC timestamp at scan time.

### 6. Set confidence placeholder

At scan time, set:
- `confidence = 'medium'`
- `confidence_reason = 'Scan complete — awaiting consolidation pass'`

The consolidation tool (consolidate.md) will update these.

### 7. Return the output structure

Populate every field. Do not omit any field even if the value is null.
Return as a JSON object.

---

## Error Handling

If ANY step fails unexpectedly after Step 2 (repo exists):
- Set `scan_succeeded = false`
- Set `scan_error = "[step name]: [error description]"`
- Return the output structure with whatever data was collected up to the point of failure
- Do not throw an exception — let the orchestrator handle the failed scan gracefully
