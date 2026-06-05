#!/usr/bin/env python3
"""Backfill bge-m3 embeddings for the hadith corpus.

Mirrors backfill_juridical_embeddings.py but specialised:
  - Source: hadiths.english_text (no chunking — each hadith is one vector)
  - Target: hadith_embeddings (PK = hadith_id)
  - Encoder: Mac Studio bge-m3 at ENCODER_URL
  - ~36K rows, ~3-6 hour wall-clock at typical Mac Studio throughput

Idempotent: UPSERTs on hadith_id PK with embedded_source_hash check. Re-runs
after partial completion skip already-embedded rows where the source hash
matches (cheap correctness over wasteful re-embed).

Usage:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... ENCODER_URL=http://100.104.36.27:8080 \
    python3 scripts/backfill_hadith_embeddings.py [--limit N] [--dry-run] [--collection NAME]
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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ENCODER_URL  = os.environ.get("ENCODER_URL", "http://100.104.36.27:8080")
ENCODER_SHA  = os.environ.get("ENCODER_SHA", "bge-m3-unpinned")
CORPUS_VERSION = "hadith-corpus-v1-per-row-bge-m3"

BATCH_SIZE = 8  # 32 OOM'd the Mac Studio (MPS) when mlx_lm Gemma+Qwen co-resident.
# 8 keeps peak allocation well under the 36 GiB MPS ceiling.

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
    """POST to bge-m3 encoder; returns list of 1024-dim vectors."""
    req = urllib.request.Request(
        f"{ENCODER_URL}/embed",
        data=json.dumps({"inputs": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    return body["embeddings"]


def fetch_pending_hadiths(limit: Optional[int], collection_name: Optional[str]) -> list[dict]:
    """Get hadiths without embeddings (or with stale source_hash).

    Strategy: page through hadiths in id-asc order, drop ones already
    embedded with a matching source hash. We do this client-side because
    PostgREST doesn't expose anti-join. For 36K rows it's fine.
    """
    print(f"[fetch] reading hadiths...", flush=True)
    page_size = 1000
    offset = 0
    all_hadiths: list[dict] = []
    filter_params = ""
    if collection_name:
        # Resolve collection_id from name first
        cols = supabase_request("GET",
            f"hadith_collections?name=eq.{urllib.parse.quote(collection_name)}&select=id")
        if not cols:
            print(f"ERROR: collection '{collection_name}' not found", file=sys.stderr)
            sys.exit(2)
        filter_params = f"&collection_id=eq.{cols[0]['id']}"
    while True:
        rows = supabase_request("GET",
            f"hadiths?select=id,english_text&order=id.asc&limit={page_size}&offset={offset}{filter_params}")
        if not rows:
            break
        all_hadiths.extend(rows)
        print(f"  fetched {len(all_hadiths)} hadiths so far", flush=True)
        offset += page_size
        if len(rows) < page_size:
            break
    print(f"[fetch] total hadiths: {len(all_hadiths)}", flush=True)

    # Filter to those needing embedding
    print(f"[fetch] reading existing embeddings...", flush=True)
    existing_hashes: dict[str, str] = {}
    offset = 0
    while True:
        emb_rows = supabase_request("GET",
            f"hadith_embeddings?select=hadith_id,embedded_source_hash&limit={page_size}&offset={offset}")
        if not emb_rows:
            break
        for er in emb_rows:
            existing_hashes[er["hadith_id"]] = er["embedded_source_hash"]
        offset += page_size
        if len(emb_rows) < page_size:
            break
    print(f"[fetch] existing embeddings: {len(existing_hashes)}", flush=True)

    pending = []
    for h in all_hadiths:
        text = h.get("english_text") or ""
        if not text.strip():
            continue
        src_hash = sha256_hex(text)
        if existing_hashes.get(h["id"]) == src_hash:
            continue
        pending.append({"id": h["id"], "english_text": text, "source_hash": src_hash})
    print(f"[fetch] {len(pending)} hadiths need embedding ({len(all_hadiths) - len(pending)} skipped, already current)", flush=True)
    if limit:
        pending = pending[:limit]
        print(f"[fetch] limited to first {limit}", flush=True)
    return pending


def upsert_embedding_batch(rows: list[dict]) -> None:
    """UPSERT into hadith_embeddings on hadith_id PK."""
    supabase_request(
        "POST",
        "hadith_embeddings",
        payload=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap to first N pending hadiths")
    ap.add_argument("--dry-run", action="store_true", help="show plan, no inserts, no encoding")
    ap.add_argument("--collection", help="restrict to a single hadith_collections.name (e.g. bukhari, muslim)")
    args = ap.parse_args()

    print(f"encoder: {ENCODER_URL}  model=BAAI/bge-m3  sha={ENCODER_SHA}", flush=True)
    print(f"corpus_version: {CORPUS_VERSION}", flush=True)

    pending = fetch_pending_hadiths(args.limit, args.collection)
    if not pending:
        print("nothing to embed")
        return 0

    if args.dry_run:
        print(f"[dry-run] would embed {len(pending)} hadiths in batches of {BATCH_SIZE}")
        print(f"  first hadith preview: id={pending[0]['id']}")
        print(f"  text[:200]: {pending[0]['english_text'][:200]}")
        return 0

    # Sanity-check encoder
    print(f"[health] encoder check...", flush=True)
    health = json.loads(urllib.request.urlopen(f"{ENCODER_URL}/health", timeout=5).read())
    print(f"  {health}", flush=True)
    if health.get("status") != "ok":
        print("ERROR: encoder not healthy", file=sys.stderr)
        return 2

    t0 = time.time()
    inserted = 0
    failed = 0
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        texts = [b["english_text"] for b in batch]
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
                "hadith_id": b["id"],
                "embedding": f"[{','.join(str(x) for x in v)}]",
                "embedding_model": "BAAI/bge-m3",
                "encoder_sha": ENCODER_SHA,
                "corpus_version": CORPUS_VERSION,
                "embedded_source_hash": b["source_hash"],
                "source_token_count": len(b["english_text"].split()),
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
        rate = inserted / max(elapsed, 1)
        remaining = (len(pending) - inserted) / max(rate, 0.01)
        print(f"  [{inserted:>5}/{len(pending)}] batch {i//BATCH_SIZE + 1}  elapsed={elapsed:.0f}s  rate={rate:.1f}/s  eta={remaining:.0f}s", flush=True)

    elapsed_total = time.time() - t0
    print(f"\ndone — inserted={inserted}, failed={failed}, elapsed={elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
