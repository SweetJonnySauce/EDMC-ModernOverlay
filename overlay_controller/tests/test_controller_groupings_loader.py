from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
import sys

# Ensure repository root is on sys.path so overlay_controller package can be imported.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import overlay_controller.overlay_controller as oc  # noqa: E402
from overlay_plugin.groupings_loader import GroupingsLoader  # noqa: E402


def test_controller_uses_merged_groupings(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    cache_path = tmp_path / "overlay_group_cache.json"

    shipped.write_text(
        json.dumps({"PluginA": {"idPrefixGroups": {"GroupA": {}}}}, indent=2),
        encoding="utf-8",
    )
    user.write_text(
        json.dumps({"PluginB": {"idPrefixGroups": {"GroupB": {}}}}, indent=2),
        encoding="utf-8",
    )
    cache_payload = {
        "groups": {
            "PluginA": {"GroupA": {"base": {}, "transformed": {}}},
            "PluginB": {"GroupB": {"base": {}, "transformed": {}}},
        }
    }
    cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")

    loader = GroupingsLoader(shipped, user)
    loader.load()
    app = SimpleNamespace(
        _groupings_loader=loader,
        _groupings_cache_path=cache_path,
        _groupings_cache=cache_payload,
        _idprefix_entries=[],
    )
    options = oc.OverlayConfigApp._load_idprefix_options(app)

    assert options == ["GroupA", "GroupB"]
    assert ("PluginB", "GroupB") in getattr(app, "_idprefix_entries")


def test_controller_writes_user_file_only(tmp_path):
    user_path = tmp_path / "overlay_groupings.user.json"
    shipped_path = tmp_path / "overlay_groupings.json"
    shipped_path.write_text("{}", encoding="utf-8")

    app = SimpleNamespace(
        _groupings_user_path=user_path,
        _groupings_path=user_path,
        _groupings_data={"PluginA": {"idPrefixGroups": {"Main": {}}}},
    )

    oc.OverlayConfigApp._write_groupings_config(app)

    assert user_path.exists()
    assert shipped_path.read_text(encoding="utf-8") == "{}"


def test_controller_write_uses_diff(tmp_path):
    user_path = tmp_path / "overlay_groupings.user.json"
    shipped_path = tmp_path / "overlay_groupings.json"
    shipped_payload = {
        "PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"], "offsetX": 1}}},
    }
    merged_payload = {
        "PluginA": {
            "idPrefixGroups": {
                "Main": {"idPrefixes": ["foo-"], "offsetX": 1, "offsetY": 5},
                "Extra": {"idPrefixes": ["Bar-"], "payloadJustification": "Center"},
            }
        },
        "PluginOnly": {"idPrefixGroups": {"Only": {"idPrefixes": ["Only-"]}}},
    }
    shipped_path.write_text(json.dumps(shipped_payload), encoding="utf-8")

    app = SimpleNamespace(
        _groupings_user_path=user_path,
        _groupings_path=user_path,
        _groupings_shipped_path=shipped_path,
        _groupings_data=merged_payload,
    )

    oc.OverlayConfigApp._write_groupings_config(app)

    saved = json.loads(user_path.read_text(encoding="utf-8"))
    assert saved == {
        "PluginA": {
            "idPrefixGroups": {
                "Extra": {"idPrefixes": ["bar-"], "payloadJustification": "center"},
                "Main": {"offsetY": 5},
            }
        },
        "PluginOnly": {"idPrefixGroups": {"Only": {"idPrefixes": ["only-"]}}},
    }


def test_controller_write_noop_on_empty_diff(tmp_path):
    user_path = tmp_path / "overlay_groupings.user.json"
    shipped_path = tmp_path / "overlay_groupings.json"
    payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    shipped_path.write_text(json.dumps(payload), encoding="utf-8")

    app = SimpleNamespace(
        _groupings_user_path=user_path,
        _groupings_path=user_path,
        _groupings_shipped_path=shipped_path,
        _groupings_data=payload,
    )

    oc.OverlayConfigApp._write_groupings_config(app)

    assert not user_path.exists()


def test_controller_write_clears_user_when_matching_defaults(tmp_path):
    user_path = tmp_path / "overlay_groupings.user.json"
    shipped_path = tmp_path / "overlay_groupings.json"
    shipped_payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"], "offsetY": 0}}}}
    user_payload = {"PluginA": {"idPrefixGroups": {"Main": {"offsetY": 5}}}}
    shipped_path.write_text(json.dumps(shipped_payload), encoding="utf-8")
    user_path.write_text(json.dumps(user_payload, indent=2), encoding="utf-8")

    # Simulate merged view matching shipped defaults (user reset to baseline).
    app = SimpleNamespace(
        _groupings_user_path=user_path,
        _groupings_path=user_path,
        _groupings_shipped_path=shipped_path,
        _groupings_data=shipped_payload,
    )

    oc.OverlayConfigApp._write_groupings_config(app)

    assert user_path.exists()
    assert json.loads(user_path.read_text(encoding="utf-8")) == {}
