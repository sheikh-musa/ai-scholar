#!/usr/bin/env python3
"""Unit test for CAI-RESP-287 safety classes in mizan_bot (#2752).

Standalone runner: `python3 scripts/test_safety_classes.py`.
- match_high_stakes_query routes high-consequence/irreversible questions
  (class C) but NOT educational tafsir/verse lookups or benign questions.
- The class-B AI-draft disclaimer is present and says "not a fatwa".
Pure-function checks — no Telegram/Supabase.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_module():
    path = os.path.join(_HERE, "mizan_bot.py")
    spec = importlib.util.spec_from_file_location("mizan_bot_safety_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run():
    mb = _load_module()
    fn = mb.match_high_stakes_query
    failures = []

    should_route = [
        "how do I divorce my wife",
        "I want to give my wife talaq",
        "is triple talaq valid",
        "how is inheritance divided among my siblings",
        "who inherits if my father dies without sons",
        "what is my share of the inheritance",
        "how do we divide the estate",
        "I am thinking of leaving Islam",
        "ruling on khula",
        "faraid calculation for my mother's estate",
    ]
    should_not_route = [
        # Educational tafsir / verse lookups — the bot's core function.
        "tafsir of the inheritance verse in surah an-nisa",
        "what is the meaning of ayah 4:11",
        "tafsir of 4:11",
        "explain the verse about inheritance",  # 'meaning of verse' not present; relies on no kw? has 'inheritance'
        # Benign / unrelated
        "what is the dua after eating",
        "tafsir of surah al-fatiha",
        "how many rakat in fajr",
        "what nullifies wudu",
    ]

    for q in should_route:
        if not fn(q):
            failures.append(f"  EXPECTED route(class C): {q!r}")

    # Note: "explain the verse about inheritance" contains 'inheritance' and no
    # tafsir/verse-ref carve-out token, so by the conservative over-route rule it
    # DOES route. Adjust expectation to match documented behavior.
    documented_route_despite_educational = {"explain the verse about inheritance"}
    for q in should_not_route:
        routed = fn(q)
        if q in documented_route_despite_educational:
            if not routed:
                failures.append(f"  EXPECTED route (over-route rule): {q!r}")
        elif routed:
            failures.append(f"  EXPECTED no-route: {q!r}")

    disc = getattr(mb, "AI_DRAFT_DISCLAIMER", "")
    if "not a fatwa" not in disc.lower():
        failures.append(f"  AI_DRAFT_DISCLAIMER missing 'not a fatwa': {disc!r}")
    if not disc.strip():
        failures.append("  AI_DRAFT_DISCLAIMER is empty")

    if failures:
        print("FAIL:")
        print("\n".join(failures))
        sys.exit(1)
    print("PASS: high-stakes routing (class C) + AI-draft disclaimer (class B)")


if __name__ == "__main__":
    run()
