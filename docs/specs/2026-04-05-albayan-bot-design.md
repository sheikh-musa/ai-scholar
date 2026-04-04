# Al-Bayan Bot Design Spec

**Bot:** @AlBayanBot (seeker-facing Islamic knowledge Q&A)
**Status:** Phase 1 -- 10-ayat proof of concept, deterministic keyword matching
**Date:** 2026-04-05
**Author:** Musa (CTO, Wingmen)

---

## 1. Overview

Al-Bayan is a public-facing Telegram bot that answers Islamic knowledge questions using **exclusively sourced material** from Supabase (Quran ayat, dual tafsir, hadith). It is separate from Mizan (@mzninterfacebot), the internal admin/research tool.

Key difference from Mizan: Al-Bayan has **no Claude CLI dependency**. Phase 1 is entirely deterministic -- keyword match, Supabase query, formatted response. No AI generation.

### Relationship to Mizan

| Concern | Mizan | Al-Bayan |
|---------|-------|----------|
| Audience | Internal / admin | Public seekers |
| Engine | Claude CLI + Supabase | Supabase only (Phase 1) |
| Response style | Research-grade, verbose | Concise, practice-oriented |
| Fiqh handling | Can surface raw data | Scholar Gate (hard redirect) |
| Tier markers | Optional | Mandatory on every response |

---

## 2. Architecture

```
Telegram (long-polling)
        |
        v
  Telegram Bot Adapter        (Python script, long-polling via getUpdates)
        |
        v
  POST /functions/v1/ask-scholar   (Supabase Edge Function, Deno/TS)
        |
        v
  Query Pipeline               (normalize -> fiqh detect -> topic match
        |                        -> ayat fetch -> tafsir fetch -> format)
        v
  Supabase Tables              (ayat, tafsir_entries, topics, ayat_topics,
                                 hadiths, hadith_collections)
```

### 2.1 Telegram Bot Adapter

A lightweight Python script (`scripts/albayan_bot.py`) that:

- Long-polls Telegram via `getUpdates` (same pattern as `scripts/mizan_bot.py`)
- Accepts user text messages only (no inline, no callbacks in Phase 1)
- Forwards the user query to the Supabase Edge Function via `POST`
- Receives a structured JSON response and sends it back as a formatted Telegram message
- Uses `ALBAYAN_BOT_TOKEN` env var (separate token from Mizan)
- No session memory in Phase 1 (stateless per-message)

The adapter is intentionally thin. All logic lives in the Edge Function.

### 2.2 Supabase Edge Function: `ask-scholar`

**Endpoint:** `POST /functions/v1/ask-scholar`

**Request body:**
```json
{
  "query": "What does the Quran say about patience?",
  "chat_id": "123456789"
}
```

**Response body:**
```json
{
  "status": "ok" | "scholar_gate" | "no_match",
  "tier": "quoted" | "paraphrased" | "inferred" | "ai_generated",
  "response": {
    "arabic": "...",
    "translation": "...",
    "translator": "...",
    "surah_name": "...",
    "surah_number": 2,
    "ayah_number": 153,
    "tafsir": [
      {
        "scholar_name": "Ibn Kathir",
        "source_work": "Tafsir Ibn Kathir",
        "english_text": "...",
        "output_tier": "paraphrased"
      }
    ],
    "tier_marker": "[Quoted: Quran 2:153]",
    "practice": "Try: When you feel overwhelmed today, pause and say 'Inna lillahi wa inna ilayhi raji'un' before reacting.",
    "scholar_gate_message": null
  }
}
```

**Why an Edge Function?** Keeps query logic server-side, supports future web/app clients without duplicating logic, enforces RLS, and keeps the bot adapter stateless.

---

## 3. Query Processing Pipeline

The Edge Function processes every query through these stages in order:

### Stage 1: Normalize

- Lowercase the query
- Strip punctuation except Arabic characters
- Remove stop words (reuse the same set from Mizan: "what", "does", "the", "quran", "say", "about", etc.)
- Extract remaining keywords as a list

**Input:** `"What does the Quran say about patience?"`
**Output:** `["patience"]`

### Stage 2: Scholar Gate (Fiqh Detection)

Check if any extracted keyword matches the fiqh keyword set:

```
halal, haram, permissible, ruling, allowed, forbidden,
fard, wajib, makruh, mustahab, fatwa, obligatory,
is it permissible, can i, am i allowed, is it ok to,
should i, must i, do i have to
```

Also match common fiqh phrase patterns:
- `"is X halal/haram"`
- `"can I do X in Islam"`
- `"ruling on X"`
- `"is it permissible to X"`

**If triggered:** Immediately return `status: "scholar_gate"` with the Scholar Gate message (see Section 6). Skip all remaining stages.

### Stage 3: Topic Match

Query the `topics` table with each keyword using `ilike`:

```sql
SELECT id, name FROM topics WHERE name ILIKE '%patience%' LIMIT 1;
```

If a topic matches, fetch linked ayat via `ayat_topics`:

```sql
SELECT ayah_id FROM ayat_topics WHERE topic_id = :tid LIMIT 3;
```

If no topic matches, fall through to Stage 4.

### Stage 4: Ayat Fetch

**If topic matched:** Fetch the linked ayat by ID from Stage 3.

**If no topic matched:** Fall back to full-text search on `english_translation`:

```sql
SELECT * FROM search_ayat_fts(query := 'patience', lim := 3);
```

If FTS fails or returns nothing, try `ILIKE` fallback on `english_translation`.

If still nothing, return `status: "no_match"` with a graceful message.

### Stage 5: Tafsir Fetch

For each matched ayah, fetch tafsir entries:

```sql
SELECT scholar_name, source_work, english_text, output_tier
FROM tafsir_entries
WHERE ayah_id = :ayah_id
ORDER BY scholar_name;
```

Filter out Arabic-only entries (where `english_text` starts with `[Arabic tafsir`).

### Stage 6: Format Response

Assemble the final response object with:
- Arabic text + translation + tafsir
- Tier markers on every piece of content
- Practice off-ramp suggestion
- Source references

---

## 4. Response Format

Every Al-Bayan response follows this exact template when sent via Telegram (Markdown parse mode):

### 4.1 Standard Response (Ayah Found)

```
--- Al-Bayan ---

{arabic_text}

"{english_translation}"
-- {translator}, {surah_name} ({surah_number}:{ayah_number})
[Quoted: Quran]

--- Tafsir ---

{scholar_name} ({source_work}):
"{tafsir_english_text}"
[Paraphrased: {scholar_name}]

--- Practice ---

{practice_suggestion}

---
Sources: Quran {surah_number}:{ayah_number}, {source_work}
Transparency: All content above is sourced. Tier markers [] indicate origin.
```

### 4.2 Scholar Gate Response

```
--- Al-Bayan ---

Your question touches on a fiqh (Islamic legal) ruling.

Al-Bayan does not generate legal rulings. Fiqh requires qualified scholarship, understanding of context, and knowledge of your specific situation.

Please consult:
- A local imam or scholar you trust
- Qualified fatwa services (e.g., IslamQA.info, Dar al-Ifta)
- Your community's religious authority

We can still help you explore what the Quran and scholars say about the *topic* behind your question. Try rephrasing without asking for a ruling.

---
[AI-Generated: This redirect message is not Islamic knowledge]
```

### 4.3 No Match Response

```
--- Al-Bayan ---

We could not find a direct match for your question in our current corpus.

Try:
- Using simpler keywords (e.g., "patience" instead of "how to be patient")
- Asking about a specific verse (e.g., "2:153")
- Asking about a topic (e.g., "gratitude", "prayer")

Phase 1 covers a limited set of topics. More coverage is coming soon.

---
[AI-Generated: This message is not Islamic knowledge]
```

### 4.4 Tier Markers

Every piece of content in a response MUST carry a tier marker:

| Tier | Marker | When Used |
|------|--------|-----------|
| Quoted | `[Quoted: Quran X:Y]` or `[Quoted: Hadith, Collection #N]` | Verbatim Quran text, verbatim hadith text |
| Paraphrased | `[Paraphrased: Scholar Name]` | Tafsir summaries attributed to a named scholar |
| Inferred | `[Inferred: cross-source]` | Not used in Phase 1 |
| AI-Generated | `[AI-Generated: ...]` | System messages, practice suggestions, error messages |

The practice off-ramp always carries `[AI-Generated]` implicitly since it is a suggestion, not Islamic knowledge.

---

## 5. Practice Off-Ramp

Every successful response ends with an actionable practice suggestion. In Phase 1, these are **static mappings** from topic to suggestion, not AI-generated.

### Practice Map (Phase 1)

```
patience    -> "Try: Next time you face difficulty, pause before reacting and say 'HasbunAllahu wa ni'mal wakeel.'"
gratitude   -> "Try: Before sleeping tonight, write down three blessings you noticed today."
prayer      -> "Try: Add one extra du'a after your next salah for someone you care about."
repentance  -> "Try: Take a quiet moment today to make istighfar (seek forgiveness) for something specific."
knowledge   -> "Try: Commit to reading one verse with tafsir each day this week."
charity     -> "Try: Give something -- even a smile or kind word -- to someone today."
forgiveness -> "Try: Think of someone who wronged you and make du'a for their guidance."
justice     -> "Try: In your next disagreement, actively listen to the other person's perspective first."
family      -> "Try: Call or message a family member you haven't spoken to recently."
trust       -> "Try: Identify one worry you are carrying and consciously hand it over to Allah in du'a."
```

**Default** (when no specific topic matches): `"Try: Read the verse above one more time slowly, and sit with its meaning for a minute."`

---

## 6. Scholar Gate Design

### 6.1 Trigger Conditions

The Scholar Gate fires when ANY of these conditions are true:

**Keyword match** -- query contains any of:
`halal`, `haram`, `permissible`, `ruling`, `allowed`, `forbidden`, `fard`, `wajib`, `makruh`, `mustahab`, `fatwa`, `obligatory`, `sinful`

**Phrase match** -- query matches patterns:
- `"is it (halal|haram|permissible|allowed|forbidden) to ..."`
- `"can I ... in Islam"`
- `"ruling on ..."`
- `"is it ok/okay to ..."`
- `"am I allowed to ..."`
- `"do I have to ..."`
- `"what is the punishment for ..."`

### 6.2 Behavior

- Scholar Gate is **always checked before** any data lookup (Stage 2 in pipeline)
- When triggered, the response is the Scholar Gate message (Section 4.2) and processing **stops**
- No ayat, tafsir, or hadith are returned alongside a Scholar Gate response
- The Scholar Gate message itself is marked `[AI-Generated]`

### 6.3 False Positive Handling

Some queries mention fiqh keywords in an educational context (e.g., "What does halal mean?"). Phase 1 accepts false positives -- the Scholar Gate fires conservatively. This is intentional: it is safer to over-redirect than to risk generating a fiqh ruling.

Phase 2 may introduce disambiguation ("Are you asking for a ruling, or exploring the concept?").

---

## 7. Supabase Edge Function: `ask-scholar`

### 7.1 Function Signature

```
POST /functions/v1/ask-scholar
Content-Type: application/json
Authorization: Bearer <anon_key>
```

### 7.2 Implementation Notes

- Written in TypeScript (Deno runtime, standard Supabase Edge Function)
- Uses `@supabase/supabase-js` to query tables with RLS (anon key, not service role)
- Stateless -- no session tracking
- Timeout: 10 seconds max
- Returns JSON always, never plain text
- All errors return a valid JSON response with `status: "error"` and a user-friendly message

### 7.3 Query Flow (Pseudocode)

```
function handleAskScholar(query, chat_id):
    keywords = normalize(query)

    if fiqhDetect(keywords, query):
        return { status: "scholar_gate", response: SCHOLAR_GATE_MESSAGE }

    // Try verse reference first (e.g., "2:153")
    ref = parseVerseReference(query)
    if ref:
        ayah = fetchAyah(ref.surah, ref.ayah)
        tafsir = fetchTafsir(ayah.id)
        return formatResponse(ayah, tafsir)

    // Try topic match
    topic = matchTopic(keywords)
    if topic:
        ayat = fetchAyatByTopic(topic.id, limit=3)
        tafsir = fetchTafsirBatch(ayat)
        practice = PRACTICE_MAP[topic.name] || DEFAULT_PRACTICE
        return formatResponse(ayat, tafsir, practice)

    // Fall back to FTS
    ayat = searchAyatFTS(keywords.join(" "), limit=3)
    if ayat.length > 0:
        tafsir = fetchTafsirBatch(ayat)
        return formatResponse(ayat, tafsir, DEFAULT_PRACTICE)

    return { status: "no_match", response: NO_MATCH_MESSAGE }
```

### 7.4 Tables Accessed

| Table | Access | Purpose |
|-------|--------|---------|
| `ayat` | SELECT | Arabic text, English translation |
| `tafsir_entries` | SELECT | Scholar commentary on ayat |
| `topics` | SELECT | Topic name lookup |
| `ayat_topics` | SELECT | Topic-to-ayah mapping |
| `hadiths` | SELECT | Phase 2 (not in Phase 1 scope) |
| `hadith_collections` | SELECT | Phase 2 |

All access goes through RLS. The Edge Function uses the anon key.

---

## 8. Telegram Bot Adapter

### 8.1 File

`scripts/albayan_bot.py`

### 8.2 Responsibilities

1. Long-poll Telegram via `getUpdates` (offset tracking, 30s timeout)
2. Extract `chat_id` and `text` from each message
3. Handle `/start` and `/help` commands locally (static text)
4. For all other text, `POST` to the Edge Function
5. Format the JSON response into Telegram Markdown
6. Send via `sendMessage` with `parse_mode=Markdown`
7. Log errors to `logs/albayan_bot.log` and `logs/albayan_bot.err`

### 8.3 Commands

| Command | Response |
|---------|----------|
| `/start` | Welcome message explaining Al-Bayan, its scope, and the transparency model |
| `/help` | Usage instructions, example queries, link to topics list |
| `/topics` | Phase 2: list available topics |

### 8.4 Environment Variables

| Var | Required | Description |
|-----|----------|-------------|
| `ALBAYAN_BOT_TOKEN` | Yes | Telegram bot token for @AlBayanBot |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anon key (not service role) |

### 8.5 Deployment

- Runs on Musa's Mac Mini alongside the orchestrator
- Managed by the orchestrator's process supervisor (same as Mizan)
- Logs to `~/wingmen/projects/ai-scholar/logs/`

---

## 9. Hard Constraints (North Star)

These constraints are non-negotiable and apply to every phase:

1. **No fiqh rulings.** Al-Bayan never tells a user something is halal, haram, obligatory, or forbidden. The Scholar Gate catches these queries and redirects.

2. **No AI-generated religious claims.** Phase 1 has zero AI generation. All Quran text is verbatim from the corpus. All tafsir is attributed to named scholars. Practice suggestions are system-generated and clearly marked.

3. **Sources always traceable.** Every piece of content carries a tier marker pointing to its origin. A user can always verify: which surah/ayah, which scholar, which source work.

4. **4-tier transparency is mandatory.** No response leaves Al-Bayan without tier markers on every content block.

5. **Practice off-ramp on every interaction.** Even Scholar Gate and no-match responses should encourage the user toward beneficial action (reading Quran, making du'a, etc.).

6. **Conservative over permissive.** When uncertain whether a query is seeking a ruling, assume it is and trigger the Scholar Gate. False positives are acceptable; false negatives are not.

7. **No data leakage.** The bot adapter uses the anon key, never the service role key. RLS policies on all tables remain enforced.

---

## 10. Phase 1 Scope and Boundaries

### In Scope
- 10 ayat (proof of concept subset) with full tafsir
- Keyword-to-topic matching for those 10 ayat
- Dual tafsir display (e.g., Ibn Kathir + one other)
- Verse reference lookup (e.g., "2:153")
- Scholar Gate for fiqh queries
- Practice off-ramp from static map
- Tier markers on all content

### Out of Scope (Phase 2+)
- Full 6,236 ayat corpus
- 36k hadith integration
- AI-generated responses (Claude integration)
- Session memory / follow-up detection
- Inline keyboards / callback queries
- Arabic-language interface
- Semantic search (embeddings)
- User feedback collection
- Rate limiting / abuse prevention

---

## 11. Open Questions

1. **Which 10 ayat?** Need to select the Phase 1 proof-of-concept set. Candidates: frequently asked topics (patience, gratitude, prayer, repentance, knowledge).
2. **Practice map coverage.** Do we need practice suggestions for all 10 ayat individually, or is topic-level mapping sufficient?
3. **Edge Function cold start.** Supabase Edge Functions have cold start latency. Acceptable for Phase 1? May need keep-alive pings.
4. **Hadith in Phase 1?** The spec says Phase 1 is ayat-only, but hadiths are in the DB. Should we include hadith search as a stretch goal?
