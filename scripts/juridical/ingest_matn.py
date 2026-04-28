#!/usr/bin/env python3
"""
Ingest a canonicalized matn file into juridical_texts + ingestion_provenance
per AL-BAYAN-003 (decision id 568).

Flow:
  1. SHA-256 the canonicalized matn file
  2. INSERT ingestion_provenance row (source_url, maintainer, license, SHA, verified_by)
  3. Split matn on baab markers (بَابٌ / فَصْلٌ / مَسْأَلَةٌ / كِتَابٌ)
  4. For each baab segment, INSERT juridical_texts row referencing provenance

DOES NOT embed yet — embedding is a separate workstream gated on
EMBED_PIPELINE_v02 backfill kickoff (which gates on Modal verification +
ENCODER-EVAL completion).

Usage:
  python3 scripts/juridical/ingest_matn.py \\
    --text-name "Safīnat al-Najā" \\
    --author-name "Sālim b. Sumayr al-Ḥaḍramī" \\
    --author-death-hijri 1271 \\
    --author-death-gregorian 1855 \\
    --madhab shafii \\
    --dalil-strength primer_juridical \\
    --source-file data/juridical/safinah_al_najaa/matn.txt \\
    --source-url "https://shamela.ws/book/..." \\
    --source-maintainer "al-Maktaba al-Shamela" \\
    --license "public domain (author d. 1855)" \\
    --verified-by "musa"

After ingestion: SELECT count(*) FROM juridical_texts WHERE text_name = 'Safīnat al-Najā';
should match the number of baab segments printed by this script.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

SUPABASE_URL = (os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
                or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co"))
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Baab markers — same set as canonicalize.py uses for preservation. The split
# fires when any of these patterns are found at a line start (after canonicalize
# normalizes whitespace).
BAAB_SPLIT_PATTERNS = [
    re.compile(r"^\s*(بَابُ?)", re.MULTILINE),
    re.compile(r"^\s*(بابُ?)", re.MULTILINE),
    re.compile(r"^\s*(فَصْلٌ?)", re.MULTILINE),
    re.compile(r"^\s*(فصلٌ?)", re.MULTILINE),
    re.compile(r"^\s*(مَسْأَلَةٌ?)", re.MULTILINE),
    re.compile(r"^\s*(مسألةٌ?)", re.MULTILINE),
    re.compile(r"^\s*(كِتَابُ?)", re.MULTILINE),
    re.compile(r"^\s*(كتابُ?)", re.MULTILINE),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_into_baabs(text: str) -> list[tuple[str, str]]:
    """Returns [(baab_or_section, arabic_text)] in document order."""
    # Find all baab-marker positions across all patterns
    matches = []
    for pat in BAAB_SPLIT_PATTERNS:
        for m in pat.finditer(text):
            matches.append((m.start(), m.group()))
    # Sort by position
    matches.sort(key=lambda x: x[0])

    if not matches:
        # No baab markers — single segment
        title = "(matn — no baab markers detected)"
        return [(title, text.strip())]

    segments = []
    for i, (pos, marker) in enumerate(matches):
        segment_start = pos
        segment_end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        segment = text[segment_start:segment_end].strip()
        # First line of segment is the baab title (until first newline or 80 chars)
        first_newline = segment.find("\n")
        title = segment[:first_newline].strip() if first_newline > 0 else segment[:80].strip()
        segments.append((title, segment))
    return segments


def api_post(path: str, body: dict, prefer: str = "return=representation"):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": prefer},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    if not SUPABASE_KEY:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY not set in .env")

    parser = argparse.ArgumentParser(description="Ingest matn into juridical_texts")
    parser.add_argument("--text-name", required=True)
    parser.add_argument("--author-name", required=True)
    parser.add_argument("--author-death-hijri", type=int)
    parser.add_argument("--author-death-gregorian", type=int)
    parser.add_argument("--madhab", required=True, choices=["shafii", "hanafi", "maliki", "hanbali"])
    parser.add_argument("--dalil-strength", required=True,
                        choices=["primer_juridical", "standard_juridical", "spine_juridical"])
    parser.add_argument("--source-file", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-maintainer", required=True)
    parser.add_argument("--license", required=True, dest="license_declaration")
    parser.add_argument("--verified-by", required=True, dest="verified_by_identity")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source_file.exists():
        sys.exit(f"source file not found: {args.source_file}")

    text = args.source_file.read_text(encoding="utf-8")
    file_sha = sha256_file(args.source_file)

    print(f"=== ingest_matn ===")
    print(f"  text_name:        {args.text_name}")
    print(f"  author:           {args.author_name} (d. {args.author_death_hijri} AH / {args.author_death_gregorian} CE)")
    print(f"  madhab:           {args.madhab}")
    print(f"  dalil_strength:   {args.dalil_strength}")
    print(f"  source_file:      {args.source_file}  ({len(text)} chars)")
    print(f"  source_file_sha:  {file_sha[:12]}…")
    print(f"  source_url:       {args.source_url}")
    print(f"  license:          {args.license_declaration}")
    print(f"  verified_by:      {args.verified_by_identity}")
    print()

    segments = split_into_baabs(text)
    print(f"split into {len(segments)} baab segments:")
    for i, (title, body) in enumerate(segments[:5], 1):
        print(f"  {i}. {title[:70]}…  ({len(body)} chars)")
    if len(segments) > 5:
        print(f"  … {len(segments) - 5} more")
    print()

    if args.dry_run:
        print("dry-run — exiting without ingesting")
        return 0

    # 1. INSERT ingestion_provenance
    print("inserting ingestion_provenance row…")
    provenance = api_post("ingestion_provenance", {
        "source_url": args.source_url,
        "source_maintainer": args.source_maintainer,
        "license_declaration": args.license_declaration,
        "source_file_sha256": file_sha,
        "verified_by_identity": args.verified_by_identity,
        "notes": args.notes,
    })
    provenance_id = provenance[0]["id"]
    print(f"  provenance_id: {provenance_id[:12]}…")

    # 2. INSERT juridical_texts rows in batches
    print(f"inserting {len(segments)} juridical_texts rows…")
    rows_to_insert = []
    for i, (title, body) in enumerate(segments):
        normalized = unicodedata.normalize("NFC", body)
        rows_to_insert.append({
            "text_name": args.text_name,
            "author_name": args.author_name,
            "author_death_hijri": args.author_death_hijri,
            "author_death_gregorian": args.author_death_gregorian,
            "madhab": args.madhab,
            "dalil_strength": args.dalil_strength,
            "baab_or_section": title[:200],
            "baab_order": i + 1,
            "arabic_text": normalized,
            "arabic_text_sha256": sha256_text(normalized),
            "ingestion_provenance_id": provenance_id,
        })

    # Batch insert in chunks of 100
    inserted = 0
    for chunk_start in range(0, len(rows_to_insert), 100):
        chunk = rows_to_insert[chunk_start:chunk_start + 100]
        api_post("juridical_texts", chunk, prefer="return=minimal")
        inserted += len(chunk)
        print(f"  inserted {inserted}/{len(rows_to_insert)}")

    print(f"\n=== done ===")
    print(f"  text:        {args.text_name}")
    print(f"  segments:    {inserted}")
    print(f"  provenance:  {provenance_id}")
    print(f"\nverify with:")
    print(f"  SELECT count(*) FROM juridical_texts WHERE text_name = '{args.text_name}';")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
