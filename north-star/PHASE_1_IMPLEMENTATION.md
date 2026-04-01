# PHASE 1 — Technical Implementation Spec
# Al-Bayan Proof of Concept: 10 Ayat with Dual Tafsir

---

## 1. Islamic Knowledge Schema

These tables are separate from the Wingmen schema. They live in the same Supabase project but under a distinct logical domain for Al-Bayan.

### Table: `ayat`

```sql
CREATE TABLE ayat (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  surah_number INT NOT NULL,
  ayah_number INT NOT NULL,
  arabic_text TEXT NOT NULL,
  english_translation TEXT NOT NULL,
  translator TEXT NOT NULL DEFAULT 'Sahih International',
  topic_tags TEXT[],
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (surah_number, ayah_number, translator)
);
```

### Table: `tafsir_entries`

```sql
CREATE TABLE tafsir_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ayah_id UUID NOT NULL REFERENCES ayat(id) ON DELETE CASCADE,
  scholar_name TEXT NOT NULL,
  source_work TEXT NOT NULL,
  arabic_text TEXT,
  english_text TEXT NOT NULL,
  output_tier TEXT NOT NULL CHECK (output_tier IN ('quoted', 'paraphrased')),
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### Table: `topics`

```sql
CREATE TABLE topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  arabic_name TEXT,
  description TEXT,
  synonyms TEXT[]
);
```

### Table: `ayat_topics`

```sql
CREATE TABLE ayat_topics (
  ayah_id UUID NOT NULL REFERENCES ayat(id) ON DELETE CASCADE,
  topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (ayah_id, topic_id)
);
```

### Row-Level Security (RLS)

```sql
-- Enable RLS on all tables
ALTER TABLE ayat ENABLE ROW LEVEL SECURITY;
ALTER TABLE tafsir_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE ayat_topics ENABLE ROW LEVEL SECURITY;

-- service_role has full access (bypasses RLS by default in Supabase)
-- No explicit policy needed for service_role as it bypasses RLS.

-- Authenticated users: SELECT only
CREATE POLICY "Authenticated users can read ayat"
  ON ayat FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Authenticated users can read tafsir_entries"
  ON tafsir_entries FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Authenticated users can read topics"
  ON topics FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Authenticated users can read ayat_topics"
  ON ayat_topics FOR SELECT
  TO authenticated
  USING (true);

-- Anonymous users: SELECT only
CREATE POLICY "Anon users can read ayat"
  ON ayat FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "Anon users can read tafsir_entries"
  ON tafsir_entries FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "Anon users can read topics"
  ON topics FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "Anon users can read ayat_topics"
  ON ayat_topics FOR SELECT
  TO anon
  USING (true);
```

---

## 2. The 10 Ayat Selection

These 10 verses cover foundational themes that a seeker is most likely to ask about. Each verse is well-established in tafsir literature from both Ibn Kathir and Al-Sa'di, ensuring dual commentary is available.

| # | Theme | Reference | Surah Name | Rationale |
|---|-------|-----------|------------|-----------|
| 1 | Patience | 2:153 | Al-Baqarah | Foundational verse on seeking help through sabr and salah. One of the most frequently cited verses on patience in the Quran. |
| 2 | Gratitude | 14:7 | Ibrahim | Promise of increase through shukr. Establishes the direct link between gratitude and divine provision. |
| 3 | Purpose | 51:56 | Adh-Dhariyat | Creation for worship. The most concise statement of human purpose in the Quran. |
| 4 | Mercy | 39:53 | Az-Zumar | Allah's mercy encompasses all. The verse that prevents despair and opens the door to repentance for every soul. |
| 5 | Prayer | 2:45 | Al-Baqarah | Seek help through patience and prayer. Establishes salah as the practical mechanism for navigating difficulty. |
| 6 | Justice | 4:135 | An-Nisa | Stand firmly for justice even against yourselves. The Quranic standard for justice that transcends self-interest. |
| 7 | Tawakkul | 65:3 | At-Talaq | Whoever relies upon Allah, He is sufficient. The core verse on trust in divine sufficiency. |
| 8 | Knowledge | 20:114 | Ta-Ha | "My Lord, increase me in knowledge." The prophetic du'a that models the posture of the lifelong learner. |
| 9 | Ease with hardship | 94:5-6 | Ash-Sharh | With hardship comes ease. Repeated twice for emphasis — the Quranic promise that difficulty is never the final word. |
| 10 | Sincerity | 98:5 | Al-Bayyinah | Worship Allah sincerely. Ikhlas as the condition that separates accepted worship from performance. |

**Note:** This selection is preliminary and requires scholar review before final confirmation. The themes were chosen to cover the most common questions a seeker encounters: suffering, purpose, hope, practice, ethics, trust, growth, struggle, and intention.

---

## 3. Data Ingestion

### Phase 1 Approach: Manual Seed SQL

Phase 1 uses a manually curated SQL seed file. No automated ingestion pipeline. Every piece of data is hand-verified before insertion.

**Sources:**
- **Arabic text:** Tanzil.net (clean, non-commercial licensed Uthmani script)
- **English translation:** Sahih International (widely recognized, clear modern English)
- **Tafsir (Ibn Kathir):** Authenticated English translations of Tafsir Ibn Kathir
- **Tafsir (Al-Sa'di):** Authenticated English translations of Taysir al-Karim al-Rahman

### Template INSERT: Ayah 2:153 with Dual Tafsir

```sql
-- Insert the ayah
INSERT INTO ayat (id, surah_number, ayah_number, arabic_text, english_translation, translator, topic_tags)
VALUES (
  'a1b2c3d4-0001-4000-8000-000000000001',
  2,
  153,
  'يَا أَيُّهَا الَّذِينَ آمَنُوا اسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ ۚ إِنَّ اللَّهَ مَعَ الصَّابِرِينَ',
  'O you who have believed, seek help through patience and prayer. Indeed, Allah is with the patient.',
  'Sahih International',
  ARRAY['patience', 'prayer', 'sabr', 'salah']
);

-- Insert the topic
INSERT INTO topics (id, name, arabic_name, description, synonyms)
VALUES (
  't1b2c3d4-0001-4000-8000-000000000001',
  'patience',
  'الصبر',
  'The Islamic concept of patient perseverance through difficulty, rooted in trust in Allah''s wisdom and timing.',
  ARRAY['sabr', 'patient', 'perseverance', 'endurance', 'steadfastness', 'forbearance']
);

-- Link ayah to topic
INSERT INTO ayat_topics (ayah_id, topic_id)
VALUES (
  'a1b2c3d4-0001-4000-8000-000000000001',
  't1b2c3d4-0001-4000-8000-000000000001'
);

-- Insert tafsir: Ibn Kathir
INSERT INTO tafsir_entries (id, ayah_id, scholar_name, source_work, english_text, output_tier)
VALUES (
  'f1b2c3d4-0001-4000-8000-000000000001',
  'a1b2c3d4-0001-4000-8000-000000000001',
  'Ibn Kathir',
  'Tafsir Ibn Kathir',
  'Allah commands His believing servants to seek help through patience and prayer when facing difficulties and hardships. Patience is of two types: patience in avoiding sins and patience in performing acts of worship. The prayer is the best act of worship that involves the body. Allah specifically mentions patience and prayer together because patience restrains the soul from desires and sinful acts, while the prayer connects the servant to his Lord and draws him closer to Allah. The statement "Indeed, Allah is with the patient" means that Allah grants His special companionship, support, guidance, and clear victory to those who are patient.',
  'paraphrased'
);

-- Insert tafsir: Al-Sa'di
INSERT INTO tafsir_entries (id, ayah_id, scholar_name, source_work, english_text, output_tier)
VALUES (
  'f1b2c3d4-0002-4000-8000-000000000002',
  'a1b2c3d4-0001-4000-8000-000000000001',
  'Al-Sa''di',
  'Taysir al-Karim al-Rahman',
  'Allah commands the believers to seek help in all their affairs through patience and prayer. Patience means restraining the soul from that which it dislikes. It encompasses three categories: patience in obeying Allah, patience in avoiding His prohibitions, and patience with the decrees of Allah that may be painful. All three are included in this verse. As for prayer, it is the greatest act of worship and the most beneficial means of attaining all that is good and warding off all that is harmful. This is why Allah specifically singled it out after mentioning patience generally. The statement "Indeed, Allah is with the patient" is an assurance that Allah provides His special care, support, and closeness to those who exercise patience — a companionship of guidance, assistance, and granting of success.',
  'paraphrased'
);
```

### Automated Ingestion Pipeline

Deferred to Phase 2. Phase 1 focuses on proving the query and delivery pipeline with manually verified data. Automated ingestion introduces risks around text accuracy, diacritical marks, and attribution that must be solved separately.

---

## 4. Query API

### Endpoint

**Supabase Edge Function:** `POST /functions/v1/ask-scholar`

### Input

```json
{
  "question": "string"
}
```

### Processing Logic (Pseudocode)

```
function handleQuestion(question: string):
  1. Normalize the question:
     - Convert to lowercase
     - Strip common stop words ("what", "does", "islam", "say", "about", "the", "is", "a", "an", "in", "of", "how", "why", "can", "do")
     - Extract remaining keywords as an array

  2. Check for fiqh ruling detection:
     - If any keyword matches ["halal", "haram", "permissible", "ruling", "allowed", "forbidden", "fard", "wajib", "makruh", "mustahab"]:
       -> Return fiqh gate response (see Section 6)

  3. Match keywords against topics:
     - Query topics table WHERE name ILIKE any keyword OR any element of synonyms ILIKE any keyword
     - Collect matching topic IDs

  4. If no topic matches found:
     - Return no-match response

  5. Fetch matching ayat:
     - Query ayat_topics JOIN ayat WHERE topic_id IN (matched topic IDs)

  6. For each matched ayah:
     - Fetch all tafsir_entries WHERE ayah_id = ayah.id
     - Order by scholar_name ASC

  7. Generate practice off-ramp:
     - Based on the matched topic name, generate a reflective question
     - Example for "patience": "What is one thing you can do today to practice patience?"

  8. Return structured response
```

### Output JSON: Match Found

```json
{
  "question": "What does Islam say about patience?",
  "matches": [
    {
      "surah": 2,
      "ayah": 153,
      "surah_name": "Al-Baqarah",
      "arabic": "\u064a\u064e\u0627 \u0623\u064e\u064a\u0651\u064f\u0647\u064e\u0627 \u0627\u0644\u0651\u064e\u0630\u0650\u064a\u0646\u064e \u0622\u0645\u064e\u0646\u064f\u0648\u0627 \u0627\u0633\u0652\u062a\u064e\u0639\u0650\u064a\u0646\u064f\u0648\u0627 \u0628\u0650\u0627\u0644\u0635\u0651\u064e\u0628\u0652\u0631\u0650 \u0648\u064e\u0627\u0644\u0635\u0651\u064e\u0644\u064e\u0627\u0629\u0650...",
      "translation": "O you who have believed, seek help through patience and prayer. Indeed, Allah is with the patient.",
      "translator": "Sahih International",
      "tafsir": [
        {
          "scholar": "Ibn Kathir",
          "source": "Tafsir Ibn Kathir",
          "text": "Allah commands His believing servants to seek help through patience and prayer when facing difficulties...",
          "tier": "paraphrased"
        },
        {
          "scholar": "Al-Sa'di",
          "source": "Taysir al-Karim al-Rahman",
          "text": "Allah commands the believers to seek help in all their affairs through patience and prayer...",
          "tier": "paraphrased"
        }
      ]
    }
  ],
  "practice_offramp": "What is one thing you can do today to practice patience?",
  "tiers_used": ["quoted", "paraphrased"]
}
```

### Output JSON: No Match

```json
{
  "question": "What does Islam say about cryptocurrency?",
  "matches": [],
  "message": "I don't have knowledge on this topic yet. My current scope covers 10 verses across themes of patience, gratitude, mercy, purpose, prayer, justice, trust in God, knowledge, hardship, and sincerity."
}
```

### Edge Function: Deno/TypeScript Pseudocode

```typescript
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const STOP_WORDS = new Set([
  "what", "does", "islam", "say", "about", "the", "is", "a", "an",
  "in", "of", "how", "why", "can", "do", "tell", "me", "please",
  "i", "want", "to", "know", "learn", "understand",
]);

const FIQH_KEYWORDS = new Set([
  "halal", "haram", "permissible", "ruling", "allowed", "forbidden",
  "fard", "wajib", "makruh", "mustahab",
]);

const SURAH_NAMES: Record<number, string> = {
  2: "Al-Baqarah",
  4: "An-Nisa",
  14: "Ibrahim",
  20: "Ta-Ha",
  39: "Az-Zumar",
  51: "Adh-Dhariyat",
  65: "At-Talaq",
  94: "Ash-Sharh",
  98: "Al-Bayyinah",
};

const PRACTICE_OFFRAMPS: Record<string, string> = {
  patience: "What is one thing you can do today to practice patience?",
  gratitude: "What is one blessing you can thank Allah for right now?",
  purpose: "How can you align one action today with your purpose of worship?",
  mercy: "Who in your life needs your mercy today?",
  prayer: "Can you pray your next salah with more presence and focus?",
  justice: "Where in your life can you stand for what is right, even when it is hard?",
  tawakkul: "What is one worry you can surrender to Allah today?",
  knowledge: "What is one thing you can learn today that brings you closer to Allah?",
  hardship: "What difficulty in your life might be carrying hidden ease?",
  sincerity: "Is there one act of worship you can do today purely for Allah, with no audience?",
};

serve(async (req: Request) => {
  try {
    const { question } = await req.json();

    if (!question || typeof question !== "string") {
      return new Response(
        JSON.stringify({ error: "A 'question' field (string) is required." }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    // Step 1: Extract keywords
    const keywords = question
      .toLowerCase()
      .replace(/[^\w\s]/g, "")
      .split(/\s+/)
      .filter((word: string) => word.length > 1 && !STOP_WORDS.has(word));

    // Step 2: Check for fiqh keywords
    const hasFiqhKeyword = keywords.some((kw: string) => FIQH_KEYWORDS.has(kw));
    if (hasFiqhKeyword) {
      return new Response(
        JSON.stringify({
          question,
          matches: [],
          message:
            "This question involves a fiqh ruling that requires qualified scholarly judgment. " +
            "I can share relevant Quranic verses and commentary for context, but I cannot issue rulings. " +
            "Please consult a qualified scholar (mufti) for a definitive answer.",
          fiqh_gate: true,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    // Step 3: Match keywords against topics
    const { data: matchedTopics, error: topicError } = await supabase
      .from("topics")
      .select("id, name, synonyms");

    if (topicError) throw topicError;

    const relevantTopicIds: string[] = [];
    const matchedTopicNames: string[] = [];

    for (const topic of matchedTopics || []) {
      const allTerms = [topic.name, ...(topic.synonyms || [])].map((t: string) =>
        t.toLowerCase()
      );
      const isMatch = keywords.some((kw: string) =>
        allTerms.some((term: string) => term.includes(kw) || kw.includes(term))
      );
      if (isMatch) {
        relevantTopicIds.push(topic.id);
        matchedTopicNames.push(topic.name);
      }
    }

    // Step 4: No matches
    if (relevantTopicIds.length === 0) {
      return new Response(
        JSON.stringify({
          question,
          matches: [],
          message:
            "I don't have knowledge on this topic yet. My current scope covers " +
            "10 verses across themes of patience, gratitude, mercy, purpose, prayer, " +
            "justice, trust in God, knowledge, hardship, and sincerity.",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    // Step 5: Fetch matching ayat via ayat_topics
    const { data: ayatTopicLinks, error: linkError } = await supabase
      .from("ayat_topics")
      .select("ayah_id")
      .in("topic_id", relevantTopicIds);

    if (linkError) throw linkError;

    const ayahIds = [...new Set((ayatTopicLinks || []).map((l: any) => l.ayah_id))];

    const { data: ayatRows, error: ayatError } = await supabase
      .from("ayat")
      .select("*")
      .in("id", ayahIds);

    if (ayatError) throw ayatError;

    // Step 6: For each ayah, fetch tafsir entries
    const matches = [];
    const tiersUsed = new Set<string>();

    for (const ayah of ayatRows || []) {
      const { data: tafsirRows, error: tafsirError } = await supabase
        .from("tafsir_entries")
        .select("*")
        .eq("ayah_id", ayah.id)
        .order("scholar_name", { ascending: true });

      if (tafsirError) throw tafsirError;

      const tafsirFormatted = (tafsirRows || []).map((t: any) => {
        tiersUsed.add(t.output_tier);
        return {
          scholar: t.scholar_name,
          source: t.source_work,
          text: t.english_text,
          tier: t.output_tier,
        };
      });

      matches.push({
        surah: ayah.surah_number,
        ayah: ayah.ayah_number,
        surah_name: SURAH_NAMES[ayah.surah_number] || `Surah ${ayah.surah_number}`,
        arabic: ayah.arabic_text,
        translation: ayah.english_translation,
        translator: ayah.translator,
        tafsir: tafsirFormatted,
      });
    }

    // Step 7: Generate practice off-ramp
    const primaryTopic = matchedTopicNames[0] || "general";
    const practiceOfframp =
      PRACTICE_OFFRAMPS[primaryTopic] ||
      "What is one thing you can do today to make this real in your life?";

    // Step 8: Return response
    return new Response(
      JSON.stringify({
        question,
        matches,
        practice_offramp: practiceOfframp,
        tiers_used: [...tiersUsed],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: "Internal server error", details: String(err) }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
});
```

---

## 5. Telegram Bot

### Bot Identity

**Bot:** @AlBayanBot (distinct from the Wingmen CTO bot)

This is a separate Telegram bot with its own token, registered via BotFather. It serves one purpose: answer questions about Islam using the Al-Bayan knowledge base.

### Flow

```
User sends message to @AlBayanBot
  -> Bot receives update via webhook or polling
  -> Bot extracts message text
  -> Bot calls POST /functions/v1/ask-scholar with { "question": message_text }
  -> Bot receives JSON response
  -> Bot formats response as Telegram message
  -> Bot sends formatted message back to user
```

### Response Template: Match Found

```
Quran [S:A] — [Surah Name]

[Arabic text]

[English translation]
— Sahih International

---

Tafsir — Ibn Kathir [Tier 2: Paraphrased]
[Commentary text]

Tafsir — Al-Sa'di [Tier 2: Paraphrased]
[Commentary text]

---
What is one thing you can do today to make this real?
```

**Example:**

```
Quran 2:153 — Al-Baqarah

يَا أَيُّهَا الَّذِينَ آمَنُوا اسْتَعِينُوا بِالصَّبْرِ وَالصَّلَاةِ ۚ إِنَّ اللَّهَ مَعَ الصَّابِرِينَ

O you who have believed, seek help through patience and prayer. Indeed, Allah is with the patient.
— Sahih International

---

Tafsir — Ibn Kathir [Tier 2: Paraphrased]
Allah commands His believing servants to seek help through patience and prayer when facing difficulties and hardships. Patience is of two types: patience in avoiding sins and patience in performing acts of worship. The prayer is the best act of worship that involves the body. The statement "Indeed, Allah is with the patient" means that Allah grants His special companionship, support, guidance, and clear victory to those who are patient.

Tafsir — Al-Sa'di [Tier 2: Paraphrased]
Allah commands the believers to seek help in all their affairs through patience and prayer. Patience means restraining the soul from that which it dislikes. It encompasses three categories: patience in obeying Allah, patience in avoiding His prohibitions, and patience with the decrees of Allah that may be painful. The statement "Indeed, Allah is with the patient" is an assurance that Allah provides His special care, support, and closeness to those who exercise patience.

---
What is one thing you can do today to practice patience?
```

### Response Template: No Match

```
I don't have knowledge on this topic yet.

My current scope covers 10 verses across these themes:
- Patience
- Gratitude
- Mercy
- Purpose
- Prayer
- Justice
- Trust in God (Tawakkul)
- Knowledge
- Hardship and Ease
- Sincerity

Try asking about one of these topics, and I will share what I have with full sources.
```

### Fiqh Detection

If the user's question contains any of the following keywords: "halal", "haram", "permissible", "ruling", "allowed", "forbidden" — the bot triggers the scholar gate redirect instead of attempting to answer.

**Fiqh Gate Response:**

```
This question involves a fiqh ruling that requires qualified scholarly judgment.

I can share relevant Quranic verses and commentary for context, but I cannot issue rulings. Please consult a qualified scholar (mufti) for a definitive answer.

If you would like to explore related Quranic themes instead, try asking about patience, gratitude, mercy, purpose, prayer, justice, trust in God, knowledge, hardship, or sincerity.
```

---

## 6. Scholar Gate (Phase 1 Simplification)

### Tier Delivery Rules

| Tier | Label | Delivery | Gate Required? |
|------|-------|----------|----------------|
| Tier 1 | Quoted | Delivered directly. Quran and authenticated hadith with full citation. | No |
| Tier 2 | Paraphrased | Delivered directly. Synthesized from named scholarly sources with attribution. | No |
| Tier 3 | Inferred | Delivered with mandatory disclaimer. | Yes (disclaimer) |
| Tier 4 | AI-Generated | Never presented as Islamic knowledge. | Blocked |

### Tier 3 Disclaimer

When Tier 3 content is delivered, the following disclaimer must be appended:

> "This is an inference drawn from multiple sources. It has not been reviewed by a scholar. Please consult a qualified scholar for definitive guidance."

In Phase 1, Tier 3 content does not exist in the database. All seed data is Tier 1 (quoted ayat) or Tier 2 (paraphrased tafsir). The disclaimer mechanism is built now so it is ready when Tier 3 content enters the system in later phases.

### Tier 4 Handling

Tier 4 content (AI-generated articulations with no direct source) is never presented as Islamic knowledge, opinion, or guidance. If the system generates framing language (e.g., the practice off-ramp question), it is clearly distinct from sourced content and does not carry any Islamic authority marker.

### Fiqh Ruling Detection

If the user's question contains any of the following keywords, the system does not attempt to answer with ayat or tafsir. Instead, it returns the scholar gate redirect:

**Keywords:** `halal`, `haram`, `permissible`, `ruling`, `allowed`, `forbidden`

**Response:**

> "This question involves a fiqh ruling that requires qualified scholarly judgment. I can share relevant Quranic verses and commentary for context, but I cannot issue rulings. Please consult a qualified scholar (mufti) for a definitive answer."

### Phase 2 Enhancement (Deferred)

Phase 2 will introduce a scholar review queue:

- Tier 3 content is flagged and held in a review queue.
- Designated scholars (authenticated via Supabase auth with a `scholar` role) can approve or reject Tier 3 content.
- Approved Tier 3 content is promoted to Tier 2 with the reviewing scholar's name attached.
- Rejected Tier 3 content is removed from the delivery pipeline and logged for system improvement.

This queue does not exist in Phase 1. Phase 1 avoids the problem entirely by only seeding Tier 1 and Tier 2 content.

---

*Last Updated: 2026-04-01*
*Status: SPEC COMPLETE — Ready for implementation*
*Next Action: Execute the CREATE TABLE SQL in Supabase, then run the seed INSERT for all 10 ayat with dual tafsir.*
