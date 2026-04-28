"""Feishu event JSON parsers — raw WS payload → typed event objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeishuMessageEvent:
    """Parsed inbound Feishu message event."""

    chat_id: str
    """Feishu chat_id (group or p2p)."""
    thread_id: str
    """Feishu thread_id (empty string if not in a thread)."""
    user_id: str
    """Feishu open_id of the sender."""
    text: str
    """Message text content (empty string if not a text message)."""
    message_id: str
    """Feishu message_id for reply threading."""
    msg_type: str
    """Feishu message type: text, image, file, card, etc."""
    app_name: str = "default"
    """App name this message belongs to (set by FeishuWSClient, for multi-app routing)."""


def parse_message_event(payload: dict) -> FeishuMessageEvent | None:
    """Parse a Feishu im.message.receive_v1 event payload (schema 1.0 and 2.0)."""
    try:
        event = payload.get("event", {})
        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {})
        message = event.get("message", {})
        message_id = message.get("message_id", "")

        # Schema 2.0 uses message_type and message.chat_id;
        # schema 1.0 uses msg_type and event.chat_id
        msg_type = message.get("message_type", "") or message.get("msg_type", "")
        chat_id = message.get("chat_id", "") or event.get("chat_id", "")

        if msg_type != "text":
            return None

        content = message.get("content", "{}")
        import json as _json
        parsed = _json.loads(content)
        text = parsed.get("text", "").strip()

        return FeishuMessageEvent(
            chat_id=chat_id,
            thread_id=event.get("thread_id", ""),
            user_id=sender_id.get("open_id", ""),
            text=text,
            message_id=message_id,
            msg_type=msg_type,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
