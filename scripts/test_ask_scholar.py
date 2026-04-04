#!/usr/bin/env python3
"""
Test script for the ask-scholar Supabase Edge Function.

Usage:
    python scripts/test_ask_scholar.py

Requires SUPABASE_URL and SUPABASE_ANON_KEY env vars (or uses defaults for
the ai-scholar project: tscuymavysscrvoberrr).
"""

import json
import os
import sys
import requests

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co"
)
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

ENDPOINT = f"{SUPABASE_URL}/functions/v1/ask-scholar"


def call_ask_scholar(question: str) -> dict:
    """POST a question to the ask-scholar edge function."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    resp = requests.post(
        ENDPOINT,
        json={"question": question},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def print_result(label: str, question: str, result: dict):
    """Pretty-print a test result."""
    print(f"\n{'=' * 60}")
    print(f"TEST: {label}")
    print(f"Question: {question}")
    print(f"{'=' * 60}")
    print(json.dumps(result, indent=2, ensure_ascii=False)[:2000])

    # Quick assertions
    if result.get("scholar_gate"):
        print(f"  -> SCHOLAR GATE triggered")
        assert "message" in result, "Missing 'message' in scholar gate response"
        assert "suggested_resources" in result, "Missing 'suggested_resources'"
    elif result.get("matches") is not None:
        n = len(result["matches"])
        print(f"  -> {n} match(es) returned")
        if n > 0:
            m = result["matches"][0]
            assert "surah" in m, "Missing 'surah' in match"
            assert "ayah" in m, "Missing 'ayah' in match"
            assert "arabic" in m, "Missing 'arabic' in match"
            assert "translation" in m, "Missing 'translation' in match"
            assert "tafsir" in m, "Missing 'tafsir' in match"
            print(f"     First: {m['surah_name']} {m['surah']}:{m['ayah']}")
        assert "practice_offramp" in result, "Missing 'practice_offramp'"
        assert "tiers_used" in result, "Missing 'tiers_used'"
    elif "error" in result:
        print(f"  -> ERROR: {result['error']}")
    print("  -> PASS")


def main():
    if not SUPABASE_ANON_KEY:
        print("ERROR: Set SUPABASE_ANON_KEY env var before running tests.")
        print("  export SUPABASE_ANON_KEY='your-anon-key-here'")
        sys.exit(1)

    tests = [
        # Topic match tests
        ("Topic: patience", "What does Islam say about patience?"),
        ("Topic: gratitude", "Tell me about gratitude in the Quran"),
        ("Topic: tawakkul (synonym: trust)", "What does the Quran say about trust in Allah?"),

        # Verse reference test
        ("Verse reference", "2:153"),
        ("Verse reference (words)", "surah 2 ayah 153"),

        # Scholar gate tests (fiqh keywords)
        ("Scholar gate: halal keyword", "Is music halal?"),
        ("Scholar gate: haram keyword", "Is interest haram in Islam?"),
        ("Scholar gate: ruling phrase", "What is the ruling on fasting?"),
        ("Scholar gate: permissible phrase", "Is it permissible to eat gelatin?"),
        ("Scholar gate: can I phrase", "Can I take a loan in Islam?"),

        # Fallback / FTS test
        ("FTS fallback: mercy", "mercy"),
        ("FTS fallback: light", "light and darkness"),

        # No match (unlikely topic)
        ("No match test", "quantum entanglement blockchain"),
    ]

    passed = 0
    failed = 0

    for label, question in tests:
        try:
            result = call_ask_scholar(question)
            print_result(label, question, result)
            passed += 1
        except Exception as e:
            print(f"\n{'=' * 60}")
            print(f"FAIL: {label}")
            print(f"Question: {question}")
            print(f"Error: {e}")
            print(f"{'=' * 60}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 60}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
