"""FastAPI webhook server for Feishu bot events."""

from __future__ import annotations

import json
import structlog
from typing import Any, Callable, Awaitable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cclark.callback_registry import CallbackContext
from cclark.config import config
from cclark.event_parsers import (
    is_card_callback,
    parse_callback_event,
    parse_message_event,
    parse_url_verification,
)
from cclark.feishu_client import FeishuClient

logger = structlog.get_logger()

# Module-level callback handler registration
_callback_handler: Callable[[dict], Awaitable[None]] | None = None
_message_handler: Callable[[dict], Awaitable[None]] | None = None


def register_message_handler(handler: Callable[[dict], Awaitable[None]]) -> None:
    global _message_handler
    _message_handler = handler


def register_callback_handler(handler: Callable[[dict], Awaitable[None]]) -> None:
    global _callback_handler
    _callback_handler = handler


def create_app(client: FeishuClient) -> FastAPI:  # noqa: ARG001, C901
    app = FastAPI(title="cclark webhook")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(config.webhook_path)
    async def webhook_event(request: Request) -> Response:
        try:
            payload: dict[str, Any] = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"error": "invalid JSON"})

        # URL verification challenge
        verification = parse_url_verification(payload)
        if verification:
            return JSONResponse(content={"challenge": verification.challenge})

        # Card button click
        if is_card_callback(payload):
            return await _handle_callback(payload)

        # Inbound message
        return await _handle_message(payload)

    async def _handle_callback(payload: dict[str, Any]) -> Response:
        event = parse_callback_event(payload)
        if event is None:
            return JSONResponse(status_code=400, content={"error": "bad callback"})

        # Verify challenge token if configured
        if config.feishu_verification_token and event.token != config.feishu_verification_token:
            logger.warning("Callback token mismatch")
            return JSONResponse(status_code=403, content={"error": "forbidden"})

        channel_id = config.parse_channel_id(event.chat_id, event.thread_id)
        ctx = CallbackContext(
            user_id=event.user_id,
            chat_id=event.chat_id,
            thread_id=event.thread_id,
            value=event.action_value,
            message_id=event.message_id,
            token=event.token,
            channel_id=channel_id,
        )

        if _callback_handler is None:
            logger.warning("No callback handler registered")
            return JSONResponse(content={"error": "no handler"})

        try:
            await _callback_handler(ctx)
        except Exception:
            logger.exception("Callback handler failed")
            return JSONResponse(status_code=500, content={"error": "handler failed"})

        return JSONResponse(content={"status": "ok"})

    async def _handle_message(payload: dict[str, Any]) -> Response:
        event = parse_message_event(payload)
        if event is None:
            # Non-text or malformed — acknowledge silently
            return JSONResponse(content={"status": "ok"})

        # Skip bot's own messages
        if event.user_id == config.bot_user_id:
            return JSONResponse(content={"status": "ok"})

        if not config.is_user_allowed(event.user_id):
            logger.info("Message from unauthorized user %s", event.user_id)
            return JSONResponse(content={"status": "ok"})

        if _message_handler is None:
            logger.warning("No message handler registered")
            return JSONResponse(content={"status": "ok"})

        try:
            await _message_handler(event)
        except Exception:
            logger.exception("Message handler failed")

        return JSONResponse(content={"status": "ok"})

    return app
