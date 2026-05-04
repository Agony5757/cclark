"""Tests for FeishuCardBuilder: markdown conversion, truncation, and card building."""

from __future__ import annotations

import json


from cclark.cards.builder import FeishuCardBuilder

# Minimal CardPayload / InteractivePrompt stubs to avoid importing unified-icc
from unittest.mock import MagicMock


def make_card(
    title: str = "Test Card",
    body: str = "",
    fields: dict | None = None,
    actions: list | None = None,
    color: str = "blue",
) -> MagicMock:
    c = MagicMock()
    c.title = title
    c.body = body
    c.fields = fields or {}
    c.actions = actions or []
    c.color = color
    return c


def make_prompt(
    title: str = "Are you sure?",
    options: list | None = None,
    cancel_text: str = "Cancel",
    prompt_type: str = "shell_approval",
) -> MagicMock:
    p = MagicMock()
    p.title = title
    p.options = options or []
    p.cancel_text = cancel_text
    p.prompt_type = prompt_type
    return p


class TestMarkdownConversion:
    def test_bold_conversion(self) -> None:
        result = FeishuCardBuilder._md("Hello **world**")
        assert "<strong>world</strong>" in result

    def test_inline_code_conversion(self) -> None:
        result = FeishuCardBuilder._md("Use `ls -la`")
        assert "<code>ls -la</code>" in result

    def test_html_escape(self) -> None:
        result = FeishuCardBuilder._md("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_ampersand_escape(self) -> None:
        result = FeishuCardBuilder._md("foo & bar")
        assert "&amp;" in result

    def test_fenced_code_block_preserved(self) -> None:
        text = "result:\n\n```text\nhello-codex\n```"
        result = FeishuCardBuilder._md(text)
        assert "<pre lang=\"text\">hello-codex</pre>" in result
        assert "<code>" not in result

    def test_fenced_code_block_without_language(self) -> None:
        text = "```\nvar x = 1;\n```"
        result = FeishuCardBuilder._md(text)
        assert "<pre>var x = 1;</pre>" in result

    def test_code_block_with_inline_code(self) -> None:
        text = "use `npm` to install:\n\n```bash\nnpm install\n```"
        result = FeishuCardBuilder._md(text)
        assert "<code>npm</code>" in result
        assert "<pre lang=\"bash\">npm install</pre>" in result


class TestCodeTruncation:
    def test_under_limit_unchanged(self) -> None:
        text = "x" * 100
        assert FeishuCardBuilder._truncate_code(text) == text

    def test_over_limit_truncates_and_annotates(self) -> None:
        from cclark.cards.builder import _MAX_CODE_BLOCK

        text = "x" * 3000
        result = FeishuCardBuilder._truncate_code(text)
        assert result.endswith("(truncated 1000 chars)")
        suffix = f"\n... (truncated {len(text) - _MAX_CODE_BLOCK} chars)"
        assert len(result) == _MAX_CODE_BLOCK + len(suffix)

    def test_exactly_at_limit_unchanged(self) -> None:
        text = "x" * 2000
        assert FeishuCardBuilder._truncate_code(text) == text


class TestBuildCard:
    def test_empty_card_has_header(self) -> None:
        card = make_card(title="My Card", body="")
        result = json.loads(FeishuCardBuilder.build_card(card))
        assert result["header"]["title"]["content"] == "My Card"
        assert result["header"]["template"] == "blue"

    def test_body_becomes_markdown_element(self) -> None:
        card = make_card(title="Card", body="Hello **world**")
        result = json.loads(FeishuCardBuilder.build_card(card))
        elements = result["elements"]
        md_elements = [e for e in elements if e["tag"] == "markdown"]
        assert any("<strong>world</strong>" in e["content"] for e in md_elements)

    def test_fields_become_markdown_table(self) -> None:
        card = make_card(title="Card", body="", fields={"Key": "Value"})
        result = json.loads(FeishuCardBuilder.build_card(card))
        elements = result["elements"]
        md_elements = [e for e in elements if e["tag"] == "markdown"]
        assert any("<strong>Key</strong>" in e["content"] for e in md_elements)
        assert any("Value" in e["content"] for e in md_elements)

    def test_actions_become_buttons(self) -> None:
        card = make_card(
            title="Card",
            actions=[
                {"label": "Approve", "action": "sh:run:ls"},
                {"label": "Deny", "action": None},
            ],
        )
        result = json.loads(FeishuCardBuilder.build_card(card))
        buttons = result["elements"][0]["children"]
        assert len(buttons) == 2
        assert buttons[0]["text"]["content"] == "Approve"
        assert buttons[0]["action_type"] == "interactive"
        assert buttons[1]["action_type"] == "default"

    def test_color_header_mapping(self) -> None:
        card = make_card(title="Card", body="", color="green")
        result = json.loads(FeishuCardBuilder.build_card(card))
        assert result["header"]["template"] == "green"

    def test_unknown_color_defaults_to_blue(self) -> None:
        card = make_card(title="Card", body="", color="notacolor")
        result = json.loads(FeishuCardBuilder.build_card(card))
        assert result["header"]["template"] == "blue"


class TestBuildPromptCard:
    def test_title_becomes_markdown(self) -> None:
        prompt = make_prompt(title="Run `rm -rf /`?")
        result = json.loads(FeishuCardBuilder.build_prompt_card(prompt))
        elements = result["elements"]
        assert any("<code>rm -rf /</code>" in e["content"] for e in elements if e["tag"] == "markdown")

    def test_options_become_buttons(self) -> None:
        prompt = make_prompt(
            title="Continue?",
            options=[{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
        )
        result = json.loads(FeishuCardBuilder.build_prompt_card(prompt))
        buttons = result["elements"][1]["children"]
        assert len(buttons) == 3  # 2 options + cancel

    def test_cancel_button_action_is_cancel(self) -> None:
        prompt = make_prompt(title="Continue?", options=[{"label": "Go", "value": "go"}], cancel_text="Abort")
        result = json.loads(FeishuCardBuilder.build_prompt_card(prompt))
        buttons = result["elements"][1]["children"]
        cancel_btn = next(b for b in buttons if b["text"]["content"] == "Abort")
        assert cancel_btn["value"]["action"] == "cancel"

    def test_wide_screen_mode_enabled(self) -> None:
        prompt = make_prompt(title="?", options=[])
        result = json.loads(FeishuCardBuilder.build_prompt_card(prompt))
        assert result["config"]["wide_screen_mode"] is True

    def test_json_string_returned(self) -> None:
        prompt = make_prompt(title="?", options=[])
        result = FeishuCardBuilder.build_prompt_card(prompt)
        # Should be valid JSON when re-parsed
        parsed = json.loads(result)
        assert "elements" in parsed
