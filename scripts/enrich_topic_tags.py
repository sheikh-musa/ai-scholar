#!/usr/bin/env python3
"""
Enrich topic_tags on all ayat using Claude CLI.

For each ayah, asks Claude: "What practical topics would a Muslim ask about
that this verse addresses?" and updates the topic_tags array.

Usage:
  python3 scripts/enrich_topic_tags.py [--batch-size 50] [--start-from 1]

Requires:
  - claude CLI installed (~/.local/bin/claude)
  - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Load env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")

BATCH_SIZE = int(sys.argv[sys.argv.index("--batch-size") + 1]) if "--batch-size" in sys.argv else 50
START_FROM = int(sys.argv[sys.argv.index("--start-from") + 1]) if "--start-from" in sys.argv else 0


def supabase_get(table, params):
    """GET from Supabase REST API."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def supabase_patch(table, row_id, data):
    """PATCH a row in Supabase."""
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


def get_tags_from_claude(surah, ayah, arabic, english, existing_tags):
    """Ask Claude to generate practical topic tags for an ayah."""
    prompt = f"""Given this Quran verse, generate practical topic tags that a Muslim might search for when this verse is relevant to their question.

Surah {surah}, Ayah {ayah}:
Arabic: {arabic[:200]}
English: {english}

Existing tags: {json.dumps(existing_tags)}

Rules:
- Return ONLY a JSON array of strings, no explanation
- Include both theological concepts AND practical life topics
- Think about what questions a person might ask where this verse would be a relevant answer
- Examples of good practical tags: "fasting exemption", "breastfeeding", "inheritance rules", "marriage", "debt", "patience in hardship", "anger management", "parent rights", "charity", "business ethics"
- Include existing tags if they're good, remove if irrelevant
- Max 12 tags per verse
- Lowercase, use hyphens for multi-word tags only if needed

Return ONLY the JSON array, nothing else."""

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
    # Extract JSON array from response
    try:
        # Try direct parse
        tags = json.loads(output)
        if isinstance(tags, list):
            return tags[:12]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in the text
    import re
    match = re.search(r'\[.*?\]', output, re.DOTALL)
    if match:
        try:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                return [str(t) for t in tags[:12]]
        except json.JSONDecodeError:
            pass

    return None


def main():
    print("=" * 60)
    print("Quran Topic Tag Enrichment")
    print(f"Batch size: {BATCH_SIZE}, Starting from offset: {START_FROM}")
    print("=" * 60)

    # Get total count
    all_ayat = supabase_get("ayat", {
        "select": "id",
        "order": "surah_number,ayah_number",
    })
    total = len(all_ayat)
    print(f"Total ayat in database: {total}")

    offset = START_FROM
    enriched = 0
    failed = 0
    skipped = 0

    while offset < total:
        # Fetch batch
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
            existing = ayah.get("topic_tags") or []
            english = ayah.get("english_translation", "")

            # Skip if already has 8+ quality tags
            if len(existing) >= 8:
                skipped += 1
                continue

            print(f"  {surah}:{ayah_num} — ", end="", flush=True)

            try:
                tags = get_tags_from_claude(
                    surah, ayah_num,
                    ayah.get("arabic_text", ""),
                    english,
                    existing,
                )

                if tags:
                    supabase_patch("ayat", ayah["id"], {"topic_tags": tags})
                    print(f"✓ {len(tags)} tags: {', '.join(tags[:5])}{'...' if len(tags) > 5 else ''}")
                    enriched += 1
                else:
                    print("✗ Claude returned no tags")
                    failed += 1
            except subprocess.TimeoutExpired:
                print("✗ timeout")
                failed += 1
            except Exception as e:
                print(f"✗ {e}")
                failed += 1

            # Rate limit — don't overwhelm Claude
            time.sleep(0.5)

        offset += BATCH_SIZE

        # Progress report
        print(f"\nProgress: {offset}/{total} ({enriched} enriched, {failed} failed, {skipped} skipped)")

    print(f"\n{'=' * 60}")
    print(f"DONE: {enriched} enriched, {failed} failed, {skipped} skipped")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
