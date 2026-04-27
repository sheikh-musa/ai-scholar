#!/usr/bin/env python3
"""
Compare BGE-M3 vs jina-v3 measurement results and produce a markdown
comparison report. Decides whether jina-v3 wins by ≥3 MTEB-multilingual
points (per ARCH-AL-BAYAN-ENCODER-EVAL switch threshold).

Output: docs/encoder-eval-results.md (committed) + console verdict.

Usage:
  python3 scripts/encoder_eval/compare.py
    [--bge evals/encoder_eval_results_bge-m3.json]
    [--jina evals/encoder_eval_results_jina-v3.json]
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone


SWITCH_THRESHOLD_POINTS = 3  # per ARCH-AL-BAYAN-ENCODER-EVAL


def load(path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def main():
    bge_path = Path(sys.argv[sys.argv.index("--bge") + 1] if "--bge" in sys.argv
                    else "evals/encoder_eval_results_bge-m3.json")
    jina_path = Path(sys.argv[sys.argv.index("--jina") + 1] if "--jina" in sys.argv
                     else "evals/encoder_eval_results_jina-v3.json")

    bge = load(bge_path)
    jina = load(jina_path)

    if not bge or not jina:
        sys.exit(f"missing result file(s): bge={bool(bge)} jina={bool(jina)}")

    # Compute average recall@10 across the 3 language slices
    languages = ["ar", "id", "en"]
    bge_avg = sum(bge["by_language"][l]["recall_at_10"] for l in languages) / 3
    jina_avg = sum(jina["by_language"][l]["recall_at_10"] for l in languages) / 3
    delta_points = (jina_avg - bge_avg) * 100

    winner = "jina-v3" if delta_points >= SWITCH_THRESHOLD_POINTS else "bge-m3"
    print(f"BGE-M3 avg recall@10: {bge_avg:.3f}")
    print(f"jina-v3 avg recall@10: {jina_avg:.3f}")
    print(f"Delta: {delta_points:+.2f} points (threshold: {SWITCH_THRESHOLD_POINTS})")
    print(f"WINNER: {winner}")

    # Write markdown report
    report = f"""# ENCODER-EVAL Results — BGE-M3 vs jina-v3

**Generated:** {datetime.now(timezone.utc).isoformat()}
**Switch threshold:** {SWITCH_THRESHOLD_POINTS} points (jina-v3 wins iff delta ≥ {SWITCH_THRESHOLD_POINTS})

## Summary

| Model | avg recall@10 | License |
|---|---|---|
| BGE-M3 | {bge_avg:.3f} | MIT |
| jina-v3 | {jina_avg:.3f} | CC BY-NC 4.0 |
| **Delta** | **{delta_points:+.2f} points** | |

**Winner: {winner}**

## Per-language detail

| Language | BGE-M3 recall@10 | jina-v3 recall@10 | Delta |
|---|---|---|---|
"""
    for l in languages:
        b = bge["by_language"][l]["recall_at_10"]
        j = jina["by_language"][l]["recall_at_10"]
        report += f"| {l} | {b:.3f} | {j:.3f} | {(j-b)*100:+.2f} |\n"

    report += f"""

## Per-language MRR@10 + precision@5

| Language | BGE-M3 MRR / P@5 | jina-v3 MRR / P@5 |
|---|---|---|
"""
    for l in languages:
        b = bge["by_language"][l]
        j = jina["by_language"][l]
        report += f"| {l} | {b.get('mrr_at_10', 0):.3f} / {b.get('precision_at_5', 0):.3f} | {j.get('mrr_at_10', 0):.3f} / {j.get('precision_at_5', 0):.3f} |\n"

    if winner == "jina-v3":
        report += """

## License review (jina-v3 wins)

CC BY-NC 4.0 — non-commercial use only.

Required check vs WAQFTOOL-01 monetisation:
- W-1 rulings never paywalled — non-commercial-output product
- W-2 monetise compute (API, deep-search credits, institutional seats)

If "compute monetisation" counts as commercial use of jina-v3 model, this is a license conflict and we revert to BGE-M3.

**Action required before adoption:** consult intellectual-property advisor on whether internal model use for compute-monetised output service constitutes "commercial use" under CC BY-NC 4.0.
"""
    else:
        report += """

## Decision: BGE-M3

License-clean MIT. No further action needed for adoption.
"""

    out = Path("docs/encoder-eval-results.md")
    out.write_text(report)
    print(f"\nReport written: {out}")


if __name__ == "__main__":
    main()
