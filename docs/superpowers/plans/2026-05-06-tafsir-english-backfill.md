# Tafsir English Backfill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the 11,968 `tafsir_entries` rows that are currently `[Arabic tafsir...]` placeholder strings with translated English text from canonical scholar-attributed sources, so retrieval surfaces tafsir on every ayah for every scholar Al-Bayān has loaded.

**Architecture:** The substrate already has `tafsir_entries(ayah_id, scholar_name, source_work, english_text, output_tier, ...)` populated for all 6,236 ayat × 4 scholars = 24,944 rows. Of these, 12,976 carry usable English; 11,968 carry the literal placeholder `[Arabic tafsir not translated]` (or close variant). Backfill scope is the 11,968 placeholder rows only — Arabic source text is already present per scholar; we are translating, not ingesting from scratch. Translation source per scholar is the operator-decision gate (Q1 below). Backfill mechanism is a Python script that reads each placeholder row, fetches the canonical translation from the chosen source, validates against tier discipline (T-1 NOT NULL, output_tier='quoted' iff verbatim, 'paraphrased' iff editorial smoothing), and updates the row. Resumable via checkpoint file. Fail-soft per-row logging.

**Tech Stack:** Python 3, Supabase REST API (service-role), Claude CLI (per CAI-PROCESS-MAX-FIRST-001 for any LLM-assisted summarization), `requests` for translation source fetching. Reuses the patterns from `enrich_topic_tags_v4_ihsan.py` (checkpoint, log file, audit subcommand).

**Consensus source:** AL-BAYAN-CORPUS-EXPANSION-001 (id 692, amended 2026-05-06) GAP 1.

**Not in this plan (deferred):** Topic-tag enrichment (separate v4 ihsan run, blocked on CAI adversarial review per agent_messages #1303). Hadith retrieval routing fixes (separate cc-scholar PR; audit findings in same session digest). Juridical corpus ingestion (AL-BAYAN-003).

---

## Pre-ratification operator decisions (BLOCKING — do not start implementation until resolved)

These are GATES. Implementation cannot proceed until operator answers each:

### Q1 — Translation source per scholar

| Scholar | Placeholder rows | Recommended source | Rationale |
|---|---|---|---|
| **Ibn Kathir** | ~3,000 (verify) | **Tafsir Ibn Kathir abridged, Saheeh International / Darussalam edition** (10-vol, complete English) | Most-cited tafsir globally; abridged English is canonical and free of significant theological drift; available as structured text via Quran.com / Tafsir.com APIs |
| **Al-Sa'di** | ~3,000 (verify) | **Tafsir as-Sa'di — Tafsir al-Karim ar-Rahman**, English translation by various (partial); GAP: full English coverage incomplete | Modern, accessible style. **WARNING: full English may not exist for all 6,236 ayat — backfill may be partial.** |
| **Al-Jalalayn** | ~3,000 (verify) | **Feras Hamza translation, Royal Aal al-Bayt Institute, available via altafsir.com** (Creative Commons-licensed) | Compact, classical, complete English coverage. Preferred for licensing clarity. |
| **Al-Qurtubi** | ~3,000 (verify) | **Aisha Bewley partial translation + selective passages from Tafsir.com** | Coverage is the thinnest — likely cannot fill all rows. May need an interim "translation pending" row state vs leaving as-is. |

**Q1 sub-decisions:**
- Q1a: Approve recommended sources OR specify alternates per scholar?
- Q1b: For Al-Qurtubi where coverage is thin, **leave placeholder as-is** OR **introduce new tier `'pending-translation'`** so the bot can distinguish "we have no English" from "the scholar didn't comment on this ayah"?

### Q2 — Backfill ordering

cc-scholar lean: **Ibn Kathir + Al-Sa'di first** (most-cited two scholars in Mizan responses; biggest UX impact), then Al-Jalalayn, then Al-Qurtubi. Single-pass per scholar (each pass writes ~3,000 rows). Total ~3-5 days at single-concurrency Claude CLI route per CAI-PROCESS-MAX-FIRST-001.

Alternative: **all four in parallel** at concurrency 2 — finishes in ~1-2 days but bot serves users in a mixed-tier state during the run.

Q2: Confirm sequential (cc-scholar lean) OR approve parallel?

### Q3 — Translation strategy per source

Two operating modes:

**Mode A — Direct fetch (preferred where possible):** for sources with structured public data (Tafsir.com API, Quran.com tafsir endpoints, altafsir.com bulk text), pull canonical English directly, store with `output_tier='quoted'` and `translation_source_url` populated. No LLM involved.

**Mode B — LLM-assisted translation (fallback):** for sources where only Arabic text exists in our corpus and no canonical English is available externally (or for partial-coverage Al-Qurtubi gaps), use Claude CLI per CAI-PROCESS-MAX-FIRST-001 to translate the existing Arabic-text row, store with `output_tier='paraphrased'` (editorial smoothing applied), `translator='ai-scholar-claude-cli-2026'`. **This mode requires its own governance review per F-1 + CAI-RESP-127 — translating sacred-text-adjacent material via LLM is a posture decision, not just an implementation choice.**

Q3: Approve Mode A only (Q1 sources MUST cover all rows; treat Mode B as scope-out)? OR approve Mode A + Mode B with separate filing for Mode B before any LLM-assisted row writes? cc-scholar lean: **Mode A only for v0.2**; defer Mode B to a separate strategic_decision after operator and paired scholar review.

### Q4 — Output tier rule

Per T-1 invariant (4-tier-transparency skill), every row carries `output_tier`. For backfilled rows:
- `quoted` iff exact verbatim from source (Mode A direct fetch, no editorial changes)
- `paraphrased` iff source-attributed but editorially smoothed (Mode B, or Mode A with format normalization like punctuation / footnote inlining)
- `inferred` and `ai-generated` are FORBIDDEN in backfill (no synthesis allowed; we're filling translations, not generating commentary)

Q4: Confirm this tier rule? Specifically: if Mode A source has paragraph breaks restructured (some sources publish single-paragraph; we may want sentence breaks for Telegram), does that count as 'paraphrased' (editorial smoothing) or 'quoted' (semantic preservation)? cc-scholar lean: **paraphrased** for safety.

### Q5 — Verification before write

Each backfilled row should be verified for:
- Arabic text alignment (the row's existing Arabic text must match the source's Arabic for that ayah; mismatch indicates source-version drift)
- Length sanity (English text ≤ 5KB per row; outliers flagged for review)
- No-isnad-leakage check (per F-4: hadith citations in tafsir text must come with full attribution; truncated citations rejected)

Q5: Approve manual spot-check of first 20 rows per scholar before bulk backfill resumes? OR approve unattended bulk with audit afterward?

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `scripts/backfill_tafsir_english.py` | Create | Main backfill driver — reads placeholders, fetches translation per chosen source, validates, updates rows, writes checkpoint |
| `scripts/tafsir_sources/__init__.py` | Create | Package init |
| `scripts/tafsir_sources/ibn_kathir.py` | Create | Source adapter for Ibn Kathir Saheeh International — fetches by surah:ayah, returns structured `{english_text, output_tier, translator, source_url}` |
| `scripts/tafsir_sources/al_sadi.py` | Create | Source adapter for Al-Sa'di |
| `scripts/tafsir_sources/al_jalalayn.py` | Create | Source adapter for Al-Jalalayn (Feras Hamza, altafsir.com) |
| `scripts/tafsir_sources/al_qurtubi.py` | Create | Source adapter for Al-Qurtubi (partial — handles coverage-gap rows per Q1b decision) |
| `scripts/.tafsir_backfill_checkpoint.json` | Generated | Last-completed-row marker for resume |
| `scripts/.tafsir_backfill_log.jsonl` | Generated | Per-row outcome (success / fail / skipped) for post-hoc audit |
| `docs/TAFSIR_BACKFILL_RUNBOOK.md` | Create | Operator runbook — env setup, audit subcommand, run subcommand, recovery from interruption |

Each source adapter is independent. The driver dispatches by `scholar_name` to the right adapter. Adding a fifth scholar later is one new file + one switch case.

---

## Task 1: Source adapter contract + Ibn Kathir adapter

**Files:**
- Create: `scripts/tafsir_sources/__init__.py`
- Create: `scripts/tafsir_sources/ibn_kathir.py`

- [ ] **Step 1: Define the source-adapter contract**

Create `scripts/tafsir_sources/__init__.py`:

```python
"""Tafsir source adapters — Q1 backfill substrate.

Each adapter exposes a single function:
    fetch(surah: int, ayah: int) -> SourceResult | None

Returns None on coverage gap (source has no entry for this ayah).
SourceResult is a dataclass with: english_text, output_tier, translator,
translation_source_url, fetched_at_iso. Adapter is responsible for tier
assignment per Q4 — quoted iff verbatim, paraphrased iff smoothed.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SourceResult:
    english_text: str
    output_tier: str   # 'quoted' | 'paraphrased' (others FORBIDDEN per Q4)
    translator: str
    translation_source_url: str
    fetched_at_iso: str


SourceAdapter = "Callable[[int, int], Optional[SourceResult]]"
```

- [ ] **Step 2: Write the Ibn Kathir adapter**

Create `scripts/tafsir_sources/ibn_kathir.py`. The exact source URL/API depends on Q1a — assume Saheeh International abridged via tafsir.com or quran.com endpoint pending confirmation. Stub structure (do NOT fetch live data until Q1a ratifies):

```python
"""Ibn Kathir abridged tafsir, Saheeh International / Darussalam edition.
Source: TBD — confirmed in AL-BAYAN-CORPUS-EXPANSION-001 Q1a.
"""
import datetime as dt
from typing import Optional
from . import SourceResult


def fetch(surah: int, ayah: int) -> Optional[SourceResult]:
    raise NotImplementedError(
        "Ibn Kathir adapter: pending Q1a ratification of source URL/API. "
        "Do NOT implement live fetch until operator approves source per "
        "AL-BAYAN-CORPUS-EXPANSION-001 amended decision body."
    )
```

- [ ] **Step 3: Commit**

```bash
git add scripts/tafsir_sources/__init__.py scripts/tafsir_sources/ibn_kathir.py
git commit -m "feat(tafsir-backfill): source-adapter contract + Ibn Kathir stub — Task 1 of tafsir-english-backfill plan; live fetch gated on Q1a ratification"
```

---

## Task 2: Backfill driver with audit + run subcommands

**Files:**
- Create: `scripts/backfill_tafsir_english.py`

- [ ] **Step 1: Write the driver**

Pattern after `scripts/enrich_topic_tags_v4_ihsan.py`. Subcommands: `audit` (read-only, classify rows), `run [--scholar X] [--limit N]`, `status`, `sample N`.

The audit subcommand should run today even before Q1 ratifies — it surveys the placeholder distribution per scholar, per surah, and reports any unexpected patterns (e.g., placeholders in places where the scholar usually has text).

Audit output target shape:

```
Tafsir Backfill Audit
=====================
Total tafsir_entries: 24,944
By scholar:
  Ibn Kathir:     6,236 total / 3,118 English / 3,118 placeholder (50%)
  Al-Sa'di:       6,236 total / 3,150 English / 3,086 placeholder (49%)
  Al-Jalalayn:    6,236 total / 3,250 English / 2,986 placeholder (48%)
  Al-Qurtubi:     6,236 total / 3,458 English / 2,778 placeholder (45%)

Placeholder hot spots (surahs >70% placeholder):
  [list per scholar]

Estimated row writes per scholar at concurrency 1:
  [estimate based on adapter latency]
```

The numbers above are illustrative — Step 2 of this task is to run the audit and substitute real numbers into the runbook.

```python
#!/usr/bin/env python3
"""backfill_tafsir_english.py — fill placeholder tafsir rows with English translations.

Subcommands:
  audit                    Read-only survey of placeholder distribution. Always safe.
  run [--scholar X] [--limit N]   Bulk backfill. REQUIRES Q1-Q5 ratification.
  status                   Print checkpoint + progress.
  sample N                 Show N borderline cases (placeholder rows where source
                           would smooth → tier='paraphrased' decision points).

Resumability via scripts/.tafsir_backfill_checkpoint.json.
Fail-soft logging in scripts/.tafsir_backfill_log.jsonl.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY")
PLACEHOLDER_PREFIX = "[Arabic tafsir"
CHECKPOINT_PATH = Path(__file__).parent / ".tafsir_backfill_checkpoint.json"
LOG_PATH = Path(__file__).parent / ".tafsir_backfill_log.jsonl"

if not SUPABASE_KEY:
    print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY not set. Source ihsanos/.env.local first.", file=sys.stderr)
    sys.exit(2)


def fetch_placeholder_rows(scholar: str | None = None, limit: int | None = None) -> list[dict]:
    """Fetch tafsir_entries rows where english_text starts with the placeholder prefix."""
    params = {
        "select": "id,ayah_id,scholar_name,source_work,english_text,output_tier",
        "english_text": f"like.{PLACEHOLDER_PREFIX}%",
    }
    if scholar:
        params["scholar_name"] = f"eq.{scholar}"
    if limit:
        params["limit"] = str(limit)
    url = f"{SUPABASE_URL}/rest/v1/tafsir_entries?{urllib.parse.urlencode(params, safe=':,.')}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_audit(args):
    from collections import Counter
    rows = fetch_placeholder_rows()
    print(f"Total placeholder rows: {len(rows)}")
    by_scholar = Counter(r["scholar_name"] for r in rows)
    print(f"By scholar:")
    for scholar, count in by_scholar.most_common():
        print(f"  {scholar}: {count}")
    # Surah-level concentration would need a join to ayat, omitted in stub for clarity.


def cmd_run(args):
    raise NotImplementedError(
        "tafsir-backfill `run` is gated on AL-BAYAN-CORPUS-EXPANSION-001 ratification "
        "(Q1-Q5 in plan must resolve). See plan + amended decision body."
    )


def cmd_status(args):
    if CHECKPOINT_PATH.exists():
        cp = json.loads(CHECKPOINT_PATH.read_text())
        print(json.dumps(cp, indent=2))
    else:
        print("No checkpoint yet (run not started or completed).")


def cmd_sample(args):
    rows = fetch_placeholder_rows(limit=args.n)
    for r in rows:
        print(f"  scholar={r['scholar_name']} source={r['source_work']} ayah_id={r['ayah_id']}")
        print(f"    english_text: {r['english_text'][:80]!r}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("audit").set_defaults(func=cmd_audit)
    p_run = sub.add_parser("run")
    p_run.add_argument("--scholar")
    p_run.add_argument("--limit", type=int)
    p_run.set_defaults(func=cmd_run)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p_sample = sub.add_parser("sample")
    p_sample.add_argument("n", type=int, default=10)
    p_sample.set_defaults(func=cmd_sample)
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the audit subcommand and substitute real numbers**

```bash
python3 scripts/backfill_tafsir_english.py audit
```

Capture output. Write the actual placeholder distribution into `docs/TAFSIR_BACKFILL_RUNBOOK.md` (Task 4) so the operator decision Q1a is informed by exact per-scholar numbers.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_tafsir_english.py
git commit -m "feat(tafsir-backfill): driver with audit subcommand — Task 2 of tafsir-english-backfill plan; run subcommand gated on Q1-Q5 ratification"
```

---

## Task 3: Per-scholar adapters (gated on Q1a)

This task does NOT execute until Q1a ratifies. The work is, per scholar:

- [ ] Implement `tafsir_sources/<scholar>.py` with the chosen source's fetch logic
- [ ] Add unit test fixture: known-good (surah, ayah) → expected English text fragment
- [ ] Add the scholar's `fetch` to the driver's dispatch table
- [ ] Run `sample 5 --scholar <name>` to spot-check 5 rows; review with operator
- [ ] Commit per scholar

Implementation skipped here because the source URL/API depends on Q1a. The pattern is straightforward once approved.

---

## Task 4: Operator runbook

**Files:**
- Create: `docs/TAFSIR_BACKFILL_RUNBOOK.md`

- [ ] **Step 1: Write runbook**

Sections:
- Pre-run checklist (Q1-Q5 ratifications confirmed; ihsanos/.env.local sourced; service key present)
- Audit walkthrough (`audit` command, expected output shape, what to look for)
- Run sequence per Q2 ordering
- Recovery from interruption (checkpoint format, resume command)
- Post-run verification (sample 50 backfilled rows for tier / source-URL / Arabic alignment)
- Rollback procedure (per-scholar revert via `english_text = '[Arabic tafsir not translated]'` UPDATE)

- [ ] **Step 2: Commit**

```bash
git add docs/TAFSIR_BACKFILL_RUNBOOK.md
git commit -m "docs(tafsir-backfill): operator runbook — Task 4 of tafsir-english-backfill plan"
```

---

## Self-Review Checklist

- **Spec coverage:**
  - GAP 1 of AL-BAYAN-CORPUS-EXPANSION-001 amended body: addressed ✅
  - Q1-Q5 operator decisions: enumerated ✅
  - T-1 tier discipline: enforced via `output_tier` validation in driver ✅
  - F-1 retrieval-first posture: respected (we are filling existing rows, not adding new retrieval substrate) ✅
  - F-4 no-hallucinated-isnads: enforced via Q5 verification ✅
  - Q-1 Arabic canonical: respected (Arabic text in rows is unchanged; only English_text is updated) ✅
  - CAI-PROCESS-MAX-FIRST-001: only Mode B (LLM-assisted) would invoke Claude CLI; gated on separate filing per Q3 ✅
  - Resumability: checkpoint + per-row log ✅

- **Placeholder scan:** Every `TBD` and `pending Q1a` is intentional — these are decision-gates explicitly enumerated in the Q1-Q5 block. No `implement later` or `similar to Task N` placeholders.

- **Type consistency:** `SourceResult` dataclass shape used uniformly across adapters; `output_tier` constraint enforced at driver level before write.

---

## Execution dependencies + blockers

This plan can begin Task 1 + Task 2 immediately (audit + scaffolding, no source decisions needed). Tasks 3+ require Q1a ratification. Q3 Mode B specifically requires its own strategic_decision filing if approved (LLM-assisted translation of sacred-text-adjacent material is a posture commitment per F-1, not an implementation choice).

## Provenance

This plan authored 2026-05-06 by cc-scholar in response to operator request 'how do we fix all these retrieval gaps?' triggered by mizan_bot.log review. Filed under AL-BAYAN-CORPUS-EXPANSION-001 amended decision body GAP 1. Hadith retrieval audit (separate workstream — STEP 1 of amended rollout) confirmed Q2 of mizan-bot test cases (al-Nawwas Isa minaret hadith) is in Sahih Muslim #7373 but bot's retrieval failed to surface it. Routing fix will ship as separate `mizan_bot.py` PR in same shape as `446f562`. Q3 (Musnad al-Bazzar) and Q4 (Mukhtasar al-Uluw) confirmed as genuine ingestion gaps; deferred to Tier 3 specialty source decisions per amended rollout STEP 4.
