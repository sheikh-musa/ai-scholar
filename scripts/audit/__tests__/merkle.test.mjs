/**
 * Integration test for INV-8 Merkle proof math.
 *
 * Reproduces the logic shipped in:
 *   - scripts/audit/publish-daily-attestation.ts  (Merkle root computation)
 *   - supabase/functions/audit-verify/index.ts    (proof path + verification)
 *
 * Verifies the end-to-end property: any leaf + its proof path reconstructs
 * the root that the nightly attestation signs. If this test passes, a
 * third-party verifier clone-and-check of the audit-attestations git repo
 * will verify any published ruling.
 *
 * Runs with `node --test scripts/audit/__tests__/merkle.test.mjs`.
 * Zero deps (uses node:crypto + node:test built-ins).
 */

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { createHash } from "node:crypto";

function sha256Hex(...parts) {
  const h = createHash("sha256");
  for (const p of parts) h.update(p);
  return h.digest("hex");
}

/** Balanced binary Merkle root. Matches publish-daily-attestation.ts. */
function merkleRoot(leaves) {
  if (leaves.length === 0) return "0".repeat(64);
  let level = leaves.slice();
  while (level.length > 1) {
    const next = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = level[i + 1] ?? left;
      next.push(sha256Hex(left, right));
    }
    level = next;
  }
  return level[0];
}

/** Proof path for leaf at index. Matches audit-verify/index.ts. */
function merkleProof(leaves, index) {
  const proof = [];
  let level = leaves.slice();
  let i = index;
  while (level.length > 1) {
    const next = [];
    for (let j = 0; j < level.length; j += 2) {
      const left = level[j];
      const right = level[j + 1] ?? left;
      next.push(sha256Hex(left, right));
    }
    const pairIndex = i % 2 === 0 ? i + 1 : i - 1;
    const sibling = level[pairIndex] ?? level[i];
    proof.push({ hash: sibling, side: i % 2 === 0 ? "R" : "L" });
    i = Math.floor(i / 2);
    level = next;
  }
  return proof;
}

/** Apply proof to a leaf and return the reconstructed root. Third-party verifier side. */
function reconstructRoot(leaf, proof) {
  let computed = leaf;
  for (const step of proof) {
    if (step.side === "R") computed = sha256Hex(computed, step.hash);
    else computed = sha256Hex(step.hash, computed);
  }
  return computed;
}

/** Synthetic audit-log leaf: SHA-256(content_hash || prev_hash || id || created_at). Matches migration 20260423_003_ruling_audit_log.sql. */
function auditLeaf(row) {
  return sha256Hex(row.content_hash, row.prev_hash, String(row.id), row.created_at);
}

function genAuditLog(n) {
  const rows = [];
  const genesis = "0".repeat(64);
  let prev = genesis;
  for (let i = 1; i <= n; i++) {
    const contentHash = sha256Hex(`ruling-${i}`);
    const createdAt = new Date(1714000000000 + i * 60_000).toISOString().replace(/\.\d+Z$/, ".000000+00:00");
    const row = { id: i, content_hash: contentHash, prev_hash: prev, created_at: createdAt };
    rows.push(row);
    prev = contentHash;
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("empty leaves → all-zero root", () => {
  assert.equal(merkleRoot([]), "0".repeat(64));
});

test("single leaf → root equals leaf", () => {
  const leaf = sha256Hex("solo");
  assert.equal(merkleRoot([leaf]), leaf);
});

test("two leaves → root = hash(l, r)", () => {
  const a = sha256Hex("a");
  const b = sha256Hex("b");
  assert.equal(merkleRoot([a, b]), sha256Hex(a, b));
});

test("odd leaf count duplicates last leaf at each level", () => {
  const a = sha256Hex("a");
  const b = sha256Hex("b");
  const c = sha256Hex("c");
  const level1Left = sha256Hex(a, b);
  const level1Right = sha256Hex(c, c); // c duplicated
  const expected = sha256Hex(level1Left, level1Right);
  assert.equal(merkleRoot([a, b, c]), expected);
});

test("proof of single-leaf tree is empty and leaf equals root", () => {
  const leaf = sha256Hex("x");
  const proof = merkleProof([leaf], 0);
  assert.equal(proof.length, 0);
  assert.equal(reconstructRoot(leaf, proof), leaf);
});

for (const n of [2, 3, 4, 5, 8, 15, 16, 17, 100]) {
  test(`round-trip: n=${n} leaves, every leaf's proof reconstructs root`, () => {
    const leaves = Array.from({ length: n }, (_, i) => sha256Hex(`leaf-${i}`));
    const root = merkleRoot(leaves);
    for (let i = 0; i < n; i++) {
      const proof = merkleProof(leaves, i);
      const computed = reconstructRoot(leaves[i], proof);
      assert.equal(
        computed,
        root,
        `leaf ${i} proof of length ${proof.length} failed to reconstruct root`,
      );
    }
  });
}

test("proof rejects tampered leaf", () => {
  const leaves = Array.from({ length: 8 }, (_, i) => sha256Hex(`leaf-${i}`));
  const root = merkleRoot(leaves);
  const proof = merkleProof(leaves, 3);
  const tampered = sha256Hex("tampered-leaf");
  assert.notEqual(reconstructRoot(tampered, proof), root);
});

test("proof rejects swapped sibling side", () => {
  const leaves = Array.from({ length: 8 }, (_, i) => sha256Hex(`leaf-${i}`));
  const root = merkleRoot(leaves);
  const proof = merkleProof(leaves, 3);
  const swapped = proof.map((s) => ({ hash: s.hash, side: s.side === "L" ? "R" : "L" }));
  assert.notEqual(reconstructRoot(leaves[3], swapped), root);
});

// ---------------------------------------------------------------------------
// End-to-end: synthetic audit log, hash chain, and Merkle round-trip
// ---------------------------------------------------------------------------

test("audit-log hash chain: every row's prev_hash equals previous row's content_hash", () => {
  const rows = genAuditLog(20);
  assert.equal(rows[0].prev_hash, "0".repeat(64), "genesis prev_hash");
  for (let i = 1; i < rows.length; i++) {
    assert.equal(rows[i].prev_hash, rows[i - 1].content_hash, `row ${i} chain break`);
  }
});

test("audit-log Merkle: each leaf verifies against root", () => {
  const rows = genAuditLog(25);
  const leaves = rows.map(auditLeaf);
  const root = merkleRoot(leaves);
  for (let i = 0; i < rows.length; i++) {
    const proof = merkleProof(leaves, i);
    assert.equal(reconstructRoot(leaves[i], proof), root);
  }
});

test("audit-log tamper detection: edit any row's content_hash → at least one leaf fails", () => {
  const rows = genAuditLog(10);
  const leaves = rows.map(auditLeaf);
  const root = merkleRoot(leaves);

  const tamperedRows = rows.map((r, i) =>
    i === 5 ? { ...r, content_hash: sha256Hex("tampered") } : r,
  );
  const tamperedLeaves = tamperedRows.map(auditLeaf);

  // Re-computed root differs
  assert.notEqual(merkleRoot(tamperedLeaves), root);

  // Each original proof against a tampered leaf fails
  const proof5 = merkleProof(leaves, 5);
  assert.notEqual(reconstructRoot(tamperedLeaves[5], proof5), root);
});
