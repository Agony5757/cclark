"""Status card builder — renders session / window status as Feishu cards."""

from __future__ import annotations

import json
from typing import Any


def build_status_card(
    title: str,
    window_id: str,
    provider: str,
    status: str,
    working_dir: str = "",
    last_seen: str = "",
    actions: list[dict[str, str]] | None = None,
) -> str:
    """Build a Feishu card showing session/window status."""
    fields: list[dict[str, str]] = [
        {"field": "Provider", "value": provider},
        {"field": "Status", "value": status},
    ]
    if working_dir:
        fields.append({"field": "Dir", "value": working_dir})
    if last_seen:
        fields.append({"field": "Last seen", "value": last_seen})
    fields.append({"field": "Window", "value": window_id})

    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": _build_fields_md(fields),
        }
    ]

    if actions:
        buttons: list[dict[str, Any]] = []
        for action in actions:
            btn: dict[str, Any] = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": action.get("label", "Button")},
                "action_type": "interactive",
                "value": {"action": action["action"]},
            }
            buttons.append(btn)
        elements.append({"tag": "action", "children": buttons})

    return json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "turquoise",
        },
        "elements": elements,
    })


def _build_fields_md(fields: list[dict[str, str]]) -> str:
    lines = []
    for f in fields:
        lines.append(f"<strong>{_esc(f['field'])}</strong>: {_esc(f['value'])}")
    return "<br>".join(lines)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
