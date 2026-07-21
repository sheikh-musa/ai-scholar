# STATUS — ai-scholar

Last Updated: 2026-04-29
Phase: v0.2 retrieval-substrate sequence (system_layer L2 hybrid pgvector + FTS); pre-authored artifacts in repo, sequence pure-blocker-bound on operator/CAI dispatch
Status: building (paused on dispatched blockers in agent_messages #972)
Deploy URL: backend-only — `ask-scholar` Edge Function on Supabase project `tscuymavysscrvoberrr`; Telegram bots Al-Bayān + Al-Mīzān runtime per ops runbook
Health: green on shipped substrate; yellow on v0.2 sequence (waiting on CAI dispatch since 2026-04-28T14:25 UTC, escalation ping filed msg #1023)

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
- `mizan_retract_gate` singleton + `mizan_retract_block` trigger + `mizan_unlock_retract_gate` procedure (closed by default)
- Mizan judge prompt v1 (`mizan-judge-v1-2026-04-22`) with madhab-pluralism declaration
- `ruling_audit_log` append-only hash chain + `daily_attestations` table (migration `20260423_003`)
- Postgres-Merkle fallback substrate per `INV-8-postgres-merkle-fallback.md`
- `audit-verify` Edge Function (third-party permissionless verification)
- 19/19 Merkle proof round-trip integration tests passing

### Producer wiring
- `ask-scholar` writes `mizan_interactions` + `ruling_audit_log` rows on every emission path
- Canonical-JSON serializer for content_hash stability (10/10 tests)
- Bot adapters (`albayan_bot`, `mizan_bot`) send `telegram_id` + `bot_variant` for stable hashed identity

### Mizan judge pipeline (Phases 0-3)
- `scripts/mizan_judge.py {batch, calibrate}` — 8-axis scoring + Pearson judge-human agreement (15/15 tests)
- `scripts/mizan_review.py {list, show, verdict, promote}` — human-in-loop review + Phase 3 gold-set seeding

### Authored skills (per CAI-RESP-061 / CAI-RESP-073)
- `.claude/skills/tafsir-defense-funnel/{SKILL.md,hook.md}` — F-1..F-6 + Hook #8 spec
- `.claude/skills/4-tier-transparency/{SKILL.md,hook.md}` — T-1..T-6 + Hook #10 spec
- `.claude/skills/inbox-check/SKILL.md` — I-1..I-5 governance discipline
- `.claude/commands/{mizan-judge, mizan-review, audit-publish}.md` — slash workflow commands

### Operator runbook
- `docs/OPS_AL_BAYAN_V01.md` — 8-step v0.1 launch checklist
- `docs/INV-8-{scholar-question, postgres-merkle-fallback}.md`
- `docs/WAQFTOOL-01-hanafi-declaration.md`

## Completed (v0.2 design, pre-authored, awaiting dispatch)

### Architecture + governance docs
- `docs/EMBED_PIPELINE_v02.md` — system_layer L2 hybrid pgvector + FTS + RRF + Opus reranker (CAI-RESP-094 + CAI-RESP-095 + AL-BAYAN-003 + LAYERING-RECONCILE applied)
- `docs/LAYERING.md` — content_layer (primary/interpretive/juridical/connective) vs system_layer (L1-L8) glossary; gates further L-prefix filings
- `docs/ARCH_AL_BAYAN_ENCODER_EVAL.md` — BGE-M3 vs jina-v3 90-query measurement plan (30/30/30 Arabic/Bahasa/English)
- `docs/MODAL_PRIVACY_VERIFICATION.md` — 5-check pre-execution checklist gates Phase A backfill
- `docs/AL_BAYAN_003_PHASE_1_RUNBOOK.md` — Safīnat al-Najā + Matn Abī Shujā' source-acquisition runbook

### Migrations (committed; do-NOT-apply until upstream gates clear)
- `20260428_005_mizan_judge_shadow.sql` — shadow-mode judge logging table (Q10 hard gate substrate)
- `20260428_006_ayah_embeddings.sql` — pgvector(1024) + HNSW + RLS + `search_ayat_semantic` RPC
- `20260429_001_juridical_corpus.sql` — `juridical_texts` + `ingestion_provenance` + `juridical_embeddings` + `search_juridical_semantic` RPC, multi-madhab schema from day one (AL-BAYAN-003)

### Scripts + container scaffold
- `scripts/encoder_eval/{build_corpus, build_gold_set, embed_corpus, measure, compare}.py` — measurement harness
- `scripts/juridical/{canonicalize, ingest_matn}.py` — matn cleanup + ingestion to `juridical_texts`
- `modal/encoder/{Dockerfile, requirements.txt, serve.py, modal_app.py}` — model-agnostic FastAPI container (BGE-M3 / jina-v3 env switch); CAI-RESP-095 5-check privacy posture honored at config level (region=ap-southeast, container_idle_timeout=300, keep_warm=0, no request-body logging)

### Strategic_decisions filings (cc-scholar-authored)
- `AL-BAYAN-002` (id 564) — topic tags demote-to-facets + judge-consumption non-deciding-factor bound (CAI-RESP-095 (C))
- `ARCH-AL-BAYAN-ENCODER-EVAL` (id 565) — measurement spec placeholder
- `MIZAN-JUDGE-SHADOW-001` (id 566) — shadow logging table

## Blocked (filed to CAI msg #972, escalated msg #1023)

| # | Blocker | Owner |
|---|---|---|
| 1 | Apply `MIZAN-JUDGE-SHADOW-001` migration to prod (`tscuymavysscrvoberrr`) | cc-orchestrator (post-AGENTS-002 platform handoff) or Musa-direct supabase CLI |
| 2 | Modal account provisioning + execute 5 privacy checks per `MODAL_PRIVACY_VERIFICATION.md` | account = Musa-direct (payment + ToS); execution = cc-orchestrator or CAI |
| 3 | Phase 1 ENCODER-EVAL gold-set labeling (~90 min, 30 queries) | Musa-direct (CAI cannot label per their own LLM-rejection rule in CAI-RESP-094 Q10 (iv)) |
| 7 | Apply `juridical_corpus` migration once AL-BAYAN-003 challenge window closes | cc-orchestrator |
| 8 | Verify Wikisource AR canonical URLs for Safīnat + Matn Abī Shujā' (cc-scholar's WebFetch 404'd) | Musa, paired scholar (post-INV-7), or CAI direct |

cc-scholar cannot self-clear items 1-3 + 7-8. Items 4 (ENCODER-EVAL measurement), 5 (`ayah_embeddings` apply), 6 (backfill), 9 (juridical ingestion), 10-15 (shadow → audit → augment → recalibrate → unlock → cutover) all downstream.

## Files Changed (recent — last 10 commits)

```
0242b52  feat+migrations(arch): pre-author Phase A-E artifacts (gated; do-not-apply)
ed32329  docs+scripts: CAI-RESP-094/095 + AL-BAYAN-003 + LAYERING-RECONCILE follow-ups
bd0ea3b  docs+migration(arch): ENCODER-EVAL spec + JUDGE-SHADOW migration per CAI-RESP-094 follow-ups
d8aca86  docs(arch): EMBED_PIPELINE_v02 design draft + v4 tag-run halted
80a7e1b  fix(hook-8): amend tafsir-defense-funnel hook spec — v0 is file-level, not same-function
f4275d6  fix(ask-scholar): self-audit — add top-level tier per 4-tier-transparency T-2
6f8b3cb  docs(claude): ai-scholar CLAUDE.md + 3 mizan/audit slash commands
3b0a61c  docs(ops): Al-Bayan v0.1 operator launch runbook
2f2a942  test(audit): Merkle proof round-trip — INV-8 math integration test (19/19 pass)
5b31f57  feat(mizan): promote subcommand — reviewed interactions → eval_set (Phase 3)
```

## Next Up

When upstream blockers clear (msg #972 dispatched):

1. (post-1) Verify migration 20260428_005 applied; smoke-test `INSERT INTO mizan_judge_shadow`
2. (post-2) Run Modal privacy verification, fill TBD result section in `MODAL_PRIVACY_VERIFICATION.md`
3. (post-3) Once gold-set labeled, run ENCODER-EVAL measurement (BGE-M3 vs jina-v3)
4. Apply `ayah_embeddings` migration (post 2 + 3)
5. Backfill 6,236 ayat embeddings via Modal `/embed`
6. Apply `juridical_corpus` migration (post AL-BAYAN-003 window close)
7. Phase 1 source acquisition (operator-verified URLs)
8. Juridical ingestion (canonicalize + ingest_matn)
9. Wire fused retrieval into `ask-scholar/index.ts` in shadow-mode (logs to `mizan_judge_shadow`, returns existing FTS-only)
10. 1-2 week shadow accumulation
11. Diff audit + augmented gold-set (50-200 items per AL-BAYAN-003 extension)
12. Recalibrate retract threshold
13. Unlock retract-gate
14. Cutover Quran retrieval to fused (primary user-serving)
15. Activate juridical retrieval (separate gate per AL-BAYAN-003)

## Conformance debt (per CAI-RESP-097 GAP 4)

This STATUS.md uses dookana-style canonical pattern as interim. Conform to `STATUS-CANONICAL-001` template within 30 days of that template shipping.

## Questions for CTO

- L7 first scholar pairing: who? for which ruling category first? (Easier-to-bound categories first per my prior framing — salah times / permissible income types / qurban eligibility.) This is the only thing I cannot push to CAI per their advisory-to-Musa-direct routing on this item.
- Modal account: confirm whether you'll provision personally or delegate to cc-orchestrator? Workspace name reservation pattern?
- ENCODER-EVAL gold-set labeling timing: 90 min Phase 1 — can you slot a calendar block, or want me to dispatch via CAI to a paired scholar once L7 lands?

## Provenance

This STATUS.md authored 2026-04-29 per `agent_messages msg #962` (CAI-RESP-097 GAP 4 routing to cc-scholar) using dookana-style interim per CAI guidance.
