import { assertEquals, assertStringIncludes } from "https://deno.land/std@0.208.0/assert/mod.ts";
import {
  AskScholarResponse,
  ERROR_MESSAGE,
  formatResponse,
  handleUpdate,
  HELP_MESSAGE,
  NO_MATCH_MESSAGE,
  SCHOLAR_GATE_MESSAGE,
  TelegramUpdate,
  trimSentences,
  WELCOME_MESSAGE,
} from "../handler.ts";

// --- formatResponse: routing floors ----------------------------------------

Deno.test("formatResponse: error -> ERROR_MESSAGE (ai-generated floor)", () => {
  assertEquals(formatResponse({ error: "boom" }), ERROR_MESSAGE);
});

Deno.test("formatResponse: scholar_gate -> refusal (F-3 passthrough)", () => {
  assertEquals(formatResponse({ scholar_gate: true }), SCHOLAR_GATE_MESSAGE);
});

Deno.test("formatResponse: no matches -> NO_MATCH_MESSAGE", () => {
  assertEquals(formatResponse({ matches: [], hadith_matches: [] }), NO_MATCH_MESSAGE);
});

// --- formatResponse: tier markers preserved (T-1/T-2) -----------------------

Deno.test("formatResponse: ayah + FTS tafsir keeps every tier marker", () => {
  const data: AskScholarResponse = {
    scholar_gate: false,
    matches: [
      {
        surah: 2,
        ayah: 153,
        surah_name: "Al-Baqarah",
        arabic: "يَا أَيُّهَا الَّذِينَ آمَنُوا",
        translation: "O you who believe, seek help through patience and prayer.",
        translator: "Sahih International",
        tafsir: [
          {
            scholar: "Ibn Kathir",
            source: "Tafsir al-Qur'an al-'Azim",
            text: "full text here.",
            tier: "paraphrased",
            matched_passage: "Patience is of two kinds. It anchors the believer.",
            matched_passage_tier: "quoted",
          },
        ],
      },
    ],
  };
  const out = formatResponse(data);
  assertStringIncludes(out, "[Quoted: Quran 2:153]");
  // matched_passage_tier wins over tier (Quoted, capitalized) with attribution
  assertStringIncludes(out, "[Quoted: Ibn Kathir, Tafsir al-Qur'an al-'Azim]");
  // prefers the FTS-matched excerpt, trimmed
  assertStringIncludes(out, "Patience is of two kinds.");
  assertStringIncludes(out, "Sources: Quran 2:153");
  assertStringIncludes(out, "Tier markers [] indicate content origin.");
});

Deno.test("formatResponse: hadith match carries a Quoted isnad marker", () => {
  const out = formatResponse({
    matches: [],
    hadith_matches: [
      { collection: "Riyad al-Salihin", hadith_number: 25, grading: "sahih", english: "Actions are by intentions. So each person gets what they intended." },
    ],
  });
  assertStringIncludes(out, "Riyad al-Salihin #25 · sahih");
  assertStringIncludes(out, "[Quoted: Hadith, Riyad al-Salihin #25]");
});

Deno.test("trimSentences caps sentence count (parity: no ellipsis when it ends in .!?)", () => {
  // Faithful port of albayan_bot.py:_trim_sentences — the '…' is only appended
  // when the truncated text does NOT already end in sentence punctuation. Since
  // the boundary split keeps the '.' on each piece, capped output ends in '.'
  // and no ellipsis is added. Preserving this quirk keeps message-shape parity.
  assertEquals(trimSentences("One. Two. Three. Four.", 2), "One. Two.");
});

// --- handleUpdate: routing + parity (with injected fakes) -------------------

function recorder() {
  const sent: { chatId: number | string; text: string; parseMode?: string }[] = [];
  const asked: { query: string; chatId: number | string }[] = [];
  return { sent, asked };
}

Deno.test("handleUpdate: /start -> welcome (Markdown), no ask-scholar call", async () => {
  const r = recorder();
  const update: TelegramUpdate = { message: { text: "/start", chat: { id: 99 } } };
  await handleUpdate(update, {
    callAskScholar: async (query, chatId) => { r.asked.push({ query, chatId }); return {}; },
    sendMessage: async (chatId, text, parseMode) => { r.sent.push({ chatId, text, parseMode }); },
  });
  assertEquals(r.asked.length, 0);
  assertEquals(r.sent.length, 1);
  assertEquals(r.sent[0].text, WELCOME_MESSAGE);
  assertEquals(r.sent[0].parseMode, "Markdown");
});

Deno.test("handleUpdate: /help -> help (Markdown)", async () => {
  const r = recorder();
  await handleUpdate({ message: { text: "/help", chat: { id: 5 } } }, {
    callAskScholar: async () => ({}),
    sendMessage: async (chatId, text, parseMode) => { r.sent.push({ chatId, text, parseMode }); },
  });
  assertEquals(r.sent[0].text, HELP_MESSAGE);
  assertEquals(r.sent[0].parseMode, "Markdown");
});

Deno.test("handleUpdate: normal query -> ask-scholar(al-bayan path) then formatted reply", async () => {
  const r = recorder();
  const fake: AskScholarResponse = {
    scholar_gate: false,
    matches: [{ surah: 103, ayah: 3, surah_name: "Al-Asr", translation: "...except those who believe.", translator: "SI", tafsir: [] }],
  };
  await handleUpdate({ message: { text: "patience", chat: { id: 7 }, from: { first_name: "Aisha" } } }, {
    callAskScholar: async (query, chatId) => { r.asked.push({ query, chatId }); return fake; },
    sendMessage: async (chatId, text) => { r.sent.push({ chatId, text }); },
    sendTyping: async () => {},
  });
  assertEquals(r.asked.length, 1);
  assertEquals(r.asked[0].query, "patience");
  assertEquals(r.asked[0].chatId, 7);
  assertStringIncludes(r.sent[0].text, "[Quoted: Quran 103:3]");
});

Deno.test("handleUpdate: ask-scholar throws -> ERROR_MESSAGE (never throws to caller)", async () => {
  const r = recorder();
  await handleUpdate({ message: { text: "x", chat: { id: 1 } } }, {
    callAskScholar: async () => { throw new Error("network"); },
    sendMessage: async (chatId, text) => { r.sent.push({ chatId, text }); },
  });
  assertEquals(r.sent[0].text, ERROR_MESSAGE);
});

Deno.test("handleUpdate: non-text / no chat -> ignored", async () => {
  const r = recorder();
  const send = async (chatId: number | string, text: string) => { r.sent.push({ chatId, text }); };
  await handleUpdate({}, { callAskScholar: async () => ({}), sendMessage: send });
  await handleUpdate({ message: { text: "", chat: { id: 2 } } }, { callAskScholar: async () => ({}), sendMessage: send });
  await handleUpdate({ message: { text: "hi" } }, { callAskScholar: async () => ({}), sendMessage: send });
  assertEquals(r.sent.length, 0);
});
