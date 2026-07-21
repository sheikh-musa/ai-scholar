# STATUS — ai-scholar

Last Updated: 2026-07-08
Phase: v0.2 hybrid-retrieval substrate SHIPPED + live; Al-Mīzān answer-quality hardening arc complete (#6489). Now operating on residual UX/quality + governance-gated re-engagement.
Status: live — Al-Bayān (`ask-scholar` Edge Function) + Al-Mīzān bot in operator/tester use; hybrid retrieval (FTS+synonym ∪ bge-m3 semantic-rerank) serving; INV-8 nightly attestation publishing via GitHub Action.
Deploy URL: backend-only — `ask-scholar` Edge Function on Supabase project `tscuymavysscrvoberrr`; local encoder service (bge-m3 + bge-reranker-v2-m3) on Mac Studio; Telegram bots Al-Bayān + Al-Mīzān per ops runbook.
Health: green on shipped substrate + retrieval + audit + answer-quality fixes. Yellow only on governance-gated forward work (MIZAN-REENGAGE-01 awaiting cai; retract-gate still closed by default — never unlocked, correct posture).

## Self-FIX shipped — 6 self-review fixes on branch `fix/scholar-self-review-40` (2026-07-21, per msg #10515; proof reported to cc-orchestrator 'Scholar self-fix: proof')

Operator-approved (msg #10515) implementation of the 6 fixes below. **Branch only — NOT deployed to live bots** (awaiting operator/hub). All tightening; none relaxes the ruling-gate → no cai question required.

| # | Fix | Files | Proof |
|---|-----|-------|-------|
| 1 | Keyed-lookup fallback for verse/hadith/named-ayah on synthesis failure (no timeout non-answer) + `--tools ""` speedup | `mizan_bot.py` (`build_keyed_answer`, `ask_claude`) | `test_mizan_self_review_fixes.py` 23/23; ayatul-kursi/2:255/bukhari-N routed |
| 2 | Persona-leak: root cause = `claude -p` ran agentic in repo cwd → fixed with `--tools ""` + neutral `cwd`; + `detect_dev_leak` guard on both answer surfaces; + `MIZAN_TEST_MODE` skips persistence | `mizan_bot.py`, `persist-mizan-ruling/index.ts` | leak guard: 4/4 real leak samples caught, 4/4 clean answers pass |
| 3 | Classifier: first-person/mubtilat/intimacy ruling patterns → `query_type='ruling'` (INV-6 + F-3 fire structurally) | `query-type-classifier.ts` | `test_query_type_ruling_patterns.mjs` 14/14; 26 anchor cases no regression |
| 4 | `output_tier` = FLOOR (most-synthetic present); MT-in-prose detection | `_shared/output-tier.ts` (extracted), `index.ts` | `test_output_tier_floor.mjs` 7/7; real 40: quoted 17→5, 14 rows corrected |
| 5 | Relevance gate on FTS-fallback matn (lexical grounding) so "MUST surface" can't force off-topic matn | `mizan_bot.py` (`_matn_relevant_to_query`) | fasting-rescue kept, coding/decode noise dropped |
| 6 | Machine-translation guard: ai-generated-tier matn gets a stronger "don't act on wording" flag on validity questions | `mizan_bot.py` prompt | prompt rule added |

**Test totals:** 23 (py) + 14 + 7 + 27 (node) = 71 assertions pass; existing `test_cli_failure_classification` (20) + `test_tafsir_verse_routing` green. Live CLI synthesis not exercised here (subprocess CLI unauthenticated in this env) — `--tools ""` flag verified accepted; timeout-reduction claim rests on removing agentic tool-wandering + the deterministic fallback.

**Open (surfaced, not decided by CC):** (a) F-3 route-to-scholar arm is dead (no `scholar_of_record`); Fix #3 pushes more users into refusal-with-no-scholar → operator product decision. (b) durable `is_test` COLUMN on `mizan_interactions` (currently client+server SKIP, no migration) — file DDL to cai if stored-flagged test rows are wanted. (c) pre-existing (not mine): deno test expects "tell me about **the** companion X" = biography but regex needs "about companion".

## Self-review — last 40 Al-Mīzān answers (2026-07-21, per msg #10507; full report msg #10510)

Reviewed the 40 most-recent genuine `mizan_interactions` (2026-06-21 → 2026-07-18, 5 real users, all al-mizan). Honest composition: ~31 substantive answers; **6 timeout non-answers (15%)** + **3 dev-context leaks** into the user surface.

**Strengths:** fabrication discipline is exemplary (no-hallucinated-isnad held to the letter; consistent ✅/❌ grading; refuses to quote hadith from memory). Evidence-grounding strong — bot correctly declines to force-fit topically-irrelevant retrieval. Tone/pedagogy warm and Socratic; no length-budget breaches (max 3500 char).

**Top defects → fixes (priority order):**
1. **Reliability (15% timeouts)** — incl. trivial keyed lookups (Ayatul Kursi ×2, Bukhari 35). Route ayah/hadith-number/"generate <surah>" to keyed lookup; tune CLI timeout + retrieval-fallback (extend #2613/#2615 pattern).
2. **Dev/test leak into persona** (#10/#11/#18) — model narrated its own uncommitted-prompt/pipeline state to logged interactions. Harden system prompt against pipeline self-narration; add `is_test` path so dev passes don't pollute the corpus/judge set.
3. **Query-type classifier under-fires the scholar gate** — 7/40 first-person ruling-class Qs, only 1 tagged `query_type='ruling'` (#35 intimacy tagged `definition`). Gate is upheld by careful prose, not the structured pipeline. Strengthen `_shared` classifier so INV-6 `action_prompt`/F-3 fire structurally.
4. **`output_tier` under-reports synthesis on mixed bodies** (#35 `quoted` but carries AI-MT matn) — record the floor (most-synthetic tier present); bless inline per-passage badges as the INV-3 mechanism.
5. **No relevance gate before "MUST surface fiqh matn"** (#10/#11) — add similarity-score floor so it doesn't depend on model disposition.
6. **Machine-translated ruling-bearing matn** is the top content risk — prioritize human-verified translation of most-retrieved passages / stronger "don't act on wording" gate on ruling-class MT.

Net: fabrication/grounding excellent; the gap is **structural not doctrinal** — gate + tier posture rest on model disposition rather than the pipeline, and reliability+persona-integrity are eroding trust. Also flagged: `scholar_of_record` null on all 40 (F-3 route-to-scholar arm never exercised — no paired scholar yet); U3 madhhab ("Shafiʿī you follow") may be assumed not stored — verify.

## Completed (v0.1 substrate, all shipped)

### Retrieval / pipeline
- `search_tafsir_fts` Postgres tsvector RPC + GIN index (migration `20260419_001`)
- `ask-scholar` Supabase Edge Function with full retrieval pipeline (verse-ref, topic, FTS-combined, scholar-gate, no-match paths)
- 4-tier-transparency invariants (every response carries `tier`)
- INV-6 query-type classifier carve-out (definition / biography / language-clarification / madhhab-identification)
- Tafsir defense funnel (search before LLM, matched_passage overlay, no-hallucinated-isnad)

### Audit substrate (INV-8)
- `mizan_interactions` + `mizan_auto_scores` + `mizan_human_reviews` + `mizan_eval_set` + `mizan_eval_runs` schema (migration `20260422_002`)
- `mizan_retract_gate` singleton + `mizan_retract_block` trigger + `mizan_unlock_retract_gate` procedure (closed by default — still locked, correct)
- Mizan judge prompt v1 (`mizan-judge-v1-2026-04-22`) with madhab-pluralism declaration
- `ruling_audit_log` append-only hash chain + `daily_attestations` table (migration `20260423_003`)
- Postgres-Merkle fallback substrate per `INV-8-postgres-merkle-fallback.md`; `audit-verify` Edge Function; 19/19 Merkle round-trip tests

### Mizan judge pipeline (Phases 0-3)
- `scripts/mizan_judge.py {batch, calibrate}` — 8-axis scoring + Pearson judge-human agreement (15/15 unit tests; runs on Python 3.9 as of `ed4e911`)
- `scripts/mizan_review.py {list, show, verdict, promote}` — human-in-loop review + Phase 3 gold-set seeding

## Completed (v0.2 — SHIPPED since 2026-04-29, was "pre-authored/awaiting dispatch")

The v0.2 sequence that STATUS previously listed as blocked-on-dispatch has largely SHIPPED, with one architectural pivot: the encoder moved from **Modal (cloud) → local Mac Studio** (MLX + `encoder_service_v2.py`), which cleared the Modal-provisioning and Modal-privacy blockers entirely (zero cloud PII surface, zero Claude quota for embeddings).

### Semantic + hybrid retrieval (the v0.2 core)
- `20260605_001_semantic_retrieval_substrate.sql` — bge-m3 semantic substrate for hadith + tafsir + asbab (`2b4f8ac`)
- bge-reranker-v2-m3 + hybrid scoring 0.6·rerank + 0.4·semantic (`bb35a3f`); `encoder_service_v2.py` on Mac Studio (`44dfa29`)
- Al-Mīzān hybrid retrieval: FTS+SYNONYM ∪ semantic-rerank (`7afb032`)
- Server-side pgvector RPC for juridical fiqh + `retrieval_config` audit stamp — CAI-RESP-220 (`8152c9f`, migrations `20260613_002/003`)
- Recall widening + targeted retrieval-gap closes: sujūd al-sahw, radāʿah/maḥram milk-kinship, qurban-class, after-meal duʿā, combining prayers (`d0db488`, `3ac8299`, `d48322d`, `9f21b13`, `20260616_001`)
- Coverage-based relevance floor on FTS/ILIKE noise — #6489 (`bd16cff`)

### Juridical corpus ingestion (AL-BAYAN-003)
- Ihsan-grade ingestion pipeline: schema + adapters + orchestrator (`6ce82ae`, migration `20260522_001`); idempotent provenance writes (`67f9583`)
- Arabic→English translation path + Arabic-source embedding backfill (`be77310`), Claude-CLI-Max default, checkpoint/resume, output_tier CHECK (`7c208d2`, `7adcec7`, migrations `20260507_001/002`, `20260526_001`)
- Source ingestion: Safīnat al-Najā (Salah baab complete), Kashifat al-Sajā Hajj baab, OpenITI adapter BOM tolerance

### Audit (INV-8) — now live in production
- INV-8 forward attestation publisher: GitHub Action `attestation-publish.yml` + least-privilege role (`9f812fb`, migration `20260611_001`)
- Attestation recovery + health check — CAI-RESP-165 R6/R7 (`6fe6d8b`); end-to-end verifier (`8f7a8b3`)

### Al-Mīzān bot UX + answer-quality
- Audience-tier inline keyboard layman/seeker/scholar (`fc3ffa5`) + last-question persistence across restart (`b2ac6f9`)
- `/madhhab` user preference for ikhtilaf re-ranking (`cb656c7`, migration `20260603_001`); audio recitation buttons on Quranic citations (`fd919a6`); Telegram slash-command menu (`68541cf`)
- Natural-language tafsir verse-ref → keyed lookup (`86a0e03`); honest error + auto-retry on transient CLI blips (`315c89c`)
- **Answer-quality arc (#6489, 2026-07-05):** timeout graceful-degrade (kills the dead-end stub), ruling-classifier widening, fateha alias (`b2d746a`); real-time scholar gate now classification-driven — F-3 (`d6ba7cf`)

### Safety + governance
- P1 safety: AI-draft disclaimer + high-stakes scholar routing — CAI-RESP-287 (`98188d8`)
- Scholar-review flag button + `/review` admin export (`da16ce3`, migration `20260620_001`)
- Classifier: biography precedes madhhab-identification (`06ca10b`); third-person obligation caught as ruling-class (`a8abd99`)

### Eval seeding
- `mizan_eval_set` seeded to 30 candidate Q+A pairs across 2 batches (`040c4c5`, `f87b066`) awaiting scholar grading toward the ≥30 N / ≥0.800 agreement retract-gate unlock threshold

## Open / in-flight

| Item | State | Owner |
|---|---|---|
| MIZAN-REENGAGE-01 short-retention failure re-queue | SPEC shipped (`34836e8`), routed to cai (bus #7020) — build-gated on §6 ruling | cai (decision) → cc-scholar (build) |
| Retract-gate unlock | Still CLOSED (correct) — needs ≥30 scholar-graded eval items at ≥0.800 judge-human agreement | Musa / paired scholar (grading) |
| L7 first scholar-of-record pairing | Open question (see below) | Musa-direct |
| asbab_nuzul provenance | 275 ishārī rows re-tagged uncertain-provenance (`3de8ffd`) — resolved, monitoring | — |

## Known corpus/provenance notes
- asbab_nuzul source-tag corruption diagnosed + resolved (`f1e56b9`, `3de8ffd`): 275 rows re-tagged uncertain-provenance rather than asserting a false isnād.
- Corpus gaps remain phrasing-sensitive on some queries (e.g. tasawwuf absent; wudu-hadith under-retrieval) — handled honestly ("corpus doesn't carry this") rather than fabricated, per funnel F-4.

## Questions for CTO
- L7 first scholar pairing: who, and which ruling category first? (Easier-to-bound first: salah times / permissible income / qurban eligibility.) Only item that cannot route through cai per their advisory-to-Musa-direct rule.
- Scholar grading of the 30-item eval set: needed to move toward the retract-gate unlock threshold — can a paired scholar slot the grading pass?

## Provenance
STATUS.md refreshed 2026-07-08 by cc-scholar from commit evidence (`git log --since=2026-04-29`), during the donated-cap backlog-drain session. Supersedes the 2026-04-29 dookana-style snapshot, whose "Blocked on Modal/dispatch" section is obsolete (encoder pivoted to local Mac Studio; v0.2 substrate shipped).
