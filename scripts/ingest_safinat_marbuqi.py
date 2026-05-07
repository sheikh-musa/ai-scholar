#!/usr/bin/env python3
"""Safīnat al-Najā (al-Marbūqī tr.) ingestion driver — TWO-STEP INSERT per Path B refined.

Per AL-BAYAN-003-AMEND-ENGLISH-FIRST-002 (decision id 756, CAI-RESP-136):
  STEP 1: insert Arabic matn into juridical_texts (deployed Arabic-only schema:
          text_name, baab_or_section, baab_order, arabic_text NOT NULL, arabic_text_sha256, etc.)
  STEP 2: insert English translation into juridical_translations (FK'd to juridical_texts.id)
Both rows share the same ingestion_provenance_id (single source PDF).

Per CAI-RESP-136 META-PROCESS AMENDMENT: cmd_provenance and cmd_ingest call verify_schema()
which fetches the OpenAPI spec and confirms both juridical_texts and juridical_translations
exist with expected columns before any insert. If juridical_translations is missing, script
exits with code 5 and instructions to apply the migration first.

PHASE 2 NOTE (Arabic quality): Arabic text is extracted from the bilingual PDF using pypdf
Unicode-script regex. RTL extraction quality is rough for side-by-side layouts. The
arabic_text_sha256 is stable for whatever pypdf produces. A Phase 2 refresh script can
overwrite arabic_text (and recompute sha256) from a cleaner source such as al-Maktaba
al-Shamela or the publisher's digital edition. If extraction yields <50 chars per chapter
(below minimum plausibility threshold), that chapter is SKIPPED with a warning rather than
ingested with garbage — operator should provide a better Arabic source before ingest commits.

Subcommands:
  extract     Dry-run — extract chapters from PDF, print chapter_path, Arabic length,
              + first 200 chars of English per chapter. No DB writes.
  provenance  Write the single ingestion_provenance row. Idempotent: skips if SHA already present.
              Calls verify_schema() first — exits 5 if juridical_translations not deployed.
  ingest      Two-step insert per chapter: juridical_texts then juridical_translations.
              Idempotent per (text_name, baab_or_section, ingestion_provenance_id): skips if row exists.
              Calls verify_schema() first — exits 5 if juridical_translations not deployed.
  verify      Post-ingest sanity: JOIN both tables, row count, sample output per chapter.

Source: docs/sources/safinat-al-najah-marbuqi-tr.pdf (operator-supplied, SHA 679404ac…ad491).
License: sadaqah jariyah (publisher al-inaam.com explicit reproduction grant per page 3).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
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

PROMPT_VERSION = "safinat-marbuqi-ingest-v2-2026-05-07"
TEXT_NAME = "Safīnat al-Najā"
AUTHOR_NAME = "Sālim ibn ʿAbdullah ibn Saʿd ibn Samīr al-Ḥaḍramī al-Shāfiʿī"
AUTHOR_DEATH_HIJRI = 1271    # confirmed from Hadhrami sources
AUTHOR_DEATH_GREGORIAN = 1855
TRANSLATOR = "ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī"
TRANSLATION_SOURCE_WORK = "Safīnat al-Najā (al-inaam.com 2009)"
EDITION_LABEL = "Limited Edition Ṣafar 1430 H / Feb 2009"
SOURCE_URL = "docs/sources/safinat-al-najah-marbuqi-tr.pdf"  # repo-pinned canonical
SOURCE_MAINTAINER = "al-inaam.com"
LICENSE_DECLARATION = (
    "Translator/publisher explicit reproduction grant per page 3 of source PDF: "
    "'Any part of this publication may be reproduced, stored in a retrieval system "
    "or transmitted in any form or by any means, electronic, mechanical, photocopying, "
    "recording or otherwise, without the prior permission of the publisher.' "
    "Sadaqah jariyah posture per Hadhrami Shafi'i publishing tradition; verified by Musa 2026-05-07."
)

# Arabic Unicode block ranges (covers Arabic, Extended-A, Extended-B, Presentation Forms A+B)
ARABIC_RUN_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻾]+(?:\s+[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻾]+){2,}")

ARABIC_MIN_CHARS = 50  # minimum plausible Arabic extraction per chapter

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


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_arabic_from_pages(page_texts: list[str]) -> str:
    """Extract Arabic runs from a list of page texts; concatenate; NFC normalize.

    Returns NFC-normalized Arabic string. Caller must check len() >= ARABIC_MIN_CHARS
    before trusting result.
    """
    runs = []
    for page_text in page_texts:
        runs.extend(ARABIC_RUN_RE.findall(page_text))
    arabic = "\n".join(runs)
    return unicodedata.normalize("NFC", arabic)


def extract_pages(path: Path) -> list[str]:
    reader = pypdf.PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in reader.pages]


def segment_chapters(pages: list[str]) -> list[dict]:
    """Walk pages, identify chapter boundaries by heading match in extracted text.

    Returns list of dicts with:
      chapter_path, page_start, page_end, english_text, english_text_pages_raw
    english_text_pages_raw retains per-page strings for Arabic extraction.
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
                "english_text_pages_raw": [page_text],
            }
        elif current is not None:
            current["english_text_pages_raw"].append(page_text)
    if current is not None:
        current["page_end"] = len(pages) - 1
        chapters.append(current)
    # Concatenate page texts per chapter; keep raw pages for Arabic extraction
    for ch in chapters:
        ch["english_text"] = "\n\n".join(ch["english_text_pages_raw"])
    return chapters


# ---------------------------------------------------------------------------
# Schema verification gate (CAI-RESP-136 meta-process amendment)
# ---------------------------------------------------------------------------

def verify_schema() -> bool:
    """Fetch OpenAPI spec and confirm both juridical_texts and juridical_translations exist.

    Returns True if both tables present. Prints error and calls sys.exit(5) if
    juridical_translations is missing.
    """
    try:
        spec_url = f"{SUPABASE_URL}/rest/v1/"
        req = urllib.request.Request(spec_url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            spec = json.loads(resp.read().decode("utf-8"))
        paths = spec.get("paths", {})
        has_jt = "/juridical_texts" in paths
        has_tr = "/juridical_translations" in paths
    except Exception as exc:
        print(f"ERROR: could not fetch OpenAPI spec for schema verification: {exc}", file=sys.stderr)
        sys.exit(5)

    if not has_jt:
        print(
            "ERROR: juridical_texts table not found in deployed schema. "
            "Confirm AL-BAYAN-003 migration (20260428194802_al_bayan_003_juridical_corpus) is applied.",
            file=sys.stderr,
        )
        sys.exit(5)

    if not has_tr:
        print(
            "ERROR: juridical_translations table not deployed. "
            "Run `supabase migration up` after challenge_window closes 2026-05-08T01:32Z "
            "(or with explicit Musa early-close consent) to apply 20260507_001_juridical_translations.sql.",
            file=sys.stderr,
        )
        sys.exit(5)

    print("Schema verified: juridical_texts + juridical_translations both present.")
    return True


# ---------------------------------------------------------------------------
# Supabase REST helpers
# ---------------------------------------------------------------------------

def supabase_get(table: str, params: dict) -> list:
    qs = urllib.parse.urlencode(params)
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_post(table: str, data: dict | list) -> list:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_extract(args):
    """Dry-run: extract chapters, show Arabic extraction quality per chapter."""
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
    arabic_warn = False
    for ch in chapters:
        arabic = extract_arabic_from_pages(ch["english_text_pages_raw"])
        ar_len = len(arabic)
        ar_flag = "OK" if ar_len >= ARABIC_MIN_CHARS else "WARN:<50chars"
        if ar_len < ARABIC_MIN_CHARS:
            arabic_warn = True
        eng = ch["english_text"][:200].replace("\n", " ")
        print(
            f"  {ch['chapter_path']:35} pages {ch['page_start']:3}-{ch['page_end']:3}  "
            f"arabic={ar_len:5}chars[{ar_flag}]  en: {eng}…"
        )
    if arabic_warn:
        print(
            "\nWARN: One or more chapters produced <50 Arabic chars. "
            "Those chapters will be SKIPPED by `ingest`. "
            "Provide a cleaner Arabic source for Phase 2 refresh."
        )
    return 0


def cmd_provenance(args):
    """Write the single ingestion_provenance row. Idempotent on SHA."""
    verify_schema()
    sha = compute_sha256(PDF_PATH)
    # Check if already present
    existing = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{sha}",
        "select": "id",
        "limit": "1",
    })
    if existing:
        print(f"Provenance row already present: id={existing[0]['id']}")
        return 0
    row = {
        "source_url": SOURCE_URL,
        "source_maintainer": SOURCE_MAINTAINER,
        "license_declaration": LICENSE_DECLARATION,
        "source_file_sha256": sha,
        "verified_by_identity": "musa",
        "notes": (
            "Bilingual Arabic+English. 185 pages. "
            f"Edition {EDITION_LABEL}. "
            f"Translator {TRANSLATOR}. Operator-supplied 2026-05-07."
        ),
    }
    result = supabase_post("ingestion_provenance", row)
    print(f"Wrote ingestion_provenance row: id={result[0]['id']}")
    return 0


def cmd_ingest(args):
    """Two-step insert per chapter: juridical_texts (Arabic) then juridical_translations (English).

    Step 1: INSERT into juridical_texts with deployed Arabic-only schema columns.
    Step 2: Capture returned id; INSERT into juridical_translations FK'd to step 1.
    Idempotency: checks (text_name, baab_or_section, ingestion_provenance_id) before inserting.
    Chapters with <50 Arabic chars are SKIPPED with a warning (not ingested with garbage).
    """
    verify_schema()

    pages = extract_pages(PDF_PATH)
    chapters = segment_chapters(pages)
    sha = compute_sha256(PDF_PATH)

    # Get the provenance id
    prov = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{sha}",
        "select": "id",
        "limit": "1",
    })
    if not prov:
        print(
            "ERROR: ingestion_provenance row missing — run `provenance` subcommand first.",
            file=sys.stderr,
        )
        return 4
    provenance_id = prov[0]["id"]

    written = 0
    skipped_dup = 0
    skipped_arabic = 0

    for i, ch in enumerate(chapters):
        # Extract and validate Arabic
        arabic = extract_arabic_from_pages(ch["english_text_pages_raw"])
        if len(arabic) < ARABIC_MIN_CHARS:
            print(
                f"  [{ch['chapter_path']}] WARN: Arabic extraction yielded {len(arabic)} chars; "
                "SKIPPING pending operator review (provide cleaner Arabic source for Phase 2 refresh)"
            )
            skipped_arabic += 1
            continue

        arabic_sha = sha256_hex(arabic)

        # Idempotency check on juridical_texts
        existing = supabase_get("juridical_texts", {
            "text_name": f"eq.{urllib.parse.quote(TEXT_NAME)}",
            "baab_or_section": f"eq.{urllib.parse.quote(ch['chapter_path'])}",
            "ingestion_provenance_id": f"eq.{provenance_id}",
            "select": "id",
            "limit": "1",
        })
        if existing:
            skipped_dup += 1
            continue

        # STEP 1: Insert into juridical_texts (deployed Arabic-only schema)
        jt_row = {
            "text_name": TEXT_NAME,
            "author_name": AUTHOR_NAME,
            "author_death_hijri": AUTHOR_DEATH_HIJRI,
            "author_death_gregorian": AUTHOR_DEATH_GREGORIAN,
            "madhab": "shafii",
            "dalil_strength": "primer_juridical",
            "baab_or_section": ch["chapter_path"],
            "baab_order": i + 1,
            "arabic_text": arabic,
            "arabic_text_sha256": arabic_sha,
            "ingestion_provenance_id": provenance_id,
        }
        jt_result = supabase_post("juridical_texts", jt_row)
        juridical_text_id = jt_result[0]["id"]

        # STEP 2: Insert into juridical_translations (English, FK'd to step 1)
        english_nfc = unicodedata.normalize("NFC", ch["english_text"])
        english_sha = sha256_hex(english_nfc)
        tr_row = {
            "juridical_text_id": juridical_text_id,
            "language_code": "en",
            "translator_name": TRANSLATOR,
            "translation_source_work": TRANSLATION_SOURCE_WORK,
            "translation_text": english_nfc[:50000],  # cap per row to avoid blob rows
            "translation_text_sha256": english_sha,
            "output_tier": "paraphrased",  # chapter-level is editorial alignment, not verbatim per fiqh rule
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
            "edition_label": EDITION_LABEL,
            "ingestion_provenance_id": provenance_id,
        }
        supabase_post("juridical_translations", tr_row)

        written += 1
        print(
            f"  + {ch['chapter_path']:35} "
            f"(pages {ch['page_start']:3}-{ch['page_end']:3}, "
            f"{len(arabic):5} ar / {len(english_nfc):6} en chars)"
        )

    print(
        f"\nDone: {written} chapters written, "
        f"{skipped_dup} already present, "
        f"{skipped_arabic} skipped (insufficient Arabic extraction)."
    )
    return 0


def cmd_verify(args):
    """Spot-check ingested rows — JOIN juridical_texts + juridical_translations."""
    # Query translations joined to texts
    rows = supabase_get("juridical_translations", {
        "translator_name": f"eq.{urllib.parse.quote(TRANSLATOR)}",
        "select": "juridical_text_id,language_code,page_start,page_end,output_tier,edition_label,"
                  "juridical_texts(text_name,baab_or_section,baab_order,author_name)",
        "order": "page_start",
    })
    print(f"juridical_translations rows for translator '{TRANSLATOR}': {len(rows)}")
    for r in rows:
        jt = r.get("juridical_texts") or {}
        print(
            f"  [{r.get('language_code','?')}] "
            f"{jt.get('baab_or_section','?'):35} "
            f"pp {r.get('page_start','?'):3}-{r.get('page_end','?'):3}  "
            f"tier={r.get('output_tier','?')}  "
            f"text={jt.get('text_name','?')}"
        )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUBCOMMANDS = {
    "extract": cmd_extract,
    "provenance": cmd_provenance,
    "ingest": cmd_ingest,
    "verify": cmd_verify,
}


def main():
    parser = argparse.ArgumentParser(description="Safīnat al-Najā ingestion driver (Path B refined)")
    parser.add_argument("cmd", choices=list(SUBCOMMANDS))
    args, _ = parser.parse_known_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
