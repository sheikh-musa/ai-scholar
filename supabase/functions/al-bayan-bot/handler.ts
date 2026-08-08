// al-bayan-bot / handler.ts
//
// Pure logic for the Al-Bayān Telegram *webhook* receiver. Kept free of any
// top-level `Deno.serve` so it is unit-testable (per CLAUDE.md: importing a
// module that boots Deno.serve is not testable). index.ts is the thin serve
// wrapper that injects real deps.
//
// DESIGN — this receiver is a THIN Telegram<->ask-scholar adapter. It does NOT
// re-implement any scholar logic. All retrieval, 4-tier tiering, scholar-gate
// routing (F-3), matched_passage overlay (F-2), no-hallucinated-isnad (F-4) AND
// mizan_interactions persistence are inherited from the ask-scholar Edge
// Function, which the poll bot (scripts/albayan_bot.py) already delegates to.
// This function only: validates the Telegram secret, formats ask-scholar's
// tiered JSON into a Telegram message, and sends it. It is the webhook twin of
// albayan_bot.py — format_response is ported 1:1 to preserve parity, including
// every tier marker (T-1/T-2).

// --- Static messages (ported verbatim from scripts/albayan_bot.py) ----------

export const WELCOME_MESSAGE =
  "*Bismillah* -- Welcome to Al-Bayan\n\n" +
  "I help you explore what the Quran and classical scholars say " +
  "about topics like patience, gratitude, mercy, prayer, and sincerity.\n\n" +
  "*How it works:*\n" +
  "Send me a question or topic and I will find relevant ayat " +
  "with tafsir from named scholars.\n\n" +
  "*Transparency:*\n" +
  "Every response is labelled with its source:\n" +
  "  [Quoted: Quran] -- verbatim Quran text\n" +
  "  [Paraphrased: Scholar] -- tafsir from a named scholar\n" +
  "  [AI-Generated] -- system messages, not Islamic knowledge\n\n" +
  "*Examples to try:*\n" +
  "  - patience\n" +
  "  - What does the Quran say about gratitude?\n" +
  "  - 2:153\n\n" +
  "*Important:* Al-Bayan does not issue fiqh rulings. " +
  "Questions about halal/haram will be redirected to qualified scholars.\n\n" +
  "_Phase 1 covers a limited set of topics. More coming soon._\n\n" +
  "---\n" +
  "[AI-Generated: This welcome message is not Islamic knowledge]";

export const HELP_MESSAGE =
  "*Al-Bayan -- Usage*\n\n" +
  "Send a topic keyword or question:\n" +
  "  - patience\n" +
  "  - gratitude\n" +
  "  - What does the Quran say about mercy?\n" +
  "  - 2:153\n\n" +
  "*Available topics (Phase 1):*\n" +
  "patience, gratitude, prayer, repentance, knowledge, " +
  "charity, forgiveness, justice, family, trust\n\n" +
  "*Commands:*\n" +
  "/start -- Welcome message\n" +
  "/help -- This message\n\n" +
  "---\n" +
  "[AI-Generated: This help message is not Islamic knowledge]";

export const NO_MATCH_MESSAGE =
  "--- Al-Bayan ---\n\n" +
  "I don't have specific knowledge on that topic yet.\n\n" +
  "Try asking about patience, gratitude, mercy, prayer, or sincerity.\n\n" +
  "You can also:\n" +
  "- Use simpler keywords (e.g., \"patience\" instead of \"how to be patient\")\n" +
  "- Ask about a specific verse (e.g., \"2:153\")\n\n" +
  "_Phase 1 covers a limited set of topics. More coverage is coming soon._\n\n" +
  "---\n" +
  "[AI-Generated: This message is not Islamic knowledge]";

export const SCHOLAR_GATE_MESSAGE =
  "--- Al-Bayan ---\n\n" +
  "Your question touches on a fiqh (Islamic legal) ruling.\n\n" +
  "Al-Bayan does not generate legal rulings. Fiqh requires qualified " +
  "scholarship, understanding of context, and knowledge of your specific situation.\n\n" +
  "Please consult:\n" +
  "- A local imam or scholar you trust\n" +
  "- Qualified fatwa services (e.g., IslamQA.info, Dar al-Ifta)\n" +
  "- Your community's religious authority\n\n" +
  "We can still help you explore what the Quran and scholars say about " +
  "the _topic_ behind your question. Try rephrasing without asking for a ruling.\n\n" +
  "---\n" +
  "[AI-Generated: This redirect message is not Islamic knowledge]";

export const ERROR_MESSAGE =
  "--- Al-Bayan ---\n\n" +
  "Something went wrong while processing your question. " +
  "Please try again in a moment.\n\n" +
  "---\n" +
  "[AI-Generated: This error message is not Islamic knowledge]";

// --- ask-scholar response types (subset the formatter reads) ----------------

export interface TafsirEntry {
  scholar?: string;
  source?: string;
  text?: string;
  tier?: string;
  matched_passage?: string | null;
  matched_passage_tier?: string | null;
}
export interface MatchEntry {
  surah?: number | string;
  ayah?: number | string;
  surah_name?: string;
  arabic?: string;
  translation?: string;
  translator?: string;
  tafsir?: TafsirEntry[];
}
export interface HadithMatch {
  collection?: string;
  hadith_number?: number | string;
  grading?: string | null;
  english?: string;
}
export interface AskScholarResponse {
  error?: unknown;
  scholar_gate?: boolean;
  matches?: MatchEntry[];
  hadith_matches?: HadithMatch[];
  practice_offramp?: string;
  message?: string;
}

// --- Formatting helpers (ported 1:1 from albayan_bot.py) --------------------

const SENTENCE_BOUNDARY = /(?<=[.!?])\s+/;

export function trimSentences(text: string, maxSentences = 3): string {
  const parts = text.trim().split(SENTENCE_BOUNDARY);
  let trimmed = parts.slice(0, maxSentences).join(" ");
  if (parts.length > maxSentences && trimmed && !".!?".includes(trimmed[trimmed.length - 1])) {
    trimmed += "…";
  }
  return trimmed;
}

function selectTafsir(tafsirList: TafsirEntry[] | undefined, maxEntries = 2): TafsirEntry[] {
  const valid = (tafsirList || []).filter(
    (t) => t.text && !t.text.startsWith("[Arabic tafsir")
  );
  // FTS-matched entries first (the relevance-ranked excerpts) — stable sort.
  const ordered = valid
    .map((t, i) => ({ t, i }))
    .sort((a, b) => {
      const ka = a.t.matched_passage ? 0 : 1;
      const kb = b.t.matched_passage ? 0 : 1;
      return ka === kb ? a.i - b.i : ka - kb;
    })
    .map((x) => x.t);
  return ordered.slice(0, maxEntries);
}

function selectBestMatch(matches: MatchEntry[]): [MatchEntry | null, MatchEntry[]] {
  if (!matches.length) return [null, []];
  for (const m of matches) {
    if ((m.tafsir || []).some((t) => t.matched_passage)) {
      const rest = matches.filter((x) => x !== m);
      return [m, rest.slice(0, 1)];
    }
  }
  return [matches[0], matches.slice(1, 2)];
}

/** Format the ask-scholar JSON into a concise Telegram message. Faithful port of
 * albayan_bot.py:format_response — preserves every tier marker (T-1/T-2), the
 * scholar-gate refusal (F-3), and the no-match floor. */
export function formatResponse(data: AskScholarResponse): string {
  if (data.error) return ERROR_MESSAGE;
  if (data.scholar_gate) return SCHOLAR_GATE_MESSAGE;

  const matches = data.matches || [];
  const hadithMatches = data.hadith_matches || [];

  if (!matches.length && !hadithMatches.length) return NO_MATCH_MESSAGE;

  const parts: string[] = ["--- Al-Bayan ---\n"];
  const sources: string[] = [];

  const [primary, secondary] = selectBestMatch(matches);

  if (primary) {
    const surahNum = primary.surah ?? "";
    const ayahNum = primary.ayah ?? "";
    const surahName = primary.surah_name ?? "";
    const arabic = primary.arabic ?? "";
    const translation = primary.translation ?? "";
    const translator = primary.translator ?? "";

    if (arabic) {
      parts.push(arabic);
      parts.push("");
    }
    if (translation) {
      const ref = surahName ? `${surahName} (${surahNum}:${ayahNum})` : `${surahNum}:${ayahNum}`;
      parts.push(`"${translation}"`);
      parts.push(`— ${translator ? translator + ", " : ""}${ref}`);
      parts.push(`[Quoted: Quran ${surahNum}:${ayahNum}]`);
      parts.push("");
      sources.push(`Quran ${surahNum}:${ayahNum}`);
    }

    for (const t of selectTafsir(primary.tafsir)) {
      const scholar = t.scholar || "Unknown";
      const source = t.source || "";
      const raw = t.matched_passage || t.text || "";
      if (!raw) continue;
      const excerpt = trimSentences(raw, 3);
      const rawTier = t.matched_passage_tier || t.tier || "paraphrased";
      const tier = rawTier.charAt(0).toUpperCase() + rawTier.slice(1);
      parts.push(`${scholar}:`);
      parts.push(`"${excerpt}"`);
      parts.push(`[${tier}: ${scholar}, ${source}]`);
      parts.push("");
      if (source && !sources.includes(source)) sources.push(source);
    }
  }

  if (secondary.length) {
    const sec = secondary[0];
    const sNum = sec.surah ?? "";
    const aNum = sec.ayah ?? "";
    const sName = sec.surah_name ?? "";
    const trans = sec.translation ?? "";
    if (trans && sNum && aNum) {
      const ref = sName ? `${sName} (${sNum}:${aNum})` : `${sNum}:${aNum}`;
      parts.push(`Also: "${trimSentences(trans, 1)}" — ${ref}`);
      parts.push(`[Quoted: Quran ${sNum}:${aNum}]`);
      parts.push("");
      sources.push(`Quran ${sNum}:${aNum}`);
    }
  }

  if (hadithMatches.length) {
    const h = hadithMatches[0];
    const coll = h.collection || "unknown";
    const num = h.hadith_number ?? "";
    const grading = h.grading || "";
    const english = h.english || "";
    if (english) {
      const excerpt = trimSentences(english, 2);
      let header = coll;
      if (num) header += ` #${num}`;
      if (grading) header += ` · ${grading}`;
      parts.push(`${header}:`);
      parts.push(`"${excerpt}"`);
      parts.push(`[Quoted: Hadith, ${coll} #${num}]`);
      parts.push("");
      if (!sources.includes(coll)) sources.push(coll);
    }
  }

  const practice = data.practice_offramp;
  if (practice) {
    parts.push(practice);
    parts.push("");
  }

  parts.push("---");
  if (sources.length) parts.push(`Sources: ${sources.join(", ")}`);
  parts.push("Tier markers [] indicate content origin.");
  return parts.join("\n");
}

// --- Telegram update handling ----------------------------------------------

export interface TelegramUpdate {
  message?: {
    text?: string;
    chat?: { id?: number | string };
    from?: { first_name?: string };
  };
}

export interface HandleDeps {
  /** Calls ask-scholar and returns its parsed JSON (retrieval/tiering/gate/persist). */
  callAskScholar: (query: string, chatId: number | string) => Promise<AskScholarResponse>;
  /** Sends a Telegram message. parseMode "Markdown" only for static welcome/help. */
  sendMessage: (chatId: number | string, text: string, parseMode?: "Markdown") => Promise<void>;
  /** Optional typing indicator; failures are swallowed by the impl. */
  sendTyping?: (chatId: number | string) => Promise<void>;
  /** Optional logger. */
  log?: (msg: string) => void;
}

/** Route one Telegram update. Mirrors albayan_bot.py:main() message handling.
 * Non-text / non-message updates are ignored. Never throws — errors become the
 * AI-generated ERROR_MESSAGE so the user always gets a tiered reply. */
export async function handleUpdate(update: TelegramUpdate, deps: HandleDeps): Promise<void> {
  const msg = update.message;
  if (!msg) return;
  const text = (msg.text || "").trim();
  const chatId = msg.chat?.id;
  if (!text || chatId === undefined || chatId === null) return;

  const lower = text.toLowerCase();
  if (lower === "/start" || lower === "/start@mzninterfacebot") {
    await deps.sendMessage(chatId, WELCOME_MESSAGE, "Markdown");
    return;
  }
  if (lower === "/help" || lower === "/help@mzninterfacebot") {
    await deps.sendMessage(chatId, HELP_MESSAGE, "Markdown");
    return;
  }

  if (deps.sendTyping) {
    try { await deps.sendTyping(chatId); } catch { /* non-fatal */ }
  }

  let responseText: string;
  try {
    const result = await deps.callAskScholar(text, chatId);
    responseText = formatResponse(result);
  } catch (e) {
    deps.log?.(`ask-scholar error: ${e instanceof Error ? e.message : e}`);
    responseText = ERROR_MESSAGE;
  }
  await deps.sendMessage(chatId, responseText);
}
