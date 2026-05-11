"""Semantic retrieval for juridical (Shafi'i fiqh) corpus via local bge-m3 encoder.

Phase 3 wire-in target for mizan_bot.lookup_fiqh — semantic-first, FTS-fallback.
Authored as standalone module so mizan_bot.py is not patched (preserves freeze
marker per CAI-PROCESS-GLUE-AUDIT-MIZANBOT-001 id 870 — extracting to a new
module is structural, not glue).

At current 5-row corpus scale, brute-force cosine similarity in Python is fine.
Replace with pgvector RPC (`<#>` operator + ivfflat index) when juridical_translations
re-ingests at sub-chapter granularity in Phase 3+.
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
ENCODER_URL = os.environ.get("ENCODER_URL", "http://100.104.36.27:8080")
ENCODER_TIMEOUT_SEC = float(os.environ.get("ENCODER_TIMEOUT_SEC", "2.0"))


def _http(method: str, url: str, payload=None, headers=None, timeout: float = 5.0):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def _supa(method: str, path: str, payload=None) -> Optional[list]:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    return _http(method, f"{SUPABASE_URL}{path}", payload, headers, timeout=5.0)


def _encode(query: str) -> Optional[list]:
    """Returns 1024-dim vector or None if encoder unreachable / slow."""
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


def _parse_vec(v) -> list:
    """pgvector serializes via PostgREST as the string '[0.1,0.2,...]'.
    Accept both string and list forms.
    """
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.startswith("["):
        return [float(x) for x in v[1:-1].split(",") if x]
    return []


def _cosine(a: list, b) -> float:
    """bge-m3 outputs are L2-normalized via normalize_embeddings=True in
    encoder_service.py, so dot product equals cosine similarity. Defensive
    re-normalize anyway in case a future upstream change drops the flag.
    """
    b = _parse_vec(b)
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def search_semantic(query: str, limit: int = 3) -> dict:
    """Semantic retrieval over juridical corpus. Same return shape as
    mizan_bot.lookup_fiqh so wire-in is a one-line swap.

    Returns: {"results": [{baab, translator, source_work, edition, text, tier, rank}, ...]}
    Empty results on encoder timeout, transport error, or zero corpus rows.
    """
    qvec = _encode(query)
    if qvec is None:
        return {"results": []}

    try:
        embeds = _supa(
            "GET",
            "/rest/v1/juridical_embeddings?select=juridical_text_id,embedding",
        ) or []
    except Exception:
        return {"results": []}
    if not embeds:
        return {"results": []}

    scored = sorted(
        ((_cosine(qvec, row["embedding"]), row["juridical_text_id"]) for row in embeds),
        key=lambda t: t[0],
        reverse=True,
    )[:limit]

    if not scored:
        return {"results": []}

    text_ids = [tid for _, tid in scored]
    in_clause = "(" + ",".join(text_ids) + ")"
    juridical_texts = _supa(
        "GET",
        f"/rest/v1/juridical_texts?select=id,baab_or_section,author_name,text_name&id=in.{in_clause}",
    ) or []
    text_meta = {t["id"]: t for t in juridical_texts}

    translations = _supa(
        "GET",
        f"/rest/v1/juridical_translations?select=juridical_text_id,translator_name,translation_source_work,translation_text,output_tier,edition_label&juridical_text_id=in.{in_clause}",
    ) or []
    by_text_id: dict = {}
    for tr in translations:
        by_text_id.setdefault(tr["juridical_text_id"], tr)

    results = []
    for score, tid in scored:
        meta = text_meta.get(tid, {})
        tr = by_text_id.get(tid, {})
        results.append({
            "baab": meta.get("baab_or_section", "?"),
            "translator": tr.get("translator_name", "?"),
            "source_work": tr.get("translation_source_work", meta.get("text_name", "?")),
            "edition": tr.get("edition_label", ""),
            "text": tr.get("translation_text", ""),
            "tier": tr.get("output_tier", "paraphrased"),
            "rank": float(score),
        })
    return {"results": results}


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "what nullifies the fast"
    t0 = time.time()
    out = search_semantic(q, limit=3)
    print(f"query: {q!r}  elapsed: {time.time() - t0:.3f}s")
    for r in out["results"]:
        print(f"  rank={r['rank']:.4f} baab={r['baab']!r} text_len={len(r['text'])}")
