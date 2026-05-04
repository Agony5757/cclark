"""Feishu bot configuration — config.yaml first, falls back to .env.

~/.unified-icc/config.yaml format (multi-app):
  apps:
    - name: "default"
      app_id: "cli_xxx"
      app_secret: "xxx"
      allowed_users: "all"
      provider: "claude"
      tmux_session: "cclark"
      health_port: 8080   # HTTP health-check port for load-balancer probes

If config.yaml does not exist, falls back to FEISHU_APP_ID / FEISHU_APP_SECRET
env vars for single-app development mode.

Key class: FeishuConfig (singleton at module level as `config`).
"""

from __future__ import annotations

import os
import structlog
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = structlog.get_logger()

_CONFIG_DIR_ENV = "UNIFIED_ICC_DIR"
_DEFAULT_CONFIG_DIR = Path.home() / ".unified-icc"


@dataclass
class AppConfig:
    """Configuration for one Feishu app."""

    name: str
    app_id: str
    app_secret: str
    allowed_users: set[str] | None = None  # None = allow all
    provider: str = "claude"
    tmux_session: str = "cclark"
    health_port: int = 8080


class FeishuConfig:
    """Feishu bot configuration — supports multiple apps via config.yaml."""

    def __init__(self) -> None:
        self.config_dir = self._resolve_config_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Always load .env for local overrides
        for env_path in (Path(".env"), self.config_dir / ".env"):
            if env_path.is_file():
                load_dotenv(env_path)
                logger.debug("Loaded env from %s", env_path.resolve())

        # Try config.yaml first, then environment variables.
        yaml_path = self.config_dir / "config.yaml"
        self.apps: list[AppConfig] = []
        self._by_name: dict[str, AppConfig] = {}

        if yaml_path.is_file():
            self._load_yaml(yaml_path)
        else:
            self._load_from_env()

        if not self.apps:
            raise ValueError(
                "No Feishu app configured: create ~/.unified-icc/config.yaml or set "
                "FEISHU_APP_ID + FEISHU_APP_SECRET in .env"
            )

        self._default_app: AppConfig = self.apps[0]

        logger.info(
            "FeishuConfig initialized: %d app(s), default=%s",
            len(self.apps), self._default_app.name,
        )

    # ── YAML loading ─────────────────────────────────────────────────────────────

    def _resolve_config_dir(self) -> Path:
        """Return the primary configuration directory."""
        raw = os.getenv(_CONFIG_DIR_ENV, "")
        if raw:
            return Path(raw).expanduser()

        return _DEFAULT_CONFIG_DIR

    def _load_yaml(self, path: Path) -> None:
        """Parse config.yaml and populate self.apps with one AppConfig per entry."""
        import yaml  # type: ignore[import]

        with open(path) as f:
            raw = yaml.safe_load(f)

        self.unified_icc_ws_url = str(
            raw.get("unified_icc_ws_url", "ws://127.0.0.1:8900/api/v1/ws")
        )
        self.unified_icc_api_key = str(raw.get("unified_icc_api_key", ""))

        apps_list = raw.get("apps", [])
        if not isinstance(apps_list, list):
            raise ValueError("config.yaml: 'apps' must be a list")

        for item in apps_list:
            name = str(item.get("name", ""))
            if not name:
                logger.warning("Skipping app entry with no name in config.yaml")
                continue

            allowed_raw = str(item.get("allowed_users", "all")).strip().lower()
            if allowed_raw in ("", "all"):
                allowed: set[str] | None = None
            else:
                allowed = {u.strip() for u in allowed_raw.split(",") if u.strip()}

            app = AppConfig(
                name=name,
                app_id=str(item["app_id"]),
                app_secret=str(item["app_secret"]),
                allowed_users=allowed,
                provider=str(item.get("provider", "claude")),
                tmux_session=str(item.get("tmux_session", "cclark")),
                health_port=int(item.get("health_port", 8080)),
            )
            self.apps.append(app)
            self._by_name[name] = app

        logger.info("Loaded %d app(s) from %s", len(self.apps), path)

    # ── Env-var fallback (single-app development) ──────────────────────────────

    def _load_from_env(self) -> None:
        """Read FEISHU_APP_ID / FEISHU_APP_SECRET env vars and create a single default app."""
        app_id = os.getenv("FEISHU_APP_ID", "").strip()
        app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            return  # Will raise "no apps" above

        self.unified_icc_ws_url = os.getenv(
            "CCLARK_UNIFIED_ICC_WS_URL",
            os.getenv("ICC_WS_URL", "ws://127.0.0.1:8900/api/v1/ws"),
        )
        self.unified_icc_api_key = os.getenv(
            "CCLARK_UNIFIED_ICC_API_KEY",
            os.getenv("ICC_API_KEY", ""),
        )

        allowed_raw = os.getenv("ALLOWED_USERS", "").strip().lower()
        if allowed_raw in ("", "all"):
            allowed: set[str] | None = None
        else:
            allowed = {u.strip() for u in allowed_raw.split(",") if u.strip()}

        self.apps.append(AppConfig(
            name="default",
            app_id=app_id,
            app_secret=app_secret,
            allowed_users=allowed,
            provider=os.getenv("CCLARK_PROVIDER", "claude"),
            tmux_session=os.getenv("TMUX_SESSION_NAME", "cclark"),
            health_port=int(os.getenv("CCLARK_HEALTH_PORT", "8080")),
        ))
        self._by_name["default"] = self.apps[0]
        logger.info("Loaded single-app config from environment")

    # ── App lookup ────────────────────────────────────────────────────────────

    def get_app(self, name: str) -> AppConfig | None:
        return self._by_name.get(name)

    def get_default_app(self) -> AppConfig:
        return self._default_app

    @property
    def is_multi_app(self) -> bool:
        return len(self.apps) > 1

    # ── Convenience shortcuts ─────────────────────────────────────────────────

    @property
    def feishu_app_id(self) -> str:
        return self._default_app.app_id

    @property
    def feishu_app_secret(self) -> str:
        return self._default_app.app_secret

    @property
    def allowed_users(self) -> set[str] | None:
        return self._default_app.allowed_users

    @property
    def default_provider(self) -> str:
        return self._default_app.provider

    @property
    def health_port(self) -> int:
        return self._default_app.health_port

    @property
    def bot_user_id(self) -> str:
        return os.getenv("FEISHU_BOT_USER_ID", "")

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if a user is allowed (uses default app's allowed_users)."""
        allowed = self._default_app.allowed_users
        return allowed is None or user_id in allowed

    def parse_channel_id(self, chat_id: str, thread_id: str = "") -> str:
        """Build a channel ID string.

        In multi-app mode: includes app name to distinguish channels
        across apps. In single-app mode: plain feishu:chat_id[:thread_id].
        """
        suffix = f":{thread_id}" if thread_id else ""
        if self.is_multi_app:
            return f"feishu:{self._default_app.name}:{chat_id}{suffix}"
        return f"feishu:{chat_id}{suffix}"

    def split_channel_id(self, channel_id: str) -> tuple[str, str]:
        """Parse channel_id into (chat_id, thread_id). Handles both formats.

        Single-app:  feishu:chat_id[:thread_id]
        Multi-app:   feishu:app_name:chat_id[:thread_id]
        """
        parts = channel_id.split(":")
        n2, n3, n4 = 2, 3, 4
        if len(parts) == n2:  # feishu:chat_id
            return parts[1], ""
        if len(parts) == n3:  # feishu:chat_id:thread_id OR feishu:app:chat (if app has no _)
            # Heuristic: if the middle part looks like a Feishu ID (oc_xxx or ou_xxx),
            # treat as single-app. Otherwise multi-app.
            if parts[1].startswith("oc_") or parts[1].startswith("ou_"):
                return parts[1], parts[2]
            # Multi-app: feishu:app_name:chat_id
            return f"{parts[1]}:{parts[2]}", ""
        if len(parts) == n4:  # feishu:app_name:chat_id:thread_id
            return f"{parts[1]}:{parts[2]}", parts[3]
        raise ValueError(f"Invalid channel_id format: {channel_id!r}")

    def app_name_for_channel(self, channel_id: str) -> str:
        """Return the app name encoded in a channel_id, or 'default'."""
        if not self.is_multi_app:
            return "default"
        parts = channel_id.split(":")
        n4 = 4
        if len(parts) == n4 and parts[0] == "feishu":
            return parts[1]
        return "default"

    def is_user_allowed_in_app(self, user_id: str, app_name: str) -> bool:
        """Check if a user is allowed for a specific app."""
        app = self._by_name.get(app_name)
        if app is None:
            return False
        allowed = app.allowed_users
        return allowed is None or user_id in allowed


config = FeishuConfig()
