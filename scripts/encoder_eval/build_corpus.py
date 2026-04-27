#!/usr/bin/env python3
"""
Build the corpus-text-per-ayah file used by embed_corpus.py.

Per EMBED_PIPELINE_v02 §source-text-shape: single ayah-level concat of
arabic + translation + top-tafsir + asbab + topic_themes, capped ~4K tokens.

Output: evals/encoder_eval_corpus.jsonl — one ayah per line:
  {"ayah_id": "<uuid>", "surah": int, "ayah": int,
   "source_text": "...", "token_count_approx": int}

Usage:
  python3 scripts/encoder_eval/build_corpus.py [--out evals/encoder_eval_corpus.jsonl]
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

SUPABASE_URL = (os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
                or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co"))
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SURAH_NAMES = {1:"Al-Fatiha",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiya",46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahina",61:"As-Saff",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddathir",75:"Al-Qiyamah",76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"}

CHAR_PER_TOKEN_APPROX = 4  # rough average; good enough for cap budgeting
TARGET_TOKEN_CAP = 4000


def api_get_all(path):
    rows = []
    offset = 0
    while True:
        sep = "&" if "?" in path else "?"
        url = f"{SUPABASE_URL}/rest/v1/{path}{sep}limit=1000&offset={offset}"
        req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req) as resp:
            chunk = json.loads(resp.read())
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    return rows


def build_source_text(ayah, tafsir_rows, asbab_rows):
    surah_name = SURAH_NAMES.get(ayah["surah_number"], f"Surah {ayah['surah_number']}")
    parts = [
        f"Quran ayah {surah_name} ({ayah['surah_number']}:{ayah['ayah_number']})",
        f"Arabic: {ayah.get('arabic_text', '')}",
        f"English: {ayah.get('english_translation', '')}",
    ]
    for t in tafsir_rows[:2]:
        scholar = t.get("scholar_name") or "Unknown"
        text = (t.get("english_text") or "")[:1500]
        parts.append(f"Tafsir {scholar}: {text}")
    if asbab_rows:
        text = (asbab_rows[0].get("text_en") or "")[:500]
        if text:
            parts.append(f"Asbab al-Nuzul: {text}")
    if ayah.get("topic_tags"):
        themes = ", ".join(ayah["topic_tags"][:8])
        parts.append(f"Topic themes: {themes}")

    full = "\n".join(parts)
    # Cap at TARGET_TOKEN_CAP * char_per_token_approx
    cap_chars = TARGET_TOKEN_CAP * CHAR_PER_TOKEN_APPROX
    if len(full) > cap_chars:
        full = full[:cap_chars]
    return full


def main():
    out_path = Path(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
                    else "evals/encoder_eval_corpus.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Fetching ayat …")
    ayat = api_get_all("ayat?select=id,surah_number,ayah_number,arabic_text,english_translation,topic_tags&order=surah_number,ayah_number")
    print(f"  {len(ayat)} ayat")

    print(f"Fetching tafsir entries …")
    tafsir_all = api_get_all("tafsir_entries?select=ayah_id,scholar_name,english_text&order=ayah_id,scholar_name")
    tafsir_by_ayah = {}
    for t in tafsir_all:
        tafsir_by_ayah.setdefault(t["ayah_id"], []).append(t)
    print(f"  {len(tafsir_all)} tafsir entries across {len(tafsir_by_ayah)} ayat")

    print(f"Fetching asbab al-nuzul …")
    try:
        asbab_all = api_get_all("asbab_nuzul?select=ayah_number_quran,text_en&order=ayah_number_quran")
        # asbab_nuzul keys by ayah_number_quran (1-6236), need to map to ayah_id
        # Simpler: index by (surah, ayah) via a second query if needed; for now, skip if not joinable
        asbab_by_quran_num = {a["ayah_number_quran"]: a for a in asbab_all if a.get("ayah_number_quran")}
        print(f"  {len(asbab_all)} asbab rows")
    except Exception as e:
        print(f"  skipping asbab: {e}")
        asbab_by_quran_num = {}

    # Build position-based lookup so we can map asbab to ayah by Quranic position
    quran_pos = 0
    pos_to_ayat_id = {}
    for a in sorted(ayat, key=lambda r: (r["surah_number"], r["ayah_number"])):
        quran_pos += 1
        pos_to_ayat_id[quran_pos] = a["id"]
    asbab_by_ayah_id = {}
    for pos, asbab in asbab_by_quran_num.items():
        if pos in pos_to_ayat_id:
            asbab_by_ayah_id.setdefault(pos_to_ayat_id[pos], []).append(asbab)

    print(f"Writing corpus to {out_path} …")
    written = 0
    with out_path.open("w") as f:
        for a in ayat:
            tafsir = tafsir_by_ayah.get(a["id"], [])
            asbab = asbab_by_ayah_id.get(a["id"], [])
            text = build_source_text(a, tafsir, asbab)
            row = {
                "ayah_id": a["id"],
                "surah": a["surah_number"],
                "ayah": a["ayah_number"],
                "source_text": text,
                "token_count_approx": len(text) // CHAR_PER_TOKEN_APPROX,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    print(f"  wrote {written} rows")


if __name__ == "__main__":
    main()
