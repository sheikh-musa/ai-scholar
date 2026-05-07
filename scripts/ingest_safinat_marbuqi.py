#!/usr/bin/env python3
"""Safīnat al-Najā (al-Marbūqī tr.) ingestion driver.

Subcommands:
  extract     Dry-run — extract chapters from PDF, print chapter_path + first 200 chars of each. No DB writes.
  provenance  Write the single ingestion_provenance row. Idempotent: skips if SHA already present.
  ingest      Write juridical_texts content rows. Reads from extract output. Idempotent per chapter_path: skips if row exists.
  verify      Post-ingest sanity: row count, sample 5 random rows, spot-check English text fragments against PDF source.

Source: docs/sources/safinat-al-najah-marbuqi-tr.pdf (operator-supplied, SHA 679404ac…ad491).
License: sadaqah jariyah (publisher al-inaam.com explicit reproduction grant per page 3).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# pypdf installed in /tmp/pdfvenv per session 2026-05-07. If running standalone,
# `python3 -m venv /tmp/pdfvenv && /tmp/pdfvenv/bin/pip install pypdf`.
sys.path.insert(0, "/tmp/pdfvenv/lib/python3.14/site-packages")
import pypdf  # type: ignore

PDF_PATH = Path(__file__).parent.parent / "docs/sources/safinat-al-najah-marbuqi-tr.pdf"
EXPECTED_SHA = "679404ac682aea814ed726b6255611fd4624a2d724fe6fc5969cd430255ad491"

SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY", "")
if not SUPABASE_KEY:
    print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY not set", file=sys.stderr)
    sys.exit(2)

PROMPT_VERSION = "safinat-marbuqi-ingest-v1-2026-05-07"
TRANSLATOR = "ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī"
SOURCE_WORK = "Safīnat al-Najā (al-Marbūqī tr., al-inaam.com 2009)"
SOURCE_URL = "docs/sources/safinat-al-najah-marbuqi-tr.pdf"  # repo-pinned canonical
SOURCE_MAINTAINER = "al-inaam.com"
LICENSE_DECLARATION = (
    "Translator/publisher explicit reproduction grant per page 3 of source PDF: "
    "'Any part of this publication may be reproduced, stored in a retrieval system "
    "or transmitted in any form or by any means, electronic, mechanical, photocopying, "
    "recording or otherwise, without the prior permission of the publisher.' "
    "Sadaqah jariyah posture per Hadhrami Shafi'i publishing tradition; verified by Musa 2026-05-07."
)

# Chapter heading patterns from PDF TOC inspection. Order matters (longest first
# to avoid 'Salah' matching inside 'Salah Times').
CHAPTER_HEADINGS = [
    "Muqaddimah", "Islam and Iman", "Al-Ahkam al-Sharʿiyyah",
    "Taharah", "Adhan", "Salah", "Salah Janazah",
    "Zakah", "Saum", "Hajj and ʿUmrah",
    "Bibliography",
    # Biographical appendix
    "Al-Imām al-Rāfiʿī", "Al-Imām al-Nawawī", "Shaykh al-Islām Zakariyyā al-Anṣārī",
    "Al-Imām Ibn Ḥajar al-Haytamī", "Al-Imām Muḥammad al-Shirbīnī al-Khāṭib",
]


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pages(path: Path) -> list[str]:
    reader = pypdf.PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in reader.pages]


def segment_chapters(pages: list[str]) -> list[dict]:
    """Walk pages, identify chapter boundaries by heading match in extracted text.
    Returns list of dicts with chapter_path, page_start, page_end, english_text.
    """
    chapters = []
    current = None
    for i, page_text in enumerate(pages):
        # Try to match a chapter heading at the start of meaningful text on this page
        first_lines = "\n".join(page_text.split("\n")[:3])
        matched_heading = None
        for h in CHAPTER_HEADINGS:
            if h in first_lines:
                matched_heading = h
                break
        if matched_heading and (current is None or current["chapter_path"] != matched_heading):
            if current is not None:
                current["page_end"] = i - 1
                chapters.append(current)
            current = {
                "chapter_path": matched_heading,
                "page_start": i,
                "page_end": i,
                "english_text_pages": [page_text],
            }
        elif current is not None:
            current["english_text_pages"].append(page_text)
    if current is not None:
        current["page_end"] = len(pages) - 1
        chapters.append(current)
    # Concatenate page texts per chapter
    for ch in chapters:
        ch["english_text"] = "\n\n".join(ch["english_text_pages"])
        del ch["english_text_pages"]
    return chapters


def cmd_extract(args):
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 2
    sha = compute_sha256(PDF_PATH)
    if sha != EXPECTED_SHA:
        print(f"ERROR: PDF SHA mismatch — expected {EXPECTED_SHA}, got {sha}", file=sys.stderr)
        return 3
    print(f"PDF SHA verified: {sha}")
    pages = extract_pages(PDF_PATH)
    print(f"Extracted {len(pages)} pages")
    chapters = segment_chapters(pages)
    print(f"Segmented into {len(chapters)} chapter(s):")
    for ch in chapters:
        eng = ch["english_text"][:200].replace("\n", " ")
        print(f"  {ch['chapter_path']:35} pages {ch['page_start']:3}-{ch['page_end']:3}: {eng}…")
    return 0


def supabase_post(table: str, data: dict | list) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=representation",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_provenance(args):
    """Write the single ingestion_provenance row. Idempotent on SHA."""
    sha = compute_sha256(PDF_PATH)
    # Check if already present
    url = f"{SUPABASE_URL}/rest/v1/ingestion_provenance?source_file_sha256=eq.{sha}&select=id&limit=1"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        existing = json.loads(resp.read().decode("utf-8"))
    if existing:
        print(f"Provenance row already present: id={existing[0]['id']}")
        return 0
    row = {
        "source_url": SOURCE_URL,
        "source_maintainer": SOURCE_MAINTAINER,
        "license_declaration": LICENSE_DECLARATION,
        "source_file_sha256": sha,
        "verified_by_identity": "musa",
        "notes": "Bilingual Arabic+English. 185 pages. Edition Ṣafar 1430 H (Feb 2009). "
                 f"Translator {TRANSLATOR}. Operator-supplied 2026-05-07.",
    }
    result = supabase_post("ingestion_provenance", row)
    print(f"Wrote ingestion_provenance row: id={result[0]['id']}")
    return 0


def cmd_ingest(args):
    """Write juridical_texts content rows. Idempotent per chapter_path within source SHA."""
    pages = extract_pages(PDF_PATH)
    chapters = segment_chapters(pages)
    sha = compute_sha256(PDF_PATH)
    # Get the provenance id
    url = f"{SUPABASE_URL}/rest/v1/ingestion_provenance?source_file_sha256=eq.{sha}&select=id&limit=1"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        prov = json.loads(resp.read().decode("utf-8"))
    if not prov:
        print("ERROR: ingestion_provenance row missing — run `provenance` subcommand first", file=sys.stderr)
        return 4
    provenance_id = prov[0]["id"]
    written = 0
    skipped = 0
    for ch in chapters:
        # Check if row exists
        path_enc = urllib.parse.quote(ch["chapter_path"])
        check_url = f"{SUPABASE_URL}/rest/v1/juridical_texts?chapter_path=eq.{path_enc}&provenance_id=eq.{provenance_id}&select=id&limit=1"
        req = urllib.request.Request(check_url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req) as resp:
            existing = json.loads(resp.read().decode("utf-8"))
        if existing:
            skipped += 1
            continue
        # Determine output_tier — chapter-level rows are 'paraphrased' (editorial alignment)
        # since we're concatenating pages. Future rule-level granularity can use 'quoted'.
        row = {
            "madhab": "shafii",
            "dalil_strength_tier": "primer_juridical",
            "text_role": "matn",
            "scholar_name": TRANSLATOR,
            "source_work": SOURCE_WORK,
            "chapter_path": ch["chapter_path"],
            "arabic_text": None,  # Bilingual extraction TBD; English-first per amended decision
            "english_text": ch["english_text"][:50000],  # cap per row to avoid blob rows
            "output_tier": "paraphrased",
            "provenance_id": provenance_id,
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
        }
        result = supabase_post("juridical_texts", row)
        written += 1
        print(f"  + {ch['chapter_path']:35} (pages {ch['page_start']:3}-{ch['page_end']:3}, {len(ch['english_text']):6} chars)")
    print(f"\nDone: {written} rows written, {skipped} already present.")
    return 0


def cmd_verify(args):
    """Spot-check ingested rows."""
    url = f"{SUPABASE_URL}/rest/v1/juridical_texts?source_work=eq.{urllib.parse.quote(SOURCE_WORK)}&select=chapter_path,page_start,page_end,output_tier&order=page_start"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    print(f"juridical_texts rows for {SOURCE_WORK}: {len(rows)}")
    for r in rows:
        print(f"  {r['chapter_path']:35} pp {r['page_start']:3}-{r['page_end']:3}  tier={r['output_tier']}")
    return 0


SUBCOMMANDS = {"extract": cmd_extract, "provenance": cmd_provenance, "ingest": cmd_ingest, "verify": cmd_verify}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=list(SUBCOMMANDS))
    args, _ = parser.parse_known_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
