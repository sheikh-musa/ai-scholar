#!/usr/bin/env bash
# Durable boot for the OLD-Bayan-bot redirect responder (@mzninterfacebot -> @bayanQAbot).
# Sources the dedicated redirect config for the OLD token, then long-polls forever.
# Run under launchd (dev.wingmen.bayan-redirect, KeepAlive) on the Studio host.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Dedicated config (chmod 600): OLD_BOT_TOKEN=... NEW_BOT_USERNAME=bayanQAbot
CONFIG="$REPO_DIR/.env.bayan-redirect"
if [[ -f "$CONFIG" ]]; then
  set -a; source "$CONFIG"; set +a
fi

# Never bill Claude API — this responder makes no LLM calls, but scrub anyway.
unset ANTHROPIC_API_KEY 2>/dev/null || true

: "${OLD_BOT_TOKEN:?OLD_BOT_TOKEN missing (set in $CONFIG)}"
export NEW_BOT_USERNAME="${NEW_BOT_USERNAME:-bayanQAbot}"

exec /usr/bin/python3 "$SCRIPT_DIR/bayan_redirect_bot.py"
