#!/usr/bin/env node
/**
 * Generate an Ed25519 audit signing keypair for INV-8 Postgres-Merkle
 * fallback substrate.
 *
 * Usage:
 *   npx tsx scripts/audit/generate-signing-key.ts [--key-id <id>]
 *
 * Output:
 *   1. Private key written to stdout as base64 — ONLY capture into secure
 *      secret manager / .env of the orchestrator. Never commit.
 *   2. Public key + key_id written to .well-known/audit-key.json
 *      (publish this file on Al-Bayān's domain).
 *   3. INSERT statement for audit_key_registry printed to stdout as SQL
 *      for the operator to run on the orchestrator Supabase project.
 *
 * Key rotation: run this script again with a new --key-id; run the INSERT
 * AND update the prior key's valid_until column.
 */

import { generateKeyPairSync } from "node:crypto";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { argv } from "node:process";

function parseArgs() {
  const args = new Map<string, string>();
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (key?.startsWith("--") && value) args.set(key.slice(2), value);
  }
  return args;
}

function nowIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function main() {
  const args = parseArgs();
  const keyId = args.get("key-id") ?? `al-bayan-audit-${nowIsoDate()}`;

  const { publicKey, privateKey } = generateKeyPairSync("ed25519");

  const privateKeyB64 = privateKey.export({ format: "der", type: "pkcs8" }).toString("base64");
  const publicKeyB64 = publicKey.export({ format: "der", type: "spki" }).toString("base64");

  const wellKnownPath = resolve(process.cwd(), ".well-known/audit-key.json");
  mkdirSync(dirname(wellKnownPath), { recursive: true });
  writeFileSync(wellKnownPath, JSON.stringify({
    key_id: keyId,
    algorithm: "Ed25519",
    public_key_b64: publicKeyB64,
    format: "spki-der-base64",
    generated_at: new Date().toISOString(),
  }, null, 2));

  console.log("=".repeat(72));
  console.log("Ed25519 keypair generated for INV-8 audit substrate");
  console.log("=".repeat(72));
  console.log();
  console.log(`key_id: ${keyId}`);
  console.log();
  console.log("PRIVATE KEY (base64, pkcs8-der) — install into orchestrator env:");
  console.log(`  ORCHESTRATOR_AUDIT_SIGNING_KEY='${privateKeyB64}'`);
  console.log("  (do not commit; do not paste in chat; do not log in app code)");
  console.log();
  console.log(`PUBLIC KEY written to: ${wellKnownPath}`);
  console.log("  Publish this file at https://al-bayan.{domain}/.well-known/audit-key.json");
  console.log();
  console.log("RUN on orchestrator Supabase (audit_key_registry):");
  console.log(
    `  INSERT INTO public.audit_key_registry (key_id, public_key_b64, valid_from)\n` +
    `    VALUES ('${keyId}', '${publicKeyB64}', now());\n`
  );
  console.log("If this is a rotation, also update the prior key:");
  console.log(
    `  UPDATE public.audit_key_registry\n` +
    `    SET valid_until = now(), rotation_reason = '<reason>'\n` +
    `    WHERE key_id = '<prior-key-id>';\n`
  );
}

main();
