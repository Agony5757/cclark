from __future__ import annotations

from pathlib import Path

from cclark.config import FeishuConfig


def test_feishu_config_uses_unified_icc_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "unified"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
unified_icc_ws_url: "ws://127.0.0.1:8900/api/v1/ws"
apps:
  - name: "default"
    app_id: "cli_test"
    app_secret: "secret"
""".strip()
    )
    monkeypatch.setenv("UNIFIED_ICC_DIR", str(config_dir))

    cfg = FeishuConfig()

    assert cfg.config_dir == config_dir
    assert cfg.get_default_app().app_id == "cli_test"


def test_feishu_config_ignores_old_config_dir_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "new"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        """
apps:
  - name: "default"
    app_id: "cli_new"
    app_secret: "secret"
""".strip()
    )
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    (old_dir / "config.yaml").write_text(
        """
apps:
  - name: "default"
    app_id: "cli_old"
    app_secret: "secret"
""".strip()
    )
    monkeypatch.setenv("UNIFIED_ICC_DIR", str(config_dir))
    monkeypatch.setenv("CCLARK_CONFIG_DIR", str(old_dir))
    monkeypatch.setenv("CCLARK_DIR", str(old_dir))

    cfg = FeishuConfig()

    assert cfg.config_dir == config_dir
    assert cfg.get_default_app().app_id == "cli_new"
