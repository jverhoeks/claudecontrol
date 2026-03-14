from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class RiskTier(str, Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    ASK_HUMAN = "ask_human"


class HookRequest(BaseModel):
    session_id: str
    cwd: str
    hook_event_name: str
    tool_name: str
    tool_input: dict[str, Any]
    permission_mode: str | None = None
    transcript_path: str | None = None


class StopHookRequest(BaseModel):
    session_id: str
    cwd: str
    hook_event_name: str = "Stop"
    stop_reason: str | None = None
    transcript_path: str | None = None


class _PreToolUseOutput(BaseModel):
    hookEventName: str = "PreToolUse"
    permissionDecision: str
    permissionDecisionReason: str | None = None


class PreToolUseResponse(BaseModel):
    hookSpecificOutput: _PreToolUseOutput | None = None

    @classmethod
    def allow(cls) -> PreToolUseResponse:
        return cls(hookSpecificOutput=_PreToolUseOutput(permissionDecision="allow"))

    @classmethod
    def deny(cls, reason: str) -> PreToolUseResponse:
        return cls(hookSpecificOutput=_PreToolUseOutput(permissionDecision="deny", permissionDecisionReason=reason))

    @classmethod
    def no_opinion(cls) -> PreToolUseResponse:
        return cls(hookSpecificOutput=None)


class _PermissionDecision(BaseModel):
    behavior: str
    reason: str | None = None


class _PermissionRequestOutput(BaseModel):
    decision: _PermissionDecision


class PermissionRequestResponse(BaseModel):
    hookSpecificOutput: _PermissionRequestOutput | None = None

    @classmethod
    def allow(cls) -> PermissionRequestResponse:
        return cls(hookSpecificOutput=_PermissionRequestOutput(decision=_PermissionDecision(behavior="allow")))

    @classmethod
    def deny(cls, reason: str) -> PermissionRequestResponse:
        return cls(hookSpecificOutput=_PermissionRequestOutput(decision=_PermissionDecision(behavior="deny", reason=reason)))
