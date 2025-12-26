from __future__ import annotations

import json
import time
from pathlib import Path

from overlay_plugin.groupings_diff import diff_groupings, is_empty_diff
from overlay_plugin.groupings_diff import shrink_user_file, shrink_user_groupings
from overlay_plugin.groupings_loader import merge_groupings_dicts


def test_diff_emits_overrides_user_only_and_disabled():
    shipped = {
        "PluginA": {
            "matchingPrefixes": ["Foo-"],
            "idPrefixGroups": {
                "Main": {"idPrefixes": ["Foo-1"], "idPrefixGroupAnchor": "NE", "offsetX": 1},
            },
        },
        "PluginB": {"idPrefixGroups": {"Alpha": {"idPrefixes": ["Alpha-"], "payloadJustification": "Left"}}},
        "PluginC": {"idPrefixGroups": {"Solo": {"idPrefixes": ["Solo-"]}}},
    }

    merged = {
        # matchingPrefixes normalized to same value; only offsetY differs and user-only group added.
        "PluginA": {
            "matchingPrefixes": ["FOO-"],
            "idPrefixGroups": {
                "Main": {"idPrefixes": ["FOO-1"], "idPrefixGroupAnchor": "ne", "offsetX": 1, "offsetY": 5},
                "Extra": {"idPrefixes": ["Extra-"], "payloadJustification": "Center"},
            },
        },
        # Group Alpha disabled -> omitted from merged view.
        "PluginB": {"idPrefixGroups": {}},
        # PluginC disabled -> omitted entirely.
        # User-only plugin should be emitted whole.
        "PluginUser": {"matchingPrefixes": ["User-"], "idPrefixGroups": {"Only": {"idPrefixes": ["Only-"], "offsetX": 3}}},
    }

    diff = diff_groupings(shipped, merged)

    assert "matchingPrefixes" not in diff["PluginA"]
    assert diff["PluginA"]["idPrefixGroups"]["Main"] == {"offsetY": 5}
    assert diff["PluginA"]["idPrefixGroups"]["Extra"] == {
        "idPrefixes": ["extra-"],
        "payloadJustification": "center",
    }

    assert diff["PluginB"]["idPrefixGroups"]["Alpha"] == {"disabled": True}
    assert diff["PluginC"] == {"disabled": True}

    plugin_user = diff["PluginUser"]
    assert plugin_user["matchingPrefixes"] == ["user-"]
    assert plugin_user["idPrefixGroups"]["Only"]["idPrefixes"] == ["only-"]
    assert plugin_user["idPrefixGroups"]["Only"]["offsetX"] == 3.0


def test_empty_diff_detected():
    payload = {
        "PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}},
    }
    diff = diff_groupings(payload, payload)
    assert diff == {}
    assert is_empty_diff(diff) is True


def test_shrink_user_groupings_preserves_overrides_and_disabled():
    shipped = {
        "PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"], "offsetX": 1}}},
        "PluginB": {"idPrefixGroups": {"Alpha": {"idPrefixes": ["Alpha-"]}}},
    }
    user = {
        "PluginA": {
            "idPrefixGroups": {
                # same as shipped except added offsetY; offsetX matches shipped and should be dropped
                "Main": {"idPrefixes": ["Foo-"], "offsetX": 1, "offsetY": 5},
                "Extra": {"idPrefixes": ["Bar-"]},
            }
        },
        # disable PluginB
        "PluginB": {"disabled": True},
        # user-only plugin
        "PluginC": {"idPrefixGroups": {"Only": {"idPrefixes": ["Only-"]}}},
    }

    shrunk = shrink_user_groupings(shipped, user)
    assert shrunk == {
        "PluginA": {"idPrefixGroups": {"Extra": {"idPrefixes": ["bar-"]}, "Main": {"offsetY": 5}}},
        "PluginB": {"disabled": True},
        "PluginC": {"idPrefixGroups": {"Only": {"idPrefixes": ["only-"]}}},
    }


def test_shrink_user_file_writes_minimized_and_backup(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    shipped_payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    user_payload = {
        "PluginA": {
            "idPrefixGroups": {
                "Main": {"idPrefixes": ["Foo-"]},
                "Extra": {"idPrefixes": ["Bar-"]},
            }
        }
    }
    shipped.write_text(json.dumps(shipped_payload), encoding="utf-8")
    user.write_text(json.dumps(user_payload, indent=2), encoding="utf-8")

    wrote = shrink_user_file(shipped, user, backup=True)
    assert wrote is True

    minimized = json.loads(user.read_text(encoding="utf-8"))
    assert minimized == {"PluginA": {"idPrefixGroups": {"Extra": {"idPrefixes": ["bar-"]}}}}
    backup_path = user.with_suffix(user.suffix + ".bak")
    assert backup_path.exists()
    assert json.loads(backup_path.read_text(encoding="utf-8")) == user_payload


def test_shrink_user_file_no_change_is_noop(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    shipped.write_text(json.dumps(payload), encoding="utf-8")
    user.write_text(json.dumps({}, indent=2), encoding="utf-8")
    before = user.read_text(encoding="utf-8")
    before_mtime = user.stat().st_mtime
    time.sleep(0.01)

    wrote = shrink_user_file(shipped, user, backup=True)
    after = user.read_text(encoding="utf-8")
    after_mtime = user.stat().st_mtime

    assert wrote is False
    assert before == after
    assert before_mtime == after_mtime


def test_diff_merge_round_trip_matches_merged_view():
    shipped = {
        "PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"], "offsetX": 1}}},
    }
    merged = {
        "PluginA": {
            "idPrefixGroups": {
                "Main": {"idPrefixes": ["Foo-"], "offsetX": 1, "offsetY": 2},
                "Extra": {"idPrefixes": ["Bar-"], "payloadJustification": "Center"},
            }
        }
    }

    diff = diff_groupings(shipped, merged)
    rebuilt = merge_groupings_dicts(shipped, diff)

    normalized_expected = merge_groupings_dicts(shipped, merged)
    assert rebuilt == normalized_expected


def test_diff_includes_background_fields():
    shipped = {
        "PluginA": {
            "idPrefixGroups": {
                "Main": {
                    "idPrefixes": ["Foo-"],
                    "backgroundColor": "#111111",
                    "backgroundBorderColor": "red",
                    "backgroundBorderWidth": 1,
                }
            }
        }
    }
    merged = {
        "PluginA": {
            "idPrefixGroups": {
                "Main": {
                    "idPrefixes": ["Foo-"],
                    "backgroundColor": "#222222",
                    "backgroundBorderColor": "blue",
                    "backgroundBorderWidth": 3,
                }
            }
        }
    }

    diff = diff_groupings(shipped, merged)
    assert diff["PluginA"]["idPrefixGroups"]["Main"]["backgroundColor"] == "#222222"
    assert diff["PluginA"]["idPrefixGroups"]["Main"]["backgroundBorderColor"] == "blue"
    assert diff["PluginA"]["idPrefixGroups"]["Main"]["backgroundBorderWidth"] == 3


def test_disabled_survives_diff_and_shrink_round_trip():
    shipped = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    merged = {}

    diff = diff_groupings(shipped, merged)
    assert diff == {"PluginA": {"disabled": True}}

    shrunk = shrink_user_groupings(shipped, diff)
    rebuilt = merge_groupings_dicts(shipped, shrunk)
    assert "PluginA" not in rebuilt


def test_shrink_malformed_user_is_noop(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    shipped.write_text(json.dumps({"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}), encoding="utf-8")
    user.write_text("{bad json", encoding="utf-8")
    before = user.read_text(encoding="utf-8")

    wrote = shrink_user_file(shipped, user)

    assert wrote is False
    assert user.read_text(encoding="utf-8") == before


def test_shrink_unwritable_path_skips(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    shipped.write_text(json.dumps({"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}), encoding="utf-8")
    user_dir = tmp_path / "overlay_groupings.user.json"
    user_dir.mkdir()

    wrote = shrink_user_file(shipped, user_dir)

    assert wrote is False
    assert user_dir.is_dir()
