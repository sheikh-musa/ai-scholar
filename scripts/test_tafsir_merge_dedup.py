#!/usr/bin/env python3
"""Unit tests for mizan_bot._tafsir_merge_key — cross-path dedup of the
FTS+semantic tafsir union.

Regression guard for two bugs found 2026-07-08:
  1. Disjoint-key bug: FTS and semantic tafsir paths return the SAME corpus with
     DISJOINT identifiers (FTS: scholar/surah/ayah, no entry id; semantic:
     tafsir_entry_id, no surah/ayah), so keying them separately meant the same
     passage from both paths appeared twice (once as "Surah (unknown):?").
  2. Over-merge risk (surfaced by an end-to-end smoke sweep): an intermediate
     english_text-prefix key would collapse two DIFFERENT ayat that share a
     scholar's boilerplate opening (e.g. Ibn Kathir's "…which was revealed in
     Makkah…").

The key is now the natural unique key (scholar, surah, ayah) — the corpus has
exactly one tafsir row per (ayah_id, scholar), and semantic ayah_id is resolved
to surah:ayah before the merge so both paths share coords. It falls back to
scholar+text-prefix only when coords are unavailable.

Pure offline. Run:  python3 scripts/test_tafsir_merge_dedup.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))

import mizan_bot as mb  # noqa: E402

key = mb._tafsir_merge_key
PASSAGE = "The Throne Verse establishes Allah's absolute sovereignty over the heavens..."


def test_same_passage_across_paths_collides():
    # FTS carries (scholar, surah, ayah); semantic's ayah_id is resolved to the
    # same (surah, ayah) before the key is computed — so both key identically.
    assert key("Ibn Kathir", 2, 255, PASSAGE) == key("ibn kathir", 2, 255, "different snippet text")


def test_different_ayah_distinct():
    assert key("Ibn Kathir", 2, 255, PASSAGE) != key("Ibn Kathir", 2, 256, PASSAGE)


def test_same_ayah_different_scholar_kept():
    assert key("Ibn Kathir", 2, 255, PASSAGE) != key("Al-Sa'di", 2, 255, PASSAGE)


def test_boilerplate_prefix_does_not_over_merge():
    # THE over-merge guard: two DIFFERENT ayat whose tafsir shares a long
    # boilerplate opening must stay distinct (a text-prefix key would collapse them).
    boiler = "Which was revealed in Makkah and it is a Makki surah consisting of several verses that..."
    assert key("Ibn Kathir", 106, 2, boiler) != key("Ibn Kathir", 50, 4, boiler)


def test_coord_fallback_to_text_when_unresolved():
    # When ayah coords are unavailable (ayah_id resolution failed), fall back to
    # scholar + text prefix so within-path dedup still works.
    k = key("Ibn Kathir", None, None, PASSAGE)
    assert k == ("ibn kathir", " ".join(PASSAGE.split())[:120].lower())
    # same unresolved passage dedups; a different one does not
    assert key("Ibn Kathir", None, None, PASSAGE) == key("Ibn Kathir", None, None, PASSAGE)
    assert key("Ibn Kathir", None, None, PASSAGE) != key("Ibn Kathir", None, None, "On riba and its consequences...")


def test_missing_scholar_safe():
    assert key(None, 1, 1, "") == ("", "1", "1")


def test_dedup_over_a_mixed_list():
    # FTS hit + semantic hit (already resolved to same coords) + a distinct scholar.
    items = [
        ("Ibn Kathir", 2, 255, PASSAGE),        # fts
        ("Ibn Kathir", 2, 255, "snippet form"),  # sem, same ayah -> dedup
        ("Al-Sa'di", 2, 255, PASSAGE),           # distinct scholar -> kept
    ]
    seen, merged = set(), []
    for args in items:
        k = key(*args)
        if k in seen:
            continue
        seen.add(k)
        merged.append(args)
    assert len(merged) == 2


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
