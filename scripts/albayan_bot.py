#!/usr/bin/env python3
"""
Al-Bayan — Public Telegram Bot (Phase 1)
Deterministic keyword-match Q&A via Supabase Edge Function.
No Claude CLI, no session memory, no external dependencies.

Usage:
  ALBAYAN_BOT_TOKEN=... python3 scripts/albayan_bot.py

Requires:
  - ALBAYAN_BOT_TOKEN env var (Telegram bot token for @AlBayanBot)
"""

import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --- Config ---
BOT_TOKEN = os.environ.get("ALBAYAN_BOT_TOKEN", "")
EDGE_FUNCTION_URL = "https://tscuymavysscrvoberrr.supabase.co/functions/v1/ask-scholar"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0."
    "qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"
)

# --- Static messages ---
WELCOME_MESSAGE = (
    "*Bismillah* -- Welcome to Al-Bayan\n\n"
    "I help you explore what the Quran and classical scholars say "
    "about topics like patience, gratitude, mercy, prayer, and sincerity.\n\n"
    "*How it works:*\n"
    "Send me a question or topic and I will find relevant ayat "
    "with tafsir from named scholars.\n\n"
    "*Transparency:*\n"
    "Every response is labelled with its source:\n"
    "  [Quoted: Quran] -- verbatim Quran text\n"
    "  [Paraphrased: Scholar] -- tafsir from a named scholar\n"
    "  [AI-Generated] -- system messages, not Islamic knowledge\n\n"
    "*Examples to try:*\n"
    "  - patience\n"
    "  - What does the Quran say about gratitude?\n"
    "  - 2:153\n\n"
    "*Important:* Al-Bayan does not issue fiqh rulings. "
    "Questions about halal/haram will be redirected to qualified scholars.\n\n"
    "_Phase 1 covers a limited set of topics. More coming soon._\n\n"
    "---\n"
    "[AI-Generated: This welcome message is not Islamic knowledge]"
)

HELP_MESSAGE = (
    "*Al-Bayan -- Usage*\n\n"
    "Send a topic keyword or question:\n"
    "  - patience\n"
    "  - gratitude\n"
    "  - What does the Quran say about mercy?\n"
    "  - 2:153\n\n"
    "*Available topics (Phase 1):*\n"
    "patience, gratitude, prayer, repentance, knowledge, "
    "charity, forgiveness, justice, family, trust\n\n"
    "*Commands:*\n"
    "/start -- Welcome message\n"
    "/help -- This message\n\n"
    "---\n"
    "[AI-Generated: This help message is not Islamic knowledge]"
)

NO_MATCH_MESSAGE = (
    "--- Al-Bayan ---\n\n"
    "I don't have specific knowledge on that topic yet.\n\n"
    "Try asking about patience, gratitude, mercy, prayer, or sincerity.\n\n"
    "You can also:\n"
    "- Use simpler keywords (e.g., \"patience\" instead of \"how to be patient\")\n"
    "- Ask about a specific verse (e.g., \"2:153\")\n\n"
    "_Phase 1 covers a limited set of topics. More coverage is coming soon._\n\n"
    "---\n"
    "[AI-Generated: This message is not Islamic knowledge]"
)

SCHOLAR_GATE_MESSAGE = (
    "--- Al-Bayan ---\n\n"
    "Your question touches on a fiqh (Islamic legal) ruling.\n\n"
    "Al-Bayan does not generate legal rulings. Fiqh requires qualified "
    "scholarship, understanding of context, and knowledge of your specific situation.\n\n"
    "Please consult:\n"
    "- A local imam or scholar you trust\n"
    "- Qualified fatwa services (e.g., IslamQA.info, Dar al-Ifta)\n"
    "- Your community's religious authority\n\n"
    "We can still help you explore what the Quran and scholars say about "
    "the _topic_ behind your question. Try rephrasing without asking for a ruling.\n\n"
    "---\n"
    "[AI-Generated: This redirect message is not Islamic knowledge]"
)

ERROR_MESSAGE = (
    "--- Al-Bayan ---\n\n"
    "Something went wrong while processing your question. "
    "Please try again in a moment.\n\n"
    "---\n"
    "[AI-Generated: This error message is not Islamic knowledge]"
)


# --- Telegram helpers ---

def tg_request(method, data=None):
    """Make a Telegram Bot API request."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(chat_id, text, parse_mode=None):
    """Send a Telegram message.

    Defaults to plain text (parse_mode=None) because format_response
    emits plain text that routinely contains characters Telegram's
    Markdown parser rejects (e.g. underscores in transliterated Arabic
    like ``al-Ṭabarī`` or ``_ibadah``, unbalanced ``*`` from punctuation).
    Callers sending static Markdown-formatted messages (WELCOME_MESSAGE,
    HELP_MESSAGE) must opt in by passing ``parse_mode="Markdown"``.
    """
    truncated = text[:4000] + "..." if len(text) > 4000 else text
    payload = {
        "chat_id": chat_id,
        "text": truncated,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        tg_request("sendMessage", payload)
    except Exception as e:
        print(f"  Failed to send message: {e}")


def send_typing(chat_id):
    """Send typing indicator."""
    try:
        tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


# --- Edge Function client ---

def call_ask_scholar(query, chat_id):
    """POST to the ask-scholar Supabase Edge Function.
    Sends telegram_id so the Edge Function can hash it for mizan_interactions
    audit identity (per CAI-MIZAN-EVAL-001 telegram_id_hash constraint).
    chat_id kept for backward compat with older Edge Function versions."""
    payload = json.dumps({
        "query": query,
        "telegram_id": str(chat_id),
        "chat_id": str(chat_id),
        "bot_variant": "al-bayan",
    }).encode("utf-8")
    req = urllib.request.Request(
        EDGE_FUNCTION_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --- Response formatting helpers ---

_SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+')


def _trim_sentences(text: str, max_sentences: int = 3) -> str:
    """Return the first max_sentences sentences from text."""
    parts = _SENTENCE_BOUNDARY.split(text.strip())
    trimmed = ' '.join(parts[:max_sentences])
    # If we cut, end cleanly with ellipsis only if the last char isn't punctuation
    if len(parts) > max_sentences and trimmed and trimmed[-1] not in '.!?':
        trimmed += '…'
    return trimmed


def _select_tafsir(tafsir_list: list, max_entries: int = 2) -> list:
    """Return at most max_entries tafsir dicts, preferring FTS-matched ones.
    Filters out Arabic-only placeholders."""
    valid = [
        t for t in (tafsir_list or [])
        if t.get('text') and not t['text'].startswith('[Arabic tafsir')
    ]
    # FTS-matched entries first (these are the relevance-ranked excerpts)
    ordered = sorted(valid, key=lambda t: 0 if t.get('matched_passage') else 1)
    return ordered[:max_entries]


def _select_best_match(matches: list) -> tuple:
    """Return (primary_match, secondary_refs) where primary has richest tafsir."""
    if not matches:
        return None, []
    # Prefer matches that have at least one FTS-matched tafsir entry
    for m in matches:
        if any(t.get('matched_passage') for t in (m.get('tafsir') or [])):
            rest = [x for x in matches if x is not m]
            return m, rest[:1]
    return matches[0], matches[1:2]


# --- Response formatting ---

def format_response(data):
    """Format the ask-scholar Edge Function JSON into a concise Telegram message.

    Selects the single best-matched ayah + up to 2 tafsir excerpts (trimmed to
    3 sentences each). Secondary ayat references are shown as a compact footnote.
    Tier markers are always preserved per T-1/T-2 invariants.

    Edge Function response shape:
      { question, scholar_gate: bool, matches: [MatchEntry], hadith_matches: [...],
        practice_offramp: str, tiers_used: [str], message?: str }
    MatchEntry:
      { surah, ayah, surah_name, arabic, translation, translator,
        tafsir: [{ scholar, source, text, tier,
                   matched_passage, matched_passage_tier }] }
    """
    if data.get("error"):
        return ERROR_MESSAGE

    if data.get("scholar_gate"):
        return SCHOLAR_GATE_MESSAGE

    matches = data.get("matches") or []
    hadith_matches = data.get("hadith_matches") or []

    if not matches and not hadith_matches:
        return NO_MATCH_MESSAGE

    parts = ["--- Al-Bayan ---\n"]
    sources = []

    primary, secondary = _select_best_match(matches)

    # Primary ayah
    if primary:
        surah_num = primary.get("surah", "")
        ayah_num = primary.get("ayah", "")
        surah_name = primary.get("surah_name", "")
        arabic = primary.get("arabic", "")
        translation = primary.get("translation", "")
        translator = primary.get("translator", "")

        if arabic:
            parts.append(arabic)
            parts.append("")

        if translation:
            ref = f"{surah_name} ({surah_num}:{ayah_num})" if surah_name else f"{surah_num}:{ayah_num}"
            parts.append(f'"{translation}"')
            parts.append(f"— {translator + ', ' if translator else ''}{ref}")
            parts.append(f"[Quoted: Quran {surah_num}:{ayah_num}]")
            parts.append("")
            sources.append(f"Quran {surah_num}:{ayah_num}")

        # Tafsir: up to 2 entries, trimmed to 3 sentences
        for t in _select_tafsir(primary.get("tafsir") or []):
            scholar = t.get("scholar", "Unknown")
            source = t.get("source", "")
            raw = t.get("matched_passage") or t.get("text", "")
            if not raw:
                continue
            excerpt = _trim_sentences(raw, 3)
            tier = (t.get("matched_passage_tier") or t.get("tier") or "paraphrased").capitalize()
            parts.append(f"{scholar}:")
            parts.append(f'"{excerpt}"')
            parts.append(f"[{tier}: {scholar}, {source}]")
            parts.append("")
            if source and source not in sources:
                sources.append(source)

    # Secondary ayat: compact inline refs only (no full tafsir dump)
    if secondary:
        sec = secondary[0]
        s_num = sec.get("surah", "")
        a_num = sec.get("ayah", "")
        s_name = sec.get("surah_name", "")
        trans = sec.get("translation", "")
        if trans and s_num and a_num:
            ref = f"{s_name} ({s_num}:{a_num})" if s_name else f"{s_num}:{a_num}"
            parts.append(f'Also: "{_trim_sentences(trans, 1)}" — {ref}')
            parts.append(f"[Quoted: Quran {s_num}:{a_num}]")
            parts.append("")
            sources.append(f"Quran {s_num}:{a_num}")

    # Hadith: best 1 entry, trimmed to 2 sentences
    if hadith_matches:
        h = hadith_matches[0]
        coll = h.get("collection", "unknown")
        num = h.get("hadith_number", "")
        grading = h.get("grading") or ""
        english = h.get("english", "")
        if english:
            excerpt = _trim_sentences(english, 2)
            header = coll
            if num:
                header += f" #{num}"
            if grading:
                header += f" · {grading}"
            parts.append(f"{header}:")
            parts.append(f'"{excerpt}"')
            parts.append(f"[Quoted: Hadith, {coll} #{num}]")
            parts.append("")
            if coll not in sources:
                sources.append(coll)

    practice = data.get("practice_offramp")
    if practice:
        parts.append(practice)
        parts.append("")

    parts.append("---")
    if sources:
        parts.append(f"Sources: {', '.join(sources)}")
    parts.append("Tier markers [] indicate content origin.")
    return "\n".join(parts)


# --- Main loop ---

def main():
    if not BOT_TOKEN:
        print("ERROR: ALBAYAN_BOT_TOKEN environment variable is not set.")
        sys.exit(1)

    print("=" * 50)
    print("Al-Bayan -- Public Telegram Bot (Phase 1)")
    print("Deterministic Q&A via Supabase Edge Function")
    print("=" * 50)

    # Delete webhook so we can use long polling
    print("Removing webhook for long polling...")
    tg_request("deleteWebhook")

    print("Bot is running. Press Ctrl+C to stop.\n")

    offset = 0

    def handle_shutdown(sig, frame):
        print("\nShutting down gracefully.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    if sys.stdin.isatty():
        signal.signal(signal.SIGTERM, handle_shutdown)

    while True:
        try:
            updates = tg_request("getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message"],
            })

            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")
                user = msg.get("from", {}).get("first_name", "?")

                if not text or not chat_id:
                    continue

                print(f"[{user}] {text}")

                # Handle commands
                if text.lower() in ("/start", "/start@albayan_bot"):
                    send_message(chat_id, WELCOME_MESSAGE, parse_mode="Markdown")
                    continue

                if text.lower() in ("/help", "/help@albayan_bot"):
                    send_message(chat_id, HELP_MESSAGE, parse_mode="Markdown")
                    continue

                # Send typing indicator
                send_typing(chat_id)

                # Call the Edge Function
                try:
                    result = call_ask_scholar(text, chat_id)
                    response_text = format_response(result)
                except urllib.error.HTTPError as e:
                    print(f"  Edge Function HTTP error: {e.code} {e.reason}")
                    try:
                        body = e.read().decode("utf-8", errors="replace")
                        print(f"  Response body: {body[:500]}")
                    except Exception:
                        pass
                    response_text = ERROR_MESSAGE
                except urllib.error.URLError as e:
                    print(f"  Edge Function connection error: {e.reason}")
                    response_text = ERROR_MESSAGE
                except Exception as e:
                    print(f"  Edge Function error: {e}")
                    response_text = ERROR_MESSAGE

                send_message(chat_id, response_text)

        except urllib.error.URLError as e:
            print(f"Telegram polling error: {e.reason}")
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
