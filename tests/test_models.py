from server.models import HookRequest, PreToolUseResponse, PermissionRequestResponse, RiskTier


def test_hook_request_parses_bash_command():
    data = {
        "session_id": "abc123", "cwd": "/Users/jj/src/my-project",
        "hook_event_name": "PreToolUse", "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "permission_mode": "default", "transcript_path": "/tmp/transcript.jsonl",
    }
    req = HookRequest(**data)
    assert req.session_id == "abc123"
    assert req.tool_name == "Bash"
    assert req.tool_input == {"command": "git push origin main"}


def test_hook_request_parses_edit_tool():
    data = {
        "session_id": "abc123", "cwd": "/Users/jj/src/my-project",
        "hook_event_name": "PreToolUse", "tool_name": "Edit",
        "tool_input": {"file_path": "/src/foo.py", "file_contents": "x = 1"},
        "permission_mode": "default",
    }
    req = HookRequest(**data)
    assert req.tool_name == "Edit"


def test_hook_request_allows_missing_optional_fields():
    data = {
        "session_id": "abc123", "cwd": "/tmp",
        "hook_event_name": "PreToolUse", "tool_name": "Read",
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
