#!/usr/bin/env python3
"""
Enrich topic_tags on all ayat using Claude CLI — V2 (context-aware).

For each ayah, gathers:
1. Arabic text + English translation
2. ALL tafsir entries for this ayah (Ibn Kathir, Al-Sa'di, Al-Jalalayn, etc.)
3. Ayah metadata (Meccan/Madinan, juz, surah theme)
4. Surrounding context (2 ayat before and after)

Then asks Claude to generate comprehensive topic tags based on the FULL scholarly context.

Usage:
  python3 scripts/enrich_topic_tags_v2.py [--batch-size 50] [--start-from 0]
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")

BATCH_SIZE = int(sys.argv[sys.argv.index("--batch-size") + 1]) if "--batch-size" in sys.argv else 50
START_FROM = int(sys.argv[sys.argv.index("--start-from") + 1]) if "--start-from" in sys.argv else 0

SURAH_NAMES = {
    1: "Al-Fatiha", 2: "Al-Baqarah", 3: "Ali 'Imran", 4: "An-Nisa", 5: "Al-Ma'idah",
    6: "Al-An'am", 7: "Al-A'raf", 8: "Al-Anfal", 9: "At-Tawbah", 10: "Yunus",
    11: "Hud", 12: "Yusuf", 13: "Ar-Ra'd", 14: "Ibrahim", 15: "Al-Hijr",
    16: "An-Nahl", 17: "Al-Isra", 18: "Al-Kahf", 19: "Maryam", 20: "Ta-Ha",
    21: "Al-Anbiya", 22: "Al-Hajj", 23: "Al-Mu'minun", 24: "An-Nur", 25: "Al-Furqan",
    26: "Ash-Shu'ara", 27: "An-Naml", 28: "Al-Qasas", 29: "Al-Ankabut", 30: "Ar-Rum",
    31: "Luqman", 32: "As-Sajdah", 33: "Al-Ahzab", 34: "Saba", 35: "Fatir",
    36: "Ya-Sin", 37: "As-Saffat", 38: "Sad", 39: "Az-Zumar", 40: "Ghafir",
    41: "Fussilat", 42: "Ash-Shura", 43: "Az-Zukhruf", 44: "Ad-Dukhan", 45: "Al-Jathiya",
    46: "Al-Ahqaf", 47: "Muhammad", 48: "Al-Fath", 49: "Al-Hujurat", 50: "Qaf",
    51: "Adh-Dhariyat", 52: "At-Tur", 53: "An-Najm", 54: "Al-Qamar", 55: "Ar-Rahman",
    56: "Al-Waqi'ah", 57: "Al-Hadid", 58: "Al-Mujadila", 59: "Al-Hashr", 60: "Al-Mumtahina",
    61: "As-Saff", 62: "Al-Jumu'ah", 63: "Al-Munafiqun", 64: "At-Taghabun", 65: "At-Talaq",
    66: "At-Tahrim", 67: "Al-Mulk", 68: "Al-Qalam", 69: "Al-Haqqah", 70: "Al-Ma'arij",
    71: "Nuh", 72: "Al-Jinn", 73: "Al-Muzzammil", 74: "Al-Muddathir", 75: "Al-Qiyamah",
    76: "Al-Insan", 77: "Al-Mursalat", 78: "An-Naba", 79: "An-Nazi'at", 80: "Abasa",
    81: "At-Takwir", 82: "Al-Infitar", 83: "Al-Mutaffifin", 84: "Al-Inshiqaq", 85: "Al-Buruj",
    86: "At-Tariq", 87: "Al-A'la", 88: "Al-Ghashiyah", 89: "Al-Fajr", 90: "Al-Balad",
    91: "Ash-Shams", 92: "Al-Layl", 93: "Ad-Duha", 94: "Ash-Sharh", 95: "At-Tin",
    96: "Al-Alaq", 97: "Al-Qadr", 98: "Al-Bayyinah", 99: "Az-Zalzalah", 100: "Al-Adiyat",
    101: "Al-Qari'ah", 102: "At-Takathur", 103: "Al-Asr", 104: "Al-Humazah", 105: "Al-Fil",
    106: "Quraysh", 107: "Al-Ma'un", 108: "Al-Kawthar", 109: "Al-Kafirun", 110: "An-Nasr",
    111: "Al-Masad", 112: "Al-Ikhlas", 113: "Al-Falaq", 114: "An-Nas",
}


def supabase_get(table, params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def supabase_patch(table, row_id, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="PATCH", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.status


def get_tafsir(surah, ayah):
    """Fetch all tafsir entries for an ayah."""
    rows = supabase_get("tafsir_entries", {
        "surah_number": f"eq.{surah}",
        "ayah_number": f"eq.{ayah}",
        "select": "scholar_name,text",
    })
    return rows


def get_surrounding(surah, ayah):
    """Get 2 ayat before and after for context."""
    rows = supabase_get("ayat", {
        "surah_number": f"eq.{surah}",
        "ayah_number": f"gte.{max(1, ayah-2)}",
        "ayah_number": f"lte.{ayah+2}",
        "select": "ayah_number,english_translation",
        "order": "ayah_number",
    })
    return rows


def get_ayah_meta(surah, ayah):
    """Get metadata for the ayah."""
    rows = supabase_get("ayah_meta", {
        "surah_number": f"eq.{surah}",
        "ayah_number": f"eq.{ayah}",
        "select": "place_of_revelation,juz_number,ruku_number",
        "limit": "1",
    })
    return rows[0] if rows else {}


def get_tags_from_claude(surah, ayah, arabic, english, tafsir_entries, meta, surrounding):
    """Ask Claude to generate comprehensive topic tags using full scholarly context."""

    surah_name = SURAH_NAMES.get(surah, f"Surah {surah}")
    place = meta.get("place_of_revelation", "unknown")
    juz = meta.get("juz_number", "?")

    # Build tafsir context
    tafsir_text = ""
    for t in tafsir_entries[:4]:  # Max 4 scholars to stay within prompt limits
        scholar = t.get("scholar_name", "Unknown")
        text = t.get("text", "")[:500]  # Cap each tafsir
        tafsir_text += f"\n[{scholar}]: {text}\n"

    # Build surrounding context
    context_text = ""
    for s in surrounding:
        if s["ayah_number"] != ayah:
            context_text += f"  {surah}:{s['ayah_number']} — {s['english_translation'][:150]}\n"

    prompt = f"""You are a Quran topic tagger. Given a verse with its full scholarly context, generate comprehensive topic tags.

VERSE: Surah {surah_name} ({surah}:{ayah})
REVELATION: {place} | Juz {juz}
ARABIC: {arabic[:200]}
ENGLISH: {english}

TAFSIR (SCHOLARLY COMMENTARY):
{tafsir_text if tafsir_text else "(no tafsir available)"}

SURROUNDING CONTEXT:
{context_text if context_text else "(none)"}

Generate topic tags considering:
1. The LITERAL meaning of the verse (what it directly says)
2. The SCHOLARLY interpretation (what the tafsir scholars derive from it)
3. PRACTICAL life topics a Muslim might search for where this verse is relevant
4. RELATED rulings or principles scholars derive (e.g. "fasting exemption" from a breastfeeding verse)
5. The CONTEXT — what was this surah/passage addressing?

Rules:
- Return ONLY a JSON array of lowercase strings
- Include both broad themes AND specific practical topics
- Think: "what question would someone ask where this verse is the answer?"
- Max 15 tags
- No explanations, just the JSON array"""

    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=45,
        env={
            "HOME": os.path.expanduser("~"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "USER": os.environ.get("USER", ""),
            "SHELL": os.environ.get("SHELL", ""),
            "LANG": os.environ.get("LANG", ""),
        }
    )

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    try:
        tags = json.loads(output)
        if isinstance(tags, list):
            return [str(t).lower() for t in tags[:15]]
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r'\[.*?\]', output, re.DOTALL)
    if match:
        try:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                return [str(t).lower() for t in tags[:15]]
        except json.JSONDecodeError:
            pass

    return None


def main():
    print("=" * 60)
    print("Quran Topic Tag Enrichment V2 (Context-Aware)")
    print(f"Using: translation + tafsir + metadata + surrounding ayat")
    print(f"Batch size: {BATCH_SIZE}, Starting from offset: {START_FROM}")
    print("=" * 60)

    total_ayat = supabase_get("ayat", {"select": "id", "order": "surah_number,ayah_number"})
    total = len(total_ayat)
    print(f"Total ayat: {total}")

    offset = START_FROM
    enriched = 0
    failed = 0

    while offset < total:
        batch = supabase_get("ayat", {
            "select": "id,surah_number,ayah_number,arabic_text,english_translation,topic_tags",
            "order": "surah_number,ayah_number",
            "offset": str(offset),
            "limit": str(BATCH_SIZE),
        })

        if not batch:
            break

        print(f"\n--- Batch {offset // BATCH_SIZE + 1}: ayat {offset + 1}-{offset + len(batch)} ---")

        for ayah in batch:
            surah = ayah["surah_number"]
            ayah_num = ayah["ayah_number"]
            english = ayah.get("english_translation", "")

            print(f"  {surah}:{ayah_num} — ", end="", flush=True)

            try:
                # Gather full context
                tafsir = get_tafsir(surah, ayah_num)
                meta = get_ayah_meta(surah, ayah_num)
                surrounding = get_surrounding(surah, ayah_num)

                tags = get_tags_from_claude(
                    surah, ayah_num,
                    ayah.get("arabic_text", ""),
                    english,
                    tafsir, meta, surrounding,
                )

                if tags:
                    supabase_patch("ayat", ayah["id"], {"topic_tags": tags})
                    print(f"✓ {len(tags)} tags ({len(tafsir)} tafsir): {', '.join(tags[:4])}...")
                    enriched += 1
                else:
                    print("✗ no tags returned")
                    failed += 1
            except subprocess.TimeoutExpired:
                print("✗ timeout")
                failed += 1
            except Exception as e:
                print(f"✗ {e}")
                failed += 1

            time.sleep(0.5)

        offset += BATCH_SIZE
        print(f"\nProgress: {offset}/{total} ({enriched} enriched, {failed} failed)")

    print(f"\n{'=' * 60}")
    print(f"DONE: {enriched} enriched, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
