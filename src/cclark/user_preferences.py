"""Per-Feishu-user directory favorites and read offsets.

Adapted from ccgram/user_preferences.py — uses str user IDs instead of int.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = structlog.get_logger()


@dataclass
class UserPreferences:
    """Per-user directory favorites and transcript read offsets."""

    user_dir_favorites: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    """user_id -> {"starred": [...], "mru": [...]}"""

    user_window_offsets: dict[str, dict[str, int]] = field(default_factory=dict)
    """user_id -> {window_id -> byte_offset}"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_window_offsets": dict(self.user_window_offsets),
            "user_dir_favorites": dict(self.user_dir_favorites),
        }

    def from_dict(self, data: dict[str, Any]) -> None:
        self.user_window_offsets = {
            str(uid): offsets
            for uid, offsets in data.get("user_window_offsets", {}).items()
        }
        self.user_dir_favorites = {
            str(uid): favs for uid, favs in data.get("user_dir_favorites", {}).items()
        }

    # ── Directory favorites ─────────────────────────────────────────────────

    def get_user_starred(self, user_id: str) -> list[str]:
        return list(self.user_dir_favorites.get(user_id, {}).get("starred", []))

    def get_user_mru(self, user_id: str) -> list[str]:
        return list(self.user_dir_favorites.get(user_id, {}).get("mru", []))

    def update_user_mru(self, user_id: str, path: str) -> None:
        resolved = str(Path(path).resolve())
        favs = self.user_dir_favorites.setdefault(user_id, {})
        mru: list[str] = favs.get("mru", [])
        mru = [resolved] + [p for p in mru if p != resolved]
        favs["mru"] = mru[:5]

    def toggle_user_star(self, user_id: str, path: str) -> bool:
        resolved = str(Path(path).resolve())
        favs = self.user_dir_favorites.setdefault(user_id, {})
        starred: list[str] = favs.get("starred", [])
        if resolved in starred:
            starred.remove(resolved)
            now_starred = False
        else:
            starred.append(resolved)
            now_starred = True
        favs["starred"] = starred
        return now_starred

    # ── Read offsets ───────────────────────────────────────────────────────

    def get_user_window_offset(self, user_id: str, window_id: str) -> int | None:
        return self.user_window_offsets.get(user_id, {}).get(window_id)

    def update_user_window_offset(
        self, user_id: str, window_id: str, offset: int
    ) -> None:
        self.user_window_offsets.setdefault(user_id, {})[window_id] = offset

    def reset(self) -> None:
        self.user_dir_favorites.clear()
        self.user_window_offsets.clear()


user_preferences = UserPreferences()
