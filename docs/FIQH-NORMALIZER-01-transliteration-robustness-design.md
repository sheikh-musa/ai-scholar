# FIQH-NORMALIZER-01 — General transliteration-robustness for fiqh retrieval

**Author:** cc-scholar · **Date:** 2026-09-16 · **For:** orch-console code-gate (design → gate → build+wet-prove → deploy)
**Origin:** Musa op#20470 / bus #40129 item 2 — *"we can't add every spelling variation of every word — we need a better system."*
**Status:** DESIGN — recommendation for review. No build until gated.

## 1. Problem

Fiqh retrieval currently anchors transliterated Arabic terms to English via a hand-maintained dict, `fiqh_semantic.QUERY_EXPANSIONS` (~90 entries). It does two jobs at once:

1. **Spelling robustness** — map every romanization of a term to one form (`wudu`, `wudhu`, `wuduu`, `wuzu`, `wuḍūʾ` → ablution).
2. **Semantic anchoring** — append an English/Arabic gloss so bge-m3 centroids onto the right chapter (bare `wudhu` scores 0.44 and falls under the 0.50 gate; anchored it clears it).

This does not scale: each new term needs its spellings enumerated by hand (the op#20455 wudhu miss was exactly a missing spelling), and it never covers Malay/Urdu/Indonesian loanword variants or novel terms. Musa's directive: **replace the per-word list with a general system.**

## 2. Why bge-m3 alone is not enough

Empirically (this corpus, live encoder): single-vector bge-m3 does **not** bridge a bare transliterated term to its English matn. `wudhu…` tops out at 0.44 cosine; the same query with an ablution-vocabulary anchor reaches 0.69–0.75. So "just trust the multilingual model" (drop anchoring entirely) regresses recall. Any replacement must still supply a semantic anchor — the question is how to generate it generally instead of by hand.

## 3. Options considered

| # | Approach | Removes hand-list? | Latency / cost | Determinism / audit | Coverage |
|---|----------|:---:|---|---|---|
| A | **LLM query-normalizer** (Haiku via CLI): rewrite query → canonical term + Arabic script + English gloss, then embed | ✅ | +~1s/query (Max-plan, no per-call $) | non-deterministic → must log normalized query to `retrieval_meta` | any spelling, code-switch, novel terms |
| B | **Deterministic transliteration-fold + compact concept-lexicon** (fold digraphs/diacritics/doubles → key; lexicon keyed on FOLDED form) | ✅ (list shrinks to 1 entry/concept) | ~0 | fully deterministic | all spellings of *known* concepts; misses novel terms |
| C | **Pure bge-m3 + reranker + lower gate** (no anchor) | ✅ | ~0 | deterministic | ❌ regresses (see §2) |

## 4. Recommendation — hybrid B (fast path) + A (enrichment), reranker-assisted gate

Build in this order, wet-proving each stage against a fixed query panel before the next:

1. **Deterministic transliteration-fold (primary, always-on).** A pure-Python normalizer: NFC → strip diacritics → lowercase → collapse doubled letters → fold common digraph pairs (`dh↔d`, `th↔t`, `kh↔k`, `gh↔g`, `ẓ/ż/z`, long-vowel `aa↔a`,`uu↔u`,`ee↔i`). Drives a **compact frozen concept-lexicon keyed on the folded form** — one entry per *concept* (wuḍūʾ, ṣalāh, ṣawm, …), not per spelling. `wudu/wudhu/wuduu/wuzu` all fold to one key → one rich anchor (Arabic script + English gloss vocabulary, intersection-only with corpus text, as today). This alone kills the op#20455 class of miss with zero per-query cost and full audit determinism.
2. **LLM normalizer (enrichment, gated fallback).** When the folded query hits no lexicon concept (novel/rare term, heavy code-switch), call Haiku via the existing CLI path to emit `{canonical term, Arabic, gloss}`; append and embed. Bounded timeout with graceful fallback to the raw folded query (mirrors the reranker's degrade-fast pattern). **Log the normalized query string into `retrieval_meta`** so every retrieval stays reproducible (CAI-RESP-220).
3. **Reranker-assisted relevance (reduce gate brittleness).** With the top-N reranker fix (op#20470a) the cross-encoder now actually engages; use its score as a secondary relevance signal so recall no longer hinges on a single hard 0.50 cosine cut. Keeps a fiqh query whose right chunk sits at 0.48 from being dropped when the reranker strongly agrees it is on-topic.

**Why hybrid, not A-only:** A-only puts an LLM call on the reply path of *every* fiqh query (latency + a new outage mode). The deterministic fold handles the overwhelming common case at zero cost; the LLM is reserved for the tail. **Why not B-only:** a frozen lexicon still can't anchor a genuinely novel term; A covers that tail.

## 5. Migration & wet-proof

- **Freeze `QUERY_EXPANSIONS`** — no new spelling entries land during rollout (the op#20455 wudu entries are the last hand-patch).
- **Query panel** for wet-proof: the existing families (wuḍūʾ / sahw / ṭalāq / qurban / sujūd al-sahw) **+ held-out novel spellings** the list has never seen (e.g. `wuzu`, `solat`, `poasa`, `zakaat`), each asserted to place its on-topic matn ≥ gate.
- **Success bar:** ≥ current recall on the known families AND ≥1 on-topic matn ≥ gate for every held-out spelling, with normalized queries logged. Then retire `QUERY_EXPANSIONS`.
- **Reproducibility:** bump `RETRIEVER_VERSION`; stamp `normalizer_version` + normalized query into the audit meta.

## 6. Scope / non-goals

Retrieval-side only — no change to F-1 (retrieval-first), F-2 (matched_passage), F-3 (scholar gate), or the 0.50 semantic gate's *role* (it's supplemented, not removed). No corpus change. Confined to `fiqh_semantic` + the `mizan_bot` fiqh call site; tafsir/hadith semantic can adopt the same normalizer later if it proves out.

## 7. Recommendation to Musa (one line)

Build the deterministic transliteration-fold + compact concept-lexicon first (kills the spelling-miss class at zero cost, fully auditable), add the Haiku normalizer only for the novel-term tail, and lean on the now-engaged reranker so recall no longer rides a single cosine threshold. Stop hand-patching spellings.
