"""Toolbar layout configuration — per-provider button grids loaded from TOML.

Verbatim copy from ccgram/toolbar_config.py, adapted for Feishu (no Telegram
specifics — purely data + loader). See the upstream module for full docs.
"""

from __future__ import annotations

import structlog
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = structlog.get_logger()

ButtonStyle = Literal["emoji", "text", "emoji_text"]
ActionType = Literal["key", "text", "builtin"]

_VALID_STYLES: frozenset[str] = frozenset({"emoji", "text", "emoji_text"})
_VALID_TYPES: frozenset[str] = frozenset({"key", "text", "builtin"})
_MAX_NAME_LEN = 24


@dataclass(frozen=True, slots=True)
class ToolbarAction:
    name: str
    emoji: str
    text: str
    action_type: ActionType
    payload: str
    literal: bool = False
    read_state: bool = False

    def render(self, style: ButtonStyle) -> str:
        if style == "emoji":
            return self.emoji
        if style == "text":
            return self.text
        return f"{self.emoji} {self.text}"


@dataclass(frozen=True, slots=True)
class ToolbarLayout:
    style: ButtonStyle
    buttons: tuple[tuple[str, ...], ...]


def _b(
    name: str,
    emoji: str,
    text: str,
    action_type: ActionType,
    payload: str,
    *,
    literal: bool = False,
    read_state: bool = False,
) -> ToolbarAction:
    return ToolbarAction(
        name=name, emoji=emoji, text=text,
        action_type=action_type, payload=payload,
        literal=literal, read_state=read_state,
    )


BUILTIN_ACTIONS: dict[str, ToolbarAction] = {
    a.name: a
    for a in (
        _b("screen", "\U0001f4f7", "Screen", "builtin", "screenshot"),
        _b("ctrlc", "⏹", "Ctrl-C", "builtin", "ctrlc"),
        _b("live", "\U0001f4fa", "Live", "builtin", "live"),
        _b("send", "\U0001f4e4", "Send", "builtin", "send"),
        _b("close", "✖", "Close", "builtin", "dismiss"),
        _b("mode", "\U0001f500", "Mode", "key", "\x1b[Z", literal=True, read_state=True),
        _b("think", "\U0001f4ad", "Think", "key", "M-t"),
        _b("yolo", "\U0001f1fe", "YOLO", "key", "C-y", read_state=True),
        _b("esc", "⎋", "Esc", "key", "Escape"),
        _b("enter", "⏎", "Enter", "key", "Enter"),
        _b("tab", "⇥", "Tab", "key", "Tab"),
        _b("eof", "^D", "EOF", "key", "C-d"),
        _b("susp", "^Z", "Susp", "key", "C-z"),
    )
}

DEFAULT_LAYOUTS: dict[str, ToolbarLayout] = {
    "claude": ToolbarLayout(
        style="emoji_text",
        buttons=(("screen", "ctrlc", "live"), ("mode", "think", "esc"), ("send", "enter", "close")),
    ),
    "codex": ToolbarLayout(
        style="emoji_text",
        buttons=(("screen", "ctrlc", "live"), ("esc", "enter", "tab"), ("send", "mode", "close")),
    ),
    "gemini": ToolbarLayout(
        style="emoji_text",
        buttons=(("screen", "ctrlc", "live"), ("mode", "yolo", "esc"), ("send", "enter", "close")),
    ),
    "pi": ToolbarLayout(
        style="emoji_text",
        buttons=(("screen", "ctrlc", "live"), ("esc", "enter", "tab"), ("send", "close")),
    ),
    "shell": ToolbarLayout(
        style="emoji_text",
        buttons=(("screen", "ctrlc", "live"), ("enter", "eof", "susp"), ("send", "esc", "close")),
    ),
}


@dataclass
class ToolbarConfig:
    layouts: dict[str, ToolbarLayout] = field(default_factory=dict)
    actions: dict[str, ToolbarAction] = field(default_factory=dict)

    def for_provider(self, provider_name: str) -> ToolbarLayout:
        return self.layouts.get(provider_name) or self.layouts["claude"]


def _parse_action(name: str, raw: object) -> ToolbarAction | None:
    if not isinstance(name, str) or not name:
        return None
    if len(name) > _MAX_NAME_LEN:
        return None
    if not isinstance(raw, dict):
        return None
    emoji = str(raw.get("emoji", "")).strip()
    text = str(raw.get("text", "")).strip()
    action_type = str(raw.get("type", "")).strip()
    payload = str(raw.get("payload", "")).strip()
    if not (emoji or text):
        return None
    if action_type not in _VALID_TYPES:
        return None
    if action_type == "builtin":
        return None
    if not payload:
        return None
    return ToolbarAction(
        name=name,
        emoji=emoji or text,
        text=text or name,
        action_type=action_type,  # type: ignore[arg-type]
        payload=payload,
        literal=bool(raw.get("literal", False)),
        read_state=bool(raw.get("read_state", False)),
    )


def load_toolbar_config(path: str | Path | None = None) -> ToolbarConfig:  # noqa: C901
    cfg = ToolbarConfig(
        layouts=dict(DEFAULT_LAYOUTS),
        actions=dict(BUILTIN_ACTIONS),
    )
    if not path:
        return cfg
    toml_path = Path(path).expanduser()
    if not toml_path.exists():
        return cfg
    try:
        with toml_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, Exception):  # noqa: BLE001
        return cfg
    if not isinstance(raw, dict):
        return cfg
    # Merge user actions
    for name, raw_action in raw.get("actions", {}).items():
        action = _parse_action(name, raw_action)
        if action is not None:
            cfg.actions[name] = action
    # Merge provider layouts
    for provider, raw_layout in raw.get("providers", {}).items():
        if isinstance(raw_layout, dict):
            style = raw_layout.get("style", "emoji_text")
            if style not in _VALID_STYLES:
                style = "emoji_text"
            buttons_raw = raw_layout.get("buttons", [])
            if isinstance(buttons_raw, list):
                rows = []
                for row in buttons_raw:
                    if isinstance(row, list):
                        cells = [str(c) for c in row if isinstance(c, str) and c in cfg.actions]
                        rows.append(tuple(cells))
                if rows:
                    cfg.layouts[provider] = ToolbarLayout(style=style, buttons=tuple(rows))
    return cfg
