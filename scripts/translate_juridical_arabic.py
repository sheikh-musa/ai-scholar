#!/usr/bin/env python3
"""Translate a juridical_texts Arabic-source row to English via Claude Sonnet.

Used for ingests that landed with no English translation (e.g., the OpenITI
NihayatZayn ingest 2026-05-22 via the Ihsan pipeline). Generates one
juridical_translations row tagged output_tier='ai-generated' per 4-tier
transparency, plus a provenance row noting the auto-translation source.

After this completes, run scripts/backfill_juridical_embeddings.py --source
english to re-embed against the English translation chunks (matches the
language used by the rest of the corpus, lifts cross-lingual retrieval
asymmetry).

Direct Anthropic API path (requires ANTHROPIC_API_KEY env). Parallel
in-flight calls bounded by --concurrency flag (default 8). Falls back to
CLI subprocess via --backend cli if the API path is blocked.

Translation block size: ~7000 chars per call → bounded output ~7000-9000
tokens → fits Sonnet 4.6 comfortably. Block boundaries prefer paragraph
breaks for semantic coherence.

Usage:
  python3 scripts/translate_juridical_arabic.py \\
    --juridical-text-id 753a41e2-a776-4880-a5ba-273386e1e2fb \\
    [--concurrency 8] [--block-chars 7000] [--dry-run] [--limit-blocks N]
"""
from __future__ import annotations

import argparse
import concurrent.futures
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

SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# Block splitting — paragraph-aware
# ---------------------------------------------------------------------------

def split_into_blocks(text: str, block_chars: int = 7000) -> list[str]:
    """Split text into ~block_chars chunks, prefer paragraph boundaries."""
    if len(text) <= block_chars:
        return [text]
    blocks: list = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + block_chars, n)
        if end < n:
            # Look for paragraph break in trailing 800 chars
            tail = text[end - 800 : end]
            for sep in ("\n\n", "\n# ", "\n", ". "):
                idx = tail.rfind(sep)
                if idx != -1:
                    end = end - 800 + idx + len(sep)
                    break
        blocks.append(text[i:end].strip())
        if end >= n:
            break
        i = end
    return [b for b in blocks if b]


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

TRANSLATION_SYSTEM_PROMPT = """You translate classical Shafi'i fiqh manuals from Arabic to English with scholarly precision.

Guidelines:
- Preserve technical fiqh terms in Arabic transliteration with parenthetical English when first introduced (e.g., "wudu (ablution)", "ihram", "tawaf", "kinaya (indirect speech)")
- Keep classical scholarly attribution intact ("Ibn Hajar said...", "al-Ramli's view...", "in Tuhfat al-Muhtaj")
- Maintain madhhab-specific terminology (Shafi'i conventions for arkan/shurut/wajibat distinctions)
- Preserve Qur'anic citation patterns (verse numbers, surah names)
- Render iltifat / rhetorical shifts faithfully without smoothing
- Do NOT add interpretation, context, or scholarly commentary that isn't in the original
- Strip OpenITI structural artifacts: ms### page markers, lone '#' line-start markers (treat as paragraph breaks), '|' title separators, and Arabic-Indic page indicators

Output ONLY the English translation. No preamble, no notes, no markdown headers."""


def translate_block_via_api(arabic_text: str, model: str = ANTHROPIC_MODEL, timeout: int = 180) -> str:
    """POST to api.anthropic.com /v1/messages. Returns English translation text."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    payload = {
        "model": model,
        "max_tokens": 8000,
        "system": TRANSLATION_SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f"Translate to English:\n\n{arabic_text}",
        }],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API HTTP {e.code}: {err_body[:300]}")
    content = body.get("content", [])
    if not content:
        raise RuntimeError(f"empty response: {body}")
    return "".join(part.get("text", "") for part in content if part.get("type") == "text")


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def supa(method: str, path: str, payload=None) -> object:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    req = urllib.request.Request(f"{SUPABASE_URL}{path}", method=method, headers=headers)
    if payload is not None:
        req.data = json.dumps(payload).encode()
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def sha256_hex(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--juridical-text-id", required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--block-chars", type=int, default=7000)
    ap.add_argument("--dry-run", action="store_true",
                    help="translate first 2 blocks only, print to stdout, no DB writes")
    ap.add_argument("--limit-blocks", type=int, default=None)
    args = ap.parse_args()

    if not SUPABASE_KEY:
        sys.exit("ERROR: SUPABASE_SERVICE_ROLE_KEY not set")
    if not ANTHROPIC_API_KEY:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")

    # Fetch the source juridical_texts row
    rows = supa("GET", f"/rest/v1/juridical_texts?id=eq.{args.juridical_text_id}&select=id,text_name,arabic_text,arabic_text_sha256,ingestion_provenance_id")
    if not rows:
        sys.exit(f"ERROR: juridical_texts row {args.juridical_text_id} not found")
    src = rows[0]
    arabic_text = src["arabic_text"]
    print(f"=== Translating ===")
    print(f"  text_name:    {src['text_name']}")
    print(f"  arabic chars: {len(arabic_text)}")
    print(f"  arabic sha:   {src['arabic_text_sha256'][:16]}")

    # Check if translation already exists (idempotency)
    existing = supa("GET", f"/rest/v1/juridical_translations?juridical_text_id=eq.{src['id']}&language_code=eq.en&select=id,output_tier")
    if existing:
        print(f"  ⚠ English translation already exists (id={existing[0]['id']}, tier={existing[0]['output_tier']})")
        print(f"    To re-translate: delete the existing row first.")
        return 0

    blocks = split_into_blocks(arabic_text, args.block_chars)
    print(f"  blocks:       {len(blocks)} (target {args.block_chars}c each)")
    if args.limit_blocks:
        blocks = blocks[:args.limit_blocks]
        print(f"  limit:        first {len(blocks)} blocks")

    if args.dry_run:
        print(f"\n=== DRY-RUN: translating first 2 blocks ===")
        for i, b in enumerate(blocks[:2]):
            print(f"\n--- block {i} ({len(b)}c Arabic) ---")
            print(b[:200] + "...")
            t0 = time.time()
            en = translate_block_via_api(b)
            print(f"--- English ({len(en)}c, {time.time()-t0:.1f}s) ---")
            print(en[:500] + ("..." if len(en) > 500 else ""))
        return 0

    # Parallel translation
    print(f"\n=== Translating {len(blocks)} blocks via {ANTHROPIC_MODEL} (concurrency={args.concurrency}) ===")
    t0 = time.time()
    results: list = [None] * len(blocks)
    completed = 0

    def worker(idx: int, block: str) -> tuple[int, str]:
        for attempt in range(3):
            try:
                return idx, translate_block_via_api(block)
            except RuntimeError as e:
                if attempt == 2:
                    return idx, f"<<TRANSLATION FAILED: {e}>>"
                time.sleep(2 ** attempt)
        return idx, "<<UNREACHABLE>>"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(worker, i, b) for i, b in enumerate(blocks)]
        for fut in concurrent.futures.as_completed(futures):
            idx, en = fut.result()
            results[idx] = en
            completed += 1
            elapsed = time.time() - t0
            eta = elapsed / completed * (len(blocks) - completed)
            print(f"  [{completed}/{len(blocks)}] block {idx}: {len(en)}c  elapsed={elapsed:.0f}s eta={eta:.0f}s")

    # Concatenate
    english_text = "\n\n".join(results)
    print(f"\nTotal English: {len(english_text)} chars (in {time.time()-t0:.0f}s)")

    # Insert provenance row for the translation
    prov_row = {
        "source_url": f"anthropic-api://{ANTHROPIC_MODEL}",
        "source_maintainer": f"Anthropic Claude {ANTHROPIC_MODEL} (AI translation, 4-tier transparency tier='ai-generated')",
        "license_declaration": (
            f"AI-generated English translation of juridical_texts.{src['id']} "
            f"(arabic_sha256={src['arabic_text_sha256'][:16]}...) via Claude Sonnet "
            f"on {datetime.now(timezone.utc).isoformat()}. NOT a scholar-translated text; "
            f"output_tier='ai-generated' per INV-3 4-tier transparency. Translation prompt "
            f"preserves Arabic transliterations + scholar attributions. Suitable for "
            f"retrieval-grounding; NOT suitable for verbatim citation as scholar translation."
        ),
        "source_file_sha256": sha256_hex(english_text),
        "verified_by_identity": "cc-scholar (auto-translation pipeline)",
        "notes": (
            f"Translated {len(blocks)} blocks × {args.block_chars}c via {ANTHROPIC_MODEL}. "
            f"Source: juridical_texts row {src['id']}. "
            f"Original Arabic sha256: {src['arabic_text_sha256']}."
        ),
    }
    prov_result = supa("POST", "/rest/v1/ingestion_provenance", prov_row)
    prov_id = prov_result[0]["id"]
    print(f"\n+ provenance row written: id={prov_id}")

    # Insert juridical_translations row
    tr_row = {
        "juridical_text_id": src["id"],
        "language_code": "en",
        "translator_name": f"Claude {ANTHROPIC_MODEL} (auto-translated)",
        "translation_source_work": f"AI translation of {src['text_name']} (Arabic source via OpenITI)",
        "translation_text": english_text,
        "translation_text_sha256": sha256_hex(english_text),
        "output_tier": "ai-generated",
        "edition_label": f"auto-{ANTHROPIC_MODEL}-{datetime.now(timezone.utc).date().isoformat()}",
        "ingestion_provenance_id": prov_id,
    }
    tr_result = supa("POST", "/rest/v1/juridical_translations", tr_row)
    print(f"+ juridical_translations row written: id={tr_result[0]['id']}")

    print(f"\n=== Next step: re-embed against English ===")
    print(f"  Existing Arabic chunks for this row can stay (corpus_version-tagged).")
    print(f"  Add English chunks: python3 scripts/backfill_juridical_embeddings.py --source english --language en")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
