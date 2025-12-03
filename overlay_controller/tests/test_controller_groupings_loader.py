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
