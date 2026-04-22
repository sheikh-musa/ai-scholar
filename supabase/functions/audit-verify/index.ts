/**
 * INV-8 audit verification endpoint.
 *
 * GET /audit-verify?ruling_id=<uuid>
 *   Returns the ruling_audit_log row for the ruling, plus the Merkle proof
 *   path up to the most recent daily_attestations root, plus that
 *   attestation row. Caller verifies:
 *     1. content_hash matches their canonical serialization of the ruling.
 *     2. prev_hash chains backward correctly by sequential fetch.
 *     3. merkle_leaf is reconstructible from content_hash/prev_hash/id/created_at.
 *     4. merkle_leaf appears in the attestation's root via the proof path.
 *     5. root_signature verifies against the public key at
 *        https://{domain}/.well-known/audit-key.json under the attestation's key_id.
 *
 * Endpoint is anon-readable because audit should be permissionless.
 */

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

async function sha256Hex(...parts: string[]): Promise<string> {
  const data = new TextEncoder().encode(parts.join(""));
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

interface AuditRow {
  id: number;
  ruling_id: string;
  ruling_source: string;
  content_hash: string;
  prev_hash: string;
  merkle_leaf: string;
  created_at: string;
}

/** Compute the Merkle proof path for a leaf at `index` in `leaves`. */
async function merkleProof(leaves: string[], index: number): Promise<Array<{ hash: string; side: "L" | "R" }>> {
  const proof: Array<{ hash: string; side: "L" | "R" }> = [];
  let level = leaves.slice();
  let i = index;
  while (level.length > 1) {
    const next: string[] = [];
    for (let j = 0; j < level.length; j += 2) {
      const left = level[j];
      const right = level[j + 1] ?? left;
      next.push(await sha256Hex(left, right));
    }
    const pairIndex = i % 2 === 0 ? i + 1 : i - 1;
    const sibling = level[pairIndex] ?? level[i];
    proof.push({ hash: sibling, side: i % 2 === 0 ? "R" : "L" });
    i = Math.floor(i / 2);
    level = next;
  }
  return proof;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }

  const url = new URL(req.url);
  const rulingId = url.searchParams.get("ruling_id");
  if (!rulingId) {
    return json({ error: "ruling_id query param required" }, 400);
  }

  // 1. Fetch the audit row for this ruling.
  const { data: auditRow, error: auditErr } = await supabase
    .from("ruling_audit_log")
    .select("id, ruling_id, ruling_source, content_hash, prev_hash, merkle_leaf, created_at")
    .eq("ruling_id", rulingId)
    .maybeSingle();

  if (auditErr) return json({ error: auditErr.message }, 500);
  if (!auditRow) return json({ error: "ruling not found" }, 404);
  const audit = auditRow as AuditRow;

  // 2. Find the most recent attestation that covers this row (row_count_end >= audit.id).
  const { data: attestation, error: attErr } = await supabase
    .from("daily_attestations")
    .select("attestation_date, row_count_end, root_hash, root_signature, key_id, git_commit_hash")
    .gte("row_count_end", audit.id)
    .order("attestation_date", { ascending: true })
    .limit(1)
    .maybeSingle();

  if (attErr) return json({ error: attErr.message }, 500);
  if (!attestation) {
    return json({ error: "no attestation covers this row yet; retry after next nightly publish" }, 202);
  }

  // 3. Fetch all leaves up to row_count_end, build proof.
  const { data: leaves, error: leavesErr } = await supabase
    .from("ruling_audit_log")
    .select("id, merkle_leaf")
    .lte("id", attestation.row_count_end)
    .order("id", { ascending: true });

  if (leavesErr) return json({ error: leavesErr.message }, 500);

  const leafHashes = (leaves ?? []).map((r) => (r as { merkle_leaf: string }).merkle_leaf);
  const idx = (leaves ?? []).findIndex((r) => (r as { id: number }).id === audit.id);
  if (idx < 0) return json({ error: "internal: audit row not in leaves slice" }, 500);

  const proof = await merkleProof(leafHashes, idx);

  return json({
    audit_row: audit,
    attestation,
    proof,
    verifier_instructions: {
      "1_content_hash": "Re-serialize the ruling using the canonical serializer and SHA-256 it — must equal audit_row.content_hash.",
      "2_chain": "Walk backward through audit_log id order; each row's prev_hash must equal the previous row's content_hash. Genesis is 64 zeros.",
      "3_leaf": "Recompute merkle_leaf = SHA-256(content_hash || prev_hash || id || created_at-iso).",
      "4_root": "Apply the proof path to the leaf and confirm it reconstructs attestation.root_hash.",
      "5_signature": "Verify attestation.root_signature (Ed25519) over attestation.root_hash using the public key at /.well-known/audit-key.json for key_id.",
    },
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}
