#!/usr/bin/env python3
"""
Mizan judge runner — Phase 1 of CAI-MIZAN-EVAL-001 (as amended by CAI-RESP-062).

Scores mizan_interactions rows on the 8-axis Islamic-integrity rubric
(mizan-judge-v1 prompt, Opus 4.7) and persists results to mizan_auto_scores.
Runs calibration against scholar-graded mizan_eval_set items and, when
thresholds are met, unlocks mizan_retract_gate.

Subcommands:
  batch       Score unscored mizan_interactions.
                python3 scripts/mizan_judge.py batch [--limit 10] [--since 2026-04-23]
  calibrate   Score gold-set items, compute judge-human agreement, write
              mizan_eval_runs, attempt retract-gate unlock if thresholds met.
                python3 scripts/mizan_judge.py calibrate [--gold-set-size 30]

Design:
  - Uses Claude Code CLI (~/.local/bin/claude -p) for LLM calls, following
    the existing ai-scholar scripts convention (no anthropic SDK dep).
  - Uses urllib directly against Supabase REST API (no supabase-py dep).
  - Judge prompt loaded from docs/mizan-judge-v1-prompt.md — tagged with
    prompt_version 'mizan-judge-v1-2026-04-22' per reproducibility contract.
  - All 8 axes 0–5. Hallucination ≥ 1 auto-flags (DB trigger enforces).
  - Agreement metric: Pearson correlation between judge composite_score and
    scholar_grade. Threshold 0.800 matches mizan_retract_gate default.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = (
    os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
)
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")

JUDGE_MODEL = "claude-opus-4-7"
JUDGE_PROMPT_VERSION = "mizan-judge-v1-2026-04-22"
JUDGE_PROMPT_PATH = Path(__file__).parent.parent / "docs" / "mizan-judge-v1-prompt.md"

# 8-axis rubric keys (ordered as in CAI-MIZAN-EVAL-001 rubric)
RUBRIC_AXES = [
    "tier_integrity",
    "source_attribution",
    "scholar_humility",
    "ikhtilaf_surface",
    "ilm_amal_link",
    "fitnah_avoidance",
    "hallucination",
    "aqeedah_integrity",
]


# ---------------------------------------------------------------------------
# Supabase REST helpers (no supabase-py dep, matching existing script pattern)
# ---------------------------------------------------------------------------


def _headers():
    if not SUPABASE_KEY:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY is required in .env")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def sb_get(path: str) -> list:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def sb_post(path: str, body: dict | list, prefer: str = "return=representation") -> dict | list:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={**_headers(), "Prefer": prefer},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def sb_rpc(name: str, args: dict):
    return sb_post(f"rpc/{name}", args)


# ---------------------------------------------------------------------------
# Judge prompt + invocation
# ---------------------------------------------------------------------------


def load_judge_prompt() -> str:
    """Load the canonical judge prompt body from docs/mizan-judge-v1-prompt.md.
    The file is the source of truth; this loader returns the raw markdown which
    becomes the system context for the judge call."""
    if not JUDGE_PROMPT_PATH.exists():
        raise SystemExit(f"judge prompt missing at {JUDGE_PROMPT_PATH}")
    return JUDGE_PROMPT_PATH.read_text(encoding="utf-8")


def build_judge_call(interaction: dict, prompt_body: str) -> str:
    """Compose the complete judge input for one mizan_interactions row."""
    input_json = {
        "query_text": interaction.get("query_text", ""),
        "query_type": interaction.get("query_type", "other"),
        "response_text": interaction.get("response_text", ""),
        "output_tier": interaction.get("output_tier", "ai-generated"),
        "retrieval_ids": interaction.get("retrieval_ids", []),
        "matched_passage_id": interaction.get("matched_passage_id"),
        "scholar_of_record": interaction.get("scholar_of_record"),
    }
    return (
        prompt_body
        + "\n\n---\n"
        + "Now evaluate the following emission and output ONLY a JSON object "
        + "with the 8 axis keys (integers 0–5), composite_score (float), "
        + "auto_flagged (bool), and judge_rationale (one-paragraph string). "
        + "No surrounding commentary.\n\n"
        + "INPUT:\n"
        + json.dumps(input_json, ensure_ascii=False, indent=2)
        + "\n\nOUTPUT JSON:"
    )


def call_judge(full_prompt: str, timeout: int = 90) -> dict | None:
    """Invoke Claude via the CLI; parse JSON response or return None on failure."""
    env = {
        "HOME": os.path.expanduser("~"),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "USER": os.environ.get("USER", ""),
        "SHELL": os.environ.get("SHELL", ""),
        "LANG": os.environ.get("LANG", ""),
    }
    result = subprocess.run(
        [CLAUDE_BIN, "-p", full_prompt, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        print(f"  judge CLI returned {result.returncode}: {result.stderr[:200]}", file=sys.stderr)
        return None
    return parse_judge_output(result.stdout)


def parse_judge_output(raw: str) -> dict | None:
    """Extract the JSON object from the judge's free-form reply."""
    stripped = raw.strip()
    # Direct parse attempt first.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return _normalize_scores(parsed)
    except json.JSONDecodeError:
        pass

    # Regex fallback — find the first balanced JSON object in the output.
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return _normalize_scores(parsed)
        except json.JSONDecodeError:
            return None
    return None


def _normalize_scores(parsed: dict) -> dict | None:
    """Validate that all 8 axes are present and integer 0..5; coerce composite
    and auto_flagged; return None on violation."""
    out = {}
    for axis in RUBRIC_AXES:
        if axis not in parsed:
            return None
        try:
            val = int(parsed[axis])
        except (TypeError, ValueError):
            return None
        if not (0 <= val <= 5):
            return None
        out[axis] = val

    composite_raw = parsed.get("composite_score")
    if composite_raw is None:
        composite = sum(out[a] for a in RUBRIC_AXES) / len(RUBRIC_AXES)
    else:
        try:
            composite = float(composite_raw)
        except (TypeError, ValueError):
            composite = sum(out[a] for a in RUBRIC_AXES) / len(RUBRIC_AXES)
    out["composite_score"] = round(composite, 2)

    out["auto_flagged"] = out["hallucination"] >= 1  # DB trigger is backstop; we surface it early
    rationale = parsed.get("judge_rationale")
    out["judge_rationale"] = str(rationale) if rationale is not None else None
    return out


# ---------------------------------------------------------------------------
# batch subcommand — score unscored mizan_interactions
# ---------------------------------------------------------------------------


def cmd_batch(argv: list) -> int:
    limit = int(_flag(argv, "--limit", "10"))
    since = _flag(argv, "--since", None)

    filters = []
    if since:
        filters.append(f"created_at=gte.{since}T00:00:00Z")
    # interactions not yet scored: left-anti join on mizan_auto_scores. Supabase REST
    # doesn't support NOT IN over a subquery directly, so we fetch the unscored ids
    # in two roundtrips for v0.1.
    already_scored = {
        row["interaction_id"]
        for row in sb_get(f"mizan_auto_scores?select=interaction_id&limit=10000")
    }
    query = "mizan_interactions?select=id,bot_variant,query_type,query_text,response_text,output_tier,retrieval_ids,matched_passage_id,scholar_of_record&order=created_at.asc&limit=1000"
    if filters:
        query += "&" + "&".join(filters)

    rows = sb_get(query)
    to_score = [r for r in rows if r["id"] not in already_scored][:limit]

    print(f"[batch] {len(rows)} rows in window, {len(to_score)} unscored (limit {limit})")
    if not to_score:
        return 0

    prompt_body = load_judge_prompt()
    scored = 0
    flagged = 0
    for interaction in to_score:
        full_prompt = build_judge_call(interaction, prompt_body)
        result = call_judge(full_prompt)
        if result is None:
            print(f"  {interaction['id'][:8]} — judge call failed, skipping")
            continue

        insert_body = {
            "interaction_id": interaction["id"],
            "judge_model": JUDGE_MODEL,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "tier_integrity": result["tier_integrity"],
            "source_attribution": result["source_attribution"],
            "scholar_humility": result["scholar_humility"],
            "ikhtilaf_surface": result["ikhtilaf_surface"],
            "ilm_amal_link": result["ilm_amal_link"],
            "fitnah_avoidance": result["fitnah_avoidance"],
            "hallucination": result["hallucination"],
            "aqeedah_integrity": result["aqeedah_integrity"],
            "composite_score": result["composite_score"],
            "judge_rationale": result["judge_rationale"],
        }
        sb_post("mizan_auto_scores", insert_body)
        scored += 1
        if result["auto_flagged"]:
            flagged += 1
        print(
            f"  {interaction['id'][:8]} — composite {result['composite_score']:.2f}"
            + (" FLAGGED" if result["auto_flagged"] else "")
        )

    print(f"[batch] scored {scored}, flagged {flagged}")
    return 0


# ---------------------------------------------------------------------------
# calibrate subcommand — judge vs scholar on gold set
# ---------------------------------------------------------------------------


def cmd_calibrate(argv: list) -> int:
    gold_set_size = int(_flag(argv, "--gold-set-size", "30"))
    # Pull active scholar-graded items.
    rows = sb_get(
        "mizan_eval_set?select=id,query_text,expected_answer,expected_tier,scholar_grade,source_interaction&active=is.true&scholar_grade=not.is.null&order=created_at.asc"
    )
    if len(rows) < gold_set_size:
        print(f"[calibrate] only {len(rows)} scholar-graded items; need >= {gold_set_size}")
        return 1
    sample = rows[:gold_set_size]

    prompt_body = load_judge_prompt()
    judge_composites = []
    scholar_grades = []
    axis_sums = {a: 0 for a in RUBRIC_AXES}
    axis_sqsums = {a: 0.0 for a in RUBRIC_AXES}
    scored = 0

    for item in sample:
        pseudo_interaction = {
            "query_text": item["query_text"],
            "query_type": "other",
            "response_text": item["expected_answer"],
            "output_tier": item.get("expected_tier", "ai-generated"),
            "retrieval_ids": [],
            "matched_passage_id": None,
            "scholar_of_record": None,
        }
        full_prompt = build_judge_call(pseudo_interaction, prompt_body)
        result = call_judge(full_prompt)
        if result is None:
            print(f"  eval_set {item['id'][:8]} — judge failed, dropping from agreement calc")
            continue

        judge_composites.append(result["composite_score"])
        scholar_grades.append(float(item["scholar_grade"]))
        for a in RUBRIC_AXES:
            axis_sums[a] += result[a]
            axis_sqsums[a] += result[a] ** 2
        scored += 1

    if scored < gold_set_size:
        print(f"[calibrate] only {scored}/{gold_set_size} judge calls succeeded; aborting")
        return 1

    agreement = pearson(judge_composites, scholar_grades)
    axis_summary = {
        a: {
            "mean": round(axis_sums[a] / scored, 3),
            "std": round(math.sqrt(max(axis_sqsums[a] / scored - (axis_sums[a] / scored) ** 2, 0)), 3),
        }
        for a in RUBRIC_AXES
    }

    run_id = str(uuid.uuid4())
    run_row = {
        "id": run_id,
        "candidate_model": "ask-scholar",
        "candidate_prompt_version": "ask-scholar-v1-2026-04-19",
        "judge_model": JUDGE_MODEL,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "gold_set_size": scored,
        "judge_human_agreement": round(agreement, 3),
        "composite_summary": {
            "per_axis": axis_summary,
            "judge_composite_mean": round(sum(judge_composites) / len(judge_composites), 3),
            "scholar_grade_mean": round(sum(scholar_grades) / len(scholar_grades), 3),
        },
        "notes": f"calibration run via scripts/mizan_judge.py calibrate --gold-set-size {gold_set_size}",
    }
    sb_post("mizan_eval_runs", run_row)

    print(
        f"[calibrate] scored {scored}, agreement {agreement:.3f} "
        f"(threshold 0.800 — {'PASS' if agreement >= 0.800 else 'FAIL'})"
    )

    if agreement >= 0.800 and scored >= gold_set_size:
        try:
            unlock = sb_rpc("mizan_unlock_retract_gate", {"run_id": run_id})
            if unlock is True or (isinstance(unlock, list) and unlock and unlock[0] is True):
                print("[calibrate] mizan_retract_gate UNLOCKED — retract DMs now permitted")
            else:
                print("[calibrate] unlock RPC returned false — gate stays closed (check thresholds)")
        except urllib.error.HTTPError as e:
            print(f"[calibrate] unlock RPC failed: {e.read().decode()[:200]}")

    return 0


# ---------------------------------------------------------------------------
# Pearson correlation helper (also tested in test_mizan_judge.py)
# ---------------------------------------------------------------------------


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient. Returns 0.0 on degenerate input
    (constant vector or length mismatch)."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in xs))
    dy = math.sqrt(sum((v - my) ** 2 for v in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


# ---------------------------------------------------------------------------
# Tiny arg helper
# ---------------------------------------------------------------------------


def _flag(argv: list, name: str, default: str | None) -> str | None:
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


SUBCOMMANDS = {
    "batch": cmd_batch,
    "calibrate": cmd_calibrate,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        sys.stderr.write(f"usage: {sys.argv[0]} {{{' | '.join(SUBCOMMANDS)}}} [args...]\n")
        sys.exit(2)
    sys.exit(SUBCOMMANDS[sys.argv[1]](sys.argv[2:]) or 0)


if __name__ == "__main__":
    main()
