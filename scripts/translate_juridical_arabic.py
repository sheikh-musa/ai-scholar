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
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SUPABASE_URL = "https://tscuymavysscrvoberrr.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# Default backend: Claude CLI via Max plan subscription (per memory
# feedback_claude_max_default.md). Direct Anthropic API path is opt-in
# only via --backend api flag and requires ANTHROPIC_API_KEY env.
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
CLAUDE_ENV = {
    "HOME": os.path.expanduser("~"),
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "USER": os.environ.get("USER", ""),
    "SHELL": os.environ.get("SHELL", ""),
    "LANG": os.environ.get("LANG", ""),
}
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
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


class RateLimitError(RuntimeError):
    """Throttle signal — back off significantly (CLI Max-plan or API 429)."""


_THROTTLE_MARKERS = (
    "rate limit", "rate_limit", "ratelimit", "too many requests", "429",
    "usage limit", "usage_limit", "throttl", "quota", "exceeded",
)


def translate_block_via_cli(arabic_text: str, model: str = DEFAULT_MODEL, timeout: int = 480) -> str:
    """Call ~/.local/bin/claude -p via subprocess (Max plan, no API billing).
    Raises RateLimitError on detected throttle so caller can back off properly.

    Detection (per v5 enrich pattern): explicit throttle keywords in stderr,
    OR returncode!=0 with stderr length <50 (Claude CLI 2.1.x silent-failure
    on Max-plan throttle window — observed empirically during v5 enrichment).
    """
    system_in_user = f"{TRANSLATION_SYSTEM_PROMPT}\n\n---\n\nTranslate to English:\n\n{arabic_text}"
    cmd = [CLAUDE_BIN, "-p", system_in_user, "--model", model, "--output-format", "text"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=CLAUDE_ENV)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"CLI timeout after {timeout}s")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip().lower()
        if any(m in stderr for m in _THROTTLE_MARKERS):
            raise RateLimitError(f"CLI throttle: {result.stderr[:200]}")
        if len(stderr) < 50:
            # Silent-failure pattern is also throttle per v5 finding
            raise RateLimitError(f"CLI silent rc={result.returncode} (likely throttle)")
        raise RuntimeError(f"CLI returncode={result.returncode}: {result.stderr[:200]}")
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("CLI returned empty stdout")
    return output


def translate_block_via_api(arabic_text: str, model: str = "claude-sonnet-4-6", timeout: int = 180) -> str:
    """OPT-IN path: direct Anthropic REST. Requires ANTHROPIC_API_KEY env.
    Use this ONLY when --backend api is explicitly passed; default is CLI/Max.
    Per feedback_claude_max_default.md memory: API-key billing is wasteful
    when Max subscription covers the work."""
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
        if e.code == 429:
            raise RateLimitError(f"HTTP 429: {err_body[:200]}")
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
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--block-chars", type=int, default=7000)
    ap.add_argument("--backend", choices=("cli", "api"), default="cli",
                    help="cli: Claude CLI subprocess via Max plan (default — Musa pays "
                         "flat sub, no per-call billing). api: direct Anthropic REST with "
                         "ANTHROPIC_API_KEY (opt-in only; isrāf to use when Max covers it).")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="CLI model alias (sonnet/opus/haiku) or full model id")
    ap.add_argument("--dry-run", action="store_true",
                    help="translate first 2 blocks only, print to stdout, no DB writes")
    ap.add_argument("--limit-blocks", type=int, default=None)
    args = ap.parse_args()

    if not SUPABASE_KEY:
        sys.exit("ERROR: SUPABASE_SERVICE_ROLE_KEY not set")
    if args.backend == "api" and not ANTHROPIC_API_KEY:
        sys.exit("ERROR: --backend api requires ANTHROPIC_API_KEY env")

    # Bind the translator function based on backend choice
    if args.backend == "cli":
        def translate_block(text):
            return translate_block_via_cli(text, model=args.model)
        backend_label = f"Claude CLI Max plan / model={args.model}"
    else:
        def translate_block(text):
            return translate_block_via_api(text)
        backend_label = "Anthropic REST API (API-key billing, opt-in)"

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
        print(f"\n=== DRY-RUN: translating first 2 blocks via {backend_label} ===")
        for i, b in enumerate(blocks[:2]):
            print(f"\n--- block {i} ({len(b)}c Arabic) ---")
            print(b[:200] + "...")
            t0 = time.time()
            en = translate_block(b)
            print(f"--- English ({len(en)}c, {time.time()-t0:.1f}s) ---")
            print(en[:500] + ("..." if len(en) > 500 else ""))
        return 0

    # Checkpoint file — persist per-block translations so retries resume.
    # Keyed by SHA of source row id (one checkpoint per juridical_text_id).
    from pathlib import Path
    checkpoint_path = Path(__file__).parent / f".translate_{src['id']}.checkpoint.json"
    if checkpoint_path.exists():
        cp = json.loads(checkpoint_path.read_text())
        results = cp.get("results", [None] * len(blocks))
        if len(results) != len(blocks):
            print(f"  ⚠ checkpoint block count mismatch ({len(results)} vs {len(blocks)}), starting fresh")
            results = [None] * len(blocks)
        else:
            done = sum(1 for r in results if r and len(r) > 1000)
            print(f"  ⏵ resuming from checkpoint: {done}/{len(blocks)} blocks already done")
    else:
        results = [None] * len(blocks)

    def save_checkpoint(rs):
        checkpoint_path.write_text(json.dumps({
            "juridical_text_id": src["id"],
            "block_count": len(blocks),
            "results": rs,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }))

    # Parallel translation with throttle-aware backoff
    print(f"\n=== Translating {len(blocks)} blocks via {backend_label} (concurrency={args.concurrency}) ===")
    t0 = time.time()
    completed = sum(1 for r in results if r and len(r) > 1000)

    def worker(idx: int, block: str) -> tuple[int, str]:
        # Skip if already translated cleanly in a prior run
        if results[idx] is not None and len(results[idx]) > 1000:
            return idx, results[idx]
        # Backoff schedule: 30, 60, 120, 240, 480 (max ~15.5m total per block)
        backoffs = [30, 60, 120, 240, 480]
        for attempt in range(len(backoffs) + 1):
            try:
                return idx, translate_block(block)
            except RateLimitError as e:
                if attempt == len(backoffs):
                    return idx, f"<<TRANSLATION FAILED after {attempt+1} throttle retries: {e}>>"
                wait = backoffs[attempt]
                print(f"    [block {idx}] throttle, backing off {wait}s (attempt {attempt+1}/{len(backoffs)})")
                time.sleep(wait)
            except RuntimeError as e:
                # Non-throttle transient — short retry
                if attempt < 2:
                    time.sleep(5)
                    continue
                return idx, f"<<TRANSLATION FAILED: {e}>>"
        return idx, "<<UNREACHABLE>>"

    # Iterative checkpoint save after each future completes
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(worker, i, b) for i, b in enumerate(blocks)]
        for fut in concurrent.futures.as_completed(futures):
            idx, en = fut.result()
            results[idx] = en
            completed += 1
            elapsed = time.time() - t0
            eta = elapsed / completed * (len(blocks) - completed) if completed else 0
            print(f"  [{completed}/{len(blocks)}] block {idx}: {len(en)}c  elapsed={elapsed:.0f}s eta={eta:.0f}s")
            if completed % 5 == 0:
                save_checkpoint(results)
    save_checkpoint(results)

    # Check for failures BEFORE writing to DB
    failures = [i for i, r in enumerate(results) if not r or len(r) < 1000]
    if failures:
        print(f"\n⚠ {len(failures)} blocks still failed after all retries: {failures[:10]}{'...' if len(failures)>10 else ''}")
        print(f"  Run again to resume from checkpoint. NOT writing to DB until all blocks succeed.")
        return 1

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
