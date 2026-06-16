/**
 * Least-privilege Postgres pool for the INV-8 forward attestation publisher.
 *
 * Per decision INV-8-FORWARD-SCHEDULER-001 + CAI msg #2006 §2 (Hardening A):
 * the GitHub Action authenticates with the `attestation_publisher` role over a
 * direct connection string (ATTESTATION_DB_URL) — never the service-role key.
 * Grants: SELECT ruling_audit_log; SELECT/INSERT/UPDATE daily_attestations.
 * See supabase/migrations/20260611_001_attestation_publisher_role.sql.
 */

import { Pool } from "pg";

let pool: Pool | null = null;

export function attestationPool(): Pool {
  if (pool) return pool;
  const url = process.env.ATTESTATION_DB_URL;
  if (!url) {
    throw new Error(
      "missing required env: ATTESTATION_DB_URL (attestation_publisher direct connection string)",
    );
  }
  pool = new Pool({
    connectionString: url,
    // Supabase service connections require TLS. The pooler cert is not in
    // Node's default CA bundle; rejectUnauthorized:false is Supabase's
    // documented posture for non-browser connections. Set PGSSL_STRICT=1 to
    // enforce full chain verification (requires a bundled CA).
    ssl: url.includes("sslmode=disable")
      ? false
      : { rejectUnauthorized: process.env.PGSSL_STRICT === "1" },
    max: 2,
  });
  return pool;
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
  }
}
