"""Semantic retrieval for asbab al-nuzul via local bge-m3 encoder.

CAVEAT: ~19% of source-tagged 'al-wahidi' rows are mislabeled ishārī
(Maybudī Kashf al-Asrār) content per docs/ASBAB_NUZUL_CORRUPTION_2026-
06-05.md. Semantic search surfaces them regardless of label. Do NOT
quote the source field as authoritative attribution until task #46
re-tag lands.
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


def _http(method, url, payload=None, headers=None, timeout=5.0):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def _encode(query):
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


def _rerank(query, passages, timeout=30.0):
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


def search_semantic(query, limit=5, surah=None, min_score=0.35, rerank=True, candidate_pool=30):
    qvec = _encode(query)
    if qvec is None:
        return {"results": []}
    fetch_count = candidate_pool if rerank else limit
    fetch_min   = min_score  # always apply as noise filter
    try:
        payload = {
            "query_embedding": qvec,
            "match_count": fetch_count,
            "surah_filter": surah,
            "min_score": fetch_min,
        }
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        rows = _http("POST", f"{SUPABASE_URL}/rest/v1/rpc/search_asbab_semantic", payload, headers, timeout=10.0)
    except Exception:
        return {"results": []}
    if not rows:
        return {"results": []}
    if rerank:
        passages = [(r.get("text_en") or "")[:1500] for r in rows]
        scores = _rerank(query, passages)
        if scores is not None and len(scores) == len(rows):
            # 60% rerank + 40% semantic — see hadith_semantic comment.
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
            "asbab_id": r.get("asbab_id"),
            "surah_number": r.get("surah_number"),
            "ayah_number_surah": r.get("ayah_number_surah"),
            "text_en": (r.get("text_en") or "")[:1500],
            "source": r.get("source"),
            "rank": float(r.get("score") or 0.0),
        })
    return {"results": results}


if __name__ == "__main__":
    import sys, time
    q = " ".join(sys.argv[1:]) or "ayat al-kursi revelation"
    t0 = time.time()
    out = search_semantic(q, limit=5)
    print(f"query: {q!r}  elapsed: {time.time() - t0:.3f}s")
    for r in out["results"]:
        print(f"  rank={r['rank']:.4f}  Q{r['surah_number']}:{r['ayah_number_surah']}  source={r['source']}")
        print(f"    {r['text_en'][:160]}")
