"""Longest-prefix callback dispatch for Feishu card button clicks.

Provides self-registration via ``register()`` decorator and longest-prefix
match routing to the appropriate handler. Authorization and channel routing
are handled once here rather than in individual handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from .config import config

logger = structlog.get_logger()

# Handler receives parsed callback context, returns None
type CallbackHandler = Callable[["CallbackContext"], Awaitable[None]]

_registry: dict[str, CallbackHandler] = {}


def register(
    *prefixes: str,
) -> Callable[[CallbackHandler], CallbackHandler]:
    """Register a callback handler for given prefix strings.

    Usage::

        @register("db:sel:", "db:up")
        async def handle_dir_browser(ctx: CallbackContext) -> None:
            ...
    """

    def decorator(func: CallbackHandler) -> CallbackHandler:
        for prefix in prefixes:
            if prefix in _registry:
                raise ValueError(
                    f"Callback prefix {prefix!r} already registered "
                    f"(existing: {_registry[prefix].__qualname__}, "
                    f"new: {func.__qualname__})"
                )
            _registry[prefix] = func
        return func

    return decorator


@dataclass
class CallbackContext:
    """Parsed callback payload shared across all handlers."""

    user_id: str
    """Feishu open_id of the user who clicked."""
    chat_id: str
    """Feishu chat_id the callback originated from."""
    thread_id: str
    """Feishu thread_id (may be empty for non-threaded chats)."""
    value: str
    """Raw action value from the card button."""
    message_id: str
    """Feishu message_id of the card that was clicked."""
    token: str
    """Feishu callback verification token."""
    channel_id: str
    """Derived: feishu:{chat_id}[:{thread_id}]."""

    @property
    def prefix(self) -> str:
        """Shortest registered prefix that matches self.value (for logging)."""
        for prefix in sorted(_registry, key=len, reverse=True):
            if self.value.startswith(prefix):
                return prefix
        return self.value.split(":")[0] + ":"


async def dispatch(ctx: CallbackContext) -> None:
    """Route a callback to the longest-prefix-matched handler.

    Authorization is checked once here before dispatch.
    """
    if not config.is_user_allowed(ctx.user_id):
        logger.warning("Unauthorized callback from user_id=%s", ctx.user_id)
        return

    handler = _find_handler(ctx.value)
    if handler is not None:
        logger.debug(
            "Dispatching callback prefix=%r user=%s channel=%s",
            ctx.prefix,
            ctx.user_id,
            ctx.channel_id,
        )
        await handler(ctx)
    else:
        logger.debug("No handler for callback value=%r", ctx.value)


def _find_handler(value: str) -> CallbackHandler | None:
    """Find the handler for the longest matching prefix."""
    best_handler: CallbackHandler | None = None
    best_len = 0
    for prefix, handler in _registry.items():
        if value.startswith(prefix) and len(prefix) > best_len:
            best_handler = handler
            best_len = len(prefix)
    return best_handler


def load_handlers() -> None:
    """Import handler modules to trigger @register decorators."""
    from .handlers import (  # noqa: F401
        callback,
        message,
        session_creation,
        screenshot,
        toolbar,
    )
