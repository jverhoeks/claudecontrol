# Claude Control: Centralized Governance for Claude Code Sessions

## Problem

Running 5-10 concurrent Claude Code sessions leads to a flood of permission prompts across terminals. Running in dangerous/bypass mode is not acceptable. Need a way to govern all sessions centrally, with mobile approval via Telegram when away from desk and normal CLI approval when at desk.

## Solution

A Dockerized Python governance server that intercepts all Claude Code tool calls via HTTP hooks, classifies risk, auto-approves/denies based on regex rules, and routes uncertain actions to Telegram for human approval — with a dual CLI/Telegram approval path.

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│  Claude Session #1  │     │  Claude Session #N   │
│  (HTTP hooks)       │     │  (HTTP hooks)        │
└────────┬────────────┘     └────────┬────────────┘
         │ HTTP POST                 │ HTTP POST
         └──────────┐   ┌───────────┘
                    ▼   ▼
          ┌─────────────────────┐
          │  Governance Server  │
          │  (Python/FastAPI)   │
          │  Docker container   │
          │                     │
          │  Risk Classifier    │
          │  Decision Engine    │
          │  Request Queue      │
          │  Session Registry   │
          │  Whitelist Store    │
          └────────┬────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
   ┌──────────────┐  ┌──────────────┐
   │ Telegram Bot  │  │ Future:      │
   │ (inline btns) │  │ Desktop/Web  │
   └──────────────┘  └──────────────┘
```

## Risk Classification (Three Tiers)

Classification is pattern-based (regex), configured in `rules.yaml`.

### Auto-approve (no human needed)
- Tools: Read, Glob, Grep
- Bash patterns: `ls`, `cat`, `git status`, `git log`, `git diff`, `pwd`, `echo`, `npm test`, `pytest`, `make test`

### Auto-deny (blocked immediately)
- Bash patterns: `rm -rf /`, `git push.*--force.*main`, fork bombs, writes to `/dev/sd`

### Ask-human (routed to Telegram + CLI)
- Everything not matched by the above two tiers
- Timeout: 120s, then deny and queue for retry

Dynamic whitelist/denylist patterns added via Telegram take priority over `rules.yaml`.

## Dual CLI + Telegram Approval Path

Uses two Claude Code hooks working together:

1. **`PreToolUse` hook** — handles auto-approve and auto-deny instantly (10s timeout)
2. **`PermissionRequest` hook** — handles ask-human tier (180s timeout)

### Flow for ask-human actions:

1. `PreToolUse` fires → server classifies as ask-human → returns no decision (passes through)
2. `PermissionRequest` fires → server sends Telegram notification, holds HTTP response open
3. Race between two paths:
   - **Telegram approval** (within timeout) → server returns `allow`/`deny`, CLI prompt never appears
   - **Timeout** (e.g. 5s configurable) → server doesn't respond, Claude Code falls back to normal CLI prompt
4. User can configure preference:
   - `PERMISSION_REQUEST_TIMEOUT=5` → prefers CLI (fast fallback)
   - `PERMISSION_REQUEST_TIMEOUT=120` → prefers Telegram (waits longer)

## Telegram UX

### Approval request message:

```
🔒 Approval Request
━━━━━━━━━━━━━━━━━━
📂 my-project (#3)
🔧 Bash
💻 git push origin feature/auth
⚠️ Risk: MEDIUM

[✅ Approve]  [❌ Deny]
[🔄 Auto-approve similar]  [📋 Show context]
```

### Button behaviors:

| Button | Action |
|--------|--------|
| Approve | Releases HTTP response with `allow` |
| Deny | Releases with `deny`, reason sent to Claude |
| Auto-approve similar | Adds pattern to whitelist, then approves |
| Show context | Sends follow-up with last ~10 transcript lines |

### After decision:

```
✅ APPROVED — git push origin feature/auth
📂 my-project (#3) · by @you · 12s
```

### Timeout → queue:

```
⏰ Timed out — queued for retry
💻 git push origin feature/auth
📂 my-project (#3)

[✅ Approve queued]  [🗑 Dismiss]
```

Claude receives: "Approval timed out. The request has been queued — you can ask the user to retry, or try a different approach."

If "Approve queued" is tapped, the pattern is whitelisted so the next retry auto-approves.

### Multi-session clarity:

Each session gets a friendly name: `{project-dir} #{counter}` (e.g. `my-project #1`, `api-server #2`). Tracked in session registry.

## Server Components

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /hook/pre-tool-use` | Receives PreToolUse events from Claude sessions |
| `POST /hook/permission-request` | Receives PermissionRequest events, holds for Telegram approval |
| `GET /queue` | Lists pending/queued requests (future web UI) |
| `POST /queue/{id}/decide` | Manual approve/deny (future web UI) |
| `GET /health` | Healthcheck |

### Internal modules

- **`main.py`** — FastAPI app, endpoint routing
- **`risk_classifier.py`** — loads `rules.yaml` + whitelist/denylist, classifies requests
- **`decision_engine.py`** — orchestrates ask-human flow, manages pending requests with async waiters
- **`telegram_bot.py`** — long-polls Telegram API, handles inline keyboard callbacks
- **`session_registry.py`** — assigns and tracks friendly session names
- **`whitelist_store.py`** — CRUD for dynamic whitelist/denylist patterns
- **`models.py`** — Pydantic models for hook input/output

## Data Model (SQLite)

### `requests`

| Column | Type | Purpose |
|--------|------|---------|
| id | TEXT (uuid) | Primary key |
| session_id | TEXT | Claude session |
| tool_name | TEXT | Bash, Edit, etc. |
| tool_input | JSON | Full tool parameters |
| risk_tier | TEXT | auto_approve / auto_deny / ask_human |
| decision | TEXT | allow / deny / pending / timeout |
| decided_by | TEXT | system / telegram / cli / whitelist |
| telegram_message_id | INT | For updating message |
| created_at | TIMESTAMP | |
| decided_at | TIMESTAMP | |

### `sessions`

| Column | Type |
|--------|------|
| session_id | TEXT |
| project_path | TEXT |
| friendly_name | TEXT |
| first_seen | TIMESTAMP |
| last_seen | TIMESTAMP |

### `whitelist`

| Column | Type |
|--------|------|
| id | INT |
| tool_name | TEXT |
| pattern | TEXT (regex) |
| created_by | TEXT |
| created_at | TIMESTAMP |

### `denylist`

Same schema as whitelist.

Whitelist/denylist checked before `rules.yaml` — Telegram-added patterns take priority.

## Project Structure

```
claude-control/
├── setup.sh                 # Builds Docker, installs Claude Code hooks
├── docker-compose.yml
├── Dockerfile
├── rules.yaml               # Risk classification rules (live-reloadable)
├── .env.example              # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
├── server/
│   ├── main.py
│   ├── risk_classifier.py
│   ├── decision_engine.py
│   ├── telegram_bot.py
│   ├── session_registry.py
│   ├── whitelist_store.py
│   └── models.py
├── data/                     # SQLite DB (Docker volume)
└── docs/
```

## Configuration

### `.env`
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=987654321
SERVER_PORT=8932
PERMISSION_REQUEST_TIMEOUT=5
LOG_LEVEL=INFO
```

### `docker-compose.yml`
- Single service, port `8932`
- Mounts `./data` for SQLite persistence
- Mounts `./rules.yaml` for live-reload
- `restart: unless-stopped`
- Healthcheck on `/health`

### Claude Code hooks (`~/.claude/settings.json`)
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [{
          "type": "http",
          "url": "http://localhost:8932/hook/pre-tool-use",
          "timeout": 10
        }]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": ".*",
        "hooks": [{
          "type": "http",
          "url": "http://localhost:8932/hook/permission-request",
          "timeout": 180
        }]
      }
    ]
  }
}
```

### `setup.sh` flow
1. Check prerequisites (Docker)
2. Prompt for Telegram bot token + chat ID (with @BotFather instructions)
3. Write `.env`
4. `docker compose up -d --build`
5. Wait for healthcheck
6. Merge hooks into `~/.claude/settings.json` (preserving existing settings)
7. Print success message

## Future Extensibility

- Desktop notification channel (macOS native notifications)
- Web dashboard for queue management and analytics
- Cloud deployment (same Docker image)
- Taskbar/menu bar icon
- Per-project rule overrides
- Analytics: approval rates, most-denied commands, session activity
