"""Semantic retrieval for hadith corpus via local bge-m3 encoder.

Replaces the SYNONYM_MAP / CONCEPT_MAP-driven Postgres FTS path in
mizan_bot.search_hadith_fts_v2. Same return shape so the swap is a
one-line caller change.

Architecture parallel to fiqh_semantic.py:
  1. Encode user query via Mac Studio bge-m3 (1024-dim)
  2. Server-side cosine top-K via search_hadith_semantic RPC
  3. Return shape matches FTS path so callers don't change

Falls back to None on encoder timeout / unreachable so the bot can
gracefully degrade to the FTS path while still under build-up.

Per Musa direction 2026-06-05 — surface-token treadmill won't scale;
this is the structural fix.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
ENCODER_URL  = os.environ.get("ENCODER_URL", "http://100.104.36.27:8080")
ENCODER_TIMEOUT_SEC = float(os.environ.get("ENCODER_TIMEOUT_SEC", "5.0"))


def _http(method: str, url: str, payload=None, headers=None, timeout: float = 5.0):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def _encode(query: str) -> Optional[list]:
    """1024-dim bge-m3 vector, or None on encoder failure."""
    try:
        r = _http(
            "POST",
            f"{ENCODER_URL}/embed",
            {"inputs": [query]},
            {"Content-Type": "application/json"},
            timeout=ENCODER_TIMEOUT_SEC,
        )
        return r["embeddings"][0]
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError, TypeError):
        return None


def _rerank(query: str, passages: list, timeout: float = 30.0) -> Optional[list]:
    """Call bge-reranker-v2-m3 to get query×passage relevance scores.

    Returns list of float scores aligned with passages, or None on failure.
    Reranker fixes the query-document asymmetry that bge-m3 single-vector
    embedding suffers from (e.g. user asks 'supplication after eating',
    hadith says 'praise be to Allah who has fed me' — different surface
    but reranker scores them as relevant pair).
    """
    if not passages:
        return []
    try:
        r = _http(
            "POST",
            f"{ENCODER_URL}/rerank",
            {"query": query, "passages": passages},
            {"Content-Type": "application/json"},
            timeout=timeout,
        )
        return r["scores"]
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError, TypeError):
        return None


def search_semantic(
    query: str,
    limit: int = 5,
    collection_name: Optional[str] = None,
    min_score: float = 0.35,
    rerank: bool = True,
    candidate_pool: int = 30,
) -> dict:
    """Server-side cosine top-K via search_hadith_semantic RPC.

    Returns the same shape as mizan_bot.search_hadith_fts_v2:
      {"results": [{"hadith_number","collection","english_text","arabic_text",
                    "grading","narrator","rank"}, ...]}

    Empty results on:
      - encoder unreachable / timeout
      - RPC error (e.g. hadith_embeddings empty / migration not applied)
      - no rows above min_score
    """
    qvec = _encode(query)
    if qvec is None:
        return {"results": []}

    # Wide-net first pass via bge-m3 semantic (top-N candidates).
    # Always apply semantic min_score as the NOISE FILTER — the reranker
    # is only good at ordering, not at absolute "is this even relevant"
    # scoring. Without this, queries with no real corpus matches (Malay
    # code-switch, hyper-niche topics) get reordered noise back instead
    # of an empty result set. The reranker then reorders the survivors.
    fetch_count = candidate_pool if rerank else limit
    fetch_min   = min_score

    try:
        payload = {
            "query_embedding": qvec,
            "match_count": fetch_count,
            "collection_filter": collection_name,
            "min_score": fetch_min,
        }
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        rows = _http("POST", f"{SUPABASE_URL}/rest/v1/rpc/search_hadith_semantic", payload, headers, timeout=10.0)
    except Exception:
        return {"results": []}

    if not rows:
        return {"results": []}

    # Reranker pass: bge-reranker-v2-m3 scores (query, passage) pairs
    # directly, fixing the query-document asymmetry that single-vector
    # bge-m3 stumbles on (e.g. "supplication after eating" → "praise be
    # to Allah who has fed me"). If rerank fails (encoder down, etc.)
    # we fall through to the semantic-only ordering.
    if rerank:
        passages = [(r.get("english_text") or "")[:1500] for r in rows]
        scores = _rerank(query, passages)
        if scores is not None and len(scores) == len(rows):
            # Combine: 60% rerank + 40% semantic. Preserves semantic's
            # cross-lingual strength while letting reranker fix the
            # query-document asymmetry on direct-match queries. Pure
            # rerank-replace lost cross-lingual queries entirely (the
            # Malay haid mushaf case) because the reranker drops the
            # cross-lingual signal that bge-m3 captures.
            for r, s in zip(rows, scores):
                sem_score = r["score"]
                r["score"] = 0.6 * float(s) + 0.4 * sem_score
            rows.sort(key=lambda r: r["score"], reverse=True)
        rows = rows[:limit]
    else:
        rows = rows[:limit]

    results = []
    for r in rows:
        results.append({
            "hadith_number": r.get("hadith_number"),
            "collection": r.get("collection_name"),
            "english_text": (r.get("english_text") or "")[:500],
            "arabic_text": r.get("arabic_text"),
            "grading": r.get("grading"),
            "narrator": r.get("narrator"),
            "rank": float(r.get("score") or 0.0),
        })
    return {"results": results}


if __name__ == "__main__":
    import sys, time
    q = " ".join(sys.argv[1:]) or "supplication after eating"
    t0 = time.time()
    out = search_semantic(q, limit=5)
    print(f"query: {q!r}  elapsed: {time.time() - t0:.3f}s")
    for r in out["results"]:
        print(f"  rank={r['rank']:.4f}  {r['collection']}#{r['hadith_number']}  {r['grading']}")
        print(f"    {r['english_text'][:160]}")
