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
