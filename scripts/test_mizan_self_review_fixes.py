#!/usr/bin/env python3
"""Proof harness for the Python-side 40-answer self-review fixes (msg #10510).

Covers: Fix #1 (build_keyed_answer routing + not-found), Fix #2b (detect_dev_leak),
Fix #2c (MIZAN_TEST_MODE persist skip), Fix #5 (_matn_relevant_to_query gate).

Network-free: lookup_verse / lookup_hadith are monkeypatched. Fix #2a (--tools "")
is asserted by inspecting the ask_claude source (the CLI itself needs auth we don't
have here). Run: python3 scripts/test_mizan_self_review_fixes.py
"""
import os
import sys
import inspect

os.environ.setdefault("MIZAN_BOT_TOKEN", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import mizan_bot as mb  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    PASS += 1 if cond else 0
    FAIL += 0 if cond else 1


# ---------------------------------------------------------------------------
# Fix #2a — leak root cause: synthesis subprocess disables tools + neutral cwd
# ---------------------------------------------------------------------------
src = inspect.getsource(mb.ask_claude)
check("Fix#2a: ask_claude passes --tools \"\" to the CLI", '"--tools", ""' in src)
check("Fix#2a: ask_claude runs in neutral sandbox cwd (not the repo)",
      "cwd=_SYNTH_SANDBOX_DIR" in src)
check("Fix#2a: sandbox dir is not the repo root",
      os.path.abspath(mb._SYNTH_SANDBOX_DIR) != os.path.abspath(os.path.dirname(__file__) + "/.."))

# ---------------------------------------------------------------------------
# Fix #2b — dev-leak guard
# ---------------------------------------------------------------------------
# Real leak excerpts from review #10 / #11 / #18:
LEAKED = [
    "This looks like the same test/debug pass as the earlier query — you're "
    "exercising the modified, uncommitted `mizan_bot.py` prompt against retrieval.",
    "**Persona response (what Mizan would send):** ... **Retrieval flag:** the FTS "
    "match surfaced 6 unrelated Shafi'i matn blocks ... blowing past the 3900-char budget.",
    "Here's the response Al-Mīzān would send: ...",
    "Under the current prompt rule (\"you MUST surface the matn passage\") ...",
]
for i, txt in enumerate(LEAKED, 1):
    check(f"Fix#2b: leak sample #{i} is detected", mb.detect_dev_leak(txt) is not None)

# Real GOOD answers must NOT trip the guard (regression):
CLEAN = [
    "**Eating donkey meat is prohibited (ḥarām)** — established through multiple "
    "authentic hadith. 📖 *(Bukhari #4218 · ✅ Sahih · Ibn `Umar)*",
    "Wa ʿalaykum as-salām wa raḥmatullāhi wa barakātuh! 🌙 Salām is one of Allah's names.",
    "This is a fiqh question about prayer, so I can't issue a ruling — it needs a "
    "qualified scholar. On Qasr (Qur'an 4:101): ...",
    "Al-Fātiḥah means \"The Opening\" — the first chapter of the Qur'an, seven āyāt.",
]
for i, txt in enumerate(CLEAN, 1):
    marker = mb.detect_dev_leak(txt)
    check(f"Fix#2b: clean answer #{i} not flagged (got={marker!r})", marker is None)

# ---------------------------------------------------------------------------
# Fix #1 — build_keyed_answer routing (monkeypatched lookups, no network)
# ---------------------------------------------------------------------------
mb.lookup_verse = lambda s, a: {
    "surah": s, "ayah": a, "surah_name": "Al-Baqarah",
    "arabic": "ٱللَّهُ لَآ إِلَٰهَ إِلَّا هُوَ",
    "translation": "Allah — there is no deity except Him", "translator": "Sahih Intl",
    "tafsir": [{"scholar_name": "Ibn Kathir", "source_work": "Tafsir",
                "english_text": "The Greatest Verse ...", "output_tier": "paraphrased"}],
}
mb.lookup_hadith = lambda c, n: (
    {"error": "not found"} if str(n) == "35"
    else {"collection_full": "Sahih al-Bukhari", "grading": "sahih", "narrator": "Ibn Umar",
          "arabic_text": "…", "english_text": "The Prophet forbade donkey meat.",
          "collection": c})

# Ayatul Kursi (the #31/#32 timeout query) → keyed verse answer, no synthesis
ak = mb.build_keyed_answer("Generate ayatul kursi here with the tafsir")
check("Fix#1: 'ayatul kursi' routes to a keyed verse answer", ak is not None and "2:255" in ak)
check("Fix#1: keyed verse answer carries the quoted badge", ak is not None and "📖" in ak)

# Explicit surah:ayah
sa = mb.build_keyed_answer("tafsir of 2:255")
check("Fix#1: explicit 2:255 routes to keyed verse answer", sa is not None and "2:255" in sa)

# Bukhari 35 (the #33 timeout query) — genuinely absent → honest not-found (not None)
b35 = mb.build_keyed_answer("Bukhari 35")
check("Fix#1: 'Bukhari 35' (absent) → honest not-found, not a non-answer",
      b35 is not None and "numbering" in b35.lower())

# A present hadith → formatted answer with grade badge
b1 = mb.build_keyed_answer("bukhari 4218")
check("Fix#1: present hadith → keyed answer with grading badge",
      b1 is not None and "✅ Sahih" in b1)

# Non-lookup / ruling-class queries must NOT get a keyed answer
for q in ["is my asar prayed 5 minutes before maghrib azan valid?",
          "can i prey non stop", "what is tasawwuf"]:
    check(f"Fix#1: non-lookup query returns None ({q[:32]!r})", mb.build_keyed_answer(q) is None)

# ---------------------------------------------------------------------------
# Fix #5 — FTS-fallback relevance gate
# ---------------------------------------------------------------------------
fasting_matn = {"text": "The one who is fasting must avoid what nullifies the fast ...",
                "baab": "Kitab al-Siyam"}
khutbah_matn = {"text": "The pillars of the Friday khutbah are praising Allah ...",
                "baab": "Kitab al-Jumua"}
# genuine fiqh query keeps its matn
check("Fix#5: 'what nullifies the fast' keeps the fasting matn (rescue preserved)",
      mb._matn_relevant_to_query(fasting_matn, ["what", "nullifies", "fast"]))
# off-topic queries drop generic matn (review #10/#11)
check("Fix#5: 'coding software development' drops fasting matn",
      not mb._matn_relevant_to_query(fasting_matn, ["coding", "software", "development"]))
check("Fix#5: 'decode the quran' drops khutbah matn ('quran' is generic, not grounding)",
      not mb._matn_relevant_to_query(khutbah_matn, ["decode", "quran"]))

# ---------------------------------------------------------------------------
# Fix #2c — MIZAN_TEST_MODE skips persistence
# ---------------------------------------------------------------------------
_orig = mb.MIZAN_TEST_MODE
try:
    mb.MIZAN_TEST_MODE = True
    check("Fix#2c: persist_emission returns None (skips) under test mode",
          mb.persist_emission(123, "q", "a") is None)
finally:
    mb.MIZAN_TEST_MODE = _orig

print(f"\n{'ALL PASS' if FAIL == 0 else 'FAILURES PRESENT'}: {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
