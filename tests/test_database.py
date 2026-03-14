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
    req_id = _run(db.create_request(session_id="s1", tool_name="Bash", tool_input={"command": "ls"}, risk_tier="auto_approve"))
    assert req_id is not None
    req = _run(db.get_request(req_id))
    assert req["session_id"] == "s1"
    assert req["tool_name"] == "Bash"
    assert req["decision"] == "pending"


def test_update_decision(db):
    req_id = _run(db.create_request(session_id="s1", tool_name="Bash", tool_input={"command": "rm -rf /"}, risk_tier="auto_deny"))
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
