"""OpenITI source adapter.

OpenITI (Open Islamicate Texts Initiative, https://github.com/OpenITI/RELEASE)
hosts ~10,000 classical Arabic texts in a uniform markdown-like format with
YAML/header metadata. Their corpus is academically curated with edition refs,
manuscript provenance, and OCR-cleaned text — exactly the Ihsan-grade source
posture we need.

URL pattern (raw fetchable):
  https://raw.githubusercontent.com/OpenITI/RELEASE/master/data/<authorURI>/<authorURI>.<workURI>/<authorURI>.<workURI>.<editionURI>

Each text file begins with a `######OpenITI#` magic line and a `#META# ...`
header block (key::value lines, ends at `#META#Header#End#`). The body uses
`# `, `## `, `### ` for nested headings (kitab → baab → fasl), `~~` for line
continuations (joins to prior line), and `PageV<vol>P<page>` inline page
markers (preserved for citation, removed for content matching).
"""
import re
import unicodedata
import urllib.error
import urllib.request
from . import SourceArtifact

OPENITI_RAW_BASE = "https://raw.githubusercontent.com/OpenITI/RELEASE/master"


def _fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-scholar-ihsan-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_meta_block(raw: str) -> tuple[dict, str]:
    """Extract #META# header into dict; return (metadata, body)."""
    metadata: dict = {}
    body_lines: list = []
    in_header = False
    saw_magic = False
    # Strip UTF-8 BOM (some OpenITI sources — e.g. Sham19 editions like
    # 0428AbuHusaynQuduri — ship with a leading ﻿ that prevents the
    # magic-line equality check below from matching).
    if raw and raw[0] == "﻿":
        raw = raw[1:]
    for line in raw.splitlines():
        if line.strip().lstrip("﻿") == "######OpenITI#":
            saw_magic = True
            in_header = True
            continue
        if in_header:
            if line.strip() == "#META#Header#End#":
                in_header = False
                continue
            m = re.match(r"#META#\s+(\S+)\s*::\s*(.*)$", line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                if value and value != "NODATA" and value != "NOTGIVEN":
                    metadata[key] = value
        else:
            body_lines.append(line)
    if not saw_magic:
        raise ValueError("not an OpenITI text (missing ######OpenITI# magic line)")
    return metadata, "\n".join(body_lines)


def _strip_line_continuations(body: str) -> str:
    """OpenITI uses `~~` at the start of a continuation line to mean 'append
    to the prior line with a space'. Reconstitute paragraphs by removing the
    `~~` and joining."""
    lines = body.splitlines()
    out: list = []
    for ln in lines:
        if ln.startswith("~~"):
            cont = ln[2:].lstrip()
            if out:
                out[-1] = out[-1].rstrip() + " " + cont
            else:
                out.append(cont)
        else:
            out.append(ln)
    return "\n".join(out)


PAGE_MARKER_RE = re.compile(r"PageV\d+P\d+")


def _strip_page_markers(text: str) -> str:
    return PAGE_MARKER_RE.sub("", text)


def _extract_section_by_heading(body: str, heading_substring: str) -> tuple[str, int, int]:
    """Locate a section by its level-1 heading (e.g. 'كتاب الحج'). Returns
    (section_text, start_line, end_line). Section ends at the next level-1
    heading or EOF. Raises if heading not found.

    Heading-substring matching is fuzzy: NFC + diacritic-stripped substring
    match, so 'كتاب الحج' will match '# كتاب الحج' OR '# كِتَابُ الحَجِّ'.
    """
    norm_target = _strip_diacritics(unicodedata.normalize("NFC", heading_substring))
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        m = re.match(r"^# (?!#)(.+)$", ln)  # level-1 only ('# ' not '## ')
        if not m:
            continue
        heading = _strip_diacritics(unicodedata.normalize("NFC", m.group(1)))
        if norm_target in heading:
            start = i
            break
    if start is None:
        raise ValueError(f"heading '{heading_substring}' not found in body")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^# (?!#)", lines[j]):
            end = j
            break
    section = "\n".join(lines[start:end])
    return section, start, end


_DIACRITIC_RE = re.compile(r"[ً-ٰٟۖ-ۭ]")


def _strip_diacritics(text: str) -> str:
    """Strip Arabic diacritics (harakat) for fuzzy comparison."""
    return _DIACRITIC_RE.sub("", text)


def fetch_openiti(
    text_uri: str,
    edition_uri: str,
    section_heading: str | None = None,
) -> SourceArtifact:
    """Fetch an OpenITI text or section.

    Args:
      text_uri:        e.g. '1316IbnCumarBantaniJawi.NihayatZayn'
      edition_uri:     e.g. 'JK000310-ara1' or 'Shamela0006146-ara1'
      section_heading: if provided, extract only the matching level-1 heading
                       section (e.g. 'كتاب الحج'). If None, return full body.

    Returns SourceArtifact with metadata populated from the #META# header.
    """
    # text_uri is "<author>.<work>"; split to find directory structure
    if "." not in text_uri:
        raise ValueError(f"text_uri must be 'author.work' form; got '{text_uri}'")
    author_uri = text_uri.split(".")[0]
    work_dir = text_uri
    file_name = f"{text_uri}.{edition_uri}"
    url = f"{OPENITI_RAW_BASE}/data/{author_uri}/{work_dir}/{file_name}"

    try:
        raw = _fetch(url)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenITI fetch failed for {url}: HTTP {e.code}") from e

    metadata, body = _parse_meta_block(raw)
    metadata["edition_uri"] = edition_uri
    metadata["text_uri"] = text_uri

    body = _strip_line_continuations(body)
    body = _strip_page_markers(body)

    if section_heading:
        section_text, start_line, end_line = _extract_section_by_heading(body, section_heading)
        metadata["section_heading"] = section_heading
        metadata["section_line_range"] = f"{start_line}-{end_line}"
        content = section_text
    else:
        content = body

    # Normalize NFC for stable hashing
    content = unicodedata.normalize("NFC", content).strip()

    # Build provenance_fields aligned to deployed ingestion_provenance schema
    author_name = metadata.get("010.AuthorNAME", "unknown")
    book_title = metadata.get("020.BookTITLE", "unknown")
    edition_publisher = metadata.get("043.EdPUBLISHER", "unknown")
    edition_place = metadata.get("044.EdPLACE", "unknown")
    provenance_fields = {
        "source_url": url,
        "source_maintainer": "OpenITI (Open Islamicate Texts Initiative) — github.com/OpenITI/RELEASE",
        "license_declaration": (
            f"Classical Arabic text, public domain. Author {author_name} d. "
            f"{metadata.get('011.AuthorDIED', 'unknown')} H. Edition: {edition_publisher} "
            f"({edition_place}). OpenITI corpus is academically curated; mirrors editions "
            f"with attribution; redistribution permitted under CC-BY-NC-SA per OpenITI license."
        ),
        "source_file_sha256": None,   # filled by SourceArtifact.sha256 property
        "verified_by_identity": "cc-scholar (Ihsan ingestion pipeline)",
        "notes": (
            f"OpenITI text: {book_title}; edition_uri={edition_uri}; "
            f"section={section_heading or 'full body'}; "
            f"source_lib={metadata.get('030.LibURI', 'unknown')}"
        ),
    }

    return SourceArtifact(
        adapter_name="openiti",
        source_url=url,
        content=content,
        metadata=metadata,
        provenance_fields=provenance_fields,
    )
