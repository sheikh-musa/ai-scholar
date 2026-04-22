#!/usr/bin/env node
/**
 * Publish a daily Merkle-root attestation for INV-8 audit substrate.
 *
 * Cron: 03:00 UTC nightly.
 *
 * Pipeline:
 *   1. Fetch all ruling_audit_log.merkle_leaf rows in id order.
 *   2. Compute balanced binary Merkle root (SHA-256).
 *   3. Sign the root with Ed25519 using ORCHESTRATOR_AUDIT_SIGNING_KEY.
 *   4. Insert attestation row into daily_attestations (idempotent per date).
 *   5. Write attestations/YYYY/MM/DD.json to the local checkout of
 *      al-bayan/audit-attestations, commit, push to GitHub + Codeberg.
 *
 * Usage:
 *   ORCHESTRATOR_AUDIT_SIGNING_KEY=<b64-pkcs8> \
 *     AUDIT_KEY_ID=al-bayan-audit-2026-04-23 \
 *     SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
 *     AUDIT_REPO_PATH=/srv/audit-attestations \
 *     npx tsx scripts/audit/publish-daily-attestation.ts
 */

import { createHash, createPrivateKey, sign } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { join } from "node:path";

interface AuditLogRow {
  id: number;
  merkle_leaf: string;
  created_at: string;
}

const REQUIRED_ENV = [
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "ORCHESTRATOR_AUDIT_SIGNING_KEY",
  "AUDIT_KEY_ID",
  "AUDIT_REPO_PATH",
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
  AUDIT_REPO_PATH,
} = process.env as Record<(typeof REQUIRED_ENV)[number], string>;

async function fetchLeaves(): Promise<AuditLogRow[]> {
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
    key: Buffer.from(ORCHESTRATOR_AUDIT_SIGNING_KEY, "base64"),
    format: "der",
    type: "pkcs8",
  });
  const signature = sign(null, Buffer.from(message, "utf8"), privateKey);
  return signature.toString("base64");
}

async function insertAttestation(row: {
  attestation_date: string;
  row_count_end: number;
  root_hash: string;
  root_signature: string;
  key_id: string;
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
  if (!resp.ok) throw new Error(`insert attestation failed: ${resp.status} ${await resp.text()}`);
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

  const commitHash = publishToGit(today, payload);

  await insertAttestation({
    attestation_date: today,
    row_count_end: rowCountEnd,
    root_hash: root,
    root_signature: signature,
    key_id: AUDIT_KEY_ID,
  });

  // Backfill commit hash into the row we just inserted.
  const patchUrl = `${SUPABASE_URL}/rest/v1/daily_attestations?attestation_date=eq.${today}`;
  await fetch(patchUrl, {
    method: "PATCH",
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ git_commit_hash: commitHash }),
  });

  console.log(JSON.stringify({ ...payload, git_commit_hash: commitHash }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
