---
name: 4-tier-transparency
description: Invoke this skill BEFORE any edit to tafsir_entries / mizan_interactions schema, response-shaping code in supabase/functions/ask-scholar/** or scripts/*_bot.py, or any CI gate on scholar-class output. Enforces INV-3 (Quoted / Paraphrased / Inferred / AI-Generated tier tags required on every response, NOT NULL at the data model, no mixed tiers in a single body) and the INV-6 action_prompt carve-out (required iff query_type = "ruling"; null for definition / biography / language-clarification / madhhab-identification).
---

# Four-Tier Transparency

Every output emitted by Al-Bayān carries its epistemic tier. Tier collapse — shipping a paraphrase as a quote, or an AI-generated synthesis as a paraphrase — is a system error, not a UX choice. Per VISION-003 INV-3, this is enforced at the data model.

## The Four Tiers

| Tier | Meaning | Example |
|---|---|---|
| **quoted** | Verbatim text from a named primary source (Qur'an ayah, hadith matn, named scholar's work) | "Ibn Kathir, Tafsir al-Qur'an al-'Azim: '…'" |
| **paraphrased** | Summary in the bot's words of a specific named source | "Ibn Kathir explains that this ayah refers to…" |
| **inferred** | Synthesized from multiple retrieved sources with attribution | "Ibn Kathir and Al-Sa'di both emphasize … (see sources)" |
| **ai-generated** | Model-produced text not grounded in a retrieved source (refusal, clarification, conversational) | "I can help you find tafsir on this topic. Could you clarify…?" |

## Hard Invariants

**T-1 — `output_tier` column is NOT NULL.**
`tafsir_entries.output_tier`, `mizan_interactions.output_tier`, and any table persisting scholar-class output carries a NOT NULL `output_tier text CHECK (output_tier IN ('quoted','paraphrased','inferred','ai-generated'))` column. Migrations that add an output-bearing table without this column fail review.

**T-2 — Every response shape carries `tier`.**
The in-flight response object (not just the persisted row) includes `tier`. Front-end badge rendering is downstream of this field. Missing `tier` = rendering fails open with a red "UNVERIFIED" badge, never silently defaults to a lower tier.

**T-3 — Tier promotion requires evidence.**
A response cannot be tagged `quoted` unless the exact verbatim string appears in a retrieved row (exact match post-NFC-normalization). `paraphrased` requires a single named source ID. `inferred` requires ≥2 retrieved source IDs. `ai-generated` is the floor — any output without retrieval grounding defaults here.

**T-4 — INV-6 carve-out: action prompt gated by query type.**
Per CAI-RESP-062, the 'ilm→'amal CI gate (action_prompt required) fires ONLY on `query_type == "ruling"`. For `query_type ∈ {definition, biography, language-clarification, madhhab-identification}`, `action_prompt` is explicitly `null` — not a blank string, not a fabricated "recite this" pad. Implementer uses the query-type classifier (see `tafsir-defense-funnel` F-3) to route.

**T-5 — No mixed tiers in a single response body.**
If a response quotes part of an ayah and paraphrases surrounding context, the response is structured as a list of tiered segments, not a single prose blob with one umbrella tier. Schema: `body_segments: { tier, text, source_id | null }[]`.

**T-6 — Retraction emits a new tiered row, does not overwrite.**
Per MIZAN-EVAL-001 amendment (retract-block is gated on judge calibration, but when retract lands), a retraction is a NEW `mizan_interactions` row with `tier='ai-generated'`, `retraction_of: <prior_id>`, linked via thread. The original row is preserved for audit (Islamic-amanah ledger integrity, per VISION-003 INV-8).

## Validation

`scripts/validate_4tier_transparency.sql` runs:
```sql
-- T-1 check
SELECT table_name FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name = 'output_tier'
  AND is_nullable = 'YES';
-- Must return 0 rows

-- T-1 check: tier CHECK constraint present
SELECT conname FROM pg_constraint
WHERE conrelid::regclass::text IN ('tafsir_entries','mizan_interactions')
  AND pg_get_constraintdef(oid) LIKE '%output_tier%';
-- Must return ≥1 row per table
```

And `scripts/validate_4tier_transparency.sh` greps response-shaping code for `tier:` assignment on every return path.

## Worked Example

```ts
// ✅ Correct: tier drives shape
if (!retrieval.data?.length) {
  return { tier: "ai-generated", body, action_prompt: null, /* query_type classifier ran, not a ruling */ };
}
if (retrieval.data.length === 1 && isVerbatim(body, retrieval.data[0].english_text)) {
  return { tier: "quoted", body, source_id: retrieval.data[0].id };
}
if (retrieval.data.length >= 2) {
  return { tier: "inferred", body, source_ids: retrieval.data.map(r => r.id) };
}
return { tier: "paraphrased", body, source_id: retrieval.data[0].id };

// ❌ Violation: static tier regardless of evidence
return { tier: "quoted", body: claude_synthesis }; // synthesis is not quoted — tier collapse
```

## References

- VISION-003 INV-3 — constitutional source of this skill
- CAI-RESP-062 — INV-6 carve-out accepted (T-4)
- CAI-MIZAN-EVAL-001 — rubric axes `tier_integrity`, `source_attribution` are auto-judge proxies for these invariants
- `supabase/migrations/20260419_001_search_tafsir_fts.sql` — RPC returns `output_tier` already
