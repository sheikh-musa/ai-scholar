#!/usr/bin/env python3
"""
Mizan (Al-Bayan) — Local Telegram Bot
Uses Claude Code CLI (Max plan) as the reasoning engine.
Queries Supabase for Quran + tafsir data.

Usage:
  python3 scripts/mizan_bot.py

Requires:
  - claude CLI installed and authenticated (~/.local/bin/claude)
  - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars (or hardcoded below)
"""

import json
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error
import sys
import os
import signal

# --- Config ---
BOT_TOKEN = "8385088525:AAEUulSwRW226oFGjZqGdVpoJuwaDah-7_g"
SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"
CLAUDE_PATH = os.path.expanduser("~/.local/bin/claude")

SURAH_NAMES = {
    1:"Al-Fatihah",2:"Al-Baqarah",3:"Aal-Imran",4:"An-Nisa",5:"Al-Ma'idah",
    6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",
    11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",
    16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",
    21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",
    26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",
    31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",
    36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",
    41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiyah",
    46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",
    51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",
    56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahanah",
    61:"As-Saf",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",
    66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",
    71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddaththir",75:"Al-Qiyamah",
    76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",
    81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",
    86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",
    91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",
    96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",
    101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",
    106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",
    111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas",
}

FIQH_KEYWORDS = {"halal", "haram", "permissible", "ruling", "allowed", "forbidden",
                  "fard", "wajib", "makruh", "mustahab", "fatwa"}

STOP_WORDS = {"what", "does", "the", "quran", "say", "about", "islam", "islamic",
              "how", "why", "tell", "me", "is", "are", "in", "of", "a", "an",
              "and", "to", "for", "it", "this", "that", "can", "do", "please",
              "explain", "inner", "dimensions", "meaning", "deep", "deeper",
              "hadith", "sunnah", "prophet", "pbuh", "any", "some"}

# --- Session memory ---
SESSION_TTL = 1800  # 30 minutes
MAX_HISTORY = 6     # 3 Q&A pairs
sessions = {}       # chat_id -> session dict


def get_session(chat_id):
    """Get or create a session. Lazily prune expired ones."""
    now = time.time()
    expired = [cid for cid, s in sessions.items() if now - s["last_active"] > SESSION_TTL]
    for cid in expired:
        del sessions[cid]

    if chat_id not in sessions:
        sessions[chat_id] = {
            "history": [],
            "last_query": "",
            "last_context": "",
            "last_topics": [],
            "last_active": now,
        }
    sessions[chat_id]["last_active"] = now
    return sessions[chat_id]


def add_to_history(session, role, text):
    """Append a turn and trim to MAX_HISTORY."""
    session["history"].append({"role": role, "text": text[:1500]})
    if len(session["history"]) > MAX_HISTORY:
        session["history"] = session["history"][-MAX_HISTORY:]


FOLLOWUP_PATTERNS = [
    r"^(tell me )?more( about)?",
    r"^explain (that|this|it)( further| more| in detail)?",
    r"^(what|how) about (the |that |its )?(arabic|meaning|tafsir|hadith|verse|context)",
    r"^(and|also|what about) (the )?hadith",
    r"^(and|also|what about) (the )?(verse|ayah|quran)",
    r"^(can you )?(elaborate|expand|go deeper|continue)",
    r"^(what|which) (scholars?|tafsir) (say|said)",
    r"^in arabic",
    r"^(the )?arabic (text|meaning|version)",
    r"^(why|how) (is|does|did) (that|this|it)",
]


def is_followup(text, session):
    """Detect if the message is a follow-up to a previous question."""
    import re
    if not session.get("last_query"):
        return False
    t = text.lower().strip()
    for pattern in FOLLOWUP_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            return True
    # Short messages with pronouns
    if len(t.split()) <= 6:
        pronouns = {"that", "this", "it", "those", "these", "the same"}
        if any(p in t.split() for p in pronouns):
            return True
    return False


# --- Supabase helpers ---
def supabase_get(path, params=None):
    """GET from Supabase REST API."""
    url = SUPABASE_URL + "/rest/v1/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params, safe=":,.()")
    key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    req = urllib.request.Request(url, headers={
        "apikey": key,
        "Authorization": "Bearer " + key,
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_rpc(fn_name, params):
    """Call a Supabase RPC function (POST to /rest/v1/rpc/{fn})."""
    url = SUPABASE_URL + "/rest/v1/rpc/" + fn_name
    key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    payload = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))



def lookup_verse(surah, ayah):
    """Look up a specific verse with tafsir."""
    rows = supabase_get("ayat", {
        "surah_number": f"eq.{surah}",
        "ayah_number": f"eq.{ayah}",
        "select": "id,surah_number,ayah_number,arabic_text,english_translation,translator",
        "limit": "1",
    })
    if not rows:
        return {"error": f"Verse {surah}:{ayah} not found"}

    a = rows[0]
    tafsir = supabase_get("tafsir_entries", {
        "ayah_id": f"eq.{a['id']}",
        "select": "scholar_name,source_work,english_text,output_tier",
        "order": "scholar_name",
    })
    english_tafsir = [t for t in tafsir if not t["english_text"].startswith("[Arabic tafsir")]

    return {
        "surah": a["surah_number"],
        "ayah": a["ayah_number"],
        "surah_name": SURAH_NAMES.get(a["surah_number"], f"Surah {a['surah_number']}"),
        "arabic": a["arabic_text"],
        "translation": a["english_translation"],
        "translator": a["translator"],
        "tafsir": english_tafsir,
    }


def search_quran(keywords, limit=5):
    """Search Quran translations via full-text search."""
    try:
        rows = supabase_rpc("search_ayat_fts", {"query": keywords, "lim": min(limit, 10)})
        for r in rows:
            r["surah_name"] = SURAH_NAMES.get(r["surah_number"], "")
            r.pop("rank", None)
            r.pop("id", None)
        return {"results": rows}
    except Exception:
        # Fallback to ILIKE if FTS fails
        rows = supabase_get("ayat", {
            "english_translation": f"ilike.%{keywords}%",
            "select": "surah_number,ayah_number,arabic_text,english_translation",
            "limit": str(min(limit, 10)),
        })
        for r in rows:
            r["surah_name"] = SURAH_NAMES.get(r["surah_number"], "")
        return {"results": rows}


def count_mentions(word):
    """Count verses mentioning a word."""
    rows = supabase_get("ayat", {
        "english_translation": f"ilike.%{word}%",
        "select": "surah_number,ayah_number",
    })
    surahs = set(r["surah_number"] for r in rows)
    return {
        "word": word,
        "verse_count": len(rows),
        "across_surahs": len(surahs),
        "sample_verses": [f"{r['surah_number']}:{r['ayah_number']}" for r in rows[:8]],
    }


def get_surah_info(surah):
    """Get surah info + first verses."""
    rows = supabase_get("ayat", {
        "surah_number": f"eq.{surah}",
        "select": "ayah_number,arabic_text,english_translation",
        "order": "ayah_number",
        "limit": "3",
    })
    # Get total count
    all_rows = supabase_get("ayat", {
        "surah_number": f"eq.{surah}",
        "select": "ayah_number",
    })
    return {
        "surah": surah,
        "surah_name": SURAH_NAMES.get(surah, f"Surah {surah}"),
        "total_ayat": len(all_rows),
        "first_verses": rows,
    }


def search_by_topic(topic, limit=3):
    """Find verses by topic."""
    topics = supabase_get("topics", {
        "name": f"ilike.{topic}",
        "select": "id,name",
        "limit": "1",
    })
    if not topics:
        return {"error": f"Topic '{topic}' not found"}

    tid = topics[0]["id"]
    links = supabase_get("ayat_topics", {
        "topic_id": f"eq.{tid}",
        "select": "ayah_id",
        "limit": str(limit * 3),
    })
    if not links:
        return {"topic": topics[0]["name"], "results": []}

    ayah_ids = list(set(l["ayah_id"] for l in links))[:limit]
    id_filter = ",".join(ayah_ids)
    rows = supabase_get("ayat", {
        "id": f"in.({id_filter})",
        "select": "surah_number,ayah_number,arabic_text,english_translation",
    })
    for r in rows:
        r["surah_name"] = SURAH_NAMES.get(r["surah_number"], "")
    return {"topic": topics[0]["name"], "results": rows}


# Concept-level phrases: when multiple keywords appear together, search these phrases instead
CONCEPT_MAP = {
    frozenset(["fighting", "nafs"]): ["desires", "lower self", "temptation", "restrain", "self-control", "soul commands"],
    frozenset(["fighting", "soul"]): ["desires", "lower self", "temptation", "restrain", "self-control"],
    frozenset(["purify", "heart"]): ["purification", "sincerity", "clean heart", "sound heart"],
    frozenset(["purify", "soul"]): ["purification", "sincerity", "purify", "self"],
    frozenset(["good", "character"]): ["good character", "best character", "good manners", "conduct"],
    frozenset(["love", "allah"]): ["love of Allah", "loves Allah", "beloved to Allah"],
    frozenset(["fear", "allah"]): ["fear of Allah", "fears Allah", "taqwa", "God-fearing"],
    frozenset(["day", "judgment"]): ["day of resurrection", "day of judgement", "last day", "hereafter"],
    frozenset(["seeking", "knowledge"]): ["seeking knowledge", "path of knowledge", "learn", "scholar"],
}

SYNONYM_MAP = {
    "nafs": ["desires", "lower self", "soul commands", "temptation", "self-control"],
    "jihad": ["striving", "struggle", "strive"],
    "tawbah": ["repentance", "repent", "forgive", "turn back"],
    "taqwa": ["piety", "fear of Allah", "God-fearing", "righteous"],
    "sabr": ["patience", "patient", "steadfast", "perseverance"],
    "shukr": ["gratitude", "grateful", "thankful", "thanks"],
    "tawakkul": ["trust in Allah", "reliance", "rely on Allah"],
    "dhikr": ["remembrance", "remember Allah", "glorify"],
    "ihsan": ["excellence", "worship", "as if you see Him", "good conduct"],
    "riya": ["showing off", "ostentation", "seen by others"],
    "hasad": ["envy", "jealousy", "envious"],
    "kibr": ["arrogance", "pride", "proud", "superior"],
    "husn": ["good character", "good conduct", "manners"],
    "niyyah": ["intention", "intentions", "deeds are by intention"],
    "zuhd": ["asceticism", "worldly", "renounce"],
    "akhirah": ["hereafter", "afterlife", "next life", "day of judgment"],
    "dua": ["supplication", "pray", "invoke", "call upon"],
    "ilm": ["knowledge", "learn", "seeking knowledge"],
}


def expand_keywords(keyword):
    """Expand a keyword with synonyms for better search."""
    k = keyword.lower().strip()
    synonyms = SYNONYM_MAP.get(k, [])
    return [k] + synonyms


def search_hadith_fts(keywords, limit=5):
    """Search hadiths with FTS + synonym expansion (single DB query)."""
    word_list = keywords if isinstance(keywords, list) else [keywords]

    # Check concept map first — multi-word concepts get better search terms
    word_set = frozenset(w.lower() for w in word_list)
    expanded = []
    for concept_keys, concept_terms in CONCEPT_MAP.items():
        if concept_keys.issubset(word_set):
            expanded.extend(concept_terms)
            break

    # Expand individual words via synonym map
    for word in word_list:
        expanded.extend(expand_keywords(word))

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for term in expanded:
        if term.lower() not in seen:
            seen.add(term.lower())
            unique.append(term)

    # Build a single websearch query: "desire" OR "temptation" OR "restrain"
    fts_query = " OR ".join(f'"{t}"' if " " in t else t for t in unique)

    try:
        rows = supabase_rpc("search_hadiths_fts", {"query": fts_query, "lim": limit})
        for r in rows:
            r["collection"] = r.pop("collection_name", "unknown")
            r["collection_full"] = r.pop("collection_full_name", "Unknown")
            r["english_text"] = r["english_text"][:500]
            r.pop("rank", None)
            r.pop("id", None)
        return {"results": rows}
    except Exception as e:
        print(f"  FTS failed ({e}), falling back to ILIKE")
        # Fallback: try first few terms with ILIKE
        for term in unique[:3]:
            rows = supabase_get("hadiths", {
                "english_text": f"ilike.%{term}%",
                "select": "hadith_number,english_text,grading,narrator,collection_id",
                "limit": str(limit),
            })
            if rows:
                col_ids = list(set(r["collection_id"] for r in rows))
                cols = supabase_get("hadith_collections", {
                    "id": f"in.({','.join(col_ids)})",
                    "select": "id,name,full_name",
                })
                col_map = {c["id"]: c for c in cols}
                for r in rows:
                    c = col_map.get(r["collection_id"], {})
                    r["collection"] = c.get("name", "unknown")
                    r["collection_full"] = c.get("full_name", "Unknown")
                    if not r["grading"] and r["collection"] in ("bukhari", "muslim"):
                        r["grading"] = "sahih"
                    r["english_text"] = r["english_text"][:500]
                    del r["collection_id"]
                return {"results": rows}
        return {"results": []}


def lookup_hadith(collection, number):
    """Look up a specific hadith by collection and number."""
    cols = supabase_get("hadith_collections", {
        "name": f"eq.{collection}",
        "select": "id,full_name",
        "limit": "1",
    })
    if not cols:
        return {"error": f"Collection '{collection}' not found"}
    col = cols[0]
    rows = supabase_get("hadiths", {
        "collection_id": f"eq.{col['id']}",
        "hadith_number": f"eq.{number}",
        "select": "hadith_number,english_text,arabic_text,grading,grading_details,narrator,section_name",
        "limit": "1",
    })
    if not rows:
        return {"error": f"Hadith {collection} #{number} not found"}
    h = rows[0]
    h["collection"] = collection
    h["collection_full"] = col["full_name"]
    if not h.get("grading") and collection in ("bukhari", "muslim"):
        h["grading"] = "sahih"
    return h


# --- Gather context for Claude ---
MAX_CONTEXT = 25000  # chars — keeps Claude prompt lean

def _ctx_size(parts):
    return sum(len(p) for p in parts)

def gather_context(question):
    """Analyze the question and gather relevant data from Quran + hadith."""
    import re
    context_parts = []
    q = question.lower()

    # Extract keywords once
    words = [w for w in re.findall(r'\w+', q) if w not in STOP_WORDS and len(w) > 2]

    hadith_keywords = {"hadith", "sunnah", "prophet", "muhammad", "narrated", "pbuh",
                       "messenger", "sahih", "bukhari", "muslim", "tirmidhi", "nasai",
                       "abu dawud", "ibn majah"}
    wants_hadith = bool(hadith_keywords & set(q.split()))

    # --- 1. Direct lookups (highest priority, always run) ---

    # Verse reference (e.g., "2:255")
    verse_match = re.search(r'(\d{1,3}):(\d{1,3})', question)
    if verse_match:
        surah, ayah = int(verse_match.group(1)), int(verse_match.group(2))
        data = lookup_verse(surah, ayah)
        context_parts.append(f"VERSE LOOKUP {surah}:{ayah}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    # Hadith reference (e.g., "bukhari 1", "muslim 2345")
    hadith_match = re.search(r'(bukhari|muslim|abudawud|abu dawud|tirmidhi|nasai|ibnmajah|ibn majah)\s*(?:#?\s*)?(\d+)', q, re.IGNORECASE)
    if hadith_match:
        col_name = hadith_match.group(1).lower().replace(" ", "")
        hnum = hadith_match.group(2)
        data = lookup_hadith(col_name, hnum)
        context_parts.append(f"HADITH LOOKUP {col_name} #{hnum}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    # If we got a direct lookup, that's usually enough
    if context_parts and _ctx_size(context_parts) > 3000:
        return "\n\n---\n\n".join(context_parts)

    # --- 2. Counting questions ---
    count_words = ["how many", "how often", "count", "mentioned", "times"]
    if any(w in q for w in count_words):
        for name in ["moses", "musa", "abraham", "ibrahim", "jesus", "isa",
                      "noah", "nuh", "adam", "david", "dawud", "solomon", "sulaiman",
                      "joseph", "yusuf", "mary", "maryam", "pharaoh", "firaun",
                      "patience", "mercy", "prayer", "paradise", "hellfire"]:
            if name in q:
                data = count_mentions(name)
                context_parts.append(f"COUNT for '{name}':\n{json.dumps(data, ensure_ascii=False)}")

    # --- 3. Surah info ---
    surah_match = re.search(r'surah\s+(\w+)', q, re.IGNORECASE)
    if surah_match:
        name = surah_match.group(1)
        for num, sname in SURAH_NAMES.items():
            if name.lower() in sname.lower():
                data = get_surah_info(num)
                context_parts.append(f"SURAH INFO:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
                break

    # --- 4. Topic search ---
    topics = ["patience", "gratitude", "mercy", "worship", "guidance", "tawakkul",
              "justice", "knowledge", "sincerity", "repentance", "charity", "afterlife",
              "tawhid", "prophethood", "family", "hardship", "community", "creation",
              "provision", "remembrance"]
    matched_topics = [t for t in topics if t in q]
    for topic in matched_topics[:1]:  # Max 1 topic to save context space
        if _ctx_size(context_parts) < MAX_CONTEXT:
            data = search_by_topic(topic, limit=3)
            context_parts.append(f"TOPIC '{topic}':\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    # --- 5. FTS searches (Quran + Hadith) ---
    if words and _ctx_size(context_parts) < MAX_CONTEXT:
        # Build a search query from keywords
        fts_query = " OR ".join(words[:4])

        # Quran FTS (if no Quran context yet)
        has_quran = any(k in p for p in context_parts for k in ("VERSE", "TOPIC", "COUNT", "SURAH"))
        if not has_quran:
            data = search_quran(fts_query, limit=3)
            if data["results"]:
                context_parts.append(f"QURAN SEARCH:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
                # Get tafsir for top result
                if _ctx_size(context_parts) < MAX_CONTEXT:
                    r = data["results"][0]
                    vdata = lookup_verse(r["surah_number"], r["ayah_number"])
                    context_parts.append(f"TAFSIR for {r['surah_number']}:{r['ayah_number']}:\n{json.dumps(vdata, ensure_ascii=False, indent=2)}")

        # Hadith FTS (always search if question wants it, or as supplement)
        has_hadith = any("HADITH" in p for p in context_parts)
        if not has_hadith and _ctx_size(context_parts) < MAX_CONTEXT:
            hlimit = 5 if wants_hadith else 3
            data = search_hadith_fts(words[:3], limit=hlimit)
            if data["results"]:
                label = "HADITH SEARCH" if wants_hadith else "RELATED HADITHS"
                context_parts.append(f"{label}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    return "\n\n---\n\n".join(context_parts) if context_parts else "No relevant data found in the database."


# --- Claude reasoning ---
def ask_claude(question, context, history=None):
    """Use Claude Code CLI to reason over the context."""
    history_block = ""
    if history:
        turns = []
        for h in history:
            prefix = "User" if h["role"] == "user" else "Mizan"
            turns.append(f"{prefix}: {h['text'][:500]}")
        history_block = (
            "\nPREVIOUS CONVERSATION:\n"
            + "\n".join(turns)
            + "\n\n(The user's current question may reference topics from above.)\n"
        )

    prompt = f"""You are Mizan (Al-Bayan), an Islamic knowledge assistant. A user asked:

"{question}"
{history_block}
Here is the relevant data from the Quran, tafsir, and hadith database:

{context}

RULES:
- Use ONLY the provided data to answer. Do not make up verses, tafsir, or hadiths.
- NEVER issue fiqh rulings.
- Keep response concise (Telegram format, under 3000 chars).
- Include Arabic text when showing Quranic verses.
- End with a reflective question (practice off-ramp) to move knowledge toward action.
- If the data doesn't answer the question, say so honestly.

FORMATTING (Telegram Markdown):
- Use these tier badges inline, never on their own line:
  📖 = Quoted (Quran/hadith text verbatim)
  📝 = Paraphrased (tafsir/scholarly explanation)
  💭 = AI-Generated (your own synthesis/framing)
- For Quran citations: *(Surah Name, Ayah#)*
- For hadith citations with grading badge:
  ✅ = Sahih  |  ⚠️ = Hasan  |  ❌ = Da'if
  Format: *(Collection #Number · ✅ Sahih · Narrator)*
- Use > for blockquotes when quoting Arabic or translation text
- Use --- between major sections
- Bold key phrases with *asterisks*
- Keep the reflective question at the end, preceded by ---

Respond directly to the user's question:"""

    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            return f"I encountered an issue processing your question. Error: {result.stderr[:200] if result.stderr else 'unknown'}"
    except subprocess.TimeoutExpired:
        return "I'm taking too long to think. Please try a simpler question."
    except Exception as e:
        return f"Error: {str(e)}"


# --- Telegram helpers ---
def tg_request(method, data=None):
    """Make a Telegram Bot API request."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
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


# --- Main loop ---
def main():
    print("=" * 50)
    print("Mizan (Al-Bayan) — Local Telegram Bot")
    print("Using Claude Code CLI with Max plan")
    print("=" * 50)

    # Delete webhook so we can use long polling
    print("Removing webhook for long polling...")
    tg_request("deleteWebhook")

    # Verify claude CLI
    try:
        result = subprocess.run([CLAUDE_PATH, "--version"], capture_output=True, text=True, timeout=5)
        print(f"Claude CLI: {result.stdout.strip()}")
    except Exception as e:
        print(f"ERROR: Claude CLI not found at {CLAUDE_PATH}: {e}")
        sys.exit(1)

    print("Bot is running. Press Ctrl+C to stop.\n")

    offset = 0

    def handle_shutdown(sig, frame):
        print("\nShutting down... Restoring webhook.")
        try:
            tg_request("setWebhook", {
                "url": f"{SUPABASE_URL}/functions/v1/al-bayan-bot"
            })
            print("Webhook restored.")
        except Exception:
            print("Warning: Could not restore webhook.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    # Don't catch SIGTERM when running in background
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

                # Get or create session
                session = get_session(chat_id)

                # Handle commands
                if text == "/start":
                    sessions.pop(chat_id, None)  # Reset session
                    send_message(chat_id,
                        "*Bismillah* — Welcome to Mizan 🌙\n\n"
                        "I am an Islamic knowledge engine that searches primary sources "
                        "and reasons over them — not a chatbot giving opinions.\n\n"
                        "*What I search:*\n"
                        "📗 6,236 Quranic ayat (complete Quran)\n"
                        "📘 4 classical tafsir traditions\n"
                        "📙 36,000+ hadiths from 8 collections\n\n"
                        "*How I label my answers:*\n"
                        "📖 *Quoted* — exact Quran or hadith text\n"
                        "📝 *Paraphrased* — scholarly tafsir in my words\n"
                        "💭 *AI-Generated* — my own synthesis\n\n"
                        "*Hadith grading:*\n"
                        "✅ Sahih  ·  ⚠️ Hasan  ·  ❌ Da'if\n\n"
                        "*Try asking:*\n"
                        "• _What does the Quran say about patience?_\n"
                        "• _Any hadith on sincerity of intention?_\n"
                        "• _Explain the inner dimensions of 2:255_\n"
                        "• _Bukhari 1_ (direct hadith lookup)\n\n"
                        "💬 _I remember context — ask follow-ups like \"tell me more\" or \"what about the Arabic?\"_\n\n"
                        "⚠️ I do not issue fiqh rulings (halal/haram). "
                        "Consult a qualified scholar for those."
                    )
                    print("  -> /start response sent")
                    continue

                if text == "/help":
                    send_message(chat_id,
                        "*Mizan — How to use* 📖\n\n"
                        "Ask in plain language. I search the sources, then reason.\n\n"
                        "*Query types:*\n"
                        "🔍 _\"What does the Quran say about envy?\"_\n"
                        "🔍 _\"Any hadith about fighting the nafs?\"_\n"
                        "🔍 _\"How many times is Musa mentioned?\"_\n"
                        "📌 _\"2:255\"_ — direct verse + tafsir\n"
                        "📌 _\"Bukhari 50\"_ — direct hadith lookup\n"
                        "📌 _\"Surah Al-Kahf\"_ — surah overview\n\n"
                        "*Follow-ups work:*\n"
                        "• _\"Tell me more about that\"_\n"
                        "• _\"What about the Arabic?\"_\n"
                        "• _\"And the hadith on this topic?\"_\n\n"
                        "*My library:*\n"
                        "• *Quran:* 6,236 ayat · Sahih International\n"
                        "• *Tafsir:* Ibn Kathir · Al-Jalalayn · Al-Qurtubi · Al-Sa'di\n"
                        "• *Hadith:* Bukhari · Muslim · Abu Dawud · Tirmidhi · Nasai · Ibn Majah\n"
                        "• *Special:* 40 Nawawi · Riyad al-Salihin\n\n"
                        "*Transparency tiers:*\n"
                        "📖 Quoted · 📝 Paraphrased · 💭 AI-Generated\n"
                        "✅ Sahih · ⚠️ Hasan · ❌ Da'if"
                    )
                    print("  -> /help response sent")
                    continue

                if text == "/clear":
                    sessions.pop(chat_id, None)
                    send_message(chat_id, "🔄 Conversation cleared. Ask me anything fresh.")
                    print("  -> /clear response sent")
                    continue

                # Fiqh gate
                word_set = set(text.lower().split())
                if word_set & FIQH_KEYWORDS:
                    send_message(chat_id,
                        "⚠️ *Scholar Gate*\n\n"
                        "This question involves a fiqh ruling that requires qualified scholarly judgment. "
                        "I can share relevant Quranic verses and commentary for context, but I cannot issue rulings.\n\n"
                        "Please consult a qualified scholar (mufti) for a definitive answer.\n\n"
                        "_If you'd like, rephrase your question to explore the Quranic theme instead._"
                    )
                    print("  -> Fiqh gate triggered")
                    continue

                # Process question
                send_typing(chat_id)

                # Detect follow-up
                followup = is_followup(text, session)

                if followup and session["last_context"]:
                    print("  Follow-up detected, reusing context...")
                    context = session["last_context"]

                    # Check if they want additional data on top
                    q_lower = text.lower()
                    if any(w in q_lower for w in ("hadith", "sunnah", "narrated")):
                        if session["last_topics"]:
                            extra = search_hadith_fts(session["last_topics"][:3], limit=5)
                            if extra["results"]:
                                context += f"\n\n---\n\nADDITIONAL HADITH SEARCH:\n{json.dumps(extra, ensure_ascii=False, indent=2)}"
                    elif any(w in q_lower for w in ("verse", "ayah", "quran")):
                        if session["last_topics"]:
                            fts_q = " OR ".join(session["last_topics"][:4])
                            extra = search_quran(fts_q, limit=5)
                            if extra["results"]:
                                context += f"\n\n---\n\nADDITIONAL QURAN SEARCH:\n{json.dumps(extra, ensure_ascii=False, indent=2)}"
                else:
                    print("  Gathering context...")
                    context = gather_context(text)

                print("  Asking Claude...")
                send_typing(chat_id)
                answer = ask_claude(text, context, session["history"] if session["history"] else None)

                # Update session
                add_to_history(session, "user", text)
                add_to_history(session, "assistant", answer)
                session["last_query"] = text
                session["last_context"] = context
                import re as _re
                session["last_topics"] = [w for w in _re.findall(r'\w+', text.lower())
                                          if w not in STOP_WORDS and len(w) > 2]

                send_message(chat_id, answer)
                print(f"  -> Response sent ({len(answer)} chars)")
                print(f"  >> {answer[:300]}{'...' if len(answer) > 300 else ''}")

        except urllib.error.URLError as e:
            print(f"Network error: {e}. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"Error: {e}. Retrying in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
