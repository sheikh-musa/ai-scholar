#!/usr/bin/env python3
"""Verify the per-chat durable state fix for the level-button dead-end
(operator msg #2476 / cc-orchestrator): a level button tapped after a process
restart or SESSION_TTL prune must still re-answer the prior question.

Run: python3 scripts/test_chat_state_persistence.py
Standalone (no pytest needed). Isolates HOME so it never touches real prefs.
"""
import os
import sys
import tempfile

# Isolate on-disk state before importing the bot module.
_tmp_home = tempfile.mkdtemp(prefix="mizan_test_home_")
os.environ["HOME"] = _tmp_home

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import mizan_bot as mb  # noqa: E402

# Re-point the state path at the isolated HOME (it was computed at import time
# from whatever HOME was, so recompute explicitly to be safe).
mb.CHAT_STATE_PATH = os.path.join(_tmp_home, ".mizan_chat_state.json")

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + f"  {name}")
    if not cond:
        failures.append(name)


CHAT = 123456789

# 1. Round-trip: save then load returns what we stored.
mb.save_chat_state(CHAT, "what is khushu in salah?", "scholar")
st = mb.load_chat_state(CHAT)
check("round-trip last_query", st and st["last_query"] == "what is khushu in salah?")
check("round-trip answer_level", st and st["answer_level"] == "scholar")

# 2. State is keyed by hash, not raw chat_id (no raw IDs at rest).
with open(mb.CHAT_STATE_PATH, encoding="utf-8") as f:
    raw = f.read()
check("raw chat_id not stored on disk", str(CHAT) not in raw)

# 3. Simulate a process restart: wipe the in-memory sessions dict, then
#    get_session must hydrate last_query + answer_level from disk.
mb.sessions.clear()
sess = mb.get_session(CHAT)
check("hydrated last_query after restart", sess["last_query"] == "what is khushu in salah?")
check("hydrated answer_level after restart", sess["answer_level"] == "scholar")
check("last_context NOT hydrated (followup guard stays safe)", sess["last_context"] == "")
check("level_responses empty after restart", sess["level_responses"] == {})

# 4. The dead-end precondition is gone: last_q is now truthy after restart,
#    so the callback re-answer branch (not the "Ask me your next question"
#    fallback) is the one that fires.
last_q = sess.get("last_query", "")
check("dead-end fallback would NOT fire (last_q truthy)", bool(last_q))

# 5. Unknown chat → None (and get_session yields clean defaults, no crash).
check("unknown chat loads None", mb.load_chat_state(999) is None)
mb.sessions.clear()
fresh = mb.get_session(999)
check("unknown chat -> default empty session", fresh["last_query"] == "" and fresh["answer_level"] == "seeker")

# 6. Level-stickiness update keeps last_query, changes level.
mb.save_chat_state(CHAT, "what is khushu in salah?", "layman")
st2 = mb.load_chat_state(CHAT)
check("level update preserves last_query", st2["last_query"] == "what is khushu in salah?")
check("level update changes level", st2["answer_level"] == "layman")

# 7. Corrupt file fails-soft (returns {} / None, no exception).
with open(mb.CHAT_STATE_PATH, "w", encoding="utf-8") as f:
    f.write("{not valid json")
check("corrupt file fails soft", mb.load_chat_state(CHAT) is None)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL PASS")
