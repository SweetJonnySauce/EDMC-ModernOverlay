from __future__ import annotations

import json
from pathlib import Path

import pytest

from overlay_plugin import preferences as prefs


class DummyConfig:
    """Minimal EDMC config stub with get/set support."""

    def __init__(self, initial: dict[str, object] | None = None) -> None:
        self.store: dict[str, object] = dict(initial or {})

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.store.get(key, default)

    def set(self, key: str, value: object) -> None:
        self.store[key] = value


def _shadow(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_preferences_save_persists_config_and_shadow(plugin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = DummyConfig()
    monkeypatch.setattr(prefs, "EDMC_CONFIG", config)

    preferences = prefs.Preferences(plugin_dir, dev_mode=True)
    preferences.status_message_gutter = 30
    preferences.title_bar_height = 25
    preferences.payload_nudge_gutter = 40
    preferences.physical_clamp_overrides = {"DisplayPort-2": 1.0}
    preferences.save()

    shadow = _shadow(plugin_dir / prefs.PREFERENCES_FILE)
    assert shadow["status_message_gutter"] == 30
    assert shadow["title_bar_height"] == 25
    assert shadow["payload_nudge_gutter"] == 40
    assert shadow["physical_clamp_overrides"] == {"DisplayPort-2": 1.0}

    assert config.store[prefs._config_key("status_message_gutter")] == 30
    assert config.store[prefs._config_key("title_bar_height")] == 25
    assert config.store[prefs._config_key("payload_nudge_gutter")] == 40
    assert json.loads(config.store[prefs._config_key("physical_clamp_overrides")]) == {"DisplayPort-2": 1.0}


def test_preferences_reload_merges_shadow_when_config_empty(plugin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_config = DummyConfig()
    monkeypatch.setattr(prefs, "EDMC_CONFIG", first_config)

    first = prefs.Preferences(plugin_dir, dev_mode=True)
    first.status_message_gutter = 30
    first.title_bar_height = 25
    first.payload_nudge_gutter = 40
    first.physical_clamp_overrides = {"DisplayPort-2": 1.0, "HDMI-0": 1.25}
    first.save()

    # Simulate a restart where EDMC's config lost the values but the shadow JSON still exists.
    reloaded_config = DummyConfig()
    monkeypatch.setattr(prefs, "EDMC_CONFIG", reloaded_config)

    reloaded = prefs.Preferences(plugin_dir, dev_mode=True)
    assert reloaded.status_message_gutter == 30
    assert reloaded.title_bar_height == 25
    assert reloaded.payload_nudge_gutter == 40
    assert reloaded.physical_clamp_overrides == {"DisplayPort-2": 1.0, "HDMI-0": 1.25}

    # After merge, values should be written back into EDMC config as well.
    assert reloaded_config.store[prefs._config_key("status_message_gutter")] == 30
    assert reloaded_config.store[prefs._config_key("title_bar_height")] == 25
    assert reloaded_config.store[prefs._config_key("payload_nudge_gutter")] == 40
    assert json.loads(reloaded_config.store[prefs._config_key("physical_clamp_overrides")]) == {
        "DisplayPort-2": 1.0,
        "HDMI-0": 1.25,
    }
