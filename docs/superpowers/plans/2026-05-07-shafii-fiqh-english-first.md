# Shafi'i Fiqh English-First Ingestion Plan — Safīnat al-Najā (al-Marbūqī tr.)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

---

## OPTION (ii) LITE — hajj deferred to Phase 2 per operator 2026-05-07

Sourcing exhausted: usul.ai Arabic covers original matn + Nawawi al-Jawi siyam additions
(4 of 5 worship topics: taharah / salah / zakah / siyam). Ba'atiyyah's hajj addition is NOT
in the usul.ai source. Al-Marbuqi PDF Arabic side is glyph-encoded (broken Unicode mapping;
verified via both pypdf and pymupdf surveys).

Operator (Musa) ratified 2026-05-07: ingest 4 of 5 buckets for v0; defer hajj to Phase 2.
Phase 2 hajj sourcing tracked in strategic_decisions id 699 amendment 4 body. Likely
pairs with INV-7 paired-scholar program activation.

---

## PATH B REFINED — schema correction per CAI-RESP-136

**CAI ruling:** CAI-RESP-136 / strategic_decisions id 756.
**cc-scholar escalation:** agent_messages #1399 (schema mismatch escalation to cai).
**cc-scholar reply confirming 4 downstream asks:** agent_messages #1400.

CAI rejected Path A (extend juridical_texts with English columns), Path C (Arabic-only), Path D (defer).
CAI adopted Path B refined: new `public.juridical_translations` table FK'd to `juridical_texts`, 1:N cardinality.

**Schema correction history:** the original plan assumed `juridical_texts` had English columns
(`english_text`, `chapter_path`, `output_tier`, `provenance_id`, etc.) matching migration
`20260429_001_juridical_corpus.sql`. Deployed state (verified via `information_schema.columns`,
per CAI-RESP-136 meta-process amendment) shows the ACTUAL deployed migration is
`20260428194802_al_bayan_003_juridical_corpus.sql` — Arabic-only schema with `text_name`,
`baab_or_section`, `baab_order`, `arabic_text NOT NULL`, `arabic_text_sha256`, `ingestion_provenance_id`.
The stale `20260429_001_juridical_corpus.sql` shadow file was deleted (never applied; commit `360f9cc`).

**Arabic-as-source-of-truth preserved:** `juridical_texts.arabic_text_sha256` remains canonical.
Translations are derivative renderings on a separate provenance chain (`juridical_translations.translation_text_sha256`).

---

**Goal:** Ingest the operator-supplied bilingual Safīnat al-Najā translation by ʿAbdullah Muḥammad al-Marbūqī al-Shāfiʿī into `juridical_texts` (Arabic matn) + `juridical_translations` (English translation) substrate, then wire `mizan_bot.py` retrieval to surface fiqh-class queries against it as retrieve-only echo (no compose-layer synthesis per AL-BAYAN-COMPOSE-001 C4 + INV-7 paired-scholar gate).

**Architecture (option (ii) lite):** Two distinct sources:
- Arabic matn read from `docs/sources/safinat-al-najah-arabic.txt` (usul.ai / al-Maktaba al-Shamela; 24,906 chars; 65 (فصل) fasls). NOT from PDF (PDF Arabic side is glyph-encoded). Fasls are classified into 5 topical buckets by Arabic keyword matching; all 65 fasls assigned to buckets (0 unmatched).
- English translation read from `docs/sources/safinat-al-najah-marbuqi-tr.pdf` (185 pages; al-Marbuqi 2009). 8 PDF chapters segmented; chapters are merged into matching buckets.

**5 topical buckets** (hajj excluded): Muqaddimah & Iman (4 fasls), Taharah (21 fasls), Salah (32 fasls), Zakah (1 fasl), Siyam (7 fasls).

**TWO ingestion_provenance rows**: Arabic (usul.ai, PD) + English (al-Marbuqi PDF, sadaqah jariyah). Each row carries its own `ingestion_provenance_id`. `juridical_texts` rows carry the Arabic provenance id; `juridical_translations` rows carry the English provenance id.

Migration `20260507_001_juridical_translations.sql` adds the `juridical_translations` table (the parent `juridical_texts` table is ALREADY DEPLOYED as `20260428194802_al_bayan_003_juridical_corpus.sql`). `mizan_bot.py` adds a `match_fiqh_query()` routing path that consults `juridical_translations` when query mentions Shafi'i / fiqh / madhhab keywords, returns matn passages with attribution, never composes new rulings.

**Tech Stack:** Python 3, pypdf (in temp venv at `/tmp/pdfvenv`), Supabase REST (service-role for inserts), `mizan_bot.py` extension.

**Consensus source:** AL-BAYAN-003-AMEND-ENGLISH-FIRST-002 (strategic_decisions id 756, CAI-RESP-136, amended from id 699 / English-FIRST-001 due to schema mismatch correction).

**Not in this plan (deferred):**
- Reliance of the Traveller (Track 2) — copyright posture pending operator decision
- Arabic-canonical-source URL verification for parent AL-BAYAN-003 — separate workstream blocked on operator/scholar URL verification
- Compose-layer synthesis from fiqh substrate — gated on INV-7 paired-scholar program (C4 boundary)
- Hybrid retrieval (semantic embeddings via `juridical_embeddings`) — gated on Modal provisioning per EMBED_PIPELINE_v02; FTS-only acceptable for v0.2 echo path
- Tier 3 specialty fiqh sources (Musnad al-Bazzar, Mukhtasar al-Uluw) — separate Tier 3 filings per AL-BAYAN-CORPUS-EXPANSION-001 amended body
- Phase 2 Arabic refresh: arabic_text from PDF extraction is rough (pypdf RTL). A Phase 2 refresh script can overwrite rows from al-Maktaba al-Shamela or the publisher's digital edition.

---

## File Structure

| File | Change | Status |
|------|--------|--------|
| `docs/sources/safinat-al-najah-arabic.txt` | Already present | Arabic source — usul.ai / al-Maktaba al-Shamela; SHA `18a3bb24…9c`. 24,906 chars; 65 (فصل) fasls; original matn + Nawawi al-Jawi siyam additions; no hajj |
| `docs/sources/safinat-al-najah-marbuqi-tr.pdf` | Already present | English source — al-Marbuqi 2009, al-inaam.com; SHA `679404ac…ad491`. 185 pages; 8 chapters extracted; Arabic side glyph-encoded (NOT used for Arabic ingestion) |
| `supabase/migrations/20260429_001_juridical_corpus.sql` | DELETED (commit `360f9cc`) | Was never applied to remote; declared wrong schema. Shadow file removed per CAI-RESP-136 downstream ask 1 |
| `supabase/migrations/20260507_001_juridical_translations.sql` | NEW (commit `7ebc7b2`) | Adds `juridical_translations` table FK'd to `juridical_texts`. **Do NOT apply until 2026-05-08T01:32:09Z window-close or Musa early-close consent** |
| `scripts/ingest_safinat_marbuqi.py` | REWRITTEN for option (ii) lite | Arabic from `safinat-al-najah-arabic.txt` (NOT PDF); English from PDF; 5 topical buckets + bucket keyword assignment; TWO ingestion_provenance rows; verify_schema() gate guards cmd_provenance + cmd_ingest |
| `scripts/mizan_bot.py` | Modify | Add `match_fiqh_query()` routing helper + `lookup_fiqh()` retrieval against `juridical_translations`; wire into `gather_context()` after the existing surah-alias / hadith-alias detection |
| `docs/SAFINAT_INGESTION_RUNBOOK.md` | Create | Operator runbook: migration apply step, post-ingest smoke tests, recovery procedure |

---

## Task 1: Apply juridical_translations migration

**Files:**
- Run: `supabase/migrations/20260507_001_juridical_translations.sql` (new file, committed; apply only)

**Pre-condition:** The parent `juridical_texts` table is ALREADY DEPLOYED via
`20260428194802_al_bayan_003_juridical_corpus.sql`. Task 1 here only applies the NEW
`20260507_001_juridical_translations.sql` migration (adds `juridical_translations` table).

**Apply gate:** `supabase migration up` after challenge_window closes **2026-05-08T01:32:09Z**,
OR with explicit Musa early-close consent. cc-scholar does NOT pre-apply.

- [ ] **Step 1: Verify pre-state — juridical_texts exists, juridical_translations does not yet**

```bash
set -a && source ~/wingmen/projects/ihsanos/.env.local && set +a
# juridical_texts should return [] (empty), not 404
curl -s -H "apikey: $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $ORCHESTRATOR_SUPABASE_SERVICE_KEY" "$ORCHESTRATOR_SUPABASE_URL/rest/v1/juridical_texts?select=id&limit=1"
# juridical_translations should return 404 (table not yet deployed)
curl -s -H "apikey: $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $ORCHESTRATOR_SUPABASE_SERVICE_KEY" "$ORCHESTRATOR_SUPABASE_URL/rest/v1/juridical_translations?select=id&limit=1"
```

- [ ] **Step 2: Apply migration (operator-direct or cc-scholar with Musa auth)**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
supabase migration up --project-ref tscuymavysscrvoberrr
```

Expected: migration `20260507_001_juridical_translations` runs; supabase CLI confirms applied.

- [ ] **Step 3: Verify post-state — both tables accessible**

```bash
curl -s "$ORCHESTRATOR_SUPABASE_URL/rest/v1/juridical_translations?select=*&limit=1" \
  -H "apikey: $ORCHESTRATOR_SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $ORCHESTRATOR_SUPABASE_SERVICE_KEY"
```
Expected: `[]` (table exists, empty) — NOT a 404 or schema error.

- [ ] **Step 4: No commit needed** — migration already committed; this task only applies it.

---

## Task 2: PDF extraction + chapter alignment (dry-run)

**Files:**
- (Already exists): `scripts/ingest_safinat_marbuqi.py`

- [ ] **Step 1: Run `extract` to verify chapter segmentation + Arabic extraction quality**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
set -a && source ~/wingmen/projects/ihsanos/.env.local && set +a
python3 scripts/ingest_safinat_marbuqi.py extract
```

Expected: prints SHA verification + chapter segments with page ranges, Arabic char counts, and first
200 chars of English per chapter. Look for `[WARN:<50chars]` flags on Arabic — those chapters will
be SKIPPED by `ingest`. If chapter count is suspicious (e.g., 1 or 50+), the segmentation needs
tuning before `ingest` runs.

- [ ] **Step 2: No commit needed** — `extract` is read-only; script already committed at `6f7ded6`.

---

## Task 3: Write provenance + content rows (two-step insert)

**Files:**
- Modify (run only): the existing script — requires migration from Task 1 to be applied first.

**Insert pattern (option (ii) lite):** Two ingestion_provenance rows (Arabic + English). cmd_provenance writes both. cmd_ingest reads both ids. Per-bucket two-step insert: Step 1 → `juridical_texts` (Arabic blob from fasls); Step 2 → `juridical_translations` (English from PDF chapters). Both call verify_schema() first; exit code 5 if `juridical_translations` not deployed.

- [ ] **Step 1: Write BOTH provenance rows**

```bash
python3 scripts/ingest_safinat_marbuqi.py provenance
```
Expected:
```
Schema verified: juridical_texts + juridical_translations + ingestion_provenance all present.
  Arabic (usul.ai) provenance row written: id=<uuid>
  English (al-Marbuqi PDF) provenance row written: id=<uuid>
Provenance rows: arabic=<uuid>, english=<uuid>
```
Idempotent — re-running gives "already present" for each.

- [ ] **Step 2: Write content rows (two-step insert per bucket)**

```bash
python3 scripts/ingest_safinat_marbuqi.py ingest
```
Expected per bucket:
```
  + <bucket_name>             (N fasls, NNN ar chars, MMMM en chars, pages X-Y)
```
Expected 5 buckets written (Muqaddimah & Iman, Taharah, Salah, Zakah, Siyam):
```
Done: 5 bucket(s) written, 0 already present.
NOTE: Hajj DEFERRED to Phase 2 per operator decision 2026-05-07.
```

Each written bucket produces:
- 1 row in `juridical_texts` (Arabic matn blob from all fasls in bucket; author per bucket config)
- 1 row in `juridical_translations` (English from matching PDF chapters, FK to juridical_texts.id)

- [ ] **Step 3: Verify — JOIN both tables**

```bash
python3 scripts/ingest_safinat_marbuqi.py verify
```
Expected: 5 rows in `juridical_translations`, each with `baab_or_section` (bucket name),
`ar=N chars`, tier=paraphrased, pp range. Joined with `juridical_texts.arabic_text` char count.

- [ ] **Step 4: No commit needed** — Task 3 is data-write only, no code changes.

---

## Task 4: Wire `mizan_bot.py` to retrieve from juridical_translations

**Files:**
- Modify: `scripts/mizan_bot.py`

Retrieval now queries `juridical_translations` (joined to `juridical_texts` for matn metadata)
rather than `juridical_texts` directly, since English text lives in the translations table.

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
    """Detect Shafi'i fiqh keyword in query — triggers juridical retrieval."""
    t = text.lower()
    return any(kw in t for kw in FIQH_KEYWORDS)
```

- [ ] **Step 2: Add the retrieval helper**

```python
def lookup_fiqh(keywords: str, limit: int = 3) -> dict:
    """Retrieve from juridical_translations via ILIKE fallback.
    Phase 2 will swap to search_juridical_semantic RPC once embeddings populate."""
    fts_query = " OR ".join(keywords.split()[:4])
    try:
        rows = supabase_get("juridical_translations", {
            "translation_text": f"ilike.%{fts_query}%",
            "select": "translator_name,translation_source_work,output_tier,translation_text,"
                      "juridical_texts(text_name,baab_or_section)",
            "limit": str(min(limit, 5)),
        })
    except Exception:
        return {"results": []}
    out = []
    for r in rows:
        jt = r.get("juridical_texts") or {}
        out.append({
            "scholar": r["translator_name"],
            "source": r["translation_source_work"],
            "chapter_path": jt.get("baab_or_section", ""),
            "english_text": (r.get("translation_text") or "")[:1500],
            "tier": r["output_tier"],
        })
    return {"results": out}
```

- [ ] **Step 3: Wire into `gather_context()`**

In `gather_context()`, after the existing tafsir-FTS block, add:

```python
# AL-BAYAN-003-AMEND-ENGLISH-FIRST-002 Track 1 retrieve-only echo —
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

In `ask_claude()`, in the RULES section, add a new bullet AFTER the existing "NEVER issue fiqh rulings" line:

```
- When citing fiqh-substrate passages (Safīnat al-Najā / juridical_translations),
  return the translation passage VERBATIM with attribution. Do NOT synthesize a
  new ruling. The user must consult a qualified scholar for application.
```

- [ ] **Step 5: Compile-check + commit**

```bash
python3 -c "compile(open('scripts/mizan_bot.py').read(), 'mb', 'exec')"
git add scripts/mizan_bot.py
git commit -m "feat(mizan-bot): Shafi'i fiqh retrieval — match_fiqh_query + lookup_fiqh (juridical_translations) + gather_context wire-in (retrieve-only per C4 + INV-7 gate)"
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

Bot should return translation passages with `Source: Safīnat al-Najā (al-inaam.com 2009)` headers,
NO new rulings synthesized.

- [ ] **Step 2: Write runbook**

`docs/SAFINAT_INGESTION_RUNBOOK.md`:
- Pre-run checklist (env sourced, migration applied, provenance row written)
- Two-step insert verification (check both `juridical_texts` + `juridical_translations` counts match)
- Re-ingestion procedure (if PDF revised: bump SHA, write new provenance row, drop old juridical_texts
  rows for old provenance_id — cascade deletes associated juridical_translations rows — re-run `ingest`)
- Rollback procedure:
  ```sql
  -- cascade delete removes juridical_translations rows automatically (ON DELETE CASCADE)
  DELETE FROM juridical_texts WHERE ingestion_provenance_id = '<old>';
  DELETE FROM ingestion_provenance WHERE id = '<old>';
  ```
- Tier 2 future work: rule-level granularity (each fiqh rule = 1 row, `output_tier='quoted'`)
- Phase 2 future work: Arabic quality refresh — overwrite `arabic_text` + recompute `arabic_text_sha256`
  from al-Maktaba al-Shamela or publisher's digital edition (Arabic side of juridical_texts)

- [ ] **Step 3: Commit**

```bash
git add docs/SAFINAT_INGESTION_RUNBOOK.md
git commit -m "docs(juridical): Safīnat ingestion runbook (Path B refined two-step pattern)"
```

---

## Self-Review Checklist

- **Schema matches deployed state (CAI-RESP-136 meta-process amendment):**
  - `juridical_texts` deployed with Arabic-only schema (text_name, baab_or_section, baab_order, arabic_text NOT NULL, arabic_text_sha256) ✅ verified via information_schema
  - `juridical_translations` new table for English (FK to juridical_texts.id) per Path B refined ✅ migration committed
  - Stale `20260429_001_juridical_corpus.sql` shadow file deleted ✅ commit `360f9cc`

- **Spec coverage (AL-BAYAN-003-AMEND-ENGLISH-FIRST-002):**
  - Track 1 ingestion: Tasks 1-3 (migration + extract + two-step insert) ✅
  - C4 retrieve-only-no-synthesis: Task 4 wire-in honors boundary; Task 4 Step 4 reinforces in system prompt ✅
  - INV-7 paired-scholar gate: no compose-layer synthesis in ingest script or bot wire-in ✅
  - T-1 tier discipline: every `juridical_translations` row has `output_tier` set ✅
  - Arabic-as-source-of-truth: `juridical_texts.arabic_text_sha256` canonical; translations on separate chain ✅
  - License provenance: ingestion_provenance row with sadaqah-jariyah declaration; shared across both row types ✅
  - Q5 citation format: `Safīnat al-Najā (al-inaam.com 2009)` ✅

- **Idempotency:** ingest checks (text_name, baab_or_section, ingestion_provenance_id) on juridical_texts before both inserts ✅
- **Arabic extraction safety:** chapters with <50 chars are SKIPPED not ingested as garbage ✅
- **Schema verification gate:** cmd_provenance + cmd_ingest call verify_schema() → exit 5 if juridical_translations not deployed ✅
- **Cascade delete:** `juridical_texts ON DELETE CASCADE` → rollback only needs to delete juridical_texts + ingestion_provenance rows ✅

- **Placeholder scan:** TBD only on Phase 2 work (Arabic quality refresh, rule-level granularity, semantic embeddings) — those are explicitly deferred.

---

## Execution dependencies + blockers

- Task 1 Step 2 (migration apply) requires operator-direct `supabase` CLI access OR explicit cc-scholar auth. GATED on 2026-05-08T01:32:09Z window-close.
- Task 3 Steps 1-2 (data writes) require: (a) migration applied; (b) service-role key; (c) ingestion_provenance row in place.
- Task 4 (mizan_bot wire-in) does not block on data being ingested — code can land before data; if no rows match, lookup_fiqh returns empty results gracefully.
- Task 5 smoke test requires bot restart after Task 4 commit.

---

## Provenance

This plan authored 2026-05-07 by cc-scholar per AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 (strategic_decisions id 699, amended 2026-05-07 with license-verified-permissive + Q3-Q5 ratifications). Operator dropped source PDF at `docs/sources/safinat-al-najah-marbuqi-tr.pdf` (SHA `679404ac…ad491`). License posture verified via verbatim page-3 reproduction grant + al-inaam.com publisher tradition (sadaqah jariyah). cc-scholar's initial "almost certainly a typo" claim was the third substrate-assumed-not-verified failure of the session; corrected by operator pushback ("people translate books as sadaqah jariyah") and memorialized in `feedback_islamic_publishing_license.md`.

**Schema mismatch self-correction (2026-04-30):** cc-scholar escalated to CAI (msg #1399) after discovering that `scripts/ingest_safinat_marbuqi.py` assumed an English-aware `juridical_texts` schema (`english_text`, `chapter_path`, `output_tier`, `provenance_id`) that does NOT match deployed state. Deployed migration `20260428194802_al_bayan_003_juridical_corpus.sql` has Arabic-only schema (`baab_or_section`, `arabic_text NOT NULL`, `arabic_text_sha256`, `ingestion_provenance_id`). CAI adopted Path B refined (new `juridical_translations` table) per strategic_decisions id 756 / CAI-RESP-136. cc-scholar confirmed 4 downstream asks (msg #1400): delete shadow file, create new migration, rewrite ingest script for two-step insert, update this plan. This was the 4th substrate-assumed-not-verified pattern of the session; CAI-RESP-136 meta-process amendment now requires information_schema query before any schema-dependent code.
