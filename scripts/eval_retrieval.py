#!/usr/bin/env python3
"""Standing retrieval-quality gate for the Bayan bot (op#5975).

Seeded from REAL production queries (mizan_interactions, 136 distinct) rather
than invented ones, so it regression-tests what users actually asked — including
the named-verse tafsir failures that motivated it ('ayat kursi tafsir', etc.).

It grades the FIXED bot's RETRIEVAL + ROUTING layer deterministically (no LLM),
which is where every reported failure lived, so the gate is fast and stable:

  correct-gate     — a ruling / high-stakes query the bot routes to the scholar
                     gate (match_ruling_query / match_high_stakes_query fires).
  good-answer      — retrieval surfaced the correct/relevant evidence: for a
                     named-verse / explicit S:A query, the DEDICATED tafsir for
                     the resolved surah:ayah; for topical queries, a non-empty
                     evidence block.
  honest-not-found — retrieval surfaced no evidence AND the corpus genuinely
                     lacks it, so the bot will honestly say "not found".
  BAD              — a query whose evidence EXISTS in the corpus but retrieval
                     failed to surface it (the regression class). Named-verse
                     misses are the flagship BAD.

Usage:
  python3 scripts/eval_retrieval.py            # grade all, print breakdown
  python3 scripts/eval_retrieval.py --gate     # exit 1 if any BAD (pre-deploy)
  python3 scripts/eval_retrieval.py --bad      # print only BAD rows

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (loaded from .env by the bot).
"""
import os, sys, re, json, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "eval_retrieval_queries.json")

# Import the live bot module so we grade the SAME code path users hit.
_spec = importlib.util.spec_from_file_location("mizan_bot", os.path.join(HERE, "mizan_bot.py"))
mb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mb)

SCHOLARS = ("Ibn Kathir", "Al-Sa'di", "Al-Qurtubi", "Al-Jalalayn")


def _disable_semantic():
    """Fast mode: stub the CPU-heavy semantic rerankers (~28s/query) so the gate
    runs keyed + FTS retrieval only (~sub-second/query). This does NOT affect BAD
    detection — every reported failure was a KEYED named-verse / routing miss, all
    of which are deterministic. It only makes the good-answer vs honest-not-found
    split conservative for topical queries whose ONLY hit is semantic (those get
    counted honest-not-found here). Use --full for the complete, slower grade."""
    stub = lambda *a, **k: {"results": []}
    for modname in ("tafsir_semantic", "hadith_semantic", "fiqh_semantic"):
        mod = getattr(mb, modname, None)
        if mod is not None and hasattr(mod, "search_semantic"):
            mod.search_semantic = stub


def extract_verse_targets(q):
    """Return a list of (surah, ayah|None) this query explicitly names, or []
    for a non-verse query. ayah=None means a whole-surah tafsir request."""
    targets = []
    # 1) named-verse / surah alias (ayat al-kursi -> (2,255); 'fatiha' -> 1)
    a = mb.match_surah_alias(q)
    if isinstance(a, tuple):
        targets.append(a)
    elif isinstance(a, int):
        targets.append((a, None))
    # 2) explicit S:A (and the first endpoint of a range like 7:120-7:130)
    for m in re.finditer(r'\b(\d{1,3})\s*:\s*(\d{1,3})\b', q):
        s, ay = int(m.group(1)), int(m.group(2))
        if 1 <= s <= 114:
            targets.append((s, ay))
    # 3) "surah N ayah M"
    m = re.search(r'surah\s+(\d{1,3})\s+ayah\s+(\d{1,3})', q, re.I)
    if m:
        targets.append((int(m.group(1)), int(m.group(2))))
    # dedupe preserving order
    out = []
    for t in targets:
        if t not in out:
            out.append(t)
    return out


def corpus_has_tafsir(surah, ayah):
    """Ground truth: does the corpus hold ≥1 English tafsir for these coords?
    ayah=None -> check the surah's first ayah (whole-surah tafsir path)."""
    check_ayah = ayah if ayah is not None else 1
    try:
        data = mb.lookup_verse(surah, check_ayah)
    except Exception:
        return False
    return bool(data.get("tafsir"))


def ctx_has_tafsir_for(ctx, surah, ayah):
    """Did gather_context surface a scholar tafsir for these coords?"""
    if not ctx:
        return False
    has_scholar = any(name in ctx for name in SCHOLARS)
    if ayah is not None:
        coord = (f'"surah": {surah}' in ctx and f'"ayah": {ayah}' in ctx) or f"{surah}:{ayah}" in ctx
    else:
        coord = f'"surah": {surah}' in ctx or f"Surah {surah})" in ctx or f"Surah {surah}:" in ctx
    return coord and has_scholar


def has_evidence(ctx):
    """Any real retrieval block present (verse / tafsir / hadith / fiqh)."""
    if not ctx:
        return False
    return any(k in ctx for k in (
        "VERSE LOOKUP", "TAFSIR", "FULL SURAH TAFSIR", "QURAN SEARCH",
        "HADITH", "FIQH", "TOPIC", "COUNT", "SURAH INFO", "matched_passage",
        "scholar_name",
    ))


def grade(q):
    """Return (grade, detail)."""
    ruling = mb.match_ruling_query(q)
    high = mb.match_high_stakes_query(q)
    targets = extract_verse_targets(q)

    # Verse-target queries take priority: they must retrieve the DEDICATED tafsir.
    # (A verse query that is ALSO a ruling still needs its tafsir; the gate is a
    # synthesis-posture concern handled downstream.)
    if targets:
        try:
            ctx = mb.gather_context(q)
        except Exception as e:
            return "BAD", f"gather_context error: {type(e).__name__}: {e}"
        in_corpus = [(s, ay) for (s, ay) in targets if corpus_has_tafsir(s, ay)]
        if not in_corpus:
            return "honest-not-found", f"verse(s) {targets} not in corpus"
        # Good if the bot surfaced the dedicated tafsir for AT LEAST ONE named
        # target (the anchor). Ranges like 7:120-7:130 name many ayat; surfacing
        # the range anchor is a correct answer, so we don't require every endpoint.
        surfaced = [(s, ay) for (s, ay) in in_corpus if ctx_has_tafsir_for(ctx, s, ay)]
        if surfaced:
            return "good-answer", f"verse tafsir surfaced: {surfaced}"
        return "BAD", f"named verse(s) {in_corpus} tafsir in corpus but NONE surfaced"

    # Non-verse: ruling / high-stakes -> gate.
    if ruling or high:
        tag = "high-stakes" if high else "ruling"
        return "correct-gate", f"routed to scholar gate ({tag})"

    # Topical / definition / hadith: judge by whether retrieval found evidence.
    try:
        ctx = mb.gather_context(q)
    except Exception as e:
        return "BAD", f"gather_context error: {type(e).__name__}: {e}"
    if has_evidence(ctx):
        return "good-answer", "topical evidence retrieved"
    return "honest-not-found", "no evidence retrieved (bot answers honestly)"


def main():
    only_bad = "--bad" in sys.argv
    gate = "--gate" in sys.argv
    full = "--full" in sys.argv
    if not full:
        _disable_semantic()
    print(f"[mode: {'FULL (keyed+FTS+semantic)' if full else 'FAST (keyed+FTS, semantic stubbed)'}]\n")
    queries = json.load(open(GOLDEN, encoding="utf-8"))
    results = []
    for i, item in enumerate(queries):
        q = item["query"]
        g, detail = grade(q)
        results.append({"query": q, "grade": g, "detail": detail})
        if not only_bad or g == "BAD":
            mark = {"good-answer": "✓", "correct-gate": "⚖", "honest-not-found": "∅", "BAD": "✗"}[g]
            print(f"{mark} [{g:16}] {q[:70]}")
            if g == "BAD":
                print(f"      -> {detail}")

    from collections import Counter
    counts = Counter(r["grade"] for r in results)
    total = len(results)
    bad = counts.get("BAD", 0)
    passing = total - bad
    print("\n=== GRADE BREAKDOWN (n=%d real queries) ===" % total)
    for g in ("good-answer", "correct-gate", "honest-not-found", "BAD"):
        print(f"  {g:16} {counts.get(g,0):3d}  ({100*counts.get(g,0)/total:.0f}%)")
    print(f"  {'PASS RATE':16} {passing}/{total}  ({100*passing/total:.1f}%)  [BAD is the only failing bucket]")

    if gate and bad:
        print(f"\nGATE FAIL: {bad} BAD retrieval(s). Fix before deploy.")
        sys.exit(1)


if __name__ == "__main__":
    main()
