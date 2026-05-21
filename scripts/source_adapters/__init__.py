"""Ihsan-grade ingestion-pipeline source adapters.

Each adapter returns a SourceArtifact (defined here) with normalized shape so
the pipeline orchestrator (scripts/ingest_pipeline.py) can run authenticity
gates + cross-attestation + manifest generation uniformly across substrates.
"""
import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceArtifact:
    """Normalized output of a source adapter run.

    `content` is the verbatim text as extracted from the source (raw, before
    pipeline-side normalization). `metadata` captures everything the adapter
    knows about provenance (URL, edition, author, license). `provenance_fields`
    is the pre-shaped dict the pipeline will write to ingestion_provenance —
    keeps the adapter responsible for source-specific provenance shaping
    while the pipeline owns the DB layer.
    """
    adapter_name: str              # "openiti" / "archive_org" / "pdf_ocr" / "webfetch"
    source_url: str                # canonical fetchable URL or git+ref
    content: str                   # raw extracted text
    metadata: dict = field(default_factory=dict)
    provenance_fields: dict = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        """SHA-256 of NFC-normalized content. Stable across re-runs."""
        normalized = unicodedata.normalize("NFC", self.content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @property
    def byte_length(self) -> int:
        return len(self.content.encode("utf-8"))

    def content_preview(self, n: int = 400) -> str:
        """First N chars for manifest preview / operator review."""
        return self.content[:n]
