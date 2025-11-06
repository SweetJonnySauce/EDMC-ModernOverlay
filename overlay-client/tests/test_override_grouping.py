from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from plugin_overrides import PluginOverrideManager  # noqa: E402


@pytest.fixture()
def override_file(tmp_path: Path) -> Path:
    return tmp_path / "plugin_overrides.json"


def _make_manager(config_path: Path) -> PluginOverrideManager:
    logger = logging.getLogger(f"test-plugin-overrides-{config_path.name}")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.INFO)
    return PluginOverrideManager(config_path, logger)


def test_grouping_mode_plugin(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "MyPlugin": {
                    "grouping": {"mode": "plugin"}
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    key = manager.grouping_key_for("MyPlugin", "payload-1")
    assert key == ("MyPlugin", None)


def test_grouping_mode_id_prefix(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "grouping": {
                        "mode": "id_prefix",
                        "prefixes": {
                            "metrics": "example.metric.",
                            "alerts": "example.alert."
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    metrics_key = manager.grouping_key_for("Example", "example.metric.rate")
    alerts_key = manager.grouping_key_for("Example", "example.alert.red")
    fallback_key = manager.grouping_key_for("Example", "other.id")

    assert metrics_key == ("Example", "metrics")
    assert alerts_key == ("Example", "alerts")
    assert fallback_key == ("Example", None)


def test_grouping_prefix_defaults_apply(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "grouping": {
                        "mode": "id_prefix",
                        "prefixes": {
                            "alerts": {
                                "prefix": "example.alert.",
                                "transform": {
                                    "offset": {"x": 5.0, "y": -10.0}
                                }
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    payload = {
        "type": "message",
        "id": "example.alert.value",
        "text": "Warning",
        "color": "white",
        "x": 0,
        "y": 0,
        "ttl": 4,
        "plugin": "Example",
    }
    manager.apply(payload)

    assert payload.get("__mo_transform__") is None


def test_group_is_configured_plugin_mode(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "LandingPad": {
                    "grouping": {"mode": "plugin"}
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)

    assert manager.group_is_configured("LandingPad", None) is True
    assert manager.group_is_configured("LandingPad", "item:foo") is False
    assert manager.group_is_configured("Other", None) is False


def test_group_is_configured_id_prefix(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "grouping": {
                        "mode": "id_prefix",
                        "groups": {
                            "alerts": {
                                "id_prefixes": ["example.alert."],
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)

    assert manager.group_is_configured("Example", "alerts") is True
    assert manager.group_is_configured("Example", "example.alert.") is False
    assert manager.group_is_configured("Example", None) is False
    assert manager.group_is_configured("Other", "alerts") is False


def test_grouping_groups_block_applies_shared_transform(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "EDR": {
                    "grouping": {
                        "mode": "id_prefix",
                        "groups": {
                            "docking": {
                                "id_prefixes": [
                                    "edr-docking-",
                                    "edr-docking-station-"
                                ],
                                "transform": {
                                    "offset": {"x": 0.0, "y": -100.0}
                                }
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    payload = {
        "type": "shape",
        "shape": "rect",
        "id": "edr-docking-panel",
        "plugin": "EDR",
        "ttl": 4,
        "x": 10,
        "y": 20,
        "w": 5,
        "h": 5,
    }

    manager.apply(payload)

    assert payload.get("__mo_transform__") is None

    grouping_key = manager.grouping_key_for("EDR", "edr-docking-panel")
    assert grouping_key == ("EDR", "docking")

    grouping_key_station = manager.grouping_key_for("EDR", "edr-docking-station-bar")
    assert grouping_key_station == ("EDR", "docking")


def test_group_anchor_selection(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "grouping": {
                        "mode": "id_prefix",
                        "groups": {
                            "alerts": {
                                "id_prefixes": ["example.alert."],
                                "anchor": "se"
                            },
                            "metrics": {
                                "id_prefixes": ["example.metric."],
                                "anchor": "center"
                            },
                            "default": {
                                "id_prefixes": ["example.default."],
                                "anchor": "invalid"
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    assert manager.group_preserve_fill_aspect("Example", "alerts") == (True, "se")
    assert manager.group_preserve_fill_aspect("Example", "metrics") == (True, "center")
    # invalid anchor falls back to nw
    assert manager.group_preserve_fill_aspect("Example", "default") == (True, "nw")
    # unknown suffix also falls back to nw
    assert manager.group_preserve_fill_aspect("Example", "other") == (True, "nw")


def test_legacy_preserve_anchor_mapping(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Legacy": {
                    "grouping": {
                        "mode": "id_prefix",
                        "groups": {
                            "payload": {
                                "id_prefixes": ["legacy."],
                                "preserve_fill_aspect": {
                                    "anchor": "centroid"
                                }
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    assert manager.group_preserve_fill_aspect("Legacy", "payload") == (True, "center")
