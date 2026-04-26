"""Feishu event JSON parsers — raw webhook payload → typed event objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class FeishuCallbackEvent:
    """Parsed card button click callback."""

    chat_id: str
    user_id: str
    """Feishu open_id of the user who clicked."""
    action_value: str
    """Raw action value from the card button's value field."""
    message_id: str
    """ID of the card message that was clicked."""
    token: str
    """Feishu callback verification token for response."""
    thread_id: str = ""
    """Thread ID if the card is in a thread."""


@dataclass(frozen=True)
class FeishuURLVerificationEvent:
    """Webhook URL verification challenge request."""

    challenge: str


def parse_message_event(payload: dict) -> FeishuMessageEvent | None:
    """Parse a Feishu im.message.receive_v1 event payload."""
    try:
        event = payload.get("event", {})
        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", {})
        chat_id = event.get("chat_id", "")
        message = event.get("message", {})
        msg_type = message.get("msg_type", "")
        message_id = message.get("message_id", "")

        # Only handle text messages for now
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


def parse_callback_event(payload: dict) -> FeishuCallbackEvent | None:
    """Parse a Feishu card button click callback payload."""
    try:
        action = payload.get("action", {})
        chat = payload.get("chat", {})
        sender = payload.get("sender", {})
        sender_id = sender.get("sender_id", {})
        value_raw = action.get("value", "{}")
        if isinstance(value_raw, str):
            import json as _json
            value_raw = _json.loads(value_raw)

        return FeishuCallbackEvent(
            chat_id=chat.get("chat_id", ""),
            user_id=sender_id.get("open_id", ""),
            action_value=value_raw.get("action", ""),
            message_id=action.get("message_id", ""),
            token=payload.get("token", ""),
            thread_id=chat.get("thread_id", ""),
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def parse_url_verification(payload: dict) -> FeishuURLVerificationEvent | None:
    """Parse a URL verification challenge request."""
    challenge = payload.get("challenge", "")
    if challenge:
        return FeishuURLVerificationEvent(challenge=challenge)
    return None


def is_card_callback(payload: dict) -> bool:
    """Return True if this is a card callback event (not a message event)."""
    return "action" in payload and "value" in payload.get("action", {})
