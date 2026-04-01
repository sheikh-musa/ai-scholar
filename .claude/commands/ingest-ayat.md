---
allowed-tools: mcp__supabase__*, Read(*), WebFetch(*), Agent(*)
description: Ingest Quranic ayat with dual tafsir (Ibn Kathir + Al-Sa'di) into Supabase for the Al-Bayān North Star knowledge engine
---

# ingest-ayat

Ingest Quranic verses with scholarly tafsir into the Al-Bayān knowledge base. Maintains the four-tier transparency model and scholar gate integrity.

## Usage

Specify which ayat to ingest. Default: Phase 1 set (10 foundational ayat).

Phase 1 ayat: 2:153, 14:7, 51:56, 39:53, 2:45, 4:135, 65:3, 20:114, 94:5-6, 98:5

## Pre-flight

Verify schema exists:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('ayat', 'tafsir_entries', 'topics', 'ayat_topics');
```

If tables don't exist, run the Phase 1 schema creation first.

## For Each Ayah

Launch a sub-agent per ayah (run up to 5 in parallel). Each agent:

### 1. Prepare Arabic Text
- Source the Arabic text with full tashkeel (diacritics)
- Include transliteration
- Prepare two English translations (Saheeh International + Pickthall recommended)

### 2. Insert Ayah Record
```sql
INSERT INTO ayat (surah_number, ayah_number, arabic_text, translation_en, translation_en_alt, transliteration)
VALUES ($surah, $ayah, $arabic, $translation1, $translation2, $transliteration)
ON CONFLICT (surah_number, ayah_number) DO NOTHING
RETURNING id;
```

### 3. Insert Ibn Kathir Tafsir
```sql
INSERT INTO tafsir_entries (ayah_id, scholar_name, source_text, source_reference, tier, language)
VALUES ($ayah_id, 'Ibn Kathir', $text, 'Tafsir Ibn Kathir', 'quoted', 'en')
ON CONFLICT DO NOTHING;
```

### 4. Insert Al-Sa'di Tafsir
```sql
INSERT INTO tafsir_entries (ayah_id, scholar_name, source_text, source_reference, tier, language)
VALUES ($ayah_id, 'Al-Sa''di', $text, 'Taysir al-Karim al-Rahman', 'quoted', 'en')
ON CONFLICT DO NOTHING;
```

### 5. Tag Topics
Match to relevant topics and insert into ayat_topics.

Common topics: patience (sabr), gratitude (shukr), purpose (ibadah), mercy (rahmah), prayer (salah), justice (adl), trust (tawakkul), knowledge (ilm), ease (yusr), sincerity (ikhlas)

## Four-Tier Transparency Markers

Always tag content correctly:
- `quoted` — Direct Quran text or exact scholar words
- `paraphrased` — Scholar's meaning in modern language
- `inferred` — Logical extension from sources
- `ai_generated` — Claude synthesis (use sparingly, flag clearly)

## Hard Constraints

- NEVER generate fictional tafsir — all content must trace to named scholars
- Arabic text is SACRED — verify character by character if needed
- Use ON CONFLICT DO NOTHING — never overwrite existing entries
- Every tafsir entry MUST have a source_reference
- Flag any content that might touch fiqh with scholar_gate = true

## Post-Ingestion Validation

After all ayat inserted:
```sql
SELECT
  a.surah_number, a.ayah_number,
  COUNT(t.id) as tafsir_count,
  ARRAY_AGG(t.scholar_name) as scholars
FROM ayat a
LEFT JOIN tafsir_entries t ON t.ayah_id = a.id
GROUP BY a.surah_number, a.ayah_number
ORDER BY a.surah_number, a.ayah_number;
```

Report: X ayat ingested, Y tafsir entries, Z topics tagged.
