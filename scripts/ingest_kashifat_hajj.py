#!/usr/bin/env python3
"""Kashifat al-Sajā Hajj-baab ingestion driver — closes the Hajj gap.

Per session 2026-05-20 decision: ingest the Hajj baab from Kashifat al-Sajā
(Muḥammad Nawawī ibn ʿUmar al-Jāwī al-Bantanī al-Shāfiʿī, d. 1316 H / 1898 CE)
under the existing `text_name="Safīnat al-Najā"` umbrella, mirroring the
Siyam pattern (same author, separate baab).

The original Safīnat al-Najā by Sālim ibn ʿAbdullah ibn Samīr al-Ḥaḍramī
(d. 1271 H) stops before Hajj; Nawawī al-Jāwī's Kashifat al-Sajā is the
canonical Hadhrami-Shafiʿi commentary that closes both Siyam (already
ingested) and Hajj. Keeping it under one `text_name` matches operator
expectation that "everything in Safīnat" lives together for retrieval.

Schema rows produced:
  juridical_texts:
    text_name        = "Safīnat al-Najā"
    baab_or_section  = "Hajj"
    baab_order       = 6
    author_name      = "Muḥammad Nawawī ibn ʿUmar al-Jāwī al-Bantanī al-Shāfiʿī"
    madhab           = "shafii"
    dalil_strength   = "primer_juridical"

  juridical_translations:
    language_code            = "en"
    translator_name          = $TRANSLATOR_NAME env (operator-supplied)
    translation_source_work  = "Kashifat al-Sajā Hajj baab — <translator/edition>"
    output_tier              = "paraphrased"

Source files (operator drops these before running):
  docs/sources/kashifat-al-saja-hajj-arabic.txt   ← UTF-8 plain text
  docs/sources/kashifat-al-saja-hajj-english.txt  ← UTF-8 plain text (preferred)
    OR
  docs/sources/kashifat-al-saja-hajj-english.pdf  ← PDF (script extracts)

Subcommands:
  extract     Dry-run — load both files, print SHA + first 500 chars + section
              count detected via (فصل) markers in Arabic. No DB writes.
  provenance  Write BOTH ingestion_provenance rows (Arabic + English).
              Idempotent on SHA-256.
  ingest      Two-step insert: juridical_texts (Arabic) then
              juridical_translations (English). Idempotent on
              (text_name, baab_or_section, ingestion_provenance_id).
  verify      POST-INGEST: JOIN both tables, print row + char counts.

Environment:
  ORCHESTRATOR_SUPABASE_SERVICE_KEY   required (RLS bypass for insert)
  TRANSLATOR_NAME                     operator-supplied (e.g. "Mokrane Guezzou")
  TRANSLATION_EDITION_LABEL           operator-supplied (e.g. "ITS 2010")
  TRANSLATION_SOURCE_WORK             operator-supplied free-text label

Exit codes:
  0  success
  2  source file missing
  3  source SHA mismatch (when EXPECTED_AR_SHA / EXPECTED_EN_SHA are set)
  4  ingestion_provenance row missing (run provenance first)
  5  deployed schema missing required table (check migrations)
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

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
ARABIC_TXT_PATH = REPO_ROOT / "docs/sources/kashifat-al-saja-hajj-arabic.txt"
ENGLISH_TXT_PATH = REPO_ROOT / "docs/sources/kashifat-al-saja-hajj-english.txt"
ENGLISH_PDF_PATH = REPO_ROOT / "docs/sources/kashifat-al-saja-hajj-english.pdf"

SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _require_key():
    if not SUPABASE_KEY:
        print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY (or SUPABASE_SERVICE_ROLE_KEY) not set", file=sys.stderr)
        sys.exit(2)

TEXT_NAME = "Safīnat al-Najā"
BAAB_NAME = "Hajj"
BAAB_ORDER = 6
AUTHOR_NAME = "Muḥammad Nawawī ibn ʿUmar al-Jāwī al-Bantanī al-Shāfiʿī"
AUTHOR_DEATH_HIJRI = 1316
AUTHOR_DEATH_GREGORIAN = 1898
MADHAB = "shafii"
DALIL_STRENGTH = "primer_juridical"

TRANSLATOR_NAME = os.environ.get("TRANSLATOR_NAME", "unknown — set TRANSLATOR_NAME env")
TRANSLATION_SOURCE_WORK = os.environ.get(
    "TRANSLATION_SOURCE_WORK",
    f"Kashifat al-Sajā Hajj baab (tr. {TRANSLATOR_NAME})",
)
EDITION_LABEL = os.environ.get("TRANSLATION_EDITION_LABEL", "unknown — set TRANSLATION_EDITION_LABEL")

EXPECTED_AR_SHA = os.environ.get("EXPECTED_AR_SHA", "").strip().lower() or None
EXPECTED_EN_SHA = os.environ.get("EXPECTED_EN_SHA", "").strip().lower() or None


# ---------------------------------------------------------------------------
# Hash + I/O helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_arabic_text() -> str:
    raw = ARABIC_TXT_PATH.read_text(encoding="utf-8")
    return unicodedata.normalize("NFC", raw)


def load_english_text() -> str:
    """Prefer .txt; fall back to PDF extraction if only PDF present."""
    if ENGLISH_TXT_PATH.exists():
        return ENGLISH_TXT_PATH.read_text(encoding="utf-8")
    if ENGLISH_PDF_PATH.exists():
        try:
            sys.path.insert(0, "/tmp/pdfvenv/lib/python3.14/site-packages")
            import pypdf  # type: ignore
        except ImportError:
            print(
                "ERROR: pypdf not available. Either install it "
                "(python3 -m venv /tmp/pdfvenv && /tmp/pdfvenv/bin/pip install pypdf), "
                "or convert the PDF to .txt and place at "
                f"{ENGLISH_TXT_PATH}",
                file=sys.stderr,
            )
            sys.exit(2)
        reader = pypdf.PdfReader(str(ENGLISH_PDF_PATH))
        chunks = []
        for i, page in enumerate(reader.pages):
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    raise FileNotFoundError(
        f"Neither {ENGLISH_TXT_PATH} nor {ENGLISH_PDF_PATH} exists"
    )


def split_arabic_fasls(arabic_text: str) -> list:
    """Split on (فصل) markers, the same convention as Safīnat al-Najā."""
    parts = re.split(r"\(\s*فصل\s*\)", arabic_text)
    return [unicodedata.normalize("NFC", p.strip()) for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Schema verification
# ---------------------------------------------------------------------------

def verify_schema() -> bool:
    """Fetch OpenAPI spec; confirm juridical_texts + juridical_translations + ingestion_provenance."""
    _require_key()
    try:
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            spec = json.loads(resp.read().decode("utf-8"))
        paths = spec.get("paths", {})
    except Exception as exc:
        print(f"ERROR: schema fetch failed: {exc}", file=sys.stderr)
        sys.exit(5)

    for tbl in ("juridical_texts", "juridical_translations", "ingestion_provenance"):
        if f"/{tbl}" not in paths:
            print(f"ERROR: {tbl} not in deployed schema; confirm AL-BAYAN-003 migration applied", file=sys.stderr)
            sys.exit(5)
    print("Schema verified: juridical_texts + juridical_translations + ingestion_provenance present.")
    return True


# ---------------------------------------------------------------------------
# Supabase REST helpers
# ---------------------------------------------------------------------------

def supabase_get(table: str, params: dict) -> list:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}?{qs}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_post(table: str, data: dict) -> list:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _check_files(check_sha: bool = False) -> tuple:
    """Verify both source files exist; optionally verify SHA against env."""
    if not ARABIC_TXT_PATH.exists():
        print(f"ERROR: {ARABIC_TXT_PATH} not found", file=sys.stderr)
        sys.exit(2)
    if not (ENGLISH_TXT_PATH.exists() or ENGLISH_PDF_PATH.exists()):
        print(
            f"ERROR: neither {ENGLISH_TXT_PATH} nor {ENGLISH_PDF_PATH} found",
            file=sys.stderr,
        )
        sys.exit(2)
    ar_sha = compute_sha256(ARABIC_TXT_PATH)
    en_path = ENGLISH_TXT_PATH if ENGLISH_TXT_PATH.exists() else ENGLISH_PDF_PATH
    en_sha = compute_sha256(en_path)
    if check_sha:
        if EXPECTED_AR_SHA and ar_sha != EXPECTED_AR_SHA:
            print(f"ERROR: Arabic SHA mismatch — expected {EXPECTED_AR_SHA}, got {ar_sha}", file=sys.stderr)
            sys.exit(3)
        if EXPECTED_EN_SHA and en_sha != EXPECTED_EN_SHA:
            print(f"ERROR: English SHA mismatch — expected {EXPECTED_EN_SHA}, got {en_sha}", file=sys.stderr)
            sys.exit(3)
    return ar_sha, en_sha, en_path


def cmd_extract(_args):
    """Dry-run: load both files, print summary."""
    ar_sha, en_sha, en_path = _check_files(check_sha=False)
    arabic = load_arabic_text()
    fasls = split_arabic_fasls(arabic)
    english = load_english_text()

    print(f"\n=== Arabic source ({ARABIC_TXT_PATH.name}) ===")
    print(f"  SHA-256: {ar_sha}")
    print(f"  length: {len(arabic)} chars (NFC-normalized)")
    print(f"  (فصل) markers detected: {len(fasls)}")
    print(f"  first 400 chars:\n  {arabic[:400]!r}")
    if fasls:
        print(f"\n  first fasl preview ({len(fasls[0])}c):\n  {fasls[0][:300]!r}")

    print(f"\n=== English source ({en_path.name}) ===")
    print(f"  SHA-256: {en_sha}")
    print(f"  length: {len(english)} chars")
    print(f"  first 400 chars:\n  {english[:400]!r}")

    print("\n=== Lock these SHAs (set as env vars on subsequent runs) ===")
    print(f"  export EXPECTED_AR_SHA={ar_sha}")
    print(f"  export EXPECTED_EN_SHA={en_sha}")
    print("\nNext: review the source previews above, then run `provenance` and `ingest`.")
    return 0


def cmd_provenance(_args):
    """Write 2 ingestion_provenance rows (Arabic + English) — idempotent on SHA."""
    verify_schema()
    ar_sha, en_sha, en_path = _check_files(check_sha=True)

    def write_provenance(label: str, sha: str, source_file: Path, source_url: str,
                         maintainer: str, license_text: str, lang_note: str) -> str:
        existing = supabase_get("ingestion_provenance", {
            "source_file_sha256": f"eq.{sha}", "select": "id", "limit": "1",
        })
        if existing:
            print(f"  {label} provenance present: id={existing[0]['id']}")
            return existing[0]["id"]
        row = {
            "source_url": source_url,
            "source_maintainer": maintainer,
            "license_declaration": license_text,
            "source_file_sha256": sha,
            "verified_by_identity": "cc-scholar (operator-directed)",
            "notes": (
                f"Kashifat al-Sajā Hajj baab ({lang_note}) — Hadhrami Shafiʿi commentary on "
                f"Safīnat al-Najā. Author d. 1316 H / 1898 CE. Closes the Hajj gap deferred "
                f"at id 699 amendment 4. Source file: {source_file.relative_to(REPO_ROOT)}."
            ),
        }
        result = supabase_post("ingestion_provenance", row)
        print(f"  {label} provenance written: id={result[0]['id']}")
        return result[0]["id"]

    ar_id = write_provenance(
        "Arabic", ar_sha, ARABIC_TXT_PATH,
        source_url=os.environ.get("ARABIC_SOURCE_URL", f"docs/sources/{ARABIC_TXT_PATH.name}"),
        maintainer=os.environ.get("ARABIC_SOURCE_MAINTAINER", "operator-sourced (Shamela / al-Maktaba al-Shamela or equivalent)"),
        license_text="public domain (author Nawawi al-Jawi d. 1316 H / 1898 CE); inherited Hadhrami/Shafiʿi sadaqah-jariyah norm",
        lang_note="Arabic",
    )
    en_id = write_provenance(
        "English", en_sha, en_path,
        source_url=os.environ.get("ENGLISH_SOURCE_URL", f"docs/sources/{en_path.name}"),
        maintainer=os.environ.get("ENGLISH_SOURCE_MAINTAINER", f"translator: {TRANSLATOR_NAME}; edition: {EDITION_LABEL}"),
        license_text=f"operator-sourced English translation; translator {TRANSLATOR_NAME}; edition {EDITION_LABEL}",
        lang_note="English translation",
    )
    print(f"\nProvenance: arabic={ar_id}, english={en_id}")
    return 0


def cmd_ingest(_args):
    """Two-step insert: juridical_texts (Arabic) then juridical_translations (English).

    Idempotent on (text_name, baab_or_section, ingestion_provenance_id).
    """
    verify_schema()
    ar_sha, en_sha, en_path = _check_files(check_sha=True)
    arabic_blob = load_arabic_text()
    english_blob = load_english_text()

    # Fetch both provenance IDs
    ar_prov = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{ar_sha}", "select": "id", "limit": "1",
    })
    if not ar_prov:
        print("ERROR: Arabic provenance missing — run `provenance` first", file=sys.stderr)
        return 4
    en_prov = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{en_sha}", "select": "id", "limit": "1",
    })
    if not en_prov:
        print("ERROR: English provenance missing — run `provenance` first", file=sys.stderr)
        return 4
    arabic_prov_id = ar_prov[0]["id"]
    english_prov_id = en_prov[0]["id"]

    # Idempotency check on juridical_texts
    existing = supabase_get("juridical_texts", {
        "text_name": f"eq.{TEXT_NAME}",
        "baab_or_section": f"eq.{BAAB_NAME}",
        "ingestion_provenance_id": f"eq.{arabic_prov_id}",
        "select": "id", "limit": "1",
    })
    if existing:
        jt_id = existing[0]["id"]
        print(f"  juridical_texts already present (id={jt_id}); checking translation...")
    else:
        arabic_sha_inline = sha256_hex(arabic_blob)
        jt_row = {
            "text_name": TEXT_NAME,
            "author_name": AUTHOR_NAME,
            "author_death_hijri": AUTHOR_DEATH_HIJRI,
            "author_death_gregorian": AUTHOR_DEATH_GREGORIAN,
            "madhab": MADHAB,
            "dalil_strength": DALIL_STRENGTH,
            "baab_or_section": BAAB_NAME,
            "baab_order": BAAB_ORDER,
            "arabic_text": arabic_blob,
            "arabic_text_sha256": arabic_sha_inline,
            "ingestion_provenance_id": arabic_prov_id,
        }
        result = supabase_post("juridical_texts", jt_row)
        jt_id = result[0]["id"]
        print(f"  + juridical_texts row written: id={jt_id} ({len(arabic_blob)} ar chars)")

    # Idempotency check on juridical_translations
    existing_tr = supabase_get("juridical_translations", {
        "juridical_text_id": f"eq.{jt_id}",
        "language_code": "eq.en",
        "select": "id", "limit": "1",
    })
    if existing_tr:
        print(f"  juridical_translations already present (id={existing_tr[0]['id']}); skipping.")
    else:
        english_capped = english_blob[:50000]  # cap per-row blob
        tr_row = {
            "juridical_text_id": jt_id,
            "language_code": "en",
            "translator_name": TRANSLATOR_NAME,
            "translation_source_work": TRANSLATION_SOURCE_WORK,
            "translation_text": english_capped,
            "translation_text_sha256": sha256_hex(english_capped),
            "output_tier": "paraphrased",
            "edition_label": EDITION_LABEL,
            "ingestion_provenance_id": english_prov_id,
        }
        result = supabase_post("juridical_translations", tr_row)
        print(f"  + juridical_translations row written: id={result[0]['id']} ({len(english_capped)} en chars)")

    print("\nNext step: run scripts/backfill_juridical_embeddings.py with CORPUS_VERSION bumped")
    print("to generate per-chunk embeddings for the new Hajj baab.")
    return 0


def cmd_verify(_args):
    _require_key()
    rows = supabase_get("juridical_texts", {
        "text_name": f"eq.{TEXT_NAME}",
        "baab_or_section": f"eq.{BAAB_NAME}",
        "select": "id,baab_order,author_name,arabic_text_sha256,arabic_text",
    })
    if not rows:
        print(f"  no juridical_texts row for ({TEXT_NAME}, {BAAB_NAME})")
        return 1
    jt = rows[0]
    print(f"  juridical_texts: id={jt['id']} baab_order={jt['baab_order']}")
    print(f"    author: {jt['author_name']}")
    print(f"    arabic: {len(jt.get('arabic_text') or '')}c, sha256={jt['arabic_text_sha256'][:16]}...")

    trs = supabase_get("juridical_translations", {
        "juridical_text_id": f"eq.{jt['id']}",
        "select": "id,language_code,translator_name,translation_source_work,edition_label,translation_text,output_tier",
    })
    print(f"  juridical_translations: {len(trs)} row(s)")
    for tr in trs:
        print(f"    [{tr['language_code']}] {tr['translator_name']} ({tr['edition_label']}) — "
              f"tier={tr['output_tier']}, {len(tr.get('translation_text') or '')}c")
    return 0


SUBCOMMANDS = {
    "extract": cmd_extract,
    "provenance": cmd_provenance,
    "ingest": cmd_ingest,
    "verify": cmd_verify,
}


def main():
    parser = argparse.ArgumentParser(description="Kashifat al-Sajā Hajj-baab ingestion")
    parser.add_argument("cmd", choices=list(SUBCOMMANDS))
    args, _ = parser.parse_known_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
