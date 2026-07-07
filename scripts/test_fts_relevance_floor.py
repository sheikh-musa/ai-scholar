#!/usr/bin/env python3
"""Unit tests for mizan_bot._fts_topical — the coverage-based FTS relevance
floor (#6489).

ts_rank is not a usable cross-query relevance floor (a legit low-frequency
hit can rank below off-topic noise), so the floor is coverage-based: keep an
FTS hit only if the matched text carries a DISTINCTIVE (non-generic) query
term, or >= 2 query terms. This gate sits on the retrieval path and decides
which FTS rows survive into synthesis, so its contract is load-bearing —
a false-keep reintroduces the "prevent"->"prevent death" noise the floor
exists to kill; a false-drop can strip a legitimate answer.

Pure offline. Run:  python3 scripts/test_fts_relevance_floor.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).parent))

import mizan_bot as mb  # noqa: E402

topical = mb._fts_topical


def test_generic_only_overlap_is_dropped():
    # The canonical bug: "do eyelash extensions prevent wudhu" matched Al-'Imran
    # 3:168 ("...prevent death...") on the generic word "prevent" alone.
    words = ["eyelash", "extensions", "prevent", "wudhu"]
    text = "Do not think those slain for Allah are dead. They prevent the death of the soul."
    assert topical(words, text) is False


def test_single_generic_word_is_dropped():
    assert topical(["prevent"], "they prevent death") is False


def test_distinctive_term_present_is_kept():
    assert topical(["riba"], "Those who consume riba will not stand.") is True


def test_two_content_terms_present_is_kept():
    words = ["combining", "prayers", "travelling"]
    text = "The traveller may combine the prayers while travelling on a journey."
    # "prayers"->"praye" and "travelling"->"trave" both prefix-match -> >=2.
    assert topical(words, text) is True


def test_prefix_absorbs_stemming():
    # extensions -> extension, praying -> pray: the 5-char prefix bridges the stem.
    assert topical(["praying"], "the manner of praying in congregation") is True
    assert topical(["extensions"], "hair extension rulings") is True


def test_empty_query_never_over_filters():
    assert topical([], "anything at all") is True


def test_all_short_words_never_over_filter():
    # Nothing >= 3 chars to check against -> keep (do not silently drop).
    assert topical(["to", "is", "of"], "short stopwords only") is True


def test_none_text_is_safe():
    assert topical(["riba"], None) is False  # no text to cover -> not topical
    assert topical([], None) is True


def test_known_limitation_prefix5_stem_divergence():
    # DOCUMENTED limitation, asserted so a future change is a conscious one:
    # a single distinctive word whose corpus variant diverges before char 5
    # ("gratitude" vs "grateful": prefix "grati" != "grate") is dropped. Only
    # affects the FTS *fallback*; the primary semantic path is unaffected. If a
    # real stemmer is introduced, update this expectation deliberately.
    assert topical(["gratitude"], "be grateful to Me and do not deny Me") is False
    # ...but the exact form, or a second content term, keeps it:
    assert topical(["gratitude"], "this ayah is about gratitude to Allah") is True
    assert topical(["gratitude", "thankfulness"],
                   "on gratitude: the servant shows thankfulness") is True


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed} passed, 0 failed")


if __name__ == "__main__":
    _run()
