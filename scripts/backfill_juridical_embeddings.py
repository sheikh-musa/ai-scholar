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
CORPUS_VERSION = os.environ.get("CORPUS_VERSION", "marbuqi-safinat-2009-v1-chunked-1500-200")
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
    ap.add_argument("--language", default="en")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    enc_sha = encoder_sha()
    print(f"encoder: {ENCODER_URL} model={ENCODER_MODEL} sha={enc_sha}")

    q = f"/rest/v1/juridical_translations?select=id,juridical_text_id,translation_text&language_code=eq.{args.language}"
    if args.limit:
        q += f"&limit={args.limit}"
    rows = supa("GET", q)
    if not rows:
        print(f"no translations for language={args.language}")
        return 0

    # Chunk-then-mean-pool: bge-m3 attention scales quadratically with seq_len,
    # so naive whole-chapter embedding OOMs. Schema PK is juridical_text_id alone
    # (one row per text), so we cannot store per-chunk rows under current schema.
    # Mitigation: chunk each text into 1500-char windows, embed each, then
    # mean-pool the chunk vectors and re-normalize to produce a single
    # document-level embedding per text. Loses fine-grained retrieval until
    # Phase 3 schema migration to per-chunk rows; coarse-now is operator-chosen
    # (option A, 2026-05-10).
    BATCH = int(os.environ.get("EMBED_BATCH", "8"))
    now = datetime.now(timezone.utc).isoformat()
    payloads = []
    for r in rows:
        text = r["translation_text"]
        chunks = chunk_text(text)
        if not chunks:
            print(f"  skip {r['id'][:8]}: no chunks", file=sys.stderr)
            continue
        chunk_vecs: list = []
        for i in range(0, len(chunks), BATCH):
            chunk_vecs.extend(embed_batch(chunks[i : i + BATCH]))
        # Mean-pool + L2 renormalize.
        dim = len(chunk_vecs[0])
        pooled = [sum(v[j] for v in chunk_vecs) / len(chunk_vecs) for j in range(dim)]
        norm = sum(x * x for x in pooled) ** 0.5
        pooled = [x / norm for x in pooled] if norm else pooled
        payloads.append({
            "juridical_text_id": r["juridical_text_id"],
            "embedding": pooled,
            "embedding_model": ENCODER_MODEL,
            "encoder_sha": enc_sha,
            "corpus_version": CORPUS_VERSION,
            "embedded_source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "source_token_count": len(text.split()),
            "created_at": now,
            "updated_at": now,
        })
        print(f"  pooled {len(chunks)} chunks -> 1 vector for {r['id'][:8]}")

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
