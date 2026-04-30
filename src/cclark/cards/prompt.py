"""Prompt card builder — permission/question/selection prompts as Feishu cards."""

from __future__ import annotations

import json
from typing import Any

from unified_icc.adapter import InteractivePrompt
from cclark.cards.builder import FeishuCardBuilder


def build_permission_card(
    title: str,
    body: str,
    options: list[dict[str, str]] | None = None,
    cancel_text: str = "Cancel",
) -> str:
    """Build a Feishu interactive card for a permission/approval request.

    Args:
        title: Card header title.
        body: Markdown body describing the permission being requested.
        options: Optional custom approve/deny button list; defaults to standard pair.
        cancel_text: Label for the cancel button (default "Cancel").
    Returns:
        Serialized JSON string.
    """
    prompt = InteractivePrompt(
        prompt_type="permission",
        title=title,
        options=options or [{"label": "Approve", "value": "approve"}, {"label": "Deny", "value": "deny"}],
        cancel_text=cancel_text,
    )
    # Override body
    card = _prompt_to_card(prompt)
    card["elements"].insert(0, {
        "tag": "markdown",
        "content": FeishuCardBuilder._md(body),
    })
    card["header"] = {
        "title": {"tag": "plain_text", "content": title},
        "template": "orange",
    }
    return json.dumps(card)


def build_question_card(
    title: str,
    question: str,
    options: list[dict[str, str]],
    cancel_text: str = "Cancel",
) -> str:
    """Build a Feishu interactive card for a multi-choice question prompt.

    Args:
        title: Card header title.
        question: Markdown body with the question text.
        options: List of {label, value} dicts for each choice button.
        cancel_text: Label for the cancel button.
    Returns:
        Serialized JSON string.
    """
    prompt = InteractivePrompt(
        prompt_type="question",
        title=title,
        options=options,
        cancel_text=cancel_text,
    )
    card = _prompt_to_card(prompt)
    card["elements"].insert(0, {
        "tag": "markdown",
        "content": FeishuCardBuilder._md(question),
    })
    card["header"] = {
        "title": {"tag": "plain_text", "content": title},
        "template": "wathet",
    }
    return json.dumps(card)


def _prompt_to_card(prompt: InteractivePrompt) -> dict[str, Any]:
    """Build the internal card dict (without header) from an InteractivePrompt."""
    buttons: list[dict[str, Any]] = []
    for option in prompt.options:
        value = f"prompt:{prompt.prompt_type}:{option['value']}"
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": option.get("label", "Option")},
            "action_type": "interactive",
            "value": {"action": value},
        })

    if prompt.cancel_text:
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": prompt.cancel_text},
            "action_type": "interactive",
            "value": {"action": "cancel"},
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Prompt"}, "template": "wathet"},
        "elements": [{"tag": "action", "children": buttons}],
    }
