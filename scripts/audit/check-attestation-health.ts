#!/usr/bin/env node
/**
 * INV-8 attestation health check (CAI-RESP-165 R6d + R7).
 *
 * R6d — surface audit_key_registry + daily_attestations health.
 * R7  — CI gate: ruling_audit_log row >24h without attestation → fail boot.
 *
 * Two credential modes (CAI msg #2006 Hardening A):
 *   - ATTESTATION_DB_URL (preferred, used by the GitHub Action): least-privilege
 *     `attestation_publisher` role over a direct pg connection. This role can
 *     read ruling_audit_log + daily_attestations (everything the R7 gate needs)
 *     but is DENIED audit_key_registry by design — so the key-registry portion
 *     of the report is reported as "unknown" under this mode, not failed.
 *   - SUPABASE_SERVICE_ROLE_KEY (fuller check, run locally / by cc-orchestrator):
 *     PostgREST path with full visibility including audit_key_registry.
 * ATTESTATION_DB_URL wins if both are present.
 *
 * Output forms:
 *   --json     machine-readable for boot_briefing ingestion (cc-orchestrator R5)
 *   (default)  human-readable for terminal / CI log
 *   --strict   exit non-zero if any unattested row >24h old (R7 gate behavior)
 *
 * Usage (Action / least-privilege):
 *   ATTESTATION_DB_URL=postgresql://attestation_publisher:...@host:5432/postgres?sslmode=require \
 *     npx tsx scripts/audit/check-attestation-health.ts --strict
 * Usage (fuller local check):
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
 *     npx tsx scripts/audit/check-attestation-health.ts [--json]
 */

import { attestationPool, closePool } from "./db.ts";

const flags = new Set(process.argv.slice(2));
const asJson = flags.has("--json");
const strict = flags.has("--strict");

const usePg = !!process.env.ATTESTATION_DB_URL;
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!usePg && (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY)) {
  console.error(
    "missing credentials: set ATTESTATION_DB_URL (preferred) or SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY",
  );
  process.exit(2);
}

interface KeyRow {
  key_id: string;
  valid_from: string;
  valid_until: string | null;
}
interface AttestationRow {
  attestation_date: string;
  row_count_end: number;
}
interface AuditRow {
  id: number;
  created_at: string;
}

/** Raw data the report needs, sourced from either credential mode. */
interface RawData {
  keys: KeyRow[] | null; // null = not readable under current creds (least-privilege)
  attestations: AttestationRow[]; // attestation_date DESC
  auditCount: number;
  latestAudit: AuditRow | null;
  unattestedOlderThan24h: AuditRow[];
}

interface Health {
  key_registry: { count: number | null; active_keys: string[] | null };
  attestations: {
    total: number;
    earliest_date: string | null;
    latest_date: string | null;
    latest_row_count: number | null;
  };
  ruling_audit_log: { total: number; latest_id: number | null; latest_created_at: string | null };
  drift: {
    unattested_rows_over_24h: number;
    most_recent_attested_date: string | null;
    today_utc: string;
  };
  status: "healthy" | "degraded" | "broken";
  notes: string[];
}

const cutoffIso = (): string => new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

async function fetchViaPg(): Promise<RawData> {
  const pool = attestationPool();

  // audit_key_registry is intentionally NOT granted to attestation_publisher.
  // Probe it; on permission-denied keep keys=null (reported as "unknown").
  let keys: KeyRow[] | null = null;
  try {
    const { rows } = await pool.query<KeyRow>(
      "SELECT key_id, valid_from, valid_until FROM public.audit_key_registry ORDER BY valid_from DESC",
    );
    keys = rows;
  } catch {
    keys = null;
  }

  const { rows: attestations } = await pool.query<AttestationRow>(
    "SELECT attestation_date::text, row_count_end FROM public.daily_attestations ORDER BY attestation_date DESC",
  );

  const { rows: countRows } = await pool.query<{ count: string }>(
    "SELECT count(*)::bigint AS count FROM public.ruling_audit_log",
  );
  const auditCount = parseInt(countRows[0]?.count ?? "0", 10);

  const { rows: latestRows } = await pool.query<AuditRow>(
    "SELECT id, created_at FROM public.ruling_audit_log ORDER BY id DESC LIMIT 1",
  );
  const latestAudit = latestRows[0] ?? null;

  const { rows: unattested } = await pool.query<AuditRow>(
    "SELECT id, created_at FROM public.ruling_audit_log WHERE created_at < $1 ORDER BY id ASC",
    [cutoffIso()],
  );

  return { keys, attestations, auditCount, latestAudit, unattestedOlderThan24h: unattested };
}

async function pgrest(path: string): Promise<unknown> {
  const resp = await fetch(`${SUPABASE_URL}${path}`, {
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY as string,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
    },
  });
  if (!resp.ok) throw new Error(`${path}: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

async function fetchViaPgrest(): Promise<RawData> {
  const keys = (await pgrest(
    "/rest/v1/audit_key_registry?select=key_id,valid_from,valid_until&order=valid_from.desc",
  )) as KeyRow[];

  const attestations = (await pgrest(
    "/rest/v1/daily_attestations?select=attestation_date,row_count_end&order=attestation_date.desc",
  )) as AttestationRow[];

  const latest = (await pgrest(
    "/rest/v1/ruling_audit_log?select=id,created_at&order=id.desc&limit=1",
  )) as AuditRow[];

  const auditCountResp = await fetch(`${SUPABASE_URL}/rest/v1/ruling_audit_log?select=count`, {
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY as string,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
      Prefer: "count=exact",
    },
    method: "HEAD",
  });
  const auditCount = parseInt(
    auditCountResp.headers.get("content-range")?.split("/")[1] ?? "0",
    10,
  );

  const unattested = (await pgrest(
    `/rest/v1/ruling_audit_log?select=id,created_at&created_at=lt.${cutoffIso()}&order=id.asc`,
  )) as AuditRow[];

  return {
    keys,
    attestations,
    auditCount,
    latestAudit: latest[0] ?? null,
    unattestedOlderThan24h: unattested,
  };
}

function buildReport(raw: RawData): Health {
  const today = new Date().toISOString().slice(0, 10);
  const { keys, attestations, auditCount, latestAudit, unattestedOlderThan24h } = raw;

  const activeKeys = keys === null ? null : keys.filter((k) => k.valid_until === null).map((k) => k.key_id);

  const attestedDates = new Set(attestations.map((a) => a.attestation_date));
  const unattestedCount = unattestedOlderThan24h.filter(
    (r) => !attestedDates.has(r.created_at.slice(0, 10)),
  ).length;

  const notes: string[] = [];
  let status: Health["status"] = "healthy";

  if (activeKeys === null) {
    notes.push(
      "audit_key_registry not readable under least-privilege role (expected; run the service-role health check for key coverage)",
    );
  } else if (activeKeys.length === 0) {
    status = "broken";
    notes.push("no active signing key in audit_key_registry");
  }
  if (attestations.length === 0 && auditCount > 0) {
    status = "broken";
    notes.push(`${auditCount} ruling_audit_log rows but zero daily_attestations`);
  }
  if (unattestedCount > 0) {
    status = status === "broken" ? "broken" : "degraded";
    notes.push(`R7 breach: ${unattestedCount} ruling row(s) >24h old without attestation`);
  }
  if (attestations[0] && latestAudit) {
    const lastAttested = new Date(attestations[0].attestation_date + "T23:59:59Z");
    const lastLog = new Date(latestAudit.created_at);
    if (lastLog.getTime() - lastAttested.getTime() > 48 * 60 * 60 * 1000) {
      status = status === "broken" ? "broken" : "degraded";
      notes.push("latest ruling_audit_log row is >48h after last daily_attestation");
    }
  }

  return {
    key_registry: {
      count: keys === null ? null : keys.length,
      active_keys: activeKeys,
    },
    attestations: {
      total: attestations.length,
      earliest_date:
        attestations.length > 0 ? attestations[attestations.length - 1].attestation_date : null,
      latest_date: attestations[0]?.attestation_date ?? null,
      latest_row_count: attestations[0]?.row_count_end ?? null,
    },
    ruling_audit_log: {
      total: auditCount,
      latest_id: latestAudit?.id ?? null,
      latest_created_at: latestAudit?.created_at ?? null,
    },
    drift: {
      unattested_rows_over_24h: unattestedCount,
      most_recent_attested_date: attestations[0]?.attestation_date ?? null,
      today_utc: today,
    },
    status,
    notes,
  };
}

async function main(): Promise<void> {
  const raw = usePg ? await fetchViaPg() : await fetchViaPgrest();
  const report = buildReport(raw);
  const unattestedCount = report.drift.unattested_rows_over_24h;

  if (asJson) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    const activeKeys = report.key_registry.active_keys;
    console.log(`status: ${report.status.toUpperCase()}  (creds: ${usePg ? "attestation_publisher" : "service_role"})`);
    console.log(
      `audit_key_registry:   ${report.key_registry.count ?? "(unknown)"} row(s), active: ${
        activeKeys === null ? "(unknown)" : activeKeys.join(", ") || "(none)"
      }`,
    );
    console.log(
      `daily_attestations:   ${report.attestations.total} row(s), latest=${report.attestations.latest_date ?? "(none)"} (row_count_end=${report.attestations.latest_row_count})`,
    );
    console.log(
      `ruling_audit_log:     ${report.ruling_audit_log.total} row(s), latest_id=${report.ruling_audit_log.latest_id}, latest_at=${report.ruling_audit_log.latest_created_at}`,
    );
    console.log(`R7 drift:             ${unattestedCount} unattested row(s) older than 24h`);
    if (report.notes.length > 0) {
      console.log("notes:");
      for (const n of report.notes) console.log(`  - ${n}`);
    }
  }

  if (strict && (report.status === "broken" || unattestedCount > 0)) {
    process.exitCode = 1;
  }
}

main()
  .catch((err) => {
    console.error("health check failed:", err);
    process.exitCode = 2;
  })
  .finally(() => {
    if (usePg) return closePool();
  });
