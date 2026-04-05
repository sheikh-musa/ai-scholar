#!/usr/bin/env python3
"""
Extract asbab al-nuzul (reasons of revelation) from existing tafsir entries.

Ibn Kathir and Al-Qurtubi frequently mention the circumstances of revelation.
This script asks Claude to extract the asbab from their commentary and populate
the asbab_nuzul table.

Usage:
  python3 scripts/extract_asbab_nuzul.py [--batch-size 50] [--start-from 0]
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


def supabase_get(table, params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def supabase_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.status


def extract_asbab(surah, ayah, tafsir_entries):
    """Ask Claude to extract asbab al-nuzul from tafsir commentary."""
    tafsir_text = ""
    for t in tafsir_entries:
        scholar = t.get("scholar_name", "")
        text = t.get("text", "")[:800]
        tafsir_text += f"\n[{scholar}]:\n{text}\n"

    prompt = f"""You are extracting asbab al-nuzul (reasons/circumstances of revelation) from tafsir commentary.

Verse: Surah {surah}, Ayah {ayah}

Tafsir entries:
{tafsir_text}

Task: If any tafsir mentions WHY or WHEN this verse was revealed (a specific event, question posed to the Prophet, or circumstance), extract it as a concise English paragraph.

Rules:
- Return ONLY a JSON object: {{"has_sabab": true/false, "text": "...", "source": "scholar name"}}
- If no specific reason of revelation is mentioned, return {{"has_sabab": false, "text": "", "source": ""}}
- The text should be a clear, concise paragraph (50-150 words) describing the circumstance
- Attribute to the scholar who mentions it
- Do NOT fabricate — only extract what the tafsir explicitly states
- If multiple scholars mention different aspects, combine into one coherent paragraph

Return ONLY the JSON object."""

    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=30,
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
        data = json.loads(output)
        return data
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*?\}', output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def main():
    print("=" * 60)
    print("Asbab al-Nuzul Extraction from Tafsir")
    print(f"Batch size: {BATCH_SIZE}, Starting from: {START_FROM}")
    print("=" * 60)

    all_ayat = supabase_get("ayat", {
        "select": "id,surah_number,ayah_number",
        "order": "surah_number,ayah_number",
    })
    total = len(all_ayat)
    print(f"Total ayat: {total}")

    offset = START_FROM
    extracted = 0
    no_sabab = 0
    failed = 0

    while offset < total:
        batch = all_ayat[offset:offset + BATCH_SIZE]
        print(f"\n--- Batch {offset // BATCH_SIZE + 1}: ayat {offset + 1}-{offset + len(batch)} ---")

        for ayah in batch:
            surah = ayah["surah_number"]
            ayah_num = ayah["ayah_number"]
            print(f"  {surah}:{ayah_num} — ", end="", flush=True)

            try:
                tafsir = supabase_get("tafsir_entries", {
                    "surah_number": f"eq.{surah}",
                    "ayah_number": f"eq.{ayah_num}",
                    "select": "scholar_name,text",
                    "scholar_name": "in.(Ibn Kathir,Al-Qurtubi)",
                })

                if not tafsir:
                    print("skip (no tafsir)")
                    continue

                result = extract_asbab(surah, ayah_num, tafsir)

                if result and result.get("has_sabab"):
                    supabase_post("asbab_nuzul", {
                        "surah_number": surah,
                        "ayah_number_surah": ayah_num,
                        "text_en": result["text"],
                        "source": result.get("source", "Tafsir extraction"),
                    })
                    print(f"✓ extracted ({result.get('source', '?')})")
                    extracted += 1
                elif result:
                    print("— no sabab mentioned")
                    no_sabab += 1
                else:
                    print("✗ parse failed")
                    failed += 1
            except Exception as e:
                print(f"✗ {e}")
                failed += 1

            time.sleep(0.5)

        offset += BATCH_SIZE
        print(f"\nProgress: {offset}/{total} ({extracted} extracted, {no_sabab} no sabab, {failed} failed)")

    print(f"\n{'=' * 60}")
    print(f"DONE: {extracted} extracted, {no_sabab} no sabab, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
