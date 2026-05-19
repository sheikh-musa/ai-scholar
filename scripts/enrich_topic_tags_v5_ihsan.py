#!/usr/bin/env python3
"""
V5 Ihsan-grade topic tag enrichment — deep tafsir + asbab + mutashabihat.

Differences from v4:
  - Pulls ALL tafsir_entries per ayah (4 scholars: Ibn Kathir, Al-Sa'di,
    Al-Jalalayn, Al-Qurtubi) at 1500 chars each (v4 used 4×500).
  - Includes asbab al-nuzul block when present (1187 rows, ~19% coverage).
  - Includes mutashabihat cross-references when present.
  - Output schema: JSON object with tags + reasoning_trail + confidence
    (v4 returned bare tags array).
  - Stricter classifier bar: 15-20 tags, >=5 markers, required asbab tag
    when asbab present, required cross-ref tag when mutashabihat present.
  - Re-tags ALL ayat by default (no completed_ids inheritance). Use
    `--resume` flag to honor .v5_checkpoint.json completed_ids.

Usage:
  python3 scripts/enrich_topic_tags_v5_ihsan.py audit         # classify v5-bar, no Claude
  python3 scripts/enrich_topic_tags_v5_ihsan.py run [--limit N] [--resume]
  python3 scripts/enrich_topic_tags_v5_ihsan.py status
  python3 scripts/enrich_topic_tags_v5_ihsan.py sample N

Resumability: scripts/.v5_checkpoint.json. Throttle log: scripts/.v5_log.jsonl.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
CLAUDE_ENV = {
    "HOME": os.path.expanduser("~"),
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "USER": os.environ.get("USER", ""),
    "SHELL": os.environ.get("SHELL", ""),
    "LANG": os.environ.get("LANG", ""),
}

CHECKPOINT_PATH = Path(__file__).parent / ".v5_checkpoint.json"
LOG_PATH = Path(__file__).parent / ".v5_log.jsonl"


def checkpoint_path(worker_id=None):
    """Worker-aware checkpoint path. Single-worker uses .v5_checkpoint.json;
    multi-worker uses .v5_checkpoint.W{N}.json to avoid concurrent writes."""
    if worker_id is None:
        return CHECKPOINT_PATH
    return CHECKPOINT_PATH.parent / f".v5_checkpoint.W{worker_id}.json"


def log_path(worker_id=None):
    if worker_id is None:
        return LOG_PATH
    return LOG_PATH.parent / f".v5_log.W{worker_id}.jsonl"

# ---------------------------------------------------------------------------
# Tafsir-style markers (shared definition with v4)
# ---------------------------------------------------------------------------

TAFSIR_TERMS = {
    "tawhid", "shirk", "iman", "kufr", "ihsan", "taqwa", "tawakkul", "ikhlas",
    "yaqeen", "khushu", "khashyah", "muraqabah",
    "tafsir", "tawil", "qira'at", "qiraat", "naskh", "mansukh", "muhkam",
    "mutashabih", "mutashabihat", "asbab al-nuzul", "asbab", "iltifat", "majaz",
    "haqiqah", "balaghah", "i'jaz", "rasm", "tanzeel",
    "fiqh", "usul", "hadith", "sunnah", "sirah", "ijma", "qiyas", "ijtihad",
    "halal", "haram", "wajib", "fard", "mubah", "makruh", "mustahab",
    "madhhab", "shafi", "hanafi", "maliki", "hanbali",
    "rahma", "rahman", "rahim", "wahdat", "wahdaniyyah", "rububiyyah", "uluhiyyah",
    "akhirah", "dunya", "barzakh", "qiyamah", "hashr", "yawm", "jannah",
    "jahannam", "sirat", "mizan", "shafa'ah",
    "salah", "zakat", "siyam", "hajj", "umrah", "ibadah", "dhikr", "dua",
    "wudu", "ghusl", "tayammum", "qiblah", "kaaba",
    "al-hayy", "al-qayyum", "al-quddus", "al-hakeem", "al-aleem", "al-wadud",
    "al-ghafoor", "al-tawwab", "al-azeem", "al-jabbar", "al-mutakabbir",
    "asma al-husna", "asma'", "sifat",
    "sahaba", "sahabah", "tabieen", "salaf", "ulama", "imam", "shaykh",
    "ibrahim", "musa", "isa", "muhammad", "khadijah", "ayesha", "umar",
    "abu bakr", "ali", "uthman",
    "ayat", "surah", "juz", "manzil", "hizb", "ruku", "sajdah", "rukoo",
    "ghaib", "ghayb", "barakah", "bid'ah", "fitnah", "fitna", "jihad",
    "tawbah", "istighfar", "shahada", "kalimah", "ummah", "mu'min", "muslim",
    "munafiq", "kafir", "mushrik", "abd",
}


def has_tafsir_marker(tag: str) -> bool:
    t = tag.lower().strip()
    if not t:
        return False
    if t.startswith("al-") or " al-" in t:
        return True
    if "'" in t:
        return True
    if re.search(r"\b[a-z]+-[a-z]+\b", t) and t not in {"day-of-judgment", "step-by-step", "ahl-al-bayt"}:
        if any(c in t for c in ["a", "i", "u"]) and len(t) > 5:
            return True
    tokens = re.findall(r"[a-z']+", t)
    return any(tok in TAFSIR_TERMS for tok in tokens)


def classify_v5(tags: list, asbab_present: bool, mutashabihat_present: bool) -> str:
    """v5 bar: KEEP iff tag_count>=15 AND markers>=5 AND
       asbab-tag-if-asbab AND mutashabihat-tag-if-mutashabihat."""
    if not tags:
        return "EMPTY"
    if len(tags) < 15:
        return "RETAG"
    markers = sum(1 for t in tags if has_tafsir_marker(t))
    if markers < 5:
        return "RETAG"
    if asbab_present and not any("asbab" in t.lower() or "occasion" in t.lower() or "revealed" in t.lower() for t in tags):
        return "RETAG"
    if mutashabihat_present and not any("parallel" in t.lower() or "mutashab" in t.lower() or "cross-ref" in t.lower() for t in tags):
        return "RETAG"
    return "KEEP"


# ---------------------------------------------------------------------------
# Supabase REST
# ---------------------------------------------------------------------------

def api_get_all(path):
    rows = []
    offset = 0
    while True:
        sep = "&" if "?" in path else "?"
        url = f"{SUPABASE_URL}/rest/v1/{path}{sep}limit=1000&offset={offset}"
        req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req) as resp:
            chunk = json.loads(resp.read())
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    return rows


def api_get(path):
    sep = "&" if "?" in path else "?"
    url = f"{SUPABASE_URL}/rest/v1/{path}{sep}limit=1000"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_patch(table, row_id, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req)


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint(worker_id=None):
    path = checkpoint_path(worker_id)
    if not path.exists():
        return {"completed_ids": [], "started_at": None,
                "stats": {"keep": 0, "retag": 0, "empty": 0, "succeeded": 0, "failed": 0,
                          "with_asbab": 0, "with_mutashabihat": 0}}
    return json.loads(path.read_text())


def save_checkpoint(cp, worker_id=None):
    cp["updated_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint_path(worker_id).write_text(json.dumps(cp, indent=2))


def load_peer_completed_ids(worker_id, num_workers):
    """Read other workers' checkpoint files to avoid re-processing ayat
    they've already done (e.g., when this worker resumes after a peer
    completed some of its work range)."""
    peers = set()
    for w in range(num_workers):
        if w == worker_id:
            continue
        peer = checkpoint_path(w)
        if peer.exists():
            try:
                peers.update(json.loads(peer.read_text()).get("completed_ids", []))
            except Exception:
                pass
    # Also include single-worker checkpoint (.v5_checkpoint.json) since the
    # original single-worker run wrote 25 ayat there before we partitioned.
    if CHECKPOINT_PATH.exists():
        try:
            peers.update(json.loads(CHECKPOINT_PATH.read_text()).get("completed_ids", []))
        except Exception:
            pass
    return peers


def log_event(event, worker_id=None):
    event["t"] = datetime.now(timezone.utc).isoformat()
    with log_path(worker_id).open("a") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Cross-reference resolution
# ---------------------------------------------------------------------------

SURAH_NAMES = {1:"Al-Fatiha",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiya",46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahina",61:"As-Saff",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddathir",75:"Al-Qiyamah",76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"}


_position_to_ayah_cache = None  # maps 1-6236 global Quran index -> ayah row


def build_position_map(all_ayat: list) -> dict:
    """Map mutashabihat numeric position (1..6236) to ayah row.

    Assumes mutashabihat.src_ayah / similar_ayah are 1-indexed in canonical
    surah,ayah order. all_ayat must come in (surah_number, ayah_number) sort.
    """
    return {i + 1: a for i, a in enumerate(all_ayat)}


# ---------------------------------------------------------------------------
# v5 Prompt — deep tafsir + asbab + mutashabihat
# ---------------------------------------------------------------------------

def build_prompt(ayah, tafsir_rows, asbab_row, mutashabihat_refs):
    """v5 prompt. mutashabihat_refs is a list of (surah, ayah, translation_excerpt)."""
    surah_name = SURAH_NAMES.get(ayah["surah_number"], f"Surah {ayah['surah_number']}")

    # All 4 tafsir scholars at 1500 chars each
    tafsir_block = ""
    if tafsir_rows:
        for t in tafsir_rows:
            text = (t.get("english_text") or "")[:1500]
            scholar = t.get("scholar_name") or "Unknown"
            tafsir_block += f"\n[{scholar}]:\n{text}\n"
    else:
        tafsir_block = "(no tafsir available)"

    asbab_block = ""
    if asbab_row and asbab_row.get("text_en"):
        src = asbab_row.get("source", "?")
        asbab_block = f"\n\nASBAB AL-NUZUL ({src}):\n{asbab_row['text_en'][:1500]}\n"

    mutashabihat_block = ""
    if mutashabihat_refs:
        mutashabihat_block = "\n\nPARALLEL VERSES (mutashabihat):\n"
        for s, a, excerpt in mutashabihat_refs[:5]:
            sname = SURAH_NAMES.get(s, f"Surah {s}")
            mutashabihat_block += f"  - {sname} {s}:{a} — {(excerpt or '')[:200]}\n"

    existing = ", ".join((ayah.get("topic_tags") or [])[:15])
    existing_block = f"\n\nEXISTING v3/v4 TAGS (improve or replace):\n{existing}\n" if existing else ""

    return f"""Generate v5 Ihsan-grade topic tags for Quran verse {surah_name} ({ayah['surah_number']}:{ayah['ayah_number']}).

ARABIC: {(ayah.get('arabic_text') or '').strip()[:600]}
TRANSLATION: {ayah.get('english_translation', '(missing)')}

SCHOLARLY COMMENTARY (4 sources):
{tafsir_block}
{asbab_block}{mutashabihat_block}{existing_block}

Tags must reflect:
1. Literal meaning of the verse
2. Themes scholars derive from it (synthesize ACROSS the 4 tafsirs)
3. Practical questions a Muslim would ask where this verse is the answer
4. Specific Islamic concepts (Arabic transliteration: tawhid, taqwa, ikhlas, etc.)
5. Linguistic devices if salient (iltifat, tashbih, kinaayah, majaz)
6. Cross-references — names, prophetic stories, parallel ayat, asbab al-nuzul
{"7. Asbab al-nuzul context (mandatory: at least one tag must reference the revelation occasion)" if asbab_row else ""}
{"8. Mutashabihat parallel (mandatory: at least one cross-ref tag)" if mutashabihat_refs else ""}

Output schema — return ONLY this JSON object, no commentary, no markdown:
{{
  "tags": [ ...15 to 20 lowercase strings... ],
  "reasoning_trail": "one-sentence trace of how scholar commentary shaped the tag choices",
  "confidence": "high" | "medium" | "low"
}}

Tag rules:
- 15-20 tags total
- At least 5 tags must use tafsir-aware terminology (Arabic transliteration, al- prefix, classical terms)
- Mix general English + specific classical / transliteration
- Retrievable: a person searching for X via tag X should find this verse

Output the JSON object now:"""


# ---------------------------------------------------------------------------
# Claude CLI invocation (throttle-aware, inherited from v4 with v5 model)
# ---------------------------------------------------------------------------

_THROTTLE_MARKERS = (
    "rate limit", "rate_limit", "ratelimit",
    "too many requests", "429",
    "usage limit", "usage_limit",
    "throttl",
    "quota", "exceeded",
)


def _is_throttle_error(stderr_text: str, returncode: int = 1) -> bool:
    s = (stderr_text or "").strip().lower()
    if any(m in s for m in _THROTTLE_MARKERS):
        return True
    if returncode != 0 and len(s) < 50:
        return True
    return False


def call_claude(prompt, timeout=120, max_throttle_retries=12, model=None, save_cp_fn=None):
    """Call claude -p with optional model override, throttle-aware backoff.

    Backoff schedule (calibrated for Max-plan 4h rolling window — 5-hour
    rolling cap with up to ~3h+ wait when window is exhausted):
      60s, 120s, 240s, 480s, 960s, 1800s, 1800s, 1800s, 1800s, 1800s, 1800s, 1800s
    Total max wait ≈ 4.3h (covers 4h-window reset + safety margin).

    save_cp_fn (optional): called before each backoff sleep ≥ 600s. Lets
    workers persist progress before long sleeps so a kill / reboot during
    a window-exhausted backoff doesn't lose the last batch of ayat.
    """
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "text"]
    if model:
        cmd.extend(["--model", model])
    for attempt in range(max_throttle_retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=CLAUDE_ENV)
        except subprocess.TimeoutExpired:
            return None, None, f"timeout after {timeout}s"

        if result.returncode != 0:
            err = f"returncode={result.returncode}: {result.stderr[:200]}"
            if _is_throttle_error(result.stderr, result.returncode) and attempt < max_throttle_retries:
                # Cap each attempt's wait at 30 min. After exponential climb
                # plateaus at the cap, subsequent attempts just re-wait 30 min,
                # giving long total coverage without unbounded sleeps.
                backoff = min(60 * (2 ** attempt), 1800)
                print(f"  [throttle detected, backing off {backoff}s — attempt {attempt + 1}/{max_throttle_retries}]")
                if backoff >= 600 and save_cp_fn is not None:
                    try:
                        save_cp_fn()
                        print(f"  [checkpoint saved before {backoff}s sleep]")
                    except Exception as cp_err:
                        print(f"  [checkpoint save failed: {cp_err}]")
                time.sleep(backoff)
                continue
            return None, None, err

        output = result.stdout.strip()
        # Try parse as JSON object {tags, reasoning_trail, confidence}
        try:
            obj = json.loads(output)
            if isinstance(obj, dict) and isinstance(obj.get("tags"), list):
                return obj, None, None
        except json.JSONDecodeError:
            pass
        # Regex-extract a {...} block
        m = re.search(r"\{.*\}", output, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict) and isinstance(obj.get("tags"), list):
                    return obj, None, None
            except json.JSONDecodeError:
                return None, None, "regex-extracted JSON parse failed"
        return None, None, "no JSON object in output"

    return None, None, f"throttle backoff exhausted after {max_throttle_retries} retries"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _load_indices():
    """Load asbab + mutashabihat indices once at startup."""
    print("Loading asbab_nuzul index...")
    asbab_rows = api_get_all("asbab_nuzul?select=surah_number,ayah_number_surah,text_en,source")
    asbab_by_key = {(r["surah_number"], r["ayah_number_surah"]): r for r in asbab_rows}
    print(f"  {len(asbab_by_key)} asbab entries")

    print("Loading mutashabihat index...")
    mut_rows = api_get_all("mutashabihat?select=src_ayah,similar_ayah,show_context")
    mut_by_src = {}
    for r in mut_rows:
        mut_by_src.setdefault(r["src_ayah"], []).append(r["similar_ayah"])
    print(f"  {len(mut_rows)} mutashabihat pairs, {len(mut_by_src)} distinct src positions")
    return asbab_by_key, mut_by_src


def _resolve_mutashabihat(ayah_position, mut_by_src, position_map):
    """Given a 1-6236 position, return list of (surah, ayah, translation) parallels."""
    refs = []
    sims = mut_by_src.get(ayah_position, [])
    for sim_pos in sims[:5]:
        sim_ayah = position_map.get(sim_pos)
        if sim_ayah:
            refs.append((sim_ayah["surah_number"], sim_ayah["ayah_number"], sim_ayah.get("english_translation", "")))
    return refs


def cmd_audit(_args):
    rows = api_get_all("ayat?select=id,surah_number,ayah_number,topic_tags&order=surah_number,ayah_number")
    asbab_by_key, mut_by_src = _load_indices()
    counts = {"KEEP": 0, "RETAG": 0, "EMPTY": 0}
    for i, r in enumerate(rows, start=1):
        asbab_present = (r["surah_number"], r["ayah_number"]) in asbab_by_key
        mut_present = i in mut_by_src
        v = classify_v5(r.get("topic_tags") or [], asbab_present, mut_present)
        counts[v] += 1
    print(f"\nTotal ayat: {len(rows)} (under v5 bar)")
    for k in ("KEEP", "RETAG", "EMPTY"):
        print(f"  {k}: {counts[k]} ({100*counts[k]/len(rows):.1f}%)")
    return 0


def cmd_status(_args):
    cp = load_checkpoint()
    print(json.dumps(cp, indent=2)[:2000])
    return 0


def cmd_run(args):
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    resume = "--resume" in args
    model = None
    if "--model" in args:
        model = args[args.index("--model") + 1]
    worker_id = None
    num_workers = 1
    if "--worker-id" in args:
        worker_id = int(args[args.index("--worker-id") + 1])
    if "--num-workers" in args:
        num_workers = int(args[args.index("--num-workers") + 1])

    print("=" * 60)
    suffix = f" worker={worker_id}/{num_workers}" if worker_id is not None else ""
    print(f"V5 Ihsan-grade enrichment — model={model or 'default'} resume={resume}{suffix}")
    print("=" * 60)

    cp = load_checkpoint(worker_id)
    if cp.get("started_at") is None:
        cp["started_at"] = datetime.now(timezone.utc).isoformat()
    own_completed = set(cp.get("completed_ids", [])) if resume else set()
    peer_completed = load_peer_completed_ids(worker_id, num_workers) if worker_id is not None else set()
    completed = own_completed | peer_completed

    all_ayat = api_get_all("ayat?select=id,surah_number,ayah_number,arabic_text,english_translation,topic_tags&order=surah_number,ayah_number")
    position_map = build_position_map(all_ayat)
    asbab_by_key, mut_by_src = _load_indices()

    work = []
    for i, r in enumerate(all_ayat, start=1):
        if r["id"] in completed:
            continue
        # Worker-partition: stripe by position modulo num_workers
        if worker_id is not None and (i - 1) % num_workers != worker_id:
            continue
        work.append((i, r))

    print(f"Total: {len(all_ayat)} | Own completed: {len(own_completed)} | Peer completed: {len(peer_completed)}")
    print(f"Work remaining for this worker: {len(work)}")
    if limit:
        work = work[:limit]
        print(f"Limit applied: processing {len(work)}")
    save_checkpoint(cp, worker_id)

    if not work:
        print("Nothing to do.")
        return 0

    for idx, (position, ayah) in enumerate(work):
        try:
            tafsir = api_get(f"tafsir_entries?ayah_id=eq.{ayah['id']}&select=scholar_name,english_text")
        except Exception as e:
            log_event({"ayah_id": ayah["id"], "error": f"tafsir fetch: {e}"}, worker_id)
            tafsir = []

        asbab_row = asbab_by_key.get((ayah["surah_number"], ayah["ayah_number"]))
        mut_refs = _resolve_mutashabihat(position, mut_by_src, position_map)

        prompt = build_prompt(ayah, tafsir, asbab_row, mut_refs)
        # Bound a checkpoint-saver closure for throttle-aware long sleeps.
        obj, _, err = call_claude(
            prompt, model=model,
            save_cp_fn=lambda cp=cp, wid=worker_id: save_checkpoint(cp, wid),
        )

        if obj is None or not isinstance(obj.get("tags"), list) or len(obj["tags"]) < 12:
            log_event({"ayah_id": ayah["id"], "ref": f"{ayah['surah_number']}:{ayah['ayah_number']}", "error": err or "tags<12"}, worker_id)
            cp["stats"]["failed"] += 1
            print(f"  [{idx+1}/{len(work)}] {ayah['surah_number']}:{ayah['ayah_number']} ✗ {err}")
        else:
            tags = [str(t).lower() for t in obj["tags"][:20]]
            try:
                api_patch("ayat", ayah["id"], {"topic_tags": tags})
                cp["stats"]["succeeded"] += 1
                if asbab_row:
                    cp["stats"]["with_asbab"] += 1
                if mut_refs:
                    cp["stats"]["with_mutashabihat"] += 1
                own_completed.add(ayah["id"])
                cp["completed_ids"] = list(own_completed)
                marker_count = sum(1 for t in tags if has_tafsir_marker(t))
                conf = obj.get("confidence", "?")
                a_mark = "A" if asbab_row else "-"
                m_mark = f"M{len(mut_refs)}" if mut_refs else "-"
                w_pfx = f"W{worker_id} " if worker_id is not None else ""
                print(f"  {w_pfx}[{idx+1}/{len(work)}] {ayah['surah_number']}:{ayah['ayah_number']} ✓ {len(tags)} tags ({marker_count} markers, {len(tafsir)} tafsir, {a_mark}/{m_mark}, conf={conf})")
            except Exception as e:
                log_event({"ayah_id": ayah["id"], "error": f"patch: {e}"}, worker_id)
                cp["stats"]["failed"] += 1

        if (idx + 1) % 10 == 0:
            save_checkpoint(cp, worker_id)
        time.sleep(0.5)

    save_checkpoint(cp, worker_id)
    print(f"\n=== v5 Run complete ===")
    print(json.dumps(cp["stats"], indent=2))
    return 0


SUBCOMMANDS = {"audit": cmd_audit, "run": cmd_run, "status": cmd_status}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        sys.stderr.write(f"usage: {sys.argv[0]} {{{' | '.join(SUBCOMMANDS)}}} [args...]\n")
        sys.exit(2)
    sys.exit(SUBCOMMANDS[sys.argv[1]](sys.argv[2:]) or 0)


if __name__ == "__main__":
    main()
