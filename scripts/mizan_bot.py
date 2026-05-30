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

# Phase 2 semantic-first retrieval for fiqh substrate.
# Architectural pivot per CAI-PROCESS-GLUE-AUDIT-MIZANBOT-001 (id 870) hybrid
# ruling — lifts the freeze marker once shipped + validated.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fiqh_semantic  # noqa: E402

# --- Config ---
BOT_TOKEN = os.environ.get("MIZAN_BOT_TOKEN", "")
SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzY3V5bWF2eXNzY3J2b2JlcnJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzMjEzOTQsImV4cCI6MjA4OTg5NzM5NH0.qO3XH34pDVhlxDRcKs_TBaOJtoxGiAJGBLfGpThzyDw"
CLAUDE_PATH = os.path.expanduser("~/.local/bin/claude")
# AL-BAYAN-COMPOSE-001 producer wiring per CAI-RESP-135
PERSIST_FUNCTION_URL = SUPABASE_URL + "/functions/v1/persist-mizan-ruling"


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
        # Al-Fatihah
        "fatiha": 1, "fatihah": 1, "al fatiha": 1, "al fatihah": 1,
        "al-fatiha": 1, "al-fatihah": 1, "fatiha": 1, "opening": 1,
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

    # Check special verse shortcuts first
    for key, val in SPECIAL_VERSES.items():
        if key in t_clean or key in t:
            return val  # returns tuple (surah, ayah)

    best_len = 0
    best_num = None
    for alias, num in SURAH_ALIASES.items():
        # Try as substring
        if alias in t_clean or alias in t:
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
        sessions[chat_id] = {
            "history": [],
            "last_query": "",
            "last_context": "",
            "last_topics": [],
            "last_active": now,
            "answer_level": "seeker",       # layman | seeker | scholar (default seeker)
            "level_responses": {},          # level → telegram message_id (for the
                                            # last_query at that level; cleared when
                                            # last_query changes; lets callback handler
                                            # reply-point to existing answers instead
                                            # of regenerating).
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
        if tafsir_intent:
            surah_name = SURAH_NAMES.get(resolved_surah, f"Surah {resolved_surah}")
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
            if tdata["results"]:
                if meta is not None:
                    meta.add_tafsir_hits(tdata["results"])
                entries = []
                for hit in tdata["results"]:
                    entries.append(
                        f"Surah {hit['surah']} : Ayah {hit['ayah']}\n"
                        f"Scholar: {hit['scholar']} ({hit['source']})\n"
                        f"Tier: {hit['tier']}\n"
                        f"Passage: {hit['english_text']}"
                    )
                context_parts.append(
                    "TAFSIR MATCHED PASSAGES (scholar-attributed, from tafsir_entries FTS):\n"
                    + "\n\n".join(entries)
                )

        # Hadith FTS (always search if question wants it, or as supplement)
        # Gap A/B/C fix: use search_hadith_fts_v2 with collection + narrator preferences
        # and AND-mode multi-keyword search (with OR fallback if AND < 3 results).
        has_hadith = any("HADITH" in p for p in context_parts)
        if not has_hadith and _ctx_size(context_parts) < MAX_CONTEXT:
            hlimit = 5 if wants_hadith else 3
            data = search_hadith_fts_v2(
                words[:4],
                limit=hlimit,
                preferred_collection_id=preferred_collection_id,
                preferred_narrator=preferred_narrator,
                mode="auto",
            )
            if data["results"]:
                if meta is not None:
                    meta.add_hadith_hits(data["results"])
                label = "HADITH SEARCH" if wants_hadith else "RELATED HADITHS"
                context_parts.append(f"{label}:\n{json.dumps(data, ensure_ascii=False, indent=2)}")

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
            fiqh_data = fiqh_semantic.search_semantic(question, limit=3)
        except Exception:
            fiqh_data = {"results": []}
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


def ask_claude(question, context, history=None, answer_level="seeker"):
    """Use Claude Code CLI to reason over the context.

    answer_level: 'layman' | 'seeker' (default) | 'scholar' — controls audience-tier
    guidance injected into the system prompt. Per-session preference adjustable via
    Telegram inline keyboard buttons appended to every response.
    """
    history_block = ""
    if history:
        turns = []
        for h in history:
            prefix = "User" if h["role"] == "user" else "Mizan"
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

    prompt = f"""You are Mizan (Al-Bayan), an Islamic knowledge assistant. A user asked:

"{question}"
{history_block}
{level_block}

(The AUDIENCE TIER guidance above takes precedence over the RULES below on the
same topic — e.g., if AUDIENCE TIER says "skip verbatim matn unless directly
answering" then the RULE about "always surface matn" is overridden for THIS tier.)

Here is the relevant data from the Quran, tafsir, and hadith database:

{context}

RULES:
- Use ONLY the provided data to answer. Do not make up verses, tafsir, or hadiths.
- NEVER issue fiqh rulings.
- WHENEVER a "FIQH MATCHED PASSAGES" block is present in the context above,
  you MUST surface the matn passage in your response. Do not omit or summarize
  it — quote VERBATIM with full attribution: "Safīnat al-Najā (<Chapter>,
  al-Marbūqī tr., al-inaam.com 2009)" where <Chapter> is the baab name from
  the FIQH MATCHED PASSAGES block. The matn is the Shafi'i school's specific
  application of higher-tier evidence (Quran/hadith); both should be presented
  side-by-side when relevant — Quran/hadith establish the principle, the matn
  shows the school's juristic framing. Do NOT synthesize a new ruling from
  these passages. After each matn quotation, append:
  "This passage is from the Shafi'i primer for reference; consult a qualified
  scholar for application to your specific situation."
- Telegram message budget: aim for under 3900 chars total (hard limit is 4096).
  PRIORITY when fitting: surface the FULL matn enumeration verbatim — never
  summarize an arkan/wajibat/shurut/mubtilat/nawaqid list, never drop items
  mid-enumeration, never use "etc." or "..." in place of listed integrals.
  If space is tight, shorten the reflective question or drop tangential
  hadith — never abbreviate the matn integrals.
- Include Arabic text when showing Quranic verses.
- End with a reflective question (practice off-ramp) to move knowledge toward action.
- If the data doesn't answer the question, say so honestly.
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
    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            return f"I encountered an issue processing your question. Error: {result.stderr[:200] if result.stderr else 'unknown'}"
    except subprocess.TimeoutExpired:
        return ("I'm taking longer than usual to think this through — the topic needs careful "
                "consideration. Try asking again, or rephrase as a more specific question.")
    except Exception as e:
        return f"Error: {str(e)}"


# --- Persistence helper (AL-BAYAN-COMPOSE-001 / CAI-RESP-135) ---
def persist_emission(chat_id, query_text, response_text, retrieval_ids=None, matched_passage_id=None):
    """POST to persist-mizan-ruling Edge Function.

    Fail-soft: log on error, never raise. Bot's user-facing UX must not break
    if persistence is unavailable. Per CAI-RESP-135, governance integrity is
    critical but bot responsiveness is not negotiable mid-conversation.

    F-2 (tafsir-defense-funnel): retrieval_ids carries the union of every
    retrieval row ID that grounded the response (tafsir ayah_ids, juridical_text_ids,
    hadith ids). matched_passage_id is the top tafsir hit's ayah_id when
    search_tafsir_fts returned ≥1 row, else null.
    """
    payload = {
        "telegram_id": chat_id,
        "query_text": query_text[:2000],   # keep request small
        "response_text": response_text[:5000],
        "retrieval_ids": retrieval_ids or [],
        "matched_passage_id": matched_passage_id,
    }
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


def _level_keyboard(current_level):
    """Inline keyboard for audience-tier adjustment. Context-aware:
      layman   → [✓ Current: Layman] [🎓 More detail]
      seeker   → [👶 Simpler] [✓ Current: Seeker] [🎓 More detail]
      scholar  → [👶 Simpler] [✓ Current: Scholar]
    The "Current" button is informational (tapping it = keep, no re-ask).
    Simpler/Deeper buttons only appear when there's a direction to go.
    """
    buttons = []
    if current_level != "layman":
        buttons.append({"text": "👶 Simpler", "callback_data": "level:layman" if current_level == "seeker" else "level:seeker"})
    current_label = current_level.capitalize()
    buttons.append({"text": f"✓ Current: {current_label}", "callback_data": "level:keep"})
    if current_level != "scholar":
        buttons.append({"text": "🎓 More detail", "callback_data": "level:scholar" if current_level == "seeker" else "level:seeker"})
    return {"inline_keyboard": [buttons]}


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
                "allowed_updates": ["message", "callback_query"],
            })

            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                # --- Inline-keyboard callback for audience-tier adjustment ---
                cb = update.get("callback_query")
                if cb:
                    cb_id = cb.get("id")
                    cb_data = cb.get("data", "")
                    cb_chat = (cb.get("message") or {}).get("chat", {}).get("id")
                    cb_user = cb.get("from", {}).get("first_name", "?")
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
                        answer = ask_claude(
                            last_q, context,
                            session["history"] if session["history"] else None,
                            answer_level=new_level,
                        )
                        # Don't append to history a second time — just update last_*
                        session["last_context"] = context
                        msg_id = send_message(cb_chat, answer, reply_markup=_level_keyboard(new_level))
                        if msg_id:
                            session.setdefault("level_responses", {})[new_level] = msg_id
                        print(f"  -> Reformatted response sent ({len(answer)} chars) at {new_level}")
                        persist_emission(
                            cb_chat, last_q, answer,
                            retrieval_ids=retrieval_meta.retrieval_ids,
                            matched_passage_id=retrieval_meta.matched_passage_id,
                        )
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

                    print(f"  Asking Claude... (level={session['answer_level']})")
                    send_typing(chat_id)
                    answer = ask_claude(
                        text, context,
                        session["history"] if session["history"] else None,
                        answer_level=session["answer_level"],
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
                    import re as _re
                    session["last_topics"] = [w for w in _re.findall(r'\w+', text.lower())
                                              if w not in STOP_WORDS and len(w) > 2]

                    msg_id = send_message(chat_id, answer, reply_markup=_level_keyboard(session["answer_level"]))
                    if msg_id:
                        session["level_responses"][session["answer_level"]] = msg_id
                    print(f"  -> Response sent ({len(answer)} chars)")
                    print(f"  >> {answer[:300]}{'...' if len(answer) > 300 else ''}")

                    # AL-BAYAN-COMPOSE-001 producer wiring per CAI-RESP-135 — persist after send,
                    # fail-soft so persistence outages don't block user replies.
                    # F-2 (tafsir-defense-funnel): thread matched_passage_id + retrieval_ids
                    # collected from this turn's retrievals so the audit row reflects reality.
                    persist_emission(
                        chat_id, text, answer,
                        retrieval_ids=retrieval_meta.retrieval_ids,
                        matched_passage_id=retrieval_meta.matched_passage_id,
                    )
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
