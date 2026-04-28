from __future__ import annotations

from types import SimpleNamespace

import pytest

from cclark.main import _send_regular_text, _send_regular_verbose_card, _split_messages
from cclark.state import advance_turn_index, get_verbose_state, reset_channel_state


class _FakeClient:
    def __init__(self) -> None:
        self.sent_cards: list[tuple[str, str]] = []
        self.patched_cards: list[tuple[str, str]] = []

    async def send_interactive_card(self, chat_id: str, card_json: str) -> str:
        self.sent_cards.append((chat_id, card_json))
        return "om_card_1"

    async def patch_message(self, message_id: str, card_json: str) -> None:
        self.patched_cards.append((message_id, card_json))


class _FakeAdapter:
    def __init__(self) -> None:
        self._client = _FakeClient()
        self.sent_text: list[tuple[str, str]] = []

    async def send_text(self, channel_id: str, text: str) -> str:
        self.sent_text.append((channel_id, text))
        return "om_text_1"


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
