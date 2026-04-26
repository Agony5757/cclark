"""Tests for callback_registry: longest-prefix dispatch and authorization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cclark.callback_registry import (
    CallbackContext,
    _find_handler,
    _registry,
    dispatch,
    register,
)


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear the registry before and after each test."""
    _registry.clear()
    yield
    _registry.clear()


@pytest.fixture
def ctx() -> CallbackContext:
    return CallbackContext(
        user_id="ou_testuser1",
        chat_id="oc_chat1",
        thread_id="oc_thread1",
        value="db:sel:/some/path",
        message_id="om_card1",
        token="test_token",
        channel_id="feishu:oc_chat1:oc_thread1",
    )


class TestRegister:
    def test_register_single_prefix(self) -> None:
        handler = AsyncMock()

        @register("db:sel:")
        async def handle(_: CallbackContext) -> None:
            await handler()

        assert _registry["db:sel:"] is handle

    def test_register_multiple_prefixes(self) -> None:
        handler = AsyncMock()

        @register("prov:claude", "prov:codex", "prov:gemini")
        async def handle(_: CallbackContext) -> None:
            pass

        assert _registry["prov:claude"] is handle
        assert _registry["prov:codex"] is handle
        assert _registry["prov:gemini"] is handle

    def test_duplicate_prefix_raises(self) -> None:
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        @register("db:sel:")
        async def h1(_: CallbackContext) -> None:
            await handler1()

        with pytest.raises(ValueError, match="already registered"):
            @register("db:sel:")
            async def h2(_: CallbackContext) -> None:
                await handler2()


class TestFindHandler:
    def test_exact_match(self) -> None:
        handler = AsyncMock()
        _registry["db:sel:"] = handler
        result = _find_handler("db:sel:/path")
        assert result is handler

    def test_longest_prefix_wins(self) -> None:
        general = AsyncMock()
        specific = AsyncMock()
        _registry["session:send"] = general
        _registry["session:send:approve"] = specific
        assert _find_handler("session:send:approve:123") is specific

    def test_no_match_returns_none(self) -> None:
        _registry["prov:claude"] = AsyncMock()
        assert _find_handler("unrelated:value") is None

    def test_empty_registry_returns_none(self) -> None:
        assert _find_handler("anything") is None


class TestCallbackContext:
    def test_prefix_property_returns_longest_match(self) -> None:
        _registry["session:send:approve"] = AsyncMock()
        _registry["session:send"] = AsyncMock()

        ctx = CallbackContext(
            user_id="ou_u",
            chat_id="oc_c",
            thread_id="",
            value="session:send:approve:extra",
            message_id="om_1",
            token="t",
            channel_id="feishu:oc_c",
        )
        assert ctx.prefix == "session:send:approve"

    def test_prefix_property_falls_back_to_first_segment(self) -> None:
        ctx = CallbackContext(
            user_id="ou_u",
            chat_id="oc_c",
            thread_id="",
            value="noop",
            message_id="om_1",
            token="t",
            channel_id="feishu:oc_c",
        )
        assert ctx.prefix == "noop:"


class TestDispatch:
    @pytest.mark.asyncio
    async def test_unauthorized_user_skipped(self, ctx: CallbackContext, mock_config: MagicMock) -> None:
        ctx.user_id = "ou_unknown_user"
        handler = AsyncMock()
        _registry["db:sel:"] = handler

        await dispatch(ctx)
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorized_user_routed(self, ctx: CallbackContext, mock_config: MagicMock) -> None:
        handler = AsyncMock()
        _registry["db:sel:"] = handler

        await dispatch(ctx)
        handler.assert_awaited_once_with(ctx)

    @pytest.mark.asyncio
    async def test_no_handler_no_error(self, ctx: CallbackContext, mock_config: MagicMock) -> None:
        # No prefixes registered — dispatch should not raise
        await dispatch(ctx)
