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
