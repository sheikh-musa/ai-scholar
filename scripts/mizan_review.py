#!/usr/bin/env python3
"""
Mizan human-review CLI — consumer surface for mizan_auto_scores.auto_flagged
queue per CAI-MIZAN-EVAL-001 Phase 2 (as amended by CAI-RESP-062 retract-block).

Scholar / super-admin reviews flagged interactions and records verdicts in
mizan_human_reviews. If the verdict is 'retract' AND the mizan_retract_gate
is unlocked, the CLI creates a new retraction mizan_interactions row
(tier='ai-generated', retraction_of=<prior_id>). If the gate is closed,
retract verdicts are still recorded (scholar's judgment is preserved) but
no user-facing DM is emitted — matching the CAI-RESP-062 amendment.

Subcommands:
  list                    Show flagged interactions awaiting review.
                            python3 scripts/mizan_review.py list [--limit 20]
  show <interaction_id>   Show one flagged interaction + judge scores.
                            python3 scripts/mizan_review.py show <uuid>
  verdict <interaction_id> <verdict> [--correction TEXT] [--rationale TEXT]
                            verdict ∈ {ok, minor-correction, retract, escalate}
                            reviewer name resolved from MIZAN_REVIEWER env or
                            defaults to 'cai'.
  promote <interaction_id> --grade N [--expected TEXT]
                            Phase 3: promote a reviewed (verdict ok or
                            minor-correction) interaction into mizan_eval_set
                            as a gold-set item. --grade 1..5 is the scholar
                            quality grade on the expected answer. Feeds the
                            calibration pool that unlocks mizan_retract_gate.

Design: urllib + supabase REST, matching existing ai-scholar scripts pattern.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = (
    os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
)
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
REVIEWER = os.environ.get("MIZAN_REVIEWER", "cai")

VALID_VERDICTS = {"ok", "minor-correction", "retract", "escalate"}


# ---------------------------------------------------------------------------
# Supabase REST helpers
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


def sb_post(path: str, body: dict, prefer: str = "return=representation") -> dict | list | None:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**_headers(), "Prefer": prefer},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def gate_is_unlocked() -> bool:
    rows = sb_get("mizan_retract_gate?select=unlocked&id=eq.1")
    return bool(rows and rows[0].get("unlocked"))


# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------


def cmd_list(argv: list) -> int:
    limit = int(_flag(argv, "--limit", "20"))

    # Fetch most recent auto_flagged scores that don't yet have a reviewed verdict.
    scores = sb_get(
        "mizan_auto_scores?auto_flagged=is.true"
        "&select=interaction_id,tier_integrity,source_attribution,scholar_humility,"
        "ikhtilaf_surface,ilm_amal_link,fitnah_avoidance,hallucination,aqeedah_integrity,"
        "composite_score,judge_prompt_version,created_at"
        "&order=created_at.desc"
        f"&limit={limit * 3}"
    )
    if not scores:
        print("no auto-flagged interactions")
        return 0

    reviewed_ids = {
        r["interaction_id"]
        for r in sb_get("mizan_human_reviews?select=interaction_id&limit=10000")
    }
    pending = [s for s in scores if s["interaction_id"] not in reviewed_ids][:limit]

    if not pending:
        print(f"all {len(scores)} auto-flagged are reviewed; queue empty")
        return 0

    print(f"{len(pending)} pending review (gate {'UNLOCKED' if gate_is_unlocked() else 'closed'})")
    print()
    for s in pending:
        iid = s["interaction_id"]
        print(f"  {iid[:8]}  composite={s['composite_score']:.2f}  hallucination={s['hallucination']}  {s['created_at'][:19]}")
    print()
    print("next: python3 scripts/mizan_review.py show <interaction_id[:8]+>")
    return 0


# ---------------------------------------------------------------------------
# show subcommand
# ---------------------------------------------------------------------------


def cmd_show(argv: list) -> int:
    if not argv:
        sys.stderr.write("show requires interaction_id argument\n")
        return 2
    iid = argv[0]

    interactions = sb_get(
        f"mizan_interactions?id=eq.{iid}"
        "&select=id,bot_variant,query_type,query_text,query_lang,response_text,"
        "output_tier,matched_passage_id,retrieval_ids,scholar_of_record,model_name,"
        "prompt_version,created_at,retraction_of"
    )
    if not interactions:
        sys.stderr.write(f"interaction {iid} not found\n")
        return 1
    row = interactions[0]

    scores = sb_get(
        f"mizan_auto_scores?interaction_id=eq.{iid}"
        "&select=tier_integrity,source_attribution,scholar_humility,ikhtilaf_surface,"
        "ilm_amal_link,fitnah_avoidance,hallucination,aqeedah_integrity,composite_score,"
        "auto_flagged,judge_rationale,judge_model,judge_prompt_version,created_at"
        "&order=created_at.desc&limit=5"
    )
    reviews = sb_get(
        f"mizan_human_reviews?interaction_id=eq.{iid}"
        "&select=reviewer,verdict,correction_text,rationale,created_at"
        "&order=created_at.desc"
    )

    print(f"=== interaction {row['id']} ===")
    print(f"  bot: {row['bot_variant']}   query_type: {row['query_type']}   tier: {row['output_tier']}")
    print(f"  model: {row['model_name']}   prompt_version: {row['prompt_version']}")
    print(f"  created: {row['created_at']}")
    if row.get("retraction_of"):
        print(f"  retraction_of: {row['retraction_of']}")
    print()
    print(f"  query: {row['query_text']}")
    print()
    print(f"  response:\n    {row['response_text'][:1200]}")
    print()
    if row.get("retrieval_ids"):
        print(f"  retrieval_ids: {len(row['retrieval_ids'])} refs")

    print()
    print("=== auto-scores ===")
    for s in scores:
        print(
            f"  {s['created_at'][:19]}  "
            f"tier={s['tier_integrity']} src={s['source_attribution']} "
            f"hum={s['scholar_humility']} ikh={s['ikhtilaf_surface']} "
            f"iam={s['ilm_amal_link']} fit={s['fitnah_avoidance']} "
            f"HAL={s['hallucination']} aqd={s['aqeedah_integrity']} "
            f"composite={s['composite_score']:.2f}"
            + (" FLAGGED" if s['auto_flagged'] else "")
        )
        if s.get("judge_rationale"):
            print(f"    rationale: {s['judge_rationale']}")
    print()
    if reviews:
        print("=== human reviews ===")
        for r in reviews:
            print(f"  {r['created_at'][:19]}  {r['reviewer']}  →  {r['verdict']}")
            if r.get("correction_text"):
                print(f"    correction: {r['correction_text']}")
            if r.get("rationale"):
                print(f"    rationale: {r['rationale']}")
    else:
        print("=== no human reviews yet ===")

    print()
    print(f"retract-gate: {'UNLOCKED' if gate_is_unlocked() else 'CLOSED (retract DMs blocked)'}")
    print(f"next: python3 scripts/mizan_review.py verdict {row['id']} {{ok|minor-correction|retract|escalate}}")
    return 0


# ---------------------------------------------------------------------------
# verdict subcommand
# ---------------------------------------------------------------------------


def cmd_verdict(argv: list) -> int:
    if len(argv) < 2:
        sys.stderr.write("verdict requires <interaction_id> <verdict>\n")
        return 2
    iid, verdict = argv[0], argv[1]
    if verdict not in VALID_VERDICTS:
        sys.stderr.write(f"verdict must be one of {sorted(VALID_VERDICTS)}\n")
        return 2

    correction = _flag(argv[2:], "--correction", None)
    rationale = _flag(argv[2:], "--rationale", None)

    if verdict in {"minor-correction", "retract"} and not correction:
        sys.stderr.write(f"verdict '{verdict}' requires --correction TEXT\n")
        return 2

    # Verify the interaction exists (avoid FK-ambiguous errors).
    rows = sb_get(f"mizan_interactions?id=eq.{iid}&select=id,bot_variant,query_text,output_tier,model_name,prompt_version")
    if not rows:
        sys.stderr.write(f"interaction {iid} not found\n")
        return 1
    prior = rows[0]

    review_row = {
        "interaction_id": iid,
        "reviewer": REVIEWER,
        "verdict": verdict,
        "correction_text": correction,
        "rationale": rationale,
    }
    sb_post("mizan_human_reviews", review_row)
    print(f"[review] verdict {verdict} recorded by {REVIEWER}")

    if verdict == "retract":
        if not gate_is_unlocked():
            print(
                "[review] retract-gate is CLOSED — verdict recorded but no retraction "
                "mizan_interactions row created. User-facing DM blocked per "
                "CAI-RESP-062 until judge-human agreement ≥ 0.800 on ≥30 gold items."
            )
            return 0

        # Gate open — create retraction row (new mizan_interactions with retraction_of).
        retraction = {
            "telegram_id_hash": "cai-retraction-placeholder",  # operator-driven, no user identity
            "bot_variant": prior["bot_variant"],
            "query_type": "other",
            "query_text": f"[retraction of {iid[:8]}] {prior['query_text']}",
            "response_text": correction,
            "output_tier": "ai-generated",
            "model_name": "human-scholar-correction",
            "prompt_version": "mizan-review-v1-2026-04-23",
            "retraction_of": iid,
        }
        try:
            sb_post("mizan_interactions", retraction)
            print("[review] retraction row inserted; downstream DM pipeline may now fire")
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:400]
            print(f"[review] retraction insert rejected: {msg}", file=sys.stderr)
            return 1

    return 0


# ---------------------------------------------------------------------------
# promote subcommand — Phase 3: reviewed interactions → mizan_eval_set
# ---------------------------------------------------------------------------


def cmd_promote(argv: list) -> int:
    if not argv:
        sys.stderr.write("promote requires <interaction_id>\n")
        return 2
    iid = argv[0]
    grade_raw = _flag(argv[1:], "--grade", None)
    expected_override = _flag(argv[1:], "--expected", None)

    if grade_raw is None:
        sys.stderr.write("promote requires --grade 1..5 (scholar quality grade)\n")
        return 2
    try:
        grade = int(grade_raw)
        if not (1 <= grade <= 5):
            raise ValueError
    except ValueError:
        sys.stderr.write("--grade must be integer 1..5\n")
        return 2

    interactions = sb_get(
        f"mizan_interactions?id=eq.{iid}"
        "&select=id,query_text,response_text,output_tier"
    )
    if not interactions:
        sys.stderr.write(f"interaction {iid} not found\n")
        return 1
    interaction = interactions[0]

    reviews = sb_get(
        f"mizan_human_reviews?interaction_id=eq.{iid}"
        "&verdict=in.(ok,minor-correction)"
        "&select=verdict,correction_text,reviewer,created_at"
        "&order=created_at.desc&limit=1"
    )
    if not reviews:
        sys.stderr.write(
            f"interaction {iid} has no human review with verdict in (ok, minor-correction). "
            "Use `mizan_review.py verdict ...` first.\n"
        )
        return 1
    review = reviews[0]

    existing = sb_get(f"mizan_eval_set?source_interaction=eq.{iid}&select=id&limit=1")
    if existing:
        sys.stderr.write(
            f"interaction {iid} already promoted (eval_set row {existing[0]['id'][:8]}). "
            "Edit the existing row via SQL if the grade or expected_answer changed.\n"
        )
        return 1

    # Promotion logic:
    #  verdict=minor-correction → expected_answer = correction_text (scholar's fix)
    #  verdict=ok              → expected_answer = original response (scholar ratified)
    #  operator may override via --expected TEXT.
    if expected_override:
        expected_answer = expected_override
    elif review["verdict"] == "minor-correction":
        if not review.get("correction_text"):
            sys.stderr.write(
                "minor-correction review has no correction_text; pass --expected TEXT explicitly\n"
            )
            return 1
        expected_answer = review["correction_text"]
    else:
        expected_answer = interaction["response_text"]

    provenance = "corrected-from-flagged" if review["verdict"] == "minor-correction" else "curated-by-cai"
    row = {
        "provenance": provenance,
        "source_interaction": iid,
        "query_text": interaction["query_text"],
        "expected_tier": interaction["output_tier"],
        "expected_answer": expected_answer,
        "scholar_grader": review["reviewer"],
        "scholar_grade": grade,
        "active": True,
    }
    created = sb_post("mizan_eval_set", row)
    new_id = created[0]["id"] if isinstance(created, list) and created else None
    print(
        f"[promote] eval_set row {new_id[:8] if new_id else '(new)'} created "
        f"provenance={provenance} grade={grade}"
    )

    # Show gold-set progress toward retract-gate threshold (30 items default).
    total = sb_get("mizan_eval_set?active=is.true&scholar_grade=not.is.null&select=id")
    print(f"[promote] gold set now has {len(total)} active scholar-graded items (gate threshold: 30)")
    return 0


# ---------------------------------------------------------------------------
# Tiny arg helper (shared with mizan_judge.py)
# ---------------------------------------------------------------------------


def _flag(argv: list, name: str, default):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


SUBCOMMANDS = {
    "list": cmd_list,
    "show": cmd_show,
    "verdict": cmd_verdict,
    "promote": cmd_promote,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        sys.stderr.write(f"usage: {sys.argv[0]} {{{' | '.join(SUBCOMMANDS)}}} [args...]\n")
        sys.exit(2)
    sys.exit(SUBCOMMANDS[sys.argv[1]](sys.argv[2:]) or 0)


if __name__ == "__main__":
    main()
