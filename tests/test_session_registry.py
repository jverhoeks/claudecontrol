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
