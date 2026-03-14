from __future__ import annotations

from server.database import Database


class SessionRegistry:
    def __init__(self, db: Database):
        self._db = db

    async def get_friendly_name(self, session_id: str, project_path: str) -> str:
        return await self._db.upsert_session(session_id, project_path)
