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

## Check — LLM-call must be preceded by search_tafsir_fts in the same FILE

Static analysis, no runtime required. v0 enforcement is file-level; v1 will tighten to same-function once cross-file AST is feasible. For each staged file:

1. Parse the file (regex-based is acceptable for v0; proper AST is better v1).
2. Detect presence of LLM-SDK invocations anywhere in the file:
   - TypeScript: `.messages.create(`, `.chat.completions.create(`, `.generateContent(`, or any call to an imported LLM client.
   - Python: `anthropic.Anthropic().messages.create(`, `openai.ChatCompletion.create(`, `genai.GenerativeModel(...).generate_content(`, or subprocess invocation of `claude -p` (CLI as LLM proxy).
3. If ≥ 1 LLM-call found:
   a. Find any `supabase.rpc('search_tafsir_fts', ...)` OR `search_tafsir_fts(` typed call OR Python `supabase_rpc("search_tafsir_fts", ...)` anywhere in the file.
   b. Fail if no such call exists.
4. Files matching `**/*.test.*`, `**/*.spec.*`, `**/__tests__/**`, `**/fixtures/**` are exempt.

**v0 rationale:** file-level check catches the architecturally-significant case ("a file that talks to an LLM about Islamic content must also do retrieval"). Same-function ordering is harder to prove statically when retrieval is delegated to a helper and the LLM call is in a handler — both are common patterns (see mizan_bot.py where `gather_context()` does retrieval and the main loop calls `ask_claude()`). The spirit of F-1 is upheld at file-level; strict function-level is a v1 tightening when AST tooling lands.

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

## Test matrix (for cc-ihsanos hook implementer) — v0 file-level

| Input | Expected outcome |
|---|---|
| `ask-scholar/index.ts` with `supabase.rpc('search_tafsir_fts', ...)` somewhere AND `anthropic.messages.create(...)` somewhere | PASS |
| `ask-scholar/index.ts` with LLM call and NO `search_tafsir_fts` anywhere | REJECT |
| `scripts/mizan_bot.py` with `search_tafsir_fts` in one function and `claude -p` subprocess call in another (e.g., handler calls gather_context which calls retrieval; main loop calls ask_claude) | PASS (file-level, v0) |
| `__tests__/ask-scholar.test.ts` mocking the LLM client | PASS (test paths exempt) |
| `scripts/smoke_tafsir_fts.sh` — shell script, no LLM SDK imported | PASS (no LLM call, no check fires) |
| Newly-added `scripts/no_retrieval_bot.py` that imports anthropic and calls `.messages.create(...)` but has no search_tafsir_fts | REJECT |

## Edge cases

1. **Non-LLM imports.** The `@supabase/supabase-js` import itself is not an LLM. Only the listed SDKs count.
2. **Indirect LLM calls via helper.** At v0 (file-level), the hook only inspects the file being edited. Retrieval can be delegated to helper functions within the same file; the hook is satisfied. Cross-file delegation (e.g., helper imported from another module that does retrieval) is NOT caught at v0 — skill authors must keep retrieval + synthesis in the same file at minimum. v1 upgrade path: cross-file AST traversal.
3. **Streaming SDK calls.** `.messages.stream(` counts as an LLM call.
4. **Tool-use LLM flows.** An LLM call made inside a tool-use callback still counts — retrieval must exist somewhere in the same file.
5. **Claude CLI subprocess.** `subprocess.run([CLAUDE_BIN, "-p", ...])` is counted as an LLM call (matches the python bot pattern). Hook grep includes the CLAUDE_BIN pattern or a bare `claude` command with `-p`.

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
