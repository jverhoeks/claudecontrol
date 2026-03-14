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
        is_late = engine.resolve(req_id, "allow", "telegram")
        return decision, decided_by, is_late

    decision, decided_by, is_late = _run(run())
    assert decision is None
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
