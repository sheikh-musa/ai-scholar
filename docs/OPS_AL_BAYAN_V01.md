# Al-Bayān v0.1 — Operator Launch Runbook

**Scope:** everything an operator (Musa) needs to do to take Al-Bayān from "code shipped in git" to "v0.1 live with audit substrate producing + consuming". All CC-side work is complete as of this document's date; what remains is operator actions against prod Supabase + infra.

**Canonical state (2026-04-23, original):**
- Schema migrations authored + pushed to repo; **not yet applied to prod**.
- Producer + consumer pipelines wired; **not yet exercised live**.
- No external dependencies — every step can be run by Musa alone with existing credentials.

**Verified state (2026-05-19, post-substrate-audit):**
- ✅ Migrations 20260422_002 + 20260423_003 are **live in prod** (mizan_eval_* tables exist; ruling_audit_log + audit_key_registry + daily_attestations + mizan_retract_gate exist).
- ✅ Producer side **active**: 27 rows in mizan_interactions, 27 matched rows in ruling_audit_log (hash-chain populated).
- ❌ Consumer side **never fired**: audit_key_registry has 0 rows (signing key not generated), daily_attestations has 0 rows (nightly cron never run). The 27 chained rulings are accumulating un-attested.

**Verified state (2026-06-03, post-CAI-RESP-165 recovery):**
- ✅ Audit signing keypair generated. Key ID `al-bayan-audit-2026-06-03` registered in `audit_key_registry`. Private key stored in `ai-scholar/.env` (`ORCHESTRATOR_AUDIT_SIGNING_KEY`, chmod 600). Public key at `.well-known/audit-key.json` committed to repo.
- ✅ Recovery backfill: all **106 ruling_audit_log rows** (May 6 — June 2) now have signed Merkle-root attestations in `daily_attestations` (16 distinct dates). Marked with `git_commit_hash = 'RECOVERY-BACKFILL-2026-06-03'` so they're distinguishable from in-flight signing.
- ✅ R6d health surface: `scripts/audit/check-attestation-health.ts` reports current status (HEALTHY / DEGRADED / BROKEN). `--strict` exits non-zero on R7 breach (any row >24h old without attestation). JSON shape ready for cc-orchestrator's `boot_briefing` ingestion per R5.
- ❌ Forward cron **not yet installed** — operator action required (step 4 below). Today's row (2026-06-03 onward) accumulates un-attested until the launchd unit lands.
- ❌ `al-bayan/audit-attestations` git repo **not yet created** on GitHub (step 3 below). Until then, the forward cron will write DB rows but skip the git-publish phase.
- ❌ `.well-known/audit-key.json` **not yet hosted** at the Al-Bayan domain (step 2 below, operator hosting decision).

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
- `20260422_002_mizan_eval_pipeline.sql` — 5 MIZAN-EVAL tables + retract-gate. **Applied to prod (verified 2026-05-19).**
- `20260423_003_ruling_audit_log.sql` — INV-8 audit substrate + daily_attestations + audit_key_registry. **Applied to prod (verified 2026-05-19).**
- `20260511_001_juridical_embeddings_per_chunk.sql` — per-chunk juridical embeddings. **Applied to prod (verified 2026-05-19; 57 backfilled rows across 5 baabs).**

And for hifz-companion (separate migrations dir):
- `20260422_005_hifz_protocol_v1.sql` — 6 FSRS tables + view + triggers + fsrs_audit_events + manzil_miss_events.

**Verify:** `supabase db inspect` or query `information_schema.tables` for each new table name.

### 2. Generate the INV-8 audit signing key

**Status (2026-06-03):** ✅ Already done. Key ID `al-bayan-audit-2026-06-03` is registered and active. Private key stored in `ai-scholar/.env`. Public key file at `.well-known/audit-key.json` (committed).

**Remaining operator action: host the public-key file.** Publish `.well-known/audit-key.json` at `https://al-bayan.{domain}/.well-known/audit-key.json` (or whatever public URL becomes Al-Bayan's verifiable origin) so any third-party verifier can fetch the public key to check attestation signatures.

For rotation later:
```bash
cd ~/wingmen/projects/ai-scholar
npx tsx scripts/audit/generate-signing-key.ts --key-id al-bayan-audit-YYYY-MM-DD
```
Then update `audit_key_registry` for the prior key (`valid_until = now()`, `rotation_reason = '<reason>'`).

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

**Recommended path for the Mac Studio:** launchd .plist (since launchd already manages `dev.wingmen.mizan-bot`).

Create `~/Library/LaunchAgents/dev.wingmen.al-bayan-attestation.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.wingmen.al-bayan-attestation</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd /Users/sheikhmusa/wingmen/projects/ai-scholar && set -a && source .env && set +a && /usr/local/bin/npx -y tsx scripts/audit/publish-daily-attestation.ts</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>/Users/sheikhmusa</string>
        <key>AUDIT_REPO_PATH</key>
        <string>/srv/audit-attestations</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/sheikhmusa/wingmen/projects/ai-scholar/logs/al-bayan-attestation.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/sheikhmusa/wingmen/projects/ai-scholar/logs/al-bayan-attestation.err</string>
</dict>
</plist>
```

`.env` is sourced inside the bash command and supplies `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ORCHESTRATOR_AUDIT_SIGNING_KEY`, `AUDIT_KEY_ID`. `AUDIT_REPO_PATH` comes from the plist's EnvironmentVariables (point this at your local clone of `al-bayan/audit-attestations` after step 3).

Load:
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.wingmen.al-bayan-attestation.plist
launchctl start dev.wingmen.al-bayan-attestation   # manual first run to verify
tail -f logs/al-bayan-attestation.log
```

**Verify first run manually** before letting cron take over. The log should show `attestation_date`, `row_count_end`, `root_hash`, and (after step 3) a fresh git commit hash pushed to GitHub + Codeberg.

**R7 boot gate:** add `npx tsx scripts/audit/check-attestation-health.ts --strict` to any pre-deploy or boot script that must fail loudly when the attestation chain falls behind. Returns exit 1 if any ruling_audit_log row >24h old has no daily_attestations cover.

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

- [x] Migration `20260422_002` applied (verified 2026-05-19)
- [x] Migration `20260423_003` applied (verified 2026-05-19)
- [ ] Migration `20260422_005` applied (hifz repo — out of cc-scholar visibility, check hifz-companion side)
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
