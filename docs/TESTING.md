# Testing — ai-scholar

How to run the suites locally, and what CI runs. The CI definition is
`.github/workflows/tests.yml` (added 2026-07-08); this doc mirrors it so local
runs and CI stay in agreement.

## What runs where

| Suite | Runner | CI job | Needs |
|---|---|---|---|
| Python unit tests | `python3` | `python` | `requests`, `python-dotenv` |
| Merkle audit harness | `node --test` | `node` | Node 20+ |
| Edge Function tests | `deno test` | `deno` | Deno v2.x |

The two **live-integration** harnesses are intentionally NOT in CI — they hit
the live `ask-scholar` Edge Function / prod DB / Claude CLI and write real audit
rows. Run them by hand only, against a throwaway identity:
- `scripts/test_ask_scholar.py` — POSTs to the deployed function (needs `SUPABASE_ANON_KEY`)
- `scripts/test_mizan_bot_e2e.py` — drives `gather_context`+`ask_claude`+`persist_emission` (writes prod rows)

## Python

```bash
python3 -m pip install --user requests python-dotenv   # one-time
for t in \
  test_mizan_judge test_cli_failure_classification test_safety_classes \
  test_scholar_review_flag test_tafsir_verse_routing test_chat_state_persistence \
  test_evidence_fallback test_fts_relevance_floor; do
  python3 "scripts/$t.py"
done
```

All 8 are offline (no Supabase, no Claude CLI). A couple import `mizan_bot`, whose
only third-party import at load time is the local `*_semantic` modules; they
resolve without the encoder service running.

**Python version note:** the scripts target the repo's system Python (3.9 on the
dev Mac). Any script using PEP 604 union annotations (`dict | list`, `str | None`)
in a `def` signature MUST start with `from __future__ import annotations`, or it
raises `TypeError` at import under 3.9. This is enforced only by convention —
keep it in mind when adding a script.

## Node (audit / Merkle)

```bash
node --test scripts/audit/__tests__/merkle.test.mjs
```

## Deno (Edge Functions)

`deno` is not installed on the dev Mac by default — install it (`brew install deno`
or https://deno.land) or rely on CI. Deno tests import their unit-under-test
directly, never `ask-scholar/index.ts` (which starts `Deno.serve` at module
load). If you need to test a helper that lives in `index.ts`, extract it to
`_shared/` first — see `_shared/fts-relevance.ts` / `_shared/query-type-classifier.ts`
for the pattern.

```bash
deno test --allow-all supabase/functions/
```

## Parity invariants

Two pieces of logic are ported across Python and TypeScript and MUST stay in
lockstep — each has a test on both sides mirroring the same cases:

- **FTS relevance floor** — `_shared/fts-relevance.ts` (`ftsTopical`) ⇄
  `scripts/mizan_bot.py` (`_fts_topical`). Tests: `_shared/__tests__/fts-relevance.test.ts`
  and `scripts/test_fts_relevance_floor.py`.
- **Query-type classifier** — `_shared/query-type-classifier.ts`. Test:
  `_shared/__tests__/query-type-classifier.test.ts` (the Python side routes
  through the same TS via the Edge Function; the classifier itself is TS-only).

If you change one side of a ported pair, change the other and both test files.
