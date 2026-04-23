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


# --- Response formatting ---

def format_response(data):
    """Format the ask-scholar Edge Function JSON into a Telegram message.

    Edge Function response shape:
      { question, scholar_gate: bool, matches: [MatchEntry], hadith_matches: [...],
        practice_offramp: str, tiers_used: [str], message?: str, suggested_resources?: [str] }
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

    for m in matches:
        surah_num = m.get("surah", "")
        ayah_num = m.get("ayah", "")
        surah_name = m.get("surah_name", "")
        arabic = m.get("arabic", "")
        translation = m.get("translation", "")
        translator = m.get("translator", "")

        if arabic:
            parts.append(arabic)
            parts.append("")

        if translation:
            parts.append(f'"{translation}"')
            ref_bits = []
            if translator:
                ref_bits.append(translator)
            ref_bits.append(f"{surah_name} ({surah_num}:{ayah_num})" if surah_name else f"{surah_num}:{ayah_num}")
            parts.append(f"-- {', '.join(ref_bits)}")
            parts.append(f"[Quoted: Quran {surah_num}:{ayah_num}]")
            parts.append("")

        if surah_num and ayah_num:
            sources.append(f"Quran {surah_num}:{ayah_num}")

        tafsir_list = m.get("tafsir") or []
        if tafsir_list:
            parts.append("--- Tafsir ---\n")
            for t in tafsir_list:
                scholar = t.get("scholar", "Unknown")
                source = t.get("source", "")
                matched = t.get("matched_passage")
                if matched:
                    tier = (t.get("matched_passage_tier") or "paraphrased").capitalize()
                    parts.append(f"{scholar} ({source}) — matched passage:")
                    parts.append(f'"{matched}"')
                    parts.append(f"[{tier}: {scholar}, {source}]")
                    parts.append("")
                else:
                    text = t.get("text", "")
                    if not text or text.startswith("[Arabic tafsir"):
                        continue
                    tier = (t.get("tier") or "paraphrased").capitalize()
                    parts.append(f"{scholar} ({source}):")
                    parts.append(f'"{text}"')
                    parts.append(f"[{tier}: {scholar}]")
                    parts.append("")

                if source and source not in sources:
                    sources.append(source)

    if hadith_matches:
        parts.append("--- Hadith ---\n")
        for h in hadith_matches:
            coll = h.get("collection", "unknown")
            num = h.get("hadith_number", "")
            grading = h.get("grading") or ""
            narrator = h.get("narrator") or ""
            english = h.get("english", "")
            header_bits = [coll]
            if num:
                header_bits.append(f"#{num}")
            if grading:
                header_bits.append(grading)
            if narrator:
                header_bits.append(narrator)
            parts.append(f"{' · '.join(header_bits)}:")
            parts.append(f'"{english}"')
            parts.append(f"[Quoted: Hadith, {coll} #{num}]")
            parts.append("")

    practice = data.get("practice_offramp")
    if practice:
        parts.append("--- Practice ---\n")
        parts.append(practice)
        parts.append("")

    parts.append("---")
    if sources:
        parts.append(f"Sources: {', '.join(sources)}")
    parts.append(
        "Transparency: All content above is sourced. "
        "Tier markers [] indicate origin."
    )
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
