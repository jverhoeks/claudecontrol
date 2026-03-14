import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.database import Database
from server.decision_engine import DecisionEngine
from server.models import HookRequest, PreToolUseResponse, RiskTier
from server.risk_classifier import RiskClassifier
from server.session_registry import SessionRegistry


@pytest.fixture
def client(tmp_path):
    """Create test client with mocked Telegram bot and manual state setup."""
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        'auto_approve:\n'
        '  tools:\n'
        '    - Read\n'
        '    - Glob\n'
        '  bash_patterns:\n'
        '    - "^ls\\\\b"\n'
        '    - "^pwd$"\n'
        'auto_deny:\n'
        '  bash_patterns:\n'
        '    - "rm -rf /"\n'
    )
    db_path = str(tmp_path / "test.db")

    # Create app without lifespan (set up state manually)
    from server.main import create_app

    # Patch environment and TelegramBot to avoid real Telegram calls
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "0",
        "DB_PATH": db_path,
        "RULES_PATH": str(rules),
        "PERMISSION_REQUEST_TIMEOUT": "1",
    }):
        with patch("server.main.TelegramBot") as MockBot:
            mock_bot = MagicMock()
            mock_bot.start = AsyncMock()
            mock_bot.stop = AsyncMock()
            mock_bot.send_approval_request = AsyncMock(return_value=99999)
            mock_bot.update_message_timeout = AsyncMock()
            MockBot.return_value = mock_bot

            app = create_app()

            # Manually set up state (since TestClient doesn't run async lifespan properly for our needs)
            db = Database(db_path)
            asyncio.get_event_loop().run_until_complete(db.init())

            classifier = RiskClassifier(str(rules), db)
            asyncio.get_event_loop().run_until_complete(classifier.load_rules())

            engine = DecisionEngine(timeout_seconds=1)
            registry = SessionRegistry(db)

            app.state.db = db
            app.state.classifier = classifier
            app.state.engine = engine
            app.state.registry = registry
            app.state.bot = mock_bot

            with TestClient(app, raise_server_exceptions=False) as tc:
                yield tc

            asyncio.get_event_loop().run_until_complete(db.close())


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_pre_tool_use_auto_approve(client):
    resp = client.post("/hook/pre-tool-use", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/foo.py"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_pre_tool_use_auto_deny(client):
    resp = client.post("/hook/pre-tool-use", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_ask_human_sends_telegram_and_times_out(client):
    """ask_human items send Telegram notification, then fall back to no opinion on timeout."""
    resp = client.post("/hook/pre-tool-use", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "docker run nginx"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body == {}  # No opinion after timeout — falls back to CLI
    # Verify Telegram was notified
    client.app.state.bot.send_approval_request.assert_called_once()


def test_permission_request_passthrough(client):
    """PermissionRequest is now a passthrough — returns empty (CLI handles it)."""
    resp = client.post("/hook/permission-request", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "docker run nginx"},
    })
    assert resp.status_code == 200
    assert resp.json() == {}


def test_queue_endpoint(client):
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
