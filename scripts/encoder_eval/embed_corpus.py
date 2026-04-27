#!/usr/bin/env python3
"""
Embed the corpus produced by build_corpus.py with a chosen encoder.

v0.1 STUB — encoder integration deferred until Modal container is up
(per CAI-RESP-095 hosting decision) and BGE-M3 vs jina-v3 measurement
gate is reached. This script produces the structural skeleton so the
measurement workflow has a placeholder to swap real embeddings into.

Real implementation (when Modal container ready):
  - HTTP POST to https://embedder.al-bayan.modal.run/embed
  - Body: {"input_type": "document" | "query", "texts": [...]}
  - Response: {"embeddings": [[...1024 floats...], ...]}
  - Save to evals/embeddings_{model}_{sha}.npy + metadata.json

For now: prints the call shape. Actual measurement work begins after
Modal verification gate clears and at least one encoder is deployed.

Usage:
  python3 scripts/encoder_eval/embed_corpus.py {bge-m3|jina-v3}
    [--corpus evals/encoder_eval_corpus.jsonl]
    [--out evals/embeddings_{model}.npy]
"""

import json
import os
import sys
from pathlib import Path

VALID_MODELS = {"bge-m3", "jina-v3"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_MODELS:
        sys.exit(f"usage: {sys.argv[0]} {{{' | '.join(VALID_MODELS)}}}")
    model = sys.argv[1]
    corpus_path = Path(sys.argv[sys.argv.index("--corpus") + 1] if "--corpus" in sys.argv
                       else "evals/encoder_eval_corpus.jsonl")
    out_path = Path(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
                    else f"evals/embeddings_{model}.npy")

    if not corpus_path.exists():
        sys.exit(f"corpus file not found: {corpus_path} — run build_corpus.py first")

    print(f"Model: {model}")
    print(f"Corpus: {corpus_path}")
    print(f"Output: {out_path}")
    print()
    print("STUB — actual embedding pending Modal container deployment.")
    print()
    print("When ready, this script will:")
    print(f"  1. Read {corpus_path} (one ayah per line)")
    print(f"  2. Batch-POST to Modal endpoint embedder.al-bayan.modal.run/embed")
    print(f"     with input_type='document'")
    print(f"  3. Save resulting (N, 1024) numpy array to {out_path}")
    print(f"  4. Save metadata: {out_path.with_suffix('.json')}")
    print(f"     {{\"model\": \"{model}\", \"encoder_sha\": \"...\", \"corpus_sha\": \"...\",")
    print(f"      \"row_count\": N, \"created_at\": \"...\"}}")
    print()

    # Confirm corpus is parseable + count rows
    n = 0
    total_tokens = 0
    with corpus_path.open() as f:
        for line in f:
            row = json.loads(line)
            n += 1
            total_tokens += row.get("token_count_approx", 0)
    print(f"Corpus stats: {n} ayat, ~{total_tokens:,} total tokens (avg ~{total_tokens // max(n, 1)} per ayah)")


if __name__ == "__main__":
    main()
