# Plan: Conversation Memory + Follow-up Ability

## Problem
Every question to Mizan is standalone. Users can't say "tell me more about that hadith" or "what about the Arabic?" — the bot has no memory of what it just answered.

## Design

### Data Structure
```python
# In-memory session store (no Redis needed — single process bot)
sessions = {}  # chat_id -> Session

class Session:
    last_active: float          # timestamp, for expiry
    last_question: str          # "any hadith on fighting the nafs?"
    last_context: str           # the gathered context JSON that was sent to Claude
    last_response: str          # Claude's full response text
    last_verses: list           # [(surah, ayah), ...] referenced
    last_hadiths: list          # [("bukhari", "50"), ...] referenced
    last_topic: str             # "nafs", "patience", etc.
    history: list               # last 3 Q&A pairs for Claude context
```

### Session Lifecycle
- **Created** on first message from a chat_id
- **Updated** after every Q&A exchange
- **Expired** after 30 min of inactivity (checked lazily on next message)
- **Cleared** on `/start` or `/clear` command

### Follow-up Detection
Add a function `is_followup(text)` that returns True if the message looks like a follow-up:

```python
FOLLOWUP_PATTERNS = [
    r"^(tell|explain|say)\s+more",
    r"^more\s+(about|on|detail)",
    r"^what about",
    r"^and (the|what about)",
    r"^(expand|elaborate|continue)",
    r"^(arabic|translation|tafsir)\s*(of|for|meaning)?",
    r"^why\s+(is|does|did)\s+(that|this|it)",
    r"^(which|what)\s+(scholar|collection|surah)",
    r"^(also|another|other|related)",
]
```

### Modified Flow

```
User message
    │
    ├── is_followup? ──Yes──> Use session.last_context + session.last_response
    │                         as additional context for Claude
    │                         Don't re-query the database
    │
    └── No ──> Normal flow: gather_context() from DB
               Save results to session
```

### Changes to `ask_claude()`

When it's a follow-up, prepend conversation history to the prompt:

```python
def ask_claude(question, context, session=None):
    history_block = ""
    if session and session.history:
        history_block = "CONVERSATION HISTORY:\n"
        for q, a in session.history[-3:]:  # Last 3 exchanges
            history_block += f"User: {q}\nMizan: {a[:500]}...\n\n"

    prompt = f"""You are Mizan...

{history_block}

The user now asks: "{question}"

{context}

RULES: ...
"""
```

### Changes to `main()` loop

```python
# Before processing:
session = get_or_create_session(chat_id)

# Detect follow-up:
if is_followup(text) and session.last_context:
    context = session.last_context  # Reuse previous context
    # Optionally enrich with new specific lookups
else:
    context = gather_context(text)

# After Claude responds:
session.last_question = text
session.last_context = context
session.last_response = answer
session.history.append((text, answer))
if len(session.history) > 5:
    session.history = session.history[-3:]
session.last_active = time.time()
```

### New Commands
- `/clear` — Reset conversation memory ("Let's start fresh")

## Implementation Checklist
1. Add `Session` class and `sessions` dict at module level
2. Add `is_followup()` detection function
3. Add `get_or_create_session(chat_id)` with lazy expiry
4. Modify `main()` loop to use sessions
5. Modify `ask_claude()` to accept session and include history
6. Add `/clear` command handler
7. Test: verse lookup -> "tell me more" -> "what about the Arabic?"

## Not in Scope (Future)
- Cross-session memory (remembering user preferences across restarts)
- User profiles (tracking what topics a user frequently asks about)
- Proactive suggestions ("Since you asked about patience, you might also want to know...")
