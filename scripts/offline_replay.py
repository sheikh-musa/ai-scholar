#!/usr/bin/env python3
"""Replay queries through the live mizan_bot.py pipeline with no Telegram and
no production-DB writes (MIZAN_TEST_MODE=1 short-circuits persist_emission).

For reproducing/judging specific historical mizan_interactions rows offline
(e.g. before/after a retrieval or prompt fix) without touching real traffic.

Usage:
  python3 scripts/offline_replay.py "query one" "query two"
"""
import argparse
import os
import sys

os.environ["MIZAN_BOT_TOKEN"] = os.environ.get("MIZAN_BOT_TOKEN", "offline-replay-unused")
os.environ["MIZAN_TEST_MODE"] = "1"
os.environ.setdefault("ENCODER_URL", "http://127.0.0.1:8080")
os.environ.pop("ANTHROPIC_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mizan_bot import gather_context, ask_claude, RetrievalMeta, build_keyed_answer  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queries", nargs="+", help="Query text(s) to replay")
    args = parser.parse_args()

    for q in args.queries:
        print(f"\n{'=' * 80}\nQUERY: {q}\n{'=' * 80}")
        meta = RetrievalMeta()
        context = gather_context(q, meta=meta)
        print(f"--- retrieval_config: {meta.retrieval_config}")
        keyed_fallback = build_keyed_answer(q)
        answer = ask_claude(q, context, None, answer_level="seeker", madhhab=None, fallback_answer=keyed_fallback)
        print(f"--- ANSWER:\n{answer}")


if __name__ == "__main__":
    main()
