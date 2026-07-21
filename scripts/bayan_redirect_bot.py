#!/usr/bin/env python3
"""Redirect responder for the OLD Bayan bot (@mzninterfacebot -> @bayanQAbot).

After the Al-Mizan -> Bayan cutover the live poller consumes @bayanQAbot, so
anyone still messaging the OLD @mzninterfacebot hits a dead bot. This tiny
long-poll responder replies to every message on the OLD bot with a redirect to
the new one (inline button + text). No LLM, no retrieval — pure signpost.

Env:
  OLD_BOT_TOKEN       (required)  token for the OLD bot being redirected FROM
  NEW_BOT_USERNAME    (default 'bayanQAbot')  username to redirect TO (no @)
  REDIRECT_ONCE       (optional)  if '1', drain the current backlog and exit
                                  (used for the verification run); else loop.
"""
import os, sys, json, time, urllib.request, urllib.parse

OLD_TOKEN = os.environ.get("OLD_BOT_TOKEN", "").strip()
NEW_USER = os.environ.get("NEW_BOT_USERNAME", "bayanQAbot").strip().lstrip("@")
ONCE = os.environ.get("REDIRECT_ONCE") == "1"
API = f"https://api.telegram.org/bot{OLD_TOKEN}"

REDIRECT_TEXT = (
    "As-salamu alaykum. This assistant has moved.\n\n"
    f"Please send your question to @{NEW_USER} — that is the active Bayan bot now. "
    "This old bot is no longer monitored."
)
KEYBOARD = {"inline_keyboard": [[{"text": f"Open @{NEW_USER}", "url": f"https://t.me/{NEW_USER}"}]]}


def _api(method, params, timeout=65):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{API}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def send_redirect(chat_id):
    try:
        _api("sendMessage", {
            "chat_id": chat_id,
            "text": REDIRECT_TEXT,
            "reply_markup": json.dumps(KEYBOARD),
            "disable_web_page_preview": "true",
        }, timeout=20)
        return True
    except Exception as e:
        print(f"[redirect] send failed chat={chat_id}: {e}", flush=True)
        return False


def main():
    if not OLD_TOKEN:
        print("OLD_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(2)
    print(f"[redirect] live: @mzninterfacebot -> @{NEW_USER} (once={ONCE})", flush=True)
    offset = None
    idle_polls = 0
    while True:
        params = {"timeout": 50}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = _api("getUpdates", params)
        except Exception as e:
            print(f"[redirect] getUpdates error: {e}", flush=True)
            time.sleep(3)
            continue
        updates = resp.get("result", [])
        if not updates:
            idle_polls += 1
            if ONCE:
                print("[redirect] backlog drained, exiting (ONCE).", flush=True)
                return
            continue
        seen_chats = set()
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message") or {}
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            if chat_id is None or chat_id in seen_chats:
                continue
            seen_chats.add(chat_id)  # one redirect per chat per batch
            if send_redirect(chat_id):
                print(f"[redirect] redirected chat={chat_id} (@{chat.get('username','?')})", flush=True)


if __name__ == "__main__":
    main()
