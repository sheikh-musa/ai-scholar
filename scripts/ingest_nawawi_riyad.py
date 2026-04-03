#!/usr/bin/env python3
"""
Ingest 40 Hadith of Nawawi + Riyad al-Salihin into Supabase.

Sources:
  - Nawawi 40: fawazahmed0/hadith-api on jsDelivr CDN (42 hadiths)
  - Riyad al-Salihin: CheeseWithSauce/HadithsJSONFormat on jsDelivr CDN (~1900 hadiths)

Usage:
  python3 scripts/ingest_nawawi_riyad.py           # Both
  python3 scripts/ingest_nawawi_riyad.py nawawi     # Just Nawawi
  python3 scripts/ingest_nawawi_riyad.py riyad      # Just Riyad
"""

import json
import sys
import re
import time
import urllib.request
import urllib.error

# --- Config ---
SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=ignore-duplicates,return=minimal",
}

NAWAWI_CDN = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1"
RIYAD_CDN = "https://cdn.jsdelivr.net/gh/CheeseWithSauce/HadithsJSONFormat@main/Sunnah/riyadussalihin"

RIYAD_BOOKS = [
    "the_book_of_miscellany",
    "001_the_book_of_good_manners",
    "002_the_book_about_the_etiquette_of_eating",
    "003_the_book_of_dress",
    "004_the_book_of_the_etiquette_of_sleeping_lying_and_sitting_etc",
    "005_the_book_of_greetings",
    "006_the_book_of_visiting_the_sick",
    "007_the_book_of_etiquette_of_traveling",
    "008_the_book_of_virtues",
    "009_the_book_of_itikaf",
    "010_the_book_of_hajj",
    "011_the_book_of_jihad",
    "012_the_book_of_knowledge",
    "013_the_book_of_praise_and_gratitude_to_allah",
    "014_the_book_of_supplicating_allah_to_exalt_the_mention_of_allahs_messenger",
    "015_the_book_of_the_remembrance_of_allah",
    "016_the_book_of_dua_supplications",
    "017_the_book_of_the_prohibited_actions",
    "018_the_book_of_miscellaneous_ahadith_of_significant_values",
    "019_the_book_of_forgiveness",
]


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MizanBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        text = raw.decode("utf-8-sig")  # Handle BOM
        return json.loads(text)


def supabase_post(table, rows):
    url = SUPABASE_URL + "/rest/v1/" + table
    payload = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    HTTP {e.code}: {body[:200]}")
        return e.code


def supabase_get(path):
    url = SUPABASE_URL + "/rest/v1/" + path
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_narrator(text):
    m = re.match(r"(?:Narrated|It is narrated|It was narrated|On the authority of)\s+([^:,]+?)(?:\s*[:,]|\s+that\b|\s+who\b)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(".")
    return None


def get_or_create_collection(name, full_name, author, description):
    existing = supabase_get(f"hadith_collections?name=eq.{name}&select=id")
    if existing:
        print(f"  Collection exists: {existing[0]['id']}")
        return existing[0]["id"]
    row = {"name": name, "full_name": full_name, "author": author, "description": description}
    status = supabase_post("hadith_collections", [row])
    if status not in (200, 201):
        print(f"  ERROR creating collection: {status}")
        return None
    existing = supabase_get(f"hadith_collections?name=eq.{name}&select=id")
    print(f"  Collection created: {existing[0]['id']}")
    return existing[0]["id"]


# --- Nawawi 40 ---
def ingest_nawawi():
    print("\n" + "=" * 60)
    print("  40 Hadith of Imam al-Nawawi")
    print("=" * 60)

    col_id = get_or_create_collection(
        "nawawi40",
        "40 Hadith of Imam al-Nawawi",
        "Imam Yahya ibn Sharaf al-Nawawi",
        "The foundational 42 hadiths (40 + 2 by Ibn Rajab) covering the core principles of Islam"
    )
    if not col_id:
        return 0

    # Fetch English
    print("  Fetching English...")
    eng_data = fetch_json(f"{NAWAWI_CDN}/editions/eng-nawawi.json")
    eng_hadiths = eng_data.get("hadiths", [])
    print(f"  English hadiths: {len(eng_hadiths)}")

    # Fetch Arabic
    print("  Fetching Arabic...")
    ara_map = {}
    try:
        ara_data = fetch_json(f"{NAWAWI_CDN}/editions/ara-nawawi.json")
        for h in ara_data.get("hadiths", []):
            ara_map[h["hadithnumber"]] = h.get("text", "")
        print(f"  Arabic hadiths: {len(ara_map)}")
    except Exception as e:
        print(f"  Warning: Arabic fetch failed: {e}")

    rows = []
    for h in eng_hadiths:
        hnum = h["hadithnumber"]
        eng_text = h.get("text", "")
        if not eng_text:
            continue
        rows.append({
            "collection_id": col_id,
            "hadith_number": str(hnum),
            "arabic_number": str(h.get("arabicnumber", hnum)),
            "english_text": eng_text,
            "arabic_text": ara_map.get(hnum, None),
            "grading": "sahih",  # Nawawi selected only sahih/hasan
            "narrator": extract_narrator(eng_text),
            "section_name": "40 Hadith al-Nawawi",
        })

    # Insert all at once (only 42)
    status = supabase_post("hadiths", rows)
    if status in (200, 201):
        print(f"  Done: {len(rows)} hadiths inserted")
        return len(rows)
    else:
        print(f"  ERROR inserting: {status}")
        return 0


# --- Riyad al-Salihin ---
def ingest_riyad():
    print("\n" + "=" * 60)
    print("  Riyad al-Salihin")
    print("=" * 60)

    col_id = get_or_create_collection(
        "riyadussalihin",
        "Riyad al-Salihin (Gardens of the Righteous)",
        "Imam Yahya ibn Sharaf al-Nawawi",
        "A compilation of ~1900 hadiths organized by topic, covering virtues, manners, worship, and daily life"
    )
    if not col_id:
        return 0

    total_inserted = 0
    BATCH_SIZE = 50

    for book_idx, book_file in enumerate(RIYAD_BOOKS):
        print(f"\n  Book {book_idx}: {book_file}")
        try:
            data = fetch_json(f"{RIYAD_CDN}/{book_file}.json")
        except Exception as e:
            print(f"    ERROR fetching: {e}")
            continue

        if not isinstance(data, list):
            print(f"    Unexpected format: {type(data)}")
            continue

        print(f"    Hadiths in book: {len(data)}")
        batch = []

        for h in data:
            eng_text = h.get("english", "")
            if not eng_text:
                continue

            # Parse riyad number from reference string
            # "Reference : Riyad as-Salihin 680 In-book reference : Book 1, Hadith 1"
            ref_str = h.get("reference", "")
            riyad_num = None
            m = re.search(r'Riyad as-Salihin\s+(\d+)', ref_str)
            if m:
                riyad_num = m.group(1)
            else:
                riyad_num = str(h.get("id", ""))

            # Parse book name
            book_name = h.get("book", "")
            # Clean up: "1 The Book of Good Manners كتاب الأدب" -> "The Book of Good Manners"
            book_clean = re.sub(r'^\d+\s*', '', book_name)
            book_clean = re.sub(r'\s*[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+.*$', '', book_clean).strip()

            if len(eng_text) > 5000:
                eng_text = eng_text[:4997] + "..."
            arabic = h.get("arabic", "")
            if len(arabic) > 5000:
                arabic = arabic[:4997] + "..."

            batch.append({
                "collection_id": col_id,
                "hadith_number": riyad_num,
                "section_number": book_idx,
                "section_name": book_clean or None,
                "english_text": eng_text,
                "arabic_text": arabic or None,
                "grading": None,  # Mixed grading, not consistently available
                "narrator": extract_narrator(eng_text),
            })

            if len(batch) >= BATCH_SIZE:
                status = supabase_post("hadiths", batch)
                if status in (200, 201):
                    total_inserted += len(batch)
                batch = []
                pct = total_inserted
                print(f"\r    Inserted: {total_inserted}", end="", flush=True)

        # Final batch for this book
        if batch:
            status = supabase_post("hadiths", batch)
            if status in (200, 201):
                total_inserted += len(batch)
            print(f"\r    Inserted: {total_inserted}", end="", flush=True)

        print()

    print(f"\n  Done: {total_inserted} hadiths inserted")
    return total_inserted


# --- Main ---
if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["nawawi", "riyad"]
    total = 0

    if "nawawi" in targets:
        total += ingest_nawawi()
    if "riyad" in targets:
        total += ingest_riyad()

    print(f"\n{'='*60}")
    print(f"DONE: {total} hadiths ingested")
