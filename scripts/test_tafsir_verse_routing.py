#!/usr/bin/env python3
"""Verify natural-language tafsir verse references route to a KEYED lookup, not
keyword/semantic fallthrough (operator tafsir miss #2613/#2615).

Root cause was: a verse reference is a structured key, but only the colon `S:A`
form reached lookup_verse(). Natural-language refs ("Surah 94 ayah 7 and 8",
"last 2 ayat of al insyirah") fell through to keyword FTS + semantic similarity,
which structurally cannot retrieve a verse by number (measured cosine ~0.20-0.28,
all wrong ayat) — so the bot correctly refused, leaving an empty answer.

This test covers the deterministic parse/routing layer (no DB/encoder needed).
Run: python3 scripts/test_tafsir_verse_routing.py
"""
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="mizan_test_home_")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import mizan_bot as mb  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    if not cond:
        failures.append(name)


def resolve_surah(q):
    """Mirror gather_context's surah-resolution order: alias, then numeric."""
    alias = mb.match_surah_alias(q)
    if isinstance(alias, tuple):
        return alias[0]
    if isinstance(alias, int):
        return alias
    m = re.search(r'\bsurah\s+(\d{1,3})\b', q.lower())
    if m and 1 <= int(m.group(1)) <= 114:
        return int(m.group(1))
    return None


# --- The two production failures now resolve to surah 94, ayat 7 & 8 ---
check("'Surah 94 ayah 7 and 8' -> surah 94", resolve_surah("tafsir of Surah 94 ayah 7 and 8") == 94)
check("'Surah 94 ayah 7 and 8' -> ayat [7,8]",
      mb.extract_ayah_numbers("tafsir of surah 94 ayah 7 and 8", 94) == [7, 8])

check("'al insyirah' alias -> surah 94", resolve_surah("tafsir of last 2 ayat of al insyirah") == 94)
check("'al-inshirah' (2nd name) alias -> surah 94", resolve_surah("tafsir of al-inshirah") == 94)
check("'insyirah' (Malay spelling) alias -> surah 94", resolve_surah("insyirah") == 94)
# 'last 2 ayat' needs DB for surah length; only assert it's a 2-element tail if DB reachable.
try:
    last2 = mb.extract_ayah_numbers("tafsir of last 2 ayat of al insyirah", 94)
    if last2:  # DB reachable
        check("'last 2 ayat' of surah 94 -> [7,8]", last2 == [7, 8])
    else:
        print("SKIP  'last 2 ayat' (DB unreachable — surah length query returned empty)")
except Exception as e:
    print(f"SKIP  'last 2 ayat' (DB error: {e})")

# --- Ayah-spec extraction variants ---
check("'ayah 7' -> [7]", mb.extract_ayah_numbers("ayah 7", 1) == [7])
check("'verses 7-8' -> [7,8]", mb.extract_ayah_numbers("verses 7-8", 1) == [7, 8])
check("'ayat 7 to 9' -> [7,8,9]", mb.extract_ayah_numbers("ayat 7 to 9", 1) == [7, 8, 9])
check("'first 3 verses' -> [1,2,3]", mb.extract_ayah_numbers("first 3 verses", 1) == [1, 2, 3])
check("oversized range collapses to endpoints",
      mb.extract_ayah_numbers("ayat 1 to 50", 2) == [1, 50])

# --- Regressions: existing paths must be untouched ---
check("colon '2:186' still NOT name-resolved (handled by colon path)", resolve_surah("tafsir 2:186") is None)
check("canonical 'Ash-Sharh' still resolves to 94", resolve_surah("tafsir of Ash-Sharh") == 94)
check("named surah w/o ayah -> no spurious ayah numbers",
      mb.extract_ayah_numbers("tafsir of ash-sharh", 94) == [])

# --- False-positive guard: non-verse phrasings extract nothing ---
check("'ruling on combining prayers' -> no ayah", mb.extract_ayah_numbers("what is the ruling on combining prayers", 1) == [])
check("'how many times is patience mentioned' -> no ayah",
      mb.extract_ayah_numbers("how many times is patience mentioned", 1) == [])

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL PASS")
