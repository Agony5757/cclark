from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


def test_split_messages_keeps_tool_result_markers_as_regular() -> None:
    tool_result_marker = "\x02EXPQUOTE_START\x02modified 3 files\x02EXPQUOTE_END\x02"
    messages = [
        SimpleNamespace(
            text=tool_result_marker,
            content_type="tool_result",
            role="assistant",
        ),
        SimpleNamespace(text="done", content_type="tool_result", role="assistant"),
    ]

    thinking, regular = _split_messages(messages)

    assert not thinking
    assert [m.text for m in regular] == [tool_result_marker, "done"]


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


# ── Simulated on_message call sequences ─────────────────────────────────────────


async def _fake_on_message(
    channel_id: str,
    thinking_text: str | None,
    regular_text: str | None,
    thinking_complete: bool = False,
    provider: str = "claude",
) -> None:
    """Simulate one on_message delivery: thinking + regular in separate dispatch calls."""
    from types import SimpleNamespace
    from cclark.main import _dispatch_channel_messages
    from unittest.mock import MagicMock

    gateway = MagicMock()
    window_id = "@99"
    gateway.channel_router.resolve_window.return_value = window_id

    if thinking_text is not None:
        thinking_msgs = [
            SimpleNamespace(text=thinking_text, role="assistant", content_type="thinking")
        ]
        await _dispatch_channel_messages(channel_id, thinking_msgs, "sess", gateway)

    if regular_text is not None:
        regular_msgs = [
            SimpleNamespace(text=regular_text, role="assistant", content_type="text")
        ]
        await _dispatch_channel_messages(channel_id, regular_msgs, "sess", gateway)


@pytest.mark.asyncio
async def test_multiple_onmessage_same_turn_produces_one_output_card() -> None:
    """Multiple on_message calls in the same turn must produce exactly one output card.

    Regression test for the bug where each on_message call created a fresh
    VerboseCardStreamer (turn_index=-1), causing every call to flush and
    send a NEW card instead of patching the existing one.
    """
    channel_id = "feishu:oc_multi_call:"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = True
    advance_turn_index(channel_id)

    adapter = _FakeAdapter()

    # Simulate three separate on_message deliveries in the same turn
    # by calling _send_regular_verbose_card three times (each creates a fresh
    # VerboseCardStreamer, exactly as the real on_message dispatch does).
    from cclark.main import _send_regular_verbose_card
    from types import SimpleNamespace

    for text in ["chunk one", "chunk two", "chunk three"]:
        await _send_regular_verbose_card(
            adapter,
            channel_id,
            [SimpleNamespace(text=text, role="assistant", content_type="text")],
            provider="claude",
        )

    # Exactly ONE output card should have been created
    assert len(adapter._client.sent_cards) == 1
    # Two patches: second and third chunks patch the card created by the first
    assert len(adapter._client.patched_cards) == 2


@pytest.mark.asyncio
async def test_new_streamer_reads_turn_index_from_state_same_turn() -> None:
    """A new VerboseCardStreamer must read turn_index from shared state.

    This is the core fix: VerboseCardStreamer.__init__ now initializes
    _turn_index from state.turn_state(user_id).last_turn_index instead of -1.
    This means a new streamer in the same turn sees turn_index=N (not -1),
    so push(turn_index=N) does NOT trigger an immediate flush.
    """
    channel_id = "feishu:oc_new_streamer:"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = True
    # advance_turn_index: last_turn_index goes from -1 (initial) to 0
    advance_turn_index(channel_id)

    from cclark.cards.streaming import VerboseCardStreamer

    class _FakeClient:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.patched: list[str] = []

        async def send_interactive_card(self, chat_id: str, card: str) -> str:
            self.sent.append(card)
            return f"om_{len(self.sent)}"

        async def patch_message(self, msg_id: str, card: str) -> None:
            self.patched.append(msg_id)

    fc = _FakeClient()

    # VerboseCardStreamer takes the FeishuClient directly (adapter._client)
    # First streamer: push text, flush → creates card
    streamer1 = VerboseCardStreamer(fc, channel_id, "__channel__", "claude")
    # After fix: _turn_index = state.turn_state(_CHANNEL_TURN_KEY).last_turn_index = 0
    assert streamer1._turn_index == 0, (
        "Streamer must read turn_index from state (0), not default to -1"
    )
    await streamer1.push("first", turn_index=0)
    await streamer1.flush()

    assert len(fc.sent) == 1, "First streamer must create a card"
    # send_interactive_card returns "om_1", not the card JSON
    card_id = "om_1"

    # Second streamer (simulating a new on_message call): turn_index should also be 0
    streamer2 = VerboseCardStreamer(fc, channel_id, "__channel__", "claude")
    assert streamer2._turn_index == 0, (
        "New streamer in same turn must also read turn_index=0 from state"
    )

    # push with same turn_index → no flush (turn_index unchanged), accumulates
    await streamer2.push("second", turn_index=0)
    await streamer2.flush()

    # Only ONE card should have been created; second streamer patched it
    assert len(fc.sent) == 1, f"Only one card should be created, got {len(fc.sent)}"
    assert card_id in fc.patched, (
        f"Card {card_id} should be patched by second streamer, patched: {fc.patched}"
    )


@pytest.mark.asyncio
async def test_new_turn_creates_new_card() -> None:
    """advance_turn_index must create a fresh card for the new turn."""
    channel_id = "feishu:oc_new_turn_card:"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = True

    adapter = _FakeAdapter()
    from cclark.main import _send_regular_verbose_card
    from types import SimpleNamespace

    advance_turn_index(channel_id)
    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="turn 0", role="assistant", content_type="text")],
        provider="claude",
    )

    advance_turn_index(channel_id)
    await _send_regular_verbose_card(
        adapter,
        channel_id,
        [SimpleNamespace(text="turn 1", role="assistant", content_type="text")],
        provider="claude",
    )

    # Two cards: one per turn
    assert len(adapter._client.sent_cards) == 2
    assert adapter._client.patched_cards == []
