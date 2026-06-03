#!/usr/bin/env node
/**
 * INV-8 ATTESTATION RECOVERY (CAI-RESP-165 R6b — one-time bulk sign)
 *
 * Background: ruling_audit_log producer ran healthy for 28 days while the
 * nightly attestation cron never fired (audit_key_registry + daily_attestations
 * both empty). cc-scholar observed the half-running pipeline in msg #1628;
 * CAI ruled this a P1 amanah breach (CAI-RESP-165 R6).
 *
 * This script is run ONCE to backfill attestations for every date that has
 * ruling_audit_log rows up to and including yesterday (UTC). It is NOT the
 * forward cron — that's publish-daily-attestation.ts and operates on a
 * single-date basis. The recovery rows are marked with git_commit_hash =
 * 'RECOVERY-BACKFILL-2026-06-03' to distinguish them from in-flight signing.
 *
 * Per-date semantics:
 *   For each date D in [first ruling date, yesterday]:
 *     leaves = ruling_audit_log.merkle_leaf WHERE created_at <= EOD(D), ordered by id ASC
 *     root   = balanced binary Merkle (SHA-256) over leaves
 *     sig    = Ed25519 sign of `${date}|${root}|${row_count}`
 *     UPSERT into daily_attestations (date PK, idempotent)
 *
 * Today's date is NOT backfilled (the cron will handle the rolling boundary).
 *
 * Usage:
 *   ORCHESTRATOR_AUDIT_SIGNING_KEY=<b64-pkcs8> \
 *     AUDIT_KEY_ID=al-bayan-audit-2026-06-03 \
 *     SUPABASE_URL=https://tscuymavysscrvoberrr.supabase.co \
 *     SUPABASE_SERVICE_ROLE_KEY=... \
 *     npx tsx scripts/audit/backfill-attestations.ts
 *
 * Idempotent: re-runs safely (UPSERT on date PK). Safe to run multiple times.
 */

import { createHash, createPrivateKey, sign } from "node:crypto";

const REQUIRED_ENV = [
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "ORCHESTRATOR_AUDIT_SIGNING_KEY",
  "AUDIT_KEY_ID",
] as const;

for (const key of REQUIRED_ENV) {
  if (!process.env[key]) {
    console.error(`missing required env: ${key}`);
    process.exit(1);
  }
}

const {
  SUPABASE_URL,
  SUPABASE_SERVICE_ROLE_KEY,
  ORCHESTRATOR_AUDIT_SIGNING_KEY,
  AUDIT_KEY_ID,
} = process.env as Record<(typeof REQUIRED_ENV)[number], string>;

const RECOVERY_MARKER = "RECOVERY-BACKFILL-2026-06-03";

interface AuditLogRow {
  id: number;
  merkle_leaf: string;
  created_at: string;
}

async function fetchAllLeaves(): Promise<AuditLogRow[]> {
  const url = `${SUPABASE_URL}/rest/v1/ruling_audit_log?order=id.asc&select=id,merkle_leaf,created_at`;
  const resp = await fetch(url, {
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
    },
  });
  if (!resp.ok) throw new Error(`fetch leaves failed: ${resp.status} ${await resp.text()}`);
  return (await resp.json()) as AuditLogRow[];
}

function sha256Hex(...parts: string[]): string {
  const h = createHash("sha256");
  for (const p of parts) h.update(p);
  return h.digest("hex");
}

function merkleRoot(leaves: string[]): string {
  if (leaves.length === 0) return "0".repeat(64);
  let level = leaves.slice();
  while (level.length > 1) {
    const next: string[] = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = level[i + 1] ?? left;
      next.push(sha256Hex(left, right));
    }
    level = next;
  }
  return level[0];
}

function signBase64(message: string): string {
  const privateKey = createPrivateKey({
    key: Buffer.from(ORCHESTRATOR_AUDIT_SIGNING_KEY, "base64"),
    format: "der",
    type: "pkcs8",
  });
  return sign(null, Buffer.from(message, "utf8"), privateKey).toString("base64");
}

function dateKey(iso: string): string {
  return iso.slice(0, 10);
}

async function upsertAttestation(row: {
  attestation_date: string;
  row_count_end: number;
  root_hash: string;
  root_signature: string;
  key_id: string;
  git_commit_hash: string;
}): Promise<void> {
  const url = `${SUPABASE_URL}/rest/v1/daily_attestations`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates",
    },
    body: JSON.stringify(row),
  });
  if (!resp.ok) throw new Error(`upsert attestation failed: ${resp.status} ${await resp.text()}`);
}

async function main(): Promise<void> {
  console.log("=".repeat(72));
  console.log("INV-8 attestation recovery backfill (CAI-RESP-165 R6b)");
  console.log("=".repeat(72));

  const allRows = await fetchAllLeaves();
  console.log(`fetched ${allRows.length} ruling_audit_log rows`);
  if (allRows.length === 0) {
    console.log("nothing to backfill");
    return;
  }

  const today = new Date().toISOString().slice(0, 10);
  const dates = new Set<string>();
  for (const r of allRows) dates.add(dateKey(r.created_at));
  const sortedDates = [...dates].filter((d) => d < today).sort();
  console.log(`distinct dates to attest (excluding today=${today}): ${sortedDates.length}`);

  for (const date of sortedDates) {
    // leaves where created_at <= EOD(date), in id order
    const eod = `${date}T23:59:59.999Z`;
    const leaves: string[] = [];
    for (const r of allRows) {
      if (r.created_at <= eod) leaves.push(r.merkle_leaf);
      else break; // rows are ordered by id which is monotonic with created_at
    }
    const root = merkleRoot(leaves);
    const rowCount = leaves.length;
    const signedMessage = `${date}|${root}|${rowCount}`;
    const signature = signBase64(signedMessage);

    await upsertAttestation({
      attestation_date: date,
      row_count_end: rowCount,
      root_hash: root,
      root_signature: signature,
      key_id: AUDIT_KEY_ID,
      git_commit_hash: RECOVERY_MARKER,
    });

    console.log(`  ${date}  rows=${rowCount.toString().padStart(3)}  root=${root.slice(0, 16)}...  signed`);
  }

  console.log("=".repeat(72));
  console.log(`recovery backfill complete: ${sortedDates.length} attestations`);
  console.log(`(today=${today} left for forward cron to handle in next 03:00 UTC run)`);
}

main().catch((err) => {
  console.error("backfill failed:", err);
  process.exit(1);
});
