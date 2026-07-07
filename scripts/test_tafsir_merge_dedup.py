#!/usr/bin/env python3
"""Unit tests for mizan_bot._tafsir_merge_key — cross-path dedup of the
FTS+semantic tafsir union.

Regression guard for the disjoint-key bug fixed 2026-07-08: the FTS and
semantic tafsir paths return the SAME corpus with DISJOINT identifiers (FTS:
scholar/surah/ayah, no entry id; semantic: tafsir_entry_id, no surah/ayah), so
the old key (tafsir_entry_id OR (scholar, surah, ayah)) keyed them in different
spaces and the same passage surfaced by both paths appeared TWICE in context —
once degraded as "Surah (unknown):?". The key now uses the fields both paths
share (normalized scholar + english_text prefix).

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

PASSAGE = ("The Throne Verse establishes Allah's absolute sovereignty over the "
           "heavens and the earth, His eternal life and self-subsistence...")

# FTS-shaped row (search_tafsir): scholar/surah/ayah, no tafsir_entry_id.
FTS = {"scholar": "Ibn Kathir", "surah": 2, "ayah": 255, "english_text": PASSAGE}
# Semantic-shaped row (tafsir_semantic): tafsir_entry_id/scholar_name, no numbers.
SEM = {"scholar_name": "Ibn Kathir", "tafsir_entry_id": "uuid-abc",
       "ayah_id": "uuid-xyz", "english_text": PASSAGE}


def test_same_passage_across_paths_collides():
    # The whole point: FTS and semantic hits of the same passage dedup to one.
    assert key(FTS) == key(SEM)


def test_different_passage_distinct():
    other = {"scholar_name": "Ibn Kathir",
             "english_text": "On the prohibition of riba and its consequences..."}
    assert key(FTS) != key(other)


def test_same_text_different_scholar_kept():
    # Two scholars' commentary on the same ayah are distinct hits — must NOT merge.
    saadi = {"scholar": "Al-Sa'di", "english_text": PASSAGE}
    assert key(FTS) != key(saadi)


def test_scholar_field_name_normalized():
    # 'scholar' (FTS) and 'scholar_name' (semantic) are treated as the same field.
    assert key({"scholar": "Ibn Kathir", "english_text": PASSAGE}) == \
           key({"scholar_name": "ibn kathir", "english_text": PASSAGE})


def test_whitespace_normalized():
    a = {"scholar": "X", "english_text": "the  throne   verse\nestablishes"}
    b = {"scholar": "X", "english_text": "the throne verse establishes"}
    assert key(a) == key(b)


def test_missing_fields_safe():
    assert key({}) == ("", "")
    assert key({"scholar": "X"}) == ("x", "")


def test_dedup_over_a_mixed_list():
    # Simulate the merge loop's dedup and assert the duplicate collapses.
    rows = [FTS, SEM, {"scholar": "Al-Sa'di", "english_text": PASSAGE}]
    seen, merged = set(), []
    for r in rows:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        merged.append(r)
    assert len(merged) == 2  # Ibn Kathir (deduped across paths) + Al-Sa'di


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
