"""Shared pytest fixtures and test environment setup."""

from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Set env vars before any modules are imported — prevents FeishuConfig from raising."""
    os.environ.setdefault("FEISHU_APP_ID", "cli_test")
    os.environ.setdefault("FEISHU_APP_SECRET", "test_secret")
    os.environ.setdefault("FEISHU_VERIFICATION_TOKEN", "test_token")
    os.environ.setdefault("ALLOWED_USERS", "ou_testuser1,ou_testuser2")
    os.environ.setdefault("FEISHU_BOT_USER_ID", "ou_bot")
    os.environ.setdefault("CCLARK_PROVIDER", "claude")


@pytest.fixture(autouse=True)
def mock_config(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub out the FeishuConfig singleton after import.

    The tricky part: `cclark.config` imports `from cclark.config import config`,
    so patching `cclark.config.config` doesn't help other modules that also
    did `from cclark.config import config`. We patch the *module* so every
    import path sees the mock.
    """
    mock_cfg = MagicMock()
    mock_cfg.feishu_app_id = "cli_test"
    mock_cfg.feishu_app_secret = "test_secret"
    mock_cfg.feishu_verification_token = "test_token"
    mock_cfg.feishu_encrypt_key = ""
    mock_cfg.webhook_port = 8080
    mock_cfg.webhook_path = "/webhook/event"
    mock_cfg.allowed_users = {"ou_testuser1", "ou_testuser2"}
    mock_cfg.bot_user_id = "ou_bot"
    mock_cfg.default_provider = "claude"
    mock_cfg.toolbar_config_path = ""
    # Real methods needed by callback_registry and ws_client
    mock_cfg.is_user_allowed = lambda uid: uid in {"ou_testuser1", "ou_testuser2"}
    mock_cfg.parse_channel_id = lambda cid, tid="": f"feishu:{cid}:{tid}" if tid else f"feishu:{cid}"
    mock_cfg.split_channel_id = lambda cid: (cid.split(":")[1], cid.split(":")[2]) if cid.startswith("feishu:") else (cid, "")

    # Patch the module object in sys.modules so all import paths see the mock
    mock_module = ModuleType("cclark.config")
    mock_module.config = mock_cfg
    monkeypatch.setitem(sys.modules, "cclark.config", mock_module)

    return mock_cfg
