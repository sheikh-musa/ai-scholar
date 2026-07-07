#!/usr/bin/env python3
"""Offline unit tests for the MIZAN-REENGAGE-01 follow-up module
(scripts/mizan_followup.py) — the pure, DB-free logic that encodes the
CAI-RESP-396 bounds.

Covers: failure classification (§3 eligible classes), 30-day cooldown (§5),
send-worthy shape pre-gate (§4 bias-to-skip), STOP opt-out detection (§6b),
the mandatory self-identifying follow-up message (§6a/§6b), and the crucial
safety property that enqueue_if_eligible is INERT while the feature is
disabled (default) — so wiring the hook into the live bot changes nothing
until the migration is applied and MIZAN_FOLLOWUP_ENABLED=1.

Pure offline: no Supabase, no Claude CLI, no Telegram.
Run:  python3 scripts/test_mizan_followup.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("MIZAN_FOLLOWUP_ENABLED", None)  # ensure the default (disabled) path
sys.path.insert(0, str(Path(__file__).parent))

import mizan_followup as f  # noqa: E402
from mizan_bot import EVIDENCE_FALLBACK_PREFIX, TIMEOUT_STUB_MSG  # noqa: E402

NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)


# --- §3 failure classification ---------------------------------------------
def test_good_answer_is_not_a_failure():
    assert f.classify_failure("A full scholarly answer on riba, 900 chars ...") is None


def test_evidence_fallback_classified():
    assert f.classify_failure(EVIDENCE_FALLBACK_PREFIX + "\n\n📖 stuff") == "evidence-fallback"


def test_timeout_stub_classified():
    assert f.classify_failure(TIMEOUT_STUB_MSG) == "timeout-stub"


def test_empty_answer_is_none():
    assert f.classify_failure("") is None
    assert f.classify_failure(None) is None


def test_weak_corpus_gap_is_not_eligible():
    # An honest "we don't carry this" is NOT one of the two eligible strings (§3):
    # re-running the same corpus yields the same non-answer, so it must not enqueue.
    assert f.classify_failure("We don't have material on tasawwuf in the corpus.") is None


# --- §5 cooldown -----------------------------------------------------------
def test_cooldown_recent_is_blocked():
    assert f.within_cooldown((NOW - timedelta(days=10)).isoformat(), NOW) is True


def test_cooldown_old_is_clear():
    assert f.within_cooldown((NOW - timedelta(days=40)).isoformat(), NOW) is False


def test_cooldown_boundary_29_vs_31():
    assert f.within_cooldown((NOW - timedelta(days=29)).isoformat(), NOW) is True
    assert f.within_cooldown((NOW - timedelta(days=31)).isoformat(), NOW) is False


def test_cooldown_no_prior_row():
    assert f.within_cooldown(None, NOW) is False
    assert f.within_cooldown("not-a-date", NOW) is False


# --- §4 send-worthy shape pre-gate (bias to skip) --------------------------
def test_send_worthy_rejects_short():
    assert f.is_send_worthy_shape("too short") is False


def test_send_worthy_rejects_fallback_shaped():
    assert f.is_send_worthy_shape(EVIDENCE_FALLBACK_PREFIX + "\n\nx" * 400) is False
    assert f.is_send_worthy_shape(TIMEOUT_STUB_MSG) is False


def test_send_worthy_rejects_honest_gap():
    assert f.is_send_worthy_shape("Unfortunately we couldn't find this in the corpus. " * 8) is False


def test_send_worthy_accepts_real_answer():
    assert f.is_send_worthy_shape("A" * 250) is True


# --- §6b STOP opt-out detection --------------------------------------------
def test_stop_variants_detected():
    for s in ["STOP", "stop", "unsubscribe", "opt out", "berhenti", "no thanks"]:
        assert f.is_stop_reply(s) is True, s


def test_real_question_starting_with_stop_is_not_optout():
    assert f.is_stop_reply("stop combining prayers when travelling?") is False
    assert f.is_stop_reply("what is the ruling on stopping a fast") is False


def test_empty_is_not_stop():
    assert f.is_stop_reply("") is False


# --- §6a/§6b follow-up message ---------------------------------------------
def test_followup_message_shape():
    m = f.build_followup_message("What is riba?", "Riba is an increase ..." + "x" * 300)
    assert "Reply STOP" in m               # §6b mandatory opt-out line
    assert "not marketing" in m            # §6a honest, not marketing
    assert "What is riba?" in m            # quotes the user's own question
    assert "you asked earlier" in m.lower()


def test_followup_message_truncates_long_question():
    long_q = "why " * 100
    m = f.build_followup_message(long_q, "answer " * 60)
    assert "…" in m  # question clipped


# --- safety: disabled feature is fully inert -------------------------------
def test_enqueue_noop_when_disabled():
    # Default (no MIZAN_FOLLOWUP_ENABLED) must return None WITHOUT any network
    # call — even for a genuine failure answer. If this made a DB call it would
    # raise; returning None proves the gate short-circuits first.
    assert f.FOLLOWUP_ENABLED is False
    rid = f.enqueue_if_eligible(123456789, "what is riba?", TIMEOUT_STUB_MSG)
    assert rid is None


def test_g1_good_answer_never_enqueues_even_if_enabled():
    # Flip the flag in-process; a send-worthy answer classifies as None, so
    # enqueue returns before any DB call (G1). Restore the flag after.
    saved = f.FOLLOWUP_ENABLED
    f.FOLLOWUP_ENABLED = True
    try:
        rid = f.enqueue_if_eligible(123, "q", "A genuinely complete answer " * 20)
        assert rid is None
    finally:
        f.FOLLOWUP_ENABLED = saved


def test_hash_matches_bot_convention():
    import mizan_bot as mb
    assert f.hash_chat_id(42) == mb._hash_telegram_id(42)


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
