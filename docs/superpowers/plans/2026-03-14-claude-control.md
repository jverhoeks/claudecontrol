# Claude Control Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized Python governance server that intercepts Claude Code tool calls via HTTP hooks, classifies risk via regex rules, and routes uncertain actions to Telegram for human approval — with dual CLI/Telegram approval path.

**Architecture:** FastAPI server in Docker receives PreToolUse and PermissionRequest HTTP hooks from all Claude sessions. Risk classifier (regex-based, from rules.yaml + dynamic whitelist/denylist in SQLite) decides auto-approve, auto-deny, or ask-human. For ask-human, a Telegram bot sends inline-keyboard messages and the server holds the HTTP response until the user decides or timeout triggers CLI fallback.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, python-telegram-bot (async), SQLite (aiosqlite, WAL mode), PyYAML, Pydantic, Docker, docker-compose

**Spec:** `docs/superpowers/specs/2026-03-14-claude-control-governance-design.md`

---

## Chunk 1: Core Server Foundation

### Task 1: Project scaffolding and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `rules.yaml`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
python-telegram-bot==22.1
aiosqlite==0.21.0
pyyaml==6.0.2
pydantic==2.11.3
pydantic-settings==2.9.1
watchfiles==1.0.5
```

- [ ] **Step 2: Create .gitignore**

```
.env
data/*.db
data/*.db-wal
data/*.db-shm
__pycache__/
*.pyc
.venv/
```

- [ ] **Step 3: Create .env.example**

```
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
TELEGRAM_CHAT_ID=your-chat-id
SERVER_PORT=8932
PERMISSION_REQUEST_TIMEOUT=5
LOG_LEVEL=INFO
```

- [ ] **Step 4: Create rules.yaml**

```yaml
auto_approve:
  tools:
    - Read
    - Glob
    - Grep
  bash_patterns:
    - "^ls\\b"
    - "^cat\\b"
    - "^git (status|log|diff|branch)\\b"
    - "^pwd$"
    - "^echo\\b"
    - "^(npm test|pytest|make test)\\b"

auto_deny:
  bash_patterns:
    - "rm -rf /"
    - "git push.*--force.*(main|master)"
    - ":\\(\\)\\{\\s*:\\|:&\\s*\\};:"
    - "> /dev/sd"
```

- [ ] **Step 5: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY rules.yaml .

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8932"]
```

- [ ] **Step 6: Create docker-compose.yml**

```yaml
services:
  governance:
    build: .
    ports:
      - "${SERVER_PORT:-8932}:8932"
    volumes:
      - ./data:/app/data
      - ./rules.yaml:/app/rules.yaml:ro
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8932/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
```

- [ ] **Step 7: Create data directory**

```bash
mkdir -p data
touch data/.gitkeep
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt Dockerfile docker-compose.yml .env.example .gitignore rules.yaml data/.gitkeep
git commit -m "feat: add project scaffolding and dependencies"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `server/__init__.py`
- Create: `server/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Create server/__init__.py**

Empty file.

- [ ] **Step 2: Write failing test for models**

Create `tests/__init__.py` (empty) and `tests/test_models.py`:

```python
from server.models import (
    HookRequest,
    PreToolUseResponse,
    PermissionRequestResponse,
    RiskTier,
)


def test_hook_request_parses_bash_command():
    data = {
        "session_id": "abc123",
        "cwd": "/Users/jj/src/my-project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "permission_mode": "default",
        "transcript_path": "/tmp/transcript.jsonl",
    }
    req = HookRequest(**data)
    assert req.session_id == "abc123"
    assert req.tool_name == "Bash"
    assert req.tool_input == {"command": "git push origin main"}


def test_hook_request_parses_edit_tool():
    data = {
        "session_id": "abc123",
        "cwd": "/Users/jj/src/my-project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/src/foo.py", "file_contents": "x = 1"},
        "permission_mode": "default",
    }
    req = HookRequest(**data)
    assert req.tool_name == "Edit"


def test_hook_request_allows_missing_optional_fields():
    data = {
        "session_id": "abc123",
        "cwd": "/tmp",
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/foo.py"},
    }
    req = HookRequest(**data)
    assert req.permission_mode is None
    assert req.transcript_path is None


def test_pre_tool_use_response_allow():
    resp = PreToolUseResponse.allow()
    d = resp.model_dump(exclude_none=True)
    assert d["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_pre_tool_use_response_deny():
    resp = PreToolUseResponse.deny("dangerous command")
    d = resp.model_dump(exclude_none=True)
    assert d["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert d["hookSpecificOutput"]["permissionDecisionReason"] == "dangerous command"


def test_pre_tool_use_response_no_opinion():
    resp = PreToolUseResponse.no_opinion()
    d = resp.model_dump(exclude_none=True)
    assert d == {}


def test_permission_request_response_allow():
    resp = PermissionRequestResponse.allow()
    d = resp.model_dump(exclude_none=True)
    assert d["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_permission_request_response_deny():
    resp = PermissionRequestResponse.deny("user said no")
    d = resp.model_dump(exclude_none=True)
    assert d["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert d["hookSpecificOutput"]["decision"]["reason"] == "user said no"


def test_risk_tier_enum():
    assert RiskTier.AUTO_APPROVE == "auto_approve"
    assert RiskTier.AUTO_DENY == "auto_deny"
    assert RiskTier.ASK_HUMAN == "ask_human"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: ImportError — `server.models` does not exist yet.

- [ ] **Step 4: Implement models**

Create `server/models.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class RiskTier(str, Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    ASK_HUMAN = "ask_human"


class HookRequest(BaseModel):
    session_id: str
    cwd: str
    hook_event_name: str
    tool_name: str
    tool_input: dict[str, Any]
    permission_mode: str | None = None
    transcript_path: str | None = None


class _PreToolUseOutput(BaseModel):
    hookEventName: str = "PreToolUse"
    permissionDecision: str
    permissionDecisionReason: str | None = None


class _PreToolUseHookSpecific(BaseModel):
    hookSpecificOutput: _PreToolUseOutput


class PreToolUseResponse(BaseModel):
    hookSpecificOutput: _PreToolUseOutput | None = None

    @classmethod
    def allow(cls) -> PreToolUseResponse:
        return cls(
            hookSpecificOutput=_PreToolUseOutput(permissionDecision="allow")
        )

    @classmethod
    def deny(cls, reason: str) -> PreToolUseResponse:
        return cls(
            hookSpecificOutput=_PreToolUseOutput(
                permissionDecision="deny",
                permissionDecisionReason=reason,
            )
        )

    @classmethod
    def no_opinion(cls) -> PreToolUseResponse:
        return cls(hookSpecificOutput=None)


class _PermissionDecision(BaseModel):
    behavior: str
    reason: str | None = None


class _PermissionRequestOutput(BaseModel):
    decision: _PermissionDecision


class PermissionRequestResponse(BaseModel):
    hookSpecificOutput: _PermissionRequestOutput | None = None

    @classmethod
    def allow(cls) -> PermissionRequestResponse:
        return cls(
            hookSpecificOutput=_PermissionRequestOutput(
                decision=_PermissionDecision(behavior="allow")
            )
        )

    @classmethod
    def deny(cls, reason: str) -> PermissionRequestResponse:
        return cls(
            hookSpecificOutput=_PermissionRequestOutput(
                decision=_PermissionDecision(behavior="deny", reason=reason)
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/__init__.py server/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: add Pydantic models for hook request/response contracts"
```

---

### Task 3: Database layer

**Files:**
- Create: `server/database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write failing tests for database**

Create `tests/test_database.py`:

```python
import asyncio
import pytest
from server.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    asyncio.get_event_loop().run_until_complete(database.init())
    yield database
    asyncio.get_event_loop().run_until_complete(database.close())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_create_request(db):
    req_id = _run(db.create_request(
        session_id="s1",
        tool_name="Bash",
        tool_input={"command": "ls"},
        risk_tier="auto_approve",
    ))
    assert req_id is not None
    req = _run(db.get_request(req_id))
    assert req["session_id"] == "s1"
    assert req["tool_name"] == "Bash"
    assert req["decision"] == "pending"


def test_update_decision(db):
    req_id = _run(db.create_request(
        session_id="s1",
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
        risk_tier="auto_deny",
    ))
    _run(db.update_decision(req_id, decision="deny", decided_by="system"))
    req = _run(db.get_request(req_id))
    assert req["decision"] == "deny"
    assert req["decided_by"] == "system"


def test_upsert_session(db):
    _run(db.upsert_session("s1", "/home/user/project"))
    session = _run(db.get_session("s1"))
    assert session["project_path"] == "/home/user/project"
    assert session["friendly_name"] == "project #1"

    _run(db.upsert_session("s2", "/home/user/project"))
    session2 = _run(db.get_session("s2"))
    assert session2["friendly_name"] == "project #2"

    _run(db.upsert_session("s3", "/home/user/other"))
    session3 = _run(db.get_session("s3"))
    assert session3["friendly_name"] == "other #1"


def test_whitelist_crud(db):
    wl_id = _run(db.add_whitelist_pattern("Bash", "^git push origin .*$", "user"))
    patterns = _run(db.get_whitelist_patterns())
    assert len(patterns) == 1
    assert patterns[0]["pattern"] == "^git push origin .*$"

    _run(db.remove_whitelist_pattern(wl_id))
    patterns = _run(db.get_whitelist_patterns())
    assert len(patterns) == 0


def test_denylist_crud(db):
    dl_id = _run(db.add_denylist_pattern("Bash", "^rm -rf", "user"))
    patterns = _run(db.get_denylist_patterns())
    assert len(patterns) == 1

    _run(db.remove_denylist_pattern(dl_id))
    patterns = _run(db.get_denylist_patterns())
    assert len(patterns) == 0


def test_get_pending_requests(db):
    id1 = _run(db.create_request("s1", "Bash", {"command": "ls"}, "ask_human"))
    id2 = _run(db.create_request("s1", "Bash", {"command": "rm x"}, "ask_human"))
    _run(db.update_decision(id1, "allow", "telegram"))

    pending = _run(db.get_pending_requests())
    assert len(pending) == 1
    assert pending[0]["id"] == id2


def test_set_telegram_message_id(db):
    req_id = _run(db.create_request("s1", "Bash", {"command": "ls"}, "ask_human"))
    _run(db.set_telegram_message_id(req_id, 12345))
    req = _run(db.get_request(req_id))
    assert req["telegram_message_id"] == 12345


def test_get_request_by_telegram_message_id(db):
    req_id = _run(db.create_request("s1", "Bash", {"command": "ls"}, "ask_human"))
    _run(db.set_telegram_message_id(req_id, 99999))
    req = _run(db.get_request_by_telegram_message_id(99999))
    assert req["id"] == req_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement database layer**

Create `server/database.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite


class Database:
    def __init__(self, db_path: str = "data/governance.db"):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_input TEXT NOT NULL,
                risk_tier TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'pending',
                decided_by TEXT,
                telegram_message_id INTEGER,
                created_at TEXT NOT NULL,
                decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                project_path TEXT NOT NULL,
                friendly_name TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                pattern TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS denylist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                pattern TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

    async def create_request(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        risk_tier: str,
    ) -> str:
        req_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO requests (id, session_id, tool_name, tool_input, risk_tier, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (req_id, session_id, tool_name, json.dumps(tool_input), risk_tier, now),
        )
        await self._db.commit()
        return req_id

    async def get_request(self, req_id: str) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM requests WHERE id = ?", (req_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tool_input"] = json.loads(d["tool_input"])
        return d

    async def get_request_by_telegram_message_id(self, msg_id: int) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM requests WHERE telegram_message_id = ?", (msg_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tool_input"] = json.loads(d["tool_input"])
        return d

    async def update_decision(self, req_id: str, decision: str, decided_by: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE requests SET decision = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (decision, decided_by, now, req_id),
        )
        await self._db.commit()

    async def set_telegram_message_id(self, req_id: str, msg_id: int) -> None:
        await self._db.execute(
            "UPDATE requests SET telegram_message_id = ? WHERE id = ?",
            (msg_id, req_id),
        )
        await self._db.commit()

    async def get_pending_requests(self) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM requests WHERE decision = 'pending' ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tool_input"] = json.loads(d["tool_input"])
            result.append(d)
        return result

    async def upsert_session(self, session_id: str, project_path: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        existing = await cursor.fetchone()
        if existing:
            await self._db.execute(
                "UPDATE sessions SET last_seen = ? WHERE session_id = ?",
                (now, session_id),
            )
            await self._db.commit()
            return dict(existing)["friendly_name"]

        # Generate friendly name: dirname #counter
        dir_name = project_path.rstrip("/").split("/")[-1] if "/" in project_path else project_path
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE project_path = ?",
            (project_path,),
        )
        row = await cursor.fetchone()
        counter = dict(row)["cnt"] + 1
        friendly_name = f"{dir_name} #{counter}"

        await self._db.execute(
            "INSERT INTO sessions (session_id, project_path, friendly_name, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
            (session_id, project_path, friendly_name, now, now),
        )
        await self._db.commit()
        return friendly_name

    async def get_session(self, session_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def add_whitelist_pattern(self, tool_name: str, pattern: str, created_by: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO whitelist (tool_name, pattern, created_by, created_at) VALUES (?, ?, ?, ?)",
            (tool_name, pattern, created_by, now),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_whitelist_patterns(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM whitelist")
        return [dict(row) for row in await cursor.fetchall()]

    async def remove_whitelist_pattern(self, pattern_id: int) -> None:
        await self._db.execute("DELETE FROM whitelist WHERE id = ?", (pattern_id,))
        await self._db.commit()

    async def add_denylist_pattern(self, tool_name: str, pattern: str, created_by: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO denylist (tool_name, pattern, created_by, created_at) VALUES (?, ?, ?, ?)",
            (tool_name, pattern, created_by, now),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_denylist_patterns(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM denylist")
        return [dict(row) for row in await cursor.fetchall()]

    async def remove_denylist_pattern(self, pattern_id: int) -> None:
        await self._db.execute("DELETE FROM denylist WHERE id = ?", (pattern_id,))
        await self._db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database.py tests/test_database.py
git commit -m "feat: add SQLite database layer with WAL mode"
```

---

### Task 4: Risk classifier

**Files:**
- Create: `server/risk_classifier.py`
- Create: `tests/test_risk_classifier.py`

- [ ] **Step 1: Write failing tests for risk classifier**

Create `tests/test_risk_classifier.py`:

```python
import asyncio
import pytest
from server.risk_classifier import RiskClassifier
from server.database import Database
from server.models import RiskTier


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    asyncio.get_event_loop().run_until_complete(database.init())
    yield database
    asyncio.get_event_loop().run_until_complete(database.close())


@pytest.fixture
def rules_file(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
auto_approve:
  tools:
    - Read
    - Glob
    - Grep
  bash_patterns:
    - "^ls\\\\b"
    - "^git (status|log|diff|branch)\\\\b"
    - "^pwd$"

auto_deny:
  bash_patterns:
    - "rm -rf /"
    - "git push.*--force.*(main|master)"
""")
    return str(rules)


@pytest.fixture
def classifier(rules_file, db):
    c = RiskClassifier(rules_file, db)
    asyncio.get_event_loop().run_until_complete(c.load_rules())
    return c


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_auto_approve_by_tool_name(classifier):
    tier, reason = _run(classifier.classify("Read", {"file_path": "/foo.py"}))
    assert tier == RiskTier.AUTO_APPROVE


def test_auto_approve_bash_pattern(classifier):
    tier, reason = _run(classifier.classify("Bash", {"command": "ls -la"}))
    assert tier == RiskTier.AUTO_APPROVE


def test_auto_deny_bash_pattern(classifier):
    tier, reason = _run(classifier.classify("Bash", {"command": "rm -rf /"}))
    assert tier == RiskTier.AUTO_DENY
    assert "rm -rf" in reason


def test_auto_deny_force_push(classifier):
    tier, reason = _run(classifier.classify("Bash", {"command": "git push --force origin main"}))
    assert tier == RiskTier.AUTO_DENY


def test_ask_human_unknown_bash(classifier):
    tier, reason = _run(classifier.classify("Bash", {"command": "docker run nginx"}))
    assert tier == RiskTier.ASK_HUMAN


def test_ask_human_unknown_tool(classifier):
    tier, reason = _run(classifier.classify("WebFetch", {"url": "http://example.com"}))
    assert tier == RiskTier.ASK_HUMAN


def test_denylist_overrides_whitelist(classifier, db):
    _run(db.add_whitelist_pattern("Bash", "^docker run", "user"))
    _run(db.add_denylist_pattern("Bash", "^docker run", "user"))
    tier, reason = _run(classifier.classify("Bash", {"command": "docker run nginx"}))
    assert tier == RiskTier.AUTO_DENY


def test_whitelist_overrides_rules(classifier, db):
    _run(db.add_whitelist_pattern("Bash", "^docker run", "user"))
    tier, reason = _run(classifier.classify("Bash", {"command": "docker run nginx"}))
    assert tier == RiskTier.AUTO_APPROVE


def test_denylist_overrides_auto_approve_rule(classifier, db):
    _run(db.add_denylist_pattern("Bash", "^ls\\b", "user"))
    tier, reason = _run(classifier.classify("Bash", {"command": "ls -la"}))
    assert tier == RiskTier.AUTO_DENY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk_classifier.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement risk classifier**

Create `server/risk_classifier.py`:

```python
from __future__ import annotations

import logging
import re

import yaml

from server.database import Database
from server.models import RiskTier

logger = logging.getLogger(__name__)


class RiskClassifier:
    def __init__(self, rules_path: str, db: Database):
        self._rules_path = rules_path
        self._db = db
        self._auto_approve_tools: list[str] = []
        self._auto_approve_bash: list[re.Pattern] = []
        self._auto_deny_bash: list[tuple[re.Pattern, str]] = []

    async def load_rules(self) -> None:
        try:
            with open(self._rules_path) as f:
                rules = yaml.safe_load(f)

            self._auto_approve_tools = rules.get("auto_approve", {}).get("tools", [])
            self._auto_approve_bash = [
                re.compile(p)
                for p in rules.get("auto_approve", {}).get("bash_patterns", [])
            ]
            self._auto_deny_bash = [
                (re.compile(p), p)
                for p in rules.get("auto_deny", {}).get("bash_patterns", [])
            ]
            logger.info(
                "Loaded rules: %d approve tools, %d approve patterns, %d deny patterns",
                len(self._auto_approve_tools),
                len(self._auto_approve_bash),
                len(self._auto_deny_bash),
            )
        except Exception:
            logger.exception("Failed to load rules from %s — keeping previous rules", self._rules_path)

    async def classify(self, tool_name: str, tool_input: dict) -> tuple[RiskTier, str]:
        # Extract the relevant string to match against
        match_str = self._get_match_string(tool_name, tool_input)

        # 1. Check denylist (highest priority)
        for pattern in await self._db.get_denylist_patterns():
            if self._matches(pattern, tool_name, match_str):
                return RiskTier.AUTO_DENY, f"Blocked by denylist: {pattern['pattern']}"

        # 2. Check whitelist
        for pattern in await self._db.get_whitelist_patterns():
            if self._matches(pattern, tool_name, match_str):
                return RiskTier.AUTO_APPROVE, f"Allowed by whitelist: {pattern['pattern']}"

        # 3. Check rules.yaml auto-deny
        if tool_name == "Bash" and match_str:
            for compiled, raw in self._auto_deny_bash:
                if compiled.search(match_str):
                    return RiskTier.AUTO_DENY, f"Blocked by rule: {raw}"

        # 4. Check rules.yaml auto-approve
        if tool_name in self._auto_approve_tools:
            return RiskTier.AUTO_APPROVE, f"Tool {tool_name} is auto-approved"

        if tool_name == "Bash" and match_str:
            for compiled in self._auto_approve_bash:
                if compiled.search(match_str):
                    return RiskTier.AUTO_APPROVE, "Matched auto-approve pattern"

        # 5. Default: ask-human
        return RiskTier.ASK_HUMAN, ""

    def _get_match_string(self, tool_name: str, tool_input: dict) -> str | None:
        if tool_name == "Bash":
            return tool_input.get("command")
        if tool_name in ("Edit", "Write"):
            return tool_input.get("file_path")
        return None

    def _matches(self, db_pattern: dict, tool_name: str, match_str: str | None) -> bool:
        if db_pattern["tool_name"] != tool_name:
            return False
        if match_str is None:
            return False
        try:
            return bool(re.search(db_pattern["pattern"], match_str))
        except re.error:
            logger.warning("Invalid regex in DB pattern: %s", db_pattern["pattern"])
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_classifier.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/risk_classifier.py tests/test_risk_classifier.py
git commit -m "feat: add regex-based risk classifier with precedence chain"
```

---

## Chunk 2: Decision Engine & Telegram Bot

### Task 5: Decision engine (async waiter for Telegram responses)

**Files:**
- Create: `server/decision_engine.py`
- Create: `tests/test_decision_engine.py`

- [ ] **Step 1: Write failing tests for decision engine**

Create `tests/test_decision_engine.py`:

```python
import asyncio
import pytest
from server.decision_engine import DecisionEngine


@pytest.fixture
def engine():
    return DecisionEngine(timeout_seconds=1)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_resolve_before_timeout(engine):
    req_id = "test-123"

    async def resolve_after_delay():
        await asyncio.sleep(0.1)
        engine.resolve(req_id, "allow", "telegram")

    async def run():
        task = asyncio.create_task(resolve_after_delay())
        decision, decided_by = await engine.wait_for_decision(req_id)
        await task
        return decision, decided_by

    decision, decided_by = _run(run())
    assert decision == "allow"
    assert decided_by == "telegram"


def test_timeout_returns_none(engine):
    decision, decided_by = _run(engine.wait_for_decision("test-456"))
    assert decision is None
    assert decided_by is None


def test_resolve_after_timeout_is_late(engine):
    req_id = "test-789"

    async def run():
        decision, decided_by = await engine.wait_for_decision(req_id)
        # After timeout, resolve should report as late
        is_late = engine.resolve(req_id, "allow", "telegram")
        return decision, decided_by, is_late

    decision, decided_by, is_late = _run(run())
    assert decision is None  # timed out
    assert is_late is True


def test_multiple_concurrent_waiters(engine):
    async def run():
        async def wait_and_resolve(req_id, delay):
            async def resolver():
                await asyncio.sleep(delay)
                engine.resolve(req_id, "allow", "telegram")

            task = asyncio.create_task(resolver())
            result = await engine.wait_for_decision(req_id)
            await task
            return result

        r1, r2 = await asyncio.gather(
            wait_and_resolve("a", 0.1),
            wait_and_resolve("b", 0.2),
        )
        return r1, r2

    r1, r2 = _run(run())
    assert r1 == ("allow", "telegram")
    assert r2 == ("allow", "telegram")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_decision_engine.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement decision engine**

Create `server/decision_engine.py`:

```python
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(self, timeout_seconds: float = 5.0):
        self._timeout = timeout_seconds
        self._waiters: dict[str, asyncio.Future] = {}

    async def wait_for_decision(self, request_id: str) -> tuple[str | None, str | None]:
        future: asyncio.Future[tuple[str, str]] = asyncio.get_event_loop().create_future()
        self._waiters[request_id] = future

        try:
            decision, decided_by = await asyncio.wait_for(future, timeout=self._timeout)
            return decision, decided_by
        except asyncio.TimeoutError:
            logger.info("Timeout waiting for decision on request %s", request_id)
            return None, None
        finally:
            self._waiters.pop(request_id, None)

    def resolve(self, request_id: str, decision: str, decided_by: str) -> bool:
        """Resolve a pending decision. Returns True if the request had already timed out (late)."""
        future = self._waiters.get(request_id)
        if future is None:
            return True  # late — waiter already gone
        if not future.done():
            future.set_result((decision, decided_by))
        return False

    def has_pending(self, request_id: str) -> bool:
        return request_id in self._waiters
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_decision_engine.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/decision_engine.py tests/test_decision_engine.py
git commit -m "feat: add async decision engine with timeout and late-resolve detection"
```

---

### Task 6: Session registry

**Files:**
- Create: `server/session_registry.py`
- Create: `tests/test_session_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_session_registry.py`:

```python
import asyncio
import pytest
from server.session_registry import SessionRegistry
from server.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    asyncio.get_event_loop().run_until_complete(database.init())
    yield database
    asyncio.get_event_loop().run_until_complete(database.close())


@pytest.fixture
def registry(db):
    return SessionRegistry(db)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_register_new_session(registry):
    name = _run(registry.get_friendly_name("s1", "/home/user/my-project"))
    assert name == "my-project #1"


def test_same_session_returns_same_name(registry):
    name1 = _run(registry.get_friendly_name("s1", "/home/user/my-project"))
    name2 = _run(registry.get_friendly_name("s1", "/home/user/my-project"))
    assert name1 == name2


def test_different_session_same_project_increments(registry):
    _run(registry.get_friendly_name("s1", "/home/user/my-project"))
    name2 = _run(registry.get_friendly_name("s2", "/home/user/my-project"))
    assert name2 == "my-project #2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement session registry**

Create `server/session_registry.py`:

```python
from __future__ import annotations

from server.database import Database


class SessionRegistry:
    def __init__(self, db: Database):
        self._db = db

    async def get_friendly_name(self, session_id: str, project_path: str) -> str:
        return await self._db.upsert_session(session_id, project_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_session_registry.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/session_registry.py tests/test_session_registry.py
git commit -m "feat: add session registry for friendly session names"
```

---

### Task 7: Telegram bot

**Files:**
- Create: `server/telegram_bot.py`
- Create: `tests/test_telegram_bot.py`

- [ ] **Step 1: Write failing tests for pattern generation and message formatting**

Create `tests/test_telegram_bot.py`:

```python
from server.telegram_bot import generate_similar_pattern, format_approval_message


def test_generate_pattern_bash_simple():
    pattern = generate_similar_pattern("Bash", {"command": "git push origin feature/auth"})
    assert pattern == "^git push origin .*$"


def test_generate_pattern_bash_single_word():
    pattern = generate_similar_pattern("Bash", {"command": "docker"})
    assert pattern == "^docker$"


def test_generate_pattern_edit():
    pattern = generate_similar_pattern("Edit", {"file_path": "/src/foo/bar.py"})
    assert pattern == "^/src/foo/.*$"


def test_generate_pattern_write():
    pattern = generate_similar_pattern("Write", {"file_path": "/src/foo/bar.py"})
    assert pattern == "^/src/foo/.*$"


def test_generate_pattern_unknown_tool():
    pattern = generate_similar_pattern("WebFetch", {"url": "http://example.com"})
    assert pattern is None


def test_format_approval_message():
    msg = format_approval_message(
        friendly_name="my-project (#3)",
        tool_name="Bash",
        tool_input={"command": "git push origin feature/auth"},
        request_id="abc-123",
    )
    assert "my-project (#3)" in msg
    assert "Bash" in msg
    assert "git push origin feature/auth" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement telegram bot**

Create `server/telegram_bot.py`:

```python
from __future__ import annotations

import json
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from server.decision_engine import DecisionEngine
from server.database import Database

logger = logging.getLogger(__name__)


def generate_similar_pattern(tool_name: str, tool_input: dict) -> str | None:
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        parts = command.split()
        if len(parts) <= 1:
            return f"^{command}$"
        return "^" + " ".join(parts[:-1]) + " .*$"
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        last_slash = file_path.rfind("/")
        if last_slash >= 0:
            return "^" + file_path[: last_slash + 1] + ".*$"
        return None
    return None


def format_approval_message(
    friendly_name: str,
    tool_name: str,
    tool_input: dict,
    request_id: str,
) -> str:
    if tool_name == "Bash":
        display = tool_input.get("command", str(tool_input))
    elif tool_name in ("Edit", "Write"):
        display = tool_input.get("file_path", str(tool_input))
    else:
        display = json.dumps(tool_input, indent=2)[:200]

    return (
        f"\U0001f512 Approval Request\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c2 {friendly_name}\n"
        f"\U0001f527 {tool_name}\n"
        f"\U0001f4bb {display}\n"
        f"\u26a0\ufe0f Tier: NEEDS APPROVAL"
    )


def build_approval_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\u2705 Approve", callback_data=f"approve:{request_id}"),
                InlineKeyboardButton("\u274c Deny", callback_data=f"deny:{request_id}"),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f504 Auto-approve similar",
                    callback_data=f"whitelist:{request_id}",
                ),
                InlineKeyboardButton(
                    "\U0001f4cb Show context",
                    callback_data=f"context:{request_id}",
                ),
            ],
        ]
    )


def build_timeout_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\u2705 Approve queued", callback_data=f"approve_queued:{request_id}"),
                InlineKeyboardButton("\U0001f5d1 Dismiss", callback_data=f"dismiss:{request_id}"),
            ],
        ]
    )


class TelegramBot:
    def __init__(
        self,
        token: str,
        chat_id: int,
        decision_engine: DecisionEngine,
        db: Database,
    ):
        self._token = token
        self._chat_id = chat_id
        self._engine = decision_engine
        self._db = db
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_approval_request(
        self,
        request_id: str,
        friendly_name: str,
        tool_name: str,
        tool_input: dict,
    ) -> int:
        text = format_approval_message(friendly_name, tool_name, tool_input, request_id)
        keyboard = build_approval_keyboard(request_id)
        msg = await self._app.bot.send_message(
            chat_id=self._chat_id,
            text=text,
            reply_markup=keyboard,
        )
        return msg.message_id

    async def update_message_decided(
        self, message_id: int, tool_input: dict, tool_name: str, friendly_name: str, decision: str, elapsed: float
    ) -> None:
        icon = "\u2705" if decision == "allow" else "\u274c"
        verb = "APPROVED" if decision == "allow" else "DENIED"
        if tool_name == "Bash":
            display = tool_input.get("command", "")
        else:
            display = tool_input.get("file_path", str(tool_input))
        text = f"{icon} {verb} \u2014 {display}\n\U0001f4c2 {friendly_name} \u00b7 {elapsed:.0f}s"
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
            )
        except Exception:
            logger.exception("Failed to update Telegram message %d", message_id)

    async def update_message_timeout(
        self, message_id: int, tool_input: dict, tool_name: str, friendly_name: str, request_id: str
    ) -> None:
        if tool_name == "Bash":
            display = tool_input.get("command", "")
        else:
            display = tool_input.get("file_path", str(tool_input))
        text = (
            f"\u23f0 Timed out \u2014 queued for retry\n"
            f"\U0001f4bb {display}\n"
            f"\U0001f4c2 {friendly_name}"
        )
        keyboard = build_timeout_keyboard(request_id)
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to update Telegram message %d for timeout", message_id)

    async def send_context(self, transcript_path: str | None) -> None:
        if not transcript_path:
            await self._app.bot.send_message(
                chat_id=self._chat_id, text="No transcript available."
            )
            return
        try:
            with open(transcript_path) as f:
                lines = f.readlines()
            context = "".join(lines[-10:])
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=f"Last 10 transcript lines:\n```\n{context[:3000]}\n```",
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Failed to read transcript at %s", transcript_path)
            await self._app.bot.send_message(
                chat_id=self._chat_id, text="Failed to read transcript."
            )

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.message.chat_id != self._chat_id:
            return  # Security: ignore callbacks from other chats
        await query.answer()

        data = query.data
        action, request_id = data.split(":", 1)

        req = await self._db.get_request(request_id)
        if req is None:
            return

        if action == "approve":
            is_late = self._engine.resolve(request_id, "allow", "telegram")
            await self._db.update_decision(request_id, "allow", "telegram")
            if is_late:
                # Auto-whitelist for next time
                pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
                if pattern:
                    await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram-late")
                await query.edit_message_text(
                    "Handled in CLI \u2014 pattern saved for next time."
                )
            else:
                await query.edit_message_text(
                    f"\u2705 APPROVED \u2014 {req['tool_input'].get('command', '')}"
                )

        elif action == "deny":
            is_late = self._engine.resolve(request_id, "deny", "telegram")
            await self._db.update_decision(request_id, "deny", "telegram")
            if is_late:
                await self._db.add_denylist_pattern(
                    req["tool_name"],
                    f"^{req['tool_input'].get('command', '')}$",
                    "telegram-late",
                )
                await query.edit_message_text(
                    "Handled in CLI \u2014 deny pattern saved for next time."
                )
            else:
                await query.edit_message_text(
                    f"\u274c DENIED \u2014 {req['tool_input'].get('command', '')}"
                )

        elif action == "whitelist":
            pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
            if pattern:
                await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram")
            self._engine.resolve(request_id, "allow", "telegram")
            await self._db.update_decision(request_id, "allow", "telegram")
            await query.edit_message_text(
                f"\u2705 APPROVED + whitelisted: {pattern}"
            )

        elif action == "approve_queued":
            pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
            if pattern:
                await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram-queued")
            await self._db.update_decision(request_id, "allow", "telegram-queued")
            await query.edit_message_text(
                f"\u2705 Queued approval \u2014 whitelisted: {pattern}"
            )

        elif action == "context":
            transcript_path = None  # Would need to be stored in request
            await self.send_context(transcript_path)

        elif action == "dismiss":
            await self._db.update_decision(request_id, "dismissed", "telegram")
            await query.edit_message_text("\U0001f5d1 Dismissed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat: add Telegram bot with approval buttons and pattern generation"
```

---

## Chunk 3: FastAPI Endpoints & Integration

### Task 8: Configuration module

**Files:**
- Create: `server/config.py`

- [ ] **Step 1: Create config module**

Create `server/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0
    server_port: int = 8932
    permission_request_timeout: float = 5.0
    log_level: str = "INFO"
    db_path: str = "data/governance.db"
    rules_path: str = "rules.yaml"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 2: Commit**

```bash
git add server/config.py
git commit -m "feat: add settings config with pydantic-settings"
```

---

### Task 9: FastAPI app and endpoints

**Files:**
- Create: `server/main.py`
- Create: `tests/test_endpoints.py`

- [ ] **Step 1: Write failing tests for endpoints**

Create `tests/test_endpoints.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create test client with mocked Telegram bot."""
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
auto_approve:
  tools:
    - Read
    - Glob
  bash_patterns:
    - "^ls\\\\b"
    - "^pwd$"
auto_deny:
  bash_patterns:
    - "rm -rf /"
""")
    db_path = str(tmp_path / "test.db")

    with patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "fake-token",
        "TELEGRAM_CHAT_ID": "12345",
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

            from server.main import create_app
            app = create_app()
            # Initialize DB synchronously for tests
            from server.database import Database
            db = Database(db_path)
            asyncio.get_event_loop().run_until_complete(db.init())
            app.state.db = db

            from server.risk_classifier import RiskClassifier
            classifier = RiskClassifier(str(rules), db)
            asyncio.get_event_loop().run_until_complete(classifier.load_rules())
            app.state.classifier = classifier

            from server.decision_engine import DecisionEngine
            app.state.engine = DecisionEngine(timeout_seconds=1)

            from server.session_registry import SessionRegistry
            app.state.registry = SessionRegistry(db)

            app.state.bot = mock_bot

            yield TestClient(app)

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


def test_pre_tool_use_ask_human_returns_empty(client):
    resp = client.post("/hook/pre-tool-use", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "docker run nginx"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body == {}


def test_permission_request_timeout_returns_408(client):
    resp = client.post("/hook/permission-request", json={
        "session_id": "s1",
        "cwd": "/tmp/project",
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "docker run nginx"},
    })
    # Should timeout (1s) and return 408
    assert resp.status_code == 408


def test_queue_endpoint(client):
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endpoints.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement FastAPI app**

Create `server/main.py`:

```python
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from server.config import Settings
from server.database import Database
from server.decision_engine import DecisionEngine
from server.models import HookRequest, PreToolUseResponse, PermissionRequestResponse, RiskTier
from server.risk_classifier import RiskClassifier
from server.session_registry import SessionRegistry
from server.telegram_bot import TelegramBot


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logging.basicConfig(level=getattr(logging, settings.log_level))

        db = Database(settings.db_path)
        await db.init()
        app.state.db = db

        classifier = RiskClassifier(settings.rules_path, db)
        await classifier.load_rules()
        app.state.classifier = classifier

        engine = DecisionEngine(timeout_seconds=settings.permission_request_timeout)
        app.state.engine = engine

        registry = SessionRegistry(db)
        app.state.registry = registry

        bot = TelegramBot(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            decision_engine=engine,
            db=db,
        )
        app.state.bot = bot

        if settings.telegram_bot_token:
            try:
                await bot.start()
            except Exception:
                logger.exception("Failed to start Telegram bot — running without Telegram")

        logger.info("Governance server started on port %d", settings.server_port)
        yield

        # Shutdown
        if settings.telegram_bot_token:
            try:
                await bot.stop()
            except Exception:
                logger.exception("Error stopping Telegram bot")
        await db.close()

    app = FastAPI(title="Claude Control", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/hook/pre-tool-use")
    async def pre_tool_use(request: Request):
        body = await request.json()
        hook_req = HookRequest(**body)

        # Register session
        await app.state.registry.get_friendly_name(hook_req.session_id, hook_req.cwd)

        # Classify risk
        tier, reason = await app.state.classifier.classify(
            hook_req.tool_name, hook_req.tool_input
        )

        # Log request
        await app.state.db.create_request(
            session_id=hook_req.session_id,
            tool_name=hook_req.tool_name,
            tool_input=hook_req.tool_input,
            risk_tier=tier.value,
        )

        if tier == RiskTier.AUTO_APPROVE:
            resp = PreToolUseResponse.allow()
            return resp.model_dump(exclude_none=True)
        elif tier == RiskTier.AUTO_DENY:
            resp = PreToolUseResponse.deny(reason)
            return resp.model_dump(exclude_none=True)
        else:
            # Ask human — return no opinion, let PermissionRequest handle it
            return {}

    @app.post("/hook/permission-request")
    async def permission_request(request: Request):
        body = await request.json()
        hook_req = HookRequest(**body)

        friendly_name = await app.state.registry.get_friendly_name(
            hook_req.session_id, hook_req.cwd
        )

        # Create request record
        req_id = await app.state.db.create_request(
            session_id=hook_req.session_id,
            tool_name=hook_req.tool_name,
            tool_input=hook_req.tool_input,
            risk_tier="ask_human",
        )

        # Send Telegram notification
        try:
            msg_id = await app.state.bot.send_approval_request(
                request_id=req_id,
                friendly_name=friendly_name,
                tool_name=hook_req.tool_name,
                tool_input=hook_req.tool_input,
            )
            await app.state.db.set_telegram_message_id(req_id, msg_id)
        except Exception:
            logger.exception("Failed to send Telegram notification")

        # Wait for decision
        decision, decided_by = await app.state.engine.wait_for_decision(req_id)

        if decision is None:
            # Timeout — update Telegram message and return 408
            await app.state.db.update_decision(req_id, "timeout", "system")
            try:
                msg_id_val = (await app.state.db.get_request(req_id) or {}).get("telegram_message_id")
                if msg_id_val:
                    await app.state.bot.update_message_timeout(
                        msg_id_val, hook_req.tool_input, hook_req.tool_name, friendly_name, req_id
                    )
            except Exception:
                logger.exception("Failed to update Telegram timeout message")
            return Response(status_code=408)

        # Got a decision from Telegram
        await app.state.db.update_decision(req_id, decision, decided_by)

        if decision == "allow":
            resp = PermissionRequestResponse.allow()
        else:
            resp = PermissionRequestResponse.deny("Denied by user via Telegram")

        return resp.model_dump(exclude_none=True)

    @app.get("/queue")
    async def queue():
        return await app.state.db.get_pending_requests()

    return app


# For uvicorn direct run
settings = Settings()
app = create_app(settings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_endpoints.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/main.py tests/test_endpoints.py
git commit -m "feat: add FastAPI endpoints for PreToolUse and PermissionRequest hooks"
```

---

## Chunk 4: Setup Script & Final Integration

### Task 10: setup.sh

**Files:**
- Create: `setup.sh`

- [ ] **Step 1: Create setup.sh**

```bash
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
```

- [ ] **Step 2: Make setup.sh executable and commit**

```bash
chmod +x setup.sh
git add setup.sh
git commit -m "feat: add setup.sh for Docker build and Claude Code hook installation"
```

---

### Task 11: Store transcript_path in requests table for "Show context"

**Files:**
- Modify: `server/database.py` — add `transcript_path` column to `requests` table
- Modify: `server/main.py` — pass `transcript_path` when creating requests
- Modify: `server/telegram_bot.py` — read transcript_path from request in context callback

- [ ] **Step 1: Add transcript_path to requests table**

In `server/database.py`, add `transcript_path TEXT` to the CREATE TABLE for requests, and update `create_request` to accept and store it.

- [ ] **Step 2: Update main.py to pass transcript_path**

Pass `hook_req.transcript_path` to `db.create_request()` in both endpoints.

- [ ] **Step 3: Update telegram_bot.py context callback**

In `_handle_callback` for the `context` action, read `req["transcript_path"]` and call `self.send_context()` with it.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/database.py server/main.py server/telegram_bot.py
git commit -m "feat: store transcript_path for Show Context button"
```

---

### Task 12: CLAUDE.md and final integration test

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Create CLAUDE.md**

```markdown
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
# Install deps locally for IDE/testing
pip install -r requirements.txt

# Run all tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_risk_classifier.py -v

# Run a single test
python -m pytest tests/test_endpoints.py::test_health -v
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
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "feat: add CLAUDE.md with project overview and dev commands"
```

---

### Task 13: Manual integration test

- [ ] **Step 1: Build Docker image**

Run: `docker compose build`
Expected: Build succeeds.

- [ ] **Step 2: Verify server starts without Telegram (dry run)**

Run: `TELEGRAM_BOT_TOKEN="" TELEGRAM_CHAT_ID=0 docker compose up` (foreground, ctrl+c to stop)
Expected: Server starts, logs "Failed to start Telegram bot — running without Telegram", healthcheck passes.

- [ ] **Step 3: Test endpoints with curl**

```bash
# Health
curl http://localhost:8932/health

# Auto-approve (Read tool)
curl -X POST http://localhost:8932/hook/pre-tool-use \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/foo.py"}}'

# Auto-deny
curl -X POST http://localhost:8932/hook/pre-tool-use \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /"}}'

# Ask-human (should return {})
curl -X POST http://localhost:8932/hook/pre-tool-use \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"docker run nginx"}}'
```

- [ ] **Step 4: Stop and commit any fixes**

```bash
docker compose down
```
