#!/usr/bin/env python3
"""Unit tests for mizan_bot._evidence_fallback — the post-timeout, no-LLM
answer built from retrieval that already succeeded (#6489).

Regression guard for the fallback gap fixed 2026-07-08: search blocks are
serialized as {"results": [...]} with *_number / arabic_text /
english_translation keys, and were silently dropped by the earlier parser
(which only recognised direct verse-lookup rows: arabic/translation/surah/
ayah). Since the timeout class the fallback exists for is precisely the
heavy-retrieval (search-driven) case, dropping those blocks left users with
the generic "send again" stub — the very dead-end the fix set out to remove.

Pure offline: no Supabase, no Claude CLI.

Run:
  python3 scripts/test_evidence_fallback.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))

import mizan_bot as mb  # noqa: E402


def _ctx(*blocks) -> str:
    return "\n\n---\n\n".join(blocks)


def _quran_search_block() -> str:
    # Real search_quran shape: results-wrapped, *_number / arabic_text /
    # english_translation.
    payload = {"results": [{
        "surah_number": 2, "ayah_number": 152, "surah_name": "Al-Baqarah",
        "arabic_text": "فَٱذْكُرُونِىٓ أَذْكُرْكُمْ",
        "english_translation": "So remember Me; I will remember you.",
    }]}
    return "QURAN SEARCH:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _tafsir_search_block() -> str:
    payload = {"results": [{
        "surah_number": 2, "ayah_number": 152, "scholar_name": "Ibn Kathir",
        "english_text": "This ayah commands the remembrance of Allah (dhikr).",
    }]}
    return "TAFSIR for 2:152:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _verse_lookup_block() -> str:
    # Direct verse-lookup shape: arabic / translation / surah / ayah.
    payload = {
        "surah": 2, "ayah": 255, "surah_name": "Al-Baqarah",
        "arabic": "ٱللَّهُ لَآ إِلَـٰهَ إِلَّا هُوَ",
        "translation": "Allah - there is no deity except Him...",
    }
    return "VERSE LOOKUP 2:255:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def test_search_block_surfaces_arabic_and_ref():
    out = mb._evidence_fallback("remembrance of Allah", _ctx(_quran_search_block()))
    assert "2:152" in out, out
    assert "فَٱذْكُرُونِىٓ" in out, "arabic from results-wrapped search row must surface"
    assert "So remember Me" in out
    assert "send it again" not in out


def test_tafsir_search_block_surfaces():
    out = mb._evidence_fallback("remembrance", _ctx(_tafsir_search_block()))
    assert "Ibn Kathir" in out, out
    assert "remembrance of Allah" in out


def test_direct_verse_lookup_still_surfaces():
    out = mb._evidence_fallback("ayat al kursi", _ctx(_verse_lookup_block()))
    assert "2:255" in out
    assert "ٱللَّهُ لَآ إِلَـٰهَ" in out


def test_all_three_together():
    out = mb._evidence_fallback(
        "remembrance of Allah",
        _ctx(_quran_search_block(), _tafsir_search_block(), _verse_lookup_block()),
    )
    for needle in ("2:152", "Ibn Kathir", "2:255"):
        assert needle in out, f"missing {needle} in fallback output"
    assert "not a ruling" in out  # F-3 disclaimer retained


def test_empty_context_returns_honest_stub_no_crash():
    out = mb._evidence_fallback("q", "")
    assert "send it again" in out


def test_unparseable_context_returns_honest_stub():
    out = mb._evidence_fallback("q", "FIQH: just prose, no json\n\n---\n\nmore prose")
    assert "send it again" in out


def test_output_stays_within_telegram_budget():
    # Many large blocks must not blow past a sane message length.
    big = "\n\n---\n\n".join(_quran_search_block() for _ in range(20))
    out = mb._evidence_fallback("x", big)
    assert len(out) < 4096, f"fallback output {len(out)} chars exceeds Telegram limit"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
