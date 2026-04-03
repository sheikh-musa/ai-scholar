#!/usr/bin/env python3
"""
Ingest Quran text + tafsir from public CDN into Supabase via REST API.

Sources:
  - Quran text: risan/quran-json (Sahih International)
  - Tafsir: spa5k/tafsir_api (Ibn Kathir, Al-Jalalayn, Al-Qurtubi, Al-Sa'di)
"""

import json
import os
import sys
import time
import urllib.request

SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"

QURAN_CDN = "https://cdn.jsdelivr.net/gh/risan/quran-json@master/dist/chapters/en/{surah}.json"
TAFSIR_CDN = "https://cdn.jsdelivr.net/gh/spa5k/tafsir_api/tafsir/{edition}/{surah}.json"

TAFSIR_EDITIONS = {
    "Ibn Kathir": {"slug": "en-tafisr-ibn-kathir", "source": "Tafsir Ibn Kathir", "lang": "en"},
    "Al-Jalalayn": {"slug": "en-al-jalalayn", "source": "Tafsir al-Jalalayn", "lang": "en"},
    "Al-Qurtubi": {"slug": "ar-tafseer-al-qurtubi", "source": "Al-Jami li Ahkam al-Quran", "lang": "ar"},
    "Al-Sa'di": {"slug": "ar-tafseer-al-saddi", "source": "Taysir al-Karim al-Rahman", "lang": "ar"},
}

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=ignore-duplicates,return=minimal",
}


def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AlBayan/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return None


def supabase_post(table, rows):
    """POST rows to Supabase REST API. Returns True on success."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    data = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        # Duplicate key errors are fine (ON CONFLICT ignore)
        if "duplicate" in body.lower() or "conflict" in body.lower() or e.code == 409:
            return True
        print(f"    HTTP {e.code}: {body[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"    Error: {e}", file=sys.stderr)
        return False


def supabase_get(table, params=""):
    """GET from Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    GET Error: {e}", file=sys.stderr)
        return []


def truncate_text(text, max_len=3000):
    if not text or len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_period = cut.rfind(".")
    if last_period > max_len // 2:
        return cut[:last_period + 1]
    return cut + "..."


def ingest_surah(surah_num):
    """Ingest one surah: fetch data, insert ayat, insert tafsir."""
    print(f"\n{'='*50}")
    print(f"Surah {surah_num}")
    print(f"{'='*50}")

    # 1. Fetch Quran text
    print(f"  Fetching Quran text...")
    quran = fetch_json(QURAN_CDN.format(surah=surah_num))
    if not quran:
        print(f"  FAILED to fetch Quran text")
        return False

    verses = quran.get("verses", [])
    surah_name = quran.get("transliteration", f"Surah {surah_num}")
    print(f"  {surah_name}: {len(verses)} verses")

    # 2. Fetch all tafsir
    tafsir_data = {}
    for scholar, info in TAFSIR_EDITIONS.items():
        print(f"  Fetching {scholar}...")
        data = fetch_json(TAFSIR_CDN.format(edition=info["slug"], surah=surah_num))
        if data and "ayahs" in data:
            tafsir_data[scholar] = {a["ayah"]: a["text"] for a in data["ayahs"]}
            print(f"    {len(data['ayahs'])} entries")
        else:
            print(f"    MISSING")
        time.sleep(0.15)

    # 3. Insert ayat in batches of 20
    print(f"  Inserting ayat...")
    ayat_inserted = 0
    for i in range(0, len(verses), 20):
        batch = verses[i:i+20]
        rows = [{
            "surah_number": surah_num,
            "ayah_number": v["id"],
            "arabic_text": v.get("text", ""),
            "english_translation": v.get("translation", ""),
            "translator": "Sahih International",
            "topic_tags": []
        } for v in batch]

        if supabase_post("ayat", rows):
            ayat_inserted += len(batch)
        else:
            print(f"    Failed batch {i}-{i+len(batch)}")

    print(f"  Inserted {ayat_inserted}/{len(verses)} ayat")

    # 4. Get ayat IDs for this surah
    print(f"  Fetching ayat IDs...")
    existing = supabase_get("ayat", f"surah_number=eq.{surah_num}&select=id,ayah_number&order=ayah_number")
    ayah_id_map = {a["ayah_number"]: a["id"] for a in existing}
    print(f"  Got {len(ayah_id_map)} IDs")

    # 5. Check existing tafsir to avoid duplicates
    if ayah_id_map:
        sample_ids = list(ayah_id_map.values())[:5]
        ids_param = ",".join(f'"{x}"' for x in sample_ids)
        existing_tafsir = supabase_get("tafsir_entries", f"ayah_id=in.({ids_param})&select=ayah_id,scholar_name")
        existing_pairs = {(t["ayah_id"], t["scholar_name"]) for t in existing_tafsir}
    else:
        existing_pairs = set()

    # 6. Insert tafsir in batches
    print(f"  Inserting tafsir...")
    tafsir_inserted = 0
    tafsir_skipped = 0

    for scholar, info in TAFSIR_EDITIONS.items():
        texts = tafsir_data.get(scholar, {})
        if not texts:
            continue

        batch = []
        for ayah_num, text in texts.items():
            ayah_id = ayah_id_map.get(ayah_num)
            if not ayah_id:
                continue

            truncated = truncate_text(text)
            if not truncated:
                continue

            if info["lang"] == "en":
                row = {
                    "ayah_id": ayah_id,
                    "scholar_name": scholar,
                    "source_work": info["source"],
                    "english_text": truncated,
                    "output_tier": "paraphrased"
                }
            else:
                row = {
                    "ayah_id": ayah_id,
                    "scholar_name": scholar,
                    "source_work": info["source"],
                    "arabic_text": truncated,
                    "english_text": "[Arabic tafsir — translation pending]",
                    "output_tier": "paraphrased"
                }

            batch.append(row)

            if len(batch) >= 30:
                if supabase_post("tafsir_entries", batch):
                    tafsir_inserted += len(batch)
                batch = []

        if batch:
            if supabase_post("tafsir_entries", batch):
                tafsir_inserted += len(batch)

    print(f"  Inserted {tafsir_inserted} tafsir entries")
    return True


def main():
    if len(sys.argv) > 1:
        if "-" in sys.argv[1]:
            start, end = sys.argv[1].split("-")
            surahs = range(int(start), int(end) + 1)
        else:
            surahs = [int(x) for x in sys.argv[1:]]
    else:
        surahs = range(1, 115)

    success = 0
    failed = 0

    for s in surahs:
        if ingest_surah(s):
            success += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"DONE: {success} surahs ingested, {failed} failed")


if __name__ == "__main__":
    main()
