# Hook #8 — tafsir-defense-funnel

**Paired skill:** `.claude/skills/tafsir-defense-funnel/SKILL.md`
**Decision:** CAI-RESP-073 (hook taxonomy extension)
**Owner:** cc-scholar (spec), cc-ihsanos (implementation per CAI-RESP-069)
**Severity:** CRITICAL — fail-closed. Bypassing search_tafsir_fts = LLM hallucinates fatwa-grade content.

## Invariant enforced

- **F-1** `search_tafsir_fts` executes before any LLM synthesis call on any scholar-class query path.

## Trigger paths

Hook fires on:

1. **pre-Edit** (Claude Code hook) when an LLM is about to write to any of:
   - `supabase/functions/ask-scholar/**`
   - `scripts/albayan_bot.py`
   - `scripts/mizan_bot.py`
   - any file under `supabase/functions/` that imports `anthropic` / `openai` / `google-generativeai` / `@anthropic-ai/sdk`
2. **pre-commit** in ai-scholar when any of the above paths are staged.

## Check — LLM-call must be preceded by search_tafsir_fts in same function

Static analysis, no runtime required. For each staged file:

1. Parse the file (regex-based is acceptable for v0; proper AST is better v1).
2. For each function definition (`function`, `async function`, `const foo = async (`, `def foo`):
   a. Find line numbers of LLM-SDK invocations inside the function body:
      - TypeScript: `.messages.create(`, `.chat.completions.create(`, `.generateContent(`, or any call to an imported LLM client.
      - Python: `anthropic.Anthropic().messages.create(`, `openai.ChatCompletion.create(`, `genai.GenerativeModel(...).generate_content(`.
   b. If ≥ 1 LLM-call line found:
      i. Find line numbers of `supabase.rpc('search_tafsir_fts', ...)` OR equivalent (`search_tafsir_fts(` as a typed function call) inside the same function.
      ii. Fail if no such call exists, OR if its line number is ≥ the first LLM-call line.
3. Files matching `**/*.test.*`, `**/*.spec.*`, `**/__tests__/**`, `**/fixtures/**` are exempt.

On failure the hook prints:

```
REFUSED: tafsir-defense-funnel F-1 invariant violated.
  File: <path>
  Function: <name>
  LLM call at line <N> is not preceded by search_tafsir_fts in same function.
  Al-Bayān never lets an LLM speak first on tafsir. Call the RPC first, feed
  retrieval rows to the LLM, overlay matched_passage in the response shape.
  See skills/tafsir-defense-funnel/SKILL.md F-1..F-2.
```

## Test matrix (for cc-ihsanos hook implementer)

| Input | Expected outcome |
|---|---|
| `ask-scholar/index.ts` with `supabase.rpc('search_tafsir_fts', ...)` at line 100 and `anthropic.messages.create(...)` at line 150 inside same function | PASS |
| `ask-scholar/index.ts` with LLM call at line 80 and no `search_tafsir_fts` | REJECT |
| `ask-scholar/index.ts` with `search_tafsir_fts` at line 120 and LLM call at line 80 (wrong order inside same function) | REJECT |
| `ask-scholar/index.ts` with `search_tafsir_fts` in one function and LLM call in a different function | REJECT (each LLM-call function needs its own preceding RPC call) |
| `__tests__/ask-scholar.test.ts` mocking the LLM client | PASS (test paths exempt) |
| `scripts/mizan_bot.py` that composes both via a helper `handle_query()` calling `retrieve_tafsir_fts()` then `claude.messages.create()` | PASS |
| `scripts/smoke_tafsir_fts.sh` — shell script, no LLM SDK imported | PASS (no LLM call, no check fires) |

## Edge cases

1. **Non-LLM imports.** The `@supabase/supabase-js` import itself is not an LLM. Only the listed SDKs count.
2. **Indirect LLM calls via helper.** If a file imports a helper that eventually calls an LLM, the hook only inspects the file being edited. This is a known blind spot; v1 may add cross-file AST. For v0, skill authors are expected to keep retrieval + synthesis in the same file at minimum.
3. **Streaming SDK calls.** `.messages.stream(` counts as an LLM call.
4. **Tool-use LLM flows.** An LLM call made inside a tool-use callback still counts — retrieval must precede the outer LLM call.

## Failure recovery

If hook fires in error (e.g., migration to a new retrieval mechanism that legitimately replaces `search_tafsir_fts`), override with:

```bash
SKIP_TAFSIR_DEFENSE_FUNNEL_HOOK=1 git commit ...
```

Override requires accompanying `strategic_decisions` entry naming the new retrieval RPC and plan to update this hook to recognize it.

## Not enforced here (out of scope)

- F-2 `matched_passage` overlay (checked at response-shape-assertion, a different invariant) — candidate for a response-shape hook (future #11 if needed).
- F-3 scholar-gate routing on ruling queries (runtime check; cannot static-analyze without running the classifier).
- F-4 no-hallucinated-isnad (requires LLM output comparison; belongs in `mizan_auto_scores` judge pipeline).
