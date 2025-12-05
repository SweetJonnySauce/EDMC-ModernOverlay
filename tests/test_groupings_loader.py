import json
import time

import pytest

from overlay_plugin.groupings_loader import GroupingsLoader


def _write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_merge_precedence_and_normalisation(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped_payload = {
        "PluginA": {
            "matchingPrefixes": ["Foo-"],
            "idPrefixGroups": {
                "Main": {
                    "idPrefixes": ["Foo-1"],
                    "idPrefixGroupAnchor": "NE",
                    "offsetX": 1,
                    "payloadJustification": "Right",
                }
            },
        }
    }
    user_payload = {
        "PluginA": {
            "matchingPrefixes": ["bar-"],
            "idPrefixGroups": {
                "Main": {
                    "idPrefixes": ["Foo-2"],
                    "offsetY": 5,
                },
                "Extra": {
                    "idPrefixes": ["Baz-"],
                    "payloadJustification": "Center",
                },
            },
        },
        "PluginOnly": {
            "idPrefixGroups": {"Only": {"idPrefixes": ["Only-"]}},
        },
    }

    _write_json(shipped, shipped_payload)
    _write_json(user, user_payload)

    loader = GroupingsLoader(shipped, user)
    merged = loader.load()

    plugin_a = merged["PluginA"]
    assert plugin_a["matchingPrefixes"] == ["bar-"]

    groups = plugin_a["idPrefixGroups"]
    main = groups["Main"]
    assert main["idPrefixes"] == ["foo-2"]
    assert main["idPrefixGroupAnchor"] == "ne"  # normalised from shipped
    assert main["offsetX"] == pytest.approx(1.0)
    assert main["offsetY"] == pytest.approx(5.0)
    assert main["payloadJustification"] == "right"

    extra = groups["Extra"]
    assert extra["idPrefixes"] == ["baz-"]
    assert extra["payloadJustification"] == "center"

    plugin_only = merged["PluginOnly"]
    assert "idPrefixGroups" in plugin_only
    assert plugin_only["idPrefixGroups"]["Only"]["idPrefixes"] == ["only-"]


def test_disabled_plugin_and_group(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped_payload = {
        "PluginA": {
            "idPrefixGroups": {
                "Alpha": {"idPrefixes": ["Alpha-"]},
                "Beta": {"idPrefixes": ["Beta-"]},
            }
        },
        "PluginDisabled": {"idPrefixGroups": {"Main": {"idPrefixes": ["X-"]}}},
    }
    user_payload = {
        "PluginA": {
            "idPrefixGroups": {
                "Alpha": {"disabled": True},
            }
        },
        "PluginDisabled": {"disabled": True},
    }

    _write_json(shipped, shipped_payload)
    _write_json(user, user_payload)

    loader = GroupingsLoader(shipped, user)
    merged = loader.load()

    assert "PluginDisabled" not in merged
    plugin_a = merged["PluginA"]
    groups = plugin_a["idPrefixGroups"]
    assert "Alpha" not in groups  # disabled
    assert "Beta" in groups  # inherited


def test_reload_if_changed_handles_malformed_and_recovers(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped_payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    _write_json(shipped, shipped_payload)
    _write_json(user, {})

    loader = GroupingsLoader(shipped, user)
    initial = loader.load()
    assert not loader.diagnostics()["stale"]

    # Introduce malformed user file; reload should keep last-good and mark stale.
    user.write_text("{bad", encoding="utf-8")
    time.sleep(0.01)  # ensure mtime changes
    reloaded = loader.reload_if_changed()
    assert reloaded is False
    assert loader.diagnostics()["stale"] is True
    assert loader.merged() == initial

    # Fix user file; reload should succeed and clear stale flag.
    _write_json(user, {"PluginA": {"idPrefixGroups": {"Extra": {"idPrefixes": ["Bar-"]}}}})
    time.sleep(0.01)
    reloaded = loader.reload_if_changed()
    assert reloaded is True
    assert loader.diagnostics()["stale"] is False
    merged = loader.merged()
    assert "Extra" in merged["PluginA"]["idPrefixGroups"]

