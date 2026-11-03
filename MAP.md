# MAP — ai-scholar

## 1. What this app is

Backend for two Telegram bots sharing one Islamic-knowledge evidence pipeline: **Al-Bayān**
(retrieval-only ruling surface) and **Al-Mīzān** (Claude-synthesis scholar dev bot). Both
answer Qur'an/tafsir/hadith/fiqh questions against a Supabase corpus, tag every output with
one of four transparency tiers (Quoted/Paraphrased/Inferred/AI-Generated), and append an
Ed25519-signed, hash-chained audit trail for every ruling-class emission.

## 2. Top-level layout

- `supabase/functions/` — Deno Edge Functions: the retrieval+synthesis backend (`ask-scholar`),
  the webhook bot adapter (`al-bayan-bot`), persistence (`persist-mizan-ruling`), third-party
  audit verification (`audit-verify`), and ported shared logic (`supabase/functions/_shared/`).
- `supabase/migrations/` — 18 dated SQL files, applied in order; base corpus tables
  (`ayat`, `tafsir_entries`, `hadith_entries`, `juridical_texts`, `ingestion_provenance`, etc.)
  predate this directory and were created directly in Supabase Studio, not tracked here.
- `scripts/` — everything else: the two bot runners, corpus ingestion/translation/embedding
  pipelines, the Mizan judge/review CLIs, retrieval eval harnesses, and `scripts/audit/` (the
  Node/TS Merkle-attestation publisher).
- `scripts/juridical/` — fiqh-corpus matn ingestion + source-text canonicalization.
- `scripts/source_adapters/` — OpenITI source fetch + cross-edition attestation.
- `docs/` — design docs, ops runbooks, and per-feature specs (`docs/TESTING.md`,
  `docs/OPS_AL_BAYAN_V01.md`, `docs/ingest-recipes/` JSON recipes per primer).
- `evals/` — retrieval/judge eval config and gold-set candidates.
- `modal/encoder/` — a Modal (cloud) encoder service definition; superseded in production by
  a local encoder (`scripts/notes/encoder_service_v2.py`) — see hazards.
- `north-star/`, `wingmen/` — early design/spec docs (North Star vision, Wingmen Nervous
  System spec) largely superseded by shipped code; `STATUS.md` is the current source of truth,
  not `README.md` (which still says "no code has been written yet" — stale).
- `.claude/commands/`, `.claude/skills/` — Claude Code slash commands and the three
  cc-scholar-authored skills (`tafsir-defense-funnel`, `4-tier-transparency`, `inbox-check`).
- `deploy/launchd/` — macOS launchd plist for the bot healthcheck.
- `.github/workflows/` — CI (`tests.yml`) and the nightly attestation publisher
  (`attestation-publish.yml`).

## 3. Main flows

**Al-Bayān query, webhook path (production):**
Telegram → `supabase/functions/al-bayan-bot/index.ts` (secret check, fast-ack) →
`handler.ts` (`formatResponse`/`handleUpdate`) → `supabase/functions/ask-scholar/index.ts` →
`supabase/functions/_shared/query-type-classifier.ts` → retrieval
(`supabase/functions/_shared/fts-relevance.ts` + Postgres RPCs) →
`supabase/functions/_shared/persist-ruling.ts` → `mizan_interactions` + `ruling_audit_log` → reply sent back by
`al-bayan-bot`.

**Al-Bayān query, legacy long-poll path:**
`scripts/albayan_bot.py` (`main`) → same `ask-scholar` Edge Function as above → formats and
sends the reply itself via `tg_request`.

**Al-Mīzān query (long-poll bot):**
`scripts/mizan_bot.py` (`main`) → `poll_get_updates` → `gather_context` (calls
`search_quran`/`search_tafsir`/`search_hadith_fts_v2`/`lookup_fiqh`, which hit
`fiqh_semantic.py`/`hadith_semantic.py`/`tafsir_semantic.py` RPCs) → `ask_claude` (Claude CLI
subprocess synthesis, with `build_keyed_answer` as a non-LLM fallback) → `persist_emission` →
`send_message`.

**Corpus ingestion:**
`scripts/ingest_quran.py` / `ingest_hadith.py` / `scripts/juridical/ingest_matn.py` (source →
`juridical_texts` row) → `scripts/translate_juridical_arabic.py` (Arabic → English, Claude CLI
Max-plan OAuth only) → `backfill_juridical_embeddings.py` / `backfill_hadith_embeddings.py` /
`backfill_tafsir_embeddings.py` / `backfill_asbab_embeddings.py` (embed via the local encoder,
incremental/resumable upsert).

**Judge → human review → gold-set promotion:**
`scripts/mizan_judge.py batch` (scores unscored `mizan_interactions` → `mizan_auto_scores`) →
`scripts/mizan_review.py` (list / show / verdict, writing `mizan_human_reviews`) → `promote` (`mizan_eval_set`)
→ `scripts/mizan_judge.py calibrate` (`mizan_eval_runs`) → `mizan_unlock_retract_gate()` only
once judge-human agreement ≥ 0.800 on ≥30 items (see hazards).

**Nightly audit attestation:**
Every `ruling_audit_log` insert (trigger fills `prev_hash`+`merkle_leaf`) →
`.github/workflows/attestation-publish.yml` (nightly) → `scripts/audit/publish-daily-attestation.ts`
→ `daily_attestations` + an Ed25519-signed Merkle root published to the
al-bayan org's audit-attestations git repo (external, not in this repo) → independently checkable via
`supabase/functions/audit-verify/index.ts` / `scripts/audit/verify-attestation.ts`.

## 4. Data

Single store: Supabase Postgres, project ref **`tscuymavysscrvoberrr`** (shared with the
Wingmen orchestrator and hifz-companion — same project, different table namespaces).

- **Corpus (read-heavy, pre-dates `supabase/migrations/`):** `ayat`, `tafsir_entries`,
  `hadith_entries`, `mutashabihat`, `asbab_al_nuzul`, `juridical_texts`, `ingestion_provenance`,
  plus per-domain `*_embeddings` tables (`ayah_embeddings`, `hadith_embeddings`,
  `tafsir_embeddings`, `asbab_embeddings`) and `juridical_translations`. Written by the
  ingestion scripts (§3); read by the bots/Edge Functions via Postgres RPCs
  (`search_tafsir_fts`, `match_juridical_embeddings`, etc.) and plain REST selects.
- **Interaction/audit (read+write, live traffic):** `mizan_interactions`,
  `mizan_user_feedback`, `mizan_user_prefs`, `mizan_followup_queue` (migration present,
  **not applied** — see hazards), `ruling_audit_log`, `daily_attestations`,
  `audit_key_registry`. Written by `ask-scholar`'s `persistRulingEmission` / `mizan_bot.py`'s
  `persist_emission`; read by the judge/review/attestation tooling.
- **Judge/eval (read+write, offline tooling only):** `mizan_auto_scores`,
  `mizan_human_reviews`, `mizan_eval_set`, `mizan_eval_runs`, `mizan_judge_shadow`,
  `mizan_retract_gate`. Written/read only by `scripts/mizan_judge.py` and
  `scripts/mizan_review.py`.

## 5. Shared code — do not duplicate

- `supabase/functions/_shared/` is the single source of truth for logic ported to Python:
  `fts-relevance.ts` (`ftsTopical`) mirrors `scripts/mizan_bot.py`'s `_fts_topical`;
  `query-type-classifier.ts` is TS-only (the Python bot routes through the Edge Function for
  it, it does not reimplement it). If you change one side of a ported pair, change both test
  files (`docs/TESTING.md` "Parity invariants") — don't let them drift.
- `supabase/functions/_shared/persist-ruling.ts` (`persistRulingEmission`) is the only path that should write
  `mizan_interactions`/`ruling_audit_log` from an Edge Function; don't hand-roll a second
  insert path.
- `supabase/functions/_shared/output-tier.ts` is the only place that computes the INV-3 tier floor; don't
  recompute it inline in a handler.
- scripts/offline_replay.py (on the feat/bayan-webhook-receiver branch, not yet on main) replays a
  query through `gather_context`+`ask_claude` with `MIZAN_TEST_MODE=1` — use it instead of a
  one-off script to reproduce a `mizan_bot.py` retrieval/prompt issue without touching prod.

## 6. Hazards / do not touch

- **`main` lags the live checkout.** The production bots run from the
  feat/bayan-webhook-receiver branch (currently 4 commits ahead of `main`, a clean fast-forward
  ancestor as of 2026-11-03). Don't assume a file's content on `main` matches what's live —
  check `git log -1` on the actual running checkout. Fast-forwarding `main` is Musa's call, not
  a routine docs/dev action.
- **Edge Functions drift from git independently of bot restarts.** `supabase/functions/*`
  requires an explicit `supabase functions deploy <name>`; merging to any branch does nothing
  by itself. Check the function's `updated_at` via the Supabase management API against
  `git log -1 -- supabase/functions/<name>` before telling anyone a server-side fix is live.
- **Service-role vs anon client.** `ask-scholar`'s `persistRulingEmission` needs the service
  role to bypass RLS; it silently falls back to the anon client (persistence just fails) if
  `SUPABASE_SERVICE_ROLE_KEY` is missing. Always set it.
- **`mizan_followup_queue` / `mizan_followup_optout` (migration `20260708_001`) is BUILT but
  NOT APPLIED.** It stores raw PII and is awaiting independent schema review
  (MIZAN-REENGAGE-01). Do not apply it without that review.
- **Retract-gate closed by default.** No user-facing retraction ships until judge-human
  agreement ≥ 0.800 on ≥30 scholar-graded items, recorded in `mizan_eval_runs`. Enforced by the
  `mizan_retract_block` trigger — don't call `mizan_unlock_retract_gate()` to work around it.
- **No hallucinated isnads.** Hadith citations must come from a `hadith_entries` retrieval
  hit, never from the model's parametric knowledge; `mizan_judge.py` auto-flags violations.
- **KFGQPC canonical Arabic text.** Never overwrite Qur'an text from ML paraphrase or a
  different mushaf edition.
- **Claude CLI subprocess calls** (`mizan_judge.py`, ingestion/translation scripts) need
  `CLAUDE_CODE_OAUTH_TOKEN` (Max-plan), explicitly with `ANTHROPIC_API_KEY` **unset** — if both
  are present the CLI bills the API key over the Max subscription and every call fails with a
  misleadingly short "Credit balance too low" error that looks like a silent throttle.
- **`.claude/skills/` only has 3 directories here** (`tafsir-defense-funnel`,
  `4-tier-transparency`, `inbox-check`); the repo's own `CLAUDE.md` additionally references
  `quranic-text-integrity` and `hifz-fsrs-invariants`, which do not exist in this repo on any
  branch checked. Don't assume a skill named in `CLAUDE.md` is actually present.

## 7. Run, test, deploy

- **Run a bot locally:** source secrets (`/dev/shm/wingmen-secrets/.env` +
  `/dev/shm/wingmen-secrets/private/bayanqa.env` in the deployed environment), set
  `ENCODER_URL` to a running encoder, then `python3 scripts/mizan_bot.py` or
  `scripts/albayan_bot.py`. Production runs both under `~/bayanqa_supervisor.sh` in a tmux
  session, which auto-restarts on exit.
- **Test:** see `docs/TESTING.md` — Python unit suites (`python3 scripts/test_*.py`, 8 offline
  suites listed there), `node --test scripts/audit/__tests__/merkle.test.mjs`, and
  `deno test --allow-all supabase/functions/`. CI runs all three on push/PR
  (`.github/workflows/tests.yml`). `test_ask_scholar.py` and `test_mizan_bot_e2e.py` are
  live-integration only — hand-run against a throwaway identity, never in CI.
- **Deploy an Edge Function:** `supabase functions deploy <name>` — see the Edge-Function
  drift hazard above; this is a live-prod action.
- **Smoke-test retrieval:** `bash scripts/smoke_tafsir_fts.sh` / `scripts/smoke_tafsir_rpc.sh`.
- **Attestation:** nightly via GitHub Action; manual run via
  `scripts/audit/publish-daily-attestation.ts`.
