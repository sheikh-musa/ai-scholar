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
ENCODER_TIMEOUT_SEC = float(os.environ.get("ENCODER_TIMEOUT_SEC", "5.0"))

# bge-m3 ranks lexical overlap of transliterated Arabic terms strongly even
# when semantically off-topic (e.g. "wājib" appears densely in the Salah
# imam-followership section, pulling "wajibat of sawm" to Salah rank-1).
# Expand the query with English equivalents so bge-m3 centroids toward the
# correct semantic chapter. Mapping is INTERSECTION-ONLY with the Marbuqi
# translation vocabulary — terms that exist in juridical_translations text.
QUERY_EXPANSIONS = {
    "sawm": "fasting",
    "siyam": "fasting",
    "saum": "fasting",
    "wudu": "ablution",
    "wuduʾ": "ablution",
    "wuḍūʾ": "ablution",
    "ghusl": "ritual bath",
    "tayammum": "dry ablution",
    "salah": "prayer",
    "ṣalāh": "prayer",
    "salat": "prayer",
    "zakah": "almsgiving",
    "zakat": "almsgiving",
    "zakāh": "almsgiving",
    "hajj": "pilgrimage",
    "ḥajj": "pilgrimage",
    "iman": "faith creed",
    "īmān": "faith creed",
    "wajib": "obligation compulsory",
    "wājib": "obligation compulsory",
    "wajibat": "obligations compulsory",
    "fard": "obligation farḍ",
    "farḍ": "obligation farḍ",
    "furud": "obligations integrals",
    "furuḍ": "obligations integrals",
    "sunnah": "recommended sunnah",
    "arkan": "pillars integrals",
    "arkān": "pillars integrals",
    "mufṭirāt": "nullifiers breakers",
    "mufsidat": "nullifiers breakers",
    "nawāqiḍ": "nullifiers breakers",
    "taharah": "purification cleanliness",
    "ṭahārah": "purification cleanliness",
    "najis": "impurity",
    "najāsah": "impurity",
    # Sacrifice / Udhiyya family — added 2026-06-01 after live qurban question
    # surfaced that bge-m3 does not cross the qurban (Persian/Malay/Indonesian/
    # Urdu loanword) ↔ udhiyya (Arabic) divide. Corpus already has udhiyya
    # content in Nihayat tail chunks but stays unretrievable without expansion.
    "qurban": "udhiyya sacrifice slaughter",
    "qurbān": "udhiyya sacrifice slaughter",
    "korban": "udhiyya sacrifice slaughter",
    "udhiyya": "sacrifice slaughter",
    "udhiyyah": "sacrifice slaughter",
    "uḍḥiyya": "sacrifice slaughter",
    "uḍḥiyyah": "sacrifice slaughter",
    "udhiyah": "sacrifice slaughter",
    "adahi": "sacrifices",
    "aḍāḥī": "sacrifices",
    "dhabh": "slaughter",
    "ḏabḥ": "slaughter",
    "dhabihah": "slaughtered animal",
    "ḏabīḥah": "slaughtered animal",
    "aqiqah": "birth sacrifice",
    "ʿaqīqah": "birth sacrifice",
    "hady": "sacrificial gift offering",
    "hadī": "sacrificial gift offering",
    # Sujūd al-sahw family — added 2026-06-11 after a live "how to do sujud
    # sahwi" question retrieved general-ṣalāh arkān chunks instead of the sahw
    # faṣl. The corpus HAS the sahw section (Safīnat chunks 11-12, plus Nihāyat
    # / Qudūrī), but "sujud sahwi" sits in a tight 0.52-0.55 cosine band against
    # the dense general-prostration content, so the sahw faṣl loses Safīnat's
    # single diversified slot. Expansion (intersection-only with the translation
    # vocabulary) lifts the sahw chunks to rank-1 across all three matns.
    "sahw": "sajdah sahw prostration of forgetfulness omitted sunnah abʿaḍ tashahhud qunut doubt rakah",
    "sahwi": "sajdah sahw prostration of forgetfulness omitted sunnah abʿaḍ tashahhud qunut doubt rakah",
    "sahwa": "sajdah sahw prostration of forgetfulness omitted sunnah abʿaḍ tashahhud qunut doubt rakah",
    "sahu": "sajdah sahw prostration of forgetfulness omitted sunnah abʿaḍ tashahhud qunut doubt rakah",
}


def _expand_query(q: str) -> str:
    """Append English equivalents for transliterated Arabic terms. Original
    query stays in place so lexical match is preserved if substrate uses
    transliteration too.
    """
    if not q:
        return q
    extras: list = []
    for tok in q.lower().split():
        norm = tok.strip(".,;:!?\"'()[]")
        if norm in QUERY_EXPANSIONS:
            extras.append(QUERY_EXPANSIONS[norm])
    if extras:
        return q + " " + " ".join(extras)
    return q


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


def search_semantic(query: str, limit: int = 3, max_per_text_id: int = 2) -> dict:
    """Semantic retrieval over juridical corpus with per-source diversification.

    Same return shape as mizan_bot.lookup_fiqh so wire-in is a one-line swap.

    Returns: {"results": [{baab, translator, source_work, edition, text, tier, rank}, ...]}
    Empty results on encoder timeout, transport error, or zero corpus rows.

    Diversification rationale (2026-05-27):
      After ingesting Nihāyat al-Zayn (794 English chunks via OpenITI+Sonnet),
      Nihāyat's broader content outranked the existing Safīnat al-Najā baabs
      (57 specialized chunks) on most fiqh queries. E2E test panel showed
      10/15 queries returning ONLY Nihāyat, losing the Safīnat matn-style
      answers that Hadhrami Shafi'i users expect.

      Fix: cap chunks-per-juridical_text_id at `max_per_text_id` (default 2).
      Sort all embeddings by cosine, walk in order, include only if we
      haven't hit the cap for that text. Preserves top-1 quality
      (highest-ranked chunk always wins) while reserving slots for other
      sources when their chunks rank ≥ 0.45.
    """
    qvec = _encode(_expand_query(query))
    if qvec is None:
        return {"results": []}

    try:
        embeds = _supa(
            "GET",
            "/rest/v1/juridical_embeddings?select=juridical_text_id,chunk_index,chunk_text,embedding",
        ) or []
    except Exception:
        return {"results": []}
    if not embeds:
        return {"results": []}

    # Score all, sort descending
    all_scored = sorted(
        ((_cosine(qvec, row["embedding"]), row) for row in embeds),
        key=lambda t: t[0],
        reverse=True,
    )

    # Per-text_id-diversified top-K: walk in score order, take up to
    # max_per_text_id from any single juridical_text_id
    scored: list = []
    per_text_count: dict = {}
    for score, row in all_scored:
        if len(scored) >= limit:
            break
        tid = row["juridical_text_id"]
        if per_text_count.get(tid, 0) >= max_per_text_id:
            continue
        scored.append((score, row))
        per_text_count[tid] = per_text_count.get(tid, 0) + 1

    if not scored:
        return {"results": []}

    text_ids = list({row["juridical_text_id"] for _, row in scored})
    in_clause = "(" + ",".join(text_ids) + ")"
    juridical_texts = _supa(
        "GET",
        f"/rest/v1/juridical_texts?select=id,baab_or_section,author_name,text_name&id=in.{in_clause}",
    ) or []
    text_meta = {t["id"]: t for t in juridical_texts}

    translations = _supa(
        "GET",
        f"/rest/v1/juridical_translations?select=juridical_text_id,translator_name,translation_source_work,output_tier,edition_label&juridical_text_id=in.{in_clause}",
    ) or []
    by_text_id: dict = {}
    for tr in translations:
        by_text_id.setdefault(tr["juridical_text_id"], tr)

    results = []
    for score, row in scored:
        tid = row["juridical_text_id"]
        meta = text_meta.get(tid, {})
        tr = by_text_id.get(tid, {})
        results.append({
            "id": tid,                # F-2: juridical_text_id for retrieval_ids audit
            "baab": meta.get("baab_or_section", "?"),
            "translator": tr.get("translator_name", "?"),
            "source_work": tr.get("translation_source_work", meta.get("text_name", "?")),
            "edition": tr.get("edition_label", ""),
            "text": row.get("chunk_text", ""),
            "chunk_index": row.get("chunk_index"),
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
