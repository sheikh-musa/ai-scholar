# Hook #10 — 4-tier-transparency

**Paired skill:** `.claude/skills/4-tier-transparency/SKILL.md`
**Decision:** CAI-RESP-073 (hook taxonomy extension)
**Owner:** cc-scholar (spec), cc-ihsanos (implementation per CAI-RESP-069)
**Severity:** CRITICAL — fail-closed. Tier collapse ships ai-generated content as quoted / silences INV-3.

## Invariants enforced

- **T-1** `output_tier` column is NOT NULL with CHECK constraint on every output-bearing table.
- **T-2** Every response-shaping function assigns `tier` on every return path.

## Trigger paths

Hook fires on:

1. **pre-commit** in ai-scholar when any of the following are staged:
   - `supabase/migrations/*.sql`
   - `supabase/functions/ask-scholar/**`
   - `scripts/albayan_bot.py`
   - `scripts/mizan_bot.py`
2. **pre-Edit** on response-shaping files.

## Check 1 — output_tier NOT NULL on new output-bearing tables

Parse staged `.sql` migration files. Heuristic for "output-bearing": CREATE TABLE whose column set includes any of `response_text`, `answer_text`, `output`, `emission`, `matched_passage`, or the table name contains `_interactions` / `_responses` / `_emissions` / `_rulings`.

For each such CREATE TABLE, verify:

```sql
-- Required:
output_tier text NOT NULL CHECK (output_tier IN ('quoted','paraphrased','inferred','ai-generated'))
```

Fail if:
- Missing `output_tier` column entirely.
- Column present but NULLABLE.
- Column present without CHECK constraint on the 4-value enum (other CHECK sets also fail — enum is fixed).

Also check ALTER TABLE migrations:
- `ALTER TABLE ... ALTER COLUMN output_tier DROP NOT NULL` → REJECT.
- `ALTER TABLE ... DROP CONSTRAINT <check_output_tier>` → REJECT unless immediately paired with a new CHECK covering the same 4 values.

On failure:

```
REFUSED: 4-tier-transparency T-1 invariant violated.
  Migration: <path>
  Table: <name>
  <specific-missing-element>
  Every output-bearing table carries output_tier NOT NULL with the 4-value
  CHECK. Tier collapse is a system error, not a UX choice.
  See skills/4-tier-transparency/SKILL.md T-1.
```

## Check 2 — `tier` assigned on every return path in response shapers

Static analysis on staged `.ts` / `.py` files matching:
- `supabase/functions/ask-scholar/**`
- `scripts/*_bot.py`
- any file under `supabase/functions/` exporting a `formatResponse` / `shapeResponse` / `buildResponse` / `answer` function.

For each such function:

1. Identify return-statement line numbers.
2. For each `return` statement that returns an object literal (TypeScript) or dict (Python):
   - Must include a key `tier` with a string value that is one of the four enum values, OR
   - Must assign to a `tier` variable earlier in the function and return an object that spreads or references that variable.
3. For each `return` that returns a non-object (e.g., Response wrapping JSON.stringify):
   - The serialized object passed to the serializer must itself include `tier`.

Regex (TypeScript, starting point):

```regex
return\s+\{[^}]*\btier\s*:\s*['"](quoted|paraphrased|inferred|ai-generated)['"][^}]*\}
# OR shape: return { ...shape, tier };
return\s+\{[^}]*\btier\b[^}]*\}
```

On failure:

```
REFUSED: 4-tier-transparency T-2 invariant violated.
  File: <path>
  Function: <name>
  Return at line <N> does not assign `tier`.
  Every response-shaping function assigns tier on every return path. Missing
  tier = rendering falls back to red "UNVERIFIED" badge, which is catching a
  real problem — but the problem is here, not downstream.
  See skills/4-tier-transparency/SKILL.md T-2.
```

## Test matrix

| Input | Expected |
|---|---|
| Migration: `CREATE TABLE public.new_output (... output_tier text NOT NULL CHECK (output_tier IN ('quoted','paraphrased','inferred','ai-generated')), ...)` | PASS |
| Migration: `CREATE TABLE public.new_responses (... output_tier text, ...)` (nullable) | REJECT T-1 |
| Migration: `CREATE TABLE public.new_emissions (...)` without output_tier column | REJECT T-1 |
| Migration: `CREATE TABLE public.user_profiles (...)` (not output-bearing) | PASS (heuristic doesn't trigger) |
| TS function returning `{ query_type, body, tier: "inferred", ... }` | PASS |
| TS function returning `{ query_type, body, ... }` (missing tier) | REJECT T-2 |
| TS function: `const tier = classify(...); return { body, tier };` | PASS |
| Test file under `__tests__/**` returning `{ body: 'x' }` without tier | PASS (test path exempt) |

## Edge cases

1. **Typed return with spread.** `return { ...base, additional }` — if `base` is typed as `{ tier: string; ... }` in scope, pass. Check requires simple type-threading; implementer can escalate to full TypeScript compiler API if regex false-positives become noisy.
2. **Builder pattern.** `const response = new ResponseBuilder().tier('inferred').build();` — grep for `.tier(` method call in builder chains; pass if found.
3. **Python TypedDict.** `return cast(ScholarResponse, {"body": ..., "tier": "inferred"})` — grep for `"tier"` or `'tier'` key in returned dict literals.
4. **Empty file edits / doc-only changes.** If the file has no net change to functions emitting responses, do not re-check.

## Failure recovery

```bash
SKIP_4TIER_TRANSPARENCY_HOOK=1 git commit ...
# with trailer
git commit -m "..." --trailer 'Tier-Override: <decision_ref>'
```

## Not enforced here (out of scope)

- T-3 tier-promotion-requires-evidence (runtime check against retrieval rows; belongs in response-shape assertion or judge pipeline).
- T-4 INV-6 action_prompt gating — covered by the query-type classifier in `supabase/functions/_shared/query-type-classifier.ts` and its tests.
- T-5 no-mixed-tiers-in-body (runtime structural check).
- T-6 retraction-is-new-row (schema-level via `retraction_of` FK; covered by migrations inspected in Check 1 heuristic).
