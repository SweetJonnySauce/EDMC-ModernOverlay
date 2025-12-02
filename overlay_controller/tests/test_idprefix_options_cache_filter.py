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


def test_idprefix_options_filtered_by_cache(tmp_path):
    groupings_path = tmp_path / "overlay_groupings.json"
    cache_path = tmp_path / "overlay_group_cache.json"

    groupings_payload = {
        "PluginA": {
            "idPrefixGroups": {
                "Group1": {},
                "Group2": {},
            }
        },
        "PluginB": {"idPrefixGroups": {"OnlyB": {}}},
    }
    cache_payload = {
        "version": 1,
        "groups": {
            "PluginA": {
                "Group1": {
                    "base": {"base_min_x": 0, "base_min_y": 0, "base_max_x": 1, "base_max_y": 1},
                    "transformed": {},
                }
            },
            # PluginB missing entirely, Group2 missing
        },
    }

    groupings_path.write_text(json.dumps(groupings_payload), encoding="utf-8")
    cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")

    app = SimpleNamespace(
        _groupings_path=groupings_path,
        _groupings_cache_path=cache_path,
        _groupings_cache=cache_payload,
        _idprefix_entries=[],
    )
    options = oc.OverlayConfigApp._load_idprefix_options(app)

    # Only PluginA:Group1 should be present.
    assert options == ["PluginA: Group1"]
    assert getattr(app, "_idprefix_entries") == [("PluginA", "Group1")]
