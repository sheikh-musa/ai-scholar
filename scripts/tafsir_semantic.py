"""Semantic retrieval for tafsir corpus via local bge-m3 encoder.

Supplements search_tafsir_fts (which remains the F-2 anchor for
matched_passage in mizan_interactions audit rows). Semantic results
broaden retrieval beyond surface-token matching; the FTS path still
owns the ayah-keyed audit anchor.
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


def search_semantic(query, limit=5, scholar_name=None, min_score=0.45):
    """Returns {"results": [{tafsir_entry_id, ayah_id, scholar_name, source_work,
                             english_text, arabic_text, output_tier, rank}, ...]}."""
    qvec = _encode(query)
    if qvec is None:
        return {"results": []}
    try:
        payload = {
            "query_embedding": qvec,
            "match_count": limit,
            "scholar_filter": scholar_name,
            "min_score": min_score,
        }
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        rows = _http("POST", f"{SUPABASE_URL}/rest/v1/rpc/search_tafsir_semantic", payload, headers, timeout=10.0)
    except Exception:
        return {"results": []}
    if not rows:
        return {"results": []}
    results = []
    for r in rows:
        results.append({
            "tafsir_entry_id": r.get("tafsir_entry_id"),
            "ayah_id": r.get("ayah_id"),
            "scholar_name": r.get("scholar_name"),
            "source_work": r.get("source_work"),
            "english_text": (r.get("english_text") or "")[:1500],
            "arabic_text": r.get("arabic_text"),
            "output_tier": r.get("output_tier"),
            "rank": float(r.get("score") or 0.0),
        })
    return {"results": results}


if __name__ == "__main__":
    import sys, time
    q = " ".join(sys.argv[1:]) or "patience in trial"
    t0 = time.time()
    out = search_semantic(q, limit=5)
    print(f"query: {q!r}  elapsed: {time.time() - t0:.3f}s")
    for r in out["results"]:
        print(f"  rank={r['rank']:.4f}  {r['scholar_name']} ({r['source_work']})  tier={r['output_tier']}")
        print(f"    {r['english_text'][:160]}")
