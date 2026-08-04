#!/usr/bin/env bash
# Lightweight liveness watchdog for the client-facing Bayan services (#15609,
# cai-flagged product-uptime gap: mizan_bot.py died silently for ~5 days and
# nobody noticed). One round of checks; posts a P1 bus alert to orch-console on
# failure. Detection-only (no auto-restart — KeepAlive/operator owns restart);
# the point is that a dead bot is DETECTED in minutes, not days.
#
# Run modes:
#   scripts/bot_healthcheck.sh           # one round (for launchd StartInterval)
#   scripts/bot_healthcheck.sh --loop    # nohup fallback: round every 300s
#
# Signals (chosen against the two real failure modes):
#   DEATH  — pgrep finds no process           (the 5-day outage: process killed)
#   WEDGE  — process alive but log is actively logging getUpdates HARD-TIMEOUT
#            (black-holed getUpdates; KeepAlive can't catch this — process lives)
#   ENCODER— local bge-m3 /health unreachable (semantic retrieval degraded->FTS)
#
# Dedup: re-alert at most once per REALERT_SEC per service; clears on recovery.
set -uo pipefail

REPO="/Users/Musa/wingmen/projects/ai-scholar"
STATE_DIR="$REPO/logs/healthcheck"; mkdir -p "$STATE_DIR"
REALERT_SEC="${REALERT_SEC:-1800}"          # 30 min between repeat alerts
WEDGE_FRESH_SEC="${WEDGE_FRESH_SEC:-180}"   # HARD-TIMEOUT counts only if log mtime < this
ENCODER_URL="${ENCODER_URL:-http://100.104.36.27:8080}"

# Bus creds: agent_messages lives in the SAME Supabase project as the corpus, so
# ai-scholar/.env suffices (ihsanos/.env.local is absent on the Studio).
set -a; source "$REPO/.env" 2>/dev/null; set +a
BUS_URL="https://tscuymavysscrvoberrr.supabase.co"
BUS_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

_now() { date +%s; }

_mtime() { stat -f %m "$1" 2>/dev/null || echo 0; }

alert() {  # $1=service key  $2=severity(P1|P2)  $3=detail
  local svc="$1" sev="$2" detail="$3"
  local marker="$STATE_DIR/$svc.down" now last=0
  now=$(_now); [ -f "$marker" ] && last=$(cat "$marker" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$REALERT_SEC" ]; then
    echo "[$(date -u +%FT%TZ)] $svc DOWN ($detail) — alert suppressed (dedup)"; return
  fi
  echo "$now" > "$marker"
  local subj="[bayan-health] DOWN: $svc"
  local body="cc-scholar watchdog: client-facing service '$svc' failed liveness at $(date -u +%FT%TZ) on the Studio. $detail. Source: scripts/bot_healthcheck.sh (detection-only). If mizan_bot: @bayanQAbot is not answering — restart it (nohup or load dev.wingmen.mizan-bot.plist)."
  if [ -z "$BUS_KEY" ]; then echo "[healthcheck] NO BUS KEY — cannot alert ($svc)"; return; fi
  BUS_URL="$BUS_URL" BUS_KEY="$BUS_KEY" SUBJ="$subj" BODY="$body" SEV="$sev" python3 - <<'PY'
import os,json,urllib.request
row={"to_agent":"orch-console","from_agent":"cc-scholar","message_type":"update",
     "subject":os.environ["SUBJ"],"body":os.environ["BODY"],
     "priority":os.environ["SEV"],"requires_response":False}
req=urllib.request.Request(os.environ["BUS_URL"]+"/rest/v1/agent_messages",
    data=json.dumps(row).encode(),
    headers={"apikey":os.environ["BUS_KEY"],"Authorization":"Bearer "+os.environ["BUS_KEY"],
             "Content-Type":"application/json"})
try:
    urllib.request.urlopen(req,timeout=10); print("[healthcheck] bus alert sent:",os.environ["SUBJ"])
except Exception as e:
    print("[healthcheck] bus alert FAILED:",e)
PY
}

recover() {  # clear the down-marker + note recovery once
  local svc="$1"
  local marker="$STATE_DIR/$svc.down"
  if [ -f "$marker" ]; then
    rm -f "$marker"
    echo "[$(date -u +%FT%TZ)] $svc RECOVERED"
  fi
}

check_once() {
  local now; now=$(_now)

  # 1. QA answerer (@bayanQAbot). DEATH = the 5-day outage.
  if ! pgrep -f 'mizan_bot\.py' >/dev/null 2>&1; then
    alert mizan_bot P1 "no mizan_bot.py process — the @bayanQAbot answerer is DEAD"
  else
    local log="$REPO/logs/mizan_bot.log" age tail_txt
    age=$(( now - $(_mtime "$log") ))
    tail_txt=$(tail -6 "$log" 2>/dev/null)
    if [ "$age" -lt "$WEDGE_FRESH_SEC" ] && grep -q 'HARD-TIMEOUT' <<<"$tail_txt"; then
      alert mizan_bot P1 "process alive but getUpdates is WEDGED (recent HARD-TIMEOUT, black-holed connection)"
    else
      recover mizan_bot
    fi
  fi

  # 2. Redirect shim (@mzninterfacebot -> @bayanQAbot).
  if pgrep -f 'bayan_redirect_bot\.py' >/dev/null 2>&1; then
    recover redirect
  else
    alert redirect P2 "redirect responder DEAD (old-bot users get no signpost)"
  fi

  # 3. Local encoder (semantic retrieval; graceful FTS-fallback, so P2).
  if curl -s --max-time 4 "$ENCODER_URL/health" 2>/dev/null | grep -q '"status"'; then
    recover encoder
  else
    alert encoder P2 "encoder /health unreachable — semantic retrieval degraded to FTS-only"
  fi

  echo "[$(date -u +%FT%TZ)] healthcheck round complete"
}

if [ "${1:-}" = "--loop" ]; then
  echo "[healthcheck] loop mode, interval ${HEALTHCHECK_INTERVAL:-300}s"
  while true; do check_once; sleep "${HEALTHCHECK_INTERVAL:-300}"; done
else
  check_once
fi
