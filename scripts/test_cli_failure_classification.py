#!/usr/bin/env python3
"""Unit test for the Claude-CLI transient-failure classifier (msg #2737).

Standalone runner (no pytest dep): `python3 scripts/test_cli_failure_classification.py`.
Verifies _is_transient_cli_error distinguishes network blips (retry) from
genuine processing errors (surface honestly) — the root cause of the operator's
"Error: unknown" was a network blip that should have been retried.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_module():
    """Import mizan_bot without running its __main__ polling loop."""
    path = os.path.join(_HERE, "mizan_bot.py")
    spec = importlib.util.spec_from_file_location("mizan_bot_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    # mizan_bot.py guards side effects under __name__ == "__main__"; importing
    # as a non-main module loads the helpers without starting the bot.
    spec.loader.exec_module(mod)
    return mod


def run():
    mb = _load_module()
    fn = mb._is_transient_cli_error

    transient = [
        "No route to host",
        "OSError: [Errno 65] No route to host",
        "Connection reset by peer",
        "Errno 54 connection reset",
        "the read operation timed out",
        "Temporary failure in name resolution",
        "could not resolve host: api.anthropic.com",
        "ssl.SSLEOFError: EOF occurred in violation of protocol",
        "Connection refused",
        "Network is unreachable",
    ]
    non_transient = [
        "empty output",
        "invalid prompt: token limit exceeded",
        "Error: authentication failed (401)",
        "Permission denied: CLAUDE_PATH not executable",
        "",
        None,
        "model returned malformed json",
    ]

    failures = []
    for s in transient:
        if not fn(s):
            failures.append(f"  EXPECTED transient, got non-transient: {s!r}")
    for s in non_transient:
        if fn(s):
            failures.append(f"  EXPECTED non-transient, got transient: {s!r}")

    # The honest messages must never contain the old catch-all phrasing.
    for name in ("_CLI_NETWORK_MSG", "_CLI_PROCESSING_MSG", "_CLI_UNEXPECTED_MSG"):
        msg = getattr(mb, name)
        if "unknown" in msg.lower():
            failures.append(f"  {name} still contains 'unknown': {msg!r}")
        if not msg.strip():
            failures.append(f"  {name} is empty")

    if failures:
        print("FAIL:")
        print("\n".join(failures))
        sys.exit(1)
    n = len(transient) + len(non_transient)
    print(f"PASS: {n} classification cases + 3 message checks")


if __name__ == "__main__":
    run()
