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
                transcript_path TEXT,
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
        transcript_path: str | None = None,
    ) -> str:
        req_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO requests (id, session_id, tool_name, tool_input, risk_tier, transcript_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (req_id, session_id, tool_name, json.dumps(tool_input), risk_tier, transcript_path, now),
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
        cursor = await self._db.execute("SELECT * FROM requests WHERE telegram_message_id = ?", (msg_id,))
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
        await self._db.execute("UPDATE requests SET telegram_message_id = ? WHERE id = ?", (msg_id, req_id))
        await self._db.commit()

    async def get_pending_requests(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM requests WHERE decision = 'pending' ORDER BY created_at")
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tool_input"] = json.loads(d["tool_input"])
            result.append(d)
        return result

    async def upsert_session(self, session_id: str, project_path: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        existing = await cursor.fetchone()
        if existing:
            await self._db.execute("UPDATE sessions SET last_seen = ? WHERE session_id = ?", (now, session_id))
            await self._db.commit()
            return dict(existing)["friendly_name"]

        dir_name = project_path.rstrip("/").split("/")[-1] if "/" in project_path else project_path
        cursor = await self._db.execute("SELECT COUNT(*) as cnt FROM sessions WHERE project_path = ?", (project_path,))
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
        cursor = await self._db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
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
