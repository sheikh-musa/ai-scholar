#!/usr/bin/env python3
"""
Ingest the six major hadith collections into Supabase.
Source: fawazahmed0/hadith-api on jsDelivr CDN.

Usage:
  python3 scripts/ingest_hadith.py              # All 6 collections
  python3 scripts/ingest_hadith.py bukhari       # Just Bukhari
  python3 scripts/ingest_hadith.py muslim nasai  # Multiple specific

Collections: bukhari, muslim, abudawud, tirmidhi, nasai, ibnmajah
"""

import json
import sys
import time
import urllib.request
import urllib.error
import re

# --- Config ---
SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"

CDN_BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1"

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": "Bearer " + SUPABASE_ANON_KEY,
    "Content-Type": "application/json",
    "Prefer": "resolution=ignore-duplicates,return=minimal",
}

COLLECTIONS = {
    "bukhari": {
        "full_name": "Sahih al-Bukhari",
        "author": "Imam Muhammad ibn Ismail al-Bukhari",
        "description": "The most authentic collection of hadith, compiled by Imam al-Bukhari (d. 870 CE). Contains 7,563 hadiths.",
    },
    "muslim": {
        "full_name": "Sahih Muslim",
        "author": "Imam Muslim ibn al-Hajjaj",
        "description": "The second most authentic hadith collection, compiled by Imam Muslim (d. 875 CE).",
    },
    "abudawud": {
        "full_name": "Sunan Abu Dawud",
        "author": "Imam Abu Dawud al-Sijistani",
        "description": "A major Sunan collection focusing on legal hadiths, compiled by Abu Dawud (d. 889 CE).",
    },
    "tirmidhi": {
        "full_name": "Jami at-Tirmidhi",
        "author": "Imam Abu Isa Muhammad al-Tirmidhi",
        "description": "A comprehensive hadith collection known for its jurisprudential commentary, compiled by al-Tirmidhi (d. 892 CE).",
    },
    "nasai": {
        "full_name": "Sunan an-Nasai",
        "author": "Imam Ahmad ibn Shuayb an-Nasai",
        "description": "Known for its strict authentication criteria, compiled by an-Nasai (d. 915 CE).",
    },
    "ibnmajah": {
        "full_name": "Sunan Ibn Majah",
        "author": "Imam Muhammad ibn Yazid Ibn Majah",
        "description": "The sixth of the Kutub al-Sittah, compiled by Ibn Majah (d. 887 CE).",
    },
}


def fetch_json(url):
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mizan/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_post(table, rows):
    """POST rows to Supabase REST API."""
    url = SUPABASE_URL + "/rest/v1/" + table
    data = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    HTTP {e.code}: {body[:200]}")
        return e.code


def supabase_get(path):
    """GET from Supabase REST API."""
    url = SUPABASE_URL + "/rest/v1/" + path
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_narrator(text):
    """Extract primary narrator from hadith text."""
    # Pattern: "Narrated X:" or "X reported:" etc.
    m = re.match(r"(?:Narrated|It was narrated from|It was narrated that)\s+([^:]+?)(?:\s*:|\s*that\b)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(".")
    return None


def determine_grade(grades):
    """Determine primary grade from list of scholar grades."""
    if not grades:
        return None

    grade_priority = {"sahih": 1, "hasan": 2, "daif": 3}
    best = None
    best_priority = 99

    for g in grades:
        grade_text = g.get("grade", "").lower().strip()
        for key, priority in grade_priority.items():
            if key in grade_text and priority < best_priority:
                best = key
                best_priority = priority

    return best


def ingest_collection(name):
    """Ingest a single hadith collection."""
    info = COLLECTIONS[name]
    print(f"\n{'='*60}")
    print(f"  {info['full_name']}")
    print(f"{'='*60}")

    # Check/create collection entry
    existing = supabase_get(f"hadith_collections?name=eq.{name}&select=id")
    if existing:
        collection_id = existing[0]["id"]
        print(f"  Collection exists: {collection_id}")
    else:
        row = {
            "name": name,
            "full_name": info["full_name"],
            "author": info["author"],
            "description": info["description"],
        }
        status = supabase_post("hadith_collections", [row])
        if status not in (200, 201):
            print(f"  ERROR creating collection: {status}")
            return 0

        existing = supabase_get(f"hadith_collections?name=eq.{name}&select=id")
        collection_id = existing[0]["id"]
        print(f"  Collection created: {collection_id}")

    # Fetch English hadiths
    print(f"  Fetching English edition...")
    try:
        eng_data = fetch_json(f"{CDN_BASE}/editions/eng-{name}.json")
    except Exception as e:
        print(f"  ERROR fetching English: {e}")
        return 0

    eng_hadiths = eng_data.get("hadiths", [])
    print(f"  English hadiths: {len(eng_hadiths)}")

    # Fetch Arabic hadiths
    print(f"  Fetching Arabic edition...")
    ara_hadiths_map = {}
    try:
        ara_data = fetch_json(f"{CDN_BASE}/editions/ara-{name}.json")
        for h in ara_data.get("hadiths", []):
            ara_hadiths_map[h["hadithnumber"]] = h.get("text", "")
        print(f"  Arabic hadiths: {len(ara_hadiths_map)}")
    except Exception as e:
        print(f"  Warning: Arabic fetch failed: {e}")

    # Fetch section info
    print(f"  Fetching sections...")
    sections_map = {}
    try:
        sections_data = fetch_json(f"{CDN_BASE}/editions/eng-{name}/sections.json")
        # sections_data is a list of section objects
        if isinstance(sections_data, list):
            for s in sections_data:
                sections_map[s.get("number")] = s.get("name", "")
        elif isinstance(sections_data, dict):
            for k, v in sections_data.items():
                sections_map[int(k)] = v if isinstance(v, str) else v.get("name", "")
        print(f"  Sections: {len(sections_map)}")
    except Exception as e:
        print(f"  Warning: Sections fetch failed: {e}")

    # Build rows and insert in batches
    total_inserted = 0
    batch = []
    BATCH_SIZE = 50

    for idx, h in enumerate(eng_hadiths):
        hnum = h["hadithnumber"]
        eng_text = h.get("text", "")
        if not eng_text:
            continue

        # Truncate very long hadiths
        if len(eng_text) > 5000:
            eng_text = eng_text[:4997] + "..."

        arabic = ara_hadiths_map.get(hnum, "")
        if len(arabic) > 5000:
            arabic = arabic[:4997] + "..."

        grades = h.get("grades", [])
        primary_grade = determine_grade(grades)

        # Determine section
        ref = h.get("reference", {})
        section_num = ref.get("book")

        row = {
            "collection_id": collection_id,
            "hadith_number": str(hnum),
            "arabic_number": str(h["arabicnumber"]) if h.get("arabicnumber") is not None else None,
            "section_number": int(section_num) if section_num is not None and isinstance(section_num, (int, float)) and float(section_num) == int(section_num) else None,
            "section_name": sections_map.get(section_num, "") if section_num else None,
            "arabic_text": arabic or None,
            "english_text": eng_text,
            "grading": primary_grade,
            "grading_details": grades if grades else None,
            "narrator": extract_narrator(eng_text),
            "reference_book": int(ref["book"]) if ref.get("book") is not None and isinstance(ref["book"], (int, float)) and float(ref["book"]) == int(ref["book"]) else None,
            "reference_hadith": int(ref["hadith"]) if ref.get("hadith") is not None and isinstance(ref["hadith"], (int, float)) and float(ref["hadith"]) == int(ref["hadith"]) else None,
        }
        batch.append(row)

        if len(batch) >= BATCH_SIZE:
            status = supabase_post("hadiths", batch)
            if status in (200, 201):
                total_inserted += len(batch)
            batch = []
            # Progress
            pct = ((idx + 1) / len(eng_hadiths)) * 100
            print(f"\r  Inserted: {total_inserted}/{len(eng_hadiths)} ({pct:.0f}%)", end="", flush=True)

    # Final batch
    if batch:
        status = supabase_post("hadiths", batch)
        if status in (200, 201):
            total_inserted += len(batch)

    print(f"\n  Done: {total_inserted} hadiths inserted")

    # Update collection totals
    # (Can't easily PATCH with anon key, so skip)
    return total_inserted


def main():
    collections = sys.argv[1:] if len(sys.argv) > 1 else list(COLLECTIONS.keys())

    # Validate
    for c in collections:
        if c not in COLLECTIONS:
            print(f"Unknown collection: {c}")
            print(f"Available: {', '.join(COLLECTIONS.keys())}")
            sys.exit(1)

    print(f"Ingesting {len(collections)} hadith collection(s): {', '.join(collections)}")

    total = 0
    failed = []
    for c in collections:
        try:
            count = ingest_collection(c)
            total += count
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append(c)

    print(f"\n{'='*60}")
    print(f"DONE: {total} hadiths ingested, {len(failed)} failed")
    if failed:
        print(f"Failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
