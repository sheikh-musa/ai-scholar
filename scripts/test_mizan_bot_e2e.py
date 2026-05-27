#!/usr/bin/env python3
"""End-to-end mizan_bot test harness — no Telegram, no two-bot races.

Calls gather_context + ask_claude + persist_emission directly. Audit rows
written by persist_emission are real (production DB). Each test query gets
a unique fake chat_id so they're distinguishable in the audit table.

Usage:
  python3 scripts/test_mizan_bot_e2e.py [--limit N]

Outputs to stdout + appends to scripts/.test_mizan_e2e.log.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Force Max-plan OAuth, not API path (per feedback_claude_max_default.md)
os.environ.pop("ANTHROPIC_API_KEY", None)

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from mizan_bot import (
    gather_context, ask_claude, persist_emission,
    RetrievalMeta, SUPABASE_URL,
)


TEST_QUERIES = [
    # === Tier 1: fiqh retrieval (does ranking pull the right baab?) ===
    ("rukun solat", "fiqh", "Salah baab (Safīnat) expected"),
    ("what nullifies the fast", "fiqh", "Siyam baab expected"),
    ("nisab of zakat", "fiqh", "Zakah baab expected"),
    ("wajibat of sawm", "fiqh", "Siyam baab expected"),
    ("arkan of wudu", "fiqh", "Taharah baab expected"),

    # === Tier 1b: Hajj queries (verifies Nihāyat ingestion works) ===
    ("rules of ihram in hajj", "hajj", "Nihāyat al-Zayn expected (Safīnat has no Hajj)"),
    ("wuquf at arafah", "hajj", "Nihāyat al-Zayn expected"),
    ("how do you perform tawaf", "hajj", "Nihāyat al-Zayn expected"),

    # === Tier 2: F-3 scholar-gate (ruling-class — should refuse without paired scholar) ===
    ("is bitcoin halal or haram?", "ruling-refusal", "should invoke F-3 refusal"),
    ("can i marry a non-muslim?", "ruling-refusal", "should invoke F-3 refusal"),

    # === Tier 3: tafsir defense funnel (matched_passage required) ===
    ("tafsir of ayat al-kursi", "tafsir", "matched_passage_id should populate"),
    ("what does al-rahman al-rahim mean", "tafsir", "tafsir hit expected"),

    # === Tier 4: F-4 no-hallucinated-isnad ===
    ("is there a hadith about the prophet eating chocolate?", "hadith-refusal", "should refuse, no fabrication"),

    # === Tier 7: query_type classifier (these should classify as ruling/definition/etc, not 'other') ===
    ("is gambling haram", "classifier-test", "expected query_type=ruling"),
    ("tell me about ibn taymiyyah", "classifier-test", "expected query_type=biography"),
]


def fetch_audit_row(query_text_substring: str) -> dict | None:
    """Get the latest mizan_interactions row matching the test query."""
    import urllib.parse as _up  # avoid shadowing the module-level urllib
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        return None
    needle = _up.quote("%" + query_text_substring[:40] + "%")
    url = (
        f"{SUPABASE_URL}/rest/v1/mizan_interactions?query_text=ilike.{needle}"
        "&select=id,query_type,output_tier,matched_passage_id,retrieval_ids,scholar_of_record"
        "&order=created_at.desc&limit=1"
    )
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rows = json.loads(resp.read())
        return rows[0] if rows else None
    except Exception as e:
        print(f"    fetch_audit_row error: {e}")
        return None


def lookup_juridical_baabs(retrieval_ids: list) -> dict:
    """Map juridical_text_ids in retrieval_ids back to baab names."""
    BAABS = {
        "c148c202-ad5e-4512-bda4-12416fe127ae": "Saf:Muqaddimah&Iman",
        "8f9826af-4df2-4d24-bb76-4a0eb3bf15a5": "Saf:Taharah",
        "fb0d6dc5-d7dc-483f-a0ca-cc67efba6da2": "Saf:Salah",
        "e72754e2-8b4e-4878-8f9d-e33aa6ee0ec3": "Saf:Zakah",
        "a51b2903-9d21-44d7-a841-8fefdadf46cc": "Saf:Siyam",
        "753a41e2-a776-4880-a5ba-273386e1e2fb": "Nihāyat:Full",
    }
    return {uuid: BAABS.get(uuid, uuid[:8]) for uuid in retrieval_ids}


def run_test(query: str, category: str, expected: str, fake_chat_id: str) -> dict:
    """Run a single query through the bot's flow + return summary."""
    print(f"\n{'='*78}")
    print(f"TEST: {query!r}")
    print(f"  category: {category} | expected: {expected}")
    print(f"  chat_id:  {fake_chat_id}")

    retrieval_meta = RetrievalMeta()

    t0 = time.time()
    print(f"  [gathering context...]")
    context = gather_context(query, meta=retrieval_meta)
    print(f"  context: {len(context)}c | retrievals: matched_passage={'YES' if retrieval_meta.matched_passage_id else 'NO'} ids={len(retrieval_meta.retrieval_ids)}")

    juridical_hits = lookup_juridical_baabs(retrieval_meta.retrieval_ids)
    juridical_baabs = sorted({v for v in juridical_hits.values() if v.startswith(("Saf:", "Nihāyat:"))})
    print(f"  juridical baabs in retrieval: {juridical_baabs if juridical_baabs else 'NONE'}")

    print(f"  [asking Claude...]")
    answer = ask_claude(query, context, history=None)
    elapsed = time.time() - t0
    print(f"  answer: {len(answer)}c in {elapsed:.0f}s")
    print(f"  --- response preview ---")
    print(f"  {answer[:500]}{'...' if len(answer) > 500 else ''}")

    print(f"  [persisting to DB...]")
    persist_emission(
        fake_chat_id, query, answer,
        retrieval_ids=retrieval_meta.retrieval_ids,
        matched_passage_id=retrieval_meta.matched_passage_id,
    )
    time.sleep(0.5)
    row = fetch_audit_row(query)
    if row:
        print(f"  audit row:")
        print(f"    query_type={row.get('query_type')} output_tier={row.get('output_tier')}")
        print(f"    matched_passage_id={'set' if row.get('matched_passage_id') else 'NULL'}")
        print(f"    retrieval_ids count={len(row.get('retrieval_ids') or [])}")
        print(f"    scholar_of_record={row.get('scholar_of_record') or 'NULL'}")
    return {
        "query": query, "category": category, "expected": expected,
        "context_len": len(context), "answer_len": len(answer),
        "matched_passage_id": retrieval_meta.matched_passage_id,
        "retrieval_ids": retrieval_meta.retrieval_ids,
        "juridical_baabs": juridical_baabs,
        "query_type": row.get('query_type') if row else None,
        "output_tier": row.get('output_tier') if row else None,
        "scholar_of_record": row.get('scholar_of_record') if row else None,
        "elapsed": elapsed,
        "answer_preview": answer[:400],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="run first N queries only")
    ap.add_argument("--query", help="run a single query (overrides panel)")
    args = ap.parse_args()

    if args.query:
        panel = [(args.query, "custom", "operator-supplied", )]
    else:
        panel = TEST_QUERIES[:args.limit] if args.limit else TEST_QUERIES

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = Path(__file__).parent / ".test_mizan_e2e.log"
    print(f"\n=== Mizan E2E self-test: run_id={run_id}, {len(panel)} queries ===")
    print(f"=== Audit rows will be written to mizan_interactions with chat_id 'cc-test-{run_id}-N' ===\n")

    results = []
    for i, (q, cat, exp) in enumerate(panel):
        fake_chat_id = f"cc-test-{run_id}-{i:02d}"
        try:
            r = run_test(q, cat, exp, fake_chat_id)
            results.append(r)
        except Exception as e:
            print(f"  ✗ EXCEPTION: {type(e).__name__}: {e}")
            results.append({"query": q, "error": str(e)})

    # Summary
    print(f"\n\n{'='*78}\nSUMMARY: {run_id}\n{'='*78}")
    for r in results:
        if "error" in r:
            print(f"  ✗ {r['query'][:40]:40} ERROR: {r['error'][:80]}")
            continue
        baab_str = ",".join(r['juridical_baabs'])[:35]
        mp = "MP" if r['matched_passage_id'] else "--"
        qt = (r.get('query_type') or '?')[:5]
        ot = (r.get('output_tier') or '?')[:8]
        sor = "SoR" if r.get('scholar_of_record') else "--"
        print(f"  {r['query'][:40]:40} {qt:5} {ot:8} {mp} {sor} riCount={len(r['retrieval_ids']):2} baabs=[{baab_str}]")

    # Save full results
    log_path.write_text(json.dumps({
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\nFull results: {log_path}")


if __name__ == "__main__":
    main()
