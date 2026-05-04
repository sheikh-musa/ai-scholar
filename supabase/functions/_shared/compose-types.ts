/**
 * Compose layer types — AL-BAYAN-COMPOSE-001 Constraint 3 vendor-portability surface.
 *
 * The LLMProvider protocol forward-references the wingmen-staff
 * CAI-STAFF-SPEC-001 §5.2 protocol. Once that lands, this interface is
 * the migration target. For now it lives ai-scholar-local.
 */

export type ComposeTier = "quoted" | "paraphrased" | "inferred";
// Note: 'ai-generated' is FORBIDDEN in compose output per Amendment 1.
// If compose would emit ai-generated, the post-validator rejects.

export interface ComposePassage {
  passage_id: string;
  scholar_name?: string;
  source_work?: string;
  arabic_text?: string;
  english_text: string;
  output_tier: "quoted" | "paraphrased" | "inferred" | "ai-generated";
}

export interface ComposeRequest {
  query: string;
  passages: ComposePassage[];
  prompt_version: string;
}

export interface ComposeResult {
  text: string;
  tier: ComposeTier;
  cited_passage_ids: string[];
  ayah_violations: string[]; // empty on success
  latency_ms: number;
  provider: string;
  prompt_version: string;
}

export interface LLMProvider {
  name: string;
  generate(req: ComposeRequest): Promise<{ text: string; latency_ms: number }>;
}
