# Changelog

## [Unreleased]

### Added
- **Stop hook for question detection** — sends a Telegram notification when Claude asks a question and is waiting for user input. Only triggers on `end_turn` with a `?` in the last assistant message.
- New `/hook/stop` endpoint in the governance server
- `StopHookRequest` model for Stop hook payloads
- `send_question_notification` method on TelegramBot
- Mount `~/.claude` read-only in Docker so transcript files are accessible for question detection
- Stop hook installation in `setup.sh` alongside PreToolUse and PermissionRequest hooks
