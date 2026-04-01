#!/usr/bin/env bash
# AI Scholar — Mac Mini setup script
# Run once after cloning: bash setup.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"

echo "AI Scholar setup..."

# 1. Install custom Claude commands
mkdir -p "$COMMANDS_DIR"
for f in "$REPO_DIR/.claude/commands/"*.md; do
  name=$(basename "$f")
  if [ -f "$COMMANDS_DIR/$name" ]; then
    echo "  ↻ $name (updated)"
  else
    echo "  + $name (new)"
  fi
  cp "$f" "$COMMANDS_DIR/$name"
done

# 2. Enable required plugins in settings.json
SETTINGS="$CLAUDE_DIR/settings.json"
if [ -f "$SETTINGS" ]; then
  echo ""
  echo "Plugins to enable in $SETTINGS:"
  echo "  agent-sdk-dev, claude-md-management, mcp-server-dev, hookify"
  echo "  feature-dev, skill-creator, commit-commands, code-review"
  echo "  pr-review-toolkit, security-guidance, supabase, telegram"
  echo ""
  echo "Add these to enabledPlugins in your Claude settings, or run:"
  echo "  claude /plugin install supabase@claude-plugins-official"
  echo "  claude /plugin install telegram@claude-plugins-official"
fi

# 3. Create required directories
mkdir -p "$HOME/gazzabyte/logs"
echo "  Created ~/gazzabyte/logs"

# 4. Check env vars
echo ""
echo "Required env vars (add to ~/.zshrc or ~/.bashrc):"
[ -z "$SUPABASE_URL" ]              && echo "  ❌ SUPABASE_URL" || echo "  ✅ SUPABASE_URL"
[ -z "$SUPABASE_SERVICE_ROLE_KEY" ] && echo "  ❌ SUPABASE_SERVICE_ROLE_KEY" || echo "  ✅ SUPABASE_SERVICE_ROLE_KEY"
[ -z "$SUPABASE_ANON_KEY" ]         && echo "  ❌ SUPABASE_ANON_KEY" || echo "  ✅ SUPABASE_ANON_KEY"
[ -z "$TELEGRAM_BOT_TOKEN" ]        && echo "  ❌ TELEGRAM_BOT_TOKEN" || echo "  ✅ TELEGRAM_BOT_TOKEN"
[ -z "$TELEGRAM_CHAT_ID" ]          && echo "  ❌ TELEGRAM_CHAT_ID" || echo "  ✅ TELEGRAM_CHAT_ID"
[ -z "$GAZZABYTE_HOME" ]            && echo "  ❌ GAZZABYTE_HOME (default: $HOME)" || echo "  ✅ GAZZABYTE_HOME=$GAZZABYTE_HOME"

# 5. Check bun (required for Telegram MCP)
if command -v bun &>/dev/null; then
  echo ""
  echo "  ✅ bun $(bun --version)"
else
  echo ""
  echo "  ❌ bun not found — install with: curl -fsSL https://bun.sh/install | bash"
fi

echo ""
echo "Setup complete. Available commands in Claude Code:"
echo "  /build-ai-scholar  — Build everything (max parallel agents)"
echo "  /deploy-wingmen    — Deploy Wingmen Nervous System"
echo "  /ingest-ayat       — Ingest Quranic knowledge"
echo "  /brain-sync        — Sync all repo snapshots"
echo "  /morning-brief     — Send Telegram brief"
echo "  /scholar-ask       — Query Al-Bayān"
