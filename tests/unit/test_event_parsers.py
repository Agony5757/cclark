"""Tests for event_parsers: Feishu WS payload → typed event objects."""

from cclark.event_parsers import (
    FeishuMessageEvent,
    parse_message_event,
)


class TestParseMessageEvent:
    def test_valid_text_message(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "thread_id": "oc_thread1",
                "sender": {"sender_id": {"open_id": "ou_user1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "hello world"}',
                },
            }
        }
        result = parse_message_event(payload)
        assert result is not None
        assert result == FeishuMessageEvent(
            chat_id="oc_chat1",
            thread_id="oc_thread1",
            user_id="ou_user1",
            text="hello world",
            message_id="om_msg1",
            msg_type="text",
        )

    def test_text_message_strips_whitespace(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_user1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "  /new  "}',
                },
            }
        }
        result = parse_message_event(payload)
        assert result is not None
        assert result.text == "/new"

    def test_missing_thread_id_returns_empty_string(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_user1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "hello"}',
                },
            }
        }
        result = parse_message_event(payload)
        assert result is not None
        assert result.thread_id == ""

    def test_non_text_msg_type_returns_none(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_user1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "image",
                    "content": "{}",
                },
            }
        }
        assert parse_message_event(payload) is None

    def test_missing_event_key_returns_none(self) -> None:
        assert parse_message_event({}) is None

    def test_missing_open_id_returns_empty_user_id(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "hi"}',
                },
            }
        }
        result = parse_message_event(payload)
        assert result is not None
        assert result.user_id == ""

    def test_invalid_json_content_returns_none(self) -> None:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_user1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": "not valid json",
                },
            }
        }
        assert parse_message_event(payload) is None
