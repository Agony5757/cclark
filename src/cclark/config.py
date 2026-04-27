"""Feishu-specific configuration — reads env vars and exposes a singleton.

Loads FEISHU_APP_ID, FEISHU_APP_SECRET, ALLOWED_USERS, and
webhook verification settings from environment variables (with .env support).

Key class: FeishuConfig (singleton instantiated as `config`).
"""

from __future__ import annotations

import os
import structlog
from pathlib import Path

from dotenv import load_dotenv

logger = structlog.get_logger()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class FeishuConfig:
    """Feishu bot configuration loaded from environment variables."""

    def __init__(self) -> None:
        self.config_dir = Path.home() / ".cclark"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        for env_path in (Path(".env"), self.config_dir / ".env"):
            if env_path.is_file():
                load_dotenv(env_path)
                logger.debug("Loaded env from %s", env_path.resolve())

        # Feishu credentials
        self.feishu_app_id = _env("FEISHU_APP_ID")
        if not self.feishu_app_id:
            raise ValueError("FEISHU_APP_ID environment variable is required")

        self.feishu_app_secret = _env("FEISHU_APP_SECRET")
        if not self.feishu_app_secret:
            raise ValueError("FEISHU_APP_SECRET environment variable is required")

        self.feishu_verification_token = _env("FEISHU_VERIFICATION_TOKEN", "")
        self.feishu_encrypt_key = _env("FEISHU_ENCRYPT_KEY", "")

        # Webhook settings
        self.webhook_port = int(_env("CCLARK_WEBHOOK_PORT", "8080"))
        self.webhook_path = _env("CCLARK_WEBHOOK_PATH", "/webhook/event")

        # Authorization
        # "all" (or empty) means allow everyone; otherwise a comma-separated list of open_ids
        allowed_users_str = _env("ALLOWED_USERS", "").strip().lower()
        if allowed_users_str in ("", "all"):
            self.allowed_users: set[str] | None = None  # None = allow all
        else:
            self.allowed_users = {
                uid.strip() for uid in allowed_users_str.split(",") if uid.strip()
            }

        # Bot user ID (to skip own messages)
        self.bot_user_id: str = _env("FEISHU_BOT_USER_ID", "")

        # Default provider
        self.default_provider = _env("CCLARK_PROVIDER", "claude")

        # Toolbar config path
        toolbar_path = _env("CCLARK_TOOLBAR_CONFIG", "").strip()
        if not toolbar_path:
            fallback = self.config_dir / "toolbar.toml"
            self.toolbar_config_path = str(fallback) if fallback.exists() else ""
        else:
            self.toolbar_config_path = toolbar_path

        allowed_label = "all" if self.allowed_users is None else f"{len(self.allowed_users)} users"
        logger.debug(
            "FeishuConfig initialized: app_id=%s..., allowed_users=%s, "
            "provider=%s",
            self.feishu_app_id[:8],
            allowed_label,
            self.default_provider,
        )

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if a Feishu user is in the allowed list.

        Returns True if allowed_users is None (no restriction) or
        if user_id is in the explicit allow list.
        """
        if self.allowed_users is None:
            return True
        return user_id in self.allowed_users

    def parse_channel_id(self, chat_id: str, thread_id: str = "") -> str:
        """Build a channel ID string from chat and thread IDs."""
        if thread_id:
            return f"feishu:{chat_id}:{thread_id}"
        return f"feishu:{chat_id}"

    def split_channel_id(self, channel_id: str) -> tuple[str, str]:
        """Parse a channel ID into (chat_id, thread_id)."""
        parts = channel_id.split(":", 2)
        if len(parts) == 3 and parts[0] == "feishu":  # noqa: PLR2004
            return parts[1], parts[2]
        elif len(parts) == 2 and parts[0] == "feishu":  # noqa: PLR2004
            return parts[1], ""
        raise ValueError(f"Invalid channel_id format: {channel_id!r}")


config = FeishuConfig()
