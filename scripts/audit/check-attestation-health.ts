#!/usr/bin/env node
/**
 * INV-8 attestation health check (CAI-RESP-165 R6d + R7).
 *
 * R6d — surface audit_key_registry + daily_attestations health.
 * R7  — CI gate: ruling_audit_log row >24h without attestation → fail boot.
 *
 * Output forms:
 *   --json     machine-readable for boot_briefing ingestion (cc-orchestrator R5)
 *   (default)  human-readable for terminal / CI log
 *   --strict   exit non-zero if any unattested row >24h old (R7 gate behavior)
 *
 * Usage:
 *   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
 *     npx tsx scripts/audit/check-attestation-health.ts [--json] [--strict]
 *
 * Boot wiring (when boot_briefing source='migration_drift' lands per R5):
 *   - Also accept source='attestation_health' with the JSON shape below.
 */

const REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"] as const;
for (const k of REQUIRED_ENV) {
  if (!process.env[k]) {
    console.error(`missing required env: ${k}`);
    process.exit(2);
  }
}

const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY } = process.env as Record<
  (typeof REQUIRED_ENV)[number],
  string
>;

const flags = new Set(process.argv.slice(2));
const asJson = flags.has("--json");
const strict = flags.has("--strict");

async function pgrest(path: string): Promise<unknown> {
  const resp = await fetch(`${SUPABASE_URL}${path}`, {
    headers: {
      apikey: SUPABASE_SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
    },
  });
  if (!resp.ok) throw new Error(`${path}: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

interface Health {
  key_registry: { count: number; active_keys: string[] };
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

async function main(): Promise<void> {
  const today = new Date().toISOString().slice(0, 10);

  const keys = (await pgrest(
    "/rest/v1/audit_key_registry?select=key_id,valid_from,valid_until&order=valid_from.desc",
  )) as Array<{ key_id: string; valid_from: string; valid_until: string | null }>;

  const activeKeys = keys.filter((k) => k.valid_until === null).map((k) => k.key_id);

  const attestations = (await pgrest(
    "/rest/v1/daily_attestations?select=attestation_date,row_count_end&order=attestation_date.desc",
  )) as Array<{ attestation_date: string; row_count_end: number }>;

  const auditLog = (await pgrest(
    "/rest/v1/ruling_audit_log?select=id,created_at&order=id.desc&limit=1",
  )) as Array<{ id: number; created_at: string }>;
  const auditCountResp = await fetch(
    `${SUPABASE_URL}/rest/v1/ruling_audit_log?select=count`,
    {
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        Prefer: "count=exact",
      },
      method: "HEAD",
    },
  );
  const auditCount = parseInt(
    auditCountResp.headers.get("content-range")?.split("/")[1] ?? "0",
    10,
  );

  // R7 logic: count audit-log rows whose created_at is >24h ago and whose
  // date is NOT covered by daily_attestations.
  const attestedDates = new Set(attestations.map((a) => a.attestation_date));
  const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000);

  const unattestedOlderThan24h = (await pgrest(
    `/rest/v1/ruling_audit_log?select=id,created_at&created_at=lt.${cutoff.toISOString()}&order=id.asc`,
  )) as Array<{ id: number; created_at: string }>;
  const unattestedCount = unattestedOlderThan24h.filter(
    (r) => !attestedDates.has(r.created_at.slice(0, 10)),
  ).length;

  const notes: string[] = [];
  let status: Health["status"] = "healthy";

  if (activeKeys.length === 0) {
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
  // Forward cron didn't run for >1 day after latest log entry?
  if (attestations[0] && auditLog[0]) {
    const lastAttested = new Date(attestations[0].attestation_date + "T23:59:59Z");
    const lastLog = new Date(auditLog[0].created_at);
    if (lastLog.getTime() - lastAttested.getTime() > 48 * 60 * 60 * 1000) {
      status = status === "broken" ? "broken" : "degraded";
      notes.push("latest ruling_audit_log row is >48h after last daily_attestation");
    }
  }

  const report: Health = {
    key_registry: {
      count: keys.length,
      active_keys: activeKeys,
    },
    attestations: {
      total: attestations.length,
      earliest_date: attestations.length > 0 ? attestations[attestations.length - 1].attestation_date : null,
      latest_date: attestations[0]?.attestation_date ?? null,
      latest_row_count: attestations[0]?.row_count_end ?? null,
    },
    ruling_audit_log: {
      total: auditCount,
      latest_id: auditLog[0]?.id ?? null,
      latest_created_at: auditLog[0]?.created_at ?? null,
    },
    drift: {
      unattested_rows_over_24h: unattestedCount,
      most_recent_attested_date: attestations[0]?.attestation_date ?? null,
      today_utc: today,
    },
    status,
    notes,
  };

  if (asJson) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`status: ${status.toUpperCase()}`);
    console.log(`audit_key_registry:   ${report.key_registry.count} row(s), active: ${activeKeys.join(", ") || "(none)"}`);
    console.log(`daily_attestations:   ${report.attestations.total} row(s), latest=${report.attestations.latest_date ?? "(none)"} (row_count_end=${report.attestations.latest_row_count})`);
    console.log(`ruling_audit_log:     ${report.ruling_audit_log.total} row(s), latest_id=${report.ruling_audit_log.latest_id}, latest_at=${report.ruling_audit_log.latest_created_at}`);
    console.log(`R7 drift:             ${unattestedCount} unattested row(s) older than 24h`);
    if (notes.length > 0) {
      console.log("notes:");
      for (const n of notes) console.log(`  - ${n}`);
    }
  }

  if (strict && (status === "broken" || unattestedCount > 0)) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("health check failed:", err);
  process.exit(2);
});
