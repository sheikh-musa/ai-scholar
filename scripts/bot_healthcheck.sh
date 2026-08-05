#!/usr/bin/env bash
# Lightweight liveness watchdog for the client-facing Bayan services (#15609,
# cai-flagged product-uptime gap: mizan_bot.py died silently for ~5 days and
# nobody noticed). One round of checks; posts bus alerts to orch-console on
# failure. SELF-HEALS the answerer: auto-restarts mizan_bot on DEATH or WEDGE
# (#15696 — the wedge is invisible to KeepAlive, so it needs an active kill+relaunch),
# cooldown-gated against thrash. redirect + encoder stay detect-only.
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
WEDGE_MIN_TIMEOUTS="${WEDGE_MIN_TIMEOUTS:-3}" # need this many recent HARD-TIMEOUTs (sustained, not a blip)
RESTART_COOLDOWN="${RESTART_COOLDOWN:-600}" # min seconds between mizan auto-restarts (anti-thrash)
ENCODER_URL="${ENCODER_URL:-http://100.104.36.27:8080}"

# Bus creds: agent_messages lives in the SAME Supabase project as the corpus, so
# ai-scholar/.env suffices (ihsanos/.env.local is absent on the Studio).
set -a; source "$REPO/.env" 2>/dev/null; set +a
BUS_URL="https://tscuymavysscrvoberrr.supabase.co"
BUS_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

_now() { date +%s; }

_mtime() { stat -f %m "$1" 2>/dev/null || echo 0; }

notify() {  # $1=severity(P1|P2)  $2=subject  $3=body  — posts to the bus, NO dedup
  local sev="$1" subj="$2" body="$3"
  if [ -z "$BUS_KEY" ]; then echo "[healthcheck] NO BUS KEY — cannot notify ($subj)"; return; fi
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
    urllib.request.urlopen(req,timeout=10); print("[healthcheck] bus msg sent:",os.environ["SUBJ"])
except Exception as e:
    print("[healthcheck] bus msg FAILED:",e)
PY
}

alert() {  # $1=service key  $2=severity(P1|P2)  $3=detail — dedup'd DOWN alert
  local svc="$1" sev="$2" detail="$3"
  local marker="$STATE_DIR/$svc.down" now last=0
  now=$(_now); [ -f "$marker" ] && last=$(cat "$marker" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$REALERT_SEC" ]; then
    echo "[$(date -u +%FT%TZ)] $svc DOWN ($detail) — alert suppressed (dedup)"; return
  fi
  echo "$now" > "$marker"
  notify "$sev" "[bayan-health] DOWN: $svc" \
    "cc-scholar watchdog: '$svc' failed liveness at $(date -u +%FT%TZ) on the Studio. $detail. Source: scripts/bot_healthcheck.sh."
}

# Auto-heal the @bayanQAbot answerer on DEATH or WEDGE (orch-console #15696: the
# wedge is invisible to KeepAlive since the process stays alive). Cooldown-gated
# to prevent a boot-wedge-restart thrash loop; escalates to manual if it re-fails
# inside the cooldown. Always notifies (cooldown IS the anti-spam, so no dedup).
heal_mizan() {  # $1 = reason
  local reason="$1" now last=0
  now=$(_now)
  local stamp="$STATE_DIR/mizan_bot.lastrestart"
  [ -f "$stamp" ] && last=$(cat "$stamp" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt "$RESTART_COOLDOWN" ]; then
    # already auto-restarted very recently and it's down/wedged AGAIN -> stop thrashing, escalate
    alert mizan_bot P1 "STILL DOWN after an auto-restart <${RESTART_COOLDOWN}s ago ($reason) — thrash guard tripped, NOT restarting again. MANUAL ATTENTION NEEDED."
    return
  fi
  echo "$now" > "$stamp"
  echo "[$(date -u +%FT%TZ)] AUTO-HEAL mizan_bot ($reason): kill + relaunch"
  local p
  for p in $(pgrep -f 'mizan_bot\.py'); do kill -TERM "$p" 2>/dev/null; done
  sleep 3
  for p in $(pgrep -f 'mizan_bot\.py'); do kill -9 "$p" 2>/dev/null; done
  sleep 1
  ( set -a; source "$REPO/.env" 2>/dev/null; set +a
    export HOME="/Users/Musa" USER="Musa" SHELL="/bin/zsh"
    export PATH="/usr/local/bin:/usr/bin:/bin:/Users/Musa/.local/bin"
    cd "$REPO" || exit 1
    nohup /usr/bin/python3 -u scripts/mizan_bot.py >> "$REPO/logs/mizan_bot.log" 2>> "$REPO/logs/mizan_bot.err" & )
  sleep 8
  if pgrep -f 'mizan_bot\.py' >/dev/null 2>&1; then
    rm -f "$STATE_DIR/mizan_bot.down" 2>/dev/null   # recovered; next round re-alerts if it re-wedges
    notify P1 "[bayan-health] AUTO-RESTARTED: mizan_bot" \
      "cc-scholar watchdog AUTO-HEALED @bayanQAbot at $(date -u +%FT%TZ). Trigger: $reason. New pid $(pgrep -f 'mizan_bot\.py' | head -1). getUpdates should recover; please confirm a client query answers. (self-heal per #15696)"
  else
    notify P1 "[bayan-health] AUTO-RESTART FAILED: mizan_bot" \
      "cc-scholar watchdog tried to auto-heal @bayanQAbot ($reason) but NO process came up. MANUAL ATTENTION NEEDED."
  fi
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

  # 1. QA answerer (@bayanQAbot). Auto-heals on DEATH (5-day outage) or WEDGE
  #    (black-holed getUpdates — invisible to KeepAlive). #15696.
  if ! pgrep -f 'mizan_bot\.py' >/dev/null 2>&1; then
    heal_mizan "DEATH — no mizan_bot.py process"
  else
    # WEDGE = SUSTAINED getUpdates black-hole, not a transient blip. The bot's
    # SIGALRM guard self-recovers from a single black-hole (op#10339), so a lone
    # HARD-TIMEOUT is NOT a wedge — restarting on it is futile churn. Only heal if
    # the CURRENT session (after the last boot marker) is CONTINUOUSLY timing out:
    # >= WEDGE_MIN_TIMEOUTS HARD-TIMEOUTs recently AND the log is actively fresh.
    local log="$REPO/logs/mizan_bot.log" age recent nfail
    age=$(( now - $(_mtime "$log") ))
    # lines since the last "Bot is running" boot marker (ignore prior sessions)
    recent=$(awk '/Bot is running/{buf=""} {buf=buf $0 "\n"} END{printf "%s",buf}' "$log" 2>/dev/null | tail -30)
    nfail=$(grep -c 'HARD-TIMEOUT' <<<"$recent")
    if [ "$age" -lt "$WEDGE_FRESH_SEC" ] && [ "$nfail" -ge "$WEDGE_MIN_TIMEOUTS" ]; then
      heal_mizan "WEDGE — $nfail sustained getUpdates HARD-TIMEOUTs, no recovery (black-holed)"
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
