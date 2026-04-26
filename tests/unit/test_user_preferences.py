"""Tests for user_preferences: per-user favorites and read offsets."""

from __future__ import annotations

import pytest

from cclark.user_preferences import UserPreferences


@pytest.fixture
def prefs() -> UserPreferences:
    return UserPreferences()


class TestUserPreferencesStarred:
    def test_get_starred_empty_by_default(self, prefs: UserPreferences) -> None:
        assert prefs.get_user_starred("ou_user1") == []

    def test_toggle_star_adds(self, prefs: UserPreferences) -> None:
        result = prefs.toggle_user_star("ou_user1", "/home/user/project")
        assert result is True
        assert "/home/user/project" in prefs.get_user_starred("ou_user1")

    def test_toggle_star_removes_on_second_call(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star("ou_user1", "/home/user/project")
        result = prefs.toggle_user_star("ou_user1", "/home/user/project")
        assert result is False
        assert "/home/user/project" not in prefs.get_user_starred("ou_user1")

    def test_toggle_star_normalizes_path(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star("ou_user1", "/home/user/project/../project/./src")
        starred = prefs.get_user_starred("ou_user1")
        assert len(starred) == 1

    def test_multiple_users_starred_independent(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star("ou_user1", "/path/a")
        prefs.toggle_user_star("ou_user2", "/path/b")
        assert prefs.get_user_starred("ou_user1") != prefs.get_user_starred("ou_user2")


class TestUserPreferencesMRU:
    def test_get_mru_empty_by_default(self, prefs: UserPreferences) -> None:
        assert prefs.get_user_mru("ou_user1") == []

    def test_update_mru_adds_to_front(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru("ou_user1", "/path/first")
        prefs.update_user_mru("ou_user1", "/path/second")
        assert prefs.get_user_mru("ou_user1") == ["/path/second", "/path/first"]

    def test_update_mru_deduplicates(self, prefs: UserPreferences) -> None:
        prefs.update_user_mru("ou_user1", "/path/same")
        prefs.update_user_mru("ou_user1", "/path/other")
        prefs.update_user_mru("ou_user1", "/path/same")
        mru = prefs.get_user_mru("ou_user1")
        assert mru[0] == "/path/same"
        assert mru.count("/path/same") == 1

    def test_update_mru_caps_at_5(self, prefs: UserPreferences) -> None:
        for i in range(8):
            prefs.update_user_mru("ou_user1", f"/path/{i}")
        assert len(prefs.get_user_mru("ou_user1")) == 5


class TestUserPreferencesWindowOffsets:
    def test_get_offset_missing_returns_none(self, prefs: UserPreferences) -> None:
        assert prefs.get_user_window_offset("ou_user1", "window_1") is None

    def test_update_and_get_offset(self, prefs: UserPreferences) -> None:
        prefs.update_user_window_offset("ou_user1", "window_1", 1024)
        assert prefs.get_user_window_offset("ou_user1", "window_1") == 1024

    def test_offsets_per_window(self, prefs: UserPreferences) -> None:
        prefs.update_user_window_offset("ou_user1", "window_1", 100)
        prefs.update_user_window_offset("ou_user1", "window_2", 200)
        assert prefs.get_user_window_offset("ou_user1", "window_1") == 100
        assert prefs.get_user_window_offset("ou_user1", "window_2") == 200


class TestUserPreferencesSerialization:
    def test_to_dict_roundtrip(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star("ou_user1", "/path/starred")
        prefs.update_user_mru("ou_user1", "/path/mru1")
        prefs.update_user_window_offset("ou_user1", "win1", 512)

        data = prefs.to_dict()
        restored = UserPreferences()
        restored.from_dict(data)

        assert restored.get_user_starred("ou_user1") == prefs.get_user_starred("ou_user1")
        assert restored.get_user_mru("ou_user1") == prefs.get_user_mru("ou_user1")
        assert restored.get_user_window_offset("ou_user1", "win1") == 512

    def test_from_dict_handles_missing_keys(self, prefs: UserPreferences) -> None:
        prefs.from_dict({})
        assert prefs.get_user_starred("ou_u") == []
        assert prefs.get_user_mru("ou_u") == []
        assert prefs.get_user_window_offset("ou_u", "w") is None

    def test_reset_clears_everything(self, prefs: UserPreferences) -> None:
        prefs.toggle_user_star("ou_user1", "/path")
        prefs.update_user_mru("ou_user1", "/path")
        prefs.update_user_window_offset("ou_user1", "win1", 1)

        prefs.reset()

        assert prefs.get_user_starred("ou_user1") == []
        assert prefs.get_user_mru("ou_user1") == []
        assert prefs.get_user_window_offset("ou_user1", "win1") is None
