/**
 * Compose layer types — AL-BAYAN-COMPOSE-001 Constraint 3 vendor-portability surface.
 *
 * The LLMProvider protocol forward-references the wingmen-staff
 * CAI-STAFF-SPEC-001 §5.2 protocol. Once that lands, this interface is
 * the migration target. For now it lives ai-scholar-local.
 */

/**
 * The full T-1 four-tier transparency union — matches the CHECK constraint
 * on output_tier columns in mizan_interactions and ruling_audit_log per
 * the 4-tier-transparency skill (CAI-RESP-073). Used by passages from the
 * retrieval corpus AND by persist-ruling.ts insertion fields.
 *
 * Note: ComposeTier (below) is a strict subset — the compose layer cannot
 * emit 'ai-generated' per AL-BAYAN-COMPOSE-001 Amendment 1.
 */
export type OutputTier = "quoted" | "paraphrased" | "inferred" | "ai-generated";

export type ComposeTier = "quoted" | "paraphrased" | "inferred";
// Note: 'ai-generated' is FORBIDDEN in compose output per Amendment 1.
// If compose would emit ai-generated, the post-validator rejects.

export interface ComposePassage {
  passage_id: string;
  scholar_name?: string;
  source_work?: string;
  arabic_text?: string;
  english_text: string;
  // Includes 'ai-generated' (full OutputTier) because passages come from the
  // retrieval corpus where T-1 permits all four tiers. The compose layer
  // itself (ComposeTier above) excludes 'ai-generated' per Amendment 1.
  output_tier: OutputTier;
}

export interface ComposeRequest {
  query: string;
  passages: ComposePassage[];
  prompt_version: string;
}

export interface ComposeResult {
  text: string;
  tier: ComposeTier;
  cited_passage_ids: string[]; // populated by compose orchestration (Task 5) from passage_id/scholar_name mentions in text
  ayah_violations: string[]; // empty on success
  latency_ms: number;
  provider: string; // populated from LLMProvider.name
  prompt_version: string;
}

export interface LLMProvider {
  name: string;
  generate(req: ComposeRequest): Promise<{ text: string; latency_ms: number }>;
}
