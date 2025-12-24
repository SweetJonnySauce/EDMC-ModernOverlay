from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from overlay_client.plugin_overrides import PluginOverrideManager  # noqa: E402


@pytest.fixture()
def override_file(tmp_path: Path) -> Path:
    return tmp_path / "overlay_groupings.json"


def _make_manager(config_path: Path) -> PluginOverrideManager:
    logger = logging.getLogger(f"test-plugin-overrides-{config_path.name}")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.INFO)
    return PluginOverrideManager(config_path, logger)


def test_grouping_by_id_prefix(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "metrics": {"idPrefixes": ["example.metric."]},
                        "alerts": {"idPrefixes": ["example.alert."]}
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


def test_grouping_prefix_configuration_without_transform(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {"idPrefixes": ["example.alert."]}
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


def test_group_is_configured_id_prefix(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": ["example.alert."],
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


def test_grouping_groups_block_configures_prefixes(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "EDR": {
                    "idPrefixGroups": {
                        "docking": {
                            "idPrefixes": [
                                "edr-docking-",
                                "edr-docking-station-"
                            ]
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


def test_grouping_key_infers_plugin_when_missing_plugin_name(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "EDR": {
                    "matchingPrefixes": ["edr-"],
                    "idPrefixGroups": {
                        "docking": {
                            "idPrefixes": [
                                "edr-docking-",
                                "edr-docking-station-"
                            ]
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)

    inferred_key = manager.grouping_key_for(None, "edr-docking-foo")

    assert inferred_key == ("EDR", "docking")


def test_exact_match_takes_priority_over_prefix(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": [
                                "example.alert."
                            ]
                        },
                        "warning": {
                            "idPrefixes": [
                                {"value": "example.alert.urgent", "matchMode": "exact"}
                            ]
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)

    assert manager.grouping_key_for("Example", "example.alert.urgent") == ("Example", "warning")
    assert manager.grouping_key_for("Example", "example.alert.normal") == ("Example", "alerts")


def test_group_anchor_selection(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": ["example.alert."],
                            "idPrefixGroupAnchor": "se"
                        },
                        "metrics": {
                            "idPrefixes": ["example.metric."],
                            "idPrefixGroupAnchor": "center"
                        },
                        "edge_top": {
                            "idPrefixes": ["example.top."],
                            "idPrefixGroupAnchor": "top"
                        },
                        "edge_bottom": {
                            "idPrefixes": ["example.bottom."],
                            "idPrefixGroupAnchor": "bottom"
                        },
                        "edge_left": {
                            "idPrefixes": ["example.left."],
                            "idPrefixGroupAnchor": "left"
                        },
                        "edge_right": {
                            "idPrefixes": ["example.right."],
                            "idPrefixGroupAnchor": "right"
                        },
                        "default": {
                            "idPrefixes": ["example.default."],
                            "idPrefixGroupAnchor": "invalid"
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
    assert manager.group_preserve_fill_aspect("Example", "edge_top") == (True, "top")
    assert manager.group_preserve_fill_aspect("Example", "edge_bottom") == (True, "bottom")
    assert manager.group_preserve_fill_aspect("Example", "edge_left") == (True, "left")
    assert manager.group_preserve_fill_aspect("Example", "edge_right") == (True, "right")


def test_group_payload_justification_lookup(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": ["example.alert."],
                            "payloadJustification": "right"
                        },
                        "metrics": {
                            "idPrefixes": ["example.metric."],
                            "payloadJustification": "center"
                        },
                        "default": {
                            "idPrefixes": ["example.default."]
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    assert manager.group_payload_justification("Example", "alerts") == "right"
    assert manager.group_payload_justification("Example", "metrics") == "center"
    assert manager.group_payload_justification("Example", "default") == "left"
    assert manager.group_payload_justification("Example", "missing") == "left"
    # invalid anchor falls back to nw
    assert manager.group_preserve_fill_aspect("Example", "default") == (True, "nw")
    # unknown suffix also falls back to nw
    assert manager.group_preserve_fill_aspect("Example", "other") == (True, "nw")


def test_group_offsets(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": ["example.alert."],
                            "offsetX": 25,
                            "offsetY": -40
                        },
                        "metrics": {"idPrefixes": ["example.metric."]}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    assert manager.group_offsets("Example", "alerts") == (25.0, -40.0)
    assert manager.group_offsets("Example", "metrics") == (0.0, 0.0)
    # unknown plugin / suffix fall back to zero
    assert manager.group_offsets("Other", "alerts") == (0.0, 0.0)
    assert manager.group_offsets("Example", "missing") == (0.0, 0.0)


def test_group_controller_preview_box_mode(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Example": {
                    "idPrefixGroups": {
                        "alerts": {
                            "idPrefixes": ["example.alert."],
                            "controllerPreviewBoxMode": "max",
                        },
                        "metrics": {
                            "idPrefixes": ["example.metric."],
                            "controllerPreviewBoxMode": "LAST",
                        },
                        "default": {
                            "idPrefixes": ["example.default."],
                            "controllerPreviewBoxMode": "invalid",
                        },
                        "snake": {
                            "idPrefixes": ["example.snake."],
                            "controller_preview_box_mode": "max",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manager = _make_manager(override_file)
    assert manager.group_controller_preview_box_mode("Example", "alerts") == "max"
    assert manager.group_controller_preview_box_mode("Example", "metrics") == "last"
    assert manager.group_controller_preview_box_mode("Example", "default") == "last"
    assert manager.group_controller_preview_box_mode("Example", "snake") == "max"
    assert manager.group_controller_preview_box_mode("Example", "missing") == "last"
    assert manager.group_controller_preview_box_mode("Other", "alerts") == "last"


def test_legacy_preserve_anchor_mapping(override_file: Path) -> None:
    override_file.write_text(
        json.dumps(
            {
                "Legacy": {
                    "grouping": {
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
