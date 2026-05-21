"""Authenticity gates for the Ihsan ingestion pipeline.

Each gate is a pure function that takes a SourceArtifact and returns a
GateResult{name, passed, value, threshold, message}. The pipeline runs all
gates and refuses to write to the manifest if any HARD gate fails.

Gate severity:
  hard:    must pass; failure rejects the source outright
  soft:    failure logged + surfaced in manifest but doesn't block
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import SourceArtifact


@dataclass
class GateResult:
    name: str
    passed: bool
    severity: str            # "hard" | "soft"
    value: object            # what was measured (number, string, etc.)
    threshold: object        # the threshold compared against (or None)
    message: str             # human-readable explanation


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------

def gate_sha_present(artifact: SourceArtifact) -> GateResult:
    """SHA-256 must be computable (i.e., content is non-empty bytes)."""
    sha = artifact.sha256
    ok = bool(sha) and len(sha) == 64 and artifact.byte_length > 0
    return GateResult(
        name="sha_present",
        passed=ok,
        severity="hard",
        value=sha,
        threshold="64-char hex",
        message=("SHA-256 computed" if ok else "content empty or hash invalid"),
    )


def gate_arabic_codepoint_ratio(artifact: SourceArtifact, min_ratio: float = 0.55) -> GateResult:
    """Reject sources whose content is mostly non-Arabic (likely OCR garbage
    or wrong-language content). Threshold default 0.55: 55%+ of meaningful
    chars must be in the Arabic Unicode block.

    Calculation: (Arabic letters + Arabic-Indic digits) / (all letters+digits).
    Whitespace, punctuation, ASCII metadata markers are excluded from the
    denominator so structural noise doesn't tank the ratio.
    """
    content = artifact.content
    arabic = 0
    other_letter_or_digit = 0
    for ch in content:
        if ch.isspace():
            continue
        if not (ch.isalpha() or ch.isdigit()):
            continue
        cp = ord(ch)
        # Arabic + Arabic Supplement + Arabic Extended-A + Arabic Presentation Forms-A/B
        if (0x0600 <= cp <= 0x06FF) or (0x0750 <= cp <= 0x077F) or \
           (0x08A0 <= cp <= 0x08FF) or (0xFB50 <= cp <= 0xFDFF) or \
           (0xFE70 <= cp <= 0xFEFF):
            arabic += 1
        else:
            other_letter_or_digit += 1
    total = arabic + other_letter_or_digit
    if total == 0:
        return GateResult(
            name="arabic_codepoint_ratio",
            passed=False,
            severity="hard",
            value=0.0,
            threshold=min_ratio,
            message="no letters or digits found in content",
        )
    ratio = arabic / total
    return GateResult(
        name="arabic_codepoint_ratio",
        passed=ratio >= min_ratio,
        severity="hard",
        value=round(ratio, 3),
        threshold=min_ratio,
        message=f"{arabic}/{total} chars are Arabic ({ratio:.1%})",
    )


def gate_author_death_classical(artifact: SourceArtifact, min_years_postmortem_hijri: int = 50) -> GateResult:
    """For public-domain claims, author death-year must be ≥50 hijri years
    in the past. Modern authors require explicit license declaration that
    bypasses this gate (handled at the pipeline level).

    Expects metadata['011.AuthorDIED'] (OpenITI format) or provenance_fields['author_death_hijri'].
    Severity: soft (some sources lack metadata; pipeline applies stricter
    check on cross-attestation step).
    """
    died = (
        artifact.metadata.get("011.AuthorDIED")
        or artifact.provenance_fields.get("author_death_hijri")
    )
    if not died or str(died).strip().upper() in ("NODATA", "NOTGIVEN", "UNKNOWN"):
        return GateResult(
            name="author_death_classical",
            passed=False,
            severity="soft",
            value=None,
            threshold=min_years_postmortem_hijri,
            message="author death year missing from source metadata",
        )
    try:
        died_h = int(re.search(r"\d{3,4}", str(died)).group())
    except (AttributeError, ValueError):
        return GateResult(
            name="author_death_classical",
            passed=False,
            severity="soft",
            value=died,
            threshold=min_years_postmortem_hijri,
            message=f"could not parse '{died}' as hijri year",
        )
    # Current hijri ≈ 1447 (2026 CE). Strict-ish.
    current_hijri = 1447
    years_postmortem = current_hijri - died_h
    return GateResult(
        name="author_death_classical",
        passed=years_postmortem >= min_years_postmortem_hijri,
        severity="soft",
        value=years_postmortem,
        threshold=min_years_postmortem_hijri,
        message=(
            f"author d. {died_h} H; {years_postmortem}y postmortem "
            f"(≥{min_years_postmortem_hijri}y required for classical public-domain claim)"
        ),
    )


def gate_min_content_length(artifact: SourceArtifact, min_bytes: int = 1024) -> GateResult:
    """Reject trivially short content (< 1KB) — likely error pages or stubs."""
    return GateResult(
        name="min_content_length",
        passed=artifact.byte_length >= min_bytes,
        severity="hard",
        value=artifact.byte_length,
        threshold=min_bytes,
        message=f"{artifact.byte_length} bytes (≥{min_bytes} required)",
    )


def gate_license_declared(artifact: SourceArtifact) -> GateResult:
    """provenance_fields['license_declaration'] must be present and non-trivial."""
    decl = (artifact.provenance_fields.get("license_declaration") or "").strip()
    ok = bool(decl) and len(decl) >= 30 and decl.lower() not in ("unknown", "nodata")
    return GateResult(
        name="license_declared",
        passed=ok,
        severity="hard",
        value=decl[:80] + ("..." if len(decl) > 80 else ""),
        threshold="non-trivial license_declaration string",
        message=("license declaration present" if ok else "license declaration missing or trivial"),
    )


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

DEFAULT_GATES = [
    gate_sha_present,
    gate_min_content_length,
    gate_arabic_codepoint_ratio,
    gate_license_declared,
    gate_author_death_classical,
]


def run_gates(artifact: SourceArtifact, gates: list = None) -> list[GateResult]:
    """Run all gates on a SourceArtifact; return list of results in run order."""
    return [g(artifact) for g in (gates or DEFAULT_GATES)]


def all_hard_passed(results: list[GateResult]) -> bool:
    """True if every hard-severity gate passed."""
    return all(r.passed for r in results if r.severity == "hard")


def summarize(results: list[GateResult]) -> str:
    """Human-readable summary for manifest / log output."""
    lines = []
    for r in results:
        icon = "✓" if r.passed else "✗"
        sev = r.severity.upper()[0]  # "H" or "S"
        lines.append(f"  [{icon} {sev}] {r.name}: {r.message}")
    return "\n".join(lines)
