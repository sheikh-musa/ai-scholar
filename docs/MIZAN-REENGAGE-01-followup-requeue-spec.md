# MIZAN-REENGAGE-01 — Short-retention failure re-queue (DESIGN SPEC — for cai review)

**Status:** APPROVED (CAI-RESP-396, Option C, tighter bounds) — BUILT, apply-gated. Migration + code + tests committed; nothing applied or activated. Awaiting the independent schema review CAI-RESP-396 requires (raw PII) before apply. See §8 for the ruling + build.
**Author:** cc-scholar · **Requested by:** operator via cc-orchestrator (bus #6519 → approval to spec) · **Date:** 2026-07-05
**Origin:** mizan answer-quality arc (#6489). Operator ask (verbatim): *"is it possible to reach out to those whose questions were unanswered previously to give a better answer? i dont want their bad experience to deter them from using the bot."*

---

## 1. Problem

A user whose question got a dead-end/weak answer cannot be proactively re-engaged, because the durable audit store keeps **only** `telegram_id_hash = SHA-256(chat_id)` — a one-way hash, by design (MIZAN-EVAL-001 "no PII"). There is no reverse mapping from a hash to a `chat_id`, so a Telegram follow-up cannot be addressed.

Confirmed empirically (#6519): the 2 historical stub-failure users are **unreachable** — their raw ids are absent from every store (interactions, chat-state/prefs files, `chat_history`, Telegram's ~24h `getUpdates` retention). **This spec does NOT recover them; it is forward-only.**

## 2. Goal & non-goals

**Goal:** catch a *future* failed interaction in near-real-time, re-answer it through the now-fixed pipeline, and send the user ONE courteous follow-up — **without** creating a long-term raw-`chat_id` store.

**Non-goals:** (a) recovering historical users (impossible — one-way hash); (b) any broadcast/marketing; (c) changing `mizan_interactions` (it stays hash-only); (d) user-facing *retractions* (out of scope — see §7, the retract-gate is untouched).

## 3. The privacy tension (the crux for cai)

Re-engagement **requires** a raw `chat_id` at send time. MIZAN-EVAL-001 forbids raw telegram ids in the durable store. The proposal threads this with a **transient, short-TTL, auto-purged** side table that is the *only* place a raw id ever lands, and never for long.

| Option | Raw chat_id lifetime | Re-engagement? | Verdict |
|---|---|---|---|
| A. Status quo (no retention) | never stored | ✗ impossible | zero PII risk, but the operator's ask stays unmet; failures fixed only prospectively (Fix 1) |
| B. Retain raw id in interactions | permanent | ✓ | **rejected** — breaks the no-PII invariant, unbounded PII |
| C. **Short-retention re-queue (this spec)** | minutes–hours, then purged | ✓ | bounded PII, auto-expiring — the proposed middle path |
| D. Encrypted/reversible token in interactions | permanent (decryptable) | ✓ | rejected — decryptable ≈ PII, and longer-lived than C for no benefit |

**Already shipped, reduces the need:** Fix 1 (timeout graceful-degrade, commit `b2d746a`) means a future user hits a trimmed retry or an evidence-grounded fallback, **never the dead-end stub** — so the bad-experience class is largely eliminated at the source. This re-queue only covers the residual (a genuinely failed/weak answer that still slips through).

## 4. Proposed design (Option C)

### 4.1 New table `mizan_followup_queue` (PROPOSED — not applied)

```
id              uuid pk
interaction_id  uuid  references mizan_interactions(id)   -- audit joint (hash-only there)
chat_id         bigint NOT NULL      -- the transient raw id; THE ONLY place it lives; purged on TTL
query_text      text  NOT NULL
failure_class   text  NOT NULL  check in ('timeout-stub','evidence-fallback','weak-corpus-gap')
status          text  NOT NULL default 'queued'
                       check in ('queued','reanswered','sent','skipped','expired','purged')
attempts        int   NOT NULL default 0
reanswer_text   text                 -- cleared on purge
created_at      timestamptz NOT NULL default now()
expires_at      timestamptz NOT NULL -- created_at + TTL (cai sets TTL; default proposal 48h)
sent_at         timestamptz
```
- RLS: **service-role only**, deny-all to public/anon/authenticated (013-pattern).
- **Purge is first-class:** a scheduled job hard-deletes (or nulls `chat_id`+`reanswer_text` on) every row past `expires_at`, and purges `chat_id` shortly after a terminal `sent`/`skipped`. Raw id lifetime is bounded by TTL regardless of what else happens.

### 4.2 Flow

1. **Enqueue (at answer time):** when the bot emits a failure answer (stub / evidence-fallback / detected weak), it inserts `{interaction_id, chat_id, query_text, failure_class, expires_at}`. The durable `mizan_interactions` row stays hash-only — the raw id goes ONLY to the queue.
2. **Drain:** a worker pulls `status='queued'`, re-runs `query_text` through the fixed pipeline (F-1..F-4; ruling → F-3 gate + action_prompt).
3. **Quality gate (guardrail):** the re-answer must pass a "send-worthy" check — not a stub, not an evidence-fallback, not an honest "corpus doesn't carry this" (the tasawwuf/wudu-hadith class), above a length floor. Reuse `mizan_judge.py` or a lightweight heuristic (cai to pick).
4. **Send / skip:** if send-worthy → send ONE courteous follow-up ("sorry we couldn't answer this properly at the time — here's a proper answer" + the answer), `status='sent'`. Else `status='skipped'` (**never send another weak answer** — the operator's explicit guardrail). Either terminal state schedules `chat_id` purge.
5. **Purge:** TTL job clears any row past `expires_at`.

### 4.3 Dedupe / cooldown
One follow-up per user per failure-window (e.g., collapse multiple failures in a window to a single message; at most one follow-up per user per N days). No repeated pings.

## 5. Invariants honored
- **MIZAN-EVAL-001 (no PII in durable store):** `mizan_interactions` unchanged; raw id lives only in the TTL'd queue, auto-purged.
- **tafsir-defense-funnel (F-1..F-4):** re-answers go through the same fixed pipeline; F-3 gate + INV-6 action_prompt apply to ruling re-answers.
- **Retract-gate (CAI-RESP-062):** untouched — a follow-up to an interaction that *never got a good answer* is not a retraction of a prior ruling; no `retraction_of` row is written. (If cai deems any re-answer a correction-of-record, that path stays gated separately.)
- **Guardrails (operator):** only failed interactions; no broadcast; skip-if-still-weak; one message per user.

## 6. Open questions for cai (decisions needed before build)
1. **Is a short-TTL raw-`chat_id` retention acceptable at all** under the no-PII invariant, or is Option A (no re-engagement; rely on Fix 1 prospectively) preferred?
2. **TTL** — 24h / 48h (proposed) / 72h / 7d?
3. **Eligible failure classes** — timeout-stub only, or also evidence-fallback / weak-corpus-gap?
4. **Quality gate** — `mizan_judge` pass vs heuristic; what threshold counts as "send-worthy"?
5. **Dedupe/cooldown window** — one follow-up per user per how long?
6. **Consent posture** — the user initiated contact; is an unsolicited follow-up to *their own* question within expectation, or does it need an opt-in line at first contact?
7. **Confirm forward-only** — the 2 historical users cannot be recovered; accepted?

## 7. What this spec deliberately does NOT do
No implementation, no migration, no cron. No change to `mizan_interactions`, the retract-gate, or the funnel. Historical-user recovery is out of scope (infeasible). Ships only after cai rules on §6.

---

## 8. CAI-RESP-396 ruling + build (2026-07-08)

cai **RULED CAI-RESP-396**: Option C APPROVED, to tighter bounds than §4. Build permitted; **apply gated** — the migration + purge job + opt-out path return for an *independent schema review* (raw PII) before apply. The build below encodes the ruling.

**§6 answers (binding):**
1. Retention — YES, Option C (raw id is user-given + purpose-bound; durable store stays hash-only). Option A leaves a real da'wah harm.
2. **TTL = 24h** (backstop ceiling only) — purge `chat_id` at TERMINAL state (sent/skipped) *immediately*.
3. **Classes = timeout-stub + evidence-fallback ONLY.** `weak-corpus-gap` EXCLUDED at enqueue — re-running the same corpus yields the same honest non-answer; re-queuing risks manufacturing a confident religious claim the evidence doesn't carry. Honest "we don't have this" is correct.
4. **Gate = full `mizan_judge`** (not heuristic), same send-worthy bar as a first answer, **bias to SKIP** on any doubt; ruling-class still through F-3 + INV-6.
5. **Cooldown = one follow-up / user / 30 days**; collapse in-window failures to one message.
6. Consent — no opt-IN gate (their own question), but MANDATORY: (a) honest self-identifying message, never marketing; (b) one-line STOP opt-out; (c) opt-outs stored **hash-keyed** (permanent suppression, no raw PII).
7. Forward-only confirmed — do NOT weaken the hash to chase the 2 historical users.

**Added guardrails:** G1 enqueue ONLY on genuine failure; G2 VERIFIABLE purge (audit count per run); G3 no raw `chat_id` in logs/telemetry; G4 RLS service-role-only deny-all.

**Build (committed, apply-gated):**
- `supabase/migrations/20260708_001_mizan_followup_queue.sql` — `mizan_followup_queue` (+ `failure_class` CHECK = the 2 eligible classes; 24h `expires_at`), `mizan_followup_optout` (hash-keyed), a BEFORE-UPDATE trigger that nulls `chat_id`+`reanswer_text` at terminal (§2, DB-enforced), `purge_mizan_followup_queue()` returning `(purged_count, oldest_surviving_chat_id_age)` (G2), RLS deny-all + explicit service-role policy (G4). **DO-NOT-APPLY until schema review.**
- `scripts/mizan_followup.py` — enqueue / drain / purge / opt-out. **Activation-gated:** `enqueue_if_eligible()` no-ops unless `MIZAN_FOLLOWUP_ENABLED=1` *and* returns before any DB write for a send-worthy answer (G1). Drain runs the fixed pipeline → `mizan_judge` send-worthy gate (bias-to-skip) → send one follow-up or skip. Raw `chat_id` used only at send; never logged (G3).
- `scripts/mizan_bot.py` — the enqueue hook wired at the post-persist emit point + a STOP-reply opt-out handler, **both inert** until the flag is set (fail-soft; a follow-up problem never breaks the reply path). `EVIDENCE_FALLBACK_PREFIX` / `TIMEOUT_STUB_MSG` named as the single source of truth for failure classification.
- `scripts/test_mizan_followup.py` — 21 offline cases (classification, cooldown boundary, send-worthy bias-to-skip, STOP detection, message shape, and the safety property that the disabled feature is fully inert). Wired into test CI.

**Activation checklist (post schema review):** (1) apply `20260708_001`; (2) schedule `mizan_followup.py purge` (watch the G2 age); (3) set `MIZAN_FOLLOWUP_ENABLED=1`; (4) drive one real failed→re-answered→sent round-trip with evidence; (5) confirm STOP suppresses. Nothing user-facing until purge + opt-out are demonstrably working (cai's condition).
