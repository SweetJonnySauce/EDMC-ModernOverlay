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

    transform_meta = payload.get("__mo_transform__")
    assert isinstance(transform_meta, dict)
    offset = transform_meta.get("offset")
    assert isinstance(offset, dict)
    assert offset.get("x") == 5.0
    assert offset.get("y") == -10.0


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

    transform_meta = payload.get("__mo_transform__")
    assert isinstance(transform_meta, dict)
    offset = transform_meta.get("offset")
    assert isinstance(offset, dict)
    assert offset.get("y") == -100.0

    grouping_key = manager.grouping_key_for("EDR", "edr-docking-panel")
    assert grouping_key == ("EDR", "docking")

    grouping_key_station = manager.grouping_key_for("EDR", "edr-docking-station-bar")
    assert grouping_key_station == ("EDR", "docking")
