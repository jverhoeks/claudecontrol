from __future__ import annotations

import logging
import re

import yaml

from server.database import Database
from server.models import RiskTier

logger = logging.getLogger(__name__)


class RiskClassifier:
    def __init__(self, rules_path: str, db: Database):
        self._rules_path = rules_path
        self._db = db
        self._auto_approve_tools: list[str] = []
        self._auto_approve_bash: list[re.Pattern] = []
        self._auto_deny_bash: list[tuple[re.Pattern, str]] = []

    async def load_rules(self) -> None:
        try:
            with open(self._rules_path) as f:
                rules = yaml.safe_load(f)

            self._auto_approve_tools = rules.get("auto_approve", {}).get("tools", [])
            self._auto_approve_bash = [
                re.compile(p)
                for p in rules.get("auto_approve", {}).get("bash_patterns", [])
            ]
            self._auto_deny_bash = [
                (re.compile(p), p)
                for p in rules.get("auto_deny", {}).get("bash_patterns", [])
            ]
            logger.info(
                "Loaded rules: %d approve tools, %d approve patterns, %d deny patterns",
                len(self._auto_approve_tools),
                len(self._auto_approve_bash),
                len(self._auto_deny_bash),
            )
        except Exception:
            logger.exception("Failed to load rules from %s — keeping previous rules", self._rules_path)

    async def classify(self, tool_name: str, tool_input: dict) -> tuple[RiskTier, str]:
        match_str = self._get_match_string(tool_name, tool_input)

        # 1. Check denylist (highest priority)
        for pattern in await self._db.get_denylist_patterns():
            if self._matches(pattern, tool_name, match_str):
                return RiskTier.AUTO_DENY, f"Blocked by denylist: {pattern['pattern']}"

        # 2. Check whitelist
        for pattern in await self._db.get_whitelist_patterns():
            if self._matches(pattern, tool_name, match_str):
                return RiskTier.AUTO_APPROVE, f"Allowed by whitelist: {pattern['pattern']}"

        # 3. Check rules.yaml auto-deny
        if tool_name == "Bash" and match_str:
            for compiled, raw in self._auto_deny_bash:
                if compiled.search(match_str):
                    return RiskTier.AUTO_DENY, f"Blocked by rule: {raw}"

        # 4. Check rules.yaml auto-approve
        if tool_name in self._auto_approve_tools:
            return RiskTier.AUTO_APPROVE, f"Tool {tool_name} is auto-approved"

        if tool_name == "Bash" and match_str:
            for compiled in self._auto_approve_bash:
                if compiled.search(match_str):
                    return RiskTier.AUTO_APPROVE, "Matched auto-approve pattern"

        # 5. Default: ask-human
        return RiskTier.ASK_HUMAN, ""

    def _get_match_string(self, tool_name: str, tool_input: dict) -> str | None:
        if tool_name == "Bash":
            return tool_input.get("command")
        if tool_name in ("Edit", "Write"):
            return tool_input.get("file_path")
        return None

    def _matches(self, db_pattern: dict, tool_name: str, match_str: str | None) -> bool:
        if db_pattern["tool_name"] != tool_name:
            return False
        if match_str is None:
            return False
        try:
            return bool(re.search(db_pattern["pattern"], match_str))
        except re.error:
            logger.warning("Invalid regex in DB pattern: %s", db_pattern["pattern"])
            return False
