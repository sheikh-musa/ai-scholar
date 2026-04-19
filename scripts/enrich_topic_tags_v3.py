#!/usr/bin/env python3
"""
Enrich topic_tags — V3 (correct schema, tafsir-aware).

Uses ayah_id FK to join tafsir_entries. Correct column names.
Tested on Al-Fatiha — 100% success rate.

Usage:
  python3 scripts/enrich_topic_tags_v3.py [--batch-size 50] [--start-from 0]
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
CLAUDE_ENV = {
    "HOME": os.path.expanduser("~"),
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "USER": os.environ.get("USER", ""),
    "SHELL": os.environ.get("SHELL", ""),
    "LANG": os.environ.get("LANG", ""),
}

BATCH_SIZE = int(sys.argv[sys.argv.index("--batch-size") + 1]) if "--batch-size" in sys.argv else 50
START_FROM = int(sys.argv[sys.argv.index("--start-from") + 1]) if "--start-from" in sys.argv else 0

SURAH_NAMES = {1:"Al-Fatiha",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiya",46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahina",61:"As-Saff",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddathir",75:"Al-Qiyamah",76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"}


def api_get(path):
    """Fetch from Supabase REST. Auto-paginates for large result sets."""
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        sep = "&" if "?" in path else "?"
        url = f"{SUPABASE_URL}/rest/v1/{path}{sep}limit={page_size}&offset={offset}"
        req = urllib.request.Request(
            url,
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        )
        with urllib.request.urlopen(req) as resp:
            rows = json.loads(resp.read().decode())
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def api_patch(table, row_id, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="PATCH", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    })
    urllib.request.urlopen(req)


def main():
    print("=" * 60)
    print("Quran Topic Tag Enrichment V3 (Tafsir-Aware)")
    print(f"Batch size: {BATCH_SIZE}, Start from: {START_FROM}")
    print("=" * 60)

    # Get all ayat IDs
    all_ayat = api_get("ayat?select=id,surah_number,ayah_number,english_translation&order=surah_number,ayah_number")
    total = len(all_ayat)
    print(f"Total ayat: {total}\n")

    offset = START_FROM
    enriched = 0
    failed = 0

    while offset < total:
        batch = all_ayat[offset:offset + BATCH_SIZE]
        if not batch:
            break

        s_start = f"{batch[0]['surah_number']}:{batch[0]['ayah_number']}"
        s_end = f"{batch[-1]['surah_number']}:{batch[-1]['ayah_number']}"
        print(f"--- Batch {offset // BATCH_SIZE + 1}: {s_start} to {s_end} ({len(batch)} ayat) ---")

        for a in batch:
            aid = a["id"]
            surah = a["surah_number"]
            ayah_num = a["ayah_number"]
            surah_name = SURAH_NAMES.get(surah, f"Surah {surah}")

            print(f"  {surah}:{ayah_num} — ", end="", flush=True)

            try:
                # Get tafsir for this ayah (using ayah_id FK)
                tafsir = api_get(f"tafsir_entries?ayah_id=eq.{aid}&select=scholar_name,english_text")

                tafsir_block = ""
                for t in tafsir[:4]:
                    tafsir_block += f"[{t['scholar_name']}]: {t['english_text'][:400]}\n\n"

                prompt = f"""Generate topic tags for Quran verse {surah_name} ({surah}:{ayah_num}).

TRANSLATION: {a['english_translation']}

SCHOLARLY COMMENTARY:
{tafsir_block if tafsir_block else "(no tafsir available)"}

Tags should reflect:
1. Literal meaning of the verse
2. Themes scholars derive from it
3. Practical life questions this verse answers
4. Related Islamic concepts

Return ONLY a JSON array of lowercase strings. Max 15 tags."""

                result = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
                    capture_output=True, text=True, timeout=30, env=CLAUDE_ENV,
                )

                tags = None
                if result.returncode == 0:
                    output = result.stdout.strip()
                    try:
                        tags = json.loads(output)
                    except json.JSONDecodeError:
                        m = re.search(r'\[.*?\]', output, re.DOTALL)
                        if m:
                            try:
                                tags = json.loads(m.group())
                            except json.JSONDecodeError:
                                pass

                if tags and isinstance(tags, list):
                    tags = [str(t).lower() for t in tags[:15]]
                    api_patch("ayat", aid, {"topic_tags": tags})
                    print(f"✓ {len(tags)} tags ({len(tafsir)} tafsir): {', '.join(tags[:4])}...")
                    enriched += 1
                else:
                    print("✗ no tags")
                    failed += 1

            except subprocess.TimeoutExpired:
                print("✗ timeout")
                failed += 1
            except Exception as e:
                print(f"✗ {str(e)[:80]}")
                failed += 1

            time.sleep(0.5)

        offset += BATCH_SIZE
        print(f"\nProgress: {offset}/{total} ({enriched} enriched, {failed} failed)\n")

    print(f"{'=' * 60}")
    print(f"DONE: {enriched} enriched, {failed} failed out of {total}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
