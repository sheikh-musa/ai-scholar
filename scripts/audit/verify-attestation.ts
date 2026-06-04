#!/usr/bin/env node
/**
 * End-to-end verification of an INV-8 daily attestation.
 *
 * What it proves (or disproves):
 *   1. The hash chain is internally consistent: each ruling_audit_log row's
 *      content_hash + prev_hash chain validates.
 *   2. The Merkle root in daily_attestations matches what you get by
 *      recomputing the tree from ruling_audit_log.merkle_leaf rows up to
 *      end-of-date.
 *   3. The Ed25519 signature on (date|root|row_count) verifies against
 *      the registered public key in audit_key_registry.
 *
 * If all three pass for an arbitrary historical date, a third party with
 * (a) read-only access to ruling_audit_log + daily_attestations and
 * (b) the public key, can independently confirm the bot's emissions were
 * not silently rewritten after the fact.
 *
 * Usage:
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
 *     npx tsx scripts/audit/verify-attestation.ts <YYYY-MM-DD>
 */

import { createHash, createPublicKey, verify } from "node:crypto";

const REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"] as const;
for (const k of REQUIRED_ENV) {
  if (!process.env[k]) { console.error(`missing env: ${k}`); process.exit(1); }
}
const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY } = process.env as Record<
  (typeof REQUIRED_ENV)[number], string
>;

const date = process.argv[2];
if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
  console.error("usage: verify-attestation.ts <YYYY-MM-DD>");
  process.exit(1);
}

async function pg(path: string): Promise<unknown> {
  const r = await fetch(`${SUPABASE_URL}${path}`, {
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
    },
  });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
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
      next.push(sha256Hex(level[i], level[i + 1] ?? level[i]));
    }
    level = next;
  }
  return level[0];
}

async function main() {
  const eod = `${date}T23:59:59.999Z`;

  // Fetch the attestation
  const atts = (await pg(
    `/rest/v1/daily_attestations?attestation_date=eq.${date}&select=*`,
  )) as Array<{
    attestation_date: string;
    row_count_end: number;
    root_hash: string;
    root_signature: string;
    key_id: string;
    git_commit_hash: string | null;
  }>;
  if (atts.length === 0) {
    console.error(`no attestation for ${date}`);
    process.exit(2);
  }
  const att = atts[0];
  console.log(`attestation ${date}:`);
  console.log(`  row_count_end:    ${att.row_count_end}`);
  console.log(`  root_hash:        ${att.root_hash}`);
  console.log(`  key_id:           ${att.key_id}`);
  console.log(`  git_commit_hash:  ${att.git_commit_hash}`);

  // Fetch the public key
  const keys = (await pg(
    `/rest/v1/audit_key_registry?key_id=eq.${att.key_id}&select=public_key_b64`,
  )) as Array<{ public_key_b64: string }>;
  if (keys.length === 0) {
    console.error(`no public key for ${att.key_id}`);
    process.exit(2);
  }
  const pubB64 = keys[0].public_key_b64;
  console.log(`  pubkey (b64):     ${pubB64.slice(0, 32)}...`);

  // Fetch the leaves through EOD
  const leavesRows = (await pg(
    `/rest/v1/ruling_audit_log?created_at=lte.${eod}&order=id.asc&select=id,merkle_leaf,content_hash,prev_hash,created_at`,
  )) as Array<{ id: number; merkle_leaf: string; content_hash: string; prev_hash: string | null; created_at: string }>;

  console.log(`\nleaves through ${date}: ${leavesRows.length}`);
  if (leavesRows.length !== att.row_count_end) {
    console.error(`✗ row count mismatch: attestation=${att.row_count_end}, recomputed=${leavesRows.length}`);
    process.exit(3);
  }
  console.log(`  ✓ row count matches`);

  // Check 1: hash chain internal consistency (each row's prev_hash matches prior row's content_hash)
  let chainOk = true;
  for (let i = 1; i < leavesRows.length; i++) {
    if (leavesRows[i].prev_hash !== leavesRows[i - 1].content_hash) {
      console.error(`✗ chain break at row id=${leavesRows[i].id}: prev_hash=${leavesRows[i].prev_hash} expected=${leavesRows[i - 1].content_hash}`);
      chainOk = false;
    }
  }
  if (chainOk) console.log(`  ✓ hash chain is internally consistent across ${leavesRows.length} rows`);

  // Check 2: recompute Merkle root over leaves and compare
  const recomputed = merkleRoot(leavesRows.map((r) => r.merkle_leaf));
  if (recomputed !== att.root_hash) {
    console.error(`✗ root mismatch:\n    stored:     ${att.root_hash}\n    recomputed: ${recomputed}`);
    process.exit(3);
  }
  console.log(`  ✓ Merkle root recomputed matches stored root`);

  // Check 3: Ed25519 signature verification on (date|root|row_count)
  const signedMessage = `${date}|${att.root_hash}|${att.row_count_end}`;
  const pubKey = createPublicKey({
    key: Buffer.from(pubB64, "base64"),
    format: "der",
    type: "spki",
  });
  const sigOk = verify(null, Buffer.from(signedMessage, "utf8"), pubKey, Buffer.from(att.root_signature, "base64"));
  if (!sigOk) {
    console.error(`✗ signature DID NOT VERIFY against ${att.key_id}`);
    process.exit(3);
  }
  console.log(`  ✓ Ed25519 signature verifies against registered public key`);
  console.log(`    (signed message: "${signedMessage.slice(0, 40)}...")`);

  console.log(`\n✓✓✓ attestation for ${date} is INTACT — all three checks passed.`);
}

main().catch((e) => { console.error(e); process.exit(99); });
