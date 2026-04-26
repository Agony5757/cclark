"""Tests for event_parsers: Feishu webhook payload → typed event objects."""

import pytest

from cclark.event_parsers import (
    FeishuCallbackEvent,
    FeishuMessageEvent,
    FeishuURLVerificationEvent,
    is_card_callback,
    parse_callback_event,
    parse_message_event,
    parse_url_verification,
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


class TestParseCallbackEvent:
    def test_valid_callback_with_string_value(self) -> None:
        payload = {
            "action": {
                "value": '{"action": "db:sel:/path/to/dir"}',
                "message_id": "om_card1",
            },
            "chat": {"chat_id": "oc_chat1", "thread_id": "oc_thread1"},
            "sender": {"sender_id": {"open_id": "ou_user1"}},
            "token": "test_token",
        }
        result = parse_callback_event(payload)
        assert result is not None
        assert result == FeishuCallbackEvent(
            chat_id="oc_chat1",
            thread_id="oc_thread1",
            user_id="ou_user1",
            action_value="db:sel:/path/to/dir",
            message_id="om_card1",
            token="test_token",
        )

    def test_valid_callback_with_dict_value(self) -> None:
        payload = {
            "action": {
                "value": {"action": "prov:claude"},
                "message_id": "om_card2",
            },
            "chat": {"chat_id": "oc_chat2"},
            "sender": {"sender_id": {"open_id": "ou_user2"}},
            "token": "token2",
        }
        result = parse_callback_event(payload)
        assert result is not None
        assert result.action_value == "prov:claude"
        assert result.thread_id == ""

    def test_missing_chat_returns_empty(self) -> None:
        payload = {
            "action": {"value": '{"action": "noop"}', "message_id": "om_card1"},
            "chat": {},
            "sender": {"sender_id": {"open_id": "ou_user1"}},
            "token": "tok",
        }
        result = parse_callback_event(payload)
        assert result is not None
        assert result.chat_id == ""
        assert result.thread_id == ""

    def test_missing_action_returns_empty_event(self) -> None:
        # No action key → empty strings (no exception, no None)
        result = parse_callback_event({})
        assert result is not None
        assert result.action_value == ""
        assert result.chat_id == ""
        assert result.user_id == ""

    def test_invalid_json_value_returns_none(self) -> None:
        payload = {
            "action": {"value": "not json", "message_id": "om_card1"},
            "chat": {},
            "sender": {},
            "token": "",
        }
        assert parse_callback_event(payload) is None


class TestParseURLVerification:
    def test_valid_challenge(self) -> None:
        payload = {"challenge": "abc123def"}
        result = parse_url_verification(payload)
        assert result == FeishuURLVerificationEvent(challenge="abc123def")

    def test_empty_challenge_returns_none(self) -> None:
        assert parse_url_verification({}) is None
        assert parse_url_verification({"challenge": ""}) is None


class TestIsCardCallback:
    def test_with_action_and_value_is_true(self) -> None:
        payload = {"action": {"value": "{}"}}
        assert is_card_callback(payload) is True

    def test_with_action_but_no_value_is_false(self) -> None:
        payload = {"action": {"text": "hello"}}
        assert is_card_callback(payload) is False

    def test_missing_action_is_false(self) -> None:
        assert is_card_callback({}) is False
        assert is_card_callback({"event": "message"}) is False
