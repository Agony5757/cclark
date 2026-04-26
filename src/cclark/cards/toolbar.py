"""Toolbar card builder — renders per-provider action grids as Feishu cards."""

from __future__ import annotations

import json
from typing import Any

from cclark.toolbar_config import ToolbarConfig, ToolbarAction


def build_toolbar_card(
    window_id: str,
    provider: str,
    toolbar_config: ToolbarConfig,
    status_label: str = "",
) -> str:
    """Build a toolbar card for a provider + window."""
    layout = toolbar_config.for_provider(provider)
    rows: list[list[dict[str, Any]]] = []

    for row_names in layout.buttons:
        row: list[dict[str, Any]] = []
        for name in row_names:
            action = toolbar_config.actions.get(name)
            if action is None:
                continue
            btn = _build_button(action, window_id, layout.style)
            row.append(btn)
        if row:
            rows.append(row)

    elements: list[dict[str, Any]] = []

    if status_label:
        elements.append({
            "tag": "markdown",
            "content": f"<strong>Window</strong>: <code>{_esc(window_id)}</code> "
                       f"&nbsp;&nbsp;<strong>Status</strong>: {status_label}",
        })

    for row_buttons in rows:
        elements.append({"tag": "action", "children": row_buttons})

    return json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"Toolbar — {provider}"},
            "template": "indigo",
        },
        "elements": elements,
    })


def _build_button(
    action: ToolbarAction,
    window_id: str,
    style: str,
) -> dict[str, Any]:
    label = action.render(style)  # type: ignore
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "action_type": "interactive",
        "value": {"action": f"tb:{window_id}:{action.name}"},
    }


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
