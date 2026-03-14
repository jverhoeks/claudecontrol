# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Claude Control — centralized governance server for multi-session Claude Code approval via Telegram and CLI, using HTTP hooks with regex-based risk classification.

## Build & Run

```bash
# First-time setup (builds Docker, configures hooks)
./setup.sh

# View logs
docker compose logs -f

# Restart after code changes
docker compose up -d --build

# Stop
docker compose down
```

## Development

```bash
# Install deps locally for testing (requires Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run a single test file
.venv/bin/python -m pytest tests/test_risk_classifier.py -v

# Run a single test
.venv/bin/python -m pytest tests/test_endpoints.py::test_health -v
```

## Architecture

- `server/main.py` — FastAPI app with `/hook/pre-tool-use` and `/hook/permission-request` endpoints
- `server/risk_classifier.py` — regex rules from `rules.yaml` + dynamic whitelist/denylist from SQLite
- `server/decision_engine.py` — async futures that hold HTTP responses open while waiting for Telegram approval
- `server/telegram_bot.py` — python-telegram-bot with inline keyboard callbacks
- `server/database.py` — SQLite with WAL mode, handles concurrent sessions
- `server/session_registry.py` — assigns friendly names like `my-project #1`
- `server/models.py` — Pydantic models matching Claude Code hook JSON contracts
- `rules.yaml` — risk classification rules, live-reloaded on change

## Key Design Decisions

- PreToolUse hook handles auto-approve/deny instantly; PermissionRequest hook handles ask-human with Telegram wait
- Precedence: denylist > whitelist > rules.yaml auto-deny > rules.yaml auto-approve > ask-human
- Server binds to 127.0.0.1 only (localhost). No auth token needed for local use.
- Late Telegram callbacks (after timeout) save patterns for future auto-approve/deny
