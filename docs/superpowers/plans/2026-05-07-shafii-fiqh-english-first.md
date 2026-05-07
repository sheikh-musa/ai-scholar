# Shafi'i Fiqh English-First Ingestion Plan — Safīnat al-Najā (al-Marbūqī tr.)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the operator-supplied bilingual Safīnat al-Najā translation by ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī into `juridical_texts` substrate, then wire `mizan_bot.py` retrieval to surface fiqh-class queries against it as retrieve-only echo (no compose-layer synthesis per AL-BAYAN-COMPOSE-001 C4 + INV-7 paired-scholar gate).

**Architecture:** PDF parser extracts chapter-aligned passages from `docs/sources/safinat-al-najah-marbuqi-tr.pdf` (185 pages, bilingual Arabic+English). Each chapter or sub-section becomes one `juridical_texts` row with `madhab='shafii'`, `dalil_strength_tier='primer_juridical'`, `text_role='matn'`, populated `chapter_path`, `arabic_text`, `english_text`, `output_tier='quoted'` for verbatim Marbuqi prose / `'paraphrased'` for editorial chapter-row alignment. Migration `20260429_001_juridical_corpus.sql` applies first (operator-direct via `supabase migration up` or with Musa-explicit auth). Single `ingestion_provenance` row records the SHA-pinned PDF + sadaqah-jariyah license declaration. `mizan_bot.py` adds a `lookup_fiqh()` routing path that consults `juridical_texts` when query mentions Shafi'i / fiqh / madhhab keywords, returns matn passages with attribution, never composes new rulings.

**Tech Stack:** Python 3, pypdf (in temp venv at `/tmp/pdfvenv`), Supabase REST (service-role for inserts), `mizan_bot.py` extension.

**Consensus source:** AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 (strategic_decisions id 699, amended 2026-05-07 with license verification + Q3-Q5 operator ratifications).

**Not in this plan (deferred):**
- Reliance of the Traveller (Track 2) — copyright posture pending operator decision
- Arabic-canonical-source URL verification for parent AL-BAYAN-003 — separate workstream blocked on operator/scholar URL verification
- Compose-layer synthesis from fiqh substrate — gated on INV-7 paired-scholar program (C4 boundary)
- Hybrid retrieval (semantic embeddings via `juridical_embeddings`) — gated on Modal provisioning per EMBED_PIPELINE_v02; FTS-only acceptable for v0.2 echo path
- Tier 3 specialty fiqh sources (Musnad al-Bazzar, Mukhtasar al-Uluw) — separate Tier 3 filings per AL-BAYAN-CORPUS-EXPANSION-001 amended body

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `docs/sources/safinat-al-najah-marbuqi-tr.pdf` | Already present | Operator-supplied source, SHA `679404ac…ad491`. Committed for audit pinning |
| `scripts/ingest_safinat_marbuqi.py` | Create | PDF parsing + chapter alignment + REST POST to `juridical_texts` + `ingestion_provenance` row write. Subcommands: `extract` (dry-run prints chapters), `provenance` (writes provenance row), `ingest` (writes content rows), `verify` (counts + spot-check against PDF) |
| `scripts/mizan_bot.py` | Modify | Add `match_fiqh_query()` routing helper + `lookup_fiqh()` retrieval against `juridical_texts`; wire into `gather_context()` after the existing surah-alias / hadith-alias detection |
| `docs/SAFINAT_INGESTION_RUNBOOK.md` | Create | Operator runbook: migration apply step, post-ingest smoke tests, recovery procedure |

---

## Task 1: Apply juridical_corpus migration

**Files:**
- Modify (run): `supabase/migrations/20260429_001_juridical_corpus.sql` (already committed; apply only)

- [ ] **Step 1: Verify pre-state — table does not exist yet**

```bash
set -a && source ~/wingmen/projects/ihsanos/.env.local && set +a
curl -s -I -H "apikey: $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Prefer: count=exact" "$ORCHESTRATOR_SUPABASE_URL/rest/v1/juridical_texts?select=id&limit=1" | grep -i content-range
```
Expected: `content-range: */0` (table exists per earlier check; just confirm count is 0).

- [ ] **Step 2: Apply migration**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
supabase migration up --project-ref tscuymavysscrvoberrr
```
Expected: migration `20260429_001_juridical_corpus` runs idempotently; if already applied, supabase CLI reports no-op. Either outcome is OK — the migration uses `CREATE TABLE IF NOT EXISTS` and `CREATE TYPE … EXCEPTION WHEN duplicate_object THEN NULL` so re-applying is safe.

- [ ] **Step 3: Verify post-state — enums + tables exist**

```bash
curl -s "$ORCHESTRATOR_SUPABASE_URL/rest/v1/juridical_texts?select=*&limit=1" -H "apikey: $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $ORCHESTRATOR_SUPABASE_SERVICE_KEY"
```
Expected: `[]` (table exists, empty) — NOT a 404 or schema error.

- [ ] **Step 4: No commit needed** — migration already committed earlier; this task only applies it.

---

## Task 2: PDF extraction + chapter alignment (dry-run)

**Files:**
- Create: `scripts/ingest_safinat_marbuqi.py`

- [ ] **Step 1: Write the script scaffold with `extract` subcommand**

Create `scripts/ingest_safinat_marbuqi.py`:

```python
#!/usr/bin/env python3
"""Safīnat al-Najā (al-Marbūqī tr.) ingestion driver.

Subcommands:
  extract     Dry-run — extract chapters from PDF, print chapter_path + first 200 chars of each. No DB writes.
  provenance  Write the single ingestion_provenance row. Idempotent: skips if SHA already present.
  ingest      Write juridical_texts content rows. Reads from extract output. Idempotent per chapter_path: skips if row exists.
  verify      Post-ingest sanity: row count, sample 5 random rows, spot-check English text fragments against PDF source.

Source: docs/sources/safinat-al-najah-marbuqi-tr.pdf (operator-supplied, SHA 679404ac…ad491).
License: sadaqah jariyah (publisher al-inaam.com explicit reproduction grant per page 3).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# pypdf installed in /tmp/pdfvenv per session 2026-05-07. If running standalone,
# `python3 -m venv /tmp/pdfvenv && /tmp/pdfvenv/bin/pip install pypdf`.
sys.path.insert(0, "/tmp/pdfvenv/lib/python3.14/site-packages")
import pypdf  # type: ignore

PDF_PATH = Path(__file__).parent.parent / "docs/sources/safinat-al-najah-marbuqi-tr.pdf"
EXPECTED_SHA = "679404ac682aea814ed726b6255611fd4624a2d724fe6fc5969cd430255ad491"

SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY", "")
if not SUPABASE_KEY:
    print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY not set", file=sys.stderr)
    sys.exit(2)

PROMPT_VERSION = "safinat-marbuqi-ingest-v1-2026-05-07"
TRANSLATOR = "ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī"
SOURCE_WORK = "Safīnat al-Najā (al-Marbūqī tr., al-inaam.com 2009)"
SOURCE_URL = "docs/sources/safinat-al-najah-marbuqi-tr.pdf"  # repo-pinned canonical
SOURCE_MAINTAINER = "al-inaam.com"
LICENSE_DECLARATION = (
    "Translator/publisher explicit reproduction grant per page 3 of source PDF: "
    "'Any part of this publication may be reproduced, stored in a retrieval system "
    "or transmitted in any form or by any means, electronic, mechanical, photocopying, "
    "recording or otherwise, without the prior permission of the publisher.' "
    "Sadaqah jariyah posture per Hadhrami Shafi'i publishing tradition; verified by Musa 2026-05-07."
)

# Chapter heading patterns from PDF TOC inspection. Order matters (longest first
# to avoid 'Salah' matching inside 'Salah Times').
CHAPTER_HEADINGS = [
    "Muqaddimah", "Islam and Iman", "Al-Ahkam al-Sharʿiyyah",
    "Taharah", "Adhan", "Salah", "Salah Janazah",
    "Zakah", "Saum", "Hajj and ʿUmrah",
    "Bibliography",
    # Biographical appendix
    "Al-Imām al-Rāfiʿī", "Al-Imām al-Nawawī", "Shaykh al-Islām Zakariyyā al-Anṣārī",
    "Al-Imām Ibn Ḥajar al-Haytamī", "Al-Imām Muḥammad al-Shirbīnī al-Khāṭib",
]


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pages(path: Path) -> list[str]:
    reader = pypdf.PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in reader.pages]


def segment_chapters(pages: list[str]) -> list[dict]:
    """Walk pages, identify chapter boundaries by heading match in extracted text.
    Returns list of dicts with chapter_path, page_start, page_end, english_text.
    """
    chapters = []
    current = None
    for i, page_text in enumerate(pages):
        # Try to match a chapter heading at the start of meaningful text on this page
        first_lines = "\n".join(page_text.split("\n")[:3])
        matched_heading = None
        for h in CHAPTER_HEADINGS:
            if h in first_lines:
                matched_heading = h
                break
        if matched_heading and (current is None or current["chapter_path"] != matched_heading):
            if current is not None:
                current["page_end"] = i - 1
                chapters.append(current)
            current = {
                "chapter_path": matched_heading,
                "page_start": i,
                "page_end": i,
                "english_text_pages": [page_text],
            }
        elif current is not None:
            current["english_text_pages"].append(page_text)
    if current is not None:
        current["page_end"] = len(pages) - 1
        chapters.append(current)
    # Concatenate page texts per chapter
    for ch in chapters:
        ch["english_text"] = "\n\n".join(ch["english_text_pages"])
        del ch["english_text_pages"]
    return chapters


def cmd_extract(args):
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 2
    sha = compute_sha256(PDF_PATH)
    if sha != EXPECTED_SHA:
        print(f"ERROR: PDF SHA mismatch — expected {EXPECTED_SHA}, got {sha}", file=sys.stderr)
        return 3
    print(f"PDF SHA verified: {sha}")
    pages = extract_pages(PDF_PATH)
    print(f"Extracted {len(pages)} pages")
    chapters = segment_chapters(pages)
    print(f"Segmented into {len(chapters)} chapter(s):")
    for ch in chapters:
        eng = ch["english_text"][:200].replace("\n", " ")
        print(f"  {ch['chapter_path']:35} pages {ch['page_start']:3}-{ch['page_end']:3}: {eng}…")
    return 0


def supabase_post(table: str, data: dict | list) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=representation",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_provenance(args):
    """Write the single ingestion_provenance row. Idempotent on SHA."""
    sha = compute_sha256(PDF_PATH)
    # Check if already present
    url = f"{SUPABASE_URL}/rest/v1/ingestion_provenance?source_file_sha256=eq.{sha}&select=id&limit=1"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        existing = json.loads(resp.read().decode("utf-8"))
    if existing:
        print(f"Provenance row already present: id={existing[0]['id']}")
        return 0
    row = {
        "source_url": SOURCE_URL,
        "source_maintainer": SOURCE_MAINTAINER,
        "license_declaration": LICENSE_DECLARATION,
        "source_file_sha256": sha,
        "verified_by_identity": "musa",
        "notes": "Bilingual Arabic+English. 185 pages. Edition Ṣafar 1430 H (Feb 2009). "
                 f"Translator {TRANSLATOR}. Operator-supplied 2026-05-07.",
    }
    result = supabase_post("ingestion_provenance", row)
    print(f"Wrote ingestion_provenance row: id={result[0]['id']}")
    return 0


def cmd_ingest(args):
    """Write juridical_texts content rows. Idempotent per chapter_path within source SHA."""
    pages = extract_pages(PDF_PATH)
    chapters = segment_chapters(pages)
    sha = compute_sha256(PDF_PATH)
    # Get the provenance id
    url = f"{SUPABASE_URL}/rest/v1/ingestion_provenance?source_file_sha256=eq.{sha}&select=id&limit=1"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        prov = json.loads(resp.read().decode("utf-8"))
    if not prov:
        print("ERROR: ingestion_provenance row missing — run `provenance` subcommand first", file=sys.stderr)
        return 4
    provenance_id = prov[0]["id"]
    written = 0
    skipped = 0
    for ch in chapters:
        # Check if row exists
        path_enc = urllib.parse.quote(ch["chapter_path"])
        check_url = f"{SUPABASE_URL}/rest/v1/juridical_texts?chapter_path=eq.{path_enc}&provenance_id=eq.{provenance_id}&select=id&limit=1"
        req = urllib.request.Request(check_url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req) as resp:
            existing = json.loads(resp.read().decode("utf-8"))
        if existing:
            skipped += 1
            continue
        # Determine output_tier — chapter-level rows are 'paraphrased' (editorial alignment)
        # since we're concatenating pages. Future rule-level granularity can use 'quoted'.
        row = {
            "madhab": "shafii",
            "dalil_strength_tier": "primer_juridical",
            "text_role": "matn",
            "scholar_name": TRANSLATOR,
            "source_work": SOURCE_WORK,
            "chapter_path": ch["chapter_path"],
            "arabic_text": None,  # Bilingual extraction TBD; English-first per amended decision
            "english_text": ch["english_text"][:50000],  # cap per row to avoid blob rows
            "output_tier": "paraphrased",
            "provenance_id": provenance_id,
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
        }
        result = supabase_post("juridical_texts", row)
        written += 1
        print(f"  + {ch['chapter_path']:35} (pages {ch['page_start']:3}-{ch['page_end']:3}, {len(ch['english_text']):6} chars)")
    print(f"\nDone: {written} rows written, {skipped} already present.")
    return 0


def cmd_verify(args):
    """Spot-check ingested rows."""
    url = f"{SUPABASE_URL}/rest/v1/juridical_texts?source_work=eq.{urllib.parse.quote(SOURCE_WORK)}&select=chapter_path,page_start,page_end,output_tier&order=page_start"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    print(f"juridical_texts rows for {SOURCE_WORK}: {len(rows)}")
    for r in rows:
        print(f"  {r['chapter_path']:35} pp {r['page_start']:3}-{r['page_end']:3}  tier={r['output_tier']}")
    return 0


SUBCOMMANDS = {"extract": cmd_extract, "provenance": cmd_provenance, "ingest": cmd_ingest, "verify": cmd_verify}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=list(SUBCOMMANDS))
    args, _ = parser.parse_known_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run `extract` to verify chapter segmentation works**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
python3 scripts/ingest_safinat_marbuqi.py extract
```
Expected: prints SHA verification + 10-15 chapter segments with page ranges + first 200 chars each. If chapter count is suspicious (e.g., 1 chapter or 50+), the segmentation needs tuning before `ingest` runs.

- [ ] **Step 3: Commit the ingestion script**

```bash
git add scripts/ingest_safinat_marbuqi.py
git commit -m "feat(juridical): Safīnat al-Marbūqī ingestion driver — extract / provenance / ingest / verify subcommands"
```

---

## Task 3: Write provenance + content rows

**Files:**
- Modify (run only): the existing script

- [ ] **Step 1: Write provenance row**

```bash
python3 scripts/ingest_safinat_marbuqi.py provenance
```
Expected: prints "Wrote ingestion_provenance row: id=<uuid>". Idempotent — re-running gives "already present".

- [ ] **Step 2: Write content rows**

```bash
python3 scripts/ingest_safinat_marbuqi.py ingest
```
Expected: prints `+ <chapter_path> (pages X-Y, NNNN chars)` per chapter; total ~10-15 rows.

- [ ] **Step 3: Verify**

```bash
python3 scripts/ingest_safinat_marbuqi.py verify
```
Expected: lists all juridical_texts rows for `Safīnat al-Najā (al-Marbūqī tr., al-inaam.com 2009)`.

- [ ] **Step 4: No commit needed** — Task 3 is data-write only, no code changes.

---

## Task 4: Wire `mizan_bot.py` to retrieve from juridical_texts

**Files:**
- Modify: `scripts/mizan_bot.py`

- [ ] **Step 1: Add fiqh-query detection helper**

Near the existing `match_surah_alias()` (around line 313, post `446f562`), add:

```python
FIQH_KEYWORDS = {
    "fiqh", "ruling", "madhhab", "madhab", "shafii", "shafi'i", "shafi",
    "wudu", "wuduʾ", "ablution", "ghusl", "tayammum", "purity", "taharah",
    "salah", "salat", "prayer", "adhan",
    "zakah", "zakat", "alms",
    "saum", "sawm", "fasting", "ramadan",
    "hajj", "umrah", "pilgrimage",
}

def match_fiqh_query(text: str) -> bool:
    """Detect Shafi'i fiqh keyword in query — triggers juridical_texts retrieval."""
    t = text.lower()
    return any(kw in t for kw in FIQH_KEYWORDS)
```

- [ ] **Step 2: Add the retrieval helper**

```python
def lookup_fiqh(keywords: str, limit: int = 3) -> dict:
    """Retrieve from juridical_texts via FTS-on-english_text fallback.
    Phase 2 will swap to search_juridical_semantic RPC once embeddings populate."""
    fts_query = " OR ".join(keywords.split()[:4])
    try:
        rows = supabase_get("juridical_texts", {
            "english_text": f"ilike.%{fts_query}%",  # fallback ILIKE; FTS RPC pending Phase 2
            "select": "scholar_name,source_work,chapter_path,english_text,output_tier",
            "limit": str(min(limit, 5)),
        })
    except Exception:
        return {"results": []}
    out = []
    for r in rows:
        out.append({
            "scholar": r["scholar_name"],
            "source": r["source_work"],
            "chapter_path": r["chapter_path"],
            "english_text": (r.get("english_text") or "")[:1500],
            "tier": r["output_tier"],
        })
    return {"results": out}
```

- [ ] **Step 3: Wire into `gather_context()`**

In `gather_context()`, after the existing tafsir-FTS block (around line 535-548 post `446f562`), add:

```python
# AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 Track 1 retrieve-only echo —
# Shafi'i fiqh substrate (Safīnat al-Marbūqī). Retrieval ONLY; no compose-
# layer synthesis per C4 + INV-7 paired-scholar gate.
if match_fiqh_query(question) and _ctx_size(context_parts) < MAX_CONTEXT:
    fiqh_data = lookup_fiqh(" ".join(words[:4]), limit=3)
    if fiqh_data["results"]:
        entries = []
        for hit in fiqh_data["results"]:
            entries.append(
                f"Source: {hit['source']}\n"
                f"Chapter: {hit['chapter_path']}\n"
                f"Translator: {hit['scholar']}\n"
                f"Tier: {hit['tier']}\n"
                f"Text: {hit['english_text']}"
            )
        context_parts.append(
            "FIQH MATCHED PASSAGES (Shafi'i matn, retrieve-only echo, "
            "compose-layer synthesis FORBIDDEN per C4 + INV-7):\n" +
            "\n\n".join(entries)
        )
```

- [ ] **Step 4: Update the `ask_claude` system prompt to include the C4 boundary**

In `ask_claude()` (around line 577 post `446f562`), in the RULES section, add a new bullet AFTER the existing "NEVER issue fiqh rulings" line:

```
- When citing fiqh-substrate passages (Safīnat al-Najā / juridical_texts),
  return the matn passage VERBATIM with attribution. Do NOT synthesize a
  new ruling. The user must consult a qualified scholar for application.
```

- [ ] **Step 5: Compile-check + commit**

```bash
python3 -c "compile(open('scripts/mizan_bot.py').read(), 'mb', 'exec')"
git add scripts/mizan_bot.py
git commit -m "feat(mizan-bot): Shafi'i fiqh retrieval — match_fiqh_query + lookup_fiqh + gather_context wire-in (retrieve-only per C4 + INV-7 gate)"
```

- [ ] **Step 6: Restart bot** — operator-direct via launchctl kickstart, or with cc-scholar auth.

---

## Task 5: Smoke test + runbook

**Files:**
- Create: `docs/SAFINAT_INGESTION_RUNBOOK.md`

- [ ] **Step 1: Manual smoke test from Telegram (operator)**

After bot restart, query Mizan with:
- `"What does Safinat say about wudu?"` → expect Taharah chapter passage with attribution
- `"Shafii ruling on fasting kaffarah"` → expect Saum chapter passage
- `"Conditions for salah"` → expect Salah chapter passage

Bot should return matn passages with `Source: Safīnat al-Najā (al-Marbūqī tr.…)` headers, NO new rulings synthesized.

- [ ] **Step 2: Write runbook**

`docs/SAFINAT_INGESTION_RUNBOOK.md`:
- Pre-run checklist (env sourced, migration applied, provenance row written)
- Re-ingestion procedure (if PDF revised: bump SHA, write new provenance row, drop old juridical_texts rows for old provenance_id, re-run `ingest`)
- Rollback procedure: `DELETE FROM juridical_texts WHERE provenance_id=<old>; DELETE FROM ingestion_provenance WHERE id=<old>;`
- Tier 2 future work: rule-level granularity (each fiqh rule = 1 row, `output_tier='quoted'`)
- Phase 2 future work: bilingual ingestion (populate `arabic_text` column from PDF Arabic side)

- [ ] **Step 3: Commit**

```bash
git add docs/SAFINAT_INGESTION_RUNBOOK.md
git commit -m "docs(juridical): Safīnat ingestion runbook"
```

---

## Self-Review Checklist

- **Spec coverage** (AL-BAYAN-003-AMEND-ENGLISH-FIRST-001):
  - Track 1 ingestion: Tasks 1-3 ✅
  - Track 3 migration apply: Task 1 Step 2 ✅
  - C4 retrieve-only-no-synthesis: Task 4 wire-in honors boundary; Task 4 Step 4 reinforces in system prompt ✅
  - INV-7 paired-scholar gate: scholar_of_record null in juridical_texts rows for v0.2 ✅
  - T-1 tier discipline: every row has output_tier set ✅
  - License provenance: ingestion_provenance row with sadaqah-jariyah declaration ✅
  - Q5 citation format: `Safīnat al-Najā (al-Marbūqī tr., al-inaam.com 2009)` ✅

- **Placeholder scan:** TBD only on Phase 2 work (bilingual Arabic, rule-level granularity, semantic embeddings) — those are explicitly deferred to Tier 2 future work.

- **Type consistency:** `juridical_texts` row shape matches migration schema; chapter_path is text not enum (per migration); provenance_id is uuid foreign key.

---

## Execution dependencies + blockers

- Task 1 Step 2 (migration apply) requires operator-direct `supabase` CLI access OR explicit cc-scholar auth (same pattern as persist-mizan-ruling deploy this session).
- Task 3 Steps 1-2 (data writes) require service-role key + ingestion_provenance row in place.
- Task 4 (mizan_bot wire-in) does not block on data being ingested — code can land before data; if no rows match, lookup_fiqh returns empty results gracefully.
- Task 5 smoke test requires bot restart after Task 4 commit.

## Provenance

This plan authored 2026-05-07 by cc-scholar per AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 (strategic_decisions id 699, amended 2026-05-07 with license-verified-permissive + Q3-Q5 ratifications). Operator dropped source PDF at `docs/sources/safinat-al-najah-marbuqi-tr.pdf` (SHA `679404ac…ad491`). License posture verified via verbatim page-3 reproduction grant + al-inaam.com publisher tradition (sadaqah jariyah). cc-scholar's initial "almost certainly a typo" claim was the third substrate-assumed-not-verified failure of the session; corrected by operator pushback ("people translate books as sadaqah jariyah") and memorialized in `feedback_islamic_publishing_license.md`.
