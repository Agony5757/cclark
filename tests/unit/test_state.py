"""Tests for state module: channel streaming and toolbar state."""

from __future__ import annotations


from cclark.state import (
    ToolbarState,
    VerboseChannelState,
    VerboseTurnState,
    advance_turn_index,
    get_current_turn_index,
    get_toolbar_state,
    get_verbose_state,
    reset_channel_state,
)


class TestVerboseTurnState:
    def test_default_values(self) -> None:
        ts = VerboseTurnState()
        assert ts.last_turn_index == -1
        assert ts.pending_text == ""


class TestVerboseChannelState:
    def test_default_values(self) -> None:
        state = VerboseChannelState()
        assert state.streaming_card_id is None
        assert state.last_flush_ms == 0
        assert state.turn_states == {}

    def test_turn_state_creates_if_missing(self) -> None:
        state = VerboseChannelState()
        ts = state.turn_state("ou_user1")
        assert ts.last_turn_index == -1
        assert state.turn_states["ou_user1"] is ts

    def test_turn_state_returns_existing(self) -> None:
        state = VerboseChannelState()
        ts1 = state.turn_state("ou_user1")
        ts2 = state.turn_state("ou_user1")
        assert ts1 is ts2

    def test_to_dict_roundtrip(self) -> None:
        state = VerboseChannelState(
            streaming_card_id="om_card1",
            last_flush_ms=12345.0,
        )
        state.turn_state("ou_user1")
        state.turn_states["ou_user1"].last_turn_index = 5
        state.turn_states["ou_user1"].pending_text = "hello"

        data = state.to_dict()
        restored = VerboseChannelState.from_dict(data)

        assert restored.streaming_card_id == "om_card1"
        assert restored.last_flush_ms == 12345.0
        assert restored.turn_states["ou_user1"].last_turn_index == 5
        assert restored.turn_states["ou_user1"].pending_text == "hello"

    def test_from_dict_missing_keys_use_defaults(self) -> None:
        data: dict = {"streaming_card_id": None, "last_flush_ms": 0, "turn_states": {}}
        state = VerboseChannelState.from_dict(data)
        assert state.streaming_card_id is None
        assert state.turn_states == {}


class TestToolbarState:
    def test_default_values(self) -> None:
        ts = ToolbarState()
        assert ts.toolbar_card_id is None
        assert ts.toolbar_window_id is None


class TestGlobalStateFunctions:
    def test_get_verbose_state_creates_and_caches(self) -> None:
        s1 = get_verbose_state("feishu:oc_chat1")
        s2 = get_verbose_state("feishu:oc_chat1")
        assert s1 is s2

    def test_get_verbose_state_separate_channels(self) -> None:
        s1 = get_verbose_state("feishu:oc_chat1")
        s2 = get_verbose_state("feishu:oc_chat2")
        assert s1 is not s2

    def test_get_toolbar_state_creates_and_caches(self) -> None:
        t1 = get_toolbar_state("feishu:oc_chat1")
        t2 = get_toolbar_state("feishu:oc_chat1")
        assert t1 is t2

    def test_reset_channel_state_clears_both(self) -> None:
        vs = get_verbose_state("feishu:oc_chat1")
        ts = get_toolbar_state("feishu:oc_chat1")
        vs.streaming_card_id = "om_card1"
        ts.toolbar_card_id = "om_toolbar"

        reset_channel_state("feishu:oc_chat1")

        # After reset, getting state returns fresh instances
        vs_new = get_verbose_state("feishu:oc_chat1")
        ts_new = get_toolbar_state("feishu:oc_chat1")
        assert vs_new.streaming_card_id is None
        assert ts_new.toolbar_card_id is None
        # But different channels are unaffected
        assert vs is not vs_new

    def test_reset_channel_state_idempotent(self) -> None:
        # Resetting a non-existent channel should not raise
        reset_channel_state("feishu:unknown")

    def test_channel_turn_index_defaults_to_zero(self) -> None:
        reset_channel_state("feishu:turn-default")
        assert get_current_turn_index("feishu:turn-default") == 0

    def test_advance_turn_index_is_channel_scoped(self) -> None:
        reset_channel_state("feishu:turn-a")
        reset_channel_state("feishu:turn-b")

        assert advance_turn_index("feishu:turn-a") == 0
        assert advance_turn_index("feishu:turn-a") == 1
        assert get_current_turn_index("feishu:turn-a") == 1
        assert get_current_turn_index("feishu:turn-b") == 0

    def test_advance_turn_index_resets_thinking_card(self) -> None:
        reset_channel_state("feishu:thinking-turn")
        state = get_verbose_state("feishu:thinking-turn")
        state.streaming_thinking_card_id = "om_old_thinking"

        assert advance_turn_index("feishu:thinking-turn") == 0

        assert state.streaming_thinking_card_id is None
