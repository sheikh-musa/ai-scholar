#!/usr/bin/env python3
"""Safīnat al-Najā ingestion driver — option (ii) lite, 5 topical buckets, hajj deferred.

Per operator decision 2026-05-07 (strategic_decisions id 699 amendment 4):
  - Arabic source: docs/sources/safinat-al-najah-arabic.txt (usul.ai / al-Maktaba al-Shamela)
    Original matn + Nawawi al-Jawi siyam additions; 61 (فصل) markers; no hajj coverage.
  - English source: docs/sources/safinat-al-najah-marbuqi-tr.pdf (al-inaam 2009, al-Marbuqi tr.)
  - 5 topical buckets: Muqaddimah & Iman, Taharah, Salah, Zakah, Siyam.
  - Hajj DEFERRED to Phase 2. Arabic source (usul.ai/Shamela) lacks Ba'atiyyah hajj addition;
    al-Marbuqi PDF Arabic side is glyph-encoded garbage (verified via pymupdf survey 2026-05-07).

Per CAI-RESP-136 META-PROCESS AMENDMENT: cmd_provenance and cmd_ingest call verify_schema()
which fetches the OpenAPI spec and confirms both juridical_texts and juridical_translations
exist with expected columns before any insert. If juridical_translations is missing, script
exits with code 5 and instructions to apply the migration first.

TWO INGESTION PROVENANCE ROWS (one per source):
  - Arabic provenance: usul.ai / al-Maktaba al-Shamela; public domain (author d. 1271 H).
  - English provenance: al-Marbuqi 2009 PDF; sadaqah jariyah (al-inaam.com explicit grant).

INSERT PATTERN — per bucket (not per chapter):
  STEP 1: INSERT into juridical_texts — Arabic matn for bucket (NFC-normalized, SHA-256).
  STEP 2: INSERT into juridical_translations — English for bucket (FK to step 1 row).

Subcommands:
  extract     Dry-run — extract chapters from PDF, print chapter path + first 200 chars English.
              No DB writes.
  provenance  Write BOTH ingestion_provenance rows (Arabic + English). Idempotent on SHA.
              Calls verify_schema() first — exits 5 if juridical_translations not deployed.
  ingest      Bucket assignment + two-step insert per bucket. Idempotent per
              (text_name, baab_or_section, arabic_provenance_id). Exits 5 if schema not ready.
  verify      POST-INGEST sanity: JOIN both tables, print bucket name + arabic/english char counts.
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

# ---------------------------------------------------------------------------
# Paths + SHAs
# ---------------------------------------------------------------------------

ARABIC_TXT_PATH = Path(__file__).parent.parent / "docs/sources/safinat-al-najah-arabic.txt"
PDF_PATH = Path(__file__).parent.parent / "docs/sources/safinat-al-najah-marbuqi-tr.pdf"

ARABIC_SHA = "18a3bb24fc44ec4cef260587dd5a289a7c387750f6e7d6cfc3aed7aa60e5199c"
PDF_SHA = "679404ac682aea814ed726b6255611fd4624a2d724fe6fc5969cd430255ad491"

SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY", "")
if not SUPABASE_KEY:
    print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY not set", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEXT_NAME = "Safīnat al-Najā"
TRANSLATOR = "ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī"
TRANSLATION_SOURCE_WORK = "Safīnat al-Najā (al-Marbūqī tr., al-inaam.com 2009)"
EDITION_LABEL = "Limited Edition Ṣafar 1430 H / Feb 2009"

# ---------------------------------------------------------------------------
# Topical buckets — 5 worship topics; hajj excluded per operator 2026-05-07.
#
# Bucket author notes:
#   Buckets 1-4: Sālim ibn ʿAbdullah al-Ḥaḍramī (d. 1271 H / 1855 CE) original matn.
#   Siyam: Muḥammad Nawawī al-Jāwī (d. 1316 H / 1898 CE) added the siyam section per
#           historical record, as noted in AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 amend-4 body.
#
# Hajj DEFERRED to Phase 2 per operator decision 2026-05-07.
#   Arabic source (usul.ai/Shamela) lacks Ba'atiyyah hajj addition.
#   al-Marbuqi PDF Arabic side is glyph-encoded garbage (broken Unicode mapping;
#   verified via both pypdf and pymupdf surveys).
#   Phase 2 hajj sourcing tracked in strategic_decisions id 699 amendment 4 body.
#   Likely pairs with INV-7 paired-scholar program activation.
# ---------------------------------------------------------------------------

TOPICAL_BUCKETS: dict = {
    "Muqaddimah & Iman": {
        # Keyword match: fasl must contain at least one of these Arabic phrases.
        # Covers: pillars of Islam/Iman, signs of puberty, meaning of lailaha.
        "matn_arabic_keywords": [
            "أركان الإسلام",
            "أركان الإيمان",
            "علامات البلوغ",
            "معنى لاإله إلاالله",
            "لامعبود بحق",
        ],
        "pdf_english_chapters": ["Muqaddimah", "Islam and Iman", "Al-Ahkam al-Sharʿiyyah"],
        "baab_order": 1,
        "author_name": "Sālim ibn ʿAbdullah ibn Saʿd ibn Samīr al-Ḥaḍramī al-Shāfiʿī",
    },
    "Taharah": {
        # Covers: wudu, ghusl, tayammum, najasat, hayd, nifas, water types, istinja.
        # Broad coverage: النية here is the wudu niyyah fasl (contextually follows fara'id al-wudu).
        "matn_arabic_keywords": [
            "الوضوء",
            "فروض الوضوء",
            "الغسل",
            "التيمم",
            "النجاسات",
            "الحجر",       # istinja / hajar
            "موجبات الغسل",
            "شروط الوضوء",
            "نواقض الوضوء",
            "نوا قض الوضوء",
            "الماء قليل",   # water classification fasl
            "النية : قصد",  # niyyah for wudu (context: directly follows fara'id al-wudu fasl)
            "المغلظة",       # graded najasah removal
            "الحيض",         # hayd — purity rules
            "يتنجس بوقوع",  # additional water-najasat coverage
            "الإستعانات",    # pouring water for wudu — taharah assistance
            "الذي يظهر من النجاسة",  # things that become pure (khamr self-vinegar, hide tanning)
        ],
        "pdf_english_chapters": ["Taharah"],
        "baab_order": 2,
        "author_name": "Sālim ibn ʿAbdullah ibn Saʿd ibn Samīr al-Ḥaḍramī al-Shāfiʿī",
    },
    "Salah": {
        # Covers: salah conditions/pillars/invalidators, adhan, times, jumu'ah,
        #         janazah, imamate, qasr/jam', sujud conditions, tashahud, fatiha.
        "matn_arabic_keywords": [
            "الصلاة",
            "أركان الصلاة",
            "أوقات الصلاة",
            "مبطلات الصلاة",
            "الجمعة",
            "الجنازة",
            "تكبيرة الإحرام",
            "شروط الفاتحة",       # fatiha conditions fasl
            "تشديدات الفاتحة",    # fatiha shaddas fasl
            "شروط السجود",         # sujud conditions fasl
            "تشديدات التشهد",      # tashahud shaddas fasl
            "أقل السلام",          # taslim minimum fasl
            "الطمأنينة",           # tuma'ninah fasl
            "شروط القدوة",         # congregation conditions
            "صور القدوة",          # congregation forms
            "شروط جمع التقديم",    # jam' taqdim
            "شروط جمع التأخير",    # jam' ta'khir
            "شروط القصر",          # qasr conditions
            "أقل الكفن",           # shroud — part of janazah
            "أقل الدفن",           # burial — part of janazah
            "ينبش الميت",          # exhumation — part of janazah
        ],
        "pdf_english_chapters": ["Adhan", "Salah", "Salah Janazah"],
        "baab_order": 3,
        "author_name": "Sālim ibn ʿAbdullah ibn Saʿd ibn Samīr al-Ḥaḍramī al-Shāfiʿī",
    },
    "Zakah": {
        # Covers: zakah conditions, nisab, zakah al-fitr, rikaz.
        "matn_arabic_keywords": [
            "الزكاة",
            "زكاة الفطر",
            "الركاز",
            "النصاب",
        ],
        "pdf_english_chapters": ["Zakah"],
        "baab_order": 4,
        "author_name": "Sālim ibn ʿAbdullah ibn Saʿd ibn Samīr al-Ḥaḍramī al-Shāfiʿī",
    },
    "Siyam": {
        # Covers: sawm conditions, pillars, iftar, kaffarah — Nawawi al-Jawi additions.
        # Includes sub-fasls: shuroot al-sihhah, shuroot al-wujub, arkan.
        "matn_arabic_keywords": [
            "صوم رمضان",
            "الصوم",
            "الإفطار",
            "كفارة",
            "شروط صحته",          # shuroot sihhah al-sawm
            "شروط وجوبه",         # shuroot wujub al-sawm
            "أركانه ثلاثة",       # arkan al-sawm
            "الذي لا يفطر",       # mafatir — things that do not break fast
        ],
        "pdf_english_chapters": ["Saum"],
        "baab_order": 5,
        # Nawawi al-Jawi authored the siyam section per historical record.
        "author_name": "Muḥammad Nawawī ibn ʿUmar al-Jāwī al-Bantanī al-Shāfiʿī",
        "author_death_hijri": 1316,
        "author_death_gregorian": 1898,
    },
}

# Hajj DEFERRED — see module docstring.
# Default author death years for buckets 1-4 (Salim al-Hadhrami).
DEFAULT_AUTHOR_DEATH_HIJRI = 1271
DEFAULT_AUTHOR_DEATH_GREGORIAN = 1855

# ---------------------------------------------------------------------------
# Ingestion provenance definitions (TWO sources)
# ---------------------------------------------------------------------------

ARABIC_PROVENANCE = {
    "source_url": "https://usul.ai/t/matn-safinat-al-naja",
    "source_maintainer": "usul.ai (al-Maktaba al-Shamela)",
    "license_declaration": (
        "Classical Islamic text, public domain "
        "(author Salim al-Hadhrami d. 1271 H / 1855 CE)"
    ),
    "source_file_sha256": ARABIC_SHA,
    "verified_by_identity": "cc-scholar (operator-directed)",
    "notes": (
        "Original matn + Nawawi al-Jawi siyam additions; "
        "covers taharah/salah/zakah/siyam (no hajj). "
        "Source file: docs/sources/safinat-al-najah-arabic.txt (24,906 chars; "
        "19,289 Arabic codepoints). 61 (فصل) markers."
    ),
}

ENGLISH_PROVENANCE = {
    "source_url": "docs/sources/safinat-al-najah-marbuqi-tr.pdf",
    "source_maintainer": "al-inaam.com",
    "license_declaration": (
        "Translator/publisher explicit reproduction grant per page 3 (sadaqah jariyah posture)"
    ),
    "source_file_sha256": PDF_SHA,
    "verified_by_identity": "musa",
    "notes": "Bilingual al-Marbuqi 2009 edition. 185 pages.",
}

# ---------------------------------------------------------------------------
# Chapter headings from PDF TOC — for English extraction only.
# Order matters (longest/most-specific first).
# ---------------------------------------------------------------------------

CHAPTER_HEADINGS = [
    "Muqaddimah", "Islam and Iman", "Al-Ahkam al-Sharʿiyyah",
    "Taharah", "Adhan", "Salah", "Salah Janazah",
    "Zakah", "Saum", "Hajj and ʿUmrah",
    "Bibliography",
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


def load_arabic_text() -> str:
    """Read and NFC-normalize the Arabic source text file."""
    raw = ARABIC_TXT_PATH.read_text(encoding="utf-8")
    return unicodedata.normalize("NFC", raw)


def split_arabic_fasls(arabic_text: str) -> list:
    """Split Arabic source on (فصل) markers.

    Returns list of (fasl_index, fasl_text) tuples.
    Index 0 is the pre-fasl basmala/intro text (not a fasl proper).
    """
    parts = re.split(r"\(فصل\s*\)", arabic_text)
    result = []
    for i, part in enumerate(parts):
        result.append((i, part.strip()))
    return result


def assign_fasls_to_buckets(fasls: list) -> dict:
    """Classify each fasl (index > 0) into a bucket by keyword matching.

    Uses first-match-wins over TOPICAL_BUCKETS (insertion order preserved in Python 3.7+).
    Fasls that match no bucket are logged as unmatched.

    Returns dict: bucket_name -> list of fasl texts.
    """
    bucket_map: dict = {k: [] for k in TOPICAL_BUCKETS}
    unmatched = []

    for fasl_index, fasl_text in fasls:
        if fasl_index == 0:
            # Pre-fasl intro/basmala — skip bucket assignment.
            continue
        matched = None
        for bucket_name, bucket_cfg in TOPICAL_BUCKETS.items():
            for kw in bucket_cfg["matn_arabic_keywords"]:
                if kw in fasl_text:
                    matched = bucket_name
                    break
            if matched:
                break
        if matched:
            bucket_map[matched].append(fasl_text)
        else:
            unmatched.append((fasl_index, fasl_text[:80]))

    if unmatched:
        print(f"  [bucket-assign] {len(unmatched)} fasl(s) unmatched (likely intro/closing du'a):")
        for idx, preview in unmatched:
            print(f"    fasl #{idx}: {preview!r}")

    return bucket_map


def extract_pages(path: Path) -> list:
    reader = pypdf.PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in reader.pages]


def segment_chapters(pages: list) -> list:
    """Walk pages, identify chapter boundaries by heading match.

    Returns list of dicts: chapter_path, page_start, page_end, english_text.
    """
    chapters = []
    current = None
    for i, page_text in enumerate(pages):
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
                "pages_raw": [page_text],
            }
        elif current is not None:
            current["pages_raw"].append(page_text)
    if current is not None:
        current["page_end"] = len(pages) - 1
        chapters.append(current)
    for ch in chapters:
        ch["english_text"] = "\n\n".join(ch["pages_raw"])
    return chapters


def build_bucket_english(chapters: list) -> dict:
    """Map bucket name -> concatenated English text + page range from PDF chapters.

    Returns dict: bucket_name -> {english_text, page_start, page_end}.
    """
    result = {}
    for bucket_name, bucket_cfg in TOPICAL_BUCKETS.items():
        target_chapters = bucket_cfg.get("pdf_english_chapters", [])
        matched_chapters = [ch for ch in chapters if ch["chapter_path"] in target_chapters]
        if not matched_chapters:
            result[bucket_name] = {"english_text": "", "page_start": None, "page_end": None}
            continue
        english_parts = []
        page_starts = []
        page_ends = []
        for ch in matched_chapters:
            text_nfc = unicodedata.normalize("NFC", ch["english_text"])
            english_parts.append(text_nfc)
            page_starts.append(ch["page_start"])
            page_ends.append(ch["page_end"])
        combined = unicodedata.normalize("NFC", "\n\n".join(english_parts))
        result[bucket_name] = {
            "english_text": combined,
            "page_start": min(page_starts),
            "page_end": max(page_ends),
        }
    return result


# ---------------------------------------------------------------------------
# Schema verification gate (CAI-RESP-136 meta-process amendment)
# ---------------------------------------------------------------------------


def verify_schema() -> bool:
    """Fetch OpenAPI spec and confirm juridical_texts + juridical_translations + ingestion_provenance.

    Returns True if all tables present. Prints error and calls sys.exit(5) if
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
        has_prov = "/ingestion_provenance" in paths
    except Exception as exc:
        print(
            f"ERROR: could not fetch OpenAPI spec for schema verification: {exc}",
            file=sys.stderr,
        )
        sys.exit(5)

    if not has_jt:
        print(
            "ERROR: juridical_texts table not found in deployed schema. "
            "Confirm AL-BAYAN-003 migration (20260428194802_al_bayan_003_juridical_corpus) "
            "is applied.",
            file=sys.stderr,
        )
        sys.exit(5)

    if not has_prov:
        print(
            "ERROR: ingestion_provenance table not found in deployed schema. "
            "Confirm AL-BAYAN-003 migration is applied.",
            file=sys.stderr,
        )
        sys.exit(5)

    if not has_tr:
        print(
            "ERROR: juridical_translations table not deployed. "
            "Run `supabase migration up` after challenge_window closes 2026-05-08T01:32Z "
            "(or with explicit Musa early-close consent) to apply "
            "20260507_001_juridical_translations.sql.",
            file=sys.stderr,
        )
        sys.exit(5)

    print("Schema verified: juridical_texts + juridical_translations + ingestion_provenance all present.")
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


def supabase_post(table: str, data: dict) -> list:
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
    """Dry-run: extract PDF chapters, print chapter name + page range + English preview."""
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 2
    sha = compute_sha256(PDF_PATH)
    if sha != PDF_SHA:
        print(f"ERROR: PDF SHA mismatch — expected {PDF_SHA}, got {sha}", file=sys.stderr)
        return 3
    print(f"PDF SHA verified: {sha}")
    pages = extract_pages(PDF_PATH)
    print(f"Extracted {len(pages)} pages from PDF")
    chapters = segment_chapters(pages)
    print(f"Segmented into {len(chapters)} chapter(s):")
    for ch in chapters:
        eng_preview = ch["english_text"][:200].replace("\n", " ")
        print(
            f"  {ch['chapter_path']:35} pages {ch['page_start']:3}-{ch['page_end']:3}  "
            f"en={len(ch['english_text']):6}chars   {eng_preview}…"
        )
    print()

    # Verify Arabic source file
    if not ARABIC_TXT_PATH.exists():
        print(f"WARN: Arabic text file not found at {ARABIC_TXT_PATH}", file=sys.stderr)
        return 0
    ar_sha = compute_sha256(ARABIC_TXT_PATH)
    sha_status = "OK" if ar_sha == ARABIC_SHA else f"MISMATCH (expected {ARABIC_SHA})"
    arabic_text = load_arabic_text()
    fasls = split_arabic_fasls(arabic_text)
    # Count non-intro fasls
    fasl_count = len(fasls) - 1
    print(f"Arabic text file SHA: {ar_sha} [{sha_status}]")
    print(f"Arabic text: {len(arabic_text)} chars, {fasl_count} (فصل) fasls")
    print()

    # Dry-run bucket assignment
    bucket_map = assign_fasls_to_buckets(fasls)
    print("Bucket assignment (Arabic fasl counts):")
    for bucket_name, bucket_fasls in bucket_map.items():
        en_data = build_bucket_english(chapters).get(bucket_name, {})
        en_len = len(en_data.get("english_text", ""))
        ar_len = sum(len(f) for f in bucket_fasls)
        print(
            f"  {bucket_name:30} {len(bucket_fasls):2} fasls  "
            f"{ar_len:5} ar chars  {en_len:6} en chars"
        )
    print()
    print("NOTE: Hajj bucket is DEFERRED to Phase 2 per operator decision 2026-05-07.")
    return 0


def cmd_provenance(args):
    """Write BOTH ingestion_provenance rows (Arabic + English). Idempotent on SHA."""
    verify_schema()

    def write_provenance_row(prov_def: dict, label: str) -> str:
        sha = prov_def["source_file_sha256"]
        existing = supabase_get("ingestion_provenance", {
            "source_file_sha256": f"eq.{sha}",
            "select": "id",
            "limit": "1",
        })
        if existing:
            prov_id = existing[0]["id"]
            print(f"  {label} provenance row already present: id={prov_id}")
            return prov_id
        result = supabase_post("ingestion_provenance", prov_def)
        prov_id = result[0]["id"]
        print(f"  {label} provenance row written: id={prov_id}")
        return prov_id

    ar_id = write_provenance_row(ARABIC_PROVENANCE, "Arabic (usul.ai)")
    en_id = write_provenance_row(ENGLISH_PROVENANCE, "English (al-Marbuqi PDF)")
    print(f"Provenance rows: arabic={ar_id}, english={en_id}")
    return 0


def cmd_ingest(args):
    """Two-step insert per bucket: juridical_texts (Arabic) then juridical_translations (English).

    Per-bucket idempotency: checks (text_name, baab_or_section, arabic_provenance_id) before insert.
    Skips bucket if juridical_texts row already exists for that combo.
    """
    verify_schema()

    # ---- Source file checks ----
    if not ARABIC_TXT_PATH.exists():
        print(f"ERROR: Arabic text file not found at {ARABIC_TXT_PATH}", file=sys.stderr)
        return 2
    ar_sha = compute_sha256(ARABIC_TXT_PATH)
    if ar_sha != ARABIC_SHA:
        print(
            f"ERROR: Arabic text file SHA mismatch — expected {ARABIC_SHA}, got {ar_sha}",
            file=sys.stderr,
        )
        return 3
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 2
    pdf_sha = compute_sha256(PDF_PATH)
    if pdf_sha != PDF_SHA:
        print(
            f"ERROR: PDF SHA mismatch — expected {PDF_SHA}, got {pdf_sha}",
            file=sys.stderr,
        )
        return 3

    # ---- Load both sources ----
    arabic_text = load_arabic_text()
    fasls = split_arabic_fasls(arabic_text)
    pages = extract_pages(PDF_PATH)
    chapters = segment_chapters(pages)

    bucket_arabic = assign_fasls_to_buckets(fasls)
    bucket_english = build_bucket_english(chapters)

    # ---- Get both provenance IDs ----
    ar_prov_rows = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{ARABIC_SHA}",
        "select": "id",
        "limit": "1",
    })
    if not ar_prov_rows:
        print(
            "ERROR: Arabic ingestion_provenance row missing — run `provenance` subcommand first.",
            file=sys.stderr,
        )
        return 4
    arabic_provenance_id = ar_prov_rows[0]["id"]

    en_prov_rows = supabase_get("ingestion_provenance", {
        "source_file_sha256": f"eq.{PDF_SHA}",
        "select": "id",
        "limit": "1",
    })
    if not en_prov_rows:
        print(
            "ERROR: English ingestion_provenance row missing — run `provenance` subcommand first.",
            file=sys.stderr,
        )
        return 4
    english_provenance_id = en_prov_rows[0]["id"]

    written = 0
    skipped_dup = 0

    for bucket_name, bucket_cfg in TOPICAL_BUCKETS.items():
        fasl_list = bucket_arabic.get(bucket_name, [])
        if not fasl_list:
            print(f"  [{bucket_name}] WARN: no Arabic fasls matched — skipping bucket.")
            continue

        # Concatenate Arabic fasls into one blob; NFC normalize.
        arabic_blob = unicodedata.normalize("NFC", "\n\n".join(fasl_list))
        arabic_sha = sha256_hex(arabic_blob)

        # Idempotency check on juridical_texts
        existing = supabase_get("juridical_texts", {
            "text_name": f"eq.{urllib.parse.quote(TEXT_NAME)}",
            "baab_or_section": f"eq.{urllib.parse.quote(bucket_name)}",
            "ingestion_provenance_id": f"eq.{arabic_provenance_id}",
            "select": "id",
            "limit": "1",
        })
        if existing:
            print(f"  [{bucket_name}] already present (id={existing[0]['id']}) — skipping.")
            skipped_dup += 1
            continue

        # STEP 1: Insert into juridical_texts
        jt_row = {
            "text_name": TEXT_NAME,
            "author_name": bucket_cfg["author_name"],
            "author_death_hijri": bucket_cfg.get(
                "author_death_hijri", DEFAULT_AUTHOR_DEATH_HIJRI
            ),
            "author_death_gregorian": bucket_cfg.get(
                "author_death_gregorian", DEFAULT_AUTHOR_DEATH_GREGORIAN
            ),
            "madhab": "shafii",
            "dalil_strength": "primer_juridical",
            "baab_or_section": bucket_name,
            "baab_order": bucket_cfg["baab_order"],
            "arabic_text": arabic_blob,
            "arabic_text_sha256": arabic_sha,
            "ingestion_provenance_id": arabic_provenance_id,
        }
        jt_result = supabase_post("juridical_texts", jt_row)
        juridical_text_id = jt_result[0]["id"]

        # STEP 2: Insert into juridical_translations
        en_data = bucket_english.get(bucket_name, {})
        english_text = en_data.get("english_text", "")
        page_start = en_data.get("page_start")
        page_end = en_data.get("page_end")

        if not english_text:
            print(
                f"  [{bucket_name}] WARN: no English chapters matched for this bucket. "
                "juridical_texts row written; juridical_translations row skipped."
            )
        else:
            english_capped = english_text[:50000]  # cap per row to avoid blob rows
            english_sha = sha256_hex(english_capped)
            tr_row = {
                "juridical_text_id": juridical_text_id,
                "language_code": "en",
                "translator_name": TRANSLATOR,
                "translation_source_work": TRANSLATION_SOURCE_WORK,
                "translation_text": english_capped,
                "translation_text_sha256": english_sha,
                "output_tier": "paraphrased",
                # chapter-level granularity is editorial alignment; not verbatim per fiqh rule
                "page_start": page_start,
                "page_end": page_end,
                "edition_label": EDITION_LABEL,
                "ingestion_provenance_id": english_provenance_id,
            }
            supabase_post("juridical_translations", tr_row)

        written += 1
        print(
            f"  + {bucket_name:30} "
            f"({len(fasl_list)} fasls, {len(arabic_blob):5} ar chars, "
            f"{len(english_text):6} en chars, "
            f"pages {page_start}-{page_end})"
        )

    print(
        f"\nDone: {written} bucket(s) written, "
        f"{skipped_dup} already present."
    )
    print("NOTE: Hajj DEFERRED to Phase 2 per operator decision 2026-05-07.")
    return 0


def cmd_verify(args):
    """Spot-check ingested rows — JOIN juridical_texts + juridical_translations."""
    rows = supabase_get("juridical_translations", {
        "translator_name": f"eq.{urllib.parse.quote(TRANSLATOR)}",
        "select": (
            "juridical_text_id,language_code,page_start,page_end,output_tier,edition_label,"
            "juridical_texts(text_name,baab_or_section,baab_order,author_name,"
            "arabic_text)"
        ),
        "order": "page_start",
    })
    print(f"juridical_translations rows for translator '{TRANSLATOR}': {len(rows)}")
    for r in rows:
        jt = r.get("juridical_texts") or {}
        arabic_text = jt.get("arabic_text") or ""
        print(
            f"  [{r.get('language_code','?')}] "
            f"{jt.get('baab_or_section','?'):30} "
            f"pp {r.get('page_start','?'):3}-{r.get('page_end','?'):3}  "
            f"tier={r.get('output_tier','?')}  "
            f"ar={len(arabic_text):5}chars  "
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
    parser = argparse.ArgumentParser(
        description="Safīnat al-Najā ingestion driver — option (ii) lite, 5 buckets, hajj deferred"
    )
    parser.add_argument("cmd", choices=list(SUBCOMMANDS))
    args, _ = parser.parse_known_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
