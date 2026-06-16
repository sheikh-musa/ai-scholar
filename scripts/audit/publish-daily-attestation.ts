#!/usr/bin/env node
/**
 * Publish a daily Merkle-root attestation for the INV-8 audit substrate.
 *
 * Runs as a scheduled GitHub Action (decision INV-8-FORWARD-SCHEDULER-001).
 * Cron: 03:00 UTC nightly (activated once secrets + target repo exist).
 *
 * Hardenings (CAI msg #2006):
 *   A — authenticates with the least-privilege `attestation_publisher` role
 *       via ATTESTATION_DB_URL (direct connection), NEVER the service-role key.
 *   B — signs with a DEDICATED Ed25519 keypair (ATTESTATION_SIGNING_KEY /
 *       AUDIT_KEY_ID), not shared with any other signing use.
 *
 * Pipeline:
 *   1. SELECT all ruling_audit_log.merkle_leaf rows in id order.
 *   2. Compute balanced binary Merkle root (SHA-256).
 *   3. Sign the root with Ed25519 (ATTESTATION_SIGNING_KEY).
 *   4. Write attestations/YYYY/MM/DD.json to the local checkout of
 *      al-bayan/audit-attestations, commit, push.
 *   5. UPSERT the attestation row (incl. git_commit_hash) into
 *      daily_attestations (idempotent per date).
 *
 * Usage:
 *   ATTESTATION_DB_URL=postgresql://attestation_publisher:...@host:5432/postgres?sslmode=require \
 *     ATTESTATION_SIGNING_KEY=<b64-pkcs8> \
 *     AUDIT_KEY_ID=al-bayan-attest-2026-06-11 \
 *     AUDIT_REPO_PATH=/path/to/audit-attestations \
 *     npx tsx scripts/audit/publish-daily-attestation.ts
 */

import { createHash, createPrivateKey, sign } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { join } from "node:path";
import { attestationPool, closePool } from "./db.ts";

const REQUIRED_ENV = [
  "ATTESTATION_DB_URL",
  "ATTESTATION_SIGNING_KEY",
  "AUDIT_KEY_ID",
  "AUDIT_REPO_PATH",
] as const;

for (const key of REQUIRED_ENV) {
  if (!process.env[key]) {
    console.error(`missing required env: ${key}`);
    process.exit(1);
  }
}

const { ATTESTATION_SIGNING_KEY, AUDIT_KEY_ID, AUDIT_REPO_PATH } = process.env as Record<
  (typeof REQUIRED_ENV)[number],
  string
>;

interface AuditLogRow {
  id: number;
  merkle_leaf: string;
  created_at: string;
}

async function fetchLeaves(): Promise<AuditLogRow[]> {
  const { rows } = await attestationPool().query<AuditLogRow>(
    "SELECT id, merkle_leaf, created_at FROM public.ruling_audit_log ORDER BY id ASC",
  );
  return rows;
}

function sha256Hex(...parts: string[]): string {
  const h = createHash("sha256");
  for (const p of parts) h.update(p);
  return h.digest("hex");
}

/** Balanced binary Merkle root over leaves (hex strings). Empty → all-zero root. */
function merkleRoot(leaves: string[]): string {
  if (leaves.length === 0) return "0".repeat(64);
  let level = leaves.slice();
  while (level.length > 1) {
    const next: string[] = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = level[i + 1] ?? left; // duplicate the last leaf if odd
      next.push(sha256Hex(left, right));
    }
    level = next;
  }
  return level[0];
}

function signBase64(message: string): string {
  const privateKey = createPrivateKey({
    key: Buffer.from(ATTESTATION_SIGNING_KEY, "base64"),
    format: "der",
    type: "pkcs8",
  });
  return sign(null, Buffer.from(message, "utf8"), privateKey).toString("base64");
}

async function upsertAttestation(row: {
  attestation_date: string;
  row_count_end: number;
  root_hash: string;
  root_signature: string;
  key_id: string;
  git_commit_hash: string;
}): Promise<void> {
  await attestationPool().query(
    `INSERT INTO public.daily_attestations
       (attestation_date, row_count_end, root_hash, root_signature, key_id, git_commit_hash)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (attestation_date) DO UPDATE SET
       row_count_end   = EXCLUDED.row_count_end,
       root_hash       = EXCLUDED.root_hash,
       root_signature  = EXCLUDED.root_signature,
       key_id          = EXCLUDED.key_id,
       git_commit_hash = EXCLUDED.git_commit_hash`,
    [
      row.attestation_date,
      row.row_count_end,
      row.root_hash,
      row.root_signature,
      row.key_id,
      row.git_commit_hash,
    ],
  );
}

function publishToGit(attestationDate: string, payload: unknown): string {
  const [year, month, day] = attestationDate.split("-");
  const dir = join(AUDIT_REPO_PATH, "attestations", year, month);
  mkdirSync(dir, { recursive: true });
  const filePath = join(dir, `${day}.json`);
  writeFileSync(filePath, JSON.stringify(payload, null, 2));

  execSync(`git -C "${AUDIT_REPO_PATH}" add "${filePath}"`);
  execSync(`git -C "${AUDIT_REPO_PATH}" commit -m "attestation: ${attestationDate}"`);
  const commitHash = execSync(`git -C "${AUDIT_REPO_PATH}" rev-parse HEAD`).toString().trim();
  execSync(`git -C "${AUDIT_REPO_PATH}" push origin main`);
  return commitHash;
}

async function main() {
  const today = new Date().toISOString().slice(0, 10);
  const leaves = await fetchLeaves();
  const leafHashes = leaves.map((r) => r.merkle_leaf);
  const root = merkleRoot(leafHashes);
  const signature = signBase64(root);
  const rowCountEnd = leaves.length ? leaves[leaves.length - 1].id : 0;

  const payload = {
    attestation_date: today,
    row_count_end: rowCountEnd,
    root_hash: root,
    root_signature: signature,
    key_id: AUDIT_KEY_ID,
    leaf_count: leaves.length,
    generated_at: new Date().toISOString(),
  };

  // Commit to git first so the on-chain row carries the real commit hash.
  const commitHash = publishToGit(today, payload);

  await upsertAttestation({
    attestation_date: today,
    row_count_end: rowCountEnd,
    root_hash: root,
    root_signature: signature,
    key_id: AUDIT_KEY_ID,
    git_commit_hash: commitHash,
  });

  console.log(JSON.stringify({ ...payload, git_commit_hash: commitHash }, null, 2));
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => closePool());
