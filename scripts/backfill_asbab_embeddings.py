#!/usr/bin/env python3
"""Backfill bge-m3 embeddings for asbab_nuzul corpus.

  - Source: asbab_nuzul.text_en
  - Target: asbab_embeddings (PK = asbab_id, bigint)
  - ~1,187 rows, one batch suffices

CAVEAT: ~19% of source-tagged "al-wahidi" rows are mislabeled ishārī
content per docs/ASBAB_NUZUL_CORRUPTION_2026-06-05.md. Semantic search
will surface them regardless of label. The cleanup (task #46) re-tags
the source field but doesn't change the text, so embeddings remain
valid after re-tag. No re-embed required.

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... ENCODER_URL=http://100.104.36.27:8080 \
    python3 scripts/backfill_asbab_embeddings.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ENCODER_URL  = os.environ.get("ENCODER_URL", "http://100.104.36.27:8080")
ENCODER_SHA  = os.environ.get("ENCODER_SHA", "bge-m3-unpinned")
CORPUS_VERSION = "asbab-corpus-v1-per-row-bge-m3"

BATCH_SIZE = 8  # 32 OOM'd the Mac Studio when mlx_lm Gemma+Qwen also resident on MPS. 8 is safer.

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_ROLE_KEY not set", file=sys.stderr)
    sys.exit(2)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


def supabase_request(method: str, path: str, payload=None, prefer: Optional[str] = None) -> Optional[list]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def encode_batch(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        f"{ENCODER_URL}/embed",
        data=json.dumps({"inputs": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return body["embeddings"]


def fetch_pending(limit: Optional[int]) -> list[dict]:
    print(f"[fetch] reading asbab_nuzul...", flush=True)
    # Paginate — PostgREST caps at 1000 rows/page; asbab has 1187 rows.
    page_size = 1000
    offset = 0
    all_rows: list[dict] = []
    while True:
        rows = supabase_request("GET",
            f"asbab_nuzul?select=id,text_en&order=id.asc&limit={page_size}&offset={offset}")
        if not rows:
            break
        all_rows.extend(rows)
        offset += page_size
        if len(rows) < page_size:
            break
    print(f"[fetch] total asbab rows: {len(all_rows)}", flush=True)

    offset = 0
    existing: list[dict] = []
    while True:
        rows = supabase_request("GET",
            f"asbab_embeddings?select=asbab_id,embedded_source_hash&limit={page_size}&offset={offset}")
        if not rows:
            break
        existing.extend(rows)
        offset += page_size
        if len(rows) < page_size:
            break
    existing_hashes = {e["asbab_id"]: e["embedded_source_hash"] for e in existing}
    print(f"[fetch] existing embeddings: {len(existing_hashes)}", flush=True)

    pending = []
    for r in all_rows:
        text = r.get("text_en") or ""
        if not text.strip():
            continue
        src_hash = sha256_hex(text)
        if existing_hashes.get(r["id"]) == src_hash:
            continue
        pending.append({"id": r["id"], "text_en": text, "source_hash": src_hash})
    print(f"[fetch] {len(pending)} asbab rows need embedding", flush=True)
    if limit:
        pending = pending[:limit]
    return pending


def upsert_embedding_batch(rows: list[dict]) -> None:
    supabase_request(
        "POST",
        "asbab_embeddings",
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"encoder: {ENCODER_URL}  model=BAAI/bge-m3  sha={ENCODER_SHA}", flush=True)
    print(f"corpus_version: {CORPUS_VERSION}", flush=True)

    pending = fetch_pending(args.limit)
    if not pending:
        print("nothing to embed")
        return 0

    if args.dry_run:
        print(f"[dry-run] would embed {len(pending)} asbab rows")
        return 0

    print(f"[health] encoder check...", flush=True)
    health = json.loads(urllib.request.urlopen(f"{ENCODER_URL}/health", timeout=5).read())
    print(f"  {health}", flush=True)

    t0 = time.time()
    inserted = 0
    failed = 0
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        texts = [b["text_en"] for b in batch]
        try:
            vectors = encode_batch(texts)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError) as e:
            print(f"  [{i:>5}-{i+len(batch):>5}] ENCODE FAILED: {type(e).__name__}: {e}", flush=True)
            failed += len(batch)
            continue

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for b, v in zip(batch, vectors):
            rows.append({
                "asbab_id": b["id"],
                "embedding": f"[{','.join(str(x) for x in v)}]",
                "embedding_model": "BAAI/bge-m3",
                "encoder_sha": ENCODER_SHA,
                "corpus_version": CORPUS_VERSION,
                "embedded_source_hash": b["source_hash"],
                "source_token_count": len(b["text_en"].split()),
                "created_at": now,
                "updated_at": now,
            })
        try:
            upsert_embedding_batch(rows)
            inserted += len(rows)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            print(f"  [{i:>5}-{i+len(batch):>5}] UPSERT FAILED: {type(e).__name__}: {e}", flush=True)
            failed += len(batch)
            continue

        elapsed = time.time() - t0
        print(f"  [{inserted:>4}/{len(pending)}] batch {i//BATCH_SIZE + 1}  elapsed={elapsed:.0f}s", flush=True)

    elapsed_total = time.time() - t0
    print(f"\ndone — inserted={inserted}, failed={failed}, elapsed={elapsed_total:.0f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
