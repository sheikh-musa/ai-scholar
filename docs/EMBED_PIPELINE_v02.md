# Embedding Pipeline — v0.2 Retrieval Architecture (Layer 2)

**Status:** Design draft. Filed to cai for adversarial review. NO code ships from this doc.
**Author:** cc-scholar
**Date:** 2026-04-28
**Parent context:** "alim-grade architecture" framing 2026-04-28 conversation; v4-tag-run halt; VISION-003 INV-3 (4-tier transparency), INV-7 (scholar pairing), INV-8 (audit substrate). This is the *Layer 2* from the 8-layer scaffold ("alim-grade" requires Layers 1-8; this doc only delivers L2).

## Why this doc exists

Topic tags are at retrieval-ceiling for the bot's user-interaction shape. Adding embeddings as the primary semantic-recall surface, with the existing `search_tafsir_fts` (FTS) as the exact-match floor, lifts that ceiling. The pipeline is hybrid by design — FTS catches proper-noun/Arabic-specific queries; embeddings catch synonym/paraphrase/conceptual queries; reciprocal rank fusion (RRF) merges; existing Opus reranker top-5s.

This is **not** an alim-grade upgrade. It's foundational substrate that L3-L7 sit on. Calling it more would be the failure mode VISION-003 inverts.

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

## Vendor choice (this is the most contested decision)

| Option | Dimension | Cost | Multilingual Arabic | Vendor relationship | Amanah implication |
|---|---|---|---|---|---|
| **voyage-3-large (Anthropic-owned Voyage AI)** | 1024 | ~$0.18/M tokens | SOTA on Arabic per MTEB | Same family as existing Anthropic dependency | Sending Quran corpus to vendor — see open question 1 |
| OpenAI text-embedding-3-large | 3072 | ~$0.13/M tokens | Good but English-leaning | New vendor (OpenAI) | Same amanah concern + new vendor |
| Cohere embed-multilingual-v3.0 | 1024 | ~$0.10/M tokens | Native multilingual design | New vendor (Cohere) | Same |
| Self-host BGE-multilingual-gemma2 | 4096 | ~$0 (compute only) | Strong | None (open weights) | Amanah-pure; needs GPU + ops |
| Self-host CAMeL-BERT | 768 | ~$0 | Arabic-specialized but smaller | None | Amanah-pure |

**My v0.2 recommendation (open to challenge):** **voyage-3-large** with documented self-hosting migration path for v0.3.

Reasoning:
- Anthropic/Voyage relationship already in scope; doesn't add a new vendor
- Best Arabic+English semantic quality among vendor options
- 1024d index is small (25 MB total for 6,236 ayat) — efficient
- One-time embedding cost ~$0.56; per-query <$0.00002. Cost is essentially noise.
- Self-host migration when a paired scholar-of-record (INV-7) considers it required for amanah

**Counter-argument I want cai to test:** sending Quran + tafsir corpus to ANY vendor API — even one zero-retention contracted — touches the amanah of the data. The corpus is publicly available, but the *embedding signature* of how we structure inference over it is product IP. Worth the cost of self-hosting from day one?

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

## Migration plan

**Phase A — embed (no traffic switching)**
1. Apply migration `20260428_004_ayah_embeddings.sql`.
2. Run `scripts/embed_ayat.py` to backfill all 6,236 — ~$0.67 + ~30min wall-clock.
3. Verify: `SELECT count(*) FROM ayah_embeddings WHERE embedding IS NOT NULL` = 6236.
4. Spot-check a few queries via `search_ayat_semantic` RPC manually.

**Phase B — wire (parallel surface, no behavior change)**
1. Add `embedViaVoyage` + RRF helpers to `_shared/`.
2. In `ask-scholar/index.ts`, call both surfaces, RRF, log both rank-lists to a debug field but RETURN existing FTS-only result. Validates fusion is producing sensible candidates without changing user-facing behavior.
3. Compare on a sample of 100 historical queries (replay against `mizan_interactions`): does fused top-5 differ materially from FTS-only top-5? Where?

**Phase C — cutover**
1. After 1-2 weeks of dual-mode validation + visual-spot-check by cc-scholar (and ideally first scholar-of-record once paired), switch primary retrieval to fused result.
2. Demote `topic_tags` from retrieval pipeline. Keep column; reuse for facet UI.
3. Document the cutover in mizan_interactions audit (prompt_version bump).

**Phase D — extend (out of v0.2 scope)**
- Apply same pipeline to hadith corpus (separate `hadith_embeddings` table).
- Multi-vector per ayah if recall on long-tail queries underperforms.
- Self-host the embedding model.

---

## Open questions for cai (adversarial review)

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
