---
name: tafsir-defense-funnel
description: Use when any code in ai-scholar emits a response to a scholar-class query (Al-Bayān / Al-Mīzān / ask-scholar). Enforces the tafsir-FTS → Claude synthesis funnel, matched_passage overlay, scholar-gate routing, and no-hallucinated-isnad invariant. TRIGGER when editing supabase/functions/ask-scholar/**, scripts/albayan_bot.py, scripts/mizan_bot.py, or anything calling search_tafsir_fts.
---

# Tafsir Defense Funnel

Al-Bayān never lets an LLM speak first on tafsir. The pipeline is **evidence → synthesis**, never **synthesis → post-hoc evidence**. Bypassing the funnel is the INV-7 (scholar-of-record) bypass pattern — CI gate, not warning.

## Hard Invariants

**F-1 — `search_tafsir_fts` executes before any LLM synthesis call.**
For any scholar-class query, `supabase.rpc('search_tafsir_fts', { query, lim })` must return before Claude/Gemma/Haiku is invoked. The LLM synthesizes over retrieved tafsir passages; it does not retrieve.

**F-2 — `matched_passage` is overlaid on every match path.**
Per commit `ca99e3e`, the response shape MUST include `matched_passage` whenever `search_tafsir_fts` returned ≥1 row, regardless of whether the match path is: (a) direct FTS hit, (b) Claude-synthesized-from-FTS-context, (c) fallback-to-translation. If no FTS row, `matched_passage` is explicitly `null` — never omitted from the schema.

**F-3 — Scholar-gate routing on ruling-class queries.**
If the classified query_type (see `4-tier-transparency` skill) is `ruling` (fiqh verdict, halal/haram determination, nikah/talaq/warith opinion), the response MUST be routed through the scholar-gate: either a paired human scholar-of-record (INV-7) responds, or the bot emits the 4-tier-transparency "AI-Generated, no scholar-of-record paired for this ruling class" refusal. No synthesized fatwa ships without a paired scholar.

**F-4 — No hallucinated isnads.**
Per MIZAN-EVAL-001 hallucination axis, any synthesized response mentioning hadith MUST cite isnad/collection/grade from the retrieved corpus, never from model parametric knowledge. Isnad without a corresponding `hadith_entries` row in the retrieval result = hallucination = auto-flag (the `hallucination ≥ 1` auto-flag rule).

**F-5 — Ikhtilaf surfaced, not flattened.**
When retrieval returns tafsir entries from scholars with divergent interpretations (Ibn Kathir vs Al-Sa'di disagree, Shafi'i vs Hanafi ruling differ), the response MUST surface the divergence with scholar attribution. Flattening ikhtilaf into a single "Islam says..." answer is an INV-3 tier collapse.

**F-6 — No private LLM data paths.**
The synthesis call receives only (a) the user query, (b) retrieved corpus rows, (c) explicit system prompt with 4-tier rubric. No prior-conversation state, no user PII beyond a hashed identifier, no training on user queries.

## Required Response Shape

```ts
type ScholarResponse = {
  query_type: "ruling" | "definition" | "biography" | "language-clarification" | "madhhab-identification" | "tafsir" | "other";
  matched_passage: TafsirHit | null;   // F-2: always present, null if no FTS hit
  tier: "quoted" | "paraphrased" | "inferred" | "ai-generated";  // 4-tier-transparency
  scholar_of_record: string | null;     // F-3: null if AI-generated, named if scholar-paired
  body: string;                         // The response text
  ikhtilaf: ScholarDivergence[] | null; // F-5: surfaced when retrieval returned ≥2 divergent scholars
  action_prompt: string | null;         // INV-6 — required iff query_type == "ruling"
  audit: { retrieval_ids: string[]; judge_run_id?: string };
};
```

## Validation

`scripts/validate_tafsir_defense_funnel.sh` greps the edge function and bot adapters to confirm:
- Every file under `supabase/functions/ask-scholar/` or `scripts/*_bot.py` that calls an LLM (anthropic/openai/google SDK) must call `search_tafsir_fts` earlier in the same function.
- Every response-shaping function assigns `matched_passage` (never omits the key).

Run: `bash scripts/validate_tafsir_defense_funnel.sh`. CI fails on violation.

## Worked Example

```ts
// ✅ Correct: retrieval → synthesis → response
const hits = await supabase.rpc("search_tafsir_fts", { query, lim: 5 });
const matched_passage = hits.data?.[0] ?? null;
const claude_body = await synthesize(query, hits.data);
return { query_type, matched_passage, tier: "inferred", scholar_of_record: null, body: claude_body, ... };

// ❌ Violation: LLM called before retrieval
const claude_body = await claude.messages.create({ ... });
const hits = await supabase.rpc("search_tafsir_fts", { query });  // too late — funnel bypassed
```

## References

- `supabase/functions/ask-scholar/index.ts` — canonical pipeline implementation
- `supabase/migrations/20260419_001_search_tafsir_fts.sql` — RPC + GIN index
- Commit `ca99e3e` — matched_passage overlay on all match paths
- CAI decisions: CAI-RESP-045 (tafsir-FTS funnel accepted), CAI-RESP-062 (retract-block + F-3 routing), VISION-003 (INV-3/INV-6/INV-7)
