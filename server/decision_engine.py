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
