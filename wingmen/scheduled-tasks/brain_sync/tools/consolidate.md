---
name: consolidate
type: tool
description: >
  The consolidation pass. Detects contradictions between scan results and
  the previous snapshot. Assigns confidence scores. Generates context_notes
  summarising anything Musa should know. This is the KAIROS/autoDream analog
  for the Wingmen Nervous System.
---

# Tool: consolidate

## Purpose

Raw scan data is a collection of independent observations. This tool:

1. Detects contradictions within each product (e.g. STATUS.md says "deployed" but no recent commits)
2. Detects changes relative to the previous snapshot (e.g. a blocker was resolved, health degraded)
3. Assigns a confidence score to each product entry
4. Synthesises a free-form `context_notes` paragraph for Musa

The consolidation pass NEVER discards data. When it detects a contradiction,
it records both the data and the contradiction — it does not pick a winner.

---

## Input

```
{
  scan_results: ProductEntry[],        // array of outputs from scan_repo
  previous_snapshot: {                 // null if this is the first run
    id: string,
    created_at: string,
    products: { [repo_key]: ProductEntry },
    sync_health: string
  } | null
}
```

---

## Output

```
{
  consolidated_products: { [repo_key]: ProductEntry },  // scan_results with confidence + contradictions populated
  context_notes: string,                                // free-form synthesis for context_notes column
  contradictions_count: integer
}
```

---

## Steps

### 1. Initialise

Set `contradictions_count = 0`.
Set `context_notes_lines = []` (you will join these at the end).

### 2. For each product in scan_results

Run all contradiction checks below. For each contradiction found:
- Add it to the product's `contradictions` array
- Increment `contradictions_count`
- Add a note to `context_notes_lines`

#### 2a. Internal contradictions (STATUS.md vs git log)

| Condition | Contradiction |
|---|---|
| `status_raw = 'deployed'` AND `commits_last_7d = 0` AND `status_category = 'active'` | "STATUS.md claims deployed but no commits in 7 days — may be stale" |
| `health = 'green'` AND `commits_last_7d = 0` | "Health marked green but no recent git activity" |
| `status_raw = 'blocked'` AND `commits_last_24h > 0` AND `commits_last_7d > 3` | "Status is blocked but commits are active — is the blocker resolved?" |
| `status_raw = 'building'` AND `deploy_url` is non-null | "Status is building but a deploy URL is present — may be deployed" |
| `status_md_found = false` AND `status_category = 'active'` | "No STATUS.md found for active repo — brain_sync cannot read operational state" |

#### 2b. Regression detection (compare to previous snapshot)

If `previous_snapshot` is not null and the previous snapshot has a product entry
for this `repo_key`:

| Change | Note |
|---|---|
| `health` changed from 'green' to 'yellow' or 'red' | "⚠️ [display_name] health DEGRADED: green → [new value]" |
| `health` changed from 'yellow' or 'red' to 'green' | "✅ [display_name] health RECOVERED: [old value] → green" |
| A blocker present in previous snapshot is now absent | "✅ Blocker resolved in [display_name]: [blocker text]" |
| A blocker absent in previous snapshot is now present | "🚧 New blocker in [display_name]: [blocker text]" |
| `status_raw` changed | "📋 [display_name] status changed: [old] → [new]" |

Do NOT flag as a contradiction if both snapshots agree.

#### 2c. Assign confidence score

After running all checks:

| Condition | confidence | confidence_reason |
|---|---|---|
| No contradictions found AND status_md_found = true | 'high' | "STATUS.md and git log are consistent" |
| No contradictions found AND status_md_found = false | 'medium' | "No STATUS.md — health inferred from git only" |
| 1 contradiction found | 'medium' | "Minor inconsistency detected — see contradictions" |
| 2+ contradictions found | 'low' | "Multiple inconsistencies — verify manually" |
| scan_succeeded = false | 'low' | "Scan failed — data may be incomplete" |

Set `confidence` and `confidence_reason` on the product entry.

### 3. Check for repos that failed to scan

For any product entry where `scan_succeeded = false`:
- Set confidence = 'low'
- Add to context_notes_lines: "🔴 [display_name] scan FAILED: [scan_error]"

### 4. Check for CTO questions

For any product entry where `cto_questions` is non-empty:
- Add to context_notes_lines: "❓ [display_name] has questions for CTO: [questions joined by '; ']"

### 5. Compile context_notes

If `context_notes_lines` is empty:
- Set `context_notes = null`

Otherwise:
- Join with newlines
- Prepend: `"Brain Sync Consolidation — [ISO timestamp]\n\n"`
- Append if contradictions_count > 0: `"\n\n[contradictions_count] contradiction(s) detected. Verify manually or ask Claude Code to check the affected repos."`

### 6. Return

```
{
  consolidated_products: scan_results (with confidence, confidence_reason, and contradictions populated),
  context_notes: compiled string or null,
  contradictions_count: integer
}
```

---

## First-Run Behaviour (previous_snapshot = null)

Skip all regression detection checks (Step 2b). All other checks apply.
Add to context_notes_lines: "First brain_sync run — no previous snapshot to compare against."

---

## Consolidation Principle

When two data sources disagree:
- Record both data points
- Record the disagreement in `contradictions`
- Lower the confidence score
- Do NOT silently pick one source as correct
- Do NOT overwrite STATUS.md data with git data or vice versa

The purpose of this tool is to make uncertainty visible, not to resolve it.
