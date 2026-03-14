from __future__ import annotations

import json
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from server.decision_engine import DecisionEngine
from server.database import Database

logger = logging.getLogger(__name__)


def generate_similar_pattern(tool_name: str, tool_input: dict) -> str | None:
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        parts = command.split()
        if len(parts) <= 1:
            return f"^{command}$"
        return "^" + " ".join(parts[:-1]) + " .*$"
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        last_slash = file_path.rfind("/")
        if last_slash >= 0:
            return "^" + file_path[: last_slash + 1] + ".*$"
        return None
    return None


def format_approval_message(
    friendly_name: str,
    tool_name: str,
    tool_input: dict,
    request_id: str,
) -> str:
    if tool_name == "Bash":
        display = tool_input.get("command", str(tool_input))
    elif tool_name in ("Edit", "Write"):
        display = tool_input.get("file_path", str(tool_input))
    else:
        display = json.dumps(tool_input, indent=2)[:200]

    return (
        f"\U0001f512 Approval Request\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c2 {friendly_name}\n"
        f"\U0001f527 {tool_name}\n"
        f"\U0001f4bb {display}\n"
        f"\u26a0\ufe0f Tier: NEEDS APPROVAL"
    )


def build_approval_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\u2705 Approve", callback_data=f"approve:{request_id}"),
                InlineKeyboardButton("\u274c Deny", callback_data=f"deny:{request_id}"),
            ],
            [
                InlineKeyboardButton(
                    "\U0001f504 Auto-approve similar",
                    callback_data=f"whitelist:{request_id}",
                ),
                InlineKeyboardButton(
                    "\U0001f4cb Show context",
                    callback_data=f"context:{request_id}",
                ),
            ],
        ]
    )


def build_timeout_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\u2705 Approve queued", callback_data=f"approve_queued:{request_id}"),
                InlineKeyboardButton("\U0001f5d1 Dismiss", callback_data=f"dismiss:{request_id}"),
            ],
        ]
    )


class TelegramBot:
    def __init__(
        self,
        token: str,
        chat_id: int,
        decision_engine: DecisionEngine,
        db: Database,
    ):
        self._token = token
        self._chat_id = chat_id
        self._engine = decision_engine
        self._db = db
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_approval_request(
        self,
        request_id: str,
        friendly_name: str,
        tool_name: str,
        tool_input: dict,
    ) -> int:
        text = format_approval_message(friendly_name, tool_name, tool_input, request_id)
        keyboard = build_approval_keyboard(request_id)
        msg = await self._app.bot.send_message(
            chat_id=self._chat_id,
            text=text,
            reply_markup=keyboard,
        )
        return msg.message_id

    async def update_message_decided(
        self, message_id: int, tool_input: dict, tool_name: str, friendly_name: str, decision: str, elapsed: float
    ) -> None:
        icon = "\u2705" if decision == "allow" else "\u274c"
        verb = "APPROVED" if decision == "allow" else "DENIED"
        if tool_name == "Bash":
            display = tool_input.get("command", "")
        else:
            display = tool_input.get("file_path", str(tool_input))
        text = f"{icon} {verb} \u2014 {display}\n\U0001f4c2 {friendly_name} \u00b7 {elapsed:.0f}s"
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
            )
        except Exception:
            logger.exception("Failed to update Telegram message %d", message_id)

    async def update_message_timeout(
        self, message_id: int, tool_input: dict, tool_name: str, friendly_name: str, request_id: str
    ) -> None:
        if tool_name == "Bash":
            display = tool_input.get("command", "")
        else:
            display = tool_input.get("file_path", str(tool_input))
        text = (
            f"\u23f0 Timed out \u2014 queued for retry\n"
            f"\U0001f4bb {display}\n"
            f"\U0001f4c2 {friendly_name}"
        )
        keyboard = build_timeout_keyboard(request_id)
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to update Telegram message %d for timeout", message_id)

    async def send_context(self, transcript_path: str | None) -> None:
        if not transcript_path:
            await self._app.bot.send_message(
                chat_id=self._chat_id, text="No transcript available."
            )
            return
        try:
            with open(transcript_path) as f:
                lines = f.readlines()
            context = "".join(lines[-10:])
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=f"Last 10 transcript lines:\n```\n{context[:3000]}\n```",
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Failed to read transcript at %s", transcript_path)
            await self._app.bot.send_message(
                chat_id=self._chat_id, text="Failed to read transcript."
            )

    async def send_question_notification(self, friendly_name: str, question: str) -> None:
        snippet = question[-500:] if len(question) > 500 else question
        text = (
            f"\U0001f914 Waiting for input\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4c2 {friendly_name}\n\n"
            f"{snippet}"
        )
        await self._app.bot.send_message(chat_id=self._chat_id, text=text)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.message.chat_id != self._chat_id:
            return
        await query.answer()

        data = query.data
        action, request_id = data.split(":", 1)

        req = await self._db.get_request(request_id)
        if req is None:
            return

        if action == "approve":
            is_late = self._engine.resolve(request_id, "allow", "telegram")
            await self._db.update_decision(request_id, "allow", "telegram")
            if is_late:
                pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
                if pattern:
                    await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram-late")
                await query.edit_message_text("Handled in CLI \u2014 pattern saved for next time.")
            else:
                await query.edit_message_text(f"\u2705 APPROVED \u2014 {req['tool_input'].get('command', '')}")

        elif action == "deny":
            is_late = self._engine.resolve(request_id, "deny", "telegram")
            await self._db.update_decision(request_id, "deny", "telegram")
            if is_late:
                await self._db.add_denylist_pattern(
                    req["tool_name"],
                    f"^{req['tool_input'].get('command', '')}$",
                    "telegram-late",
                )
                await query.edit_message_text("Handled in CLI \u2014 deny pattern saved for next time.")
            else:
                await query.edit_message_text(f"\u274c DENIED \u2014 {req['tool_input'].get('command', '')}")

        elif action == "whitelist":
            pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
            if pattern:
                await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram")
            self._engine.resolve(request_id, "allow", "telegram")
            await self._db.update_decision(request_id, "allow", "telegram")
            await query.edit_message_text(f"\u2705 APPROVED + whitelisted: {pattern}")

        elif action == "approve_queued":
            pattern = generate_similar_pattern(req["tool_name"], req["tool_input"])
            if pattern:
                await self._db.add_whitelist_pattern(req["tool_name"], pattern, "telegram-queued")
            await self._db.update_decision(request_id, "allow", "telegram-queued")
            await query.edit_message_text(f"\u2705 Queued approval \u2014 whitelisted: {pattern}")

        elif action == "context":
            await self.send_context(req.get("transcript_path"))

        elif action == "dismiss":
            await self._db.update_decision(request_id, "dismissed", "telegram")
            await query.edit_message_text("\U0001f5d1 Dismissed")
