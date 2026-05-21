"""Cross-attestation engine.

Given two (or more) SourceArtifacts representing the same underlying work,
compute similarity scores and accept/reject based on threshold. Pure-Python
implementation, no external dependencies — works on million-char Arabic texts
in seconds (token-based, not full Levenshtein).

Similarity dimensions:
  token_jaccard:     |A ∩ B| / |A ∪ B| on diacritic-stripped tokens
  trigram_jaccard:   same but on token-trigrams (catches reordering / substitution)
  length_ratio:      min(|A|,|B|) / max(|A|,|B|) — sanity check for missing volumes

Accept threshold (default):
  token_jaccard ≥ 0.80 AND trigram_jaccard ≥ 0.65 AND length_ratio ≥ 0.85

Below threshold = REJECT (diff written to manifest for operator review).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from collections import Counter

from . import SourceArtifact


_DIACRITIC_RE = re.compile(r"[ً-ٰٟۖ-ۭ]")
_TATWEEL_RE = re.compile(r"ـ+")
_WS_RE = re.compile(r"\s+")
_NON_WORD_AR_RE = re.compile(r"[^؀-ۿݐ-ݿ\w\s]+")


def normalize_for_compare(text: str) -> str:
    """NFC + strip diacritics + strip tatweel + collapse whitespace + lowercase.
    Used uniformly across attestation to make minor orthographic variants align."""
    text = unicodedata.normalize("NFC", text)
    text = _DIACRITIC_RE.sub("", text)
    text = _TATWEEL_RE.sub("", text)
    text = _NON_WORD_AR_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()


def tokenize(text: str) -> list[str]:
    return normalize_for_compare(text).split()


@dataclass
class AttestationResult:
    sources: list[str]                            # source_url list
    token_jaccard: float
    trigram_jaccard: float
    length_ratio: float
    passed: bool
    threshold_token: float
    threshold_trigram: float
    threshold_length: float
    sample_diffs: dict = field(default_factory=dict)   # {"only_in_a": [...], "only_in_b": [...]}
    notes: str = ""

    def to_jsonable(self) -> dict:
        return {
            "sources": self.sources,
            "token_jaccard": round(self.token_jaccard, 4),
            "trigram_jaccard": round(self.trigram_jaccard, 4),
            "length_ratio": round(self.length_ratio, 4),
            "passed": self.passed,
            "thresholds": {
                "token": self.threshold_token,
                "trigram": self.threshold_trigram,
                "length": self.threshold_length,
            },
            "sample_diffs": self.sample_diffs,
            "notes": self.notes,
        }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cross_attest(
    artifact_a: SourceArtifact,
    artifact_b: SourceArtifact,
    threshold_token: float = 0.80,
    threshold_trigram: float = 0.65,
    threshold_length: float = 0.85,
    sample_diff_n: int = 8,
) -> AttestationResult:
    """Pairwise attestation between two SourceArtifacts.

    Returns AttestationResult with all metrics + sample diffs. Pass requires
    ALL three metrics to clear their thresholds.
    """
    tokens_a = tokenize(artifact_a.content)
    tokens_b = tokenize(artifact_b.content)

    set_a, set_b = set(tokens_a), set(tokens_b)
    token_j = _jaccard(set_a, set_b)

    # Token trigrams for sequence-aware comparison
    def trigrams(tokens: list[str]) -> set:
        return {tuple(tokens[i:i+3]) for i in range(len(tokens) - 2)} if len(tokens) >= 3 else set()

    trig_a, trig_b = trigrams(tokens_a), trigrams(tokens_b)
    trigram_j = _jaccard(trig_a, trig_b)

    len_a, len_b = len(tokens_a), len(tokens_b)
    length_r = min(len_a, len_b) / max(len_a, len_b) if max(len_a, len_b) > 0 else 1.0

    # Top-N tokens uniquely present in each (frequency-ordered)
    counter_a, counter_b = Counter(tokens_a), Counter(tokens_b)
    only_a = [t for t, _ in counter_a.most_common() if t not in set_b][:sample_diff_n]
    only_b = [t for t, _ in counter_b.most_common() if t not in set_a][:sample_diff_n]

    passed = (
        token_j >= threshold_token
        and trigram_j >= threshold_trigram
        and length_r >= threshold_length
    )

    return AttestationResult(
        sources=[artifact_a.source_url, artifact_b.source_url],
        token_jaccard=token_j,
        trigram_jaccard=trigram_j,
        length_ratio=length_r,
        passed=passed,
        threshold_token=threshold_token,
        threshold_trigram=threshold_trigram,
        threshold_length=threshold_length,
        sample_diffs={"only_in_first": only_a, "only_in_second": only_b},
        notes=(
            f"tokens: {len_a}/{len_b}; "
            f"trigrams: {len(trig_a)}/{len(trig_b)}; "
            f"{'PASS' if passed else 'REJECT'} attestation"
        ),
    )
