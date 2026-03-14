#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"
SERVER_PORT="${SERVER_PORT:-8932}"

echo ""
echo "  🛡️  Claude Control Setup"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 0: Check prerequisites ──────────────────────────────────────────────

if ! command -v docker &> /dev/null; then
    echo "  ❌ Docker is required but not installed."
    echo "     Install it from https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "  ❌ Docker daemon is not running. Please start Docker first."
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "  ❌ curl is required but not installed."
    exit 1
fi

echo "  ✅ Docker is running"
echo ""

# ── Step 1: Telegram bot setup ───────────────────────────────────────────────

if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "  📄 Found existing .env file."
    read -p "     Use existing configuration? [Y/n] " use_existing
    if [[ "${use_existing:-Y}" =~ ^[Yy]$ ]]; then
        echo "     Using existing .env"
        echo ""
    else
        rm "$SCRIPT_DIR/.env"
    fi
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "  📱 Telegram Bot Setup"
    echo "  ─────────────────────"
    echo ""
    echo "  Step 1: Create a bot"
    echo "    1. Open Telegram and search for @BotFather"
    echo "    2. Send /newbot"
    echo "    3. Pick a name (e.g. 'Claude Control')"
    echo "    4. Pick a username (e.g. 'my_claude_control_bot')"
    echo "    5. Copy the token BotFather gives you"
    echo ""
    read -p "  🔑 Paste your bot token: " bot_token

    if [ -z "$bot_token" ]; then
        echo "  ❌ Bot token cannot be empty."
        exit 1
    fi

    # Auto-detect chat ID
    echo ""
    echo "  Step 2: Connect your account"
    echo "    👉 Open Telegram and send any message to your new bot"
    echo ""
    read -p "  Press Enter after you've messaged the bot..." _

    echo "  ⏳ Detecting your Chat ID..."

    chat_id=""
    for i in $(seq 1 10); do
        response=$(curl -sf "https://api.telegram.org/bot${bot_token}/getUpdates" 2>/dev/null || echo "")

        if [ -n "$response" ]; then
            # Extract chat ID using python (available on macOS and most Linux)
            chat_id=$(python3 -c "
import json, sys
try:
    data = json.loads('$response')
    if data.get('result'):
        print(data['result'][-1]['message']['chat']['id'])
except:
    pass
" 2>/dev/null || echo "")
        fi

        if [ -n "$chat_id" ]; then
            break
        fi
        sleep 1
    done

    if [ -z "$chat_id" ]; then
        echo "  ⚠️  Could not auto-detect Chat ID."
        echo "     You can find it manually at:"
        echo "     https://api.telegram.org/bot${bot_token}/getUpdates"
        echo ""
        read -p "  🔢 Enter your Chat ID: " chat_id
    else
        echo "  ✅ Found Chat ID: $chat_id"
    fi

    if [ -z "$chat_id" ]; then
        echo "  ❌ Chat ID cannot be empty."
        exit 1
    fi

    cat > "$SCRIPT_DIR/.env" <<EOF
TELEGRAM_BOT_TOKEN=${bot_token}
TELEGRAM_CHAT_ID=${chat_id}
SERVER_PORT=${SERVER_PORT}
PERMISSION_REQUEST_TIMEOUT=5
LOG_LEVEL=INFO
EOF

    echo "  ✅ Configuration saved to .env"
    echo ""

    # Send a test message
    echo "  📨 Sending test message to Telegram..."
    test_result=$(curl -sf -X POST "https://api.telegram.org/bot${bot_token}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": ${chat_id}, \"text\": \"🛡️ Claude Control connected! You'll receive approval requests here.\"}" 2>/dev/null || echo "")

    if echo "$test_result" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
        echo "  ✅ Test message sent — check Telegram!"
    else
        echo "  ⚠️  Could not send test message. Check your token and chat ID."
        echo "     You can fix this later in .env"
    fi
    echo ""
fi

# ── Step 2: Build and start ──────────────────────────────────────────────────

mkdir -p "$SCRIPT_DIR/data"

echo "  🐳 Building and starting governance server..."
cd "$SCRIPT_DIR"
docker compose up -d --build 2>&1 | sed 's/^/     /'

echo ""
echo "  ⏳ Waiting for server to be healthy..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${SERVER_PORT}/health" > /dev/null 2>&1; then
        echo "  ✅ Server is healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ❌ Server failed to start. Run: docker compose logs"
        exit 1
    fi
    sleep 1
done

# ── Step 3: Install Claude Code hooks ────────────────────────────────────────

echo ""
echo "  ⚙️  Installing Claude Code hooks..."
mkdir -p "$(dirname "$SETTINGS_FILE")"

if [ -f "$SETTINGS_FILE" ]; then
    python3 -c "
import json

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

echo "  ✅ Hooks installed in ~/.claude/settings.json"

# ── Done! ────────────────────────────────────────────────────────────────────

echo ""
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎉 Claude Control is running!"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  🌐 Server:  http://localhost:${SERVER_PORT}"
echo "  📱 Approve: Open Telegram when Claude needs permission"
echo "  ⌨️  CLI:     Or just approve in the terminal as usual"
echo ""
echo "  📋 Useful commands:"
echo "     docker compose logs -f     # View logs"
echo "     docker compose restart     # Restart"
echo "     docker compose down        # Stop"
echo "     vim rules.yaml             # Edit rules (live-reload)"
echo ""
echo "  All Claude Code sessions will now route through governance."
echo ""
