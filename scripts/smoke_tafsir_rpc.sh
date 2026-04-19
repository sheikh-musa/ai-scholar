#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Preflight: verifies the search_tafsir_fts RPC is deployed and responding.
# Run this before smoke_tafsir_fts.sh to isolate T1 vs T2 failures.
#
# Exercises the search_tafsir_fts RPC against the live Supabase project
# (tscuymavysscrvoberrr) with 5 queries that should surface tafsir matches.
#
# REQUIRES the T1 migration (supabase/migrations/20260419_001_search_tafsir_fts.sql)
# to be applied to the live DB first. If the RPC is missing, PostgREST will
# return a 404 and this script exits non-zero.
#
# Env loading:
#   - Sources .env if present (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, etc.)
#   - Requires SUPABASE_URL (defaults to tscuymavysscrvoberrr.supabase.co)
#   - Requires one of SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
#
# Usage:
#   ./scripts/smoke_tafsir_fts.sh
#
# Exit codes:
#   0 — every query returned HTTP 2xx (zero hits is a legitimate result)
#   1 — missing env, curl error, or any query returned a non-2xx status
# ---------------------------------------------------------------------------
set -euo pipefail

# --- env loading ------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

: "${SUPABASE_URL:=https://tscuymavysscrvoberrr.supabase.co}"

API_KEY="${SUPABASE_SERVICE_ROLE_KEY:-${SUPABASE_ANON_KEY:-}}"
if [ -z "$API_KEY" ]; then
  echo "ERROR: no API key found." >&2
  echo "  Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY in .env or the shell env." >&2
  exit 1
fi

RPC_URL="${SUPABASE_URL%/}/rest/v1/rpc/search_tafsir_fts"

# jq is preferred for parsing; fall back to grep heuristics if missing.
HAS_JQ=0
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
fi

# --- test queries -----------------------------------------------------------
QUERIES=(
  "patience in affliction"
  "pilgrimage hajj rites"
  "forgiveness of sins"
  "zakat obligation"
  "light of the heavens"
)

echo "Smoke target: $RPC_URL"
echo "jq available: $HAS_JQ"
echo "---"

fail=0
for q in "${QUERIES[@]}"; do
  payload=$(printf '{"query": %s, "lim": 5}' "$(printf '%s' "$q" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")

  http_and_body=$(curl -sS -w $'\n__HTTP_STATUS__%{http_code}' \
    -X POST "$RPC_URL" \
    -H "apikey: $API_KEY" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    --data "$payload" || true)

  http_status="${http_and_body##*__HTTP_STATUS__}"
  body="${http_and_body%$'\n'__HTTP_STATUS__*}"

  echo ""
  echo "Query: \"$q\""
  echo "  HTTP: $http_status"

  if [[ ! "$http_status" =~ ^2 ]]; then
    echo "  ERROR: non-2xx response"
    echo "  Body: $(printf '%s' "$body" | head -c 500)"
    fail=$((fail + 1))
    continue
  fi

  if [ "$HAS_JQ" -eq 1 ]; then
    hits=$(printf '%s' "$body" | jq 'length' 2>/dev/null || echo "0")
    echo "  Hits: $hits"
    if [ "$hits" != "0" ] && [ -n "$hits" ]; then
      first=$(printf '%s' "$body" | jq -r '.[0] | "\(.surah_number):\(.ayah_number)  scholar=\(.scholar_name // "?")  source=\(.source_work // "?")"')
      echo "  First: $first"
    fi
  else
    # crude fallback when jq is unavailable
    hits=$(printf '%s' "$body" | grep -o '"ayah_id"' | wc -l | tr -d ' ')
    echo "  Hits (approx): $hits"
    first_snippet=$(printf '%s' "$body" | head -c 300)
    echo "  First snippet: $first_snippet"
  fi
done

echo ""
echo "---"
if [ "$fail" -gt 0 ]; then
  echo "FAILED: $fail query/queries returned a non-2xx status"
  exit 1
fi
echo "OK: all ${#QUERIES[@]} queries returned 2xx"
