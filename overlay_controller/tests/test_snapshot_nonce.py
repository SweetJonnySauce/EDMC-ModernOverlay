import time

import overlay_controller.overlay_controller as oc


def _make_app() -> oc.OverlayConfigApp:
    app = object.__new__(oc.OverlayConfigApp)
    app._groupings_data = {
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
    app._groupings_cache = {}
    app._last_edit_ts = 0.0
    app._edit_nonce = "n1"
    return app  # type: ignore[return-value]


def _cache_entry(offset_x: float, offset_y: float, nonce: str, ts: float) -> dict:
    return {
        "groups": {
            "PluginA": {
                "G1": {
                    "base": {
                        "base_min_x": 0.0,
                        "base_min_y": 0.0,
                        "base_max_x": 100.0,
                        "base_max_y": 50.0,
                        "base_width": 100.0,
                        "base_height": 50.0,
                        "has_transformed": True,
                    },
                    "transformed": {
                        "trans_min_x": 10.0,
                        "trans_min_y": 5.0,
                        "trans_max_x": 110.0,
                        "trans_max_y": 55.0,
                        "offset_dx": offset_x,
                        "offset_dy": offset_y,
                        "anchor": "nw",
                    },
                    "last_updated": ts,
                    "edit_nonce": nonce,
                }
            }
        }
    }


def test_snapshot_synthesizes_even_when_nonce_and_offsets_match():
    app = _make_app()
    now = time.time()
    entry = _cache_entry(10.0, 5.0, "n1", now)
    # Make cached transform distinct to prove it is used.
    t = entry["groups"]["PluginA"]["G1"]["transformed"]
    t["trans_min_x"] = 20.0
    t["trans_min_y"] = 15.0
    t["trans_max_x"] = 120.0
    t["trans_max_y"] = 65.0
    app._groupings_cache = entry
    app._last_edit_ts = now - 0.1
    snapshot = app._build_group_snapshot("PluginA", "G1")
    assert snapshot is not None
    # Controller synthesizes from base + current offsets even if cache matches to avoid snap-back.
    assert snapshot.transform_bounds == (10.0, 5.0, 110.0, 55.0)
    assert snapshot.has_transform


def test_snapshot_synthesizes_when_nonce_mismatch():
    app = _make_app()
    now = time.time()
    app._groupings_cache = _cache_entry(10.0, 5.0, "old", now)
    app._edit_nonce = "n1"
    app._last_edit_ts = now - 0.1
    snapshot = app._build_group_snapshot("PluginA", "G1")
    assert snapshot is not None
    # Synthesized from base + offsets (10,5) rather than cached transformed.
    assert snapshot.transform_bounds == (10.0, 5.0, 110.0, 55.0)
    assert snapshot.has_transform


def test_snapshot_synthesizes_when_offsets_mismatch():
    app = _make_app()
    now = time.time()
    app._groupings_cache = _cache_entry(0.0, 0.0, "n1", now)
    app._last_edit_ts = now - 0.1
    snapshot = app._build_group_snapshot("PluginA", "G1")
    assert snapshot is not None
    # Offsets in cache differ; expect synthesized transform from base + current offsets.
    assert snapshot.transform_bounds == (10.0, 5.0, 110.0, 55.0)
    assert snapshot.has_transform
