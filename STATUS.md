# STATUS — ai-scholar

Last Updated: 2026-07-08
Phase: v0.2 hybrid-retrieval substrate SHIPPED + live; Al-Mīzān answer-quality hardening arc complete (#6489). Now operating on residual UX/quality + governance-gated re-engagement.
Status: live — Al-Bayān (`ask-scholar` Edge Function) + Al-Mīzān bot in operator/tester use; hybrid retrieval (FTS+synonym ∪ bge-m3 semantic-rerank) serving; INV-8 nightly attestation publishing via GitHub Action.
Deploy URL: backend-only — `ask-scholar` Edge Function on Supabase project `tscuymavysscrvoberrr`; local encoder service (bge-m3 + bge-reranker-v2-m3) on Mac Studio; Telegram bots Al-Bayān + Al-Mīzān per ops runbook.
Health: green on shipped substrate + retrieval + audit + answer-quality fixes. Yellow only on governance-gated forward work (MIZAN-REENGAGE-01 awaiting cai; retract-gate still closed by default — never unlocked, correct posture).

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
