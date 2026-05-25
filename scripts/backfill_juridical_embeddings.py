#!/usr/bin/env python3
# Phase 2 backfill for EMBED-PIPELINE-LOCAL-MAC-STUDIO-001 (id 814).
# Reads juridical_translations.translation_text, embeds via local bge-m3
# encoder service on Studio Tailscale IP, writes juridical_embeddings.
#
# Run after Phase 1 install (scripts/studio_install/phase1_install.sh)
# completes and encoder service responds on http://100.104.36.27:8080/health.
#
# Substrate-verified 2026-05-08T16:06Z: juridical_embeddings FK is
# juridical_text_id (Arabic side), vector(1024) for bge-m3.

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ENCODER_URL = os.environ.get("ENCODER_URL", "http://100.104.36.27:8080")
ENCODER_MODEL = "BAAI/bge-m3"
CORPUS_VERSION = os.environ.get("CORPUS_VERSION", "marbuqi-safinat-2009-v2-per-chunk-1500-200")
CHUNK_CHARS = int(os.environ.get("CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sliding window over characters. Prefers paragraph boundaries within
    the trailing 200 chars of each window so chunks are semantically cleaner.
    """
    if not text:
        return []
    chunks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            tail_zone = text[end - overlap : end]
            for sep in ("\n\n", "\n", ". ", "; "):
                idx = tail_zone.rfind(sep)
                if idx != -1:
                    end = end - overlap + idx + len(sep)
                    break
        chunks.append(text[i:end].strip())
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


def http(method, url, payload=None, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if payload is not None:
        req.data = json.dumps(payload).encode()
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        return json.loads(body) if body else None


def supa(method, path, payload=None, prefer=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return http(method, f"{SUPABASE_URL}{path}", payload, headers)


def embed_batch(texts):
    return http(
        "POST",
        f"{ENCODER_URL}/embed",
        {"inputs": texts},
        {"Content-Type": "application/json"},
    )["embeddings"]


def encoder_sha():
    h = http("GET", f"{ENCODER_URL}/health", headers={})
    return h.get("model_sha") or "bge-m3-unpinned"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="en",
                    help="(english-source path) ISO 639-1 language code in juridical_translations")
    ap.add_argument("--source", choices=("english", "arabic"), default="english",
                    help="english: chunk from juridical_translations.translation_text. "
                         "arabic: chunk from juridical_texts.arabic_text (for ingests with no English translation).")
    ap.add_argument("--juridical-text-id",
                    help="(arabic-source path) restrict to a single juridical_texts row by uuid")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    enc_sha = encoder_sha()
    print(f"encoder: {ENCODER_URL} model={ENCODER_MODEL} sha={enc_sha}")
    print(f"corpus_version: {CORPUS_VERSION} chunk={CHUNK_CHARS}c/{CHUNK_OVERLAP}c overlap source={args.source}")

    # Two source paths: english (juridical_translations) and arabic (juridical_texts directly).
    # bge-m3 is multilingual, so Arabic embeddings retrieve fine on English queries.
    if args.source == "english":
        q = f"/rest/v1/juridical_translations?select=id,juridical_text_id,translation_text&language_code=eq.{args.language}"
        if args.juridical_text_id:
            q += f"&juridical_text_id=eq.{args.juridical_text_id}"
        text_field = "translation_text"
        id_field = "id"
    else:
        # Arabic-source: query juridical_texts directly
        q = f"/rest/v1/juridical_texts?select=id,arabic_text"
        if args.juridical_text_id:
            q += f"&id=eq.{args.juridical_text_id}"
        text_field = "arabic_text"
        id_field = "id"
    if args.limit:
        q += f"&limit={args.limit}"
    rows = supa("GET", q)
    if not rows:
        print(f"no rows for {args.source}-source query")
        return 0

    # Per-chunk embedding (Phase 3 schema migration 20260511_001 enabled this).
    # Each chunk → its own juridical_embeddings row with chunk_index + chunk_text.
    # Composite PK (juridical_text_id, chunk_index) allows N rows per text.
    BATCH = int(os.environ.get("EMBED_BATCH", "8"))
    now = datetime.now(timezone.utc).isoformat()
    payloads = []
    for r in rows:
        text = r[text_field]
        chunks = chunk_text(text)
        if not chunks:
            print(f"  skip {r[id_field][:8]}: no chunks", file=sys.stderr)
            continue
        chunk_vecs: list = []
        for i in range(0, len(chunks), BATCH):
            chunk_vecs.extend(embed_batch(chunks[i : i + BATCH]))
        # Resolve juridical_text_id: english path has explicit FK, arabic path uses row id directly
        juridical_text_id = r.get("juridical_text_id") or r["id"]
        for idx, (chunk, vec) in enumerate(zip(chunks, chunk_vecs)):
            payloads.append({
                "juridical_text_id": juridical_text_id,
                "chunk_index": idx,
                "chunk_text": chunk,
                "embedding": vec,
                "embedding_model": ENCODER_MODEL,
                "encoder_sha": enc_sha,
                "corpus_version": CORPUS_VERSION,
                "embedded_source_hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                "source_token_count": len(chunk.split()),
                "created_at": now,
                "updated_at": now,
            })
        print(f"  {r[id_field][:8]}: {len(chunks)} chunks queued")

    if args.dry_run:
        print("dry-run; first payload preview:")
        sample = {**payloads[0], "embedding": f"<vec dim={len(payloads[0]['embedding'])}>"}
        print(json.dumps(sample, indent=2))
        return 0

    res = supa("POST", "/rest/v1/juridical_embeddings", payloads, prefer="return=representation")
    print(f"inserted {len(res) if res else 0} rows into juridical_embeddings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
