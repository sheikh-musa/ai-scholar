#!/usr/bin/env bash
# Requires T1 migration applied AND T2 Edge Function deployed; run scripts/smoke_tafsir_rpc.sh first for layer isolation.
# Phase 1 smoke — 5 queries that should surface tafsir-FTS matches
# Usage: SUPABASE_ANON_KEY=... ./scripts/smoke_tafsir_fts.sh
set -euo pipefail

URL="https://tscuymavysscrvoberrr.supabase.co/functions/v1/ask-scholar"
: "${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is required}"

QUERIES=(
  "trials and tribulations"
  "ibn kathir patience"
  "gratitude to allah"
  "what is tawakkul"
  "meaning of tawhid"
)

pass=0
fail=0
for q in "${QUERIES[@]}"; do
  resp=$(curl -s -X POST "$URL" \
    -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"$q\"}")
  has_matched=$(echo "$resp" | jq -r '[.matches[]?.tafsir[]? | select(.matched_passage != null)] | length')
  total_tafsir=$(echo "$resp" | jq -r '[.matches[]?.tafsir[]?] | length')
  if [ "$has_matched" -gt 0 ]; then
    echo "PASS  [$q] matched_passages=$has_matched total_tafsir=$total_tafsir"
    pass=$((pass+1))
  else
    echo "FAIL  [$q] no matched_passage surfaced"
    fail=$((fail+1))
  fi
done

echo "---"
echo "Passed: $pass / ${#QUERIES[@]}"
[ "$fail" -eq 0 ]
