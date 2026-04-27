# ARCH-AL-BAYAN-ENCODER-EVAL — BGE-M3 vs jina-v3 measurement plan

**Status:** Spec authored 2026-04-28. Measurement execution + result codification pending.
**Parent:** CAI-RESP-094 mandatory follow-up filing #2.
**Owner:** cc-scholar (author + execute).
**Gate:** Result codified as strategic_decisions row BEFORE backfill kickoff per CAI-RESP-094.
**Target:** within 1 week (2026-05-05).

## Goal

Measure two self-host candidate multilingual embedding models on a 30/30/30 Arabic / Bahasa / English query set against the Quran corpus. Pick the winner if delta ≥ 3 MTEB-multilingual-equivalent points; otherwise default to BGE-M3 per CAI-RESP-094.

## Models under test

| Model | Source | Dimension | Context window | License | Notes |
|---|---|---|---|---|---|
| **BGE-M3** | BAAI/bge-m3 (HuggingFace) | 1024 | 8192 tokens | MIT | CAI default; multi-functional (dense + sparse + colbert); strong multilingual MTEB |
| **jina-embeddings-v3** | jinaai/jina-embeddings-v3 (HuggingFace) | 1024 | 8192 tokens | CC BY-NC 4.0 | Top MTEB multilingual leader as of 2025-Q4; LoRA task-adaptable |

Both runnable on Mac Mini MLX/MPS (M-series) with quantization (~2-4 GB resident); both runnable on Modal CPU/GPU containers.

**License consideration:** jina-v3 is CC BY-NC (non-commercial) — incompatible with Al-Bayān as a waqf/non-commercial-output product, BUT the model use itself is for inference inside our own infrastructure. Verify with the AGPL+conscience-clause framing of WAQFTOOL-01 — if Al-Bayān's outputs are non-commercial-licensed (waqf), CC BY-NC dependency is consistent. Flag for review if CC BY-NC's "non-commercial" definition prohibits any monetized API tier (which W-2 monetisation contemplates).

## Query corpus

90 queries total: 30 each Arabic / Bahasa Indonesia / English. Curated to test the failure modes the FTS-only judge is structurally blind to (per CAI-RESP-094 Q10 reasoning):

### Arabic (30) — diacritic + morphological collapse + classical-vs-colloquial

- 10 classical theological queries (`ما هو التوكل`, `معنى الصبر في القرآن`, etc.)
- 10 colloquial spiritual queries (`كيف أتغلب على الحزن`, `الدعاء عند الكرب`)
- 10 specific-citation queries (`آية الكرسي`, `السورة التي تذكر يوم القيامة`, ayah-by-attribute)

### Bahasa Indonesia / Melayu (30) — Singapore + Indonesian user base

- 10 doctrinal (`apakah riba dalam Islam`, `hukum jual beli online`)
- 10 pastoral (`bagaimana mengatasi kesedihan dengan al-Quran`, `doa untuk orang tua`)
- 10 cross-translation (test queries that map clearly to specific ayat — verify retrieval doesn't wash out under translation)

### English (30) — synonym/paraphrase + conceptual + Western framing

- 10 synonym tests (`endurance` should retrieve sabr ayat; `gratitude` → shukr; `compassion` → rahma)
- 10 conceptual tests (`what does Islam say about social media addiction`, `verses about feeling lost`)
- 10 Western-framing tests (`mental health and Islam`, `existential anxiety in Quran`) — semantic-only retrieval territory

For each query, the gold-set entry has:
- `query` (string)
- `language` (ar/id/en)
- `expected_top_5_ayah_ids` (uuid[]) — human-curated by Musa or paired scholar (INV-7)
- `notes` (rationale for inclusion + classical citation if applicable)

## Metrics

Primary:
- **recall@10** — does any expected ayah appear in top-10 results
- **MRR@10** (mean reciprocal rank) — how high is the first expected ayah
- **precision@5** — proportion of top-5 that are in the expected set

Secondary:
- **latency p50/p99** — query encoding + index search; on Mac Mini MLX vs Modal GPU
- **memory footprint** — resident model + index
- **cold-start vs warm-start** difference (for orchestrator boot warming policy)

Per language slice + overall.

## Switching threshold

Per CAI-RESP-094: "default candidate BGE-M3; alternative jina-embeddings-v3 if measured **≥3 MTEB-multilingual points better** on Arabic+Bahasa+English averaged across the augmented gold-set."

Operational interpretation: `(jina_avg_recall@10 - bge_avg_recall@10) * 100 ≥ 3` averaged across the three language slices.

If delta < 3 points → default BGE-M3 (license-clean MIT, no CC BY-NC complication).
If delta ≥ 3 points → review CC BY-NC license constraint vs Al-Bayān monetisation model. If clear → adopt jina-v3. If conflict → BGE-M3 anyway and document the trade.

## Execution plan

### Day 1-2: scaffold

1. `scripts/encoder_eval/` directory in ai-scholar
2. `scripts/encoder_eval/build_corpus.py` — pulls 6,236 ayat + tafsir from Supabase, builds source-text per EMBED_PIPELINE_v02 §source-text-shape (single-vector concat, ~4K token cap)
3. `scripts/encoder_eval/embed_corpus.py {model}` — embeds the corpus locally with the chosen model (HF Transformers + MLX backend on Mac Mini, or Modal container fallback). Saves `embeddings_{model}_{sha}.npy` + `metadata.json`
4. `scripts/encoder_eval/build_gold_set.py` — interactive CLI for Musa to curate 90-query gold set; writes to `evals/encoder_eval_gold_set.json`

### Day 3-4: measurement

5. `scripts/encoder_eval/measure.py {model} --gold-set evals/encoder_eval_gold_set.json` — runs each query through the model, retrieves top-10 from corpus, computes metrics, writes `evals/encoder_eval_results_{model}.json`
6. Both models scored independently. Both result files committed.

### Day 5: analysis + filing

7. `scripts/encoder_eval/compare.py` — produces a comparison report (markdown, committed) with per-language deltas + significance commentary
8. File completion strategic_decisions row updating ARCH-AL-BAYAN-ENCODER-EVAL with: chosen model, recall/MRR/precision tables, latency/memory data, license review outcome

### Day 6-7: buffer for re-runs

If gold-set has issues (Musa flags ambiguous cases), re-curate + re-measure.

## Hosting plan (deferred but flagged)

CAI-RESP-094 specified Mac Mini MLX/MPS primary + Modal fallback. Operational reality flagged in clarification message to CAI: cc-orchestrator hasn't yet provisioned ML-serving infra on Mac Mini. Likely resolution:

- **Measurement** runs locally on cc-scholar's Mac (MLX is general macOS, doesn't depend on cc-orchestrator's setup). Cheap.
- **v0.2 production hosting** likely Modal-first with Mac Mini migration scheduled for v0.2.5. Self-host commitment preserved; just split across two milestones rather than one.
- This split is what the clarification message asks CAI to confirm.

## What this doc does NOT do

- Doesn't pre-commit which model wins. Measurement decides.
- Doesn't gate on jina-v3's license — defers to post-measurement review.
- Doesn't ship encoder code. This is the eval plan; production embed pipeline is a separate spec (EMBED_PIPELINE_v02).
- Doesn't author the gold set. Musa (or paired scholar per INV-7) curates with cc-scholar tooling support.

## Acceptance criteria for completion

- 90-query gold set committed to `evals/encoder_eval_gold_set.json`
- Two embedding result files committed
- Comparison report committed
- strategic_decisions row updated with chosen model + measurements + license review
- model card archived to `docs/model-cards/{model}.md`

Then: ARCH-AL-BAYAN-ENCODER-EVAL goes to `status='completed'`, EMBED_PIPELINE_v02 backfill kickoff is unblocked.

## References

- CAI-RESP-094 (this filing's parent)
- EMBED_PIPELINE_v02 (the substrate this measurement gates)
- WAQFTOOL-01 (license/monetisation framing for jina-v3 review)
- VISION-003 INV-2 (no vendor lock-in for waqf products — drives self-host commitment)
- BGE-M3 paper: arxiv.org/abs/2402.03216
- Jina-v3 paper: arxiv.org/abs/2409.10173
- MTEB leaderboard reference: huggingface.co/spaces/mteb/leaderboard
