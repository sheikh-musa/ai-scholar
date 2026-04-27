# AL-BAYAN-003 Phase 1 — source acquisition runbook

**Status:** Runbook authored 2026-04-28. Acquisition execution pending operator (cc-scholar attempted WebFetch on candidate URLs; both 404'd — URL verification needed by Musa or scholar in network).
**Parent:** AL-BAYAN-003 (decision id 568).
**Window:** Phase 1 = Week 1 per AL-BAYAN-003.

## Texts to acquire

### 1. Safīnat al-Najā fī mā Yajib ʿalā al-ʿAbd li-Mawlāh
- Author: **Sālim b. Sumayr al-Ḥaḍramī** (d. 1271 AH / 1855 CE)
- Madhab: Shafi'i
- dalil_strength: `primer_juridical`
- Public domain: YES (author d. 1855)

**Candidate sources:**
- al-Maktaba al-Shamela: search at https://shamela.ws — find the "kutub al-fiqh al-Shafiʿi" section
- KSU digital library: https://lib.ksu.edu.sa
- Wikisource Arabic: https://ar.wikisource.org — search "سفينة النجا"
- archive.org: full-text PDF scans of pre-1928 editions

**Verification questions BEFORE ingestion:**
- [ ] Source is matn-only (no editor commentary apparatus)
- [ ] Plain text / OCR-clean (not scan-only)
- [ ] License: public domain confirmed (no editor copyright on apparatus)
- [ ] Complete (all standard chapters present: Wuḍū', Ṣalāh, Zakāh, Ṣawm, Ḥajj as minimum)

### 2. Matn Abī Shujā' al-Iṣfahānī (الغاية والتقريب)
- Author: **Ahmad b. al-Husayn al-Iṣfahānī (Abū Shujāʿ)** (d. 593 AH / 1196 CE)
- Madhab: Shafi'i
- dalil_strength: `primer_juridical`
- Public domain: YES (author d. 1196)

**Candidate sources:**
- al-Maktaba al-Shamela
- Wikisource Arabic: search "متن أبي شجاع" or "الغاية والتقريب"
- archive.org

**Verification questions:** same as above.

## Source clearance — **REJECTED** sources (do NOT ingest)

Per AL-BAYAN-003 constraint:
- Dar al-Minhaj tahqiq editions
- Dar al-Salam tahqiq editions
- Dar Ibn Hazm tahqiq editions
- Any other contemporary tahqiq edition where editor copyright on apparatus is unclear
- Contemporary Bahasa / English translations (translator copyright)

## Ingestion process (when sources are verified)

### 1. Download + SHA verify

```bash
# Per source, save raw + canonical-form + SHA
mkdir -p data/juridical/safinah_al_najaa
curl -L "https://..." > data/juridical/safinah_al_najaa/raw.txt
shasum -a 256 data/juridical/safinah_al_najaa/raw.txt > data/juridical/safinah_al_najaa/raw.txt.sha256

# Canonicalize: NFC normalize, strip page numbers + bracketed apparatus, preserve baab markers
python3 scripts/juridical/canonicalize.py \
  --in data/juridical/safinah_al_najaa/raw.txt \
  --out data/juridical/safinah_al_najaa/matn.txt
shasum -a 256 data/juridical/safinah_al_najaa/matn.txt > data/juridical/safinah_al_najaa/matn.txt.sha256
```

### 2. Schema (proposed — gates on AL-BAYAN-003 challenge window close)

```sql
-- supabase/migrations/YYYYMMDD_juridical_corpus.sql
CREATE TYPE dalil_strength_tier AS ENUM (
  'primer_juridical', 'standard_juridical', 'spine_juridical'
  -- NOT 'binding_fatwa' per AL-BAYAN-003 constraint
);

CREATE TYPE madhab_label AS ENUM ('shafii', 'hanafi', 'maliki', 'hanbali');

CREATE TABLE juridical_texts (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  text_name                text NOT NULL,                    -- 'Safīnat al-Najā'
  author_name              text NOT NULL,                    -- 'Sālim b. Sumayr al-Ḥaḍramī'
  author_death_hijri       integer,                          -- 1271
  author_death_gregorian   integer,                          -- 1855
  madhab                   madhab_label NOT NULL,            -- per AL-BAYAN-003: populated for every row
  dalil_strength           dalil_strength_tier NOT NULL,
  baab_or_section          text NOT NULL,                    -- 'Bāb al-Wuḍū'' '
  baab_order               integer NOT NULL,                 -- for stable ordering within text
  arabic_text              text NOT NULL,                    -- the matn passage
  arabic_text_sha256       text NOT NULL,                    -- per Q-1 from quranic-text-integrity skill, transposed
  ingestion_provenance_id  uuid NOT NULL REFERENCES ingestion_provenance(id) ON DELETE RESTRICT,
  created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX juridical_texts_madhab_idx ON juridical_texts (madhab);
CREATE INDEX juridical_texts_text_baab_idx ON juridical_texts (text_name, baab_order);

ALTER TABLE juridical_texts ENABLE ROW LEVEL SECURITY;
CREATE POLICY juridical_texts_read ON juridical_texts FOR SELECT TO anon, authenticated USING (true);

-- ingestion_provenance audit table — per AL-BAYAN-003 constraint
CREATE TABLE IF NOT EXISTS ingestion_provenance (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_url               text NOT NULL,
  source_maintainer        text NOT NULL,                    -- 'al-Maktaba al-Shamela' / 'Wikisource AR' / 'KSU' / 'archive.org'
  license_declaration      text NOT NULL,                    -- 'public domain' + reasoning
  ingestion_timestamp      timestamptz NOT NULL DEFAULT now(),
  source_file_sha256       text NOT NULL,
  verified_by_identity     text NOT NULL,                    -- 'musa' / '<scholar-name>' / 'cc-scholar'
  notes                    text
);

CREATE INDEX ingestion_provenance_source_idx ON ingestion_provenance (source_url);
ALTER TABLE ingestion_provenance ENABLE ROW LEVEL SECURITY;
CREATE POLICY ingestion_provenance_read ON ingestion_provenance FOR SELECT TO anon, authenticated USING (true);
```

### 3. Ingestion script (planned)

```python
# scripts/juridical/ingest_matn.py
# python3 ingest_matn.py --text safinah_al_najaa --source-file data/.../matn.txt
#   --source-url ... --source-maintainer "al-Maktaba al-Shamela"
#   --verified-by musa
```

The script:
1. Computes file SHA-256
2. INSERTs ingestion_provenance row, captures id
3. Splits matn.txt into baab segments (uses ` بَابُ ` / ` فصل ` markers)
4. INSERTs each segment as juridical_texts row with provenance FK + arabic_text_sha256

## Embedding integration (later — gates on retrieval activation)

Per AL-BAYAN-003 + EMBED_PIPELINE_v02 §migration-plan Phase A step 9:
- juridical_texts schema population can run PARALLEL with Quran backfill
- juridical RETRIEVAL goes live ONLY after Quran retrieval calibrated and retract-gate unlocked (Phase E in migration plan)
- Same encoder (BGE-M3 winner) embeds juridical content
- Separate `juridical_embeddings` table mirroring `ayah_embeddings`

## Citation rendering on retrieval (LOAD-BEARING per AL-BAYAN-003)

When juridical retrieval activates (Phase E), every cited matn passage MUST surface as:
```
{
  "text_name": "Safīnat al-Najā",
  "baab": "Bāb al-Wuḍū'",
  "madhab": "shafii",
  "dalil_strength_tier": "primer_juridical",
  "quoted_passage_arabic": "<matn text>",
  "translation_optional": "<query-time LLM translation>"
}
```

NEVER as "the Shafi'i school says X" or "according to classical fiqh, Y" — those are authority-performance per AL-BAYAN-002 + AL-BAYAN-003 anti-authority-performance rule.

## Action items

**Operator (Musa or cc-orchestrator):**
- [ ] Verify Safīnat al-Najā Wikisource URL (cc-scholar's WebFetch attempt 404'd)
- [ ] Verify Matn Abī Shujā' Wikisource URL (same)
- [ ] If Wikisource fails: fall back to al-Maktaba al-Shamela direct download
- [ ] Confirm source is matn-only (no apparatus)
- [ ] Download + SHA-record + checkout to `data/juridical/<text>/`

**cc-scholar (after operator confirms sources):**
- [ ] Author migration `juridical_texts` + `ingestion_provenance` schema (above)
- [ ] Author `scripts/juridical/canonicalize.py`
- [ ] Author `scripts/juridical/ingest_matn.py`
- [ ] Run ingestion; verify counts; commit data + provenance row

## References

- AL-BAYAN-003 (decision id 568) — parent ruling
- EMBED_PIPELINE_v02 §scope + §migration-plan Phase A step 9 + Phase E
- AL-BAYAN-002 + AL-BAYAN-003 anti-authority-performance citation rule
- `quranic-text-integrity` skill Q-1 (transposed: source SHA discipline applies to juridical too)
