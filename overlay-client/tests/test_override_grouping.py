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
