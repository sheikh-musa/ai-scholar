#!/usr/bin/env python3
"""MIZAN-REENGAGE-01 — short-retention failure re-queue (CAI-RESP-396, Option C).

Re-engages a user whose question got a GENUINELY failed answer: re-answers it
through the now-fixed pipeline and sends ONE courteous, self-identifying
follow-up — without a durable raw-telegram-id store. The raw chat_id lives ONLY
in mizan_followup_queue (migration 20260708_001), purged at terminal state and
by a 24h backstop. Durable audit (mizan_interactions) stays hash-only.

⚠️ ACTIVATION-GATED. This module is inert until BOTH:
  (1) migration 20260708_001_mizan_followup_queue.sql is applied (after the
      independent schema review CAI-RESP-396 requires), and
  (2) MIZAN_FOLLOWUP_ENABLED=1 is set.
Until then enqueue_if_eligible() no-ops before any DB write, so it is safe to
wire into mizan_bot's emit path now (the call is a no-op).

CAI-RESP-396 bounds enforced here:
  §3  eligible failure classes = {timeout-stub, evidence-fallback} only.
  §4  send-worthy gate = full mizan_judge, same bar as a first answer, BIAS TO
      SKIP on any doubt; ruling-class still through F-3.
  §5  cooldown = one follow-up / user / 30 days.
  §6  no opt-in; mandatory honest self-identifying message + STOP opt-out line;
      opt-outs stored hash-keyed (permanent suppression, no raw id).
  G1  enqueue ONLY on a genuine failure (a send-worthy first answer => no row).
  G3  raw chat_id is NEVER logged (we log a short hash prefix instead).

Subcommands:
  drain  [--limit N]   re-answer queued failures, send-worthy → send, else skip
  purge                run the TTL backstop sweep; print the G2 audit row
  optout <chat_id>     record a permanent (hash-keyed) opt-out
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

FOLLOWUP_ENABLED = os.environ.get("MIZAN_FOLLOWUP_ENABLED") == "1"
COOLDOWN_DAYS = 30                 # §5
MIN_SENDWORTHY_CHARS = 200         # coarse pre-judge floor; the real gate is mizan_judge (§4)

QUEUE = "mizan_followup_queue"
OPTOUT = "mizan_followup_optout"


# ===========================================================================
# Pure helpers (offline-testable — no DB, no LLM, no Telegram)
# ===========================================================================

def hash_chat_id(chat_id) -> str:
    """SHA-256(str(chat_id)) — identical to mizan_bot._hash_telegram_id and the
    hashing done by persist-mizan-ruling, so the hash joins across tables."""
    return hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()


def classify_failure(answer_text: str):
    """Return the CAI-RESP-396-eligible failure class of an emitted answer, or
    None if it was a normal (send-worthy) answer — in which case G1 says do NOT
    enqueue. Matches the two named failure strings from mizan_bot as the single
    source of truth; weak-corpus-gap (an honest 'we don't carry this') is NOT one
    of these strings and is intentionally NOT eligible (§3)."""
    from mizan_bot import EVIDENCE_FALLBACK_PREFIX, TIMEOUT_STUB_MSG
    if not answer_text:
        return None
    t = answer_text.strip()
    if t.startswith(EVIDENCE_FALLBACK_PREFIX):
        return "evidence-fallback"
    if t.startswith(TIMEOUT_STUB_MSG[:60]):
        return "timeout-stub"
    return None


def within_cooldown(last_created_at_iso, now=None, days: int = COOLDOWN_DAYS) -> bool:
    """True if the user's most recent follow-up row is inside the cooldown window
    (so a new enqueue must be suppressed/collapsed). None => no prior row => not
    in cooldown."""
    if not last_created_at_iso:
        return False
    now = now or datetime.now(timezone.utc)
    prev = _parse_iso(last_created_at_iso)
    if prev is None:
        return False
    return (now - prev) < timedelta(days=days)


def is_send_worthy_shape(answer_text: str) -> bool:
    """Coarse pre-judge shape check (the authoritative gate is mizan_judge, §4):
    a re-answer must not itself be a fallback/stub, and must clear a length floor.
    Bias to skip — returns False on anything borderline."""
    if not answer_text:
        return False
    if classify_failure(answer_text) is not None:
        return False
    honest_gap_markers = ("we don't have", "we do not have", "corpus doesn't carry",
                          "corpus does not carry", "couldn't find", "could not find")
    low = answer_text.lower()
    if any(m in low for m in honest_gap_markers):
        return False
    return len(answer_text.strip()) >= MIN_SENDWORTHY_CHARS


def is_stop_reply(text: str) -> bool:
    """Detect a STOP / opt-out reply (§6b). Conservative — only fires on a short
    message that is essentially just the opt-out word, so 'stop combining prayers'
    (a real question) is NOT treated as an opt-out."""
    if not text:
        return False
    t = text.strip().lower().strip(".!？?،, ")
    if len(t) > 24:
        return False
    return t in {"stop", "stop.", "unsubscribe", "opt out", "optout", "opt-out",
                 "no thanks", "no follow up", "no followups", "leave me alone",
                 "unsub", "stop messages", "stop messaging me", "berhenti"}


def build_followup_message(question: str, answer: str) -> str:
    """The one courteous follow-up (§6a honest & self-identifying, never marketing)
    with the mandatory §6b opt-out line. Quotes the user's own question back so it
    is unmistakably a reply to what THEY asked."""
    q = (question or "").strip()
    q_short = q if len(q) <= 160 else q[:157].rstrip() + "…"
    return (
        "As-salāmu ʿalaykum 🌿\n\n"
        f"You asked earlier: “{q_short}” — and we couldn't answer it well at the "
        "time. Sorry about that. Here's a proper answer now:\n\n"
        f"{answer.strip()}\n\n"
        "———\n"
        "_You're getting this once because you asked it here — not marketing. "
        "Reply STOP and we won't follow up again._"
    )


def _parse_iso(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


# ===========================================================================
# Supabase REST (service role) — impure
# ===========================================================================

def _headers(prefer: str = "return=representation") -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _req(method: str, path: str, body=None, prefer: str = "return=representation"):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(prefer))
    with urllib.request.urlopen(req) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def _hash_prefix(h: str) -> str:
    """A short, non-reversible tag for logs (G3: never log the raw chat_id)."""
    return (h or "")[:8]


def optout_exists(telegram_id_hash: str) -> bool:
    rows = _req("GET", f"{OPTOUT}?telegram_id_hash=eq.{telegram_id_hash}&select=telegram_id_hash&limit=1")
    return bool(rows)


def add_optout(chat_id, source: str = "stop-reply") -> None:
    h = hash_chat_id(chat_id)
    try:
        _req("POST", OPTOUT, {"telegram_id_hash": h, "source": source},
             prefer="return=minimal,resolution=merge-duplicates")
        print(f"  opt-out recorded for {_hash_prefix(h)}… (source={source})")
    except urllib.error.HTTPError as e:
        print(f"  opt-out insert failed: {e.code}")


def _last_followup_created_at(telegram_id_hash: str):
    rows = _req("GET",
                f"{QUEUE}?telegram_id_hash=eq.{telegram_id_hash}"
                f"&select=created_at&order=created_at.desc&limit=1")
    return rows[0]["created_at"] if rows else None


def enqueue_if_eligible(chat_id, query_text: str, answer_text: str, interaction_id=None):
    """THE hook (call from mizan_bot right after a failed answer is emitted).
    No-op unless activated. Returns the new row id, or None when nothing is
    enqueued (good answer / opted-out / in cooldown / disabled).

    G1: a send-worthy first answer classifies as None => no row is written.
    """
    if not FOLLOWUP_ENABLED:
        return None
    failure_class = classify_failure(answer_text)
    if failure_class is None:
        return None  # G1 — good answer, nothing to re-engage
    h = hash_chat_id(chat_id)
    try:
        if optout_exists(h):
            print(f"  followup: {_hash_prefix(h)}… opted out — skip")
            return None
        if within_cooldown(_last_followup_created_at(h)):
            print(f"  followup: {_hash_prefix(h)}… within {COOLDOWN_DAYS}d cooldown — collapse/skip")
            return None
        row = {
            "interaction_id": interaction_id,
            "telegram_id_hash": h,
            "chat_id": int(chat_id),
            "query_text": query_text,
            "failure_class": failure_class,
        }
        res = _req("POST", QUEUE, row)
        rid = res[0]["id"] if res else None
        print(f"  followup queued ({failure_class}) for {_hash_prefix(h)}… id={rid}")
        return rid
    except urllib.error.HTTPError as e:
        # Never break the live answer path on a follow-up bookkeeping error.
        print(f"  followup enqueue failed (non-fatal): {e.code}")
        return None


# ===========================================================================
# Drain / purge — impure, activation-gated
# ===========================================================================

def _set_status(row_id: str, status: str, **fields) -> None:
    body = {"status": status}
    body.update(fields)
    _req("PATCH", f"{QUEUE}?id=eq.{row_id}", body, prefer="return=minimal")


def _judge_send_worthy(question: str, reanswer: str) -> bool:
    """Authoritative send-worthy gate (§4): full mizan_judge, bias to skip.
    Any error / low score / hallucination => skip. Kept behind the drain so the
    pure path stays testable."""
    try:
        import mizan_judge as mj
        prompt = mj.build_judge_prompt(question, reanswer) if hasattr(mj, "build_judge_prompt") else None
        if prompt is None:
            return False  # judge integration not wired for ad-hoc pairs — bias to skip
        parsed = mj.parse_judge_output(mj.call_judge(prompt))
        norm = mj._normalize_scores(parsed) if parsed else None
        if not norm:
            return False
        if norm.get("hallucination", 5) >= 1:
            return False
        return (norm.get("composite_score") or 0) >= mj.SEND_WORTHY_THRESHOLD if hasattr(mj, "SEND_WORTHY_THRESHOLD") else False
    except Exception as e:
        print(f"  judge gate errored ({type(e).__name__}) — bias to skip")
        return False


def drain(limit: int = 20) -> None:
    if not FOLLOWUP_ENABLED:
        print("MIZAN_FOLLOWUP_ENABLED != 1 — drain is inert (activation-gated). Exiting.")
        return
    import mizan_bot as mb
    rows = _req("GET", f"{QUEUE}?status=eq.queued&chat_id=not.is.null"
                       f"&select=id,chat_id,telegram_id_hash,query_text,interaction_id"
                       f"&order=created_at.asc&limit={int(limit)}")
    print(f"[drain] {len(rows or [])} queued row(s)")
    for r in rows or []:
        rid, h = r["id"], r["telegram_id_hash"]
        try:
            if optout_exists(h):
                _set_status(rid, "skipped", skip_reason="opted-out")
                continue
            context = mb.gather_context(r["query_text"])
            reanswer = mb.ask_claude(r["query_text"], context)
            _set_status(rid, "reanswered", attempts=1, reanswer_text=reanswer)
            if not is_send_worthy_shape(reanswer) or not _judge_send_worthy(r["query_text"], reanswer):
                _set_status(rid, "skipped", skip_reason="not-send-worthy")
                print(f"  {_hash_prefix(h)}… skipped (bias-to-skip)")
                continue
            msg = build_followup_message(r["query_text"], reanswer)
            mb.send_message(r["chat_id"], msg)          # raw id used only here, at send time
            _set_status(rid, "sent")                    # trigger nulls chat_id + reanswer_text
            print(f"  {_hash_prefix(h)}… sent")
        except Exception as e:
            # Bias to skip; never crash the drain on one row.
            _set_status(rid, "skipped", skip_reason=f"error:{type(e).__name__}")
            print(f"  {_hash_prefix(h)}… skipped (error {type(e).__name__})")


def purge() -> None:
    """G2: run the TTL backstop sweep and print the provable audit row."""
    res = _req("POST", "rpc/purge_mizan_followup_queue", {})
    row = res[0] if isinstance(res, list) and res else (res or {})
    print(f"[purge] purged_count={row.get('purged_count')} "
          f"oldest_surviving_chat_id_age={row.get('oldest_surviving_chat_id_age')}")
    age = row.get("oldest_surviving_chat_id_age")
    if isinstance(age, str) and ("day" in age or "24:" in age):
        print("  ⚠️ a chat_id has survived ~24h — TTL enforcement needs investigation")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mizan_followup.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drain"); d.add_argument("--limit", type=int, default=20)
    sub.add_parser("purge")
    o = sub.add_parser("optout"); o.add_argument("chat_id")
    args = p.parse_args(argv)
    if args.cmd == "drain":
        drain(args.limit)
    elif args.cmd == "purge":
        purge()
    elif args.cmd == "optout":
        add_optout(args.chat_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
