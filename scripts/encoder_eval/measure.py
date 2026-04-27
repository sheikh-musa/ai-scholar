#!/usr/bin/env python3
"""
Measure recall@10 / MRR@10 / precision@5 of a model's embeddings against
the gold set.

v0.1 STUB — gates on (a) embed_corpus.py producing real embeddings via
Modal container, (b) build_gold_set.py producing curated 90-query file.

When real: loads embeddings_{model}.npy + corpus metadata, embeds each
gold query, finds top-10 by cosine, scores against expected_top_5_ayah_ids.

Usage:
  python3 scripts/encoder_eval/measure.py {bge-m3|jina-v3}
    [--gold-set evals/encoder_eval_gold_set.json]
    [--out evals/encoder_eval_results_{model}.json]
"""

import json
import sys
from pathlib import Path

VALID_MODELS = {"bge-m3", "jina-v3"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_MODELS:
        sys.exit(f"usage: {sys.argv[0]} {{{' | '.join(VALID_MODELS)}}}")
    model = sys.argv[1]
    gold_path = Path(sys.argv[sys.argv.index("--gold-set") + 1] if "--gold-set" in sys.argv
                     else "evals/encoder_eval_gold_set.json")
    out_path = Path(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
                    else f"evals/encoder_eval_results_{model}.json")

    if not gold_path.exists():
        sys.exit(f"gold set not found: {gold_path} — run build_gold_set.py first")

    gold = json.loads(gold_path.read_text())
    print(f"Model: {model}")
    print(f"Gold set: {len(gold)} queries")
    by_lang = {}
    for r in gold:
        by_lang[r["language"]] = by_lang.get(r["language"], 0) + 1
    for lang, n in sorted(by_lang.items()):
        print(f"  {lang}: {n}")
    print()
    print("STUB — measurement pending real embeddings + Modal endpoint.")
    print()
    print("When ready, this script will:")
    print(f"  1. Load evals/embeddings_{model}.npy + metadata")
    print(f"  2. For each gold query: POST to Modal /embed with input_type='query'")
    print(f"  3. Compute cosine similarity vs corpus embeddings, take top-10")
    print(f"  4. Score: recall@10, MRR@10, precision@5 against expected_top_5_ayah_ids")
    print(f"  5. Per-language slice + overall")
    print(f"  6. Write to {out_path}: {{")
    print(f"       'model': str, 'overall': {{recall_at_10, mrr_at_10, precision_at_5}},")
    print(f"       'by_language': {{...}}, 'per_query': [...] }}")


if __name__ == "__main__":
    main()
