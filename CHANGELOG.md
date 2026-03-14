# Changelog

## [Unreleased]

### Changed
- **Telegram approval moved to PreToolUse hook** — eliminates the race condition where PermissionRequest ran in parallel with the CLI dialog. Telegram now gets first shot before any CLI prompt appears. On timeout, falls back to CLI as before.
- PreToolUse HTTP timeout increased from 10s to 180s to accommodate Telegram response time
- PermissionRequest hook is now a passthrough (returns `{}`)
- Default `PERMISSION_REQUEST_TIMEOUT` increased from 5s to 120s

### Fixed
- **Invalid regex patterns in whitelist/denylist** — `generate_similar_pattern` now uses `re.escape()` so commands with heredocs, subshells, and special chars produce valid regex
- Regex validation before storing patterns in the database
- Startup cleanup of existing invalid patterns from the DB
- Added missing `hookEventName: "PermissionRequest"` to response model

### Added
- **Stop hook for question detection** — sends a Telegram notification when Claude asks a question and is waiting for user input. Only triggers on `end_turn` with a `?` in the last assistant message.
- New `/hook/stop` endpoint in the governance server
- `StopHookRequest` model for Stop hook payloads
- `send_question_notification` method on TelegramBot
- Mount `~/.claude` read-only in Docker so transcript files are accessible for question detection
- Stop hook installation in `setup.sh` alongside PreToolUse and PermissionRequest hooks
