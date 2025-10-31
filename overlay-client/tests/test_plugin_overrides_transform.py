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
            "notes": "Test override note.",
            "__match__": {"id_prefixes": ["shell-", "pad-"]},
            "shell-*": {
                "transform": {
                    "scale": {"x": 2.0, "y": 1.0, "point": "sw"},
                    "offset": {"x": 0.0, "y": 150.0},
                }
            },
            "pad-*": {
                "transform": {
                    "scale": {"x": 2.0, "y": 1.0, "point": "sw"},
                    "offset": {"x": 0.0, "y": 150.0},
                }
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


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_notes_logged_once(landingpad_config: Path) -> None:
    handler = _CaptureHandler()
    manager = _make_manager(landingpad_config, handler)
    original_points = list(_sample_shell_points())
    payload = {
        "type": "shape",
        "shape": "vect",
        "id": "shell-1",
        "plugin": "LandingPad",
        "ttl": 10,
        "vector": [{"x": x, "y": y} for x, y in original_points],
    }

    manager.apply(payload)
    manager.apply(payload)

    note_messages = [msg for msg in handler.messages if "override-note" in msg]
    assert len(note_messages) == 1
    assert "Test override note." in note_messages[0]
