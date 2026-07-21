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
import re
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error
import sys
import os
import signal
import datetime


# --- Force IPv4 (op#5959 — Bayan poll-loop outage) --------------------------
# The Studio host advertises an IPv6 address but has NO working IPv6 route, so
# IPv6-first connects to api.telegram.org hang ("No route to host", Errno 65),
# stalling the getUpdates long-poll and leaving user messages unanswered. Pin
# name resolution to IPv4 so every socket uses the route that actually works.
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _getaddrinfo_ipv4_only(*args, **kwargs):
    infos = _orig_getaddrinfo(*args, **kwargs)
    v4 = [i for i in infos if i[0] == _socket.AF_INET]
    return v4 or infos
_socket.getaddrinfo = _getaddrinfo_ipv4_only


# --- Self-contained env loading (msg #2744 hardening) -----------------------
# The bot invokes the claude CLI with os.environ; when CLAUDE_CODE_OAUTH_TOKEN
# is absent the CLI silently falls back to the macOS keychain login, which an
# operator password-reset can invalidate — the #2744 outage. Load ai-scholar/.env
# (gitignored) at startup so Claude auth + bot config are self-contained and
# survive a launchd plist rebuild. Process/plist env ALWAYS wins: we only fill
# keys that are not already set. Runs before the retrieval-module imports below
# so they see the same populated environment.
def _load_env_file():
    env_path = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    )
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  -> .env load skipped: {type(e).__name__}: {e}")


_load_env_file()

# Phase 2 semantic-first retrieval for fiqh substrate.
# Architectural pivot per CAI-PROCESS-GLUE-AUDIT-MIZANBOT-001 (id 870) hybrid
# ruling — lifts the freeze marker once shipped + validated.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fiqh_semantic  # noqa: E402
import hadith_semantic  # noqa: E402 — bge-m3 + bge-reranker-v2-m3 path
import tafsir_semantic  # noqa: E402

# --- Config ---
BOT_TOKEN = os.environ.get("MIZAN_BOT_TOKEN", "")
SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"
CLAUDE_PATH = os.path.expanduser("~/.local/bin/claude")

# --- 40-answer self-review hardening (msg #10510) ---
# Fix #2c: when set, this bot run is a developer/test pass. Its interactions are
# NOT persisted to mizan_interactions (the judge/eval/gold-set corpus), so dev
# testing can't pollute the audit substrate. See persist_emission().
MIZAN_TEST_MODE = os.environ.get("MIZAN_TEST_MODE", "").strip().lower() in ("1", "true", "yes", "on")

# Fix #2a (persona-leak root cause): the synthesis CLI call is invoked with
# `--tools ""` (no tools) AND cwd pointed at this empty sandbox, NOT the repo.
# The 40-answer review found dev/test context ("uncommitted mizan_bot.py", the
# raw RULES text, char-budget internals) leaking into user answers because
# `claude -p` ran as a FULL AGENTIC CLI in the repo working directory with
# filesystem/tool access, so it could read the uncommitted source + skills and
# fold them into the reply. Disabling tools + neutralising cwd removes that
# capability entirely (and speeds synthesis — no tool-use wandering).
import tempfile  # noqa: E402
_SYNTH_SANDBOX_DIR = tempfile.mkdtemp(prefix="mizan-synth-")

# AL-BAYAN-COMPOSE-001 producer wiring per CAI-RESP-135
PERSIST_FUNCTION_URL = SUPABASE_URL + "/functions/v1/persist-mizan-ruling"
# Admin chat for the /review scholar-verification export (#2746). Unset = the
# command self-bootstraps by telling the caller their chat_id (no data leaks).
ADMIN_CHAT_ID = os.environ.get("MIZAN_ADMIN_CHAT_ID", "").strip()

# CAI-RESP-287 class-B label — every AI-generated answer is a draft for
# reflection, NOT a fatwa. Appended to the displayed answer (not persisted, not
# fed back into conversation history). Tasteful but unmissable per the ihsan bar.
AI_DRAFT_DISCLAIMER = (
    "\n\n———\n"
    "ℹ️ _AI draft for reflection — not a fatwa. Pending scholarly review; "
    "please verify with a qualified scholar._"
)

# --- User prefs (file-based for v0.1) ---
# The mizan_user_prefs table migration is authored at
# supabase/migrations/20260603_001_mizan_user_prefs.sql but not yet applied
# (CLI db push blocked on migration history drift; apply via Studio SQL editor
# or psql with the DB password when ready). File-based persistence covers
# single-host launchd-managed bot until then. The on-disk JSON shape is the
# same as the row shape, so the migration path later is a one-time backfill.
import hashlib

USER_PREFS_PATH = os.path.expanduser("~/.mizan_user_prefs.json")
MADHHAB_VALID = ("shafii", "hanafi", "maliki", "hanbali")


def _hash_telegram_id(telegram_id):
    """sha256(str(telegram_id)) — matches the hashing done by persist-mizan-ruling
    server-side. Used to key user prefs without storing raw telegram IDs."""
    return hashlib.sha256(str(telegram_id).encode("utf-8")).hexdigest()


def _load_user_prefs():
    """Returns {telegram_id_hash: {"madhhab": str|None, "updated_at": str}}.
    Empty dict if file missing. Fails-soft on any read error so a corrupt
    file doesn't crash the bot."""
    try:
        with open(USER_PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_user_prefs(prefs):
    """Atomic write via temp file + rename. Fails-soft."""
    try:
        tmp = USER_PREFS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)
        os.replace(tmp, USER_PREFS_PATH)
        os.chmod(USER_PREFS_PATH, 0o600)
    except OSError as e:
        print(f"  _save_user_prefs failed: {e}")


def get_user_madhhab(telegram_id):
    """Returns madhhab string (shafii/hanafi/maliki/hanbali) or None."""
    if telegram_id is None:
        return None
    h = _hash_telegram_id(telegram_id)
    prefs = _load_user_prefs()
    return (prefs.get(h) or {}).get("madhhab")


def set_user_madhhab(telegram_id, madhhab):
    """Set or clear (madhhab=None) a user's school preference."""
    if telegram_id is None:
        return
    if madhhab is not None and madhhab not in MADHHAB_VALID:
        raise ValueError(f"invalid madhhab: {madhhab!r}; valid: {MADHHAB_VALID}")
    h = _hash_telegram_id(telegram_id)
    prefs = _load_user_prefs()
    if madhhab is None:
        prefs.pop(h, None)
    else:
        prefs[h] = {"madhhab": madhhab, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save_user_prefs(prefs)


# --- Durable per-chat state (last question + answer level) ---
# The in-memory `sessions` dict is wiped on a process restart AND on the 30-min
# SESSION_TTL prune. A level button (👶 Simpler / 🎓 More detail) lives on a
# Telegram message indefinitely, so a tap after either event landed on a fresh
# empty session whose last_query was "" — the dead-end "Level set to X. Ask me
# your next question." (operator-reported 2026-06-17, msg #2476). Now the bot
# managed-lane auto-restarts, so this is the common case, not an edge case.
# Persisting last_query + answer_level per chat lets the level-button callback
# re-answer the previous question even across a restart. Keyed by sha256(chat_id)
# to avoid storing raw chat IDs at rest; mirrors the user-prefs store (0600).
CHAT_STATE_PATH = os.path.expanduser("~/.mizan_chat_state.json")


def _load_chat_state():
    """Returns {chat_id_hash: {"last_query": str, "answer_level": str,
    "updated_at": str}}. Empty dict if missing/corrupt — fails-soft."""
    try:
        with open(CHAT_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_chat_state(state):
    """Atomic write via temp file + rename. Fails-soft."""
    try:
        tmp = CHAT_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CHAT_STATE_PATH)
        os.chmod(CHAT_STATE_PATH, 0o600)
    except OSError as e:
        print(f"  _save_chat_state failed: {e}")


def save_chat_state(chat_id, last_query, answer_level):
    """Persist the per-chat last question + level so a level-button press
    survives a process restart or session-TTL prune."""
    if chat_id is None:
        return
    k = _hash_telegram_id(chat_id)
    state = _load_chat_state()
    state[k] = {
        "last_query": last_query or "",
        "answer_level": answer_level or "seeker",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_chat_state(state)


def load_chat_state(chat_id):
    """Returns the persisted {"last_query", "answer_level", ...} dict for a
    chat, or None."""
    if chat_id is None:
        return None
    k = _hash_telegram_id(chat_id)
    return _load_chat_state().get(k)


MADHHAB_GUIDANCE = {
    "shafii": (
        "User follows the SHAFI'I school. When surfacing ikhtilaf on any "
        "fiqh question, lead with the Shafi'i position and note divergences "
        "from other schools. The retrieved fiqh corpus (Safīnat al-Najā, "
        "Nihāyat al-Zayn) is already Shafi'i — surface it confidently."
    ),
    "hanafi": (
        "User follows the HANAFI school. When surfacing ikhtilaf, lead with "
        "the Hanafi position if available in retrieved evidence; if the "
        "retrieved fiqh matn is Shafi'i (which it usually is — corpus gap), "
        "explicitly flag the school mismatch and route the user to a Hanafi "
        "scholar for the Hanafi-specific answer. Do NOT fabricate the "
        "Hanafi position from parametric knowledge."
    ),
    "maliki": (
        "User follows the MALIKI school. When surfacing ikhtilaf, lead with "
        "the Maliki position if in retrieved evidence; otherwise flag the "
        "school mismatch (retrieved fiqh matn is Shafi'i) and route to a "
        "Maliki scholar. Do NOT fabricate the Maliki position from memory."
    ),
    "hanbali": (
        "User follows the HANBALI school. When surfacing ikhtilaf, lead "
        "with the Hanbali position if in retrieved evidence; otherwise "
        "flag the school mismatch (retrieved fiqh matn is Shafi'i) and "
        "route to a Hanbali scholar. Do NOT fabricate the Hanbali "
        "position from memory."
    ),
}


class RetrievalMeta:
    """Threads retrieval IDs through gather_context → persist_emission so the
    mizan_interactions audit row carries the actual passages the bot grounded
    on, per F-2 (tafsir-defense-funnel) and INV-8 (audit substrate).

    matched_passage_id: top tafsir hit's ayah_id (None if no tafsir FTS match).
    retrieval_ids: union of all retrieval row IDs (tafsir ayah_id / juridical_text_id /
    hadith id) in encounter order, deduplicated.
    """
    def __init__(self):
        self.matched_passage_id = None
        self._ids = []
        self._seen = set()
        # retrieval_config: the retrieval-substrate config dict (retriever
        # version / path / reranker / limit / cap / gate) returned by
        # fiqh_semantic.search_semantic, stamped into the audit row per
        # CAI-RESP-220 so an evidence set is reproducible from its config.
        # First non-None config wins (the semantic fiqh path that grounded
        # the response); FTS-fallback / followup paths leave it None.
        self.retrieval_config = None

    def set_retrieval_config(self, cfg):
        if cfg and self.retrieval_config is None:
            self.retrieval_config = cfg

    def _add(self, rid):
        if not rid or rid in self._seen:
            return
        self._seen.add(rid)
        self._ids.append(rid)

    def add_tafsir_hits(self, hits):
        for h in hits or []:
            rid = h.get("ayah_id")
            if rid:
                if self.matched_passage_id is None:
                    self.matched_passage_id = rid
                self._add(rid)

    def add_juridical_hits(self, hits):
        for h in hits or []:
            self._add(h.get("id"))

    def add_hadith_hits(self, hits):
        for h in hits or []:
            self._add(h.get("id"))

    @property
    def retrieval_ids(self):
        return list(self._ids)

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

# AL-BAYAN-003-AMEND-ENGLISH-FIRST-001 / id 699 + CAI-RESP-136 / id 756 routing.
# Two separate keyword sets:
#  - RULING_KEYWORDS / RULING_PHRASES → scholar gate (block ruling-class queries
#    that ask for fatwa-shaped answers). Original FIQH_KEYWORDS purpose.
#  - FIQH_TOPIC_KEYWORDS → trigger juridical_translations retrieval (retrieve-only
#    echo of Safīnat al-Marbūqī English). New v0 fiqh-substrate routing.
#
# These were merged into a single variable in 51db328 — caused fiqh-topic queries
# (e.g. "what are the arkan of wudu") to trigger the scholar gate. Restoring
# separation. C4 boundary unchanged: NO compose synthesis from fiqh substrate.

RULING_KEYWORDS = {
    "halal", "haram", "permissible", "ruling", "allowed", "forbidden",
    "fard", "wajib", "makruh", "mustahab", "fatwa", "obligatory", "sinful",
    "bid'ah", "bidah",
}

RULING_PHRASES = [
    r"is\s+it\s+(halal|haram|permissible|allowed|forbidden)\s+to",
    r"can\s+i\s+.+\s+in\s+islam",
    r"ruling\s+on",
    r"is\s+it\s+ok(ay)?\s+to",
    r"am\s+i\s+allowed\s+to",
    r"do\s+i\s+have\s+to",
    r"what\s+is\s+the\s+punishment\s+for",
    r"must\s+i",
    r"is\s+it\s+permissible",
]

FIQH_TOPIC_KEYWORDS = {
    # Madhhab + general fiqh terminology
    "fiqh", "madhhab", "madhab",
    "shafii", "shafi'i", "shafi", "shaafi",
    "safinat", "safinah", "matn",
    # Worship topics covered in v0 ingestion (taharah / salah / zakah / siyam)
    "wudu", "wuduʾ", "ablution",
    "ghusl", "tayammum", "ritual bath",
    "purity", "taharah", "tahara",
    "najasah", "najis", "impurity",
    "salah", "salat", "salaah", "prayer",
    "adhan", "athan", "iqamah",
    "rukn", "arkan", "pillar", "pillars",
    "janazah", "funeral",
    "jumʿah", "jumuah",
    "zakah", "zakat", "alms",
    "saum", "sawm", "siyam", "fasting", "fast", "fasts", "fasted",
    "ramadan", "ramadhan", "ramaḍān",
    "iftar", "suhur", "kaffara", "kaffarah",
    # Common verb forms users type in queries (FTS handles stemming
    # downstream; this just opens the gate). Matched word-boundary
    # to avoid 'fast' substring-matching 'breakfast' / 'steadfast'.
    "nullify", "nullifies", "nullified",
    "invalidate", "invalidates",
    "break", "breaks", "breaking",
    # Hajj — coverage added 2026-05-20 (Kashifat al-Sajā Hajj baab via
    # ingest_kashifat_hajj.py, baab_order=6 under Safīnat umbrella).
    "hajj", "ḥajj", "umrah", "ʿumrah", "umrat",
    "ihram", "iḥrām", "muhrim", "muḥrim",
    "miqat", "mīqāt", "mawaqit", "mawāqīt",
    "tawaf", "ṭawāf", "tawafs",
    "saʿy", "sai", "saiy", "sa'i", "sa'ee",
    "safa", "marwah", "marwa",
    "arafah", "ʿarafah", "wuquf", "wuqūf",
    "muzdalifah", "mina", "minā",
    "jamarat", "jamrah", "rami", "ramy",
    "tahallul", "taḥallul",
    "hady", "hadi", "qurbani", "udhiyah", "uḍḥiya",
    "tamattuʿ", "tamattu", "qiran", "qirān", "ifrad", "ifrād",
    # Munakahat (family law) — added 2026-06-13 per "fiqh topic retrieve and
    # frame" directive. Routes definitional/procedural family-law questions to
    # juridical retrieval, NOT the scholar gate. Explicit halal/haram judgment
    # requests still hit RULING_KEYWORDS first (e.g. "is mutʿah halal") and gate
    # correctly; these only open the retrieve-and-frame path for topic queries.
    "nikah", "nikaah", "nikkah", "marriage", "marry", "wedding",
    "nafkah", "nafaqah", "nafaqa", "maintenance", "upkeep",
    "mahr", "mas kahwin", "maskahwin", "dowry", "bridal gift",
    "wali", "walī", "guardian",
    "mutʿah", "mutah", "mut'ah", "consolatory gift",
    "talaq", "talak", "ṭalāq", "divorce", "divorced",
    "taklik", "taʿliq", "ta'liq", "conditional divorce",
    "khulʿ", "khul", "khulu", "khula",
    "faskh", "annulment",
    "rujuk", "rujūʿ", "ruju", "reconciliation",
    "iddah", "ʿiddah", "idda", "waiting period",
    "hadanah", "ḥaḍānah", "hadhanah", "custody",
    "li'an", "liʿan", "lian", "zihar", "ẓihār", "ila", "īlāʾ",
    # Raḍāʿah (milk-kinship) + maḥram sub-topic — added 2026-06-16 after a
    # ping quality-sweep found "how many breastfeedings to be considered
    # mahram" matched no munakahat term and so never opened juridical
    # retrieval (Bāb al-Raḍāʿ content confirmed present in the corpus).
    # Topic-class recall expansion only — ruling-class "is it haram to marry
    # my foster sister" still hits RULING_KEYWORDS first and gates correctly.
    # Bare "rida"/"radaa" deliberately EXCLUDED: collides with riḍā
    # (contentment), an unrelated tasawwuf term.
    "radāʿah", "radaah", "rada'ah", "raḍāʿ", "raḍāʿah",
    "breastfeeding", "breastfeed", "suckling", "suckle",
    "wet nurse", "wet-nurse", "milk kinship", "milk sibling", "milk mother",
    "foster sibling", "foster brother", "foster sister", "foster mother",
    "mahram", "maharim", "mahārim", "mahramiyyah",
}


def match_ruling_query(text: str) -> bool:
    """Detect ruling-class queries (asking for halal/haram judgment) → scholar gate."""
    import re
    t = text.lower()
    if any(kw in t.split() for kw in RULING_KEYWORDS):
        return True
    for pattern in RULING_PHRASES:
        if re.search(pattern, t):
            return True
    return False


# CAI-RESP-287 class C — high-consequence / irreversible matters that must NOT
# receive an AI ruling (mis-stating these is spiritual liability before legal).
# Route to a human scholar instead. Conservative by design: better to over-route
# to a human than under-route.
HIGH_STAKES_KEYWORDS = {
    # Divorce — irreversible marital dissolution
    "talaq", "talak", "ṭalāq", "divorce", "divorces", "divorcing", "divorced",
    "khula", "khulʿ", "khul", "faskh", "annul", "annulment",
    # Inheritance / estate division (farāʾiḍ)
    "inheritance", "inherit", "inherits", "inheriting", "inherited",
    "faraid", "farāʾiḍ", "mirath", "mīrāth", "warith", "heir", "heirs",
    "estate", "bequest", "wasiyyah", "wasiyya",
    # Other grave / irreversible
    "apostasy", "apostate", "riddah", "murtad",
}
HIGH_STAKES_PHRASES = [
    r"how\s+(do|can|should)\s+i\s+divorce",
    r"divorce\s+my\s+(wife|husband|spouse)",
    r"(should|can)\s+i\s+divorce",
    r"(three|triple)\s+tala[qk]",
    r"divide\s+(the\s+|my\s+|his\s+|her\s+)?(inheritance|estate|property|wealth)",
    r"share\s+of\s+(the\s+)?inheritance",
    r"who\s+(gets|inherits|should inherit)",
    r"leav(e|ing)\s+islam",
    r"renounce\s+islam",
]


def match_high_stakes_query(text: str) -> bool:
    """High-consequence / irreversible matters (divorce, inheritance, apostasy)
    that must route to a human scholar, NOT an AI ruling (CAI-RESP-287 class C).

    Carve-out: explicit tafsir / verse-lookup requests are educational, not
    personal-ruling requests, so they flow to normal retrieval — the bot's core
    function (e.g. explaining the inheritance verses of Sūrat an-Nisāʾ) must not
    be blocked. Personal action-framed questions ("how do I divorce…") still route.
    """
    import re
    t = text.lower()
    # Educational tafsir / verse lookups are not personal high-stakes rulings.
    if re.search(r"\btafsir\b|\btafseer\b|meaning of (the )?(surah|sura|ayah|ayat|verse)", t):
        return False
    if re.search(r"\b\d{1,3}\s*[:：]\s*\d{1,3}\b", t):  # surah:ayah reference
        return False
    if any(re.search(r"\b" + re.escape(kw) + r"\b", t) for kw in HIGH_STAKES_KEYWORDS):
        return True
    for pattern in HIGH_STAKES_PHRASES:
        if re.search(pattern, t):
            return True
    return False


def match_fiqh_query(text: str) -> bool:
    """Detect Shafi'i fiqh-topic keywords in query → trigger juridical_translations
    retrieval. Topic-class queries (about wudu, salah, etc.) bypass the scholar gate
    and surface matn passages for reference. Hajj keywords NOT in set (deferred
    to Phase 2 ingestion).

    Word-boundary match (not substring) — prevents short keywords like 'fast'
    from triggering on 'breakfast' / 'steadfast' / 'fastest'.
    """
    import re
    t = text.lower()
    for kw in FIQH_TOPIC_KEYWORDS:
        if re.search(r'\b' + re.escape(kw.lower()) + r'\b', t):
            return True
    return False


FIQH_TERM_EXPANSIONS = {
    # Transliterated Arabic → English equivalents in al-Marbuqi text.
    # PostgreSQL FTS handles English stemming, hyphens, suffixes, and stop-words
    # natively — those entries are intentionally NOT here. This dict ONLY bridges
    # cross-language vocabulary that FTS cannot stem (Arabic transliteration ↔
    # English worship terms).
    #
    # Phase 2 semantic embeddings (per EMBED_PIPELINE_v02) will retire even this
    # mapping by understanding ablution ≈ wudu via vector similarity.
    "wudu":     ["ablution"],
    "wuduʾ":    ["ablution"],
    "ghusl":    ["bath"],
    "tayammum": ["tayammum"],
    "taharah":  ["purity", "purification"],
    "tahara":   ["purity", "purification"],
    "najasah":  ["impurity"],
    "najis":    ["impurity"],
    "salah":    ["prayer"],
    "salat":    ["prayer"],
    "salaah":   ["prayer"],
    "adhan":    ["adhan"],
    "iqamah":   ["iqamah"],
    "rukn":     ["pillar", "obligatory"],
    "arkan":    ["pillars", "obligatory"],
    "fard":     ["obligatory"],
    "fardh":    ["obligatory"],
    "janazah":  ["funeral"],
    "jumʿah":   ["friday", "jumuah"],
    "jumuah":   ["friday"],
    "zakah":    ["zakat", "alms"],
    "zakat":    ["alms"],
    "saum":     ["fasting"],
    "sawm":     ["fasting"],
    "siyam":    ["fasting"],
    "iftar":    ["iftar"],
    "suhur":    ["suhur"],
    "kaffara":  ["expiation"],
    "kaffarah": ["expiation"],
    "shafii":   ["shafi"],
    "shafi'i":  ["shafi"],
    "madhhab":  ["school"],
    "fiqh":     ["jurisprudence"],
    "mufsid":   ["nullify"],
    "mufattir": ["nullify"],
    "mufsidat": ["nullify"],
    "mufattirat": ["nullify"],
}


def expand_fiqh_keywords(words: list) -> list:
    """For each transliterated Arabic term, also include English equivalents.
    Returns a deduped list, original words first then expansions."""
    out = []
    seen = set()
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
        for alt in FIQH_TERM_EXPANSIONS.get(w, []):
            if alt not in seen:
                seen.add(alt)
                out.append(alt)
    return out


def lookup_fiqh(keywords_query: str, limit: int = 3) -> dict:
    """Query juridical_translations via Postgres FTS RPC (search_juridical_translations_fts).

    PostgreSQL English FTS handles stemming (nullifies → nullify), stop-words,
    hyphens, suffix variation natively. ts_rank gives built-in relevance
    scoring. Replaces the prior ILIKE+expansion treadmill.

    FIQH_TERM_EXPANSIONS still applied BEFORE the FTS call to bridge
    transliterated Arabic terms (wudu, arkan, etc.) to their English
    equivalents in the al-Marbuqi corpus — FTS cannot stem across languages.

    Returns: {results: [{baab, translator, text, source_work, ...}]}
    """
    raw_words = [w for w in keywords_query.lower().split() if w not in STOP_WORDS and len(w) > 2]
    if not raw_words:
        return {"results": []}
    expanded = expand_fiqh_keywords(raw_words)
    # Build a websearch_to_tsquery-compatible OR query from expanded terms.
    # websearch_to_tsquery treats space-separated terms as AND by default; we
    # want OR for broad fiqh-topic matching, so explicitly join with " OR ".
    fts_query = " OR ".join(expanded[:8])

    try:
        rows = supabase_rpc("search_juridical_translations_fts", {
            "query": fts_query,
            "lim": limit,
        })
    except Exception:
        return {"results": []}
    if not rows:
        return {"results": []}

    # For each translation hit, fetch baab_or_section from juridical_texts
    # for fuller attribution. Snippet still extracted via _extract_keyword_snippet
    # (anchors on first keyword occurrence past the chapter heading zone).
    results = []
    for r in rows:
        baab = "?"
        jt_id = r.get("juridical_text_id")
        try:
            if jt_id:
                texts = supabase_get(f"juridical_texts?id=eq.{jt_id}&select=baab_or_section,author_name,text_name")
                if texts:
                    baab = texts[0].get("baab_or_section", "?")
        except Exception:
            pass
        full_text = r.get("translation_text") or ""
        snippet = _extract_keyword_snippet(full_text, expanded, before=500, after=1500)
        results.append({
            "id": jt_id,                # F-2: juridical_text_id for retrieval_ids audit
            "baab": baab,
            "translator": r.get("translator_name", "?"),
            "source_work": r.get("translation_source_work", "?"),
            "edition": r.get("edition_label", ""),
            "text": snippet,
            "tier": r.get("output_tier", "paraphrased"),
            "rank": r.get("rank", 0.0),
        })
    return {"results": results}


# Ultra-generic words that appear in almost every fiqh matn — they do NOT count
# as evidence that a keyword-fallback hit actually answers the user's question.
_MATN_GENERIC_WORDS = {"quran", "qur", "islam", "islamic", "allah", "muslim",
                       "muslims", "religion", "deen", "book", "verse", "chapter"}


def _matn_relevant_to_query(hit, query_words) -> bool:
    """Fix #5 (msg #10510): True iff an FTS-fallback matn hit is lexically grounded
    in the user's LITERAL query terms — guards the 'MUST surface matn' rule from
    force-quoting off-topic keyword matches.

    Prefix-stem (len>=4) matching so 'nullifies'↔'nullify', 'fasting'↔'fast' count;
    a matn sharing no user content word (fasting rules vs a 'coding' query) is
    dropped. Ultra-generic words (quran/islam/…) are excluded so they can't rescue
    an otherwise off-topic hit (e.g. 'decode the quran').
    """
    if not query_words:
        return False
    haystack = ((hit.get("text") or "") + " " + (hit.get("baab") or "")).lower()
    for w in query_words:
        if w in _MATN_GENERIC_WORDS:
            continue
        needle = w[:4] if len(w) >= 4 else w
        if needle in haystack:
            return True
    return False


def _extract_keyword_snippet(text: str, keywords: list, before: int = 500, after: int = 1500) -> str:
    """Return a window around the first keyword occurrence in text, walked
    by keyword priority order (user's literal terms first, then expansions).

    For Safīnat-class long chapter rows, the chapter title repeats the broad
    topic word at offset 0 (e.g., 'Fasting of Ramaḍān' at the start of Siyam).
    Anchoring there misses sub-section content. Mitigation: when a keyword's
    first occurrence is in the chapter-heading zone (first 250 chars), look
    for a LATER occurrence of the same keyword OR move on to the next priority
    keyword. This trades chapter-intro snippets for sub-section snippets.
    """
    if not text:
        return ""
    text_lower = text.lower()
    HEADING_ZONE = 250

    def _find(kw_l: str, start: int = 0) -> int:
        """Substring search with prefix-stem fallback for English verb suffixes.
        FTS query routing stems via PostgreSQL websearch_to_tsquery, but snippet
        anchoring uses literal substring matching; user-typed 'nullifies' must
        match matn's 'Nullify'. If full keyword misses, try the first 5 chars
        as a prefix stem (matches plurals, verb forms, hyphen-joined variants)."""
        idx = text_lower.find(kw_l, start)
        if idx >= 0:
            return idx
        if len(kw_l) >= 6:
            return text_lower.find(kw_l[:5], start)
        return -1

    best_idx = None
    for kw in keywords:
        kw_l = kw.lower()
        idx = _find(kw_l)
        if idx < 0:
            continue
        if idx < HEADING_ZONE:
            # Look for a later occurrence past the heading zone.
            later = _find(kw_l, HEADING_ZONE)
            if later >= 0:
                best_idx = later
                break
            # Otherwise this keyword is only in the heading; try next priority kw.
            continue
        best_idx = idx
        break

    if best_idx is None:
        # No keyword matched outside heading zone; fall back to first match
        # anywhere (even if in heading) rather than empty snippet.
        for kw in keywords:
            idx = _find(kw.lower())
            if idx >= 0:
                best_idx = idx
                break

    if best_idx is None:
        return text[:before + after]

    start = max(0, best_idx - before)
    end = min(len(text), best_idx + after)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


# --- Hadith collection aliases (built once at module load) ---
# Maps lowercase alias strings → collection_id UUID.
# Longest-match-wins is enforced in match_hadith_collection_alias().
HADITH_COLLECTION_ALIASES: dict = {
    # Sahih al-Bukhari
    "sahih al-bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    "sahih bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    "al-bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    "al bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    "imam bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    "bukhari": "8ecef668-0597-473b-a812-63b2d8c89dc6",
    # Sahih Muslim
    "sahih al-muslim": "0dd871af-7513-46c0-a5a1-5f1508a52a8c",
    "sahih muslim": "0dd871af-7513-46c0-a5a1-5f1508a52a8c",
    "imam muslim": "0dd871af-7513-46c0-a5a1-5f1508a52a8c",
    "al-muslim": "0dd871af-7513-46c0-a5a1-5f1508a52a8c",
    "muslim": "0dd871af-7513-46c0-a5a1-5f1508a52a8c",
    # Sunan Abi Dawud
    "sunan abu dawud": "7f4503c4-71db-4f78-9ba4-b2fc95fecd06",
    "sunan abu dawood": "7f4503c4-71db-4f78-9ba4-b2fc95fecd06",
    "abu dawud": "7f4503c4-71db-4f78-9ba4-b2fc95fecd06",
    "abu dawood": "7f4503c4-71db-4f78-9ba4-b2fc95fecd06",
    "abudawud": "7f4503c4-71db-4f78-9ba4-b2fc95fecd06",
    # Jami' at-Tirmidhi
    "jami at-tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    "jami al-tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    "sunan tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    "at-tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    "al-tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    "tirmidhi": "837b319e-1a11-4794-8405-ab37712c97b2",
    # Sunan an-Nasa'i
    "sunan an-nasai": "3ee87efc-1162-4431-b211-6f1c42c29353",
    "sunan nasai": "3ee87efc-1162-4431-b211-6f1c42c29353",
    "an-nasai": "3ee87efc-1162-4431-b211-6f1c42c29353",
    "nasai": "3ee87efc-1162-4431-b211-6f1c42c29353",
    # Sunan Ibn Majah
    "sunan ibn majah": "e51000dc-5c1b-4ef0-8c03-849f9167e10e",
    "ibn majah": "e51000dc-5c1b-4ef0-8c03-849f9167e10e",
    "ibnmajah": "e51000dc-5c1b-4ef0-8c03-849f9167e10e",
    # Nawawi's 40 Hadith
    "nawawi 40": "84c65102-f2ac-423d-87aa-5483e45c3927",
    "40 hadith nawawi": "84c65102-f2ac-423d-87aa-5483e45c3927",
    "40 hadith": "84c65102-f2ac-423d-87aa-5483e45c3927",
    "arbain nawawi": "84c65102-f2ac-423d-87aa-5483e45c3927",
    "arbain": "84c65102-f2ac-423d-87aa-5483e45c3927",
    "nawawi40": "84c65102-f2ac-423d-87aa-5483e45c3927",
    # Riyad al-Salihin
    "riyad al-salihin": "2d75d361-b333-4d45-b0f7-c34779f51fba",
    "riyadussalihin": "2d75d361-b333-4d45-b0f7-c34779f51fba",
    "riyad us salihin": "2d75d361-b333-4d45-b0f7-c34779f51fba",
    "riyad al salihin": "2d75d361-b333-4d45-b0f7-c34779f51fba",
    "gardens of the righteous": "2d75d361-b333-4d45-b0f7-c34779f51fba",
    "riyadh al-salihin": "2d75d361-b333-4d45-b0f7-c34779f51fba",
}


def match_hadith_collection_alias(text: str):
    """
    Scan *text* for any known hadith collection alias.
    Returns collection_id (UUID str) if found, else None.
    Longest match wins to avoid short aliases shadowing longer ones.
    """
    t = text.lower()
    best_len = 0
    best_id = None
    for alias, coll_id in HADITH_COLLECTION_ALIASES.items():
        if alias in t and len(alias) > best_len:
            best_len = len(alias)
            best_id = coll_id
    return best_id


# --- Sahaba narrator detection (built once at module load) ---
# Maps lowercase alias → canonical narrator fragment used in ILIKE filter.
SAHABA_NARRATORS: list = [
    # (alias, canonical_fragment)  — longest aliases first for longest-match
    ("al-nawwas ibn sam'an", "Nawwas"),
    ("al-nawwas ibn saman", "Nawwas"),
    ("al-nawwas ibn sam'an", "Nawwas"),
    ("al-nawwas", "Nawwas"),
    ("nawwas ibn sam'an", "Nawwas"),
    ("nawwas ibn saman", "Nawwas"),
    ("nawwas", "Nawwas"),
    ("abu sa'id al-khudri", "Abu Sa"),
    ("abu sa'id al-khudri", "Abu Sa"),
    ("abu sa'id", "Abu Sa"),
    ("abu said al-khudri", "Abu Sa"),
    ("abu said", "Abu Sa"),
    ("abu hurayrah", "Abu Hurairah"),
    ("abu hurayra", "Abu Hurairah"),
    ("abu hurairah", "Abu Hurairah"),
    ("abu huraira", "Abu Hurairah"),
    ("sayyidah aisha", "Aisha"),
    ("a'isha", "Aisha"),
    ("aisha", "Aisha"),
    ("abdullah ibn abbas", "Ibn Abbas"),
    ("ibn 'abbas", "Ibn Abbas"),
    ("ibn abbas", "Ibn Abbas"),
    ("abdullah ibn umar", "Ibn Umar"),
    ("ibn umar", "Ibn Umar"),
    ("anas ibn malik", "Anas"),
    ("anas", "Anas"),
    ("jabir ibn abdullah", "Jabir"),
    ("jabir", "Jabir"),
    ("sayyiduna abu bakr", "Abu Bakr"),
    ("abu bakr", "Abu Bakr"),
    ("umar ibn al-khattab", "Umar"),
    ("umar ibn al-khattab", "Umar"),
    ("umar", "Umar"),
    ("uthman ibn affan", "Uthman"),
    ("uthman", "Uthman"),
    ("ali ibn abi talib", "Ali"),
    ("ali", "Ali"),
]


def match_sahaba_narrator(text: str):
    """
    Scan *text* for any known sahaba narrator alias.
    Returns canonical narrator fragment (str) if found, else None.
    First matching alias (longest listed first) wins.
    """
    t = text.lower()
    for alias, canonical in SAHABA_NARRATORS:
        if alias in t:
            return canonical
    return None


# --- Surah alias lookup (built once at module load) ---
# Maps normalised alias strings → surah number.
# Normalisation: lowercase, strip "al-" / "al " prefix, remove hyphens + apostrophes.
def _build_surah_aliases() -> dict:
    """Build alias → surah_number mapping from SURAH_NAMES at import time."""
    aliases: dict = {}

    def _norm(s: str) -> str:
        s = s.lower().strip()
        for prefix in ("al-", "al ", "an-", "an ", "at-", "at ", "as-", "as ",
                       "az-", "az ", "ad-", "ad ", "ar-", "ar ", "ash-", "ash "):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        return s.replace("-", "").replace("'", "").replace("'", "").replace("ā", "a").replace("ī", "i").replace("ū", "u").replace("ḥ", "h").replace("ṭ", "t").replace("ā", "a")

    for num, name in SURAH_NAMES.items():
        # Full name (lowercased)
        full = name.lower()
        aliases[full] = num
        # Without "Al-" etc.
        stripped = _norm(name)
        if stripped:
            aliases[stripped] = num
        # Without spaces
        nospace = stripped.replace(" ", "")
        if nospace:
            aliases[nospace] = num

    # Hand-coded transliteration variants for frequently-asked surahs
    extra: dict = {
        # Al-Fatihah — incl. the 'e'-vowel transliteration ("fateha"), which is
        # one of the most common spellings and was a live retrieval miss
        # (mizan quality review 2026-07-05: "What does al fateha mean?" fell
        # through to keyword FTS -> unrelated surahs, because only the 'i'-vowel
        # spellings were aliased). The most-recited surah must resolve robustly.
        "fatiha": 1, "fatihah": 1, "al fatiha": 1, "al fatihah": 1,
        "al-fatiha": 1, "al-fatihah": 1, "opening": 1,
        "fateha": 1, "fatehah": 1, "al fateha": 1, "al-fateha": 1,
        "faatiha": 1, "faatihah": 1, "fatiah": 1, "fatihatul kitab": 1,
        # Al-Baqarah
        "baqara": 2, "baqarah": 2, "al baqara": 2, "al baqarah": 2,
        "al-baqara": 2, "al-baqarah": 2, "cow": 2,
        # Aal-Imran
        "imran": 3, "aal imran": 3, "ali imran": 3,
        # An-Nisa
        "nisa": 4, "nisa": 4, "an nisa": 4, "women": 4,
        # Al-Ma'idah
        "maidah": 5, "al maidah": 5, "maida": 5, "table": 5,
        # Al-An'am
        "anam": 6, "al anam": 6, "cattle": 6,
        # Al-A'raf
        "araf": 7, "al araf": 7, "aaraf": 7, "al aaraf": 7,
        "al-araf": 7, "a'raf": 7, "heights": 7,
        # Al-Anfal
        "anfal": 8, "al anfal": 8, "spoils": 8,
        # At-Tawbah
        "tawbah": 9, "tawba": 9, "at tawbah": 9, "repentance": 9,
        # Yunus
        "yunus": 10, "jonah": 10,
        # Hud
        "hud": 11,
        # Yusuf
        "yusuf": 12, "joseph": 12,
        # Al-Kahf
        "kahf": 18, "al kahf": 18, "al-kahf": 18, "cave": 18,
        # Maryam
        "maryam": 19, "mary": 19,
        # Ta-Ha
        "taha": 20, "ta ha": 20,
        # Ya-Sin
        "yasin": 36, "ya sin": 36, "yaseen": 36,
        # Ar-Rahman
        "rahman": 55, "ar rahman": 55, "the merciful": 55,
        # Al-Waqi'ah
        "waqiah": 56, "al waqiah": 56, "event": 56,
        # Al-Mulk
        "mulk": 67, "al mulk": 67, "sovereignty": 67,
        # Al-Ikhlas
        "ikhlas": 112, "al ikhlas": 112, "al-ikhlas": 112, "sincerity": 112,
        "purity": 112,
        # Al-Falaq
        "falaq": 113, "al falaq": 113, "daybreak": 113,
        # An-Nas
        "nas": 114, "an nas": 114, "mankind": 114,
        # Nuh
        "nuh": 71, "noah": 71,
        # Al-Jinn
        "jinn": 72, "al jinn": 72,
        # Al-Qiyamah
        "qiyamah": 75, "resurrection": 75,
        # Al-Insan
        "insan": 76, "human": 76,
        # Al-Fajr
        "fajr": 89, "dawn": 89,
        # Al-Alaq
        "alaq": 96, "clot": 96,
        # Al-Qadr
        "qadr": 97, "power": 97, "decree": 97,
        # Az-Zalzalah
        "zalzalah": 99, "earthquake": 99,
        # Al-Asr
        "asr": 103, "time": 103,
        # Al-Kawthar
        "kawthar": 108, "abundance": 108,
        # Al-Kafirun
        "kafirun": 109, "disbelievers": 109,
        # An-Nasr
        "nasr": 110, "help": 110,
        # Ash-Sharh / Al-Inshirah (surah 94). SURAH_NAMES holds only the name
        # "Ash-Sharh", so the surah's SECOND canonical name "Al-Inshirah" and
        # the Malay/Indonesian spelling "insyirah" are not derivable and must be
        # explicit. (operator-reported tafsir miss 2026-06-18, msgs #2613/#2615 —
        # "tafsir of last 2 ayat of al insyirah" resolved to nothing.)
        "inshirah": 94, "al inshirah": 94, "insyirah": 94, "al insyirah": 94,
        "alam nashrah": 94, "nashrah": 94,
    }
    aliases.update(extra)
    return aliases

# Built once at module load — O(1) per alias lookup thereafter
SURAH_ALIASES: dict = _build_surah_aliases()

# Special verse shortcuts
SPECIAL_VERSES: dict = {
    "ayat al kursi": (2, 255),
    "ayat al-kursi": (2, 255),
    "ayatul kursi": (2, 255),
    "ayat ul kursi": (2, 255),
    "throne verse": (2, 255),
    "ayat kursi": (2, 255),
}


def match_surah_alias(text: str):
    """
    Scan *text* for any known surah alias.
    Returns surah_number (int) if found, else None.
    Longest match wins to avoid short aliases shadowing longer ones.
    """
    t = text.lower()
    # Remove punctuation that would block matching
    import re as _re
    t_clean = _re.sub(r"['’‘]", "", t)

    def _word_hit(needle: str) -> bool:
        # Word-boundary match, NOT bare substring. A surah alias must be a whole
        # token — otherwise a short name fragment matches inside an unrelated word
        # ('nisa' in 'nisab', 'event' in 'prevent'), wrongly injecting that surah's
        # tafsir/info into a fiqh answer (op#5975 retrieval-eval false hits).
        pat = r'(?<!\w)' + _re.escape(needle) + r'(?!\w)'
        return bool(_re.search(pat, t_clean) or _re.search(pat, t))

    # Check special verse shortcuts first
    for key, val in SPECIAL_VERSES.items():
        if _word_hit(key):
            return val  # returns tuple (surah, ayah)

    best_len = 0
    best_num = None
    for alias, num in SURAH_ALIASES.items():
        if _word_hit(alias):
            if len(alias) > best_len:
                best_len = len(alias)
                best_num = num
    return best_num

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
        # Hydrate last_query + answer_level from the durable per-chat store so a
        # level-button tap re-answers the prior question even after a restart or
        # TTL prune. last_context/history are intentionally NOT persisted: the
        # follow-up path (is_followup) guards on last_context being non-empty, so
        # a hydrated last_query with empty last_context safely falls through to a
        # fresh context gather rather than reusing stale/empty context.
        persisted = load_chat_state(chat_id) or {}
        sessions[chat_id] = {
            "history": [],
            "last_query": persisted.get("last_query", ""),
            "last_context": "",
            "last_topics": [],
            "last_active": now,
            # layman | seeker | scholar (default seeker), sticky across restarts
            "answer_level": persisted.get("answer_level", "seeker"),
            "level_responses": {},          # level → telegram message_id (for the
                                            # last_query at that level; cleared when
                                            # last_query changes; lets callback handler
                                            # reply-point to existing answers instead
                                            # of regenerating). Not persisted —
                                            # regenerates after a restart.
        }
    # Backfill new fields on pre-existing sessions (session dict survives bot
    # restarts only in-process — fresh sessions get the default; old sessions
    # mid-conversation when this feature shipped get backfilled).
    sessions[chat_id].setdefault("answer_level", "seeker")
    sessions[chat_id].setdefault("level_responses", {})
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
    words = t.split()
    for pattern in FOLLOWUP_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            return True
    # A message that names a specific verse / surah (or gives an explicit S:A
    # reference) is a FRESH keyed query — it carries its own retrieval target and
    # must never reuse the previous turn's context. Without this guard, generic
    # corpus words in the prior query's last_topics ("ayat", "tafsir", ...)
    # produced spurious ≥2-overlap follow-up hits, so e.g. "ayat kursi tafsir"
    # after "1000 dinar ayat tafsir" reused stale context and never retrieved the
    # 2:255 tafsir (operator op#5975). The explicit-continuation FOLLOWUP_PATTERNS
    # above are checked first, so "tell me more about ayat al-kursi" is still a
    # follow-up; only a bare verse-naming query is forced fresh here.
    if match_surah_alias(text) is not None or re.search(r'\b\d{1,3}\s*:\s*\d{1,3}\b', t):
        return False
    # Short messages with pronouns
    if len(words) <= 6:
        pronouns = {"that", "this", "it", "those", "these", "the same"}
        if any(p in words for p in pronouns):
            return True
    # Fix 4a (tightened 2026-05-31 — was auto-marking ANY ≤8-word message
    # as follow-up when history existed, which silently reused stale context
    # for genuinely new questions like "can we dye our hair black?" after
    # a qurban question). Now requires either an explicit "more"/"continue"
    # signal OR strong topic-word overlap with last_topics (≥2 overlaps
    # AND no introduced topic-shift words).
    if (len(words) <= 8
            and session.get("history")
            and session.get("last_topics")):
        # Explicit continuation signals
        if any(w in words for w in ("more", "continue", "also", "elaborate", "expand")):
            return True
        # Topic-word overlap (must be strong — single word like "hair" doesn't
        # qualify if the rest of the message introduces new content words)
        last_topic_set = set(session["last_topics"])
        content_words = [w.strip(".,;:!?'\"") for w in words
                         if len(w) > 3 and w.lower() not in STOP_WORDS]
        overlap = [w for w in content_words if w.lower() in last_topic_set]
        new_content = [w for w in content_words if w.lower() not in last_topic_set]
        if len(overlap) >= 2 and len(new_content) <= 1:
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


def supabase_patch(path, filters, body):
    """PATCH a Supabase REST resource. Returns True on success, False on error.
    Fail-soft: callers ack the user honestly rather than crashing the loop."""
    url = SUPABASE_URL + "/rest/v1/" + path
    if filters:
        url += "?" + urllib.parse.urlencode(filters, safe=":,.()")
    key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH", headers={
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"  -> supabase_patch failed: {type(e).__name__}: {e}")
        return False


# --- Scholar-review verification loop (#2746) -------------------------------
def toggle_review_flag(interaction_id, flagger_hash):
    """Toggle flagged_for_review on a mizan_interactions row.

    Returns the NEW bool state (True=now flagged, False=now unflagged), or None
    on error / missing columns (pre-migration) — caller acks honestly, never a
    false success. flagged_by / flagged_at capture who flagged + when; cleared
    on unflag.
    """
    try:
        rows = supabase_get("mizan_interactions", {
            "id": f"eq.{interaction_id}",
            "select": "flagged_for_review",
            "limit": "1",
        })
    except Exception as e:
        print(f"  -> flag read failed (columns applied yet?): {type(e).__name__}: {e}")
        return None
    if not rows:
        return None
    new_state = not bool(rows[0].get("flagged_for_review"))
    patch = {
        "flagged_for_review": new_state,
        "flagged_by": flagger_hash if new_state else None,
        "flagged_at": datetime.datetime.now(datetime.timezone.utc).isoformat() if new_state else None,
    }
    ok = supabase_patch("mizan_interactions", {"id": f"eq.{interaction_id}"}, patch)
    return new_state if ok else None


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


def lookup_surah_tafsir(surah_number: int, max_ayat: int = 7) -> dict:
    """Pull tafsir_entries for the first max_ayat ayat of surah_number.
    Returns a dict compatible with the existing context-block format."""
    ayat_rows = supabase_get("ayat", {
        "surah_number": f"eq.{surah_number}",
        "select": "id,surah_number,ayah_number,arabic_text,english_translation",
        "order": "ayah_number",
        "limit": str(max_ayat),
    })
    out = []
    for a in ayat_rows:
        tafsir = supabase_get("tafsir_entries", {
            "ayah_id": f"eq.{a['id']}",
            "select": "scholar_name,source_work,english_text,output_tier",
            "order": "scholar_name",
        })
        # Filter untranslated Arabic-only placeholders
        tafsir = [t for t in tafsir
                  if not (t.get("english_text") or "").startswith("[Arabic tafsir")]
        out.append({
            "surah": a["surah_number"],
            "ayah": a["ayah_number"],
            "surah_name": SURAH_NAMES.get(a["surah_number"], f"Surah {a['surah_number']}"),
            "arabic": a["arabic_text"],
            "translation": a["english_translation"],
            "tafsir": tafsir,
        })
    return {"surah_number": surah_number, "ayat": out}


def _surah_max_ayah(surah_number: int):
    """Highest ayah number in a surah — used to resolve 'last N ayat'.
    Returns int or None on miss/error."""
    try:
        rows = supabase_get("ayat", {
            "surah_number": f"eq.{surah_number}",
            "select": "ayah_number",
            "order": "ayah_number.desc",
            "limit": "1",
        })
        return rows[0]["ayah_number"] if rows else None
    except Exception:
        return None


def extract_ayah_numbers(q: str, surah_number: int):
    """Extract explicit ayah number(s) from a NATURAL-LANGUAGE verse reference
    that the colon `S:A` regex doesn't catch.

    Handles: "ayah 7", "ayah 7 and 8", "verses 7-8", "ayat 7 to 9",
    "last 2 ayat", "first 3 verses". Returns a sorted list of ints (capped at 8),
    or [] when no explicit ayah is named.

    Rationale (operator tafsir miss #2613/#2615): a verse reference is a
    STRUCTURED KEY, not a semantic concept. Resolving it here routes the query
    to a keyed lookup_verse() instead of letting it fall through to keyword FTS /
    semantic similarity, neither of which can retrieve a verse by its number
    (measured cosine ~0.20-0.28 even for the exact ayah text — all wrong ayat).
    """
    import re
    # "last N ayat" / "first N verses"
    m = re.search(r'\b(last|final|first)\s+(\d{1,3})\s+'
                  r'(?:ayah|ayat|ayahs|aayah|aayat|verse|verses)\b', q)
    if m:
        n = int(m.group(2))
        if n < 1 or n > 8:
            return []
        if m.group(1) == 'first':
            return list(range(1, n + 1))
        mx = _surah_max_ayah(surah_number)
        if mx:
            return list(range(max(1, mx - n + 1), mx + 1))
        return []
    # explicit number(s) after an ayah/verse keyword: "ayah 7", "ayah 7 and 8",
    # "verses 7-8", "ayat 7 to 9"
    m = re.search(r'\b(?:ayah|ayat|ayahs|aayah|aayat|verse|verses|v)\.?\s*'
                  r'(\d{1,3})(?:\s*(?:and|&|,|-|–|—|to|through|thru)\s*(\d{1,3}))?', q)
    if m:
        a = int(m.group(1))
        if m.group(2):
            b = int(m.group(2))
            lo, hi = min(a, b), max(a, b)
            if hi - lo <= 8:
                return list(range(lo, hi + 1))
            return [lo, hi]
        return [a]
    return []


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


def search_tafsir(keywords, limit=5):
    """Full-text search on tafsir_entries.english_text via search_tafsir_fts RPC.
    Returns up to `limit` rows (capped at 10) shaped for the Claude context block:
    {surah, ayah, arabic, english_translation, scholar, source, english_text, tier}.
    Skips rows whose english_text starts with '[Arabic tafsir' (untranslated placeholder).
    """
    try:
        rows = supabase_rpc("search_tafsir_fts", {"query": keywords, "lim": min(limit, 10)})
    except Exception:
        return {"results": []}
    if not rows:
        return {"results": []}

    results = []
    for r in rows:
        passage = r.get("english_text") or ""
        if passage.startswith("[Arabic tafsir"):
            continue
        results.append({
            "ayah_id": r["ayah_id"],   # F-2: thread retrieval ID through to audit row
            "surah": r["surah_number"],
            "ayah": r["ayah_number"],
            "arabic": r["arabic_text"],
            "english_translation": r["english_translation"],
            "scholar": r["scholar_name"],
            "source": r["source_work"],
            "english_text": passage,
            "tier": r["output_tier"],
        })
    return {"results": results}


# --- FTS relevance floor (coverage-based) -------------------------------------
# ts_rank is NOT usable as a cross-query relevance floor: measured live (mizan
# review #6489), a legitimate "gratitude" tafsir hit (ts_rank 0.061) ranks BELOW
# an off-topic "prevent"->"prevent death" noise hit (0.087) — ts_rank scales with
# term-frequency/doc-length, not topicality. The OR-joined keyword FTS query
# therefore surfaces a passage that hit a single GENERIC word while the
# distinctive query terms matched nothing (e.g. "do eyelash extensions prevent
# wudhu" -> the Al-'Imran 3:168 "prevent death" ayah). COVERAGE is separable:
# keep an FTS hit only if the matched text contains a DISTINCTIVE (non-generic)
# query term, or >=2 query terms. Applied to FTS rows only — semantic hits are
# topical by embedding and carry their own cosine gate.
_FTS_GENERIC = {
    "prevent", "prevents", "prevented", "make", "makes", "made", "making",
    "give", "gives", "given", "giving", "take", "takes", "taken", "taking",
    "use", "uses", "used", "using", "get", "gets", "got", "getting", "keep",
    "keeps", "kept", "put", "puts", "come", "comes", "came", "want", "wants",
    "wanted", "need", "needs", "needed", "help", "helps", "tell", "tells",
    "told", "ask", "asks", "asked", "say", "says", "said", "know", "knows",
    "known", "thing", "things", "way", "ways", "time", "times", "people",
    "person", "find", "finds", "found", "show", "shows", "showed", "work",
    "works", "good", "bad", "many", "much", "more", "most", "some", "between",
}


def _fts_topical(words, text) -> bool:
    """True if an FTS-matched *text* genuinely covers the query — it contains a
    distinctive (non-generic) query term, or >=2 query terms. Prefix match (5
    chars) absorbs FTS stemming (extensions->extension, praying->pray). Returns
    True when there is nothing to check against, so it never over-filters."""
    tl = (text or "").lower()
    content = [w for w in (words or []) if len(w) >= 3]
    if not content:
        return True
    distinctive = [w for w in content if w not in _FTS_GENERIC]
    if any(w[:5] in tl for w in distinctive):
        return True
    return sum(1 for w in content if w[:5] in tl) >= 2


def _tafsir_merge_key(scholar, surah, ayah, text=""):
    """Cross-path dedup key for tafsir hits (FTS+semantic union).

    The two paths describe the SAME tafsir_entries corpus but carry DISJOINT
    identifiers: FTS rows have scholar/surah/ayah and no entry id; semantic rows
    have tafsir_entry_id + ayah_id and no surah/ayah numbers. The original key
    (tafsir_entry_id OR (scholar, surah, ayah)) keyed the two paths in different
    spaces, so the same passage surfaced by BOTH appeared TWICE (once as "Surah
    (unknown):?" from the semantic side).

    The natural unique key is (scholar, surah, ayah) — the corpus has exactly one
    tafsir_entries row per (ayah_id, scholar) — and now that semantic ayah_id is
    resolved to surah:ayah before the merge (see _resolve_ayah_ids), BOTH paths
    can use it. This dedups the same passage across paths AND never over-merges
    distinct passages (an english_text-prefix key would have wrongly collapsed two
    different ayat that share a scholar's boilerplate opening, e.g. Ibn Kathir's
    "…which was revealed in Makkah…"). Falls back to scholar+text-prefix only when
    the ayah coords are unavailable (rare: ayah_id resolution failed)."""
    scholar = str(scholar or "").strip().lower()
    if surah is not None and ayah is not None:
        return (scholar, str(surah), str(ayah))
    return (scholar, " ".join(str(text or "").split())[:120].lower())


def _resolve_ayah_ids(ayah_ids):
    """Map ayah_id (uuid) → (surah_number, ayah_number) via ONE batched lookup.

    Semantic tafsir hits carry ayah_id but not surah/ayah numbers, so a
    semantic-ONLY hit rendered as "Surah (unknown) : Ayah ?" — un-citable, and
    it's exactly the paraphrased/cross-lingual queries semantic uniquely catches
    (ayat al-kursi, al-rahman) that land there. Resolving lets them be cited.
    Read-only; returns {} on any error so the caller falls back to unknown."""
    ids = [i for i in dict.fromkeys(ayah_ids) if i]
    if not ids:
        return {}
    try:
        rows = supabase_get("ayat", {
            "id": f"in.({','.join(ids)})",
            "select": "id,surah_number,ayah_number",
        })
        return {r["id"]: (r["surah_number"], r["ayah_number"]) for r in rows}
    except Exception as e:
        print(f"  ayah_id resolve failed (non-fatal): {e}")
        return {}


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
    # Udhiyya hair/nails Sunnah (Sahih Muslim 5119/5120, Abu Dawud 2791,
    # Riyad al-Salihin 1706) — Umm Salama hadith. Triggers when user asks
    # about the qurban-sponsor refraining from cutting hair/nails during
    # Dhul-Hijjah. Surfaces the authoritative hadith proactively.
    frozenset(["qurban", "hair"]): ["sacrifice", "udhiyya", "hair", "nails", "Dhul-Hijjah", "intends to sacrifice"],
    frozenset(["qurban", "nails"]): ["sacrifice", "udhiyya", "hair", "nails", "Dhul-Hijjah", "intends to sacrifice"],
    frozenset(["sacrifice", "hair"]): ["sacrifice", "udhiyya", "hair", "nails", "intends to sacrifice"],
    frozenset(["udhiyya", "hair"]): ["sacrifice", "udhiyya", "hair", "nails", "intends to sacrifice"],
    # After-meal du'ā (Abu Dawud 4023 — Mu'adh ibn Anas — "If anyone eats
    # food and then says: 'Praise be to Allah Who has fed me with this
    # food and provided me'..."). Triggers when user asks about post-meal
    # supplication. Bridge phrases the hadith uses ("fed me", "provided
    # me", "praise be to Allah", "food") to the user's phrasing.
    # Added 2026-06-05 after live-test miss surfaced this exact gap.
    frozenset(["supplication", "eating"]): ["praise be to Allah", "fed me", "provided me", "food", "Allah Who has fed"],
    frozenset(["supplication", "meal"]): ["praise be to Allah", "fed me", "provided me", "food", "Allah Who has fed"],
    frozenset(["supplication", "food"]): ["praise be to Allah", "fed me", "provided me", "food", "Allah Who has fed"],
    frozenset(["dua", "eating"]): ["praise be to Allah", "fed me", "provided me", "food"],
    frozenset(["dua", "meal"]): ["praise be to Allah", "fed me", "provided me", "food"],
    frozenset(["dua", "food"]): ["praise be to Allah", "fed me", "provided me", "food"],
    # Combining prayers (jam' al-salatayn) — Sunan an-Nasa'i 597, Sahih
    # Muslim 705 (Ibn 'Abbas, Mu'adh ibn Jabal). User asks about
    # jam' taqdīm / jam' taʾkhīr — the corpus has the hadiths under
    # "combined his prayer while traveling" phrasing which the user's
    # transliterated jama doesn't surface against. Bridge the gap.
    # Added 2026-06-05 after the "jama' takhir" live-test false-friended
    # against "gather your guile" tafsir and tartib-within-a-prayer matn.
    frozenset(["jama", "prayer"]): ["combined", "combine", "two prayers", "traveling", "Zuhr Asr", "Maghrib Isha"],
    frozenset(["jama", "salah"]): ["combined", "combine", "two prayers", "traveling"],
    frozenset(["jama", "takhir"]): ["combined", "delayed", "two prayers", "traveling"],
    frozenset(["jama", "taqdim"]): ["combined", "advance", "two prayers", "traveling"],
    frozenset(["combining", "prayers"]): ["combined", "combine", "two prayers", "traveling"],
    frozenset(["combine", "prayers"]): ["combined", "two prayers", "traveling", "Zuhr Asr"],
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
    # Sacrifice / Udhiyya family — added 2026-06-01. Hadith FTS won't bridge
    # qurban (Persian/Malay loanword) → udhiyya/sacrifice without an explicit
    # synonym hop. Mirrors the expansion already in fiqh_semantic.QUERY_EXPANSIONS.
    "qurban": ["sacrifice", "udhiyya", "slaughter", "hady", "offering"],
    "qurbani": ["sacrifice", "udhiyya", "slaughter", "hady"],
    "korban": ["sacrifice", "udhiyya", "slaughter"],
    "udhiyya": ["sacrifice", "slaughter", "udhiyah"],
    "udhiyah": ["sacrifice", "slaughter", "udhiyya"],
    "adahi": ["sacrifices", "udhiyya"],
    "dhabh": ["slaughter", "slaughtering", "slaughtered"],
    "dhabihah": ["slaughtered animal", "sacrifice"],
    "aqiqah": ["birth sacrifice", "newborn sacrifice"],
    # Combining prayers (jam'/jamʿ + taqdīm/taʾkhīr) — see also CONCEPT_MAP
    # entries above. Without these individual-word expansions, "jama"
    # surfaces against gather/assembly (ج-م-ع root) tafsir false-friends.
    # Added 2026-06-05.
    "jama": ["combine", "combined", "combining", "two prayers"],
    "jam": ["combine", "combined", "combining", "two prayers"],
    "takhir": ["delayed", "later prayer"],
    "taqdim": ["advance", "earlier prayer"],
    # Sujūd al-sahw — added 2026-06-11. FTS fallback for the prostration of
    # forgetfulness; mirrors fiqh_semantic.QUERY_EXPANSIONS. Without the hop
    # "sahwi" misses the "sajdah sahw" / abʿāḍ enumeration in the matn.
    "sahw": ["sajdah sahw", "prostration of forgetfulness", "abʿaḍ", "omitted sunnah", "tashahhud"],
    "sahwi": ["sajdah sahw", "prostration of forgetfulness", "abʿaḍ", "omitted sunnah", "tashahhud"],
    "sahwa": ["sajdah sahw", "prostration of forgetfulness", "abʿaḍ", "omitted sunnah"],
    "sahu": ["sajdah sahw", "prostration of forgetfulness", "abʿaḍ", "omitted sunnah"],
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


def _enrich_hadith_rows(rows):
    """Fetch collection names for a list of hadith rows that still carry collection_id.
    Mutates rows in-place; returns the same list."""
    if not rows:
        return rows
    col_ids = list({r["collection_id"] for r in rows if r.get("collection_id")})
    if col_ids:
        cols = supabase_get("hadith_collections", {
            "id": f"in.({','.join(col_ids)})",
            "select": "id,name,full_name",
        })
        col_map = {c["id"]: c for c in cols}
        for r in rows:
            c = col_map.get(r.get("collection_id"), {})
            r["collection"] = c.get("name", "unknown")
            r["collection_full"] = c.get("full_name", "Unknown")
            if not r.get("grading") and r.get("collection") in ("bukhari", "muslim"):
                r["grading"] = "sahih"
            r["english_text"] = r.get("english_text", "")[:500]
            r.pop("collection_id", None)
    return rows


def search_hadith_fts_v2(keywords, limit=5, preferred_collection_id=None,
                          preferred_narrator=None, mode="auto"):
    """Enhanced hadith search with:
      - Gap A fix: optional collection filter (preferred_collection_id)
      - Gap B fix: AND-mode search (multi-ILIKE intersection) with OR fallback
      - Gap C fix: optional narrator ILIKE search merged with keyword results
      - mode='auto': try AND first, fall back to OR if AND returns < 3 hits.

    Uses PostgREST direct ILIKE queries (option b) — no migration needed.
    Falls back to existing search_hadith_fts OR semantics when AND yields < 3 results.
    """
    word_list = [w for w in (keywords if isinstance(keywords, list) else [keywords])
                 if len(w) > 2]

    all_results = []
    seen_ids = set()

    # --- AND-mode search (Gap B) ---
    # Build PostgREST params: select with multiple ilike filters in and() clause
    and_rows = []
    if word_list:
        select_cols = "hadith_number,english_text,grading,narrator,collection_id,id"
        and_params = {
            "select": select_cols,
            "limit": str(limit * 3),  # Over-fetch before dedup + cap
        }
        if preferred_collection_id:
            and_params["collection_id"] = f"eq.{preferred_collection_id}"
        if mode in ("auto", "and") and len(word_list) >= 2:
            # PostgREST and() filter: and=(english_text.ilike.%w1%,english_text.ilike.%w2%)
            and_clauses = ",".join(f"english_text.ilike.%25{urllib.parse.quote(w)}%25"
                                   for w in word_list[:4])
            try:
                url_path = f"hadiths?select={urllib.parse.quote(select_cols, safe=',')}&and=({and_clauses})"
                if preferred_collection_id:
                    url_path += f"&collection_id=eq.{preferred_collection_id}"
                url_path += f"&limit={limit * 3}"
                and_rows = supabase_get(url_path)
            except Exception as e:
                print(f"  AND search failed ({e}), will rely on OR fallback")
                and_rows = []

    # If AND gave enough results, use them; otherwise fall back to OR via existing FTS
    if len(and_rows) >= 3:
        _enrich_hadith_rows(and_rows)
        for r in and_rows:
            rid = r.get("id") or r.get("hadith_number", "")
            if rid not in seen_ids:
                seen_ids.add(rid)
                # Keep id in result for F-2 audit threading (previously popped to
                # hide from LLM context; UUID is fine for Claude to see).
                all_results.append(r)
    else:
        # OR fallback — use existing search_hadith_fts logic
        or_data = search_hadith_fts(keywords, limit=limit)
        for r in or_data.get("results", []):
            rid = r.get("hadith_number", "")
            if rid not in seen_ids:
                seen_ids.add(rid)
                all_results.append(r)

    # --- Narrator search (Gap C) ---
    if preferred_narrator and len(all_results) < limit:
        try:
            nar_rows = supabase_get("hadiths", {
                "narrator": f"ilike.%{preferred_narrator}%",
                "select": "hadith_number,english_text,grading,narrator,collection_id,id",
                "limit": str(limit),
            })
            if preferred_collection_id:
                nar_rows = [r for r in nar_rows
                            if r.get("collection_id") == preferred_collection_id]
            _enrich_hadith_rows(nar_rows)
            for r in nar_rows:
                rid = r.get("id") or r.get("hadith_number", "")
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    # Keep id (same rationale as AND-branch above)
                    all_results.append(r)
        except Exception as e:
            print(f"  Narrator search failed ({e})")

    # Cap and return
    return {"results": all_results[:limit]}


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

def gather_context(question, meta=None):
    """Analyze the question and gather relevant data from Quran + hadith.

    If `meta` (RetrievalMeta) is provided, retrieval row IDs are accumulated
    into it for F-2 audit-row threading. Backward-compatible: callers that
    don't pass meta still get a string return and the function behaves as
    before.
    """
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

    # Fix 2 — verse-range regex: catches "2:255", "7:117-120", "7:117 – 120"
    verse_match = re.search(r'(\d{1,3}):(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?', question)
    if verse_match:
        surah = int(verse_match.group(1))
        ayah_start = int(verse_match.group(2))
        ayah_end = int(verse_match.group(3)) if verse_match.group(3) else None

        if ayah_end is not None and ayah_end > ayah_start:
            # Range — cap at 8 ayat to prevent context explosion
            range_ayat = list(range(ayah_start, ayah_end + 1))
            if len(range_ayat) > 8:
                cap_note = f"(showing first 8 of {len(range_ayat)} ayat in range; ask for a specific ayah for full tafsir)"
                range_ayat = range_ayat[:8]
            else:
                cap_note = ""
            range_results = []
            for n in range_ayat:
                data = lookup_verse(surah, n)
                range_results.append(data)
            block = f"VERSE RANGE LOOKUP {surah}:{ayah_start}-{ayah_end}{' ' + cap_note if cap_note else ''}:\n{json.dumps(range_results, ensure_ascii=False, indent=2)}"
            context_parts.append(block)
        else:
            # Single verse (original behaviour)
            data = lookup_verse(surah, ayah_start)
            context_parts.append(f"VERSE LOOKUP {surah}:{ayah_start}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    # Hadith reference (e.g., "bukhari 1", "muslim 2345")
    hadith_match = re.search(r'(bukhari|muslim|abudawud|abu dawud|tirmidhi|nasai|ibnmajah|ibn majah)\s*(?:#?\s*)?(\d+)', q, re.IGNORECASE)
    if hadith_match:
        col_name = hadith_match.group(1).lower().replace(" ", "")
        hnum = hadith_match.group(2)
        data = lookup_hadith(col_name, hnum)
        context_parts.append(f"HADITH LOOKUP {col_name} #{hnum}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

    # Gap A/C fix: detect collection-name alias (without number) + sahaba narrator
    # These flags are used later in the FTS block to prefer a collection / narrator.
    preferred_collection_id = match_hadith_collection_alias(question)
    preferred_narrator = match_sahaba_narrator(question)

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

    # --- 3. Surah info + Fix 1 (alias-based) + Fix 3 (tafsir-of-X intent) ---

    # Fix 1: match_surah_alias runs BEFORE the legacy "surah \w+" regex
    resolved_surah = None
    resolved_via_special = False  # True when match_surah_alias returns a (surah, ayah) tuple

    alias_result = match_surah_alias(question)
    if isinstance(alias_result, tuple):
        # Special verse shortcut (e.g., ayat al-kursi → (2, 255))
        sv_surah, sv_ayah = alias_result
        data = lookup_verse(sv_surah, sv_ayah)
        context_parts.append(f"VERSE LOOKUP {sv_surah}:{sv_ayah} (special shortcut):\n{json.dumps(data, ensure_ascii=False, indent=2)}")
        resolved_surah = sv_surah
        resolved_via_special = True
    elif isinstance(alias_result, int):
        resolved_surah = alias_result

    # Numeric "surah 94" — the legacy regex below only matched the captured
    # token against surah NAME strings, so a numeric surah reference in natural
    # language ("Surah 94 ayah 7") never resolved and fell through to keyword
    # FTS (operator tafsir miss #2613/#2615). Resolve the number directly first.
    if resolved_surah is None:
        snum = re.search(r'\bsurah\s+(\d{1,3})\b', q)
        if snum and 1 <= int(snum.group(1)) <= 114:
            resolved_surah = int(snum.group(1))

    # Legacy "surah <name>" regex as fallback when alias didn't fire
    if resolved_surah is None:
        surah_match = re.search(r'surah\s+(\w+)', q, re.IGNORECASE)
        if surah_match:
            name = surah_match.group(1)
            for num, sname in SURAH_NAMES.items():
                if name.lower() in sname.lower():
                    resolved_surah = num
                    break

    if resolved_surah is not None and not resolved_via_special:
        # Fix 3: tafsir-of-X intent — when query expresses tafsir/commentary intent
        tafsir_intent = bool(re.search(
            r'\b(tafsir|tafseer|commentary|explanation|explain|meaning)\b', q, re.IGNORECASE
        ))
        surah_name = SURAH_NAMES.get(resolved_surah, f"Surah {resolved_surah}")
        # If specific ayat are named in natural language ("ayah 7 and 8",
        # "last 2 ayat"), do a KEYED lookup per ayah — this is the deterministic
        # path that retrieves the verse + its tafsir by number, instead of the
        # whole-surah dump (which only covers the first 7 ayat) or a fallthrough
        # to keyword/semantic search. (operator tafsir miss #2613/#2615)
        ayat_nums = extract_ayah_numbers(q, resolved_surah)
        if ayat_nums:
            for n in ayat_nums[:8]:
                data = lookup_verse(resolved_surah, n)
                context_parts.append(
                    f"VERSE LOOKUP {resolved_surah}:{n} ({surah_name}):\n"
                    + json.dumps(data, ensure_ascii=False, indent=2)
                )
        elif tafsir_intent:
            data = lookup_surah_tafsir(resolved_surah, max_ayat=7)
            context_parts.append(
                f"FULL SURAH TAFSIR for {surah_name} (Surah {resolved_surah}):\n"
                + json.dumps(data, ensure_ascii=False, indent=2)
            )
        else:
            # Fallback to plain surah info (original behaviour)
            data = get_surah_info(resolved_surah)
            context_parts.append(f"SURAH INFO:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

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
            # Relevance floor: drop OR-keyword noise (hits that matched only a
            # generic word; #6489). Coverage against the ayah translation.
            data["results"] = [r for r in data["results"]
                               if _fts_topical(words, r.get("english_translation") or r.get("translation") or "")]
            if data["results"]:
                context_parts.append(f"QURAN SEARCH:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
                # Get tafsir for top result
                if _ctx_size(context_parts) < MAX_CONTEXT:
                    r = data["results"][0]
                    vdata = lookup_verse(r["surah_number"], r["ayah_number"])
                    context_parts.append(f"TAFSIR for {r['surah_number']}:{r['ayah_number']}:\n{json.dumps(vdata, ensure_ascii=False, indent=2)}")

        # Tafsir FTS — surface scholar-attributed passages that matched the query
        # directly. Runs even when Quran FTS succeeded, because tafsir may add
        # signal (e.g., the matched passage addresses the query more directly
        # than the ayah translation).
        if _ctx_size(context_parts) < MAX_CONTEXT:
            tdata = search_tafsir(fts_query, limit=5)
            # Relevance floor: drop OR-keyword noise before the FTS+semantic
            # merge (the "prevent"->"prevent death" class; #6489). FTS rows only;
            # semantic hits below are topical by embedding.
            tdata["results"] = [r for r in tdata["results"]
                               if _fts_topical(words, r.get("english_text", ""))]

            # HYBRID supplement: semantic-rerank tafsir, same head-to-head
            # logic as hadith path. FTS retains the matched_passage F-2
            # anchor (audit row); semantic broadens retrieval to topical /
            # paraphrased queries FTS misses (ayat al-kursi, al-rahman,
            # musa Sinai — all 100% miss in FTS, 1/3 top-1 hits in
            # semantic-rerank).
            try:
                tsem = tafsir_semantic.search_semantic(question, limit=5)
            except Exception as e:
                print(f"  tafsir semantic failed (fallthrough to FTS): {e}")
                tsem = {"results": []}

            # Cross-path dedup on the natural key (scholar, surah, ayah). Resolve
            # semantic hits' ayah_id → surah:ayah FIRST so both paths share coords
            # (that both dedups across paths and makes semantic hits citable).
            sem_ayah_map = _resolve_ayah_ids([r.get("ayah_id") for r in tsem["results"]])
            merged = []
            seen_keys = set()
            for src, rows in (("fts", tdata["results"]), ("sem", tsem["results"])):
                for r in rows:
                    if src == "sem":
                        _sa = sem_ayah_map.get(r.get("ayah_id"))
                        surah, ayah = (_sa if _sa else (None, None))
                        scholar = r.get("scholar_name")
                    else:
                        surah, ayah = r.get("surah"), r.get("ayah")
                        scholar = r.get("scholar")
                    key = _tafsir_merge_key(scholar, surah, ayah, r.get("english_text"))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # Normalize semantic rows to the FTS shape so downstream
                    # rendering doesn't have to branch.
                    if src == "sem":
                        r = {
                            "ayah_id": r.get("ayah_id"),
                            "surah": surah if surah is not None else "(unknown)",
                            "ayah": ayah if ayah is not None else "?",
                            "arabic": r.get("arabic_text"),
                            "english_translation": None,
                            "scholar": scholar,
                            "source": r.get("source_work"),
                            "english_text": r.get("english_text", ""),
                            "tier": r.get("output_tier"),
                            "_retrieval_via": "sem",
                        }
                    else:
                        r = dict(r)
                        r["_retrieval_via"] = "fts"
                    merged.append(r)

            merged = merged[:10]
            if merged:
                if meta is not None:
                    meta.add_tafsir_hits(merged)
                entries = []
                for hit in merged:
                    via = hit.get("_retrieval_via", "fts")
                    entries.append(
                        f"Surah {hit.get('surah','?')} : Ayah {hit.get('ayah','?')}  [via {via}]\n"
                        f"Scholar: {hit.get('scholar','?')} ({hit.get('source','?')})\n"
                        f"Tier: {hit.get('tier','?')}\n"
                        f"Passage: {hit.get('english_text','')}"
                    )
                context_parts.append(
                    "TAFSIR MATCHED PASSAGES (scholar-attributed, FTS+semantic union):\n"
                    + "\n\n".join(entries)
                )

        # Hadith FTS (always search if question wants it, or as supplement)
        # Gap A/B/C fix: use search_hadith_fts_v2 with collection + narrator preferences
        # and AND-mode multi-keyword search (with OR fallback if AND < 3 results).
        # 2026-06-01: source-order words[:4] was dropping high-signal terms for
        # compound questions ("sponsoring qurban for my infant son ... cutting
        # nails and hair before slaughter" → words[:4]=['sponsoring','qurban',
        # 'infant','son'], missing 'hair'/'nails'/'cutting' that the CONCEPT_MAP
        # needs to fire). Sort by length descending as an information-content
        # proxy (longer words = rarer = higher signal), then take 8. This still
        # bounds OR-expansion size while preferring topical over grammatical tokens.
        has_hadith = any("HADITH" in p for p in context_parts)
        if not has_hadith and _ctx_size(context_parts) < MAX_CONTEXT:
            hlimit = 5 if wants_hadith else 3
            # Length-sorted, deduped, top-8 — for the FTS+SYNONYM path
            seen_w = set()
            ranked_words = []
            for w in sorted(words, key=len, reverse=True):
                if w not in seen_w:
                    seen_w.add(w)
                    ranked_words.append(w)

            # HYBRID: union of FTS+SYNONYM and semantic-rerank paths.
            # Per 14-query head-to-head test (2026-06-10, commit bb35a3f):
            #   FTS alone:           top-1=21%  top-3=43%  miss=8/14
            #   Semantic v3 (rerank): top-1=50%  top-3=71%  miss=4/14
            # The two paths fail on different queries, so the union
            # is strictly better than either alone:
            #   - FTS catches surface-token-precise queries semantic loses
            #     (e.g. "afdhal supplication after eating" → Abu Dawud
            #     #4023, semantic doesn't bridge "supplication" ↔
            #     "praise be to Allah who has fed me")
            #   - Semantic catches paraphrased / cross-lingual / topic
            #     queries FTS loses (Malay haid mushaf, tafsir, envy)
            # Dedupe key: (collection, hadith_number).
            fts_data = search_hadith_fts_v2(
                ranked_words[:8],
                limit=hlimit,
                preferred_collection_id=preferred_collection_id,
                preferred_narrator=preferred_narrator,
                mode="auto",
            )
            try:
                sem_data = hadith_semantic.search_semantic(question, limit=hlimit)
            except Exception as e:
                print(f"  hadith semantic failed (fallthrough to FTS): {e}")
                sem_data = {"results": []}

            # Merge: dedupe on (collection, hadith_number); preserve order
            # of FIRST occurrence (FTS first because its synonym-precision
            # wins on the cases where it's better; semantic supplements).
            # Mark which path(s) surfaced each hit for downstream debugging.
            merged = []
            seen_keys = set()
            for src, rows in (("fts", fts_data["results"]), ("sem", sem_data["results"])):
                for r in rows:
                    key = (str(r.get("collection") or "").lower(),
                           str(r.get("hadith_number") or ""))
                    if key in seen_keys:
                        # Already in merged from the other path — mark as both
                        for existing in merged:
                            existing_key = (str(existing.get("collection") or "").lower(),
                                            str(existing.get("hadith_number") or ""))
                            if existing_key == key:
                                existing.setdefault("_paths", set()).add(src)
                        continue
                    seen_keys.add(key)
                    r2 = dict(r)
                    r2["_paths"] = {src}
                    merged.append(r2)
            # Cap total — keep all union hits up to 2x limit (allows the
            # claude prompt to see both authoritative + supplementary)
            merged = merged[: max(hlimit * 2, 5)]

            if merged:
                if meta is not None:
                    meta.add_hadith_hits(merged)
                # Tag each hit's source path for visibility in the prompt
                for r in merged:
                    paths = sorted(r.pop("_paths", set()))
                    r["_retrieval_via"] = "+".join(paths) if len(paths) > 1 else paths[0]
                label = "HADITH SEARCH" if wants_hadith else "RELATED HADITHS"
                payload = {"results": merged}
                context_parts.append(f"{label}:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")

    # Shafi'i fiqh substrate — retrieve-only echo per C4 + INV-7 gate.
    # 2026-05-19: dropped match_fiqh_query() keyword gate. bge-m3 semantic
    # embedding handles language code-switching (rukun solat → Malay → Salah),
    # diacritic variance (nisab vs niṣāb), and synonym bridging natively.
    # Keyword gate was producing false-negatives on every non-English-Arabic-
    # transliteration query. Filtering at the rank threshold below now serves
    # as the relevance gate (chunks with rank<0.45 are likely off-topic).
    # No MAX_CONTEXT gate: rank threshold already filters noise, and the worst-
    # case addition (3 hits × 2500c = 7.5KB) is bounded and high-value when it
    # fires. Without this, fiqh-class queries with verbose tafsir/hadith
    # context (e.g., "what nullifies the fast", "awrah to read from mushaf")
    # were getting their fiqh retrieval blocked by an already-full budget.
    if True:
        # Phase 2 semantic-first per CAI-PROCESS-GLUE-AUDIT-MIZANBOT-001
        # hybrid ruling. FTS-fallback on encoder timeout / empty / unreachable.
        try:
            fiqh_data = fiqh_semantic.search_semantic(question, limit=8)
        except Exception:
            fiqh_data = {"results": []}
        # Stamp the semantic retrieval config onto the audit meta BEFORE the FTS
        # fallback below can reassign fiqh_data and drop retrieval_meta (CAI-RESP-220
        # reproducibility constraint). Captures the path that actually ran the
        # vector search (rpc | bruteforce | none), independent of whether it cleared
        # the 0.50 gate.
        if meta is not None:
            meta.set_retrieval_config(fiqh_data.get("retrieval_meta"))
        # Rank threshold (calibrated 2026-05-19 against Tier 1 stress queries
        # AND non-fiqh controls). bge-m3 has a gray zone 0.49-0.56 where both
        # legitimate fiqh queries and broad-Islamic-knowledge queries land
        # (e.g., "tafsir of ayat al-kursi" semantically overlaps Muqaddimah &
        # Iman at 0.515). 0.50 cleanly excludes the worst non-fiqh leaks at the
        # cost of one legitimate edge case ("what nullifies the fast" tops at
        # 0.497) — that case is rescued by the FTS fallback below.
        fiqh_data["results"] = [h for h in fiqh_data.get("results") or [] if h.get("rank", 0) >= 0.50]
        if not fiqh_data["results"]:
            # FTS fallback only when semantic returns nothing above threshold
            fiqh_data = lookup_fiqh(" ".join(words[:4]), limit=3)
            # Fix #5 (msg #10510): the semantic path has a principled 0.50 relevance
            # gate; the FTS keyword fallback had NONE, so off-topic queries ("decode
            # the quran", "coding") keyword-matched generic matn (khutbah, tayammum)
            # which the prompt's "MUST surface matn" rule then force-quoted verbatim
            # (review #10/#11). Gate the fallback on genuine lexical grounding: keep a
            # hit only if the matn text/baab actually contains one of the user's
            # LITERAL content words (not just an expanded synonym). This preserves the
            # "what nullifies the fast" rescue (matn contains "fast"/"nullif") while
            # dropping noise (matn about fasting shares no word with "coding").
            if fiqh_data.get("results"):
                fiqh_data["results"] = [h for h in fiqh_data["results"]
                                        if _matn_relevant_to_query(h, words)]
        if fiqh_data["results"]:
            if meta is not None:
                meta.add_juridical_hits(fiqh_data["results"])
            entries = []
            for hit in fiqh_data["results"]:
                # Truncate per-hit text to fit MAX_CONTEXT budget. Semantic
                # path returns full chapter (PK-constrained 1 row per text);
                # FTS path returns ~2000-char snippet from _extract_keyword_snippet.
                # Phase 3 schema migration to per-chunk rows replaces this slice.
                snippet = (hit.get("text") or "")[:4000]   # was 2500; allow full 3000c chunks +safety margin
                entries.append(
                    f"Source: {hit['source_work']}\n"
                    f"Chapter: {hit['baab']}\n"
                    f"Translator: {hit['translator']} ({hit['edition']})\n"
                    f"Tier: {hit['tier']}\n"
                    f"Passage:\n{snippet}"
                )
            context_parts.append(
                "FIQH MATCHED PASSAGES (Shafi'i matn — Safīnat al-Najā / al-Marbūqī tr.; "
                "RETRIEVE-ONLY echo. Compose-layer synthesis FORBIDDEN per C4 + INV-7 "
                "paired-scholar gate. Bot returns matn passages verbatim with attribution; "
                "user must consult qualified Shafi'i scholar for application to their case.):\n\n" +
                "\n\n---\n\n".join(entries)
            )

    return "\n\n---\n\n".join(context_parts) if context_parts else "No relevant data found in the database."


# --- Claude reasoning ---
# ---------------------------------------------------------------------------
# Audience-level prompt variants (added 2026-05-31 per operator directive
# "too technical" feedback). Three levels mapped to existing Islamic education
# conventions. Default 'seeker' (matches Hadhrami-Shafi'i pedagogy audience).
# ---------------------------------------------------------------------------

LEVEL_GUIDANCE = {
    "layman": """AUDIENCE TIER: LAYMAN (average Muslim, plain-English preference).
- Open with a one-line plain answer in everyday English, then expand.
- Translate every Arabic term inline on first use ("wudu (ablution)", "taqwa (God-consciousness)").
- Use AT MOST ONE primary hadith or verse citation; brief format only ("Bukhari · authentic").
- Skip verbatim matn passages UNLESS they directly enumerate the answer to the user's question.
- Skip the 4-tier transparency markers (📖 📝 💭) — use plain prose.
- Keep total response 150-300 words.
- End with the practical takeaway, NOT a reflective question.
- NEVER include retrieved passages that don't match the user's question — say
  "the corpus doesn't directly address this" instead.""",

    "seeker": """AUDIENCE TIER: SEEKER (serious Muslim student, default tier).
- Open with a focused answer, then layer the scholarly evidence.
- Use Arabic terms with parenthetical English on first use ("ṭahāra (purification)").
- Cite hadith with brief format: (Collection #N · ✅ Sahih · Narrator).
- Surface matn passages ONLY when they directly enumerate the answer (arkan, wajibat,
  shurut lists). If the retrieved matn is off-topic, omit it — do not surface unrelated
  matn just because it was retrieved.
- Use the 4-tier badges sparingly: 📖 for direct Qur'an/hadith quotes, 📝 for
  paraphrased tafsir. Drop 💭 unless explicitly synthesizing.
- Keep total response 300-600 words.
- End with a brief reflective question tying back to practice.""",

    "scholar": """AUDIENCE TIER: SCHOLAR (fiqh student, advanced reader).
- Full scholarly apparatus.
- Surface verbatim matn from retrieved Shafi'i primer when present, with full attribution.
- Complete isnād citations + grading + narrator for every hadith.
- Surface ikhtilāf with scholar-by-scholar attribution when retrieved tafsir entries diverge.
- Use all four 4-tier markers (📖 📝 💭) per their strict definitions.
- Quote Arabic alongside translation for Qur'anic verses.
- End with a substantive reflective question that opens further inquiry.
- No length cap; aim for 600-1200 words depending on subject density.""",
}


# --- Claude CLI failure classification (msg #2737) -------------------------
# Operator hit a generic "Error: unknown" caused by a transient network blip
# (logs showed "No route to host"/Errno 65, "Connection reset by peer",
# "read operation timed out") that made the CLI call fail. Network blips fail
# FAST and recover on retry; a genuine processing error does not. We classify
# the failure, retry the transient kind with short backoff, and surface an
# honest, cause-fit message instead of the catch-all "Error: unknown".
_CLI_NETWORK_HINTS = (
    "no route to host", "errno 65", "errno 54", "errno 60", "errno 51",
    "connection reset", "connection refused", "connection aborted",
    "broken pipe", "network is unreachable", "could not resolve",
    "temporary failure in name resolution", "name or service not known",
    "getaddrinfo", "eof occurred", "ssl", "timed out", "timeout",
)

# Honest, cause-fit user messages — never "Error: unknown".
_CLI_NETWORK_MSG = (
    "I hit a temporary connection issue and couldn't reach my source — "
    "please send that again in a moment, inshaAllah. 🌿"
)
_CLI_PROCESSING_MSG = (
    "I couldn't process that question just now. Please try rephrasing it, "
    "or send it again shortly."
)
_CLI_UNEXPECTED_MSG = (
    "Something went wrong on my end while answering — please try again in a "
    "moment, inshaAllah."
)


def _is_transient_cli_error(detail) -> bool:
    """True if a Claude-CLI failure detail looks like a transient network blip."""
    t = (detail or "").lower()
    return any(h in t for h in _CLI_NETWORK_HINTS)


def _lean_prompt(question, context, max_ctx=8000) -> str:
    """A stripped-down synthesis prompt for the post-timeout FAST retry.

    The 22% dead-end-stub rate (mizan quality review #6489) came from full
    synthesis exceeding the 180s timeout — often on heavy retrieval context
    (30-40KB). A leaner prompt over trimmed context returns far more often.
    Preserves the load-bearing rules: answer ONLY from the data (F-1), never
    fabricate isnads (F-4), never issue a ruling (F-3), quote Arabic + attribution.
    """
    ctx = context if len(context) <= max_ctx else context[:max_ctx] + "\n…[context trimmed for a faster answer]…"
    return (
        'You are Bayan, an Islamic knowledge assistant. Answer the question ONLY '
        'from the data below — do not invent verses, tafsir, or hadith, and NEVER '
        'issue a fiqh ruling (if it is a ruling question, say plainly it needs a '
        'qualified scholar). Be CONCISE (well under 3500 characters). Include Arabic '
        'for any Quran verse, and keep source attribution on quoted passages.\n\n'
        f'QUESTION: "{question}"\n\nDATA:\n{ctx}\n\nAnswer directly and concisely:'
    )


# The two CAI-RESP-396-eligible failure-answer strings, named so the
# MIZAN-REENGAGE-01 follow-up classifier (scripts/mizan_followup.py) has a single
# source of truth for "was this a genuine failure worth re-queuing?" — see
# classify_failure(). EVIDENCE_FALLBACK_PREFIX = degraded-but-real evidence
# answer; TIMEOUT_STUB_MSG = the honest no-parseable-evidence stub. A normal,
# send-worthy answer matches NEITHER (G1: no follow-up row for a good answer).
TIMEOUT_STUB_MSG = (
    "That one's taking longer than I can hold the line for right now. "
    "Please send it again in a moment, inshaAllah — it usually goes "
    "through on a second try. 🌿"
)
EVIDENCE_FALLBACK_PREFIX = (
    "⏳ The full write-up is taking longer than usual, so here is the "
    "sourced evidence directly — ask again for a fuller explanation."
)


def _evidence_fallback(question, context) -> str:
    """Last-resort answer built from the retrieval that ALREADY succeeded, with
    NO LLM call — used only when both the full and the trimmed synthesis time out.

    The old behaviour returned a dead-end stub and threw the sourced evidence
    away. Surfacing the retrieved passages instead keeps the funnel's promise
    (evidence-first, F-1/F-2) and hands the user something real. It quotes only
    retrieved rows (F-4) and states no ruling (F-3).
    """
    def _clip(s, n):
        s = " ".join(str(s or "").split())
        return s if len(s) <= n else s[:n].rstrip() + "…"

    def _first(d, *keys):
        for k in keys:
            v = d.get(k)
            if v:
                return v
        return None

    parts = []
    for block in (context or "").split("\n\n---\n\n"):
        block = block.strip()
        if not parts and not block:
            continue
        nl = block.find("\n")
        header, body = (block[:nl], block[nl + 1:]) if nl != -1 else (block, "")
        try:
            data = json.loads(body)
        except Exception:
            continue
        # Unwrap {"results": [...]} envelopes so search blocks (QURAN SEARCH /
        # TOPIC / TAFSIR search) surface their rows too — not just direct verse
        # lookups. Without this the dominant timeout class (heavy retrieval
        # context, all results-wrapped) fell through to the generic stub, and
        # search rows use *_number / arabic_text / english_translation keys that
        # the ayah branch below didn't recognise (#6489 fallback gap).
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            items = data["results"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            arabic = _first(it, "arabic", "arabic_text")
            translation = _first(it, "translation", "english_translation")
            if arabic and translation:
                surah = _first(it, "surah", "surah_number")
                ayah = _first(it, "ayah", "ayah_number")
                name = it.get("surah_name") or (f"Surah {surah}" if surah else "Qur'an")
                ref = f" {surah}:{ayah}" if surah and ayah else ""
                seg = [f"📖 *{name}{ref}*",
                       f"> {_clip(arabic, 500)}",
                       f"_{_clip(translation, 500)}_"]
                for t in (it.get("tafsir") or [])[:1]:
                    seg.append(f"📝 {_clip(t.get('scholar_name'), 40)}: {_clip(t.get('english_text'), 600)}")
                parts.append("\n".join(seg))
            else:
                for k in ("english_text", "matn", "text", "english_translation", "translation"):
                    if it.get(k):
                        parts.append(f"📝 {_clip(it.get('scholar_name') or it.get('source_work') or header, 50)}: {_clip(it[k], 600)}")
                        break
        if sum(len(p) for p in parts) > 3200:
            break

    if not parts:
        # No parseable evidence (rare) — honest, not a dead-end loop-back.
        return TIMEOUT_STUB_MSG

    return (EVIDENCE_FALLBACK_PREFIX + "\n\n"
            + "\n\n".join(parts[:6])
            + "\n\n_Sourced from the retrieved corpus; this is evidence, not a ruling — "
            "for a fiqh verdict consult a qualified scholar._")


# ---------------------------------------------------------------------------
# 40-answer self-review helpers (msg #10510)
# ---------------------------------------------------------------------------

def _format_verse_answer(data):
    """Format a lookup_verse() result as a deterministic, retrieval-only answer."""
    if not data or data.get("error"):
        return None
    lines = [f"📖 *({data['surah_name']}, {data['surah']}:{data['ayah']})*", ""]
    if data.get("arabic"):
        lines.append(f"> {data['arabic']}")
    if data.get("translation"):
        tr = f"> \"{data['translation']}\""
        if data.get("translator"):
            tr += f" — {data['translator']}"
        lines.append(tr)
    for t in (data.get("tafsir") or [])[:2]:
        body = (t.get("english_text") or "").strip()
        if len(body) > 700:
            body = body[:700].rsplit(" ", 1)[0] + "…"
        badge = "📖" if t.get("output_tier") == "quoted" else "📝"
        lines += ["", "---", f"{badge} *{t.get('scholar_name', '?')}* "
                  f"({t.get('source_work', '')}): {body}"]
    lines += ["", "---", "_Direct lookup of the verse and its tafsir from the corpus "
              "(retrieval only). Ask a follow-up for a fuller explanation._"]
    return "\n".join(lines).strip()


def _format_hadith_answer(h, col, num):
    """Format a lookup_hadith() result (or an honest not-found) as a deterministic answer."""
    if not h or h.get("error"):
        # Honest not-found beats the generic timeout message. Bukhari #35 genuinely
        # isn't in the corpus; numbering differs across editions (review #27).
        return (f"I don't have {col.title()} #{num} in this corpus. Hadith numbering differs "
                f"across editions (Khan / Fath al-Bari / Arabic combined), so a bare number is "
                f"ambiguous. Tell me the book/chapter (e.g. Kitab al-Iman) or a phrase from the "
                f"text, and I'll pull the right narration.")
    grade = (h.get("grading") or "").lower()
    badge = {"sahih": "✅ Sahih", "hasan": "⚠️ Hasan",
             "daif": "❌ Da'if", "da'if": "❌ Da'if"}.get(grade, grade or "")
    head = f"📖 *({h.get('collection_full', col.title())} #{num}"
    if badge:
        head += f" · {badge}"
    if h.get("narrator"):
        head += f" · {h['narrator']}"
    head += ")*"
    lines = [head, ""]
    if h.get("arabic_text"):
        lines.append(f"> {h['arabic_text']}")
    if h.get("english_text"):
        lines.append(f"> \"{h['english_text']}\"")
    lines += ["", "---", "_Direct lookup from the corpus (retrieval only)._"]
    return "\n".join(lines).strip()


def build_keyed_answer(question):
    """Deterministic, retrieval-only answer for pure keyed-lookup queries.

    Returns a formatted verbatim answer when the query is a keyed lookup —
    surah:ayah, a named-ayah alias (ayat al-kursi → 2:255), or a hadith reference
    (bukhari 35) — else None. Used as ask_claude's fallback (Fix #1) so a keyed
    lookup can never degrade into a synthesis-timeout non-answer.

    F-1-aligned (retrieval, no LLM synthesis) and quoted/paraphrased tier — the
    safest answer shape. It does NOT fire for ruling-class queries: keyed lookups
    are verse/hadith DISPLAY only, never a fiqh verdict.
    """
    q = question.lower()
    # 1. Explicit surah:ayah (single verse; ranges stay on the synthesis path)
    m = re.search(r'\b(\d{1,3}):(\d{1,3})\b', question)
    if m:
        return _format_verse_answer(lookup_verse(int(m.group(1)), int(m.group(2))))
    # 2. Named-ayah alias (ayat al-kursi, etc.) → (surah, ayah) tuple
    special = match_surah_alias(question)
    if isinstance(special, tuple):
        return _format_verse_answer(lookup_verse(special[0], special[1]))
    # 3. Hadith reference (bukhari 35, muslim 2345)
    hm = re.search(r'(bukhari|muslim|abudawud|abu dawud|tirmidhi|nasai|ibnmajah|ibn majah)'
                   r'\s*(?:#?\s*)?(\d+)', q)
    if hm:
        col = hm.group(1).replace(" ", "")
        return _format_hadith_answer(lookup_hadith(col, hm.group(2)), col, hm.group(2))
    return None


# Fix #2b: defence-in-depth guard against dev/test/pipeline text reaching a user
# answer. The ROOT cause is fixed by `--tools ""` + neutral cwd (see ask_claude);
# this backstop catches any residual self-narration. Markers are internal
# identifiers / phrases that can never legitimately appear in an Islamic answer.
_DEV_LEAK_MARKERS = [
    r'mizan_bot\.py', r'albayan_bot\.py', r'ask-scholar', r'gather_context',
    r'persist-mizan', r'supabase/functions', r'\.ts\b',
    r'uncommitted', r'test/debug pass', r'\btest pass\b', r'\bdebug pass\b',
    r'the response Al-M[iī]z[aā]n would send', r'\bpersona response\b',
    r'not the bot persona', r'FIQH MATCHED PASSAGES', r'injected RULES',
    r'\bRULES:', r'\bsystem prompt\b', r'MUST surface', r'3900[-\s]?char',
    r'\bchar budget\b', r'similarity gate', r'relevance gate', r'Flag for you',
    r'\bretrieval flag\b',
]
_DEV_LEAK_RE = re.compile("|".join(_DEV_LEAK_MARKERS), re.IGNORECASE)


def detect_dev_leak(answer):
    """Return the first leaked marker if the answer contains dev/test/pipeline
    meta-language, else None. Fix #2b (msg #10510)."""
    if not answer:
        return None
    m = _DEV_LEAK_RE.search(answer)
    return m.group(0) if m else None


def ask_claude(question, context, history=None, answer_level="seeker", madhhab=None, fallback_answer=None):
    """Use Claude Code CLI to reason over the context.

    fallback_answer: a deterministic, retrieval-only answer (see build_keyed_answer)
      for lookup-class queries (verse ref / hadith number / named-ayah). When the
      CLI fails (timeout / network / processing error), this is returned INSTEAD of
      the generic "try again" message, so a trivial keyed lookup can never degrade
      into a non-answer. Fix #1 per the 40-answer self-review (msg #10510) — the
      6/40 (15%) hard-failure rate included "generate ayatul kursi" (×2) and
      "bukhari 35", all of which are pure keyed lookups.

    answer_level: 'layman' | 'seeker' (default) | 'scholar' — controls audience-tier
      guidance injected into the system prompt. Per-session preference adjustable via
      Telegram inline keyboard buttons appended to every response.
    madhhab: 'shafii' | 'hanafi' | 'maliki' | 'hanbali' | None — user's school
      preference (via /madhhab). Injected as a MADHHAB GUIDANCE block telling the
      LLM to lead with the user's school on ikhtilaf questions, AND to refuse to
      fabricate non-Shafi'i positions when the corpus only carries Shafi'i matn.
    """
    history_block = ""
    if history:
        turns = []
        for h in history:
            prefix = "User" if h["role"] == "user" else "Bayan"
            turns.append(f"{prefix}: {h['text'][:500]}")
        history_block = (
            "\nPREVIOUS CONVERSATION:\n"
            + "\n".join(turns)
            + "\n\nPRIOR CONVERSATION GUIDANCE:\n"
            "If recent turns establish a clear thematic thread, INFER the user's intent from\n"
            "that thread BEFORE asking for clarification. Only ask for clarification when\n"
            "multiple equally-plausible candidates exist with no thematic preference.\n"
            "For short or ambiguous follow-up questions, treat the immediately preceding\n"
            "turn(s) as the primary disambiguation source.\n"
        )

    level_block = LEVEL_GUIDANCE.get(answer_level, LEVEL_GUIDANCE["seeker"])
    madhhab_block = ""
    if madhhab and madhhab in MADHHAB_GUIDANCE:
        madhhab_block = f"\nMADHHAB GUIDANCE (user's declared school):\n{MADHHAB_GUIDANCE[madhhab]}\n"

    prompt = f"""You are Bayan, an Islamic knowledge assistant. A user asked:

"{question}"
{history_block}
{level_block}{madhhab_block}

(The AUDIENCE TIER guidance above takes precedence over the RULES below on the
same topic — e.g., if AUDIENCE TIER says "skip verbatim matn unless directly
answering" then the RULE about "always surface matn" is overridden for THIS tier.)

Here is the relevant data from the Quran, tafsir, and hadith database:

{context}

RULES:
- Use ONLY the provided data to answer. Do not make up verses, tafsir, or hadiths.
- NEVER issue fiqh rulings.
- RELEVANCE GATE (check FIRST): a matched block (FIQH MATCHED PASSAGES / TAFSIR
  MATCHED PASSAGES / QURAN SEARCH) is retrieval, not a guarantee of relevance.
  If a block is OFF-TOPIC for the question — it overlaps only on an incidental
  keyword and does not actually address what was asked — do NOT surface it.
  Say plainly that the corpus doesn't carry material on this specific point and
  stop; never pad an answer with unrelated matn/tafsir just because it matched.
- WHENEVER a "FIQH MATCHED PASSAGES" block is present AND on-topic per the gate
  above, you MUST surface the matn passage in your response. Do not omit or
  summarize it — quote VERBATIM with full attribution: "Safīnat al-Najā
  (<Chapter>, al-Marbūqī tr., al-inaam.com 2009)" where <Chapter> is the baab
  name from the FIQH MATCHED PASSAGES block. The matn is the Shafi'i school's specific
  application of higher-tier evidence (Quran/hadith); both should be presented
  side-by-side when relevant — Quran/hadith establish the principle, the matn
  shows the school's juristic framing. Do NOT synthesize a new ruling from
  these passages. After each matn quotation, append:
  "This passage is from the Shafi'i primer for reference; consult a qualified
  scholar for application to your specific situation."
- MACHINE-TRANSLATION GUARD: when a matn passage's Tier (from the FIQH MATCHED
  PASSAGES block) is "ai-generated" — i.e. an auto/Claude/OpenITI translation, not
  a human-vetted rendering — you MUST additionally flag the WORDING as unverified.
  After that passage append this second line VERBATIM:
  "⚠️ Machine translation — the wording is an unverified reference pointer, not an
  authoritative text. Do not act on the exact wording without a qualified scholar."
  This is non-negotiable on any question about the validity/permissibility of an
  act (wudu, salah, fasting, marital relations, etc.), where a user might act on
  the words directly.
- Telegram message budget: aim for under 3900 chars total (hard limit is 4096).
  PRIORITY when fitting: surface the FULL matn enumeration verbatim — never
  summarize an arkan/wajibat/shurut/mubtilat/nawaqid list, never drop items
  mid-enumeration, never use "etc." or "..." in place of listed integrals.
  If space is tight, shorten the reflective question or drop tangential
  hadith — never abbreviate the matn integrals.
- Include Arabic text when showing Quranic verses.
- End with a reflective question (practice off-ramp) to move knowledge toward action.
- If the data doesn't answer the question, say so directly — but state the
  gap as a fact, not a confession. Do NOT open with self-conscious framing
  like "I have to be honest with you upfront", "I'll be transparent", "let
  me be honest", or similar performative-honesty preambles. Just state what
  the retrieved evidence covers and what it doesn't, then proceed. The
  honesty is in the structure of the answer, not in narrating it.
- When quoting a tafsir passage, append `[<Tier>: <scholar>, <source>]` verbatim.

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

    # 2026-05-27: timeout bumped 60→180s. Dense fiqh queries with 30-40KB
    # retrieval context, controversial-topic queries that need careful refusal,
    # and ikhtilaf-rich tafsir queries routinely take 60-120s. The prior 60s
    # was producing "taking too long" timeout messages on legitimate
    # well-reasoned answers. 180s gives 3x headroom while still bounding
    # bot's polling-loop latency.
    # Auto-retry transient network failures (msg #2737). The bot already retries
    # the Telegram polling loop on network errors; apply the same resilience to
    # the answer path. Network blips fail fast, so 3 attempts with 2s/4s backoff
    # adds little latency while recovering from the common case. A 180s timeout
    # is NOT retried — it means slow synthesis, not a blip, and 3×180s would
    # strand the user.
    max_attempts = 3
    last_detail = ""
    for attempt in range(max_attempts):
        try:
            result = subprocess.run(
                # Fix #2a: `--tools ""` disables ALL tools so this is pure text
                # synthesis — the CLI cannot read the repo/uncommitted source/skills
                # and fold them into the answer (the persona-leak root cause). cwd
                # is a neutral empty sandbox, not the repo, as defence-in-depth.
                # --model pins sonnet-5 (main's retrieval-path model choice).
                [CLAUDE_PATH, "-p", prompt, "--model", "claude-sonnet-5", "--tools", "", "--output-format", "text"],
                capture_output=True, text=True, timeout=180,
                cwd=_SYNTH_SANDBOX_DIR,
                env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            # Non-zero exit or empty output — inspect both streams for cause.
            detail = ((result.stderr or "") + " " + (result.stdout or "")).strip()
            last_detail = detail[:200] or "empty output"
            if _is_transient_cli_error(detail):
                if attempt < max_attempts - 1:
                    print(f"  -> Claude CLI transient failure (attempt {attempt + 1}/{max_attempts}): {last_detail[:120]}")
                    time.sleep(2 * (attempt + 1))
                    continue
                print(f"  -> Claude CLI transient failure exhausted: {last_detail[:120]}")
                return fallback_answer or _CLI_NETWORK_MSG
            # Genuine, non-transient processing error — honest, not "unknown".
            print(f"  -> Claude CLI processing error: {last_detail[:120]}")
            return fallback_answer or _CLI_PROCESSING_MSG
        except subprocess.TimeoutExpired:
            # Fix #1: a lookup-class query with a deterministic keyed answer must
            # never degrade into the generic "try again" non-answer on synthesis
            # timeout — return the retrieval-only answer immediately.
            if fallback_answer:
                print("  -> Claude CLI timeout; serving deterministic keyed-lookup fallback")
                return fallback_answer
            # Slow synthesis, not a blip (so NOT the 3× transient retry). Try ONE
            # trimmed, shorter-timeout pass — heavy retrieval context is the usual
            # cause and a leaner prompt frequently returns. If that ALSO times out,
            # degrade to an evidence-grounded answer built from the retrieval that
            # already succeeded (F-1/F-2) — never the old dead-end stub that threw
            # the sourced evidence away and left the user with nothing (#6489).
            # The trimmed pass carries the same Fix #2a persona-leak guards as the
            # main call (`--tools ""` + neutral sandbox cwd).
            print("  -> Claude CLI timeout at 180s; trying one trimmed 90s pass")
            try:
                retry = subprocess.run(
                    [CLAUDE_PATH, "-p", _lean_prompt(question, context), "--model", "claude-sonnet-5", "--tools", "", "--output-format", "text"],
                    capture_output=True, text=True, timeout=90,
                    cwd=_SYNTH_SANDBOX_DIR,
                    env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
                )
                if retry.returncode == 0 and retry.stdout.strip():
                    print("  -> trimmed retry returned a real answer")
                    return retry.stdout.strip()
            except subprocess.TimeoutExpired:
                print("  -> trimmed retry also timed out; falling back to retrieved evidence")
            except Exception as e:
                print(f"  -> trimmed retry errored ({type(e).__name__}); falling back to retrieved evidence")
            return _evidence_fallback(question, context)
        except Exception as e:
            last_detail = str(e)[:200]
            if _is_transient_cli_error(str(e)) and attempt < max_attempts - 1:
                print(f"  -> Claude CLI transient exception (attempt {attempt + 1}/{max_attempts}): {last_detail[:120]}")
                time.sleep(2 * (attempt + 1))
                continue
            if _is_transient_cli_error(str(e)):
                print(f"  -> Claude CLI transient exception exhausted: {last_detail[:120]}")
                return fallback_answer or _CLI_NETWORK_MSG
            print(f"  -> Claude CLI unexpected error: {last_detail[:120]}")
            return fallback_answer or _CLI_UNEXPECTED_MSG
    # All attempts exhausted on transient failures.
    return fallback_answer or _CLI_NETWORK_MSG


# --- Persistence helper (AL-BAYAN-COMPOSE-001 / CAI-RESP-135) ---
def persist_emission(chat_id, query_text, response_text, retrieval_ids=None, matched_passage_id=None, retrieval_config=None):
    """POST to persist-mizan-ruling Edge Function.

    Fail-soft: log on error, never raise. Bot's user-facing UX must not break
    if persistence is unavailable. Per CAI-RESP-135, governance integrity is
    critical but bot responsiveness is not negotiable mid-conversation.

    F-2 (tafsir-defense-funnel): retrieval_ids carries the union of every
    retrieval row ID that grounded the response (tafsir ayah_ids, juridical_text_ids,
    hadith ids). matched_passage_id is the top tafsir hit's ayah_id when
    search_tafsir_fts returned ≥1 row, else null.

    Fix #2c (msg #10510): when MIZAN_TEST_MODE is set, this is a developer test
    pass — skip persistence entirely so dev runs cannot pollute mizan_interactions
    (the judge / eval / gold-set corpus). Client-side skip needs no schema change;
    is_test is also sent so a future stored-and-flagged path can be enabled server
    side without touching the bot.
    """
    if MIZAN_TEST_MODE:
        print("  -> MIZAN_TEST_MODE: skipping persist_emission (dev/test pass, not written)")
        return None
    payload = {
        "telegram_id": chat_id,
        "query_text": query_text[:2000],   # keep request small
        "response_text": response_text[:5000],
        "retrieval_ids": retrieval_ids or [],
        "matched_passage_id": matched_passage_id,
        "is_test": False,
    }
    # CAI-RESP-220: stamp the retrieval-substrate config so an evidence set is
    # reproducible from the audit row. Omit the key entirely when absent so the
    # Edge Function (pre-deploy) and column (pre-migration) degrade silently —
    # the persist path must never hard-depend on the new field.
    if retrieval_config:
        payload["retrieval_config"] = retrieval_config
    key = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(PERSIST_FUNCTION_URL, data=data, headers={
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"  -> persisted: interaction_id={result.get('interaction_id', '?')[:8]}")
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        print(f"  -> persistence failed (HTTP {e.code}): {body[:200]}")
    except Exception as e:
        print(f"  -> persistence failed: {type(e).__name__}: {str(e)[:200]}")
    return None


# --- Telegram helpers ---
def tg_request(method, data=None):
    """Make a Telegram Bot API request.

    Telegram returns HTTP 200 with {"ok":false,...} on logical errors (e.g.
    bad Markdown, message too long, "Bad Request: can't parse entities").
    Without checking the ok field these silently passed as success — recently
    caused inline-keyboard re-ask responses to appear successfully sent in
    bot logs while never reaching the user. 2026-05-31: raise on ok=false
    so the caller's try/except fallback path actually fires.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if isinstance(body, dict) and body.get("ok") is False:
        raise RuntimeError(
            f"Telegram {method} ok=false: code={body.get('error_code')} "
            f"desc={body.get('description','?')[:200]}"
        )
    return body


# --- Hardened long-poll getUpdates (op#5959 — Bayan poll-loop outage) --------
# Root cause of the silent outage: a getUpdates long-poll would latch a
# black-holed TLS connection (TCP ESTABLISHED to api.telegram.org, handshake
# stalled mid-flight) and the urlopen socket timeout did NOT fire — the loop
# wedged for minutes with no log line, no 409 (Telegram never saw the request),
# and no retry. Two defences here, independent of urllib's unreliable timeout:
#   1. A SIGALRM wall-clock backstop that interrupts the C-level poll() and
#      raises, so no single getUpdates can ever exceed the deadline. SIGALRM is
#      safe: the poll loop runs on the main thread. The handler RAISES so PEP-475
#      does not silently retry the interrupted syscall.
#   2. Per-attempt logging (start / return-count / exception) so any future
#      stall is visible in logs/mizan_bot.log instead of being silent.
# Each call is a fresh urlopen (no connection reuse), so a retry after a stall
# always dials a new connection rather than re-waiting on the dead one.
class _PollTimeout(Exception):
    pass


def _poll_alarm_handler(signum, frame):
    raise _PollTimeout("getUpdates hard deadline exceeded")


def poll_get_updates(offset, long_poll=25):
    """One long-poll getUpdates with a hard SIGALRM backstop + logging.

    long_poll is the Telegram-side wait (seconds). The SIGALRM backstop fires at
    long_poll + 20s, well past a healthy response but bounding a black-holed
    connection. Returns the parsed body dict; raises on timeout/network error so
    the caller's except path logs + retries with a fresh connection.
    """
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    deadline = long_poll + 20
    prev = signal.signal(signal.SIGALRM, _poll_alarm_handler)
    signal.alarm(deadline)
    try:
        body = tg_request("getUpdates", {
            "offset": offset,
            "timeout": long_poll,
            "allowed_updates": ["message", "callback_query"],
        })
        n = len(body.get("result", [])) if isinstance(body, dict) else 0
        if n:
            print(f"[{ts}] getUpdates -> {n} update(s)")
        return body
    except _PollTimeout:
        print(f"[{ts}] getUpdates HARD-TIMEOUT after {deadline}s "
              f"(black-holed connection) — dropping it, reconnecting")
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


def _split_for_telegram(text: str, max_chars: int = 4000) -> list[str]:
    """Split long responses on natural boundaries instead of hard-cutting at 4000c.

    Telegram hard limit is 4096c per message. Prefer splitting on '\\n---\\n'
    section breaks; fall back to paragraph breaks ('\\n\\n'); fall back to
    line breaks; last resort, hard-cut. Returns ≥1 messages, each ≤ max_chars.
    """
    if len(text) <= max_chars:
        return [text]
    parts: list = []
    remaining = text
    while len(remaining) > max_chars:
        # Look for the latest boundary within the first max_chars
        window = remaining[:max_chars]
        cut = -1
        for sep in ("\n\n---\n\n", "\n---\n", "\n\n", "\n"):
            idx = window.rfind(sep)
            if idx > max_chars // 2:  # only accept if not too early
                cut = idx + len(sep)
                break
        if cut < 0:
            cut = max_chars  # hard fallback
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def _extract_cited_verses(text, max_verses=6):
    """Pull (surah, ayah) tuples cited in a Mizan response. Looks for:
      - (X:Y) parenthetical form
      - Surah X, ayah Y (and Ayah Y) form
      - bare X:Y inside markdown bold/italics
    Deduplicates preserving first-seen order. Caps at max_verses to keep
    the inline keyboard small (Telegram limit is 100 buttons but UX
    breaks well before that — 6 keeps the keyboard scannable).

    Validates ranges (1≤surah≤114, 1≤ayah≤286 for safety). Reject
    out-of-range matches to avoid spurious citations from year numbers
    or hadith numbers (e.g., "1990" isn't 1:990).
    """
    if not text:
        return []
    import re as _re
    pattern = _re.compile(r"\((\d{1,3})\s*:\s*(\d{1,3})\)|(?:[Ss]ur[ai]h?\s+[\w؀-ۿ\s-]{1,30},?\s+[Aa]yah\s+(\d{1,3}))|\b(\d{1,3})\s*:\s*(\d{1,3})\b")
    seen = set()
    out = []
    for m in pattern.finditer(text):
        # group 1+2 = (X:Y); group 3 = ayah only after "Surah ..." (skip — no surah num); group 4+5 = bare X:Y
        if m.group(1) and m.group(2):
            s, a = int(m.group(1)), int(m.group(2))
        elif m.group(4) and m.group(5):
            s, a = int(m.group(4)), int(m.group(5))
        else:
            continue
        if not (1 <= s <= 114) or not (1 <= a <= 286):
            continue
        key = (s, a)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= max_verses:
            break
    return out


def _level_keyboard(current_level, cited_verses=None, interaction_id=None):
    """Inline keyboard for audience-tier adjustment + audio recitation.
    Level row (context-aware):
      layman   → [✓ Current: Layman] [🎓 More detail]
      seeker   → [👶 Simpler] [✓ Current: Seeker] [🎓 More detail]
      scholar  → [👶 Simpler] [✓ Current: Scholar]
    The "Current" button is informational (tapping it = keep, no re-ask).
    Simpler/Deeper buttons only appear when there's a direction to go.

    Audio row(s) — optional. When cited_verses is a non-empty list of
    (surah, ayah) tuples, render 🔊 buttons (max 3 per row, max 6 total).
    Tap → bot sends voice message via sendVoice from EveryAyah CDN.
    """
    level_buttons = []
    if current_level != "layman":
        level_buttons.append({"text": "👶 Simpler", "callback_data": "level:layman" if current_level == "seeker" else "level:seeker"})
    current_label = current_level.capitalize()
    level_buttons.append({"text": f"✓ Current: {current_label}", "callback_data": "level:keep"})
    if current_level != "scholar":
        level_buttons.append({"text": "🎓 More detail", "callback_data": "level:scholar" if current_level == "seeker" else "level:seeker"})

    rows = [level_buttons]

    if cited_verses:
        audio_buttons = [
            {"text": f"🔊 {s}:{a}", "callback_data": f"audio:{s}:{a}"}
            for s, a in cited_verses[:6]
        ]
        # Max 3 per row for readability
        for i in range(0, len(audio_buttons), 3):
            rows.append(audio_buttons[i:i + 3])

    # Scholar-review flag (#2746) — any user may flag an answer as doubtful so a
    # human scholar can verify it. Needs the persisted interaction_id, which is
    # only known after persist (runs after send per CAI-RESP-135), so this row
    # is injected via _maybe_add_flag_button after the answer is sent.
    if interaction_id:
        rows.append([{
            "text": "🔖 Flag for scholar review",
            "callback_data": f"flag:{interaction_id}",
        }])

    return {"inline_keyboard": rows}


def _maybe_add_flag_button(chat_id, msg_id, level, cited, persist_result):
    """After persist returns an interaction_id, inject the scholar-review flag
    button onto the just-sent answer (edit in place, not resend).

    Persist runs AFTER send (CAI-RESP-135: persistence outages must not block
    replies), so the flag button — which carries the interaction_id — is added
    in a second step. No-op if send or persistence failed (nothing to flag),
    which degrades gracefully rather than showing a flag that writes nowhere.
    """
    if not msg_id or not isinstance(persist_result, dict):
        return
    interaction_id = persist_result.get("interaction_id")
    if not interaction_id:
        return
    try:
        kb = _level_keyboard(level, cited_verses=cited, interaction_id=interaction_id)
        tg_request("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": msg_id,
            "reply_markup": json.dumps(kb),
        })
    except Exception as e:
        print(f"  -> flag-button inject skipped: {type(e).__name__}: {e}")


def _send_document(chat_id, filename, file_bytes, caption=None, mime="text/csv"):
    """Upload an in-memory file to a chat via sendDocument (multipart/form-data).
    Stdlib-only multipart encoder — the bot has no `requests` dependency."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    boundary = "----MizanReviewBoundary8a3f1c"
    parts = []

    def _field(name, value):
        parts.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             f"{value}\r\n").encode("utf-8")
        )

    _field("chat_id", str(chat_id))
    if caption:
        _field("caption", caption)
    parts.append(
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
         f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = json.loads(resp.read().decode("utf-8")).get("ok", False)
            print(f"  -> /review document sent: ok={ok}")
            return ok
    except Exception as e:
        print(f"  -> sendDocument failed: {type(e).__name__}: {e}")
        return False


def handle_review_export(chat_id):
    """Admin /review (#2746): compile flagged Q&A + export a scholar-ready
    spreadsheet (UTF-8-BOM CSV — opens cleanly in Excel/Sheets/Numbers and
    preserves Arabic). Columns map to the persisted interaction row; madhhab /
    answer-level are not stored per-interaction in v1, so query_type + tier
    stand in (v2 note in the migration)."""
    try:
        rows = supabase_get("mizan_interactions", {
            "flagged_for_review": "eq.true",
            "select": ("id,query_text,response_text,query_type,output_tier,"
                       "flagged_by,flagged_at,reviewer_note,created_at"),
            "order": "flagged_at.desc",
        })
    except Exception as e:
        print(f"  -> /review query failed: {type(e).__name__}: {e}")
        send_message(chat_id,
            "Couldn't load the review list right now — the flag columns may not "
            "be applied to the database yet. Try again shortly.")
        return
    if not rows:
        send_message(chat_id, "No answers are currently flagged for scholar review. ✅")
        return

    import io
    import csv
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel reads UTF-8 (Arabic) correctly
    w = csv.writer(buf)
    w.writerow(["interaction_id", "question", "answer", "query_type", "tier",
                "flagged_by", "flagged_at", "reviewer_note", "asked_at"])
    for r in rows:
        w.writerow([
            r.get("id", ""),
            r.get("query_text", ""),
            r.get("response_text", ""),
            r.get("query_type", ""),
            r.get("output_tier", ""),
            (r.get("flagged_by") or "")[:12],  # short hash — who, without raw id
            r.get("flagged_at", ""),
            r.get("reviewer_note") or "",
            r.get("created_at", ""),
        ])
    data = buf.getvalue().encode("utf-8")
    n = len(rows)
    fname = f"mizan_scholar_review_{n}_items.csv"
    send_message(chat_id, f"🔖 *{n} answer(s) flagged for scholar review.* Exporting spreadsheet…")
    if not _send_document(chat_id, fname, data,
                          caption=f"{n} flagged Q&A for scholar verification"):
        send_message(chat_id, "The list loaded but the file upload failed — try /review again.")


def send_message(chat_id, text, reply_markup=None, reply_to_message_id=None):
    """Send a Telegram message, falling back to plain text if Markdown fails.
    Long responses (>4000c) split on natural section breaks across multiple
    messages instead of hard-cutting at 4000c. If reply_markup provided, it
    attaches to the LAST chunk only.

    Returns the Telegram message_id of the LAST chunk (or None on failure)
    so the caller can track-by-level and reply-point on revisit.
    """
    chunks = _split_for_telegram(text, max_chars=4000)
    n = len(chunks)
    last_message_id = None
    for i, chunk in enumerate(chunks):
        is_last = (i == n - 1)
        # Add 1/N indicator on multi-message responses
        if n > 1:
            chunk = f"{chunk}\n\n_({i+1}/{n})_"
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if reply_markup and is_last:
            payload["reply_markup"] = json.dumps(reply_markup)
        if reply_to_message_id and i == 0:
            payload["reply_to_message_id"] = reply_to_message_id
        try:
            result = tg_request("sendMessage", payload)
            if is_last and isinstance(result, dict):
                last_message_id = (result.get("result") or {}).get("message_id")
        except Exception:
            try:
                # Fallback without Markdown
                payload.pop("parse_mode", None)
                result = tg_request("sendMessage", payload)
                if is_last and isinstance(result, dict):
                    last_message_id = (result.get("result") or {}).get("message_id")
            except Exception as e:
                print(f"  Failed to send message chunk {i+1}/{n}: {e}")
    return last_message_id


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

    # Register slash-commands so they appear in the Telegram menu button
    # (the blue circle next to the message input). Tapping it shows this
    # list; typing "/" also autocompletes from it.
    # Idempotent — setMyCommands replaces the prior list each call.
    print("Registering slash-commands...")
    try:
        tg_request("setMyCommands", {
            "commands": [
                {"command": "start",   "description": "Welcome + how to use the bot"},
                {"command": "help",    "description": "Query types, library, transparency tiers"},
                {"command": "madhhab", "description": "Set school (shafii/hanafi/maliki/hanbali)"},
                {"command": "clear",   "description": "Reset conversation context"},
            ]
        })
        # Also set the chat menu button to type='commands' so the bottom-left
        # button explicitly opens the commands list (default behavior, but
        # be explicit so any prior override is reset).
        tg_request("setChatMenuButton", {
            "menu_button": {"type": "commands"}
        })
        print("  commands registered: /start /help /madhhab /clear")
    except Exception as e:
        print(f"  warning: command registration failed: {e}")

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
            updates = poll_get_updates(offset, long_poll=25)

            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                # --- Inline-keyboard callback for audience-tier + audio ---
                cb = update.get("callback_query")
                if cb:
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    cb_chat = (cb.get("message") or {}).get("chat", {}).get("id")
                    cb_user = cb.get("from", {}).get("first_name", "?")

                    # Audio recitation: callback_data = "audio:<surah>:<ayah>"
                    if cb_data.startswith("audio:"):
                        try:
                            _, s_str, a_str = cb_data.split(":", 2)
                            s, a = int(s_str), int(a_str)
                            if not (1 <= s <= 114 and 1 <= a <= 286):
                                raise ValueError("range")
                            audio_url = f"https://everyayah.com/data/Alafasy_128kbps/{s:03d}{a:03d}.mp3"
                            # Ack first so the spinner clears
                            try:
                                tg_request("answerCallbackQuery", {
                                    "callback_query_id": cb_id,
                                    "text": f"🔊 Sending {s}:{a} (Alafasy)…",
                                })
                            except Exception:
                                pass
                            # sendAudio for MP3 (sendVoice requires OGG/Opus).
                            # Telegram accepts remote URL strings for the file param.
                            tg_request("sendAudio", {
                                "chat_id": cb_chat,
                                "audio": audio_url,
                                "title": f"Qurʾān {s}:{a}",
                                "performer": "Mishary Al-Afasy",
                                "caption": f"📖 Qurʾān {s}:{a} — Mishary Al-Afasy (recitation)",
                            })
                            print(f"  -> Audio sent for {s}:{a}")
                        except Exception as e:
                            print(f"  Audio callback failed: {e}")
                            try:
                                tg_request("answerCallbackQuery", {
                                    "callback_query_id": cb_id,
                                    "text": "❌ Audio unavailable",
                                })
                            except Exception:
                                pass
                        continue

                    # Scholar-review flag: callback_data = "flag:<interaction_id>"
                    # Any user may flag/unflag (per operator, #2746). Toggle the
                    # DB row, ack honestly, and reflect the new state on the button.
                    if cb_data.startswith("flag:"):
                        interaction_id = cb_data.split(":", 1)[1]
                        flagger_hash = _hash_telegram_id(cb.get("from", {}).get("id"))
                        new_state = toggle_review_flag(interaction_id, flagger_hash)
                        if new_state is True:
                            ack = "🔖 Flagged for scholar review, jazakAllahu khairan."
                        elif new_state is False:
                            ack = "Removed from the scholar-review list."
                        else:
                            ack = "Couldn't record that just now — please try again shortly."
                        try:
                            tg_request("answerCallbackQuery", {
                                "callback_query_id": cb_id, "text": ack,
                            })
                        except Exception:
                            pass
                        # Reflect state on the button, preserving level + audio rows.
                        if new_state is not None and cb_chat:
                            msg_obj = cb.get("message", {})
                            kb_rows = (msg_obj.get("reply_markup") or {}).get("inline_keyboard", [])
                            for kb_row in kb_rows:
                                for btn in kb_row:
                                    if btn.get("callback_data", "").startswith("flag:"):
                                        btn["text"] = ("✅ Flagged — tap to undo" if new_state
                                                       else "🔖 Flag for scholar review")
                            try:
                                tg_request("editMessageReplyMarkup", {
                                    "chat_id": cb_chat,
                                    "message_id": msg_obj.get("message_id"),
                                    "reply_markup": json.dumps({"inline_keyboard": kb_rows}),
                                })
                            except Exception:
                                pass
                        print(f"  -> Flag toggle for {interaction_id[:8]} -> {new_state}")
                        continue

                    if not cb_chat or not cb_data.startswith("level:"):
                        # Ack with nothing if malformed
                        try:
                            tg_request("answerCallbackQuery", {"callback_query_id": cb_id})
                        except Exception:
                            pass
                        continue
                    new_level = cb_data.split(":", 1)[1]   # 'layman'|'seeker'|'scholar'|'keep'
                    session = get_session(cb_chat)

                    if new_level == "keep":
                        # User dismissed — acknowledge silently
                        try:
                            tg_request("answerCallbackQuery", {
                                "callback_query_id": cb_id,
                                "text": f"Level kept at {session['answer_level']}.",
                            })
                        except Exception:
                            pass
                        continue

                    if new_level not in ("layman", "seeker", "scholar"):
                        try:
                            tg_request("answerCallbackQuery", {"callback_query_id": cb_id})
                        except Exception:
                            pass
                        continue

                    # Update session preference + re-ask the last query at the new level
                    old_level = session["answer_level"]
                    session["answer_level"] = new_level
                    last_q = session.get("last_query", "")
                    print(f"[{cb_user}] callback level: {old_level} → {new_level}")

                    # If the same query has already been answered at this level,
                    # point the user back to that message instead of burning
                    # tokens to regenerate it.
                    cached_msg_id = (session.get("level_responses") or {}).get(new_level)
                    if cached_msg_id and last_q:
                        try:
                            tg_request("answerCallbackQuery", {
                                "callback_query_id": cb_id,
                                "text": f"Already answered at {new_level} level — see above.",
                            })
                        except Exception:
                            pass
                        try:
                            send_message(
                                cb_chat,
                                f"📌 You already saw this question at *{new_level}* level — see the message above.",
                                reply_markup=_level_keyboard(new_level),
                                reply_to_message_id=cached_msg_id,
                            )
                            print(f"  -> Pointed to cached {new_level} response (msg_id={cached_msg_id})")
                        except Exception as e:
                            print(f"  Reply-pointer failed: {e}")
                        continue

                    # Acknowledge the tap (Telegram shows toast briefly)
                    try:
                        tg_request("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": f"Reformatting at {new_level} level…",
                        })
                    except Exception:
                        pass

                    if not last_q:
                        send_message(cb_chat,
                                     f"Level set to *{new_level}*. Ask me your next question.")
                        continue

                    # Re-answer the previous query at the new level
                    try:
                        send_typing(cb_chat)
                        retrieval_meta = RetrievalMeta()
                        context = gather_context(last_q, meta=retrieval_meta)
                        cb_telegram_id = cb.get("from", {}).get("id")
                        cb_keyed_fallback = build_keyed_answer(last_q)
                        answer = ask_claude(
                            last_q, context,
                            session["history"] if session["history"] else None,
                            answer_level=new_level,
                            madhhab=get_user_madhhab(cb_telegram_id),
                            fallback_answer=cb_keyed_fallback,
                        )
                        # Fix #2b: same dev-leak backstop on the level-adjust surface.
                        _cb_leak = detect_dev_leak(answer)
                        if _cb_leak:
                            print(f"  -> DEV-LEAK GUARD tripped on callback (marker={_cb_leak!r})")
                            answer = cb_keyed_fallback or (
                                "Let me try that again — could you rephrase your question?"
                            )
                        # Don't append to history a second time — just update last_*
                        session["last_context"] = context
                        cited = _extract_cited_verses(answer)
                        msg_id = send_message(cb_chat, answer + AI_DRAFT_DISCLAIMER, reply_markup=_level_keyboard(new_level, cited_verses=cited))
                        if msg_id:
                            session.setdefault("level_responses", {})[new_level] = msg_id
                        # Persist the now-sticky level (last_q unchanged) so a further
                        # button tap after a restart still re-answers at the right depth.
                        save_chat_state(cb_chat, last_q, new_level)
                        print(f"  -> Reformatted response sent ({len(answer)} chars) at {new_level}")
                        persist_result = persist_emission(
                            cb_chat, last_q, answer,
                            retrieval_ids=retrieval_meta.retrieval_ids,
                            matched_passage_id=retrieval_meta.matched_passage_id,
                            retrieval_config=retrieval_meta.retrieval_config,
                        )
                        # #2746: add the scholar-review flag button to the re-answer.
                        _maybe_add_flag_button(cb_chat, msg_id, new_level, cited, persist_result)
                    except Exception as e:
                        print(f"  Callback re-answer failed: {type(e).__name__}: {e}")
                        send_message(cb_chat,
                                     "I couldn't reformat the last response. Try asking again at your preferred level.")
                    continue

                # --- Regular message update ---
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")
                user = msg.get("from", {}).get("first_name", "?")

                if not text or not chat_id:
                    continue

                print(f"[{user}] {text}")

                # MIZAN-REENGAGE-01 (CAI-RESP-396 §6b): a bare "STOP" reply opts the
                # user out of ALL future follow-ups, permanently + hash-keyed. INERT
                # until MIZAN_FOLLOWUP_ENABLED=1 (and the migration is applied). Kept
                # conservative (only a short bare opt-out phrase; "stop combining
                # prayers?" is still a real question). Fail-soft.
                try:
                    import mizan_followup as _followup
                    if _followup.FOLLOWUP_ENABLED and _followup.is_stop_reply(text):
                        _followup.add_optout(chat_id, source="stop-reply")
                        send_message(chat_id, "Understood — we won't send any follow-ups. "
                                              "You can still ask me anything anytime. 🌿")
                        continue
                except Exception as _se:
                    print(f"  -> stop-optout check skipped ({type(_se).__name__})")

                # Get or create session
                session = get_session(chat_id)

                # Handle commands
                if text == "/start":
                    sessions.pop(chat_id, None)  # Reset session
                    send_message(chat_id,
                        "*Bismillah* — Welcome to Bayan 🌙\n\n"
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
                        "*Three answer levels:*\n"
                        "👶 *Layman* — plain English, terms translated\n"
                        "📚 *Seeker* (default) — scholarly with English glosses\n"
                        "🎓 *Scholar* — full apparatus, verbatim matn\n"
                        "_After every answer, tap [Simpler] / [Keep] / [Deeper] to adjust._\n\n"
                        "⚠️ I do not issue fiqh rulings (halal/haram). "
                        "Consult a qualified scholar for those."
                    )
                    print("  -> /start response sent")
                    continue

                if text == "/help":
                    send_message(chat_id,
                        "*Bayan — How to use* 📖\n\n"
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
                        "✅ Sahih · ⚠️ Hasan · ❌ Da'if\n\n"
                        "*Personalization:*\n"
                        "• `/madhhab shafii|hanafi|maliki|hanbali` — set your school for ikhtilaf re-ranking\n"
                        "• `/madhhab` — show current preference"
                    )
                    print("  -> /help response sent")
                    continue

                if text == "/clear":
                    sessions.pop(chat_id, None)
                    send_message(chat_id, "🔄 Conversation cleared. Ask me anything fresh.")
                    print("  -> /clear response sent")
                    continue

                # /review — admin-only scholar-verification export (#2746).
                # Unregistered (hidden) command; gated on MIZAN_ADMIN_CHAT_ID.
                if text == "/review" or text.startswith("/review "):
                    requester = str(chat_id)
                    if not ADMIN_CHAT_ID:
                        send_message(chat_id,
                            "🔒 /review is admin-only and no admin is configured yet.\n\n"
                            f"Your chat_id is `{requester}`.\n"
                            "Set `MIZAN_ADMIN_CHAT_ID` to this value in ai-scholar/.env "
                            "(or the launchd plist) and restart to enable.")
                        print(f"  -> /review unconfigured; reported chat_id {requester}")
                        continue
                    if requester != str(ADMIN_CHAT_ID):
                        send_message(chat_id, "🔒 This command is restricted to the operator.")
                        print(f"  -> /review denied for {requester}")
                        continue
                    handle_review_export(chat_id)
                    print("  -> /review export handled")
                    continue

                # /madhhab — set or query user's school preference
                if text.startswith("/madhhab"):
                    parts = text.split()
                    telegram_id = update.get("message", {}).get("from", {}).get("id")
                    if len(parts) == 1:
                        # Show current + menu
                        current = get_user_madhhab(telegram_id)
                        send_message(chat_id,
                            f"*Your school (madhhab):* `{current or 'not set (Shafi-i default)'}`\n\n"
                            "Set with one of:\n"
                            "• `/madhhab shafii`\n"
                            "• `/madhhab hanafi`\n"
                            "• `/madhhab maliki`\n"
                            "• `/madhhab hanbali`\n"
                            "• `/madhhab clear` — remove preference\n\n"
                            "_When set, I'll lead with your school's position on ikhtilaf questions._\n"
                            "_Note: my fiqh matn corpus is currently Shafi-i only — for non-Shafi-i users I'll flag school mismatches and route to a qualified scholar of your school rather than fabricate positions from memory._"
                        )
                    else:
                        arg = parts[1].lower().strip()
                        if arg == "clear":
                            set_user_madhhab(telegram_id, None)
                            send_message(chat_id, "✓ Madhhab preference cleared. I'll surface evidence without school-specific routing.")
                        elif arg in MADHHAB_VALID:
                            set_user_madhhab(telegram_id, arg)
                            send_message(chat_id,
                                f"✓ Madhhab set to *{arg.capitalize()}*.\n\n"
                                f"_From now on, ikhtilaf-class questions will lead with the {arg.capitalize()} position when retrievable._"
                            )
                        else:
                            send_message(chat_id,
                                f"❌ Unknown school: `{arg}`. Valid: shafii, hanafi, maliki, hanbali, clear."
                            )
                    print(f"  -> /madhhab handled (arg={parts[1] if len(parts) > 1 else 'show'})")
                    continue

                # CAI-RESP-287 class C — high-consequence / irreversible matters
                # (divorce, inheritance, apostasy) must NOT receive an AI ruling.
                # Route to a human scholar with care. Sits BEFORE the general
                # scholar gate so the more careful message wins. Persist first
                # (no Claude call here, so no user-perceptible latency) so the
                # question can be flagged into the scholar queue — flag-ONLY
                # keyboard (no level buttons: those would re-trigger an AI answer
                # on the very topic we're refusing to rule on).
                if match_high_stakes_query(text):
                    routing_msg = (
                        "⚠️ *This carries serious consequence.*\n\n"
                        "Questions touching divorce, inheritance, or other grave or "
                        "irreversible matters shouldn't rest on an AI draft — a mistake "
                        "here carries real spiritual and legal weight.\n\n"
                        "Please consult a qualified scholar (mufti) directly — in "
                        "Singapore, MUIS or an ARS-certified ustadh/ustazah.\n\n"
                        "_Tap below to flag this so a scholar can follow up, in shāʾ Allāh._"
                    )
                    hs_persist = persist_emission(chat_id, text, routing_msg)
                    hs_iid = hs_persist.get("interaction_id") if isinstance(hs_persist, dict) else None
                    hs_kb = None
                    if hs_iid:
                        hs_kb = {"inline_keyboard": [[
                            {"text": "🔖 Flag for scholar review",
                             "callback_data": f"flag:{hs_iid}"},
                        ]]}
                    send_message(chat_id, routing_msg, reply_markup=hs_kb)
                    print("  -> Class C high-stakes routing (consult-a-scholar)")
                    continue

                # Scholar gate — fires on ruling-class queries (halal/haram/fatwa)
                # but NOT on fiqh-topic queries (wudu/salah/etc.). Topic queries
                # route through juridical_translations retrieval downstream.
                # Gate message is source-agnostic per operator direction — don't
                # leak corpus contents to users; attribution is handled by
                # downstream quoted-passage rendering.
                if match_ruling_query(text):
                    send_message(chat_id,
                        "⚠️ *Scholar Gate*\n\n"
                        "This question involves a fiqh ruling that requires qualified scholarly judgment. "
                        "I can share relevant Quranic verses, hadith narrations, and authoritative scholarly references "
                        "for context, but I cannot issue rulings.\n\n"
                        "Please consult a qualified scholar (mufti) for a definitive answer.\n\n"
                        "_If you'd like, rephrase as a topic question — e.g., 'what is the position on X' "
                        "rather than 'is X halal'._"
                    )
                    print("  -> Scholar gate triggered (ruling-class query)")
                    continue

                # Process question — wrap in try/except so any unexpected error
                # (NameError in prompt-build, network blip, JSON parse, etc.) is
                # surfaced as a polite user-facing message rather than leaving
                # the user hanging while the outer polling loop just retries.
                try:
                    send_typing(chat_id)

                    # Detect follow-up
                    followup = is_followup(text, session)

                    retrieval_meta = RetrievalMeta()

                    if followup and session["last_context"]:
                        print("  Follow-up detected, reusing context...")
                        context = session["last_context"]

                        # Fix 4b: expand keywords to include last_topics when the
                        # follow-up introduces new entities not in last_topics
                        import re as _re2
                        current_words = [w for w in _re2.findall(r'\w+', text.lower())
                                         if w not in STOP_WORDS and len(w) > 2]
                        new_entities = [w for w in current_words
                                        if w not in (session.get("last_topics") or [])]
                        combined_keywords = (current_words[:3] + (session.get("last_topics") or [])[:3])

                        # Check if they want additional data on top
                        q_lower = text.lower()
                        if any(w in q_lower for w in ("hadith", "sunnah", "narrated")):
                            search_kw = combined_keywords if combined_keywords else (session.get("last_topics") or [])[:3]
                            if search_kw:
                                extra = search_hadith_fts(search_kw, limit=5)
                                if extra["results"]:
                                    retrieval_meta.add_hadith_hits(extra["results"])
                                    context += f"\n\n---\n\nADDITIONAL HADITH SEARCH:\n{json.dumps(extra, ensure_ascii=False, indent=2)}"
                        elif any(w in q_lower for w in ("verse", "ayah", "quran")):
                            search_kw = combined_keywords if combined_keywords else (session.get("last_topics") or [])[:4]
                            if search_kw:
                                fts_q = " OR ".join(search_kw[:4])
                                extra = search_quran(fts_q, limit=5)
                                if extra["results"]:
                                    context += f"\n\n---\n\nADDITIONAL QURAN SEARCH:\n{json.dumps(extra, ensure_ascii=False, indent=2)}"
                        elif new_entities and session.get("last_topics"):
                            # New entities in the followup → run a supplementary FTS
                            # to bring thematic context for those new terms
                            fts_q = " OR ".join(combined_keywords[:4])
                            extra = search_tafsir(fts_q, limit=3)
                            if extra["results"]:
                                retrieval_meta.add_tafsir_hits(extra["results"])
                                entries = []
                                for hit in extra["results"]:
                                    entries.append(
                                        f"Surah {hit['surah']} : Ayah {hit['ayah']}\n"
                                        f"Scholar: {hit['scholar']} ({hit['source']})\n"
                                        f"Passage: {hit['english_text']}"
                                    )
                                context += (
                                    "\n\n---\n\nSUPPLEMENTARY TAFSIR (combined current+prior topics):\n"
                                    + "\n\n".join(entries)
                                )

                        # Followup but with potential topic shift — re-run fiqh
                        # substrate retrieval if the new query has fiqh keywords
                        # so a new topic (e.g. fasting after wudu turn) surfaces
                        # fresh juridical_translations context. Without this, the
                        # bot reuses stale last_context and reports "matched data
                        # didn't include the section" even when the substrate has it.
                        if match_fiqh_query(text):
                            fiqh_data = lookup_fiqh(text, limit=3)
                            if fiqh_data["results"]:
                                retrieval_meta.add_juridical_hits(fiqh_data["results"])
                                entries = []
                                for hit in fiqh_data["results"]:
                                    entries.append(
                                        f"Source: {hit['source_work']}\n"
                                        f"Chapter: {hit['baab']}\n"
                                        f"Translator: {hit['translator']} ({hit['edition']})\n"
                                        f"Tier: {hit['tier']}\n"
                                        f"Passage:\n{hit['text']}"
                                    )
                                context += (
                                    "\n\n---\n\nFIQH MATCHED PASSAGES (followup-fresh — Shafi'i matn; "
                                    "RETRIEVE-ONLY echo per C4 + INV-7):\n\n"
                                    + "\n\n---\n\n".join(entries)
                                )
                    else:
                        print("  Gathering context...")
                        context = gather_context(text, meta=retrieval_meta)

                    msg_telegram_id = update.get("message", {}).get("from", {}).get("id")
                    user_madhhab = get_user_madhhab(msg_telegram_id)
                    print(f"  Asking Claude... (level={session['answer_level']}, madhhab={user_madhhab or 'none'})")
                    send_typing(chat_id)
                    # Fix #1: deterministic keyed-lookup fallback for verse/hadith
                    # display queries — used only if synthesis fails (no timeout
                    # non-answer for a trivial lookup).
                    keyed_fallback = build_keyed_answer(text)
                    answer = ask_claude(
                        text, context,
                        session["history"] if session["history"] else None,
                        answer_level=session["answer_level"],
                        madhhab=user_madhhab,
                        fallback_answer=keyed_fallback,
                    )
                    # Fix #2b: suppress any residual dev/test/pipeline self-narration
                    # before it reaches the user (root cause already removed via
                    # `--tools ""` + neutral cwd). Prefer the keyed answer; else ask
                    # to rephrase — never send the leaked meta-text.
                    _leak = detect_dev_leak(answer)
                    if _leak:
                        print(f"  -> DEV-LEAK GUARD tripped (marker={_leak!r}); suppressing meta-leaked answer")
                        answer = keyed_fallback or (
                            "Let me try that again — could you rephrase your question? I want to "
                            "answer from the Qur'an, tafsir, and hadith directly."
                        )

                    # Update session
                    add_to_history(session, "user", text)
                    add_to_history(session, "assistant", answer)
                    # Track new question — clear any prior per-level cache so the
                    # next callback adjustment regenerates against the new query.
                    if session.get("last_query") != text:
                        session["level_responses"] = {}
                    session["last_query"] = text
                    session["last_context"] = context
                    # Durable copy so a level-button tap survives a restart/TTL prune.
                    save_chat_state(chat_id, text, session["answer_level"])
                    import re as _re
                    session["last_topics"] = [w for w in _re.findall(r'\w+', text.lower())
                                              if w not in STOP_WORDS and len(w) > 2]

                    cited = _extract_cited_verses(answer)
                    msg_id = send_message(chat_id, answer + AI_DRAFT_DISCLAIMER, reply_markup=_level_keyboard(session["answer_level"], cited_verses=cited))
                    if msg_id:
                        session["level_responses"][session["answer_level"]] = msg_id
                    print(f"  -> Response sent ({len(answer)} chars, audio buttons: {len(cited)})")
                    print(f"  >> {answer[:300]}{'...' if len(answer) > 300 else ''}")

                    # AL-BAYAN-COMPOSE-001 producer wiring per CAI-RESP-135 — persist after send,
                    # fail-soft so persistence outages don't block user replies.
                    # F-2 (tafsir-defense-funnel): thread matched_passage_id + retrieval_ids
                    # collected from this turn's retrievals so the audit row reflects reality.
                    persist_result = persist_emission(
                        chat_id, text, answer,
                        retrieval_ids=retrieval_meta.retrieval_ids,
                        matched_passage_id=retrieval_meta.matched_passage_id,
                        retrieval_config=retrieval_meta.retrieval_config,
                    )
                    # #2746: add the scholar-review flag button now that we have
                    # the interaction_id (persist runs after send per RESP-135).
                    _maybe_add_flag_button(chat_id, msg_id, session["answer_level"], cited, persist_result)

                    # MIZAN-REENGAGE-01 (CAI-RESP-396): if THIS answer was a genuine
                    # failure (timeout-stub / evidence-fallback), queue ONE courteous
                    # follow-up for when the pipeline can answer it well. INERT until
                    # migration 20260708_001 is applied AND MIZAN_FOLLOWUP_ENABLED=1 —
                    # enqueue_if_eligible() no-ops before any DB write otherwise, and a
                    # send-worthy answer classifies as no-op (G1). Fail-soft: a follow-up
                    # bookkeeping problem must never break the user's reply.
                    try:
                        import mizan_followup as _followup
                        _iid = persist_result.get("interaction_id") if isinstance(persist_result, dict) else None
                        _followup.enqueue_if_eligible(chat_id, text, answer, interaction_id=_iid)
                    except Exception as _fe:
                        print(f"  -> followup enqueue skipped ({type(_fe).__name__})")
                except Exception as msg_err:
                    # Per-message exception handler — don't leave user hanging.
                    err_short = type(msg_err).__name__
                    print(f"  -> per-message error ({err_short}): {msg_err}")
                    import traceback
                    traceback.print_exc()
                    try:
                        send_message(chat_id,
                            "⚠️ I hit a technical issue processing that question. "
                            "The error has been logged for review. "
                            "Please try rephrasing your question, or come back in a moment."
                        )
                    except Exception as send_err:
                        print(f"  -> failed to send error notification: {send_err}")

        except urllib.error.URLError as e:
            print(f"Network error: {e}. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"Error: {e}. Retrying in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    main()
