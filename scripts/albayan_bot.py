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


def send_message(chat_id, text):
    """Send a Telegram message, falling back to plain text if Markdown fails."""
    truncated = text[:4000] + "..." if len(text) > 4000 else text
    try:
        tg_request("sendMessage", {
            "chat_id": chat_id,
            "text": truncated,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
    except Exception:
        try:
            tg_request("sendMessage", {
                "chat_id": chat_id,
                "text": truncated,
                "disable_web_page_preview": True,
            })
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
    """POST to the ask-scholar Supabase Edge Function."""
    payload = json.dumps({
        "query": query,
        "chat_id": str(chat_id),
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
    """Format the Edge Function JSON response into a Telegram message."""
    status = data.get("status", "error")

    if status == "scholar_gate":
        return SCHOLAR_GATE_MESSAGE

    if status == "no_match":
        return NO_MATCH_MESSAGE

    if status == "error":
        return ERROR_MESSAGE

    # status == "ok" -- format the full response
    resp = data.get("response", {})
    if not resp:
        return ERROR_MESSAGE

    parts = ["--- Al-Bayan ---\n"]

    # Arabic text
    arabic = resp.get("arabic", "")
    if arabic:
        parts.append(arabic)
        parts.append("")

    # Translation
    translation = resp.get("translation", "")
    translator = resp.get("translator", "")
    surah_name = resp.get("surah_name", "")
    surah_num = resp.get("surah_number", "")
    ayah_num = resp.get("ayah_number", "")

    if translation:
        parts.append(f'"{translation}"')
        ref_parts = []
        if translator:
            ref_parts.append(translator)
        if surah_name:
            ref_parts.append(f"{surah_name} ({surah_num}:{ayah_num})")
        elif surah_num:
            ref_parts.append(f"{surah_num}:{ayah_num}")
        if ref_parts:
            parts.append(f"-- {', '.join(ref_parts)}")
        parts.append(f"[Quoted: Quran {surah_num}:{ayah_num}]")
        parts.append("")

    # Tafsir
    tafsir_list = resp.get("tafsir", [])
    if tafsir_list:
        parts.append("--- Tafsir ---\n")
        for t in tafsir_list:
            scholar = t.get("scholar_name", "Unknown")
            source = t.get("source_work", "")
            text = t.get("english_text", "")
            tier = t.get("output_tier", "paraphrased")

            if not text or text.startswith("[Arabic tafsir"):
                continue

            header = scholar
            if source:
                header += f" ({source})"
            parts.append(f"{header}:")
            parts.append(f'"{text}"')

            if tier == "quoted":
                parts.append(f"[Quoted: {scholar}]")
            else:
                parts.append(f"[Paraphrased: {scholar}]")
            parts.append("")

    # Practice off-ramp
    practice = resp.get("practice", "")
    if practice:
        parts.append("--- Practice ---\n")
        parts.append(practice)
        parts.append("")

    # Sources and transparency footer
    sources = []
    if surah_num and ayah_num:
        sources.append(f"Quran {surah_num}:{ayah_num}")
    for t in tafsir_list:
        sw = t.get("source_work", "")
        if sw and sw not in sources:
            sources.append(sw)

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
                    send_message(chat_id, WELCOME_MESSAGE)
                    continue

                if text.lower() in ("/help", "/help@albayan_bot"):
                    send_message(chat_id, HELP_MESSAGE)
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
