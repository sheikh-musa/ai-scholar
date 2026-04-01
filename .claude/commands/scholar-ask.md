---
allowed-tools: mcp__supabase__*, mcp__telegram__*
description: Handle an Al-Bayān Islamic knowledge query — route through the scholar gate, query the knowledge base, and return a tiered response
---

# scholar-ask

Process an Islamic knowledge question through the Al-Bayān North Star reasoning engine.

## Input

The question to answer: $ARGUMENTS

## Step 1 — Scholar Gate Check

Scan the question for fiqh keywords. If any found, IMMEDIATELY redirect:

Fiqh keywords: halal, haram, permissible, forbidden, ruling, fatwa, pray, fasting, zakat, hajj, wudu, ghusl, nikah, divorce, inheritance, riba, interest

**If fiqh keyword detected:**
```
This question involves a religious ruling (fiqh). For accurate guidance specific
to your situation, please consult a qualified Islamic scholar.

For general Quranic context on this topic, I can share relevant ayat and tafsir.
Would that be helpful?
```

**Do not proceed to knowledge lookup for fiqh questions.**

## Step 2 — Normalize Query

Extract keywords from the question. Remove stop words. Identify core theme.

## Step 3 — Knowledge Lookup

```sql
SELECT
  a.surah_number, a.ayah_number,
  a.arabic_text, a.translation_en, a.transliteration,
  te.scholar_name, te.source_text, te.source_reference, te.tier,
  t.name as topic_name, t.arabic_name as topic_arabic
FROM ayat a
JOIN tafsir_entries te ON te.ayah_id = a.id
JOIN ayat_topics at ON at.ayah_id = a.id
JOIN topics t ON t.id = at.topic_id
WHERE t.name ILIKE ANY($keywords)
   OR a.translation_en ILIKE ANY($keyword_patterns)
ORDER BY a.surah_number, a.ayah_number
LIMIT 3;
```

## Step 4 — Generate Practice Off-Ramp

For each result, generate a reflective question that connects the ayah to lived practice. Example: for 2:153 (patience), ask "Where in your life is Allah asking you to practice sabr right now?"

## Step 5 — Format Response

```
━━━━━━━━━━━━━━━━━━━━━━
{arabic_text}
━━━━━━━━━━━━━━━━━━━━━━
{transliteration}

"{translation_en}"
— Quran {surah_number}:{ayah_number} [QUOTED]

📚 Ibn Kathir:
{ibn_kathir_text} [QUOTED]

📚 Al-Sa'di:
{alsadi_text} [QUOTED]

🤔 Reflect:
{practice_off_ramp}

━━━
Tier markers: [QUOTED] = direct source | [PARAPHRASED] = scholar's meaning | [INFERRED] = logical extension | [AI] = synthesis
```

## Hard Constraints

- Scholar gate is ABSOLUTE — no fiqh without human scholar
- Never claim faith or perform belief — process knowledge only
- Every claim must show its tier marker
- Arabic text must never be altered
- If no knowledge found, say so honestly: "I don't have ayat on this topic yet."
