#!/usr/bin/env python3
"""Fast, network-free tests for the op#48737 query-expansion cap + dedup
(scripts/fiqh_semantic._expand_query) and the _encode WARN-on-failure path.

Run: python3 scripts/test_fiqh_semantic_expansion_cap.py
"""
import io
import sys
import contextlib

sys.path.insert(0, "scripts")
import fiqh_semantic as fs  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    PASS += 1 if cond else 0
    FAIL += 0 if cond else 1


# --- _expand_query: cap ---
long_query = "what are the differences in wudhu between shafii maliki and hanafi"
expanded = fs._expand_query(long_query)
appended = expanded[len(long_query) + 1:]  # +1 for the joining space
check("expansion is capped at QUERY_EXPANSION_MAX_CHARS",
      len(appended) <= fs.QUERY_EXPANSION_MAX_CHARS)
check("original query text is preserved verbatim at the start",
      expanded.startswith(long_query))

# --- _expand_query: dedup ---
repeated_query = "wudhu and wudhu again, how is wudhu done"
expanded_rep = fs._expand_query(repeated_query)
wudu_expansion = fs.QUERY_EXPANSIONS["wudhu"]
check("repeated term's expansion is not duplicated",
      expanded_rep.count(wudu_expansion[:30]) <= 1)

# --- _expand_query: no match -> unchanged ---
plain_query = "something with no dictionary matches at all"
check("query with no QUERY_EXPANSIONS matches is returned unchanged",
      fs._expand_query(plain_query) == plain_query)

# --- _expand_query: empty string ---
check("empty query returns empty", fs._expand_query("") == "")

# --- _encode: WARN-logs on failure (point ENCODER_URL at a closed port) ---
fs.ENCODER_URL = "http://127.0.0.1:1"  # nothing listens here
fs.ENCODER_TIMEOUT_SEC = 1.0
buf = io.StringIO()
with contextlib.redirect_stderr(buf):
    result = fs._encode("test query")
stderr_out = buf.getvalue()
check("_encode returns None on connection failure", result is None)
check("_encode WARN-logs the failure to stderr", "WARN" in stderr_out and "_encode failed" in stderr_out)
check("_encode WARN includes the query length", "query_len=10" in stderr_out)

print(f"\n{'ALL PASS' if FAIL == 0 else 'FAILURES PRESENT'}: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
