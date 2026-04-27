# Embedding Pipeline — v0.2 Retrieval Architecture (system_layer L2)

**Status:** Design ratified. CAI-RESP-094 + CAI-RESP-095 + AL-BAYAN-003 amendments applied 2026-04-28. NO code ships until ENCODER-EVAL completes + Modal privacy gate verified.
**Author:** cc-scholar
**Date:** 2026-04-28 (amendments 2026-04-28T16:30 UTC)
**Parent context:** "alim-grade architecture" framing 2026-04-28 conversation; v4-tag-run halt; VISION-003 INV-3 (4-tier transparency), INV-7 (scholar pairing), INV-8 (audit substrate). This is *system_layer L2* from the engineering scaffold (per `/docs/LAYERING.md`); "alim-grade" requires system_layer L1-L8 plus content_layer maturity; this doc only delivers system_layer L2 retrieval substrate.

## Amendments since initial draft

- **2026-04-28 CAI-RESP-094 (id 562)**: vendor rejection (no Voyage-3-large), self-host BGE-M3 default with jina-v3 challenger, Q10 hard gate on retract-unlock, AL-BAYAN-002 topic-tag demote (separate filing).
- **2026-04-28 CAI-RESP-095 (id 567)**: Modal-first hosting for v0.2 with 5-check privacy verification gate, MIZAN-JUDGE-SHADOW-001 sequencing-first, AL-BAYAN-002 judge-consumption non-deciding-factor bound.
- **2026-04-28 AL-BAYAN-003 (id 568)**: scope expansion to include content_layer juridical (Shafi'i fiqh primers Phase 1+2); juridical schema population PARALLEL with Quran backfill; juridical *retrieval activation* gates on Quran retrieval calibration completing.
- **2026-04-28 ARCH-AL-BAYAN-LAYERING-RECONCILE (id 569)**: terminology disambiguation — "L2" → "system_layer L2"; juridical content is content_layer juridical, not "L3."

## Why this doc exists

Topic tags are at retrieval-ceiling for the bot's user-interaction shape. Adding embeddings as the primary semantic-recall surface, with the existing `search_tafsir_fts` (FTS) as the exact-match floor, lifts that ceiling. The pipeline is hybrid by design — FTS catches proper-noun/Arabic-specific queries; embeddings catch synonym/paraphrase/conceptual queries; reciprocal rank fusion (RRF) merges; existing Opus reranker top-5s.

This is **not** an alim-grade upgrade. It's foundational substrate that system_layer L3-L7 sit on. Calling it more would be the failure mode VISION-003 inverts.

## §scope

v0.2 corpus scope (per AL-BAYAN-003 amendment):

| content_layer | v0.2 ingestion | v0.2 retrieval activation |
|---|---|---|
| primary (Quran) | YES (existing 6,236 ayat) | YES — primary user-serving path post-Q10 calibration |
| interpretive (tafsir Ibn Kathir + Al-Sa'di + asbab al-nuzul) | YES (existing) | served via primary retrieval (joined-on-ayah) |
| juridical (Shafi'i: Safīnat, Abī Shujā' Phase 1; Fath al-Mu'īn Phase 2) | YES — schema population PARALLEL with Quran backfill | DEFERRED — gates on Quran retrieval calibrated + retract-gate unlocked |
| connective | partial (mutashabihat live) — deferred to system_layer L3 | partial |

Juridical retrieval activation is a **separate gate** beyond the Q10 sequence — even after Quran retrieval is calibrated and unlocked, juridical layer activation may require its own dual-mode shadow + gold-set per AL-BAYAN-003 gold-set extension.

Hadith corpus deferred to v0.3+ per CAI-RESP-094 Q3 ruling — when ingested, uses same encoder + RRF stack; cross-corpus retrieval policy (when do hadith hits ride alongside Quran in candidate set) is a system_layer L3 knowledge-graph question, NOT raw vector similarity.

---

## Architecture (target state)

```
User query (English or Arabic)
        │
        ├─▶ Embed query (voyage-3-large multilingual)         ← vendor call ~300ms
        │     │
        │     ▼
        │   pgvector cosine search (HNSW)                       ← <50ms p99
        │     │
        │     ▼
        │   Top-50 semantic candidates
        │
        ├─▶ search_tafsir_fts (existing, unchanged)              ← <50ms
        │     │
        │     ▼
        │   Top-50 lexical candidates
        │
        └─▶ Reciprocal Rank Fusion (k=60, literature default)
                │
                ▼
            Top-15 fused candidates
                │
                ▼
        Existing Opus rerank + 4-tier-transparency shape
                │
                ▼
        Top-5 to user, persisted to mizan_interactions + ruling_audit_log
```

Topic tags **demote from retrieval-grounding to faceted-discovery surface** — used for "browse by theme" UI, not query-time matching.

---

## Schema

```sql
-- Migration: 20260428_004_ayah_embeddings.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE ayah_embeddings (
  ayah_id              uuid PRIMARY KEY REFERENCES ayat(id) ON DELETE CASCADE,
  embedding            vector(1024),                  -- voyage-3-large dimension
  embedding_model      text NOT NULL,                 -- 'voyage-3-large@2026-04-28' (versioned)
  embedded_source_hash text NOT NULL,                 -- SHA-256 of source text used; re-embed if hash changes
  source_token_count   integer NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ayah_embeddings_hnsw_cosine
  ON ayah_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

ALTER TABLE ayah_embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY ayah_embeddings_read ON ayah_embeddings FOR SELECT TO anon, authenticated USING (true);
-- service_role only writes
```

**Source text shape per ayah (single embedding, concat with cap):**

```
Quran ayah {surah_name} ({surah}:{ayah})
Arabic: {arabic_text}
English: {english_translation}
Tafsir Ibn Kathir: {ibn_kathir_text[:1500]}
Tafsir Al-Sa'di: {al_sadi_text[:1500]}
Asbab al-Nuzul: {asbab_text[:500] if present}
Topic themes: {top-8 existing topic_tags joined}
```

Cap at ~4000 tokens per source (voyage-3 supports 32K but quality degrades with length-bloat).

---

## §hosting-privacy (CAI-RESP-095 (A) mandatory pre-backfill gate)

Hosting target: **Modal-first for v0.2** (Mac Mini → v0.2.5 milestone, separate filing). Modal is owned-container-on-managed-compute (our container, our weights pinned, our SHA in vector_metadata, our code, our data flow) — distinct from vendor-inference-API (Voyage rejected unconditionally). Same posture as self-hosted-on-AWS-EC2.

Five privacy verification checks REQUIRED BEFORE backfill kickoff per CAI-RESP-095 (A) constraint 2:

1. **Query-payload logging.** Modal default behavior on logging request bodies / stdout / stderr. If any of those captures query payloads → DISABLE (env config or container-level redaction).
2. **Operator access boundary.** Modal operator access to container memory + filesystem in normal operation vs break-glass scenarios. Document what's accessible to whom under what conditions.
3. **Container data residency.** Cross-region container scheduling — flag any jurisdictions with mandatory-disclosure regimes problematic for Muslim-user query data. Pin region if needed.
4. **Encryption-at-rest** for any persisted state. We don't intend to persist queries — verify the default and confirm.
5. **Scale-to-zero in-memory state termination.** When container goes idle and Modal terminates the instance, what happens to anything held in RAM. Confirm no leak through warm-pool or snapshot mechanism.

**Pre-execution checklist:** see `docs/MODAL_PRIVACY_VERIFICATION.md` (separate doc).

If any check returns a blocker → file `ARCH-AL-BAYAN-MODAL-PRIVACY-001` and PAUSE backfill. Managed compute is not managed amanah until verified — fatabayyanu applies to cloud substrate.

## Vendor choice (this is the most contested decision)

**Final ruling per CAI-RESP-094 + CAI-RESP-095:** self-host from day one, Modal-first hosting, BGE-M3 default with jina-v3 challenger pending ARCH-AL-BAYAN-ENCODER-EVAL measurement (see `docs/ARCH_AL_BAYAN_ENCODER_EVAL.md`). Vendor inference APIs (Voyage, OpenAI, Cohere) all rejected unconditionally — the rejection is about the inference path, not hosting choice. Modal containers running our weights = self-host. Voyage = vendor inference. Bright-line distinction.

| Option | Dimension | License | Status |
|---|---|---|---|
| **BGE-M3** (BAAI/bge-m3) | 1024 | MIT | Default per CAI-RESP-094 — wins unless ENCODER-EVAL shows jina-v3 ≥3 MTEB-multilingual points better |
| jina-embeddings-v3 (jinaai/jina-embeddings-v3) | 1024 | CC BY-NC 4.0 | Challenger; license review required if it wins (vs WAQFTOOL-01 monetisation model) |
| ~~voyage-3-large~~ | ~~1024~~ | — | **REJECTED** unconditionally per CAI-RESP-094 Q1 (vendor inference API on global Muslim query stream) |
| ~~OpenAI text-embedding-3~~ | — | — | **REJECTED** (same reason) |
| ~~Cohere embed-multilingual-v3~~ | — | — | **REJECTED** (same reason) |

Measurement plan in `docs/ARCH_AL_BAYAN_ENCODER_EVAL.md`. Result codified as strategic_decisions row before backfill kickoff.

---

## Embedding-source decision

**v0.2: single embedding per ayah, concat all sources, cap 4K tokens.**

Alternatives considered:
- *Multi-embedding per ayah* (separate vectors for Arabic / translation / each tafsir): 4-6× storage; query would need to merge across them — more complex; recall improvement marginal at v0.2 corpus size (~6K ayat).
- *Per-tafsir-entry embeddings* (so each Ibn Kathir entry, each Al-Sa'di entry separately indexed): finer-grained but loses ayah-level coherence. Better for "find a passage" not "find a verse."
- *Hierarchical*: embed ayah-text + each tafsir-entry separately, retrieve from both, merge. Closest to "best." Adds significant complexity. Defer to v0.3.

For v0.2: simplest baseline that ships. Single vector per ayah, joined with all sources concatenated.

---

## Retrieval RPC

```sql
CREATE OR REPLACE FUNCTION search_ayat_semantic(
  query_embedding vector(1024),
  lim int DEFAULT 10,
  threshold float DEFAULT 0.0
)
RETURNS TABLE (
  ayah_id              uuid,
  surah_number         int,
  ayah_number          int,
  arabic_text          text,
  english_translation  text,
  similarity           real
)
LANGUAGE sql STABLE AS $$
  SELECT a.id, a.surah_number, a.ayah_number, a.arabic_text, a.english_translation,
         1 - (e.embedding <=> query_embedding) AS similarity
    FROM ayat a
    JOIN ayah_embeddings e ON e.ayah_id = a.id
   WHERE 1 - (e.embedding <=> query_embedding) > threshold
   ORDER BY e.embedding <=> query_embedding
   LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION search_ayat_semantic(vector, int, float) TO anon, authenticated;
```

---

## Reciprocal Rank Fusion

Both result sets ranked. RRF score per candidate:
```
rrf_score(d) = sum over result_lists of  1 / (k + rank(d in list))
```
where `k=60` (literature default; see Cormack et al. 2009).

Implementation in `ask-scholar/index.ts` as a small helper:
```ts
function rrf(ranklists: Array<Array<{id: string}>>, k = 60): Map<string, number> {
  const scores = new Map<string, number>();
  for (const list of ranklists) {
    list.forEach((item, idx) => {
      scores.set(item.id, (scores.get(item.id) ?? 0) + 1 / (k + idx + 1));
    });
  }
  return scores;
}
```

---

## Wiring into ask-scholar Edge Function

```ts
// ask-scholar/index.ts (changes shown ~)
const queryEmbedding = await embedViaVoyage(rawQuery);                            // NEW
const semanticHits = await supabase.rpc("search_ayat_semantic", { query_embedding: queryEmbedding, lim: 50 });  // NEW

const ftsHits = await supabase.rpc("search_tafsir_fts", { query: keywordsJoined, lim: 50 });  // EXISTING

const fused = rrf([semanticHits.data, ftsHits.data], 60);
const top15 = Array.from(fused.entries()).sort((a,b) => b[1] - a[1]).slice(0, 15);

// Existing tafsir-defense-funnel F-1 invariant: search_tafsir_fts must run before LLM. ✓
// Existing matched_passage F-2 overlay still applies — pull from FTS leg

// Hand to existing rerank + format
```

Embedding fetch (small new helper):
```ts
async function embedViaVoyage(text: string): Promise<number[]> {
  const resp = await fetch("https://api.voyageai.com/v1/embeddings", {
    method: "POST",
    headers: { "Authorization": `Bearer ${VOYAGE_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ input: text, model: "voyage-3-large", input_type: "query" }),
  });
  const json = await resp.json();
  return json.data[0].embedding;
}
```

`input_type: "query"` vs `"document"` — Voyage uses asymmetric encoding. Documents (ayat) embedded with `"document"`; queries with `"query"`. Same model, different prompt.

---

## Cost analysis

| Phase | Calculation | Cost |
|---|---|---|
| Initial backfill | 6,236 ayat × ~600 tokens avg × $0.18/M | ~$0.67 one-time |
| Per query (embed) | 1 × 50-200 tokens × $0.18/M | ~$0.00002 |
| Per query (DB) | HNSW search + RPC | $0 (Supabase compute) |
| Storage | 6,236 × 1024 × 4 bytes | ~25 MB (trivial) |
| Re-embed on source change | rare; per-affected-ayah | <$0.001/event |

Per-query latency budget breakdown:
- Vendor API embed: ~300-500ms p99 (Voyage US-East)
- HNSW search: <50ms p99
- FTS search: <50ms p99 (existing)
- RRF: <5ms (in-process)
- Reranker: ~2-5s (existing Opus call)
- **Total added by embedding layer: ~400ms** on the request path (parallelizable with FTS, so net add ~200-400ms)

For Telegram bot UX (typing indicator already covers seconds of latency), this is fine. For future web/mobile UX, may want pre-cached embeddings of common queries.

---

## §migration-plan

Order locked per CAI-RESP-095 (B); no step skipped, no step bundled out of order:

**Phase 0 — sequencing prerequisites (must complete BEFORE Phase A backfill kickoff)**

1. Apply migration `20260428_005_mizan_judge_shadow.sql` (MIZAN-JUDGE-SHADOW-001) standalone — destination for shadow-mode judge runs must exist before fused retrieval ships.
2. Complete `ARCH-AL-BAYAN-ENCODER-EVAL` measurement (BGE-M3 vs jina-v3 on 30/30/30 multilingual gold-set). Result codified as strategic_decisions row.
3. Complete Modal privacy verification (5 checks per `§hosting-privacy`). If any blocker → file `ARCH-AL-BAYAN-MODAL-PRIVACY-001` and PAUSE.
4. Apply migration `20260428_006_ayah_embeddings.sql` (renumbered from -004; pgvector + ayah_embeddings + RLS).

**Phase A — backfill (winning encoder, no user-traffic change)**

5. Deploy Modal serverless container running winning encoder.
6. Run `scripts/embed_ayat.py` — backfill all 6,236 ayat embeddings. Track encoder_sha + corpus_version per row.
7. Verify: `SELECT count(*) FROM ayah_embeddings WHERE embedding IS NOT NULL` = 6236.
8. Spot-check via `search_ayat_semantic` RPC.
9. **PARALLEL TRACK (per AL-BAYAN-003):** ingest content_layer juridical Phase 1 sources (Safīnat + Matn Abī Shujā'). Schema population only — do NOT activate juridical retrieval.

**Phase B — shadow mode (per Q10 hard gate)**

10. Add `embedViaModal` + RRF helpers to `_shared/`.
11. In `ask-scholar/index.ts`, call both retrieval surfaces (FTS in parallel with semantic), RRF in-process. **Log fused candidate set to `mizan_judge_shadow` table but RETURN existing FTS-only result.** No user-visible behavior change.
12. mizan_judge runs over fused candidate set in shadow mode. Outputs to `mizan_judge_shadow` with `retrieval_mode='fused_rrf'`.
13. 1-2 week shadow accumulation window — collect diff data.

**Phase C — recalibration (Q10 step iv-v)**

14. Diff audit: where does shadow judge approve/reject differ from production FTS-only judge? Categorize divergences.
15. Augment gold-set with 50-150 semantic-only Quran items + 30-50 semantic-only juridical items per AL-BAYAN-003 — total 80-200 items, **human-labeled** (Musa Phase 1; L7 scholar Phase 2 once paired). LLM-generated gold REJECTED.
16. Recalibrate retract threshold preserving precision floor. Don't trade false-rejection safety for recall.

**Phase D — Quran retrieval cutover (Q10 step vi-vii)**

17. Unlock retract-gate (calibration meets thresholds).
18. Cutover fused Quran retrieval to primary user-serving path. Bump `prompt_version` on mizan_interactions for audit.
19. Demote `topic_tags` from retrieval pipeline (per AL-BAYAN-002). Keep column for facet UI; bounded judge cross-check still permitted (≤ 0.2 weight, non-deciding factor).

**Phase E — content_layer juridical retrieval activation (per AL-BAYAN-003 separate gate)**

20. After Phase D verified in production ≥1 week, run separate dual-mode + augmented gold-set for juridical retrieval.
21. Cutover juridical retrieval to primary surface for fiqh-class queries. Citation-rendering rule (AL-BAYAN-003) enforced at response shape.
22. dalil_strength tier never escalated to `binding_fatwa` — that requires L7.

**Phase F — extend (out of v0.2 scope, deferred to v0.3+)**

- Hadith corpus into separate `hadith_embeddings` table; cross-corpus fusion via system_layer L3 knowledge graph (not raw vector similarity).
- Mac Mini MLX/MPS deployment swap (file as `MAC-MINI-MIGRATION-001` when v0.2.5 scoped, after v0.2 in production ≥2 weeks).
- Multi-vector per ayah if recall@10 < 0.85 on augmented gold-set.
- Hanafi/Mālikī/Ḥanbalī juridical content (schema-supported now; content separate filings).

---

## Resolved questions (post-CAI-RESP-094 + CAI-RESP-095)

All 10 open questions from initial draft now resolved. Summary:

| # | Question | Ruling | Reference |
|---|---|---|---|
| 1 | Vendor amanah (Voyage) | REJECTED unconditionally; self-host BGE-M3 default; Modal-first for v0.2 with 5-check privacy gate | CAI-RESP-094 + CAI-RESP-095 (A) |
| 2 | Single vs multi-vector | Single at v0.2; reopen if recall@10 < 0.85 on augmented gold-set | CAI-RESP-094 |
| 3 | Hadith in same vector space | Quran-only at v0.2 + AL-BAYAN-003 juridical; hadith deferred to v0.3 | CAI-RESP-094 + AL-BAYAN-003 |
| 4 | RRF k-tuning | k=60 default; tune against augmented gold-set in Q10 step (v) | CAI-RESP-094 |
| 5 | Re-embed triggers | tafsir updates / encoder SHA bump / chunking change → full backfill; SHA + corpus_version per row | CAI-RESP-094 |
| 6 | Topic tags fate | Demote to UX facets; bounded judge cross-check (≤0.2 weight, non-deciding factor) | AL-BAYAN-002 (updated) |
| 7 | Multi-language test corpus | Required ≥30 each Arabic / Bahasa / English | CAI-RESP-094 |
| 8 | Latency on bot path | 400ms p99 OK; FTS+semantic MUST run parallel | CAI-RESP-094 |
| 9 | Vendor failure mode | Moot under self-host ruling | CAI-RESP-094 |
| 10 | Judge re-baseline | HARD GATE — sequenced 6-step pipeline; non-negotiable | CAI-RESP-094 + CAI-RESP-095 (B) |

## (legacy section) Original open questions for cai (adversarial review)

These are where I'm genuinely uncertain. Pushback welcome.

1. **Vendor amanah.** Sending Quran + tafsir corpus to Voyage (Anthropic-owned) for embedding — does this violate amanah on the data, or is "publicly-available text + zero-retention contract + Anthropic-family vendor" an acceptable v0.2 posture? Does the answer change if we pair an INV-7 scholar before this ships?
2. **Single vs multi-vector.** Am I under-specifying by going single-vector-per-ayah at v0.2? Recall improvement from multi-vector at 6K-ayah scale is probably marginal but I don't have empirics. Worth running a 50-query A/B on a sample before committing?
3. **Hadith in same vector space?** Currently scoped to ayah-only (`ayah_embeddings`). Should I include hadith in a unified embedding space (`corpus_embeddings`) so semantic queries cross ayah↔hadith boundaries? Or is ayah-and-hadith separation an INV-3 tier-clarity property worth preserving (different output_tier, different scholar-gate routing)?
4. **RRF k parameter.** `k=60` is literature default. Does that fit our top-15 final-result-size? Sensitivity test would show, but I don't want to over-engineer.
5. **Re-embedding triggers.** The `embedded_source_hash` re-embed path fires on text changes. But what about new-asbab-data added (which would change the source-text concatenation)? Should every tafsir-corpus update trigger re-embed of all affected ayat?
6. **Topic tags fate.** Demote to facets vs fully retire vs retain for fallback. I lean demote-to-facets because they're visual/discovery affordances, but cc-ihsanos may have a stronger view given cross-repo facet patterns.
7. **Multi-language testing.** Voyage handles Arabic but how do I validate this against actual Mizan-bot Arabic queries? Need a test corpus of Arabic+English query pairs with known-good ayah retrievals. cc-scholar can curate but ideally INV-7 scholar reviews.
8. **Latency on bot path.** ~400ms add is fine for Telegram with typing indicator. For future web/mobile (or a hypothetical Al-Bayān SDK), is this acceptable? Or should we pre-cache embeddings for common queries?
9. **Failure mode of vendor.** If Voyage API is down, does ask-scholar degrade to FTS-only (graceful) or 500 (alert)? Lean: degrade with warning header. But this means asymmetric retrieval quality during outages — does that violate any defense-funnel invariant?
10. **Eval pipeline integration.** The mizan_judge pipeline (Phase 1 batch + calibrate) was designed against the FTS-only retrieval. Does adding semantic recall change the gold-set composition or the judge's baseline expectations? Should we re-baseline the calibration against the new retrieval before unlocking the retract-gate?

---

## What this doc does NOT do

- Doesn't replace search_tafsir_fts (kept as exact-match floor).
- Doesn't claim to be alim-grade work (this is Layer 2 of an 8-layer architecture; alim-grade requires L3-L7).
- Doesn't pre-decide vendor — open question 1 is the real call.
- Doesn't ship code. Migration + Python embed script + Edge Function changes all wait on cai review + Musa direction.
- Doesn't retire topic_tags column (only demotes from retrieval pipeline; column stays for facet use).

## Provenance

- Halts the v4 Ihsan-tag plan (audit results: 1057 KEEP, 1366 RETAG, 3813 EMPTY).
- Aligned with VISION-003 INV-3 (4-tier transparency) — embedding ≠ output, just retrieval substrate.
- Aligned with CAI-PIPELINE-BYPASS-001 — this is design-doc-then-cai-review, not bypass.
- Cost estimates verified against Voyage AI public pricing 2026-04-28.

## References

- VISION-003 (Al-Bayān as bayān, not alim)
- VISION-003 INV-3, INV-7, INV-8
- CAI-MIZAN-EVAL-001 (judge pipeline) + CAI-RESP-062 (retract-gate amendment)
- `supabase/functions/ask-scholar/index.ts`
- `supabase/migrations/20260419_001_search_tafsir_fts.sql`
- Cormack, Clarke, Buettcher (2009) "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
- Voyage AI pricing + model card: https://docs.voyageai.com (verified 2026-04-28)
