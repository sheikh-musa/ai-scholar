#!/usr/bin/env python3
"""Unit tests for mizan_bot._resolve_ayah_ids — the batched ayah_id → surah:ayah
resolver that makes semantic-only tafsir hits citable (instead of the degraded
"Surah (unknown) : Ayah ?"). Added 2026-07-08.

Offline: stubs mizan_bot.supabase_get so no DB is touched (CI has no service key).
Run:  python3 scripts/test_ayah_id_resolve.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))

import mizan_bot as mb  # noqa: E402


class _Stub:
    """Swap mizan_bot.supabase_get for a controlled fake for the duration of a test."""
    def __init__(self, impl):
        self.impl = impl

    def __enter__(self):
        self._orig = mb.supabase_get
        mb.supabase_get = self.impl
        return self

    def __exit__(self, *a):
        mb.supabase_get = self._orig


ROWS = [
    {"id": "id-1", "surah_number": 2, "ayah_number": 255},
    {"id": "id-2", "surah_number": 1, "ayah_number": 1},
]


def test_resolves_ids_to_surah_ayah():
    with _Stub(lambda tbl, params: ROWS):
        m = mb._resolve_ayah_ids(["id-1", "id-2"])
    assert m == {"id-1": (2, 255), "id-2": (1, 1)}


def test_dedupes_and_filters_none_before_query():
    seen = {}

    def fake(tbl, params):
        seen["filter"] = params["id"]
        return ROWS

    with _Stub(fake):
        mb._resolve_ayah_ids(["id-1", "id-1", None, "id-2", None])
    # "id-1" appears once; None dropped.
    assert seen["filter"] == "in.(id-1,id-2)"


def test_empty_input_makes_no_query():
    called = {"n": 0}

    def fake(tbl, params):
        called["n"] += 1
        return []

    with _Stub(fake):
        assert mb._resolve_ayah_ids([]) == {}
        assert mb._resolve_ayah_ids([None, None]) == {}
    assert called["n"] == 0  # never hit the DB when there's nothing to resolve


def test_error_returns_empty_map_not_raise():
    def boom(tbl, params):
        raise RuntimeError("network down")

    with _Stub(boom):
        assert mb._resolve_ayah_ids(["id-1"]) == {}  # fallback to unknown, never crash


def test_partial_resolution_ok():
    # DB returns only one of two requested ids — map has just that one; caller
    # falls back to unknown for the missing one.
    with _Stub(lambda tbl, params: [ROWS[0]]):
        m = mb._resolve_ayah_ids(["id-1", "id-missing"])
    assert m == {"id-1": (2, 255)}
    assert "id-missing" not in m


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
