import json
import time
from pathlib import Path

from overlay_controller.services.group_state import GroupSnapshot, GroupStateService


def test_load_options_filters_by_cache(tmp_path: Path) -> None:
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    cache = tmp_path / "overlay_group_cache.json"

    shipped.write_text(
        json.dumps(
            {
                "PluginA": {"idPrefixGroups": {"Group1": {}, "Group2": {}}},
                "PluginB": {"idPrefixGroups": {"OnlyB": {}}},
            }
        ),
        encoding="utf-8",
    )
    cache.write_text(
        json.dumps(
            {
                "groups": {
                    "PluginA": {"Group1": {"base": {"base_min_x": 0, "base_min_y": 0, "base_max_x": 1, "base_max_y": 1}}},
                    # PluginA:Group2 missing; PluginB missing
                }
            }
        ),
        encoding="utf-8",
    )

    service = GroupStateService(shipped_path=shipped, user_groupings_path=user, cache_path=cache)
    options = service.load_options()

    assert options == ["PluginA: Group1"]
    assert service.idprefix_entries == [("PluginA", "Group1")]


def test_snapshot_synthesizes_from_base_and_offsets(tmp_path: Path) -> None:
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    cache = tmp_path / "overlay_group_cache.json"

    service = GroupStateService(shipped_path=shipped, user_groupings_path=user, cache_path=cache)
    service._groupings_data = {
        "PluginA": {
            "idPrefixGroups": {
                "G1": {
                    "offsetX": 10.0,
                    "offsetY": 5.0,
                    "idPrefixGroupAnchor": "nw",
                }
            }
        }
    }
    cache_payload = {
        "groups": {
            "PluginA": {
                "G1": {
                    "base": {
                        "base_min_x": 0.0,
                        "base_min_y": 0.0,
                        "base_max_x": 100.0,
                        "base_max_y": 50.0,
                    },
                    "transformed": {
                        "trans_min_x": 20.0,
                        "trans_min_y": 15.0,
                        "trans_max_x": 120.0,
                        "trans_max_y": 65.0,
                        "offset_dx": 20.0,
                        "offset_dy": 15.0,
                        "anchor": "se",
                    },
                    "last_updated": 123.0,
                }
            }
        }
    }
    cache.write_text(json.dumps(cache_payload), encoding="utf-8")
    service.refresh_cache()

    snapshot = service.snapshot("PluginA", "G1")

    assert isinstance(snapshot, GroupSnapshot)
    assert snapshot.anchor_token == "nw"
    assert snapshot.transform_anchor_token == "se"
    assert snapshot.base_bounds == (0.0, 0.0, 100.0, 50.0)
    assert snapshot.transform_bounds == (10.0, 5.0, 110.0, 55.0)
    assert snapshot.base_anchor == (0.0, 0.0)
    assert snapshot.transform_anchor == (110.0, 55.0)
    assert snapshot.has_transform
    assert snapshot.cache_timestamp == 123.0


def test_persist_offsets_writes_diff_and_invalidates_cache(tmp_path: Path) -> None:
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    cache = tmp_path / "overlay_group_cache.json"

    shipped.write_text(
        json.dumps({"PluginA": {"idPrefixGroups": {"G1": {"idPrefixes": ["Foo-"], "offsetX": 0, "offsetY": 0}}}}),
        encoding="utf-8",
    )
    cache.write_text(
        json.dumps(
            {
                "groups": {
                    "PluginA": {
                        "G1": {
                            "base": {
                                "base_min_x": 0.0,
                                "base_min_y": 0.0,
                                "base_max_x": 10.0,
                                "base_max_y": 10.0,
                            },
                            "transformed": {"trans_min_x": 1.0, "trans_min_y": 2.0, "trans_max_x": 3.0, "trans_max_y": 4.0},
                            "last_updated": 1.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    service = GroupStateService(shipped_path=shipped, user_groupings_path=user, cache_path=cache)
    service._groupings_data = {
        "PluginA": {
            "idPrefixGroups": {
                "G1": {"idPrefixes": ["Foo-"], "offsetX": 0.0, "offsetY": 0.0, "idPrefixGroupAnchor": "nw"}
            }
        }
    }

    service.persist_offsets("PluginA", "G1", 10.0, 5.0, edit_nonce="n-123")

    saved = json.loads(user.read_text(encoding="utf-8"))
    assert saved["_edit_nonce"] == "n-123"
    assert saved["PluginA"]["idPrefixGroups"]["G1"]["offsetX"] == 10.0
    assert saved["PluginA"]["idPrefixGroups"]["G1"]["offsetY"] == 5.0

    cache_payload = json.loads(cache.read_text(encoding="utf-8"))
    entry = cache_payload["groups"]["PluginA"]["G1"]
    assert entry["transformed"] is None
    assert entry["base"]["has_transformed"] is False
    assert entry["edit_nonce"] == "n-123"
    assert isinstance(entry["last_updated"], float)


def test_persist_anchor_can_skip_write_and_invalidate(tmp_path: Path) -> None:
    service = GroupStateService(
        shipped_path=tmp_path / "overlay_groupings.json",
        user_groupings_path=tmp_path / "overlay_groupings.user.json",
        cache_path=tmp_path / "overlay_group_cache.json",
    )
    service._groupings_data = {"PluginA": {"idPrefixGroups": {"G1": {}}}}

    service.persist_anchor("PluginA", "G1", "se", write=False, invalidate_cache=False)

    assert service._groupings_data["PluginA"]["idPrefixGroups"]["G1"]["idPrefixGroupAnchor"] == "se"
    assert not service._cache_path.exists()
    assert not service._user_path.exists()


def test_reload_groupings_skips_recent_edits_and_detects_changes(tmp_path: Path) -> None:
    class FakeLoader:
        def __init__(self) -> None:
            self.calls = 0
            self.should_change = False
            self._merged = {"PluginA": {"idPrefixGroups": {"G1": {}}}}

        def reload_if_changed(self) -> bool:
            self.calls += 1
            return self.should_change

        def merged(self) -> dict:
            return self._merged

    loader = FakeLoader()
    service = GroupStateService(
        shipped_path=tmp_path / "overlay_groupings.json",
        user_groupings_path=tmp_path / "overlay_groupings.user.json",
        cache_path=tmp_path / "overlay_group_cache.json",
        loader=loader,
    )

    last_edit = time.time()
    skipped = service.reload_groupings_if_changed(last_edit_ts=last_edit, now=last_edit + 1.0, delay_seconds=5.0)
    assert skipped is False
    assert loader.calls == 0

    loader.should_change = True
    changed = service.reload_groupings_if_changed(last_edit_ts=last_edit, now=last_edit + 6.0, delay_seconds=5.0)
    assert changed is True
    assert loader.calls == 1
    assert service._groupings_data == loader.merged()


def test_cache_changed_ignores_timestamp_churn(tmp_path: Path) -> None:
    service = GroupStateService(
        shipped_path=tmp_path / "overlay_groupings.json",
        user_groupings_path=tmp_path / "overlay_groupings.user.json",
        cache_path=tmp_path / "overlay_group_cache.json",
    )
    service._groupings_cache = {"groups": {"PluginA": {"G1": {"last_updated": 1, "base": {"v": 1}}}}}
    new_cache = {"groups": {"PluginA": {"G1": {"last_updated": 2, "base": {"v": 1}}}}}

    assert service.cache_changed(new_cache) is False

    new_cache["groups"]["PluginA"]["G1"]["base"]["v"] = 2
    assert service.cache_changed(new_cache) is True
