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

**Precedence order:** denylist > whitelist > `rules.yaml` auto-deny > `rules.yaml` auto-approve > ask-human (default). If a pattern appears in both whitelist and denylist, denylist wins (safety-first).

Dynamic whitelist/denylist patterns added via Telegram are checked first, before `rules.yaml` rules.

## Dual CLI + Telegram Approval Path

Uses two Claude Code hooks working together:

1. **`PreToolUse` hook** — handles auto-approve and auto-deny instantly (10s timeout)
2. **`PermissionRequest` hook** — handles ask-human tier (180s timeout)

### Flow for ask-human actions:

1. `PreToolUse` fires → server classifies as ask-human → responds with HTTP 200 and empty `hookSpecificOutput` (no `permissionDecision` field). This means "no opinion" — Claude Code proceeds to its normal permission check.
2. `PermissionRequest` fires → server sends Telegram notification, holds HTTP response open for up to `PERMISSION_REQUEST_TIMEOUT` seconds.
3. Race between two paths:
   - **Telegram approval** (within timeout) → server returns `{"hookSpecificOutput": {"decision": {"behavior": "allow"}}}` or `deny`, CLI prompt never appears
   - **Server-side timeout** → server returns HTTP 408 (no body). Claude Code treats hook timeout as "no opinion" and falls back to showing the normal CLI prompt.
4. **Late Telegram callback:** If the user taps Approve/Deny on Telegram after the server-side timeout has already released the HTTP response, the decision is stored but cannot affect the current request (it already went to CLI). Instead, the pattern is added to the whitelist/denylist for future requests. The Telegram message is updated to show "Handled in CLI — pattern saved for next time."
5. User can configure preference:
   - `PERMISSION_REQUEST_TIMEOUT=5` → prefers CLI (fast fallback to terminal prompt)
   - `PERMISSION_REQUEST_TIMEOUT=120` → prefers Telegram (waits longer before falling back)

## Telegram UX

### Approval request message:

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

### Button behaviors:

| Button | Action |
|--------|--------|
| Approve | Releases HTTP response with `allow` |
| Deny | Releases with `deny`, reason sent to Claude |
| Auto-approve similar | Generates a pattern from the command and adds to whitelist, then approves. Pattern generation: for Bash commands, replaces the last path/argument segment with `.*` (e.g. `git push origin feature/auth` → `^git push origin .*$`). For Edit/Write, replaces filename with `.*` keeping directory (e.g. `/src/foo/bar.py` → `/src/foo/.*`). User sees the generated pattern in a confirmation message and can edit it via a follow-up Telegram message before it's saved. |
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

If "Approve queued" is tapped, the exact command is whitelisted so the next retry auto-approves. Claude will need to re-invoke the same tool call — there is no push mechanism to resume a timed-out request.

### Multi-session clarity:

Each session gets a friendly name: `{project-dir} #{counter}` (e.g. `my-project #1`, `api-server #2`). Tracked in session registry.

## Hook Input/Output Contracts

### PreToolUse — Request body (from Claude Code)

```json
{
  "session_id": "abc123",
  "cwd": "/Users/jj/src/my-project",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push origin main"
  },
  "permission_mode": "default",
  "transcript_path": "/path/to/transcript.jsonl"
}
```

For Edit/Write, `tool_input` contains `{"file_path": "...", "file_contents": "..."}`. For other tools, the input matches their parameter schema.

### PreToolUse — Response body (from server)

**Auto-approve:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
```

**Auto-deny:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked by rule: rm -rf on root path"
  }
}
```

**Ask-human (pass through to PermissionRequest):**
```json
{}
```
HTTP 200 with empty JSON body. No `hookSpecificOutput` means "no opinion" — Claude Code proceeds to its normal permission flow.

### PermissionRequest — Request body (from Claude Code)

Same fields as PreToolUse (session_id, tool_name, tool_input, etc.).

### PermissionRequest — Response body (from server)

**Approved via Telegram:**
```json
{
  "hookSpecificOutput": {
    "decision": {
      "behavior": "allow"
    }
  }
}
```

**Denied via Telegram:**
```json
{
  "hookSpecificOutput": {
    "decision": {
      "behavior": "deny",
      "reason": "Denied by user via Telegram"
    }
  }
}
```

**Timeout (no Telegram response):** Server returns HTTP 408 or lets the connection time out. Claude Code falls back to CLI prompt.

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

## `rules.yaml` Schema

```yaml
# Risk classification rules for Claude Control
# Changes are live-reloaded (server watches file with inotify/polling)

auto_approve:
  # Tools that are always allowed without human approval
  tools:
    - Read
    - Glob
    - Grep
  # Bash commands matching these regexes are auto-approved
  bash_patterns:
    - "^ls\\b"
    - "^cat\\b"
    - "^git (status|log|diff|branch)\\b"
    - "^pwd$"
    - "^echo\\b"
    - "^(npm test|pytest|make test)\\b"

auto_deny:
  # Bash commands matching these regexes are always blocked
  bash_patterns:
    - "rm -rf /"
    - "git push.*--force.*(main|master)"
    - ":\\(\\)\\{\\s*:\\|:&\\s*\\};:"  # fork bomb
    - "> /dev/sd"

# Everything not matched above falls to ask-human tier.
# Invalid YAML on reload: server logs error, keeps previous valid rules.
```

All patterns are Python regexes matched against the `command` field for Bash, or `file_path` for Edit/Write. Tool-level rules (like `tools: [Read]`) match on `tool_name` exactly.

## Security

### Local endpoint authentication
The server binds to `127.0.0.1:8932` (localhost only, not `0.0.0.0`). No authentication token is required since only local processes can reach it. If cloud deployment is added later, bearer token auth will be required.

### Telegram bot security
All incoming Telegram updates are filtered by `TELEGRAM_CHAT_ID`. Callbacks from any other chat are silently dropped. The bot token should be treated as a secret and not committed to git.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Server is down / unreachable | Claude Code hook times out → falls back to normal CLI prompt (hooks are non-blocking on network errors) |
| Telegram API unreachable | Server logs warning, ask-human requests degrade to timeout → CLI fallback |
| SQLite locked (concurrent writes) | Use WAL mode for concurrent reads + writes. SQLite handles this natively for the expected load (5-10 sessions). |
| Invalid `rules.yaml` on reload | Server logs parse error, retains last valid ruleset, sends Telegram warning message |
| Hook returns non-2xx | Claude Code treats as "no opinion" — normal permission flow continues |

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
PERMISSION_REQUEST_TIMEOUT=5    # Seconds server waits for Telegram before releasing to CLI
                                 # Claude Code hook timeout (180s) is the hard ceiling
                                 # Set to 5 for CLI-preferred, 120 for Telegram-preferred
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
