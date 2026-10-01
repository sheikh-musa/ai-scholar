#!/usr/bin/env python3
"""Live-CLI test for the 'comparative' madhab-tag fix (op#24450 msg #48433).

Excluded from fast CI (hits the real Claude CLI, like test_mizan_bot_e2e.py)
— run manually: python3 scripts/test_comparative_madhhab_attribution.py

Verifies: when a FIQH MATCHED PASSAGES entry is tagged
"School (madhhab): comparative" and its own text names multiple schools by
position, the synthesis attributes each specific ruling to the school the
PASSAGE names, not to "comparative" (or to whichever school a DIFFERENT
single-madhhab entry nearby happens to carry). This is the exact mislabeling
risk the earlier "stop mislabeling matn as Shafi'i" bug (efa4370) covered for
single-madhhab entries, now extended to multi-madhhab comparative sources
(Bidayat al-Mujtahid, ingested op#24450).

The passage below is REAL content (an excerpt of Bidayat al-Mujtahid's actual
mash al-ra's / wiping-the-head discussion, already verified against the live
source during the op#24450 proof) — not fabricated fiqh, so this doubles as a
content-accuracy spot check.
"""
import os
import sys

os.environ.setdefault("MIZAN_BOT_TOKEN", "test-unused")
os.environ["MIZAN_TEST_MODE"] = "1"
os.environ.setdefault("ENCODER_URL", "http://127.0.0.1:8080")
os.environ.pop("ANTHROPIC_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mizan_bot import ask_claude, build_keyed_answer  # noqa: E402

COMPARATIVE_PASSAGE = """\
The Sixth Question, on Delimitation. The scholars agreed that wiping the head is \
among the fara'id of wudu, and disagreed on the amount that suffices of it. Malik \
held that wiping all of it is obligatory. Al-Shafi'i, some of Malik's companions, \
and Abu Hanifa held that wiping part of it is the obligation. Among Malik's \
companions, some limited this part to a third and some limited it to two thirds. \
Abu Hanifa limited it to a quarter, and together with this amount he also set a \
limit on the part of the hand with which one wipes, saying that if he wipes with \
less than three fingers it does not suffice him. Al-Shafi'i set no limit on \
either the wiping hand or the wiped part."""

CONTEXT = (
    "FIQH MATCHED PASSAGES (juridical matn from the ingested primers; "
    "schools present: comparative. Each passage is "
    "labelled with its own School (madhhab) — attribute to THAT school, "
    "never relabel it. If a passage's School (madhhab) is 'comparative' "
    "(a muqāran/multi-school survey work), do not attribute its content "
    "to that label as a whole — identify and attribute each specific "
    "ruling to the actual school the passage's own text names for it. "
    "RETRIEVE-ONLY echo. Compose-layer synthesis "
    "FORBIDDEN per C4 + INV-7 paired-scholar gate: quote matn verbatim "
    "with attribution, do NOT issue a ruling; the user must consult a "
    "qualified scholar of the relevant school for application to their "
    "case.):\n\n"
    "Source: Bidāyat al-Mujtahid wa Nihāyat al-Muqtaṣid\n"
    "Chapter: Kitāb al-Wuḍūʾ (comparative, mash al-ra's)\n"
    "School (madhhab): comparative\n"
    "Translator: Claude sonnet auto-translation (OpenITI JK000222-ara1)\n"
    "Tier: ai-generated\n"
    f"Passage:\n{COMPARATIVE_PASSAGE}"
)

QUERY = "what is the difference between the schools on wiping the head in wudu"

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    PASS += 1 if cond else 0
    FAIL += 0 if cond else 1


if __name__ == "__main__":
    answer = ask_claude(QUERY, CONTEXT, None, answer_level="seeker", madhhab=None,
                         fallback_answer=build_keyed_answer(QUERY))
    print("\n--- ANSWER ---\n" + answer + "\n--- END ---\n")

    lower = answer.lower()
    check("mentions Malik", "malik" in lower)
    check("mentions Shafi'i", "shafi" in lower)
    check("mentions Hanafi", "hanaf" in lower)
    check("Hanafi's quarter limit is attributed to Hanafi, not elsewhere",
          "quarter" in lower)
    check("does NOT collapse the whole passage into one school "
          "(no 'the comparative school' / 'comparative madhhab' phrasing)",
          "comparative school" not in lower and "comparative madhhab" not in lower)

    print(f"\n{'ALL PASS' if FAIL == 0 else 'FAILURES PRESENT'}: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
