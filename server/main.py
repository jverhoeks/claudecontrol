from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from server.config import Settings
from server.database import Database
from server.decision_engine import DecisionEngine
from server.models import HookRequest, PreToolUseResponse, PermissionRequestResponse, RiskTier
from server.risk_classifier import RiskClassifier
from server.session_registry import SessionRegistry
from server.telegram_bot import TelegramBot


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logging.basicConfig(level=getattr(logging, settings.log_level))

        db = Database(settings.db_path)
        await db.init()
        app.state.db = db

        classifier = RiskClassifier(settings.rules_path, db)
        await classifier.load_rules()
        app.state.classifier = classifier

        engine = DecisionEngine(timeout_seconds=settings.permission_request_timeout)
        app.state.engine = engine

        registry = SessionRegistry(db)
        app.state.registry = registry

        bot = TelegramBot(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            decision_engine=engine,
            db=db,
        )
        app.state.bot = bot

        if settings.telegram_bot_token:
            try:
                await bot.start()
            except Exception:
                logger.exception("Failed to start Telegram bot — running without Telegram")

        logger.info("Governance server started on port %d", settings.server_port)
        yield

        # Shutdown
        if settings.telegram_bot_token:
            try:
                await bot.stop()
            except Exception:
                logger.exception("Error stopping Telegram bot")
        await db.close()

    app = FastAPI(title="Claude Control", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/hook/pre-tool-use")
    async def pre_tool_use(request: Request):
        body = await request.json()
        hook_req = HookRequest(**body)

        # Register session
        await app.state.registry.get_friendly_name(hook_req.session_id, hook_req.cwd)

        # Classify risk
        tier, reason = await app.state.classifier.classify(
            hook_req.tool_name, hook_req.tool_input
        )

        # Log request
        await app.state.db.create_request(
            session_id=hook_req.session_id,
            tool_name=hook_req.tool_name,
            tool_input=hook_req.tool_input,
            risk_tier=tier.value,
        )

        if tier == RiskTier.AUTO_APPROVE:
            resp = PreToolUseResponse.allow()
            return resp.model_dump(exclude_none=True)
        elif tier == RiskTier.AUTO_DENY:
            resp = PreToolUseResponse.deny(reason)
            return resp.model_dump(exclude_none=True)
        else:
            # Ask human — return no opinion, let PermissionRequest handle it
            return {}

    @app.post("/hook/permission-request")
    async def permission_request(request: Request):
        body = await request.json()
        hook_req = HookRequest(**body)

        friendly_name = await app.state.registry.get_friendly_name(
            hook_req.session_id, hook_req.cwd
        )

        # Create request record
        req_id = await app.state.db.create_request(
            session_id=hook_req.session_id,
            tool_name=hook_req.tool_name,
            tool_input=hook_req.tool_input,
            risk_tier="ask_human",
        )

        # Send Telegram notification
        try:
            msg_id = await app.state.bot.send_approval_request(
                request_id=req_id,
                friendly_name=friendly_name,
                tool_name=hook_req.tool_name,
                tool_input=hook_req.tool_input,
            )
            await app.state.db.set_telegram_message_id(req_id, msg_id)
        except Exception:
            logger.exception("Failed to send Telegram notification")

        # Wait for decision
        decision, decided_by = await app.state.engine.wait_for_decision(req_id)

        if decision is None:
            # Timeout — update Telegram message and return 408
            await app.state.db.update_decision(req_id, "timeout", "system")
            try:
                msg_id_val = (await app.state.db.get_request(req_id) or {}).get("telegram_message_id")
                if msg_id_val:
                    await app.state.bot.update_message_timeout(
                        msg_id_val, hook_req.tool_input, hook_req.tool_name, friendly_name, req_id
                    )
            except Exception:
                logger.exception("Failed to update Telegram timeout message")
            return Response(status_code=408)

        # Got a decision from Telegram
        await app.state.db.update_decision(req_id, decision, decided_by)

        if decision == "allow":
            resp = PermissionRequestResponse.allow()
        else:
            resp = PermissionRequestResponse.deny("Denied by user via Telegram")

        return resp.model_dump(exclude_none=True)

    @app.get("/queue")
    async def queue():
        return await app.state.db.get_pending_requests()

    return app


# For uvicorn direct run
settings = Settings()
app = create_app(settings)
