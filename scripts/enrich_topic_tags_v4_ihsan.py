#!/usr/bin/env python3
"""
V4 Ihsan-grade topic tag enrichment.

Goals (per user direction 2026-04-28):
  - Go through entire Quran in the spirit of ihsan (excellence, not just completion)
  - Skip ayat we're confident are correctly tagged
  - Re-tag everything else with the v3 tafsir-aware prompt (or stronger)

Quality bar (KEEP):
  - tag_count >= 10
  - >= 2 tags carry "tafsir-style" markers (see TAFSIR_MARKERS below)
  - Otherwise → RETAG.

Empty arrays always RETAG (these were never enriched).

Usage:
  python3 scripts/enrich_topic_tags_v4_ihsan.py audit         # classify, print verdict, no Claude calls
  python3 scripts/enrich_topic_tags_v4_ihsan.py run [--limit N]   # actually re-tag (background-friendly)
  python3 scripts/enrich_topic_tags_v4_ihsan.py status        # print checkpoint + progress
  python3 scripts/enrich_topic_tags_v4_ihsan.py sample N      # print N borderline cases for spot-check

Resumability: writes scripts/.v4_checkpoint.json with last completed ayah_id.
Fail-soft: Claude errors logged to scripts/.v4_log.jsonl; ayah marked retry-needed.
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

CHECKPOINT_PATH = Path(__file__).parent / ".v4_checkpoint.json"
LOG_PATH = Path(__file__).parent / ".v4_log.jsonl"

# ---------------------------------------------------------------------------
# Tafsir-style markers — signals that a tag was generated with tafsir context
# ---------------------------------------------------------------------------

TAFSIR_TERMS = {
    # Aqeedah / theology
    "tawhid", "shirk", "iman", "kufr", "ihsan", "taqwa", "tawakkul", "ikhlas",
    "yaqeen", "khushu", "khashyah", "muraqabah",
    # Quranic sciences
    "tafsir", "tawil", "qira'at", "qiraat", "naskh", "mansukh", "muhkam",
    "mutashabih", "mutashabihat", "asbab al-nuzul", "asbab", "iltifat", "majaz",
    "haqiqah", "balaghah", "i'jaz", "rasm", "tanzeel",
    # Fiqh / usul
    "fiqh", "usul", "hadith", "sunnah", "sirah", "ijma", "qiyas", "ijtihad",
    "halal", "haram", "wajib", "fard", "mubah", "makruh", "mustahab",
    "madhhab", "shafi", "hanafi", "maliki", "hanbali",
    # Spiritual states
    "rahma", "rahman", "rahim", "wahdat", "wahdaniyyah", "rububiyyah", "uluhiyyah",
    "akhirah", "dunya", "barzakh", "qiyamah", "hashr", "yawm", "jannah",
    "jahannam", "sirat", "mizan", "shafa'ah",
    # Worship
    "salah", "zakat", "siyam", "hajj", "umrah", "ibadah", "dhikr", "dua",
    "wudu", "ghusl", "tayammum", "qiblah", "kaaba",
    # Names of Allah / divine
    "al-hayy", "al-qayyum", "al-quddus", "al-hakeem", "al-aleem", "al-wadud",
    "al-ghafoor", "al-tawwab", "al-azeem", "al-jabbar", "al-mutakabbir",
    "asma al-husna", "asma'", "sifat",
    # People
    "sahaba", "sahabah", "tabieen", "salaf", "ulama", "imam", "shaykh",
    "ibrahim", "musa", "isa", "muhammad", "khadijah", "ayesha", "umar",
    "abu bakr", "ali", "uthman",
    # Quranic concepts
    "ayat", "surah", "juz", "manzil", "hizb", "ruku", "sajdah", "rukoo",
    # Other classical
    "ghaib", "ghayb", "barakah", "bid'ah", "fitnah", "fitna", "jihad",
    "tawbah", "istighfar", "shahada", "kalimah", "ummah", "mu'min", "muslim",
    "munafiq", "kafir", "mushrik", "abd",
}

def has_tafsir_marker(tag: str) -> bool:
    """Tag carries a tafsir-aware signal: al- prefix, apostrophe, or known term."""
    t = tag.lower().strip()
    if not t:
        return False
    if t.startswith("al-") or " al-" in t:
        return True
    if "'" in t:
        return True
    # Multi-word transliteration like "ya-sin", "ar-rahman" — hyphenated lower
    if re.search(r"\b[a-z]+-[a-z]+\b", t) and not t in {"day-of-judgment", "step-by-step", "ahl-al-bayt"}:
        # rough: hyphenated lower-case bigram likely transliteration
        # except some English compounds
        # The known-English-compound exception list could grow; cheap default
        if any(c in t for c in ["a", "i", "u"]) and len(t) > 5:
            return True
    # Word-boundary match against known terms
    tokens = re.findall(r"[a-z']+", t)
    return any(tok in TAFSIR_TERMS for tok in tokens)


def classify(tags: list) -> str:
    """Return 'KEEP', 'RETAG', or 'EMPTY' for an ayah's tags."""
    if not tags:
        return "EMPTY"
    if len(tags) < 10:
        return "RETAG"
    marker_count = sum(1 for t in tags if has_tafsir_marker(t))
    if marker_count >= 2:
        return "KEEP"
    return "RETAG"


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

def load_checkpoint():
    if not CHECKPOINT_PATH.exists():
        return {"completed_ids": [], "last_position": 0, "started_at": None, "stats": {"keep": 0, "retag": 0, "empty": 0, "succeeded": 0, "failed": 0}}
    return json.loads(CHECKPOINT_PATH.read_text())


def save_checkpoint(cp):
    cp["updated_at"] = datetime.now(timezone.utc).isoformat()
    CHECKPOINT_PATH.write_text(json.dumps(cp, indent=2))


def log_event(event):
    event["t"] = datetime.now(timezone.utc).isoformat()
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Claude prompt — Ihsan-grade tafsir-aware
# ---------------------------------------------------------------------------

SURAH_NAMES = {1:"Al-Fatiha",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiya",46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahina",61:"As-Saff",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddathir",75:"Al-Qiyamah",76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"}


def build_prompt(ayah, tafsir_rows):
    """Build the v4 Ihsan-grade prompt. Tafsir-aware, asks for both general and specific tags."""
    surah_name = SURAH_NAMES.get(ayah["surah_number"], f"Surah {ayah['surah_number']}")
    tafsir_block = ""
    if tafsir_rows:
        for t in tafsir_rows[:4]:
            text = (t.get("english_text") or "")[:500]
            scholar = t.get("scholar_name") or "Unknown"
            tafsir_block += f"\n[{scholar}]: {text}\n"
    else:
        tafsir_block = "(no tafsir available — use translation alone, mark uncertainty in tags)"

    return f"""Generate Ihsan-grade topic tags for Quran verse {surah_name} ({ayah['surah_number']}:{ayah['ayah_number']}).

TRANSLATION: {ayah.get('english_translation', '(missing)')}

SCHOLARLY COMMENTARY:
{tafsir_block}

Tags must reflect:
1. The literal meaning of the verse (what it directly says)
2. The themes scholars derive from it (what tafsir extracts)
3. Practical questions a Muslim would ask where this verse is the answer
4. Specific Islamic concepts present (use Arabic transliteration: tawhid, taqwa, ikhlas, etc.)
5. Linguistic devices if salient (iltifat, tashbih, kinaayah)
6. Cross-references — names, prophetic stories, parallel ayat, asbab al-nuzul

Output rules:
- Return ONLY a JSON array of lowercase strings — no commentary, no markdown
- 12 to 15 tags
- Mix of general (English) and specific (transliteration / classical terms)
- At least 3 tags should be specific Arabic / classical terminology
- Make tags retrievable: a person asking "X" should find this verse via tag X

Output the JSON array now:"""


def call_claude(prompt, timeout=45):
    result = subprocess.run(
        [CLAUDE_BIN, "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout, env=CLAUDE_ENV,
    )
    if result.returncode != 0:
        return None, f"returncode={result.returncode}: {result.stderr[:200]}"
    output = result.stdout.strip()
    try:
        tags = json.loads(output)
        if isinstance(tags, list):
            return [str(t).lower() for t in tags[:15]], None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*?\]", output, re.DOTALL)
    if m:
        try:
            tags = json.loads(m.group())
            if isinstance(tags, list):
                return [str(t).lower() for t in tags[:15]], None
        except json.JSONDecodeError:
            return None, "regex-extracted JSON parse failed"
    return None, "no JSON array in output"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_audit(_args):
    rows = api_get_all("ayat?select=id,surah_number,ayah_number,topic_tags&order=surah_number,ayah_number")
    counts = {"KEEP": 0, "RETAG": 0, "EMPTY": 0}
    by_verdict = {"KEEP": [], "RETAG": [], "EMPTY": []}
    for r in rows:
        v = classify(r.get("topic_tags") or [])
        counts[v] += 1
        by_verdict[v].append(r)

    print(f"Total ayat: {len(rows)}")
    for k in ("KEEP", "RETAG", "EMPTY"):
        print(f"  {k}: {counts[k]} ({100*counts[k]/len(rows):.1f}%)")

    print("\nBorderline RETAG samples (existing tags shown so user can sanity-check the bar):")
    retag_samples = [r for r in by_verdict["RETAG"] if r.get("topic_tags")][:8]
    for r in retag_samples:
        n = len(r["topic_tags"])
        markers = sum(1 for t in r["topic_tags"] if has_tafsir_marker(t))
        print(f"  {r['surah_number']}:{r['ayah_number']} ({n} tags, {markers} markers): {r['topic_tags'][:5]}{'...' if n>5 else ''}")

    print("\nKEEP examples (high-confidence retain):")
    for r in by_verdict["KEEP"][:3]:
        n = len(r["topic_tags"])
        markers = sum(1 for t in r["topic_tags"] if has_tafsir_marker(t))
        print(f"  {r['surah_number']}:{r['ayah_number']} ({n} tags, {markers} markers): {r['topic_tags'][:6]}...")

    return 0


def cmd_status(_args):
    cp = load_checkpoint()
    print(json.dumps(cp, indent=2))
    return 0


def cmd_sample(args):
    n = int(args[0]) if args else 5
    rows = api_get_all("ayat?select=id,surah_number,ayah_number,topic_tags&order=surah_number,ayah_number")
    borderline = [r for r in rows if classify(r.get("topic_tags") or []) == "RETAG" and r.get("topic_tags")]
    import random
    random.shuffle(borderline)
    for r in borderline[:n]:
        markers = sum(1 for t in r["topic_tags"] if has_tafsir_marker(t))
        print(f"\n  {r['surah_number']}:{r['ayah_number']} ({len(r['topic_tags'])} tags, {markers} markers)")
        for t in r["topic_tags"]:
            mark = "✓" if has_tafsir_marker(t) else "·"
            print(f"    {mark} {t}")
    return 0


def cmd_run(args):
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    print("=" * 60)
    print("V4 Ihsan-grade enrichment — actual run")
    print("=" * 60)

    cp = load_checkpoint()
    if cp.get("started_at") is None:
        cp["started_at"] = datetime.now(timezone.utc).isoformat()
    completed = set(cp.get("completed_ids", []))

    rows = api_get_all("ayat?select=id,surah_number,ayah_number,english_translation,topic_tags&order=surah_number,ayah_number")

    work = []
    for r in rows:
        verdict = classify(r.get("topic_tags") or [])
        if verdict == "KEEP":
            cp["stats"]["keep"] += 1 if r["id"] not in completed else 0
            continue
        if r["id"] in completed:
            continue
        work.append((r, verdict))

    print(f"Total: {len(rows)} | Already completed in this run: {len(completed)}")
    print(f"Work remaining: {len(work)}")
    if limit:
        work = work[:limit]
        print(f"Limit applied: processing {len(work)}")
    save_checkpoint(cp)

    if not work:
        print("Nothing to do.")
        return 0

    for i, (ayah, verdict) in enumerate(work):
        try:
            tafsir = api_get(f"tafsir_entries?ayah_id=eq.{ayah['id']}&select=scholar_name,english_text")
        except Exception as e:
            log_event({"ayah_id": ayah["id"], "error": f"tafsir fetch: {e}"})
            tafsir = []

        prompt = build_prompt(ayah, tafsir)
        tags, err = call_claude(prompt)
        if tags is None or len(tags) < 8:
            log_event({"ayah_id": ayah["id"], "ref": f"{ayah['surah_number']}:{ayah['ayah_number']}", "error": err or "tags<8", "verdict": verdict})
            cp["stats"]["failed"] += 1
            print(f"  [{i+1}/{len(work)}] {ayah['surah_number']}:{ayah['ayah_number']} ✗ {err}")
        else:
            try:
                api_patch("ayat", ayah["id"], {"topic_tags": tags})
                cp["stats"]["succeeded"] += 1
                cp["stats"][verdict.lower()] += 1
                completed.add(ayah["id"])
                cp["completed_ids"] = list(completed)
                marker_count = sum(1 for t in tags if has_tafsir_marker(t))
                print(f"  [{i+1}/{len(work)}] {ayah['surah_number']}:{ayah['ayah_number']} ✓ {len(tags)} tags ({marker_count} markers, {len(tafsir)} tafsir, was {verdict})")
            except Exception as e:
                log_event({"ayah_id": ayah["id"], "error": f"patch: {e}"})
                cp["stats"]["failed"] += 1

        # Save checkpoint every 25 ayat to bound recovery cost
        if (i + 1) % 25 == 0:
            save_checkpoint(cp)
        time.sleep(0.5)

    save_checkpoint(cp)
    print(f"\n=== Run complete ===")
    print(json.dumps(cp["stats"], indent=2))
    return 0


SUBCOMMANDS = {"audit": cmd_audit, "run": cmd_run, "status": cmd_status, "sample": cmd_sample}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        sys.stderr.write(f"usage: {sys.argv[0]} {{{' | '.join(SUBCOMMANDS)}}} [args...]\n")
        sys.exit(2)
    sys.exit(SUBCOMMANDS[sys.argv[1]](sys.argv[2:]) or 0)


if __name__ == "__main__":
    main()
