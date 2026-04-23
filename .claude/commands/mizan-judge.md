---
allowed-tools: Bash(python3:*), Bash(cd:*), Read(*)
description: Run the Mizan judge pipeline — batch score unscored interactions or calibrate against the scholar gold set
---

# mizan-judge

Run Phase 1 (batch) or Phase 0.5 (calibrate) of the MIZAN-EVAL-001 pipeline.

## Usage

$ARGUMENTS

- `batch [--limit N] [--since YYYY-MM-DD]` — score unscored `mizan_interactions` rows (default limit 10).
- `calibrate [--gold-set-size N]` — score the scholar-graded gold set, compute Pearson correlation vs scholar_grade, write `mizan_eval_runs`, attempt `mizan_retract_gate` unlock (default N=30).

## Pre-flight

Verify the env + the script:
```bash
[ -f scripts/mizan_judge.py ] || { echo "missing scripts/mizan_judge.py"; exit 1; }
[ -n "$SUPABASE_SERVICE_ROLE_KEY" ] || grep -q "^SUPABASE_SERVICE_ROLE_KEY=" .env || { echo "missing SUPABASE_SERVICE_ROLE_KEY in env or .env"; exit 1; }
[ -x "$HOME/.local/bin/claude" ] || { echo "missing ~/.local/bin/claude (judge LLM)"; exit 1; }
```

## Run

```bash
cd ~/wingmen/projects/ai-scholar
python3 scripts/mizan_judge.py $ARGUMENTS
```

## Afterward

If `batch`:
- Check how many rows were scored and how many were auto-flagged (hallucination ≥ 1).
- Flagged rows appear in the human-review queue via `/mizan-review list`.

If `calibrate`:
- Check the printed agreement figure. If ≥ 0.800 AND gold_set_size satisfied, the gate auto-unlocks and retract DMs are permitted downstream.
- If agreement < 0.800, the judge prompt likely needs iteration. Bump version tag in `docs/mizan-judge-v1-prompt.md` and re-run calibration.

## Invariants

- Prompt version is pinned per run (`mizan-judge-v1-2026-04-22`). Any prompt edit bumps the tag and becomes a new `mizan_auto_scores.judge_prompt_version` value.
- Hallucination axis ≥ 1 auto-flags regardless of composite score (DB trigger + client normalizer).
- Scholar-default madhab (Shafi'i) narrowed to default-recommendation-selection only — judge does NOT penalize Hanafi/Maliki/Hanbali-correct attribution.

## References
- `scripts/mizan_judge.py`
- `docs/mizan-judge-v1-prompt.md`
- `supabase/migrations/20260422_002_mizan_eval_pipeline.sql`
- CAI-MIZAN-EVAL-001 + CAI-RESP-062
