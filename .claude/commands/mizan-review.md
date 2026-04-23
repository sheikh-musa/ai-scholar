---
allowed-tools: Bash(python3:*), Bash(cd:*), Read(*)
description: Mizan human-review CLI — list flagged interactions, show details, record verdicts, promote to the scholar gold set
---

# mizan-review

Phase 2 + Phase 3 of MIZAN-EVAL-001 — human-in-loop over the auto-flagged queue.

## Usage

$ARGUMENTS

Subcommands (first token of $ARGUMENTS):

- `list [--limit 20]` — flagged interactions awaiting review.
- `show <interaction_id>` — full detail (query, response, auto-scores, review history, gate status).
- `verdict <interaction_id> <verdict> [--correction TEXT] [--rationale TEXT]` — record decision.
  - `ok` / `minor-correction` / `retract` / `escalate`
  - `minor-correction` and `retract` require `--correction TEXT`
  - Reviewer name from `MIZAN_REVIEWER` env (defaults `cai`)
- `promote <interaction_id> --grade N [--expected TEXT]` — Phase 3 gold-set seeding.
  - `N` ∈ 1..5 (scholar quality grade on expected answer)
  - Requires an existing review with verdict `ok` or `minor-correction`
  - Already-promoted interactions are refused; edit `mizan_eval_set` via SQL if re-grading

## Pre-flight

```bash
[ -f scripts/mizan_review.py ] || { echo "missing scripts/mizan_review.py"; exit 1; }
[ -n "$SUPABASE_SERVICE_ROLE_KEY" ] || grep -q "^SUPABASE_SERVICE_ROLE_KEY=" .env || { echo "missing SUPABASE_SERVICE_ROLE_KEY"; exit 1; }
```

## Run

```bash
cd ~/wingmen/projects/ai-scholar
MIZAN_REVIEWER="${MIZAN_REVIEWER:-cai}" python3 scripts/mizan_review.py $ARGUMENTS
```

## Afterward

- `verdict retract` against a closed `mizan_retract_gate` records the scholar judgment but does NOT create a user-facing retraction row — matches CAI-RESP-062 hard constraint.
- Once ≥30 `mizan_eval_set` rows exist with `active=true` and `scholar_grade IS NOT NULL`, run `/mizan-judge calibrate` to attempt gate unlock.

## Invariants

- Only `scholar` / `super_admin` JWT roles can write to `mizan_human_reviews` (RLS in migration `20260422_002`).
- Promotion of a previously-unreviewed interaction is refused — write a verdict first.
- `mizan_human_reviews` is append-only; a later verdict does not overwrite earlier ones (schema CHECK + history rendered in `show`).

## References
- `scripts/mizan_review.py`
- `supabase/migrations/20260422_002_mizan_eval_pipeline.sql`
- CAI-MIZAN-EVAL-001 Phase 2 / Phase 3
