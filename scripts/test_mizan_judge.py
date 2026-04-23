#!/usr/bin/env python3
"""
Unit tests for mizan_judge.py — the pure functions (parse, normalize,
agreement math). Does not touch Supabase or Claude CLI.

Run:
  python3 -m pytest scripts/test_mizan_judge.py -v
  # or standalone
  python3 scripts/test_mizan_judge.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mizan_judge import parse_judge_output, pearson, _normalize_scores, RUBRIC_AXES  # noqa: E402


# ---------------------------------------------------------------------------
# parse_judge_output
# ---------------------------------------------------------------------------


def test_parse_direct_json():
    raw = """{
      "tier_integrity": 4, "source_attribution": 5, "scholar_humility": 3,
      "ikhtilaf_surface": 4, "ilm_amal_link": 4, "fitnah_avoidance": 5,
      "hallucination": 0, "aqeedah_integrity": 5,
      "composite_score": 3.75, "auto_flagged": false,
      "judge_rationale": "Solid retrieval with clear attribution."
    }"""
    out = parse_judge_output(raw)
    assert out is not None
    assert out["tier_integrity"] == 4
    assert out["hallucination"] == 0
    assert out["auto_flagged"] is False
    assert out["composite_score"] == 3.75


def test_parse_with_preamble():
    raw = """Here is my evaluation:

    {
      "tier_integrity": 3, "source_attribution": 3, "scholar_humility": 3,
      "ikhtilaf_surface": 3, "ilm_amal_link": 3, "fitnah_avoidance": 3,
      "hallucination": 0, "aqeedah_integrity": 3,
      "composite_score": 3.0, "auto_flagged": false,
      "judge_rationale": "Average across all axes."
    }
    """
    out = parse_judge_output(raw)
    assert out is not None
    assert out["composite_score"] == 3.0


def test_parse_hallucination_triggers_auto_flag():
    raw = """{
      "tier_integrity": 5, "source_attribution": 4, "scholar_humility": 4,
      "ikhtilaf_surface": 5, "ilm_amal_link": 4, "fitnah_avoidance": 5,
      "hallucination": 2, "aqeedah_integrity": 5,
      "composite_score": 4.25, "auto_flagged": false,
      "judge_rationale": "Two fabricated isnads detected."
    }"""
    # Judge said auto_flagged=false but hallucination=2 — normalizer overrides
    out = parse_judge_output(raw)
    assert out is not None
    assert out["auto_flagged"] is True


def test_parse_missing_axis_returns_none():
    raw = """{"tier_integrity": 3, "source_attribution": 3}"""
    assert parse_judge_output(raw) is None


def test_parse_out_of_range_axis_returns_none():
    raw = """{
      "tier_integrity": 6, "source_attribution": 3, "scholar_humility": 3,
      "ikhtilaf_surface": 3, "ilm_amal_link": 3, "fitnah_avoidance": 3,
      "hallucination": 0, "aqeedah_integrity": 3,
      "composite_score": 3.0, "auto_flagged": false, "judge_rationale": ""
    }"""
    assert parse_judge_output(raw) is None


def test_parse_non_integer_axis_returns_none():
    raw = """{
      "tier_integrity": "high", "source_attribution": 3, "scholar_humility": 3,
      "ikhtilaf_surface": 3, "ilm_amal_link": 3, "fitnah_avoidance": 3,
      "hallucination": 0, "aqeedah_integrity": 3,
      "composite_score": 3.0, "auto_flagged": false, "judge_rationale": ""
    }"""
    assert parse_judge_output(raw) is None


def test_parse_missing_composite_derives_mean():
    # All axes 4, composite missing → mean 4.0
    raw = """{
      "tier_integrity": 4, "source_attribution": 4, "scholar_humility": 4,
      "ikhtilaf_surface": 4, "ilm_amal_link": 4, "fitnah_avoidance": 4,
      "hallucination": 0, "aqeedah_integrity": 4,
      "auto_flagged": false, "judge_rationale": ""
    }"""
    out = parse_judge_output(raw)
    assert out is not None
    # Mean with hallucination=0 is (4*7 + 0) / 8 = 3.5
    assert out["composite_score"] == 3.5


def test_parse_garbage_returns_none():
    assert parse_judge_output("I refuse to evaluate this.") is None
    assert parse_judge_output("") is None


# ---------------------------------------------------------------------------
# _normalize_scores (called by parse_judge_output)
# ---------------------------------------------------------------------------


def test_normalize_all_axes_present():
    scores = {a: 3 for a in RUBRIC_AXES}
    scores["composite_score"] = 3.0
    scores["auto_flagged"] = False
    scores["judge_rationale"] = "all threes"
    out = _normalize_scores(scores)
    assert out is not None
    assert all(out[a] == 3 for a in RUBRIC_AXES)


# ---------------------------------------------------------------------------
# Pearson correlation
# ---------------------------------------------------------------------------


def test_pearson_perfect_positive():
    assert abs(pearson([1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0, 5.0]) - 1.0) < 1e-9


def test_pearson_perfect_negative():
    assert abs(pearson([1.0, 2.0, 3.0, 4.0, 5.0], [5.0, 4.0, 3.0, 2.0, 1.0]) + 1.0) < 1e-9


def test_pearson_zero_correlation():
    # Constant ys ⇒ denominator zero ⇒ return 0.0 by design
    assert pearson([1.0, 2.0, 3.0, 4.0, 5.0], [3.0, 3.0, 3.0, 3.0, 3.0]) == 0.0


def test_pearson_length_mismatch():
    assert pearson([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_pearson_too_short():
    assert pearson([1.0], [1.0]) == 0.0


def test_pearson_strong_positive_real():
    # Judge composite vs scholar grade, should be around 0.85 for this set
    xs = [3.0, 3.5, 4.0, 4.0, 4.5, 2.5, 3.5, 4.0, 5.0, 3.0]
    ys = [3.0, 4.0, 4.0, 3.5, 5.0, 3.0, 4.0, 4.5, 5.0, 3.0]
    r = pearson(xs, ys)
    assert 0.80 < r < 0.95


# ---------------------------------------------------------------------------
# Standalone runner (if pytest unavailable)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
