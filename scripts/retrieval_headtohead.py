#!/usr/bin/env python3
"""Head-to-head: FTS+SYNONYM vs semantic-HNSW retrieval.

For each query, run both paths and report top-K. Score manually-curated
expected-substring matches if provided (oracle mode), else just emit
overlap + divergence metrics.

Decision input for the hybrid-vs-swap question per Musa 2026-06-10.

Usage:
  python3 scripts/retrieval_headtohead.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Force Max-plan path (the bot uses CLI; not relevant here but consistent)
os.environ.pop("ANTHROPIC_API_KEY", None)

import hadith_semantic  # semantic path

SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


# Test panel — manually curated. Each entry:
#   query           — user phrasing
#   expected_subs   — substrings that, if present in a result's english_text,
#                     count as ON-TOPIC. Multiple alternatives OR'd.
#   notes           — what this query tests
PANEL = [
    # ----- Known surface-token gaps (CONCEPT_MAP-aided in FTS path) -----
    {
        "query": "afdhal supplication after eating",
        "expected_subs": ["fed me with this food", "Allah Who has fed me"],
        "notes": "Mu'adh ibn Anas after-meal du'a — Abu Dawud #4023",
    },
    {
        "query": "when doing jama' takhir which prayer should i pray first",
        "expected_subs": ["combined his prayer while travel", "combined the two prayers", "jamʿ", "combine"],
        "notes": "Combining prayers while traveling — Nasai #597, Muslim 705",
    },
    {
        "query": "if I am sponsoring qurban for my infant son do they need to refrain from cutting hair",
        "expected_subs": ["should not get his hair", "must not take any of his hair", "intends to sacrifice", "intends to offer sacrifice"],
        "notes": "Umm Salama hair/nails — Sahih Muslim 5119/5120, Abu Dawud 2791, Riyad 1706",
    },

    # ----- Direct phrase queries (FTS strong, semantic uncertain) -----
    {
        "query": "actions are by intentions",
        "expected_subs": ["actions are but by intentions", "actions are judged by intentions", "innama al-a'malu", "every person will have but what they intended"],
        "notes": "Famous Umar hadith — Bukhari #1, Muslim #1907",
    },
    {
        "query": "build your house in jannah recite ikhlas",
        "expected_subs": ["build a house for him in Paradise", "qul huwa Allahu ahad", "Surat al-Ikhlas"],
        "notes": "Tirmidhi/Nasai — house in jannah for reciting al-Ikhlas",
    },

    # ----- Paraphrase / topic queries (semantic should shine) -----
    {
        "query": "what does the quran say about patience in trial",
        "expected_subs": ["sabr", "patient", "patience", "those who patiently persevere"],
        "notes": "General topic — multiple ayat/hadith on sabr",
    },
    {
        "query": "envy is forbidden between believers",
        "expected_subs": ["envy", "do not envy", "hasad", "do not hate"],
        "notes": "Multiple hadith on hasad",
    },

    # ----- Tafsir tests -----
    {
        "query": "tafsir of ayat al-kursi greatest verse",
        "expected_subs": ["greatest verse", "Ayat al-Kursi", "throne"],
        "notes": "Tafsir Ibn Kathir + Al-Qurtubi on 2:255",
        "target": "tafsir",
    },
    {
        "query": "meaning of al-rahman al-rahim in opening of quran",
        "expected_subs": ["Most Gracious", "Most Merciful", "Ar-Rahman", "Ar-Rahim", "All-Beneficent"],
        "notes": "Tafsir on 1:1 / 1:3",
        "target": "tafsir",
    },
    {
        "query": "tafsir musa speaks to allah at mount sinai",
        "expected_subs": ["Tur", "Sinai", "Musa", "Moses", "spoke to"],
        "notes": "Tafsir on 7:142-143 (Musa at Tur)",
        "target": "tafsir",
    },

    # ----- Asbab tests -----
    {
        "query": "verse revealed when battle of uhud hypocrites",
        "expected_subs": ["Uhud", "hypocrites", "battle"],
        "notes": "Asbab for Surah 3 verses on Uhud aftermath",
        "target": "asbab",
    },

    # ----- Subtle topic-confusion queries (semantic risk) -----
    {
        "query": "aqiqah for newborn shaving head",
        "expected_subs": ["aqiqah", "his head is shaved", "newborn", "seventh day"],
        "notes": "Aqiqah-specific (NOT udhiyya). Tests semantic's ability to disambiguate.",
    },
    {
        "query": "shortening prayer during travel",
        "expected_subs": ["shorten", "shortening", "qasr", "two rakahs", "two rakat"],
        "notes": "Qasr specifically (NOT jam'/combining)",
    },

    # ----- Cross-lingual / transliterated -----
    {
        "query": "boleh ke perempuan haid sentuh mushaf",
        "expected_subs": ["touch", "mushaf", "menstruation", "haid", "haydah", "wudu", "ablution"],
        "notes": "Malay code-switch; bot recently produced clean Malay answer for this",
    },
]


def supabase_rpc(path: str, payload: dict) -> list:
    req = urllib.request.Request(
        f"{SUPABASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run_fts(query: str, target: str = "hadith") -> dict:
    """Call the bot's FTS+SYNONYM path (search_hadith_fts_v2 / search_tafsir_fts)."""
    # Import lazily to avoid bot-state pollution
    import re
    sys.path.insert(0, str(Path(__file__).parent))
    import mizan_bot

    t0 = time.time()
    if target == "hadith":
        # Mirror the bot's word selection
        words = [w for w in re.findall(r'\w+', query.lower()) if w not in mizan_bot.STOP_WORDS and len(w) > 2]
        seen = set(); ranked = []
        for w in sorted(words, key=len, reverse=True):
            if w not in seen:
                seen.add(w); ranked.append(w)
        data = mizan_bot.search_hadith_fts_v2(ranked[:8], limit=5, mode="auto")
        results = data.get("results", [])
        return {
            "elapsed": time.time() - t0,
            "results": [{
                "text": (r.get("english_text") or "")[:300],
                "ref": f"{r.get('collection','?')}#{r.get('hadith_number','?')}",
                "score": None,
            } for r in results],
        }
    elif target == "tafsir":
        try:
            rows = supabase_rpc("/rest/v1/rpc/search_tafsir_fts", {"query": query, "lim": 5})
        except Exception as e:
            return {"elapsed": time.time() - t0, "results": [], "error": str(e)}
        return {
            "elapsed": time.time() - t0,
            "results": [{
                "text": (r.get("english_text") or "")[:300],
                "ref": f"{r.get('scholar_name','?')} on {r.get('surah','?')}:{r.get('ayah','?')}",
                "score": None,
            } for r in rows],
        }
    elif target == "asbab":
        return {"elapsed": time.time() - t0, "results": [], "note": "no FTS RPC for asbab; semantic-only"}


def run_semantic(query: str, target: str = "hadith") -> dict:
    t0 = time.time()
    if target == "hadith":
        out = hadith_semantic.search_semantic(query, limit=5, min_score=0.0)
        return {
            "elapsed": time.time() - t0,
            "results": [{
                "text": (r.get("english_text") or "")[:300],
                "ref": f"{r.get('collection','?')}#{r.get('hadith_number','?')}",
                "score": r.get("rank"),
            } for r in out.get("results", [])],
        }
    elif target == "tafsir":
        import tafsir_semantic
        out = tafsir_semantic.search_semantic(query, limit=5, min_score=0.0)
        return {
            "elapsed": time.time() - t0,
            "results": [{
                "text": (r.get("english_text") or "")[:300],
                "ref": f"{r.get('scholar_name','?')} ({r.get('source_work','?')[:25]})",
                "score": r.get("rank"),
            } for r in out.get("results", [])],
        }
    elif target == "asbab":
        import asbab_semantic
        out = asbab_semantic.search_semantic(query, limit=5, min_score=0.0)
        return {
            "elapsed": time.time() - t0,
            "results": [{
                "text": (r.get("text_en") or "")[:300],
                "ref": f"Q{r.get('surah_number')}:{r.get('ayah_number_surah')} ({r.get('source')})",
                "score": r.get("rank"),
            } for r in out.get("results", [])],
        }


def score_path(path_results: dict, expected_subs: list[str]) -> dict:
    """Compute: which rank has an on-topic hit? best_rank=None means miss."""
    best_rank = None
    for i, r in enumerate(path_results.get("results", []), 1):
        text = (r.get("text") or "").lower()
        if any(sub.lower() in text for sub in expected_subs):
            best_rank = i
            break
    return {
        "best_rank": best_rank,  # 1 = top hit on target, None = missed
        "n_results": len(path_results.get("results", [])),
        "elapsed": path_results.get("elapsed", 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--verbose", "-v", action="store_true", help="show full top-K text")
    args = ap.parse_args()

    panel = PANEL[:args.limit] if args.limit else PANEL
    print(f"=== Head-to-head: {len(panel)} queries × 2 paths ===\n")

    summary_fts = {"hit_at_1": 0, "hit_top3": 0, "miss": 0, "total_time": 0.0}
    summary_sem = {"hit_at_1": 0, "hit_top3": 0, "miss": 0, "total_time": 0.0}

    for i, q in enumerate(panel, 1):
        target = q.get("target", "hadith")
        print(f"[{i:2}/{len(panel)}] target={target}  Q: {q['query']!r}")
        print(f"   expects: {q['expected_subs']}")

        fts = run_fts(q["query"], target=target)
        sem = run_semantic(q["query"], target=target)

        fts_score = score_path(fts, q["expected_subs"])
        sem_score = score_path(sem, q["expected_subs"])

        f_mark = "✓" if fts_score["best_rank"] == 1 else ("•" if fts_score["best_rank"] and fts_score["best_rank"] <= 3 else "✗")
        s_mark = "✓" if sem_score["best_rank"] == 1 else ("•" if sem_score["best_rank"] and sem_score["best_rank"] <= 3 else "✗")

        print(f"   FTS  : {f_mark}  best_rank={fts_score['best_rank']} ({fts_score['n_results']} results, {fts_score['elapsed']:.2f}s)")
        print(f"   SEM  : {s_mark}  best_rank={sem_score['best_rank']} ({sem_score['n_results']} results, {sem_score['elapsed']:.2f}s)")

        if args.verbose:
            print(f"   --- FTS top-3 ---")
            for j, r in enumerate(fts.get("results", [])[:3], 1):
                print(f"     {j}. {r['ref']}: {r['text'][:150]}")
            print(f"   --- SEM top-3 ---")
            for j, r in enumerate(sem.get("results", [])[:3], 1):
                s = f" [{r['score']:.3f}]" if r.get('score') is not None else ""
                print(f"     {j}.{s} {r['ref']}: {r['text'][:150]}")

        # tally
        for name, score, bucket in (("fts", fts_score, summary_fts), ("sem", sem_score, summary_sem)):
            bucket["total_time"] += score["elapsed"]
            if score["best_rank"] == 1:
                bucket["hit_at_1"] += 1
                bucket["hit_top3"] += 1
            elif score["best_rank"] and score["best_rank"] <= 3:
                bucket["hit_top3"] += 1
            else:
                bucket["miss"] += 1
        print()

    print("=" * 70)
    print("SCORECARD")
    print("=" * 70)
    n = len(panel)
    print(f"  Query count: {n}")
    print(f"                         FTS+SYNONYM         SEMANTIC")
    print(f"    Top-1 hit:           {summary_fts['hit_at_1']:>3}/{n:<3} ({100*summary_fts['hit_at_1']/n:>4.1f}%)     {summary_sem['hit_at_1']:>3}/{n:<3} ({100*summary_sem['hit_at_1']/n:>4.1f}%)")
    print(f"    Top-3 hit:           {summary_fts['hit_top3']:>3}/{n:<3} ({100*summary_fts['hit_top3']/n:>4.1f}%)     {summary_sem['hit_top3']:>3}/{n:<3} ({100*summary_sem['hit_top3']/n:>4.1f}%)")
    print(f"    Miss:                {summary_fts['miss']:>3}/{n:<3}            {summary_sem['miss']:>3}/{n:<3}")
    print(f"    Total time:          {summary_fts['total_time']:>5.1f}s             {summary_sem['total_time']:>5.1f}s")
    print(f"    Avg per query:       {summary_fts['total_time']/n:>5.2f}s             {summary_sem['total_time']/n:>5.2f}s")


if __name__ == "__main__":
    main()
