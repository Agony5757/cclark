from __future__ import annotations

from types import SimpleNamespace

import pytest

from cclark.main import (
    _auto_dismiss_terminal_panel,
    _send_regular_text,
    _send_regular_verbose_card,
    _should_auto_dismiss_terminal_panel,
    _split_messages,
    _trim_terminal_panel_body,
)
from cclark.state import advance_turn_index, get_verbose_state, reset_channel_state


class _FakeClient:
    def __init__(self) -> None:
        self.sent_cards: list[tuple[str, str]] = []
        self.patched_cards: list[tuple[str, str]] = []

    async def send_interactive_card(self, chat_id: str, card_json: str) -> str:
        self.sent_cards.append((chat_id, card_json))
        return f"om_card_{len(self.sent_cards)}"

    async def patch_message(self, message_id: str, card_json: str) -> None:
        self.patched_cards.append((message_id, card_json))


class _FakeAdapter:
    def __init__(self) -> None:
        self._client = _FakeClient()
        self.sent_text: list[tuple[str, str]] = []

    async def send_text(self, channel_id: str, text: str) -> str:
        self.sent_text.append((channel_id, text))
        return "om_text_1"


class _FakeGateway:
    def __init__(self) -> None:
        self.keys: list[tuple[str, str]] = []

    async def send_key(self, window_id: str, key: str) -> None:
        self.keys.append((window_id, key))


@pytest.mark.asyncio
async def test_send_regular_text_compact_mode_sends_plain_text() -> None:
    adapter = _FakeAdapter()
    regular_msgs = [SimpleNamespace(text="hello"), SimpleNamespace(text="world")]
    channel_id = "feishu:oc_test:"

    await _send_regular_text(adapter, channel_id, regular_msgs)

    assert adapter.sent_text == [(channel_id, "hello\nworld")]
    assert adapter._client.sent_cards == []


def test_split_messages_treats_expquote_markers_as_thinking() -> None:
    thinking_marker = "\x02EXPQUOTE_START\x02internal reasoning\x02EXPQUOTE_END\x02"
    messages = [
        SimpleNamespace(text=thinking_marker, content_type="text", role="assistant"),
        SimpleNamespace(text="final answer", content_type="text", role="assistant"),
    ]

    thinking, regular = _split_messages(messages)

    assert [m.text for m in thinking] == [thinking_marker]
    assert [m.text for m in regular] == ["final answer"]


def test_trim_terminal_panel_body_keeps_latest_prompt_panel() -> None:
    body = """
❯ /status
  ⎿  Status dialog dismissed

❯ /status

─────
   Status   Config   Usage   Stats

  Version:             2.1.122
  Esc to cancel
"""

    trimmed = _trim_terminal_panel_body(body)

    assert "Status dialog dismissed" not in trimmed
    assert trimmed.startswith("❯ /status")
    assert "Version:             2.1.122" in trimmed


def test_status_panel_should_auto_dismiss_after_capture() -> None:
    body = """
❯ /status

─────
   Status   Config   Usage   Stats

  Version:             2.1.122
  Esc to cancel
"""

    assert _should_auto_dismiss_terminal_panel(body) is True


def test_escape_cancel_panel_should_auto_dismiss_after_capture() -> None:
    body = """
❯ /permissions

─────
  Permissions:  Recently denied   Allow   Ask   Deny   Workspace

   ←/→ tab switch · ↓ return · Esc cancel
"""

    assert _should_auto_dismiss_terminal_panel(body) is True


@pytest.mark.asyncio
async def test_escape_cancel_panel_dismisses_with_retry() -> None:
    gateway = _FakeGateway()

    await _auto_dismiss_terminal_panel(
        gateway,
        "@1",
        "←/→ tab switch · ↓ return · Esc cancel",
    )

    assert gateway.keys == [("@1", "Escape"), ("@1", "Escape")]


@pytest.mark.asyncio
async def test_send_regular_text_defensively_drops_expquote_markers() -> None:
    adapter = _FakeAdapter()
    thinking_marker = "\x02EXPQUOTE_START\x02internal reasoning\x02EXPQUOTE_END\x02"
    regular_msgs = [
        SimpleNamespace(text=thinking_marker, content_type="text"),
        SimpleNamespace(text="final answer", content_type="text"),
    ]
    channel_id = "feishu:oc_test:"

    await _send_regular_text(adapter, channel_id, regular_msgs)

    assert adapter.sent_text == [(channel_id, "final answer")]
    assert "internal reasoning" not in adapter.sent_text[0][1]


@pytest.mark.asyncio
async def test_send_regular_verbose_card_creates_then_patches_same_turn() -> None:
    channel_id = "feishu:oc_verbose:"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = True
    advance_turn_index(channel_id)
    adapter = _FakeAdapter()

    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="first chunk")],
        provider="claude",
    )
    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="second chunk")],
        provider="claude",
    )

    assert len(adapter._client.sent_cards) == 1
    assert len(adapter._client.patched_cards) == 1
    assert adapter.sent_text == []


@pytest.mark.asyncio
async def test_send_regular_verbose_card_creates_new_card_after_turn_advances() -> None:
    channel_id = "feishu:oc_verbose_new_turn:"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = True
    adapter = _FakeAdapter()

    advance_turn_index(channel_id)
    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="first turn")],
        provider="claude",
    )

    advance_turn_index(channel_id)
    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="second turn")],
        provider="claude",
    )

    assert len(adapter._client.sent_cards) == 2
    assert adapter._client.patched_cards == []
