/**
 * Producer side of the INV-8 audit substrate.
 *
 * Every Al-Bayān / Al-Mīzān response that emerges from ask-scholar is
 * persisted through this function:
 *   1. INSERT into mizan_interactions  (4-tier-transparency T-1, T-6 audit row)
 *   2. INSERT into ruling_audit_log    (INV-8 hash-chain leaf)
 *
 * Both inserts are awaited before the HTTP response returns. Latency cost
 * is accepted (~50-200ms) because governance integrity outranks UX speed
 * on the ruling-emission path.
 *
 * Failures are surfaced (not swallowed) — if the audit log insert fails,
 * the function rejects and the caller chooses how to surface to the user.
 * Silently dropping ruling rows would defeat the purpose of the substrate.
 */

import type { SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2";
import { canonicalJson } from "./canonical-json.ts";
import type { QueryType } from "./query-type-classifier.ts";
import type { OutputTier } from "./compose-types.ts";

export interface PersistRulingFields {
  telegram_id_hash: string;
  thread_id?: string | null;
  bot_variant: "al-bayan" | "al-mizan";
  query_type: QueryType;
  query_text: string;
  query_lang?: string;
  response_text: string;
  output_tier: OutputTier;
  matched_passage_id?: string | null;
  retrieval_ids?: string[];
  // CAI-RESP-220: retrieval-substrate config (retriever version / path /
  // reranker / limit / cap / gate) for reproducibility. Stored on the row but
  // intentionally NOT folded into content_hash — see canonicalContent note.
  retrieval_config?: Record<string, unknown> | null;
  scholar_of_record?: string | null;
  model_name: string;
  prompt_version: string;
  retraction_of?: string | null;
}

export interface PersistRulingResult {
  interaction_id: string;
  audit_log_id: number;
  content_hash: string;
}

async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Insert a ruling emission into mizan_interactions, then chain it into
 * ruling_audit_log. Returns the new ids and the canonical content_hash.
 *
 * The ruling_audit_log trigger fills prev_hash and merkle_leaf from the
 * provided content_hash; we do not compute those client-side.
 */
export async function persistRulingEmission(
  supabase: SupabaseClient,
  fields: PersistRulingFields,
): Promise<PersistRulingResult> {
  const interactionInsert = {
    telegram_id_hash: fields.telegram_id_hash,
    thread_id: fields.thread_id ?? null,
    bot_variant: fields.bot_variant,
    query_type: fields.query_type,
    query_text: fields.query_text,
    query_lang: fields.query_lang ?? "en",
    response_text: fields.response_text,
    output_tier: fields.output_tier,
    matched_passage_id: fields.matched_passage_id ?? null,
    retrieval_ids: fields.retrieval_ids ?? [],
    retrieval_config: fields.retrieval_config ?? null,
    scholar_of_record: fields.scholar_of_record ?? null,
    model_name: fields.model_name,
    prompt_version: fields.prompt_version,
    retraction_of: fields.retraction_of ?? null,
  };

  const { data: interactionRow, error: interactionErr } = await supabase
    .from("mizan_interactions")
    .insert(interactionInsert)
    .select("id")
    .single();

  if (interactionErr) {
    throw new Error(`mizan_interactions insert failed: ${interactionErr.message}`);
  }
  const interactionId = (interactionRow as { id: string }).id;

  // Canonical content for the audit hash. Fields chosen so a verifier can
  // reproduce the hash from the row + retrieval_ids alone, without needing
  // to fetch the LLM model card or tier classifier state.
  // retrieval_config is intentionally EXCLUDED: it is reproducibility metadata
  // (CAI-RESP-220), not an integrity-bound evidence pointer. Folding it in
  // would require a lockstep audit-verify change and break hash continuity
  // across the change boundary, for no integrity gain (the config is
  // deployment-deterministic, recoverable from retriever version + git).
  const canonicalContent = {
    interaction_id: interactionId,
    bot_variant: fields.bot_variant,
    query_type: fields.query_type,
    query_text: fields.query_text,
    query_lang: fields.query_lang ?? "en",
    response_text: fields.response_text,
    output_tier: fields.output_tier,
    matched_passage_id: fields.matched_passage_id ?? null,
    retrieval_ids: (fields.retrieval_ids ?? []).slice().sort(),
    scholar_of_record: fields.scholar_of_record ?? null,
    model_name: fields.model_name,
    prompt_version: fields.prompt_version,
    retraction_of: fields.retraction_of ?? null,
  };
  const contentHash = await sha256Hex(canonicalJson(canonicalContent));

  const { data: auditRow, error: auditErr } = await supabase
    .from("ruling_audit_log")
    .insert({
      ruling_id: interactionId,
      ruling_source: "mizan_interactions",
      content_hash: contentHash,
    })
    .select("id")
    .single();

  if (auditErr) {
    throw new Error(`ruling_audit_log insert failed: ${auditErr.message}`);
  }

  return {
    interaction_id: interactionId,
    audit_log_id: (auditRow as { id: number }).id,
    content_hash: contentHash,
  };
}
