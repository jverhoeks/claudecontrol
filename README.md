# 🛡️ Claude Control

> Centralized governance for multiple Claude Code sessions — approve actions from Telegram or your terminal.

Running 5-10 Claude Code sessions at once? Tired of permission prompts popping up in every terminal? **Claude Control** gives you a single pane of glass to approve, deny, and audit every action Claude takes — from your phone.

---

## ✨ How It Works

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ 🤖 Claude #1    │   │ 🤖 Claude #2    │   │ 🤖 Claude #N    │
│  my-project     │   │  api-server     │   │  frontend       │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │ HTTP hook           │ HTTP hook           │ HTTP hook
         └─────────────┐      │      ┌──────────────┘
                       ▼      ▼      ▼
              ┌─────────────────────────┐
              │  🏛️ Governance Server   │
              │  Risk Classification    │
              │  ┌───┐ ┌───┐ ┌───────┐ │
              │  │ ✅ │ │ ❌ │ │ 🔔 Ask│ │
              │  │Auto│ │Auto│ │ Human │ │
              │  └───┘ └───┘ └───┬───┘ │
              └──────────────────┼─────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
            📱 Telegram                  💻 Terminal
            (when away)                (when at desk)
```

Every tool call from every Claude session flows through the governance server. Based on regex rules, each action is:

| Tier | What happens | Example |
|------|-------------|---------|
| ✅ **Auto-approve** | Instant, no prompt | `ls`, `git status`, reading files |
| ❌ **Auto-deny** | Blocked immediately | `rm -rf /`, force-push to main |
| 🔔 **Ask human** | Sent to Telegram + CLI | `git push`, `docker run`, file edits |

---

## 📱 Telegram Experience

When Claude tries something that needs your approval:

```
🔒 Approval Request
━━━━━━━━━━━━━━━━━━
📂 my-project (#3)
🔧 Bash
💻 git push origin feature/auth
⚠️ Tier: NEEDS APPROVAL

[✅ Approve]  [❌ Deny]
[🔄 Auto-approve similar]  [📋 Show context]
```

### 🎮 Button Actions

| Button | What it does |
|--------|-------------|
| ✅ **Approve** | Lets the command run |
| ❌ **Deny** | Blocks it, tells Claude why |
| 🔄 **Auto-approve similar** | Whitelists the pattern — never asked again |
| 📋 **Show context** | See what Claude was doing before this command |

### ⏰ Timeout Behavior

Not near your phone? No problem:

- **At your desk** → server times out quickly, CLI prompt appears normally
- **Away** → approve via Telegram within the timeout window
- **Missed it?** → action gets queued, approve later for next time

---

## 🚀 Quick Start

### Prerequisites

- 🐳 Docker
- 📱 Telegram account

### 3 commands, that's it:

```bash
git clone git@github.com:jverhoeks/claudecontrol.git
cd claudecontrol
./setup.sh
```

The interactive setup wizard will:

1. 🤖 Walk you through creating a Telegram bot (via @BotFather)
2. 🔑 Ask you to paste the bot token
3. 📱 Ask you to message the bot, then **auto-detects your Chat ID**
4. 📨 Send a test message to confirm it works
5. 🐳 Build and start the Docker container
6. ⚙️ Install HTTP hooks into `~/.claude/settings.json`
7. ✅ Verify everything is healthy

**That's it.** Every Claude Code session on your machine now routes through governance. Open Telegram and start approving! 🎉

---

## ⚙️ Configuration

### 📋 Risk Rules (`rules.yaml`)

Edit anytime — changes are **live-reloaded** (no restart needed):

```yaml
auto_approve:
  tools:
    - Read
    - Glob
    - Grep
  bash_patterns:
    - "^ls\\b"
    - "^git (status|log|diff|branch)\\b"
    - "^pwd$"
    - "^(npm test|pytest|make test)\\b"

auto_deny:
  bash_patterns:
    - "rm -rf /"
    - "git push.*--force.*(main|master)"
```

### 🎚️ Approval Timeout (`PERMISSION_REQUEST_TIMEOUT` in `.env`)

| Value | Behavior |
|-------|----------|
| `120` (default) | 📱 **Telegram-preferred** — waits 2 min for mobile approval, then falls back to CLI |
| `10` | ⌨️ **CLI-preferred** — quick fallback to terminal prompt |

### 🔄 Dynamic Rules via Telegram

Hit **🔄 Auto-approve similar** on any request to whitelist the pattern on the fly. These dynamic rules take priority over `rules.yaml`:

**Precedence:** `denylist > whitelist > rules.yaml auto-deny > rules.yaml auto-approve > ask-human`

---

## 🛠️ Commands

```bash
./setup.sh                    # 🚀 First-time setup
docker compose logs -f        # 📋 View server logs
docker compose restart        # 🔄 Restart server
docker compose down           # ⏹️ Stop server
vim rules.yaml                # ✏️ Edit risk rules (live-reload)
```

---

## 🏗️ Architecture

```
claudecontrol/
├── 🚀 setup.sh                # Builds Docker, installs hooks
├── 🐳 Dockerfile
├── 🐳 docker-compose.yml
├── 📋 rules.yaml              # Risk rules (live-reloaded)
├── 🔧 server/
│   ├── main.py                # FastAPI endpoints
│   ├── risk_classifier.py     # Regex-based risk classification
│   ├── decision_engine.py     # Async waiters for Telegram responses
│   ├── telegram_bot.py        # Inline keyboard bot
│   ├── database.py            # SQLite (WAL mode)
│   ├── session_registry.py    # Friendly session names
│   ├── models.py              # Hook JSON contracts
│   └── config.py              # Environment config
├── 🧪 tests/                  # 45 tests
└── 📁 data/                   # SQLite DB (persisted)
```

### 🔌 How Hooks Work

Claude Control uses three Claude Code [HTTP hooks](https://docs.anthropic.com/en/docs/claude-code/hooks):

| Hook | Purpose | Timeout |
|------|---------|---------|
| `PreToolUse` | Auto-approve/deny + Telegram approval for ask-human items | 180s |
| `PermissionRequest` | Passthrough (CLI fallback after PreToolUse timeout) | 180s |
| `Stop` | Detect questions and notify via Telegram | 10s |

**Telegram-first approval:** The `PreToolUse` hook handles everything — auto-approve, auto-deny, and Telegram approval. For ask-human items, it holds the HTTP connection open while waiting for your Telegram response. Since PreToolUse fires *before* the CLI permission dialog, Telegram gets first shot. If you don't respond in time, the hook returns no opinion and the CLI prompt appears as fallback.

---

## 🧪 Development

```bash
# Create venv (requires Python 3.12)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run all tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_risk_classifier.py::test_auto_deny_bash_pattern -v
```

---

## 🗺️ Roadmap

- [ ] 🖥️ Desktop notifications (macOS native)
- [ ] 🌐 Web dashboard for queue management
- [ ] ☁️ Cloud deployment option
- [ ] 📊 Analytics: approval rates, most-denied commands
- [ ] 🏷️ Per-project rule overrides
- [ ] 🔲 Menu bar / taskbar icon

---

## 📄 License

MIT

---

<p align="center">
  <b>Stop juggling terminals. Govern all your Claude sessions from one place.</b><br>
  Built with ❤️ for power users running Claude Code at scale.
</p>
