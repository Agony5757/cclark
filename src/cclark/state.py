"""Per-channel streaming state for the VerboseCardStreamer.

Stores one VerboseChannelState per channel, tracking:
- The active streaming card (message_id)
- Pending uncommitted text segments
- Last flush timestamp
- Per-window last-seen turn index (for dedup)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerboseTurnState:
    """Streaming state for a single agent turn within a channel."""

    last_turn_index: int = -1
    """Highest turn_index this user has already seen."""
    pending_text: str = ""
    """Text accumulated since the last flush."""


@dataclass
class VerboseChannelState:
    """Per-channel streaming state — one per feishu channel."""

    streaming_card_id: str | None = None
    """Feishu message_id of the streaming card for the current turn."""
    last_flush_ms: float = 0
    """Monotonic timestamp (ms) of the last flush."""
    turn_states: dict[str, VerboseTurnState] = field(default_factory=dict)
    """Per-user-id or per-window-id turn state. Key is user_id."""
    streaming_thinking_card_id: str | None = None
    """Feishu message_id of the in-progress thinking card."""
    streaming_thinking_text: str = ""
    """Latest visible thinking text for the in-progress thinking card."""
    streaming_thinking_active: bool = False
    """Whether the current turn still has an active thinking stream."""
    _verbose_enabled: bool = False
    """Per-channel verbose mode. Defaults to False (thinking hidden)."""

    def turn_state(self, user_id: str) -> VerboseTurnState:
        return self.turn_states.setdefault(user_id, VerboseTurnState())

    def to_dict(self) -> dict[str, Any]:
        return {
            "streaming_card_id": self.streaming_card_id,
            "last_flush_ms": self.last_flush_ms,
            "turn_states": {
                uid: {
                    "last_turn_index": ts.last_turn_index,
                    "pending_text": ts.pending_text,
                }
                for uid, ts in self.turn_states.items()
            },
            "streaming_thinking_card_id": self.streaming_thinking_card_id,
            "streaming_thinking_text": self.streaming_thinking_text,
            "streaming_thinking_active": self.streaming_thinking_active,
            "_verbose_enabled": self._verbose_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerboseChannelState:
        state = cls(
            streaming_card_id=data.get("streaming_card_id"),
            last_flush_ms=data.get("last_flush_ms", 0),
            streaming_thinking_card_id=data.get("streaming_thinking_card_id"),
            streaming_thinking_text=data.get("streaming_thinking_text", ""),
            streaming_thinking_active=data.get("streaming_thinking_active", False),
            _verbose_enabled=data.get("_verbose_enabled", False),
        )
        for uid, ts_data in data.get("turn_states", {}).items():
            state.turn_states[uid] = VerboseTurnState(
                last_turn_index=ts_data.get("last_turn_index", -1),
                pending_text=ts_data.get("pending_text", ""),
            )
        return state


@dataclass
class ToolbarState:
    """State tracked per channel for toolbar card management."""

    toolbar_card_id: str | None = None
    """Feishu message_id of the currently displayed toolbar card."""
    toolbar_window_id: str | None = None
    """Window ID the toolbar is attached to (for stale detection)."""


# Global registry: channel_id → VerboseChannelState
_verbose_states: dict[str, VerboseChannelState] = {}
_toolbar_states: dict[str, ToolbarState] = {}
_CHANNEL_TURN_KEY = "__channel_turn__"


def get_verbose_state(channel_id: str) -> VerboseChannelState:
    """Get (or create) the verbose/streaming state for a channel."""
    return _verbose_states.setdefault(channel_id, VerboseChannelState())


def get_toolbar_state(channel_id: str) -> ToolbarState:
    """Get (or create) the toolbar state for a channel."""
    return _toolbar_states.setdefault(channel_id, ToolbarState())


def get_current_turn_index(channel_id: str) -> int:
    """Return the current channel-level turn index."""
    ts = get_verbose_state(channel_id).turn_state(_CHANNEL_TURN_KEY)
    return max(ts.last_turn_index, 0)


def advance_turn_index(channel_id: str) -> int:
    """Advance and return the next channel-level turn index."""
    state = get_verbose_state(channel_id)
    state.streaming_card_id = None
    state.streaming_thinking_card_id = None
    state.streaming_thinking_text = ""
    state.streaming_thinking_active = False
    state.last_flush_ms = 0
    ts = state.turn_state(_CHANNEL_TURN_KEY)
    ts.last_turn_index += 1
    return ts.last_turn_index


def reset_channel_state(channel_id: str) -> None:
    """Clear all cached state for a channel. Used after unbind."""
    _verbose_states.pop(channel_id, None)
    _toolbar_states.pop(channel_id, None)


def reset_channel_state_keep_verbose(channel_id: str) -> None:
    """Reset toolbar and streaming card state but keep _verbose_enabled."""
    vs = _verbose_states.get(channel_id)
    if vs is not None:
        vs.streaming_card_id = None
        vs.streaming_thinking_card_id = None
        vs.streaming_thinking_text = ""
        vs.streaming_thinking_active = False
        vs.last_flush_ms = 0
        vs.turn_states.clear()
    _toolbar_states.pop(channel_id, None)
