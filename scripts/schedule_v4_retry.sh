#!/bin/bash
# Scheduled v4 retry-failed pass. Sleeps until Wednesday 2026-05-13 16:00 SGT
# (= 08:00 UTC), then polls probe daemon for green-state clearance, then fires
# python3 scripts/enrich_topic_tags_v4_ihsan.py retry-failed.
#
# Adds 5 min buffer after reset for bucket to settle. Then waits up to 20 min
# for probe to report green; if still not green after 20 min, aborts with a
# log entry (manual intervention needed).

set -uo pipefail   # NOT -e: we want the script to log failures, not exit silently

REPO_DIR="/Users/sheikhmusa/wingmen/projects/ai-scholar"
RESET_TS="2026-05-13T16:00:00Z"  # macOS date -j parses without tz; SGT+8 means pass SGT wall-clock to get UTC 08:00
LOG_FILE="$REPO_DIR/logs/v4_retry_scheduler.log"
PROBE_STATE="$REPO_DIR/scripts/.probe_state.json"
POST_RESET_BUFFER_SEC=300  # 5 min after reset before checking probe
MAX_GREEN_WAIT_SEC=1200    # 20 min max wait for green probe

cd "$REPO_DIR"

log() { echo "[$(date -u +'%FT%TZ')] $*" | tee -a "$LOG_FILE"; }

NOW_TS=$(date -u +"%s")
RESET_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$RESET_TS" +"%s" 2>/dev/null)
SLEEP_SECS=$((RESET_EPOCH - NOW_TS + POST_RESET_BUFFER_SEC))

if [ "$SLEEP_SECS" -le 0 ]; then
    log "ERROR: reset timestamp $RESET_TS is in the past (sleep_secs=$SLEEP_SECS); aborting"
    exit 1
fi

log "scheduler started PID=$$, sleeping $SLEEP_SECS sec until reset+buffer ($(date -u -r $((NOW_TS + SLEEP_SECS)) +'%FT%TZ'))"
sleep "$SLEEP_SECS"

log "wakeup — polling probe daemon for clear state (max ${MAX_GREEN_WAIT_SEC}s)"
WAITED=0
while [ "$WAITED" -lt "$MAX_GREEN_WAIT_SEC" ]; do
    if [ -f "$PROBE_STATE" ]; then
        STATE=$(python3 -c "import json,sys; print(json.load(open('$PROBE_STATE'))['state'])" 2>/dev/null || echo "parse-error")
    else
        STATE="no-probe-state-file"
    fi
    log "  probe state: $STATE  (waited ${WAITED}s)"
    if [ "$STATE" = "clear" ]; then
        log "  GREEN — firing v4 retry-failed"
        nohup python3 scripts/enrich_topic_tags_v4_ihsan.py retry-failed > logs/v4_retry.log 2>&1 &
        RETRY_PID=$!
        log "  v4 retry-failed PID=$RETRY_PID"
        exit 0
    fi
    sleep 60
    WAITED=$((WAITED + 60))
done

log "FAILED to detect green probe state after ${MAX_GREEN_WAIT_SEC}s — aborting auto-retry"
log "manual intervention: cd $REPO_DIR && python3 scripts/enrich_topic_tags_v4_ihsan.py retry-failed"
exit 1
