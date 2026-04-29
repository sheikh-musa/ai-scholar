#!/usr/bin/env python3
"""
Pre-seed candidate ayah_ids for the ENCODER-EVAL gold set so Musa
verifies/swaps instead of formulating from scratch.

Strategy:
  - English queries: feed query directly to search_tafsir_fts.
  - Arabic + Bahasa queries: feed an English-keyword translation
    (KEYWORD_MAP below) to search_tafsir_fts, since the FTS RPC is
    English-only (to_tsvector('english', english_text)).
  - Output: evals/encoder_eval_gold_set_candidates.json

The candidates file is consumed by build_gold_set.py — Musa accepts by
ref number (e.g., "1 3 5") rather than typing surah:ayah from memory.

Usage:
  python3 scripts/encoder_eval/pre_seed_candidates.py
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Re-use the seed lists by importing build_gold_set as a module
sys.path.insert(0, str(Path(__file__).parent))
from build_gold_set import SEED_ARABIC, SEED_BAHASA, SEED_ENGLISH  # noqa: E402

SUPABASE_URL = (os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
                or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co"))
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

OUT_PATH = Path("evals/encoder_eval_gold_set_candidates.json")

# English-keyword translations for Arabic + Bahasa queries.
# Theological concepts are stable — these aren't perfect literal translations,
# they're search keywords likely to surface relevant tafsir text.
KEYWORD_MAP = {
    # === Arabic ===
    "ما هو التوكل على الله": "tawakkul reliance trust in Allah",
    "معنى الصبر في القرآن": "patience sabr perseverance",
    "تعريف التقوى": "taqwa God-consciousness piety fear",
    "الفرق بين الإيمان والإسلام": "iman faith islam submission",
    "ما هو الإحسان": "ihsan excellence worship",
    "صفات المؤمنين": "characteristics believers qualities",
    "آية في الإخلاص": "ikhlas sincerity worship",
    "أهمية النية في العبادة": "intention niyyah worship deeds",
    "الفرق بين الشرك الأكبر والأصغر": "shirk associating partners Allah polytheism",
    "معنى أسماء الله الحسنى": "names attributes Allah beautiful",
    "كيف أتغلب على الحزن": "sadness grief sorrow comfort",
    "الدعاء عند الكرب": "supplication distress hardship affliction",
    "آيات تخفف القلق": "anxiety worry calm fear",
    "كيف أحفظ القرآن": "memorize preserve Quran recite",
    "كيف أحب الله": "love Allah devotion",
    "الدعاء قبل النوم": "sleep night supplication remember",
    "آيات تذكر بالموت": "death remembrance mortal",
    "كيف أكون شاكرا": "thankful gratitude shukr",
    "الدعاء للوالدين": "parents supplication mercy",
    "كيف أحارب الكسل": "laziness effort diligence striving",
    "آية الكرسي": "throne knowledge heaven earth all-sustaining",
    "السورة التي تذكر يوم القيامة": "day of judgment resurrection rising",
    "آيات الميراث": "inheritance share bequest",
    "آية الدين": "debt loan write contract witness",
    "آيات الحجاب": "modest cover veil women dress",
    "السورة التي ذكرت قصة موسى وفرعون": "Moses Pharaoh staff",
    "آيات الصبر في سورة العصر": "patience time loss except those who believe",
    "آيات الصلاة الخمس": "establish prayer salat five",
    "آيات الصيام": "fasting Ramadan month believers",
    "آيات الزكاة": "zakat charity purify wealth",
    # === Bahasa ===
    "apakah riba dalam Islam": "riba usury interest forbidden trade",
    "hukum jual beli online": "trade commerce buying selling",
    "syarat sah wudhu": "ablution wudu purity wash",
    "rukun salat": "pillars prayer salat establish",
    "hukum perempuan menjadi imam": "woman prayer leader imam",
    "hukum musik dalam Islam": "music permissible forbidden entertainment",
    "cara berpuasa yang benar": "fasting Ramadan correct method",
    "syarat haji": "hajj pilgrimage able afford",
    "hukum nikah beda agama": "marriage interfaith disbeliever",
    "hukum waris dalam Islam": "inheritance share bequest",
    "bagaimana mengatasi kesedihan dengan al-Quran": "sadness grief comfort Quran",
    "doa untuk orang tua yang sakit": "parents sick mercy supplication",
    "ayat tentang sabar dalam ujian": "patience trial test affliction",
    "doa sebelum belajar": "knowledge learning seek understanding",
    "ayat tentang taubat": "repentance taubah forgiveness return",
    "bagaimana cara memperkuat iman": "strengthen faith iman believers",
    "ayat tentang persaudaraan Muslim": "brotherhood Muslims believers united",
    "doa untuk dimudahkan rezeki": "sustenance provision rizq Allah",
    "ayat tentang kasih sayang Allah": "mercy compassion Allah Most Merciful",
    "doa ketika bingung memilih": "guidance choice decision istikhara",
    "ayat tentang kejujuran": "truthful honesty truth speak",
    "ayat tentang menahan amarah": "anger restrain swallow forgive",
    "ayat tentang sedekah": "charity sadaqah spend",
    "ayat tentang akhirat": "hereafter afterlife next world",
    "ayat tentang surga dan neraka": "paradise hell garden fire",
    "ayat tentang penciptaan manusia": "creation man clay humanity",
    "ayat tentang nabi Muhammad": "Muhammad messenger prophet",
    "ayat tentang tanda-tanda kiamat": "signs hour judgment day approach",
    "ayat tentang adil": "justice fair stand witnesses",
    "ayat tentang ilmu pengetahuan": "knowledge learning wisdom",
}


STOP_WORDS = {"a", "an", "the", "of", "in", "on", "to", "is", "are",
              "what", "how", "does", "say", "says", "verses", "about",
              "ayat", "tentang", "doa", "hukum", "ayah"}


def _post_fts(keywords, k):
    url = f"{SUPABASE_URL}/rest/v1/rpc/search_tafsir_fts"
    body = json.dumps({"query": keywords, "lim": k}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"apikey": SUPABASE_KEY,
                 "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def fts_top_k(keywords, k=5):
    """Try the keyword string AS-IS (websearch AND). If 0 results, retry
    with each meaningful word OR'd together — much more permissive."""
    if not SUPABASE_KEY:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY not set in .env")
    try:
        rows = _post_fts(keywords, k)
        if rows:
            return rows
        # OR fallback
        words = [w for w in keywords.lower().split()
                 if len(w) > 2 and w not in STOP_WORDS]
        if not words:
            return []
        or_query = " OR ".join(words)
        return _post_fts(or_query, k)
    except Exception as e:
        print(f"  FTS error for '{keywords[:40]}…': {e}", file=sys.stderr)
        return []


def candidate_row(query, language):
    if language == "en":
        kw = query
    else:
        kw = KEYWORD_MAP.get(query)
        if kw is None:
            print(f"  [warn] no keyword map for {language} query: {query}",
                  file=sys.stderr)
            kw = query  # fall back to raw query (will likely return nothing)

    # Pull 15 raw rows so after dedupe (corpus has 2 scholars per ayah →
    # same ayah appears up to 2× in FTS results) we keep a healthy top-5.
    rows = fts_top_k(kw, k=15)
    seen = set()
    candidates = []
    for r in rows:
        ayah_id = r.get("ayah_id")
        if ayah_id in seen:
            continue
        seen.add(ayah_id)
        excerpt = (r.get("english_translation") or r.get("english_text") or "")[:140]
        candidates.append({
            "ayah_id": ayah_id,
            "ref": f"{r.get('surah_number')}:{r.get('ayah_number')}",
            "excerpt": excerpt,
            "scholar": r.get("scholar_name"),
            "rank": r.get("rank"),
        })
        if len(candidates) >= 5:
            break
    return {
        "query": query,
        "language": language,
        "fts_keywords": kw,
        "candidates": candidates,
    }


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    seeds = (
        [(q, "ar") for q in SEED_ARABIC]
        + [(q, "id") for q in SEED_BAHASA]
        + [(q, "en") for q in SEED_ENGLISH]
    )

    for i, (q, lang) in enumerate(seeds, 1):
        print(f"[{i}/{len(seeds)}] [{lang}] {q[:60]}…")
        rows.append(candidate_row(q, lang))

    OUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    n_with = sum(1 for r in rows if r["candidates"])
    print(f"\nWrote {len(rows)} rows to {OUT_PATH} ({n_with} with ≥1 candidate).")


if __name__ == "__main__":
    main()
