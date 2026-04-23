---
allowed-tools: Bash(cd:*), Bash(npx:*), Bash(node:*), Read(*)
description: Publish a daily INV-8 Merkle-root attestation — signs + commits + pushes the nightly audit snapshot
---

# audit-publish

Run the INV-8 audit substrate nightly attestation. Normally this is a cron job at 03:00 UTC per `docs/OPS_AL_BAYAN_V01.md` step 4, but this command lets you trigger it manually for first-run verification or recovery.

## Usage

$ARGUMENTS — none required. Reads env.

## Pre-flight

All five env vars must be set:
```bash
[ -n "$SUPABASE_URL" ] || { echo "missing SUPABASE_URL"; exit 1; }
[ -n "$SUPABASE_SERVICE_ROLE_KEY" ] || { echo "missing SUPABASE_SERVICE_ROLE_KEY"; exit 1; }
[ -n "$ORCHESTRATOR_AUDIT_SIGNING_KEY" ] || { echo "missing ORCHESTRATOR_AUDIT_SIGNING_KEY (Ed25519 pkcs8 base64)"; exit 1; }
[ -n "$AUDIT_KEY_ID" ] || { echo "missing AUDIT_KEY_ID"; exit 1; }
[ -n "$AUDIT_REPO_PATH" ] || { echo "missing AUDIT_REPO_PATH (local checkout of al-bayan/audit-attestations)"; exit 1; }
[ -d "$AUDIT_REPO_PATH/.git" ] || { echo "$AUDIT_REPO_PATH is not a git repo"; exit 1; }
```

Confirm the audit key is registered:
```sql
SELECT key_id, valid_from, valid_until FROM audit_key_registry
  WHERE key_id = '$AUDIT_KEY_ID' AND valid_until IS NULL;
```
Must return exactly 1 row.

## Run

```bash
cd ~/wingmen/projects/ai-scholar
npx tsx scripts/audit/publish-daily-attestation.ts
```

Expected output: JSON with `attestation_date`, `row_count_end`, `root_hash`, `root_signature`, `key_id`, `git_commit_hash`.

## Afterward

Verify the row landed in Supabase:
```sql
SELECT * FROM daily_attestations ORDER BY attestation_date DESC LIMIT 1;
```

Verify the git commit is visible on the remote:
```bash
git -C $AUDIT_REPO_PATH log --oneline -1
```

## Recovery

If the script fails after inserting to `daily_attestations` but before pushing git:
- Re-run manually: the INSERT uses `Prefer: resolution=merge-duplicates` so it's idempotent.
- The git push path is the only non-idempotent step; manual `git push origin main` from `$AUDIT_REPO_PATH` recovers.

If the script fails before Supabase insert:
- Safe to re-run fully — no side effects yet.

## Invariants

- `ruling_audit_log` is append-only (UPDATE/DELETE rules, GRANT revoke). Attestation signs what's in the log at run time; past attestations remain valid even as new rows append.
- Ed25519 private key lives ONLY in the cron-runner's env. Never commits, never logs, never flows through application code.
- Attestation file path is `attestations/YYYY/MM/DD.json` — one file per day, idempotent commit.

## References
- `scripts/audit/publish-daily-attestation.ts`
- `scripts/audit/generate-signing-key.ts` (one-time setup)
- `supabase/functions/audit-verify/index.ts` (third-party read side)
- `scripts/audit/__tests__/merkle.test.mjs` (math validation)
- `docs/INV-8-postgres-merkle-fallback.md`
- `docs/OPS_AL_BAYAN_V01.md` step 4
