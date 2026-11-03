#!/usr/bin/env python3
"""Fail if MAP.md cites a repo-relative path that no longer exists.

Keeps MAP.md honest as the codebase changes: every backtick-quoted token
that looks like a repo-relative path (contains a "/") is resolved against
the repo root and must exist, unless it's an absolute path outside the
repo (a deployed-secrets location, a home-dir script) or a placeholder/glob
("<name>", "test_*.py") that doesn't name one concrete file.
"""
from __future__ import annotations

import glob
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_PATH = os.path.join(REPO_ROOT, "MAP.md")

# Leading command words to strip before the path portion of a backtick span.
_COMMAND_PREFIXES = [
    "bash ", "python3 ", "node --test ", "deno test --allow-all ",
    "git log -1 -- ", "supabase functions deploy ",
]


def _is_outside_repo(token: str) -> bool:
    return token.startswith("~") or token.startswith("/dev/") or (
        token.startswith("/") and not token.startswith(REPO_ROOT)
    )


def extract_candidates(text: str) -> list[str]:
    candidates = []
    for span in re.findall(r"`([^`]+)`", text):
        for word in span.split():
            for prefix in _COMMAND_PREFIXES:
                if word == prefix.strip() or span.startswith(prefix):
                    word = span[len(prefix):].strip()
                    break
            if "/" not in word:
                continue
            word = word.rstrip(".,;:)")
            candidates.append(word)
    return candidates


def check(token: str) -> str | None:
    """Return an error string if token names a path that should exist but doesn't."""
    if _is_outside_repo(token):
        return None
    if "<" in token:
        return None  # placeholder, e.g. supabase/functions/<name>
    if "*" in token:
        matches = glob.glob(os.path.join(REPO_ROOT, token))
        return None if matches else f"glob matches nothing: {token}"
    full = os.path.join(REPO_ROOT, token.rstrip("/"))
    if not os.path.exists(full):
        return f"path does not exist: {token}"
    return None


def main() -> int:
    with open(MAP_PATH, encoding="utf-8") as f:
        text = f.read()
    errors = []
    for token in extract_candidates(text):
        err = check(token)
        if err:
            errors.append(err)
    if errors:
        print(f"MAP.md cites {len(errors)} path(s) that don't resolve:", file=sys.stderr)
        for e in sorted(set(errors)):
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("MAP.md: all cited paths resolve OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
