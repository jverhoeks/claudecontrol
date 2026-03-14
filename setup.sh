#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"
SERVER_PORT="${SERVER_PORT:-8932}"

echo "=== Claude Control Setup ==="
echo ""

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is required but not installed."
    echo "Install it from https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running."
    exit 1
fi

# Check for existing .env
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Found existing .env file."
    read -p "Use existing configuration? [Y/n] " use_existing
    if [[ "${use_existing:-Y}" =~ ^[Yy]$ ]]; then
        echo "Using existing .env"
    else
        rm "$SCRIPT_DIR/.env"
    fi
fi

# Collect Telegram config if needed
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "To set up Telegram notifications:"
    echo "  1. Open Telegram and message @BotFather"
    echo "  2. Send /newbot and follow the prompts"
    echo "  3. Copy the bot token"
    echo ""
    read -p "Telegram Bot Token: " bot_token

    echo ""
    echo "To find your Chat ID:"
    echo "  1. Message your new bot in Telegram"
    echo "  2. Visit https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "  3. Look for 'chat':{'id': YOUR_CHAT_ID}"
    echo ""
    read -p "Telegram Chat ID: " chat_id

    cat > "$SCRIPT_DIR/.env" <<EOF
TELEGRAM_BOT_TOKEN=${bot_token}
TELEGRAM_CHAT_ID=${chat_id}
SERVER_PORT=${SERVER_PORT}
PERMISSION_REQUEST_TIMEOUT=5
LOG_LEVEL=INFO
EOF

    echo "Wrote .env"
fi

# Create data directory
mkdir -p "$SCRIPT_DIR/data"

# Build and start Docker container
echo ""
echo "Building and starting governance server..."
cd "$SCRIPT_DIR"
docker compose up -d --build

# Wait for healthcheck
echo "Waiting for server to be healthy..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${SERVER_PORT}/health" > /dev/null 2>&1; then
        echo "Server is healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Server failed to start. Check logs with: docker compose logs"
        exit 1
    fi
    sleep 1
done

# Install Claude Code hooks
echo ""
echo "Installing Claude Code hooks..."
mkdir -p "$(dirname "$SETTINGS_FILE")"

if [ -f "$SETTINGS_FILE" ]; then
    # Merge hooks into existing settings using python
    python3 -c "
import json, sys

with open('$SETTINGS_FILE') as f:
    settings = json.load(f)

hooks = settings.setdefault('hooks', {})

hooks['PreToolUse'] = [
    {
        'matcher': '.*',
        'hooks': [{
            'type': 'http',
            'url': 'http://localhost:${SERVER_PORT}/hook/pre-tool-use',
            'timeout': 10
        }]
    }
]

hooks['PermissionRequest'] = [
    {
        'matcher': '.*',
        'hooks': [{
            'type': 'http',
            'url': 'http://localhost:${SERVER_PORT}/hook/permission-request',
            'timeout': 180
        }]
    }
]

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(settings, f, indent=2)
"
else
    cat > "$SETTINGS_FILE" <<HOOKEOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [{
          "type": "http",
          "url": "http://localhost:${SERVER_PORT}/hook/pre-tool-use",
          "timeout": 10
        }]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": ".*",
        "hooks": [{
          "type": "http",
          "url": "http://localhost:${SERVER_PORT}/hook/permission-request",
          "timeout": 180
        }]
      }
    ]
  }
}
HOOKEOF
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Claude Control is running on http://localhost:${SERVER_PORT}"
echo ""
echo "Commands:"
echo "  docker compose logs -f        # View server logs"
echo "  docker compose restart         # Restart server"
echo "  docker compose down            # Stop server"
echo "  vim rules.yaml                 # Edit risk rules (live-reload)"
echo ""
echo "All Claude Code sessions will now route through governance."
echo "Open Telegram to approve/deny actions when away from desk."
