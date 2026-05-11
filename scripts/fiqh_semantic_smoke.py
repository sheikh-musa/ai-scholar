"""Smoke test for fiqh_semantic.search_semantic against live encoder + DB.

Run after Phase 1 (encoder up on Tailscale) + Phase 2 backfill
(juridical_embeddings populated). Validates the architectural pivot from
keyword/FTS to semantic retrieval.

Each query is one of the cases that historically required a glue patch on
mizan_bot.lookup_fiqh — the freeze ruling (id 870) calls semantic the
architectural fix. This smoke confirms it on the actual corpus before the
Phase 3 wire-in lifts the freeze marker.
"""

import sys
import time

from fiqh_semantic import search_semantic

CASES = [
    {
        "query": "what nullifies the fast",
        "expected_baab_substr": "siyam",
    },
    {
        "query": "wudu arkan",
        "expected_baab_substr": "taharah",
    },
    {
        "query": "ablution requirements",
        "expected_baab_substr": "taharah",
    },
    {
        "query": "breastfeeding mother fasting ramadan",
        "expected_baab_substr": "siyam",
    },
    {
        "query": "pillars of prayer",
        "expected_baab_substr": "salah",
    },
    {
        "query": "zakat on wealth",
        "expected_baab_substr": "zakah",
    },
    {
        "query": "creed and faith",
        "expected_baab_substr": "iman",
    },
]


def main() -> int:
    failures = 0
    for case in CASES:
        t0 = time.time()
        out = search_semantic(case["query"], limit=3)
        dt = time.time() - t0
        if not out["results"]:
            print(f"[FAIL] {case['query']!r}  no results  elapsed={dt:.3f}s")
            failures += 1
            continue
        top = out["results"][0]
        baab = (top.get("baab") or "").lower()
        expected = case["expected_baab_substr"].lower()
        ok = expected in baab
        status = "[ OK ]" if ok else "[FAIL]"
        print(f"{status} {case['query']!r}  top_baab={top['baab']!r}  rank={top['rank']:.4f}  elapsed={dt:.3f}s")
        if not ok:
            print(f"       expected baab containing {expected!r}")
            failures += 1
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
