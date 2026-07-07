# CLAUDE.md — AI Scholar (cc-scholar family)

This file gives Claude Code the essential context to work effectively on the ai-scholar repo. For the sibling hifz-companion repo, see `~/wingmen/projects/hifz-companion/CLAUDE.md`; cc-scholar handles both.

## What this repo is

ai-scholar is the backend for the **Al-Bayān** and **Al-Mīzān** bots — two Telegram bots sharing one evidence pipeline but differing in synthesis posture (per CAI-RESP-048):
- **Al-Bayān** (`scripts/albayan_bot.py`) — retrieval-only ruling surface. Calls the `ask-scholar` Supabase Edge Function, displays tafsir / hadith matches verbatim, routes ruling-class queries through the scholar gate.
- **Al-Mīzān** (`scripts/mizan_bot.py`) — synthesis-capable scholar dev bot. Uses Claude directly for multi-turn reasoning, maintains session state, produces structured responses across the 4 transparency tiers.

The corpus (6,236 ayat with Ibn Kathir + Al-Sa'di tafsir, hadith from Nawawi + Riyad al-Salihin, mutashabihat cross-references, asbab al-nuzul from Al-Wahidi) lives in Supabase project `tscuymavysscrvoberrr` — same project as the Wingmen orchestrator and hifz-companion.

## Session boot

1. Read this file.
2. Read `.claude/skills/` for the authored skills pack (cc-scholar-authored per CAI-RESP-073):
   - `tafsir-defense-funnel/` — FTS-before-LLM, matched_passage overlay, scholar-gate routing
   - `4-tier-transparency/` — output_tier enforcement, INV-6 action_prompt carve-out
   - `quranic-text-integrity/` — KFGQPC Hafs canonical, NFC+SHA-256, tajwid tolerance
   - `hifz-fsrs-invariants/` — FSRS-5 math, oracle v1a audit, Friday miss policy
   - `inbox-check/` — cross-cutting CAI queue discipline (ORCHESTRATOR-NOTIFIER-FIX-001-AMEND Fix 4)
3. **Check `agent_messages` at session start AND at every turn** — per the inbox-check skill I-1..I-5. Agent id for this repo is `cc-scholar`. Query format:
   ```sql
   SELECT id, from_agent, subject, priority, created_at
     FROM agent_messages
    WHERE to_agent = 'cc-scholar' AND read_at IS NULL
    ORDER BY created_at DESC;
   ```
   Credentials: source `~/wingmen/projects/ihsanos/.env.local` for `ORCHESTRATOR_SUPABASE_URL` + `ORCHESTRATOR_SUPABASE_SERVICE_KEY`. ai-scholar/.env only has `SUPABASE_SERVICE_ROLE_KEY` (target project).
4. If anything is unclear — write a question in `agent_messages` to `cai` (`message_type='question'`, `requires_response=true`) before proceeding.

Every cc-scholar session ends with an `agent_messages` digest row (`to_agent='cai'`, `message_type='update'`, `requires_response=false`) summarizing shipped commits, blocks hit, open questions. Prior digests: msgs 545, 611.

## Agent identity + governance

I am `cc-scholar` (not `cc-ai-scholar`, not `cc-bayan`). I author / ship / challenge for both ai-scholar and hifz-companion.

**Governance protocol:** I hold challenge rights on CAI-filed `strategic_decisions` rows during their challenge window. I do NOT punt challenge decisions to Musa. If a decision isn't Ihsan-level, I challenge; if it is, I let the window expire silently. See memory `feedback_cc_challenges_cai.md` for criteria.

**Cross-repo authorship pattern (RESP-073):** skill CONTENT authored by domain CC (me for scholar/hifz skills); skill INFRASTRUCTURE owned by cc-ihsanos (submodule root, hook wrappers). Hook #7–#10 specs in this repo are cc-scholar-authored; shell implementations will come from cc-ihsanos.

## Architecture

```
Al-Bayān bot (Telegram)           Al-Mīzān bot (Telegram)
       │                                 │
       ▼                                 ▼
  ask-scholar Edge Function          Claude API direct
  (retrieval-only)                   (synthesis + sessions)
       │                                 │
       │    ┌────────────────────────────┘
       ▼    ▼
  mizan_interactions ──► mizan_judge.py batch ──► mizan_auto_scores (auto_flagged)
       │                                                  │
       │                                                  ▼
       │                                         mizan_review.py list/show/verdict
       │                                                  │
       │                                                  ▼
       │                                         mizan_human_reviews
       │                                                  │
       │                                                  ▼
       │                                         mizan_review.py promote
       │                                                  │
       │                                                  ▼
       │                                         mizan_eval_set  ──┐
       │                                                            │
       │                                    ┌───────────────────────┘
       │                                    ▼
       │                              mizan_judge.py calibrate
       │                                    │
       │                                    ▼
       │                              mizan_eval_runs
       │                                    │
       │                                    ▼ (agreement ≥ 0.800, N ≥ 30)
       │                              mizan_unlock_retract_gate()
       │                                    │
       │                                    ▼
       │                              verdict=retract permits
       │                                    user-facing retraction
       │
       └──► ruling_audit_log (trigger fills prev_hash + merkle_leaf)
                   │
                   ▼ (nightly 03:00 UTC)
             publish-daily-attestation.ts → Ed25519-signed Merkle root
                   │
                   ▼
             al-bayan/audit-attestations git repo (GitHub + Codeberg)
                   │
                   ▼
             audit-verify Edge Function (third-party permissionless verification)
```

## Directory layout

```
ai-scholar/
├── .claude/
│   ├── commands/            ← slash commands: brain-sync, build-ai-scholar, deploy-wingmen,
│   │                          ingest-ayat, mizan-judge, mizan-review, audit-publish, etc.
│   └── skills/              ← cc-scholar-authored skills (autoloaded by Anthropic Skills)
├── docs/
│   ├── OPS_AL_BAYAN_V01.md  ← v0.1 operator launch runbook (8-step checklist)
│   ├── INV-8-*.md            ← audit substrate design + scholar-ruling question
│   ├── mizan-judge-v1-prompt.md ← canonical judge prompt (version-tagged)
│   └── WAQFTOOL-01-*.md      ← Hanafi founder-mutawalli declaration text
├── evals/
│   └── gemma-integration-a-parity.yaml ← Gemma 4 parity gate config (CAI-MIZAN-EVAL-002 harness input)
├── scripts/
│   ├── albayan_bot.py / mizan_bot.py   ← Telegram bot runners
│   ├── ingest_quran.py / ingest_hadith.py / etc.  ← corpus ingestion (historical)
│   ├── mizan_judge.py                  ← Phase 1 batch scoring + calibration
│   ├── mizan_review.py                 ← Phase 2 human review + Phase 3 promote
│   ├── audit/
│   │   ├── generate-signing-key.ts     ← Ed25519 keygen (one-time op)
│   │   ├── publish-daily-attestation.ts ← nightly cron
│   │   └── __tests__/merkle.test.mjs   ← zero-dep Node test, 19 cases
│   └── test_*.py                       ← pytest-style unit tests (standalone runners too)
└── supabase/
    ├── functions/
    │   ├── ask-scholar/     ← main retrieval Edge Function (Deno)
    │   ├── audit-verify/    ← third-party verification endpoint
    │   └── _shared/         ← query-type classifier, canonical JSON, persist-ruling,
    │                          fts-relevance (FTS floor, ported to scripts/mizan_bot.py)
    └── migrations/          ← 18 files, monotonic _NNN per date (see `ls` for the full set)
        ├── 20260419_001_search_tafsir_fts.sql                 (applied)
        ├── 20260422_002_mizan_eval_pipeline.sql                (applied)
        ├── 20260423_003_ruling_audit_log.sql                   (applied)
        ├── … (juridical corpus, semantic substrate, user prefs, attestation role,
        │      scholar-review flags — all applied; v0.2 substrate is live)
        └── 20260708_001_mizan_followup_queue.sql               (BUILT, DO-NOT-APPLY —
               MIZAN-REENGAGE-01/CAI-RESP-396; awaits independent schema review, raw PII)
```

**Test CI:** `.github/workflows/tests.yml` runs python + node + deno suites on push/PR
(added 2026-07-08). See `docs/TESTING.md`. Offline Python suites live in `scripts/test_*.py`;
the two live-integration harnesses (`test_ask_scholar.py`, `test_mizan_bot_e2e.py`) are
excluded from CI (they hit prod). Deno helpers must be extracted to `_shared/` to be
testable (importing `ask-scholar/index.ts` boots `Deno.serve`).

## Hard invariants (load-bearing)

These are codified in skills (invoke the skill before editing the matching file):

- **Tafsir defense funnel (F-1):** `search_tafsir_fts` RPC runs before any LLM synthesis call in ask-scholar or bot adapters. Hook #8 enforces at pre-commit.
- **Matched passage overlay (F-2):** response shape carries `matched_passage` (null if no FTS hit, never omitted).
- **Scholar-gate routing (F-3):** ruling-class queries route through the paired human scholar-of-record or emit a 4-tier-transparency refusal.
- **Output tier NOT NULL (T-1):** every output-bearing table has `output_tier text NOT NULL CHECK (output_tier IN ('quoted','paraphrased','inferred','ai-generated'))`. Hook #10 enforces at pre-commit on migrations.
- **Response tier on every return (T-2):** every response-shaping function assigns `tier` on every return path. Hook #10 greps response shapers.
- **INV-6 carve-out (T-4):** `action_prompt` required iff `query_type=='ruling'`; null for definition / biography / language-clarification / madhhab-identification.
- **KFGQPC canonical source (Q-1):** Arabic text is KFGQPC Madinah Mushaf Hafs 'an 'Asim v18, never overwritten from ML paraphrase or other mushafs. Hook #7 gates migrations.
- **No hallucinated isnads (F-4):** hadith citations must come from `hadith_entries` rows in the retrieval result, never from model parametric knowledge. Auto-flagged by mizan_judge.py on hallucination axis ≥ 1.
- **Retract-gate closed by default:** no user-facing retraction DM ships until judge-human agreement ≥ 0.800 on ≥30 scholar-graded items, documented in `mizan_eval_runs`. Enforced by the `mizan_retract_block` trigger.
- **INV-8 audit substrate:** every ruling emission gets a `ruling_audit_log` row with SHA-256 hash chain + nightly Ed25519-signed Merkle root published to git. Fallback-ready independent of Solana scholar ruling.

## Common workflows

| Task | Command |
|---|---|
| Run the retrieval smoke test | `bash scripts/smoke_tafsir_fts.sh` |
| Score unscored interactions | `python3 scripts/mizan_judge.py batch --limit 50` |
| Calibrate judge against gold set | `python3 scripts/mizan_judge.py calibrate --gold-set-size 30` |
| List flagged reviews | `python3 scripts/mizan_review.py list` |
| Review a flagged interaction | `python3 scripts/mizan_review.py show <uuid>` |
| Record a verdict | `python3 scripts/mizan_review.py verdict <uuid> ok --rationale "..."` |
| Promote to gold set | `python3 scripts/mizan_review.py promote <uuid> --grade 4` |
| Deploy Edge Function | `supabase functions deploy ask-scholar` |
| Run Merkle test harness | `node --test scripts/audit/__tests__/merkle.test.mjs` |
| Full v0.1 launch | see `docs/OPS_AL_BAYAN_V01.md` |

## Known pitfalls

1. **Service role vs anon client** — `persistRulingEmission()` needs service role to bypass RLS on `mizan_interactions` / `ruling_audit_log`. The Edge Function falls back to anon if `SUPABASE_SERVICE_ROLE_KEY` is missing; persistence silently fails (logged via `tryPersist`). Always set the service key.

2. **Deno vs Node test boundaries** — `supabase/functions/_shared/__tests__/*.test.ts` runs in Deno (not locally unless deno is installed). `scripts/audit/__tests__/*.test.mjs` runs in Node (`node --test`). Don't cross-import.

3. **Claude CLI subprocess calls** — `scripts/mizan_judge.py` + `scripts/enrich_topic_tags_v2.py` invoke `~/.local/bin/claude -p <prompt> --output-format text`. Environment must include HOME/PATH/USER/SHELL or the CLI refuses to run. See existing script `env=` kwarg pattern.

4. **Canonical JSON is strict** — `canonicalJson()` in `_shared/canonical-json.ts` rejects non-finite numbers and unsupported types (functions, symbols). The content_hash for `ruling_audit_log` depends on this determinism; any leak of environment-dependent serialization breaks reproducibility.

5. **Retrieval IDs as uuids** — `MatchEntry.ayah_id` is optional because the merge path may receive FTS-only entries. Always use the `collectAyahUuids` helper (dedupes + filters undefined) rather than mapping directly.

6. **Migration numbering** — date prefix + _NNN_<slug>. Sequence numbers are monotonic per repo (ai-scholar uses `_001`, `_002`, `_003`; hifz has `_001..._005`). Don't reuse a number even on a different date.

7. **`anonymous` bucket for telegram_id_hash** — callers without telegram_id fall into a single anonymous bucket (SHA-256 of the string "anonymous"). That's intentional for v0.1 but means those rows all share an identity; don't use them as per-user analytics.

## External systems

| System | URL | Purpose |
|---|---|---|
| Orchestrator Supabase | https://tscuymavysscrvoberrr.supabase.co | agent_messages, strategic_decisions, mizan_*, ruling_audit_log, hifz_* |
| GitHub | https://github.com/sheikh-musa/ai-scholar | source of truth for this repo |
| `al-bayan/audit-attestations` | (TBD) | INV-8 nightly attestation publication |
| Telegram bot API | https://api.telegram.org | Al-Bayān + Al-Mīzān delivery |
| Claude API / CLI | `~/.local/bin/claude` | judge + mizan synthesis |

## References

- `docs/OPS_AL_BAYAN_V01.md` — operator launch runbook (THE checklist)
- `docs/mizan-judge-v1-prompt.md` — judge prompt v1, tagged `mizan-judge-v1-2026-04-22`
- `docs/INV-8-postgres-merkle-fallback.md` — audit substrate architecture
- `docs/INV-8-scholar-question.md` — open scholar-of-record ruling on Solana PoS
- `docs/WAQFTOOL-01-hanafi-declaration.md` — transparent Hanafi founder-mutawalli declaration
- `.claude/skills/*/SKILL.md` + `hook.md` — authored skill pack
- Memory `feedback_ping_checks_cai.md`, `feedback_inbox_check_directive.md`, `feedback_cc_challenges_cai.md`, `reference_cai_queue.md`, `scope_projects_layout.md`
