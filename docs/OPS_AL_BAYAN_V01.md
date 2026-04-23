# Al-Bayān v0.1 — Operator Launch Runbook

**Scope:** everything an operator (Musa) needs to do to take Al-Bayān from "code shipped in git" to "v0.1 live with audit substrate producing + consuming". All CC-side work is complete as of this document's date; what remains is operator actions against prod Supabase + infra.

**Canonical state (2026-04-23):**
- Schema migrations authored + pushed to repo; **not yet applied to prod**.
- Producer + consumer pipelines wired; **not yet exercised live**.
- No external dependencies — every step can be run by Musa alone with existing credentials.

## Order of operations

### 1. Apply Supabase migrations to the orchestrator project

Target project: `tscuymavysscrvoberrr`.

```bash
cd ~/wingmen/projects/ai-scholar
supabase link --project-ref tscuymavysscrvoberrr   # if not already linked
supabase db push                                    # or apply each migration explicitly
```

Migrations that need to apply (in order):
- `20260419_001_search_tafsir_fts.sql` — already live (commit `5a13f74`).
- `20260422_002_mizan_eval_pipeline.sql` — 5 MIZAN-EVAL tables + retract-gate.
- `20260423_003_ruling_audit_log.sql` — INV-8 audit substrate + daily_attestations + audit_key_registry.

And for hifz-companion (separate migrations dir):
- `20260422_005_hifz_protocol_v1.sql` — 6 FSRS tables + view + triggers + fsrs_audit_events + manzil_miss_events.

**Verify:** `supabase db inspect` or query `information_schema.tables` for each new table name.

### 2. Generate the INV-8 audit signing key

```bash
cd ~/wingmen/projects/ai-scholar
npx tsx scripts/audit/generate-signing-key.ts --key-id al-bayan-audit-2026-04-23
```

This emits:
- **Private key** (base64, PKCS8 DER) to stdout — **capture into a secret manager or the orchestrator's `.env` as `ORCHESTRATOR_AUDIT_SIGNING_KEY`**. Never commit, never paste in chat, never log in application code.
- **Public key** to `.well-known/audit-key.json` — publish this file at `https://al-bayan.{domain}/.well-known/audit-key.json` so any third-party verifier can check attestation signatures.
- **SQL INSERT** for `audit_key_registry` — run on orchestrator Supabase to register the public key.

### 3. Initialize the audit-attestations git repo

```bash
# Create a fresh repo on GitHub: al-bayan/audit-attestations
git init /srv/audit-attestations
cd /srv/audit-attestations
mkdir attestations
touch attestations/.gitkeep
git add . && git commit -m "initial"
git remote add origin git@github.com:al-bayan/audit-attestations.git
git push -u origin main
```

Mirror to Codeberg (optional but recommended per the fallback design):
```bash
git remote add codeberg git@codeberg.org:al-bayan/audit-attestations.git
git push codeberg main
```

### 4. Schedule the nightly attestation cron (03:00 UTC)

On the chosen host (currently orchestrator Mac Mini per ARCH-030; VPS when cutover):

```bash
# /etc/crontab or equivalent
0 3 * * * cd ~/wingmen/projects/ai-scholar && \
  SUPABASE_URL=https://tscuymavysscrvoberrr.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=<from vault> \
  ORCHESTRATOR_AUDIT_SIGNING_KEY=<from vault> \
  AUDIT_KEY_ID=al-bayan-audit-2026-04-23 \
  AUDIT_REPO_PATH=/srv/audit-attestations \
  npx tsx scripts/audit/publish-daily-attestation.ts >> /var/log/al-bayan-attestation.log 2>&1
```

**Verify first run manually** before cron takes over. The log should show `attestation_date`, `row_count_end`, `root_hash`, and a fresh git commit hash pushed.

### 5. Deploy the ask-scholar Edge Function with persistence wired

```bash
cd ~/wingmen/projects/ai-scholar
supabase functions deploy ask-scholar
supabase functions deploy audit-verify   # INV-8 third-party verification
```

First prod call: `curl -X POST https://tscuymavysscrvoberrr.supabase.co/functions/v1/ask-scholar -H "Authorization: Bearer $SUPABASE_ANON_KEY" -H "Content-Type: application/json" -d '{"query":"what is tawakkul","telegram_id":"test-user-1"}'`

**Verify:** `SELECT COUNT(*) FROM mizan_interactions; SELECT COUNT(*) FROM ruling_audit_log;` should increment by 1 each.

### 6. Schedule the mizan judge batch

```bash
# Hourly: score unscored interactions
0 * * * * cd ~/wingmen/projects/ai-scholar && \
  SUPABASE_SERVICE_ROLE_KEY=<from vault> \
  python3 scripts/mizan_judge.py batch --limit 50 \
  >> /var/log/mizan-judge.log 2>&1
```

### 7. Seed the scholar gold set (blocks on INV-7 pairing)

This is the only step not automatable — it requires a paired human scholar (INV-7 obligation, open).

Until the scholar is paired, the calibration run will not have ≥30 scholar-graded items, and the retract-gate stays closed. Users' flagged interactions queue silently for later review; no retraction DMs go out.

Once the scholar is paired:
```bash
# Scholar reviews auto-flagged interactions and grades them
MIZAN_REVIEWER="scholar-<name>" python3 scripts/mizan_review.py list
MIZAN_REVIEWER="scholar-<name>" python3 scripts/mizan_review.py show <uuid>
MIZAN_REVIEWER="scholar-<name>" python3 scripts/mizan_review.py verdict <uuid> ok
MIZAN_REVIEWER="scholar-<name>" python3 scripts/mizan_review.py promote <uuid> --grade 4

# Once ≥30 graded items exist:
python3 scripts/mizan_judge.py calibrate --gold-set-size 30
# If agreement ≥ 0.800, the retract-gate unlocks automatically via the
# mizan_unlock_retract_gate() RPC.
```

### 8. Bot adapters

```bash
# Run albayan_bot (retrieval-only scholar queries)
MIZAN_BOT_TOKEN=<telegram token> python3 scripts/albayan_bot.py

# Run mizan_bot (full synthesis via Claude, direct; separate token per CAI-RESP-048)
MIZAN_BOT_TOKEN=<separate token> python3 scripts/mizan_bot.py
```

Both now send `telegram_id` to ask-scholar so the audit trail has stable (hashed) per-user identity.

## Monitoring surfaces

| Surface | How to check |
|---|---|
| Producer writes | `SELECT count(*), max(created_at) FROM mizan_interactions;` |
| Audit chain | `SELECT count(*), max(id) FROM ruling_audit_log;` — should equal mizan_interactions count (minus scholar-gate refusals that aren't audited per-row yet; each ruling class emits one audit row) |
| Nightly attestation | `SELECT * FROM daily_attestations ORDER BY attestation_date DESC LIMIT 5;` |
| Judge scoring | `SELECT count(*) FROM mizan_auto_scores; SELECT count(*) FROM mizan_auto_scores WHERE auto_flagged=true;` |
| Review queue | `python3 scripts/mizan_review.py list` |
| Gate status | `SELECT unlocked, unlocked_at FROM mizan_retract_gate;` |
| Hifz FSRS state | (once Phase 2 UI lives) `SELECT count(*) FROM hifz_fsrs_state; SELECT count(*) FROM hifz_fsrs_events;` |

## Troubleshooting

**ask-scholar 500 with "mizan_interactions insert failed":**
- Migration `20260422_002` not applied. Run `supabase db push`.

**ask-scholar 500 with "ruling_audit_log insert failed":**
- Migration `20260423_003` not applied.
- Or: service role key missing / incorrect; the function falls back to anon client and RLS blocks the insert.

**Attestation cron fails with "fetch leaves failed":**
- `SUPABASE_SERVICE_ROLE_KEY` not set in the cron env.

**Attestation cron succeeds but `git push` fails:**
- SSH key for the attestation repo not available to cron user. Use a deploy key scoped to that repo only.

**Judge batch succeeds but `mizan_auto_scores` stays empty:**
- Parse failures on judge output. Check `console.error` lines in the log for `judge CLI returned <code>` or non-JSON output.

**Calibrate agreement < 0.800:**
- Likely judge-prompt needs iteration, or gold set too small / skewed. Pull the eval_set rows and manually inspect: are scholar grades well-spread? Are questions covering the 8 axes? Iterate prompt to `mizan-judge-v2` (bump `judge_prompt_version`) and re-run.

## Checklist

- [ ] Migration `20260422_002` applied
- [ ] Migration `20260423_003` applied
- [ ] Migration `20260422_005` applied (hifz repo)
- [ ] Audit signing key generated + registered in `audit_key_registry`
- [ ] `.well-known/audit-key.json` published
- [ ] `al-bayan/audit-attestations` repo created + mirror set up
- [ ] Nightly attestation cron scheduled + first run verified
- [ ] `ask-scholar` + `audit-verify` Edge Functions deployed
- [ ] First end-to-end test call produces a mizan_interactions row AND a ruling_audit_log row
- [ ] Judge batch cron scheduled
- [ ] Bot tokens deployed with new payload shape (telegram_id + bot_variant)
- [ ] Scholar-of-record pairing (INV-7) — **external**, blocks gold-set seeding

## What's NOT in v0.1

- Gemma 4 Integration A (on-device E4B in hifz-companion tadabbur) — blocked on parity-gate run which is blocked on CAI-MIZAN-EVAL-002 harness.
- Solana anchoring of audit trail — blocked on scholar-of-record ruling on PoS halal status (see `INV-8-scholar-question.md`). Postgres-Merkle fallback is the v0.1 substrate.
- Retract DMs — blocked on judge-human agreement ≥ 0.800 on ≥30 items.
- Hifz Phase 2 UI mount — `<OnDeviceModelOptIn />` and scheduler integration shipped as modules; mounting into the app route tree is a follow-up session.
- Cross-repo skills submodule — pending cc-ihsanos landing `wingmen-orchestrator/skills/` per CAI-RESP-073 R2.

## Provenance

All referenced code is in `~/wingmen/projects/ai-scholar/` (commits up to and including this doc) and `~/wingmen/projects/hifz-companion/` (parallel commits). Every migration, script, and function in this runbook has a corresponding git commit and test where testable. Audit trail for the audit trail.
