import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY")!;
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STOP_WORDS = new Set([
  "what",
  "does",
  "the",
  "quran",
  "say",
  "about",
  "is",
  "in",
  "islam",
  "of",
  "a",
  "an",
  "and",
  "to",
  "for",
  "how",
  "why",
  "who",
  "which",
  "that",
  "this",
  "it",
  "on",
  "with",
  "from",
  "can",
  "do",
  "i",
  "me",
  "my",
  "we",
  "our",
  "you",
  "your",
  "tell",
  "explain",
  "meaning",
  "please",
  "help",
  "would",
  "could",
  "should",
  "be",
  "are",
  "was",
  "were",
  "been",
  "being",
  "have",
  "has",
  "had",
  "there",
  "their",
  "them",
  "they",
  "its",
  "not",
  "but",
  "or",
  "if",
  "so",
  "at",
  "by",
  "up",
  "out",
  "no",
  "as",
  "just",
  "also",
  "than",
  "too",
  "very",
  "will",
  "one",
  "all",
  "any",
  "each",
  "every",
  "some",
]);

const FIQH_KEYWORDS = new Set([
  "halal",
  "haram",
  "permissible",
  "ruling",
  "allowed",
  "forbidden",
  "fard",
  "wajib",
  "makruh",
  "mustahab",
  "fatwa",
  "obligatory",
  "sinful",
]);

const FIQH_PHRASES = [
  /is\s+it\s+(halal|haram|permissible|allowed|forbidden)\s+to/i,
  /can\s+i\s+.+\s+in\s+islam/i,
  /ruling\s+on/i,
  /is\s+it\s+ok(ay)?\s+to/i,
  /am\s+i\s+allowed\s+to/i,
  /do\s+i\s+have\s+to/i,
  /what\s+is\s+the\s+punishment\s+for/i,
  /must\s+i/i,
  /is\s+it\s+permissible/i,
];

const PRACTICE_MAP: Record<string, string> = {
  patience:
    "Try: Next time you face difficulty, pause before reacting and say 'HasbunAllahu wa ni'mal wakeel.'",
  gratitude:
    "Try: Before sleeping tonight, write down three blessings you noticed today.",
  prayer:
    "Try: Add one extra du'a after your next salah for someone you care about.",
  worship:
    "Try: Add one extra du'a after your next salah for someone you care about.",
  repentance:
    "Try: Take a quiet moment today to make istighfar (seek forgiveness) for something specific.",
  knowledge:
    "Try: Commit to reading one verse with tafsir each day this week.",
  charity:
    "Try: Give something -- even a smile or kind word -- to someone today.",
  forgiveness:
    "Try: Think of someone who wronged you and make du'a for their guidance.",
  justice:
    "Try: In your next disagreement, actively listen to the other person's perspective first.",
  family:
    "Try: Call or message a family member you haven't spoken to recently.",
  trust:
    "Try: Identify one worry you are carrying and consciously hand it over to Allah in du'a.",
  tawakkul:
    "Try: Identify one worry you are carrying and consciously hand it over to Allah in du'a.",
  mercy:
    "Try: Show mercy to someone today -- forgive a mistake or be gentle in your words.",
  guidance:
    "Try: Before making a decision today, ask Allah for guidance in a short du'a.",
  praise:
    "Try: Start your morning by saying 'Alhamdulillah' and reflecting on what it means.",
  sovereignty:
    "Try: Remind yourself today that Allah is in control, and let go of one thing you cannot change.",
  accountability:
    "Try: Before sleeping, reflect on your day and ask: did I live today in a way I would be proud of on the Day of Judgment?",
  sincerity:
    "Try: Before your next good deed, pause and renew your intention purely for Allah.",
  afterlife:
    "Try: Spend five minutes reflecting on what truly matters beyond this temporary life.",
  tawhid:
    "Try: Reflect on one sign of Allah's creation around you today and say 'SubhanAllah.'",
  prophethood:
    "Try: Read about one Sunnah of the Prophet (peace be upon him) and try to practice it today.",
  hardship:
    "Try: Remember that with every hardship comes ease -- identify one silver lining in a current difficulty.",
  community:
    "Try: Reach out to someone in your community today with a kind word or offer of help.",
  creation:
    "Try: Step outside and observe one sign of Allah's creation -- the sky, a tree, the rain -- and reflect.",
  provision:
    "Try: Trust that your rizq is written, and focus today on gratitude for what you already have.",
  remembrance:
    "Try: Set aside five quiet minutes today for dhikr -- say 'SubhanAllah', 'Alhamdulillah', 'Allahu Akbar' 33 times each.",
};

const DEFAULT_PRACTICE =
  "Try: Read the verse above one more time slowly, and sit with its meaning for a minute.";

const SCHOLAR_GATE_MESSAGE =
  "This question touches on Islamic jurisprudence (fiqh). " +
  "Al-Bayan does not generate legal rulings. Fiqh requires qualified scholarship, " +
  "understanding of context, and knowledge of your specific situation. " +
  "Please consult a qualified scholar or trusted fatwa service.";

const SUGGESTED_RESOURCES = [
  "Your local imam or mosque",
  "IslamQA.info",
  "Darul Ifta",
];

// Surah name lookup (114 surahs)
const SURAH_NAMES: Record<number, string> = {
  1: "Al-Fatihah",
  2: "Al-Baqarah",
  3: "Ali 'Imran",
  4: "An-Nisa",
  5: "Al-Ma'idah",
  6: "Al-An'am",
  7: "Al-A'raf",
  8: "Al-Anfal",
  9: "At-Tawbah",
  10: "Yunus",
  11: "Hud",
  12: "Yusuf",
  13: "Ar-Ra'd",
  14: "Ibrahim",
  15: "Al-Hijr",
  16: "An-Nahl",
  17: "Al-Isra",
  18: "Al-Kahf",
  19: "Maryam",
  20: "Ta-Ha",
  21: "Al-Anbiya",
  22: "Al-Hajj",
  23: "Al-Mu'minun",
  24: "An-Nur",
  25: "Al-Furqan",
  26: "Ash-Shu'ara",
  27: "An-Naml",
  28: "Al-Qasas",
  29: "Al-Ankabut",
  30: "Ar-Rum",
  31: "Luqman",
  32: "As-Sajdah",
  33: "Al-Ahzab",
  34: "Saba",
  35: "Fatir",
  36: "Ya-Sin",
  37: "As-Saffat",
  38: "Sad",
  39: "Az-Zumar",
  40: "Ghafir",
  41: "Fussilat",
  42: "Ash-Shura",
  43: "Az-Zukhruf",
  44: "Ad-Dukhan",
  45: "Al-Jathiyah",
  46: "Al-Ahqaf",
  47: "Muhammad",
  48: "Al-Fath",
  49: "Al-Hujurat",
  50: "Qaf",
  51: "Adh-Dhariyat",
  52: "At-Tur",
  53: "An-Najm",
  54: "Al-Qamar",
  55: "Ar-Rahman",
  56: "Al-Waqi'ah",
  57: "Al-Hadid",
  58: "Al-Mujadila",
  59: "Al-Hashr",
  60: "Al-Mumtahanah",
  61: "As-Saff",
  62: "Al-Jumu'ah",
  63: "Al-Munafiqun",
  64: "At-Taghabun",
  65: "At-Talaq",
  66: "At-Tahrim",
  67: "Al-Mulk",
  68: "Al-Qalam",
  69: "Al-Haqqah",
  70: "Al-Ma'arij",
  71: "Nuh",
  72: "Al-Jinn",
  73: "Al-Muzzammil",
  74: "Al-Muddaththir",
  75: "Al-Qiyamah",
  76: "Al-Insan",
  77: "Al-Mursalat",
  78: "An-Naba",
  79: "An-Nazi'at",
  80: "Abasa",
  81: "At-Takwir",
  82: "Al-Infitar",
  83: "Al-Mutaffifin",
  84: "Al-Inshiqaq",
  85: "Al-Buruj",
  86: "At-Tariq",
  87: "Al-A'la",
  88: "Al-Ghashiyah",
  89: "Al-Fajr",
  90: "Al-Balad",
  91: "Ash-Shams",
  92: "Al-Layl",
  93: "Ad-Duha",
  94: "Ash-Sharh",
  95: "At-Tin",
  96: "Al-Alaq",
  97: "Al-Qadr",
  98: "Al-Bayyinah",
  99: "Az-Zalzalah",
  100: "Al-Adiyat",
  101: "Al-Qari'ah",
  102: "At-Takathur",
  103: "Al-Asr",
  104: "Al-Humazah",
  105: "Al-Fil",
  106: "Quraysh",
  107: "Al-Ma'un",
  108: "Al-Kawthar",
  109: "Al-Kafirun",
  110: "An-Nasr",
  111: "Al-Masad",
  112: "Al-Ikhlas",
  113: "Al-Falaq",
  114: "An-Nas",
};

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/** Normalize query: lowercase, strip punctuation (keep Arabic), remove stop words */
function normalize(query: string): string[] {
  const lowered = query.toLowerCase();
  // Keep letters (latin + arabic), digits, spaces
  const cleaned = lowered.replace(/[^\p{L}\p{N}\s]/gu, " ");
  const words = cleaned.split(/\s+/).filter((w) => w.length > 0);
  return words.filter((w) => !STOP_WORDS.has(w));
}

/** Check if the query triggers the scholar gate (fiqh detection) */
function detectFiqh(keywords: string[], rawQuery: string): boolean {
  // Check keyword match
  for (const kw of keywords) {
    if (FIQH_KEYWORDS.has(kw)) return true;
  }
  // Check phrase patterns against the original query
  for (const pattern of FIQH_PHRASES) {
    if (pattern.test(rawQuery)) return true;
  }
  return false;
}

/** Try to parse a verse reference like "2:153" or "surah 2 ayah 153" */
function parseVerseReference(
  query: string
): { surah: number; ayah: number } | null {
  // Match "2:153" or "2:153"
  const colonMatch = query.match(/(\d{1,3}):(\d{1,3})/);
  if (colonMatch) {
    return {
      surah: parseInt(colonMatch[1]),
      ayah: parseInt(colonMatch[2]),
    };
  }
  // Match "surah 2 ayah 153" or "surah 2 verse 153"
  const wordMatch = query.match(
    /surah\s+(\d{1,3})\s+(?:ayah|verse|ayat)\s+(\d{1,3})/i
  );
  if (wordMatch) {
    return {
      surah: parseInt(wordMatch[1]),
      ayah: parseInt(wordMatch[2]),
    };
  }
  return null;
}

/** Get surah name from number */
function getSurahName(surahNumber: number): string {
  return SURAH_NAMES[surahNumber] || `Surah ${surahNumber}`;
}

// ---------------------------------------------------------------------------
// Database query functions
// ---------------------------------------------------------------------------

interface AyahRow {
  id: string;
  surah_number: number;
  ayah_number: number;
  arabic_text: string;
  english_translation: string;
  translator: string;
}

interface TafsirRow {
  scholar_name: string;
  source_work: string;
  english_text: string;
  output_tier: string;
}

interface TopicRow {
  id: string;
  name: string;
  synonyms: string[] | null;
}

/** Fetch a single ayah by surah:ayah reference */
async function fetchAyahByRef(
  surah: number,
  ayah: number
): Promise<AyahRow | null> {
  const { data, error } = await supabase
    .from("ayat")
    .select("id, surah_number, ayah_number, arabic_text, english_translation, translator")
    .eq("surah_number", surah)
    .eq("ayah_number", ayah)
    .limit(1)
    .single();

  if (error || !data) return null;
  return data as AyahRow;
}

/** Match keywords against topics table (name + synonyms) */
async function matchTopic(keywords: string[]): Promise<TopicRow | null> {
  // First try exact name match
  for (const kw of keywords) {
    const { data, error } = await supabase
      .from("topics")
      .select("id, name, synonyms")
      .ilike("name", `%${kw}%`)
      .limit(1);

    if (!error && data && data.length > 0) {
      return data[0] as TopicRow;
    }
  }

  // Then try synonym match -- fetch all topics and check synonyms client-side
  // (More efficient than N queries with array contains)
  const { data: allTopics, error } = await supabase
    .from("topics")
    .select("id, name, synonyms");

  if (error || !allTopics) return null;

  for (const kw of keywords) {
    for (const topic of allTopics) {
      const t = topic as TopicRow;
      if (t.synonyms && t.synonyms.some((s) => s.toLowerCase() === kw)) {
        return t;
      }
    }
  }

  return null;
}

/** Fetch ayat linked to a topic via ayat_topics join table */
async function fetchAyatByTopic(topicId: string, limit = 3): Promise<AyahRow[]> {
  const { data: links, error: linkError } = await supabase
    .from("ayat_topics")
    .select("ayah_id")
    .eq("topic_id", topicId)
    .limit(limit);

  if (linkError || !links || links.length === 0) return [];

  const ayahIds = links.map((l: { ayah_id: string }) => l.ayah_id);

  const { data, error } = await supabase
    .from("ayat")
    .select("id, surah_number, ayah_number, arabic_text, english_translation, translator")
    .in("id", ayahIds);

  if (error || !data) return [];
  return data as AyahRow[];
}

/** Full-text search on ayat english_translation via the search_ayat_fts function */
async function searchAyatFTS(query: string, limit = 3): Promise<AyahRow[]> {
  const { data, error } = await supabase.rpc("search_ayat_fts", {
    query,
    lim: limit,
  });

  if (error || !data || data.length === 0) return [];
  return data as AyahRow[];
}

/** ILIKE fallback search on english_translation */
async function searchAyatILike(
  keywords: string[],
  limit = 3
): Promise<AyahRow[]> {
  for (const kw of keywords) {
    const { data, error } = await supabase
      .from("ayat")
      .select("id, surah_number, ayah_number, arabic_text, english_translation, translator")
      .ilike("english_translation", `%${kw}%`)
      .limit(limit);

    if (!error && data && data.length > 0) {
      return data as AyahRow[];
    }
  }
  return [];
}

/** Fetch tafsir entries for a list of ayah IDs */
async function fetchTafsirBatch(
  ayahIds: string[]
): Promise<Record<string, TafsirRow[]>> {
  const { data, error } = await supabase
    .from("tafsir_entries")
    .select("ayah_id, scholar_name, source_work, english_text, output_tier")
    .in("ayah_id", ayahIds)
    .order("scholar_name", { ascending: true });

  if (error || !data) return {};

  const result: Record<string, TafsirRow[]> = {};
  for (const row of data) {
    // Filter out Arabic-only tafsir entries
    if (
      row.english_text &&
      !row.english_text.startsWith("[Arabic tafsir")
    ) {
      if (!result[row.ayah_id]) result[row.ayah_id] = [];
      result[row.ayah_id].push({
        scholar_name: row.scholar_name,
        source_work: row.source_work,
        english_text: row.english_text,
        output_tier: row.output_tier,
      });
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Response builders
// ---------------------------------------------------------------------------

interface MatchEntry {
  surah: number;
  ayah: number;
  surah_name: string;
  arabic: string;
  translation: string;
  translator: string;
  tafsir: {
    scholar: string;
    source: string;
    text: string;
    tier: string;
  }[];
}

function buildScholarGateResponse(question: string) {
  return {
    question,
    scholar_gate: true,
    message: SCHOLAR_GATE_MESSAGE,
    suggested_resources: SUGGESTED_RESOURCES,
  };
}

function buildNoMatchResponse(question: string) {
  return {
    question,
    scholar_gate: false,
    matches: [],
    practice_offramp:
      "Try: Explore a topic like 'patience', 'gratitude', or 'prayer', or ask about a specific verse like '2:153'.",
    tiers_used: [],
    message:
      "We could not find a direct match for your question in our current corpus. " +
      "Try using simpler keywords (e.g., 'patience' instead of 'how to be patient') " +
      "or asking about a specific verse (e.g., '2:153').",
  };
}

function buildSuccessResponse(
  question: string,
  matches: MatchEntry[],
  topicName: string | null
) {
  const tiersUsed = new Set<string>();
  for (const m of matches) {
    tiersUsed.add("quoted"); // Quran text is always quoted
    for (const t of m.tafsir) {
      tiersUsed.add(t.tier);
    }
  }

  const practice =
    topicName && PRACTICE_MAP[topicName]
      ? PRACTICE_MAP[topicName]
      : DEFAULT_PRACTICE;

  return {
    question,
    scholar_gate: false,
    matches,
    practice_offramp: practice,
    tiers_used: Array.from(tiersUsed),
  };
}

/** Convert ayat + tafsir data into MatchEntry objects */
function buildMatches(
  ayat: AyahRow[],
  tafsirMap: Record<string, TafsirRow[]>
): MatchEntry[] {
  return ayat.map((a) => ({
    surah: a.surah_number,
    ayah: a.ayah_number,
    surah_name: getSurahName(a.surah_number),
    arabic: a.arabic_text,
    translation: a.english_translation,
    translator: a.translator,
    tafsir: (tafsirMap[a.id] || []).map((t) => ({
      scholar: t.scholar_name,
      source: t.source_work,
      text: t.english_text,
      tier: t.output_tier,
    })),
  }));
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed. Use POST." }),
      { status: 405, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  try {
    const body = await req.json();
    // Accept both "question" and "query" field names
    const rawQuery: string = body.question || body.query || "";

    if (!rawQuery.trim()) {
      return new Response(
        JSON.stringify({ error: "Missing 'question' field in request body." }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }

    // Stage 1: Normalize
    const keywords = normalize(rawQuery);

    // Stage 2: Scholar Gate (fiqh detection)
    if (detectFiqh(keywords, rawQuery)) {
      return new Response(JSON.stringify(buildScholarGateResponse(rawQuery)), {
        status: 200,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }

    // Try verse reference first (e.g., "2:153")
    const verseRef = parseVerseReference(rawQuery);
    if (verseRef) {
      const ayah = await fetchAyahByRef(verseRef.surah, verseRef.ayah);
      if (ayah) {
        const tafsirMap = await fetchTafsirBatch([ayah.id]);
        const matches = buildMatches([ayah], tafsirMap);
        return new Response(
          JSON.stringify(buildSuccessResponse(rawQuery, matches, null)),
          {
            status: 200,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
          }
        );
      }
    }

    // Stage 3: Topic match
    const topic = await matchTopic(keywords);
    if (topic) {
      const ayat = await fetchAyatByTopic(topic.id, 3);
      if (ayat.length > 0) {
        const ayahIds = ayat.map((a) => a.id);
        const tafsirMap = await fetchTafsirBatch(ayahIds);
        const matches = buildMatches(ayat, tafsirMap);
        return new Response(
          JSON.stringify(buildSuccessResponse(rawQuery, matches, topic.name)),
          {
            status: 200,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
          }
        );
      }
    }

    // Stage 4: Full-text search fallback
    const joinedKeywords = keywords.join(" ");
    let ayat = await searchAyatFTS(joinedKeywords, 3);

    // ILIKE fallback if FTS returns nothing
    if (ayat.length === 0) {
      ayat = await searchAyatILike(keywords, 3);
    }

    if (ayat.length > 0) {
      const ayahIds = ayat.map((a) => a.id);
      const tafsirMap = await fetchTafsirBatch(ayahIds);
      const matches = buildMatches(ayat, tafsirMap);
      return new Response(
        JSON.stringify(buildSuccessResponse(rawQuery, matches, null)),
        {
          status: 200,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }

    // No match
    return new Response(JSON.stringify(buildNoMatchResponse(rawQuery)), {
      status: 200,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return new Response(
      JSON.stringify({
        error: "Internal server error",
        detail: message,
      }),
      {
        status: 500,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      }
    );
  }
});
