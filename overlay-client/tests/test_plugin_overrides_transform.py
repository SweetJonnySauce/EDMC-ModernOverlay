"""Tests for transform-based plugin overrides."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Tuple

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from plugin_overrides import PluginOverrideManager  # noqa: E402


def _make_manager(config_path: Path, handler: logging.Handler | None = None) -> PluginOverrideManager:
    logger = logging.getLogger(f"plugin-override-test-{config_path.name}")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if handler is None:
        logger.addHandler(logging.NullHandler())
    else:
        logger.addHandler(handler)
    return PluginOverrideManager(config_path, logger)


def _write_config(path: Path, overrides: dict) -> None:
    path.write_text(json.dumps(overrides), encoding="utf-8")


def _sample_shell_points() -> Iterable[Tuple[int, int]]:
    return [
        (124, 464),
        (111, 419),
        (89, 393),
        (62, 393),
        (40, 419),
        (27, 464),
        (27, 516),
        (40, 561),
        (62, 587),
        (89, 587),
        (111, 561),
        (124, 516),
        (124, 464),
    ]


@pytest.fixture()
def landingpad_config(tmp_path: Path) -> Path:
    config = {
        "LandingPad": {
            "__match__": {"id_prefixes": ["shell-", "pad-"]},
            "transform": {
                "scale": {"x": 2.0, "y": 1.0, "scale_anchor_point": "sw"},
                "offset": {"x": 0.0, "y": 150.0},
            },
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    return config_path


def test_transform_scales_landingpad_shell(landingpad_config: Path) -> None:
    manager = _make_manager(landingpad_config)
    original_points = list(_sample_shell_points())
    payload = {
        "type": "shape",
        "shape": "vect",
        "id": "shell-0",
        "plugin": "LandingPad",
        "ttl": 10,
        "vector": [{"x": x, "y": y} for x, y in original_points],
        "raw": {
            "plugin": "LandingPad",
            "vector": [{"x": x, "y": y} for x, y in original_points],
        },
    }

    manager.apply(payload)

    expected = [(2 * x - 27, y + 150) for x, y in original_points]
    transformed = [(point["x"], point["y"]) for point in payload["vector"]]
    assert transformed == expected

    raw_transformed = [(point["x"], point["y"]) for point in payload["raw"]["vector"]]
    assert raw_transformed == expected


def test_transform_scales_landingpad_rect(landingpad_config: Path) -> None:
    manager = _make_manager(landingpad_config)
    payload = {
        "type": "shape",
        "shape": "rect",
        "id": "pad-0",
        "plugin": "LandingPad",
        "ttl": 10,
        "x": 60,
        "y": 469,
        "w": 2,
        "h": 9,
        "raw": {
            "plugin": "LandingPad",
            "x": 60,
            "y": 469,
            "w": 2,
            "h": 9,
        },
    }

    manager.apply(payload)

    assert payload["x"] == 60
    assert payload["y"] == 619
    assert payload["w"] == 4
    assert payload["h"] == 9

    raw = payload["raw"]
    assert raw["x"] == 60
    assert raw["y"] == 619
    assert raw["w"] == 4
    assert raw["h"] == 9


def test_transform_accepts_point_mapping(tmp_path: Path) -> None:
    config = {
        "LandingPad": {
            "transform": {
                "scale": {
                    "x": 2.0,
                    "y": 1.0,
                    "scale_anchor_point": {"x": 50.0, "y": 75.0},
                }
            }
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    manager = _make_manager(config_path)
    payload = {
        "type": "shape",
        "shape": "vect",
        "id": "shell-99",
        "plugin": "LandingPad",
        "ttl": 5,
        "vector": [{"x": 60, "y": 80}],
    }

    manager.apply(payload)

    point = payload["vector"][0]
    assert point["x"] == 70  # 50 + (60-50) * 2
    assert point["y"] == 80  # unchanged


def test_infer_plugin_name_uses_id_prefix(landingpad_config: Path) -> None:
    manager = _make_manager(landingpad_config)
    payload = {
        "type": "shape",
        "shape": "rect",
        "id": "pad-19-0",
        "ttl": 5,
    }

    assert manager.infer_plugin_name(payload) == "LandingPad"


def test_transform_scales_message_coordinates(tmp_path: Path) -> None:
    config = {
        "bgstally": {
            "bgstally-msg-*": {
                "transform": {
                    "scale": {
                        "x": 1.0,
                        "y": 0.5,
                        "scale_anchor_point": {"x": 0.0, "y": 0.0},
                    }
                }
            }
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    manager = _make_manager(config_path)
    payload = {
        "type": "message",
        "id": "bgstally-msg-colonisation-123",
        "plugin": "bgstally",
        "ttl": 10,
        "text": "Colonisation started",
        "color": "white",
        "x": 75,
        "y": 400,
        "raw": {
            "plugin": "bgstally",
            "text": "Colonisation started",
            "x": 75,
            "y": 400,
        },
    }

    manager.apply(payload)

    assert payload["x"] == 75
    assert payload["y"] == 200
    assert payload["raw"]["x"] == 75
    assert payload["raw"]["y"] == 200


def test_transform_scales_tick_messages(tmp_path: Path) -> None:
    config = {
        "bgstally": {
            "bgstally-msg-tick": {
                "transform": {
                    "scale": {
                        "x": 1.0,
                        "y": 0.7,
                        "scale_anchor_point": {"x": 0.0, "y": 0.0},
                    }
                }
            }
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    manager = _make_manager(config_path)
    payload = {
        "type": "message",
        "id": "bgstally-msg-tick",
        "plugin": "bgstally",
        "ttl": 5,
        "text": "Tick incoming",
        "color": "white",
        "x": 120,
        "y": 480,
        "raw": {
            "plugin": "bgstally",
            "text": "Tick incoming",
            "x": 120,
            "y": 480,
        },
    }

    manager.apply(payload)

    assert payload["x"] == 120
    assert payload["y"] == 336
    assert payload["raw"]["x"] == 120
    assert payload["raw"]["y"] == 336


def test_transform_handles_mixed_case_plugin_and_id(tmp_path: Path) -> None:
    config = {
        "bgstally": {
            "bgstally-msg-*": {
                "transform": {
                    "scale": {
                        "x": 1.0,
                        "y": 0.7,
                        "scale_anchor_point": {"x": 0.0, "y": 0.0},
                    }
                }
            }
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    manager = _make_manager(config_path)
    payload = {
        "type": "message",
        "id": "BGSTally-msg-Tick",
        "plugin": "BGSTally",
        "ttl": 5,
        "text": "Tick incoming",
        "color": "white",
        "x": 200,
        "y": 500,
        "raw": {
            "plugin": "BGSTally",
            "text": "Tick incoming",
            "x": 200,
            "y": 500,
        },
    }

    manager.apply(payload)

    assert payload["y"] == 350
    assert payload["raw"]["y"] == 350


def test_transform_infers_plugin_from_mixed_case_id(tmp_path: Path) -> None:
    config = {
        "bgstally": {
            "__match__": {"id_prefixes": ["bgstally-"]},
            "bgstally-msg-*": {
                "transform": {
                    "scale": {"x": 1.0, "y": 0.7, "scale_anchor_point": {"x": 0.0, "y": 0.0}}
                }
            }
        }
    }
    config_path = tmp_path / "plugin_overrides.json"
    _write_config(config_path, config)
    manager = _make_manager(config_path)
    payload = {
        "type": "message",
        "id": "BGSTally-msg-System_Tick",
        "ttl": 5,
        "text": "System tick",
        "color": "white",
        "x": 90,
        "y": 420,
        "raw": {
            "text": "System tick",
            "x": 90,
            "y": 420,
        },
    }

    manager.apply(payload)

    assert payload["y"] == 294
