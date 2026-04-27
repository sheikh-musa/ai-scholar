#!/usr/bin/env python3
"""
Interactive CLI for Musa to curate the 90-query gold set
(30 Arabic + 30 Bahasa + 30 English) for ENCODER-EVAL.

Per CAI advisory: pre-seed candidate queries from existing topic taxonomies +
suggest primary ayah per query so Musa is verifying not formulating;
≤3 min/query target.

Output: evals/encoder_eval_gold_set.json — list of:
  {"query": "...", "language": "ar|id|en",
   "expected_top_5_ayah_ids": ["uuid", ...],
   "notes": "...", "verified_by": "musa", "verified_at": "..."}

Usage:
  python3 scripts/encoder_eval/build_gold_set.py [--phase 1|2|3]

Phases (per CAI):
  Phase 1: 30 queries (90 min)
  Phase 2: +30 queries (90 min)
  Phase 3: +30 queries (90 min)
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

SUPABASE_URL = (os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
                or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co"))
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

GOLD_SET_PATH = Path("evals/encoder_eval_gold_set.json")

# Pre-seed candidate queries — Musa edits / accepts / rejects each.
# 30 each, organized by category per ARCH-AL-BAYAN-ENCODER-EVAL spec.
SEED_ARABIC = [
    # 10 classical theological
    "ما هو التوكل على الله",
    "معنى الصبر في القرآن",
    "تعريف التقوى",
    "الفرق بين الإيمان والإسلام",
    "ما هو الإحسان",
    "صفات المؤمنين",
    "آية في الإخلاص",
    "أهمية النية في العبادة",
    "الفرق بين الشرك الأكبر والأصغر",
    "معنى أسماء الله الحسنى",
    # 10 colloquial spiritual
    "كيف أتغلب على الحزن",
    "الدعاء عند الكرب",
    "آيات تخفف القلق",
    "كيف أحفظ القرآن",
    "كيف أحب الله",
    "الدعاء قبل النوم",
    "آيات تذكر بالموت",
    "كيف أكون شاكرا",
    "الدعاء للوالدين",
    "كيف أحارب الكسل",
    # 10 specific-citation
    "آية الكرسي",
    "السورة التي تذكر يوم القيامة",
    "آيات الميراث",
    "آية الدين",
    "آيات الحجاب",
    "السورة التي ذكرت قصة موسى وفرعون",
    "آيات الصبر في سورة العصر",
    "آيات الصلاة الخمس",
    "آيات الصيام",
    "آيات الزكاة",
]

SEED_BAHASA = [
    # 10 doctrinal
    "apakah riba dalam Islam",
    "hukum jual beli online",
    "syarat sah wudhu",
    "rukun salat",
    "hukum perempuan menjadi imam",
    "hukum musik dalam Islam",
    "cara berpuasa yang benar",
    "syarat haji",
    "hukum nikah beda agama",
    "hukum waris dalam Islam",
    # 10 pastoral
    "bagaimana mengatasi kesedihan dengan al-Quran",
    "doa untuk orang tua yang sakit",
    "ayat tentang sabar dalam ujian",
    "doa sebelum belajar",
    "ayat tentang taubat",
    "bagaimana cara memperkuat iman",
    "ayat tentang persaudaraan Muslim",
    "doa untuk dimudahkan rezeki",
    "ayat tentang kasih sayang Allah",
    "doa ketika bingung memilih",
    # 10 cross-translation
    "ayat tentang kejujuran",
    "ayat tentang menahan amarah",
    "ayat tentang sedekah",
    "ayat tentang akhirat",
    "ayat tentang surga dan neraka",
    "ayat tentang penciptaan manusia",
    "ayat tentang nabi Muhammad",
    "ayat tentang tanda-tanda kiamat",
    "ayat tentang adil",
    "ayat tentang ilmu pengetahuan",
]

SEED_ENGLISH = [
    # 10 synonym tests
    "verses about endurance",  # → sabr
    "verses about gratitude",  # → shukr
    "verses about compassion",  # → rahma
    "verses about humility",
    "verses about justice",
    "verses about generosity",  # → sadaqah / infaq
    "verses about courage",
    "verses about forgiveness",
    "verses about wisdom",  # → hikmah
    "verses about contentment",  # → qana'ah
    # 10 conceptual
    "what does Islam say about social media addiction",
    "verses about feeling lost",
    "how to be a better parent according to the Quran",
    "what the Quran says about depression",
    "verses about choosing between two options",
    "how to forgive someone who hurt you",
    "what the Quran says about loneliness",
    "verses about purpose in life",
    "verses about dealing with regret",
    "how to handle wealth as a Muslim",
    # 10 Western-framing tests
    "mental health and Islam",
    "existential anxiety in the Quran",
    "verses for grief",
    "Islam on environmental stewardship",
    "Quran on time management",
    "Islam on work-life balance",
    "Islamic perspective on AI ethics",
    "Quran on intergenerational trauma",
    "Islam on consent in relationships",
    "Quran on imposter syndrome",
]


def api_get(path):
    sep = "&" if "?" in path else "?"
    url = f"{SUPABASE_URL}/rest/v1/{path}{sep}limit=20"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def suggest_candidates(query):
    """Use search_tafsir_fts to suggest top-5 candidate ayah_ids for a query.
    Musa verifies/edits."""
    keywords = " ".join(w for w in query.split() if len(w) > 2)
    if not keywords:
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/rpc/search_tafsir_fts"
        body = json.dumps({"query": keywords, "lim": 5}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                      headers={"apikey": SUPABASE_KEY,
                                               "Authorization": f"Bearer {SUPABASE_KEY}",
                                               "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  (FTS suggest failed: {e})")
        return []


def load_existing_gold():
    if GOLD_SET_PATH.exists():
        return json.loads(GOLD_SET_PATH.read_text())
    return []


def save_gold(rows):
    GOLD_SET_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLD_SET_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def interactive_label(query, language, suggestions):
    print(f"\n{'='*72}")
    print(f"  [{language.upper()}] {query}")
    print(f"{'='*72}")
    if suggestions:
        print(f"  Top FTS candidates (verify or override):")
        for i, s in enumerate(suggestions, 1):
            ref = f"{s.get('surah_number')}:{s.get('ayah_number')}"
            translation = (s.get('english_translation') or '')[:100]
            print(f"    [{i}] {ref}  {translation}…")
    else:
        print(f"  (no FTS candidates — manual entry required)")

    print(f"\n  Enter expected ayah refs (e.g., '2:153 17:36 ; notes here')")
    print(f"  Or 's' to skip, 'q' to quit & save")
    raw = input("  > ").strip()
    if raw.lower() == "q":
        return None
    if raw.lower() == "s":
        return "skip"

    # Parse "S:A S:A ; notes"
    parts = raw.split(";", 1)
    refs_str = parts[0].strip()
    notes = parts[1].strip() if len(parts) > 1 else ""

    expected_ayah_ids = []
    for ref in refs_str.split():
        if ":" not in ref:
            continue
        try:
            s, a = ref.split(":")
            rows = api_get(f"ayat?select=id&surah_number=eq.{int(s)}&ayah_number=eq.{int(a)}")
            if rows:
                expected_ayah_ids.append(rows[0]["id"])
        except Exception as e:
            print(f"  skip ref {ref}: {e}")

    if not expected_ayah_ids:
        print(f"  no valid refs parsed; skipping this query")
        return "skip"

    return {
        "query": query,
        "language": language,
        "expected_top_5_ayah_ids": expected_ayah_ids,
        "notes": notes,
        "verified_by": "musa",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    if not SUPABASE_KEY:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY not set in .env")

    phase = int(sys.argv[sys.argv.index("--phase") + 1] if "--phase" in sys.argv else 1)
    print(f"Gold-set curation Phase {phase}")
    print(f"Output: {GOLD_SET_PATH}")

    existing = load_existing_gold()
    existing_queries = {r["query"] for r in existing}
    print(f"Existing entries: {len(existing)}")

    # Phase plan: take 10 from each language per phase
    start_idx = (phase - 1) * 10
    end_idx = phase * 10
    queries = []
    for ar in SEED_ARABIC[start_idx:end_idx]:
        if ar not in existing_queries:
            queries.append((ar, "ar"))
    for id_ in SEED_BAHASA[start_idx:end_idx]:
        if id_ not in existing_queries:
            queries.append((id_, "id"))
    for en in SEED_ENGLISH[start_idx:end_idx]:
        if en not in existing_queries:
            queries.append((en, "en"))

    print(f"This phase: {len(queries)} new queries to label\n")

    for query, language in queries:
        suggestions = suggest_candidates(query) if language == "en" else []
        result = interactive_label(query, language, suggestions)
        if result is None:
            print("\nSaving and quitting…")
            break
        if result == "skip":
            continue
        existing.append(result)
        save_gold(existing)
        print(f"  ✓ saved ({len(existing)} total)")

    print(f"\nDone. Gold set has {len(existing)} entries.")
    by_lang = {}
    for r in existing:
        by_lang[r["language"]] = by_lang.get(r["language"], 0) + 1
    for lang, n in sorted(by_lang.items()):
        print(f"  {lang}: {n}")


if __name__ == "__main__":
    main()
