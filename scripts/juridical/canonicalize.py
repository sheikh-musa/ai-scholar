#!/usr/bin/env python3
"""
Canonicalize a raw downloaded matn file into ingest-ready form.

Operations (in order):
  1. NFC normalize (per quranic-text-integrity Q-2 transposed to juridical)
  2. Strip page numbers — common patterns: "[ص: 12]", "(12)", "صفحة 12"
  3. Strip bracketed editorial apparatus — "[تحقيق ...]", "(٢) أي ..."
  4. Strip footnote markers — "(1)" embedded in flowing text, where (N) is at
     line-end or followed by punctuation
  5. Preserve baab markers — keep " بَاب " / " بابُ " / " فصل " / " مسألة "
  6. Collapse runs of whitespace
  7. Strip leading/trailing whitespace per line

Does NOT modify the matn text content itself — only structural cleanup.
Preserves diacritics and shadda.

Usage:
  python3 scripts/juridical/canonicalize.py --in raw.txt --out matn.txt
  python3 scripts/juridical/canonicalize.py --in raw.txt --out matn.txt --verbose

Input: raw download (UTF-8 text). Output: canonicalized matn (UTF-8).

After canonicalization: ingest_matn.py reads the output + computes SHA + splits
on baab markers + INSERTs juridical_texts rows.
"""

import re
import sys
import unicodedata
from pathlib import Path

# Patterns to strip — order matters (more specific before more general)
PAGE_NUMBER_PATTERNS = [
    re.compile(r"\[ص:\s*\d+\s*[/\-]?\s*\d*\]"),     # [ص: 12] or [ص: 12/3]
    re.compile(r"\(صفحة\s*\d+\)"),                    # (صفحة 12)
    re.compile(r"\bصفحة\s+\d+\b"),                   # صفحة 12 standalone
    re.compile(r"\b[Pp]age\s+\d+\b"),                # English page (rare in matn but seen in some sources)
]

BRACKETED_APPARATUS = [
    re.compile(r"\[تحقيق[^]]*\]"),                    # [تحقيق ...]
    re.compile(r"\[تخريج[^]]*\]"),                    # [تخريج ...]
    re.compile(r"\[تعليق[^]]*\]"),                    # [تعليق ...]
    re.compile(r"\[شرح[^]]*\]"),                      # [شرح ...]
    re.compile(r"\[\s*\d+\s*[/\-]\s*\d+\s*\]"),       # [12/3] (volume/page)
]

FOOTNOTE_MARKER = re.compile(r"\(\d{1,3}\)(?=\s*[\.\،\؛\:\s])")

# Baab/section markers we MUST preserve (regex-detectable)
BAAB_MARKERS = [
    re.compile(r"\bبَابُ?\b"),
    re.compile(r"\bبابُ?\b"),
    re.compile(r"\bفَصْلٌ?\b"),
    re.compile(r"\bفصلٌ?\b"),
    re.compile(r"\bمَسْأَلَةٌ?\b"),
    re.compile(r"\bمسألةٌ?\b"),
    re.compile(r"\bكِتَابُ?\b"),
    re.compile(r"\bكتابُ?\b"),
]


def canonicalize(raw: str, verbose: bool = False) -> tuple[str, dict]:
    stats = {"page_numbers_stripped": 0, "apparatus_stripped": 0, "footnotes_stripped": 0}

    # 1. NFC normalize
    text = unicodedata.normalize("NFC", raw)

    # 2. Strip page numbers
    for pat in PAGE_NUMBER_PATTERNS:
        before = text
        text = pat.sub("", text)
        stats["page_numbers_stripped"] += len(pat.findall(before))

    # 3. Strip bracketed apparatus
    for pat in BRACKETED_APPARATUS:
        before = text
        text = pat.sub("", text)
        stats["apparatus_stripped"] += len(pat.findall(before))

    # 4. Strip footnote markers (numeric in parens followed by punct/space)
    before = text
    text = FOOTNOTE_MARKER.sub("", text)
    stats["footnotes_stripped"] = len(FOOTNOTE_MARKER.findall(before))

    # 5. Verify baab markers still present
    baab_count = sum(len(pat.findall(text)) for pat in BAAB_MARKERS)
    stats["baab_markers_preserved"] = baab_count

    # 6. Collapse internal whitespace, preserve newlines
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        # Collapse multiple spaces/tabs to single space
        line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(line)
    # Drop empty consecutive lines (keep at most one blank)
    final_lines = []
    prev_blank = False
    for line in cleaned_lines:
        if not line:
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        final_lines.append(line)
    text = "\n".join(final_lines).strip() + "\n"

    if verbose:
        print(f"  page_numbers_stripped: {stats['page_numbers_stripped']}", file=sys.stderr)
        print(f"  apparatus_stripped: {stats['apparatus_stripped']}", file=sys.stderr)
        print(f"  footnotes_stripped: {stats['footnotes_stripped']}", file=sys.stderr)
        print(f"  baab_markers_preserved: {stats['baab_markers_preserved']}", file=sys.stderr)
        print(f"  output: {len(text)} chars across {text.count(chr(10))+1} lines", file=sys.stderr)

    return text, stats


def main():
    args = sys.argv[1:]
    if "--in" not in args or "--out" not in args:
        print("usage: canonicalize.py --in <raw.txt> --out <matn.txt> [--verbose]", file=sys.stderr)
        sys.exit(2)
    in_path = Path(args[args.index("--in") + 1])
    out_path = Path(args[args.index("--out") + 1])
    verbose = "--verbose" in args

    raw = in_path.read_text(encoding="utf-8")
    canonical, stats = canonicalize(raw, verbose=verbose)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(canonical, encoding="utf-8")

    if not verbose:
        print(f"canonicalized {in_path} → {out_path}: {len(canonical)} chars, {stats['baab_markers_preserved']} baab markers preserved")


if __name__ == "__main__":
    main()
