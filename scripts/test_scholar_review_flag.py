#!/usr/bin/env python3
"""Unit test for the scholar-review flag-button keyboard wiring (#2746).

Standalone runner: `python3 scripts/test_scholar_review_flag.py`.
Verifies the flag row is present iff an interaction_id is supplied, carries the
correct callback_data, and that the review-export helpers exist and are callable.
Does NOT hit Telegram or Supabase — pure keyboard-shape + symbol checks.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_module():
    path = os.path.join(_HERE, "mizan_bot.py")
    spec = importlib.util.spec_from_file_location("mizan_bot_review_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # guarded under __main__, safe to import
    return mod


def _flag_rows(kb):
    return [row for row in kb["inline_keyboard"]
            for btn in row if btn.get("callback_data", "").startswith("flag:")]


def run():
    mb = _load_module()
    failures = []

    # 1. No interaction_id -> no flag button.
    kb_none = mb._level_keyboard("seeker", cited_verses=[(94, 7)])
    if _flag_rows(kb_none):
        failures.append("  flag button present when interaction_id is None")

    # 2. With interaction_id -> exactly one flag button, correct callback_data.
    iid = "4059b3b4-005f-4f92-a007-caa259ad9c1d"
    kb = mb._level_keyboard("seeker", cited_verses=[(94, 7)], interaction_id=iid)
    flags = [btn for row in kb["inline_keyboard"]
             for btn in row if btn.get("callback_data", "").startswith("flag:")]
    if len(flags) != 1:
        failures.append(f"  expected 1 flag button, got {len(flags)}")
    else:
        if flags[0]["callback_data"] != f"flag:{iid}":
            failures.append(f"  bad callback_data: {flags[0]['callback_data']!r}")
        if len(flags[0]["callback_data"].encode()) > 64:
            failures.append("  callback_data exceeds Telegram's 64-byte limit")
        if "review" not in flags[0]["text"].lower():
            failures.append(f"  flag button label unclear: {flags[0]['text']!r}")

    # 3. Flag button is the LAST row (below level + audio rows).
    last_row = kb["inline_keyboard"][-1]
    if not (len(last_row) == 1 and last_row[0]["callback_data"].startswith("flag:")):
        failures.append("  flag button is not the final row")

    # 4. Level + audio rows preserved alongside the flag row.
    if not any(btn.get("callback_data", "").startswith("level:")
               for row in kb["inline_keyboard"] for btn in row):
        failures.append("  level buttons lost when flag button added")
    if not any(btn.get("callback_data", "").startswith("audio:")
               for row in kb["inline_keyboard"] for btn in row):
        failures.append("  audio buttons lost when flag button added")

    # 5. Review-loop helpers exist and are callable.
    for name in ("toggle_review_flag", "handle_review_export",
                 "_send_document", "_maybe_add_flag_button", "supabase_patch",
                 "_load_env_file"):
        if not callable(getattr(mb, name, None)):
            failures.append(f"  missing/non-callable helper: {name}")

    if failures:
        print("FAIL:")
        print("\n".join(failures))
        sys.exit(1)
    print("PASS: flag-button keyboard wiring + review-loop helpers")


if __name__ == "__main__":
    run()
