import json

import group_cache
import pytest

def test_group_cache_configure_debounce_reschedules(monkeypatch, tmp_path):
    timers = []

    class FakeTimer:
        def __init__(self, interval, function):
            self.interval = interval
            self.function = function
            self.started = False
            self.cancelled = False
            timers.append(self)

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return self.started and not self.cancelled

        def cancel(self) -> None:
            self.cancelled = True

    monkeypatch.setattr(group_cache.threading, "Timer", FakeTimer)

    cache_path = tmp_path / "overlay_group_cache.json"
    cache = group_cache.GroupPlacementCache(cache_path, debounce_seconds=1.0, logger=None)

    cache.update_group("plugin", "", {"value": 1}, None)
    assert timers
    first = timers[-1]
    assert first.started and not first.cancelled

    cache.configure_debounce(0.1)

    assert first.cancelled is True
    assert len(timers) >= 2
    latest = timers[-1]
    assert latest is not first
    assert latest.interval == 0.1
    assert latest.started
    assert cache._debounce_seconds == 0.1


def test_group_cache_update_records_metadata(tmp_path):
    cache_path = tmp_path / "overlay_group_cache.json"
    cache = group_cache.GroupPlacementCache(cache_path, debounce_seconds=0.1, logger=None)
    normalized = {
        "base_min_x": 0.0,
        "base_min_y": 0.0,
        "base_max_x": 10.0,
        "base_max_y": 10.0,
        "base_width": 10.0,
        "base_height": 10.0,
        "has_transformed": False,
        "offset_x": 5.0,
        "offset_y": 2.0,
        "edit_nonce": "nonce-test",
        "controller_ts": 123.456,
    }
    cache.update_group("Plugin", "G1", normalized, None)
    entry = cache._state["groups"]["Plugin"]["G1"]
    assert entry["edit_nonce"] == "nonce-test"
    assert entry["controller_ts"] == pytest.approx(123.456, rel=0, abs=0.001)


def test_group_cache_flush_pending_writes(tmp_path):
    cache_path = tmp_path / "overlay_group_cache.json"
    cache = group_cache.GroupPlacementCache(cache_path, debounce_seconds=10.0, logger=None)
    normalized = {
        "base_min_x": 1.0,
        "base_min_y": 2.0,
        "base_max_x": 3.0,
        "base_max_y": 4.0,
        "base_width": 2.0,
        "base_height": 2.0,
        "has_transformed": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "edit_nonce": "flush",
        "controller_ts": 42.0,
    }
    cache.update_group("Plugin", "G1", normalized, None)
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw["groups"] == {}  # not flushed yet due to debounce
    cache.flush_pending()
    flushed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "Plugin" in flushed["groups"]
    meta = cache.last_write_metadata("Plugin", "G1")
    assert meta is not None
    assert meta["edit_nonce"] == "flush"


def test_group_cache_updates_last_visible_and_max_transformed(tmp_path):
    cache_path = tmp_path / "overlay_group_cache.json"
    cache = group_cache.GroupPlacementCache(cache_path, debounce_seconds=0.1, logger=None)
    normalized = {
        "base_min_x": 0.0,
        "base_min_y": 0.0,
        "base_max_x": 90.0,
        "base_max_y": 45.0,
        "base_width": 90.0,
        "base_height": 45.0,
        "has_transformed": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "edit_nonce": "cache",
        "controller_ts": 0.0,
    }
    first = {
        "trans_min_x": 10.0,
        "trans_min_y": 5.0,
        "trans_max_x": 110.0,
        "trans_max_y": 55.0,
        "trans_width": 100.0,
        "trans_height": 50.0,
        "anchor": "nw",
        "offset_dx": 0.0,
        "offset_dy": 0.0,
    }
    cache.update_group("Plugin", "G1", normalized, first)
    entry = cache._state["groups"]["Plugin"]["G1"]
    assert entry["last_visible_transformed"]["base_width"] == 90.0
    assert entry["max_transformed"]["base_width"] == 90.0

    normalized_small = {
        **normalized,
        "base_max_x": 80.0,
        "base_max_y": 40.0,
        "base_width": 80.0,
        "base_height": 40.0,
    }
    smaller = {
        "trans_min_x": 10.0,
        "trans_min_y": 5.0,
        "trans_max_x": 90.0,
        "trans_max_y": 45.0,
        "trans_width": 80.0,
        "trans_height": 40.0,
        "anchor": "nw",
        "offset_dx": 0.0,
        "offset_dy": 0.0,
    }
    cache.update_group("Plugin", "G1", normalized_small, smaller)
    entry = cache._state["groups"]["Plugin"]["G1"]
    assert entry["last_visible_transformed"]["base_width"] == 80.0
    assert entry["max_transformed"]["base_width"] == 90.0

    normalized_large = {
        **normalized,
        "base_max_x": 120.0,
        "base_max_y": 60.0,
        "base_width": 120.0,
        "base_height": 60.0,
    }
    larger = {
        "trans_min_x": 10.0,
        "trans_min_y": 5.0,
        "trans_max_x": 130.0,
        "trans_max_y": 65.0,
        "trans_width": 120.0,
        "trans_height": 60.0,
        "anchor": "nw",
        "offset_dx": 0.0,
        "offset_dy": 0.0,
    }
    cache.update_group("Plugin", "G1", normalized_large, larger)
    entry = cache._state["groups"]["Plugin"]["G1"]
    assert entry["last_visible_transformed"]["base_width"] == 120.0
    assert entry["max_transformed"]["base_width"] == 120.0


def test_group_cache_reset_clears_state(tmp_path):
    cache_path = tmp_path / "overlay_group_cache.json"
    cache = group_cache.GroupPlacementCache(cache_path, debounce_seconds=0.1, logger=None)
    normalized = {
        "base_min_x": 0.0,
        "base_min_y": 0.0,
        "base_max_x": 10.0,
        "base_max_y": 10.0,
        "base_width": 10.0,
        "base_height": 10.0,
        "has_transformed": True,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "edit_nonce": "reset",
        "controller_ts": 0.0,
    }
    transformed = {
        "trans_min_x": 1.0,
        "trans_min_y": 2.0,
        "trans_max_x": 11.0,
        "trans_max_y": 12.0,
        "trans_width": 10.0,
        "trans_height": 10.0,
        "anchor": "nw",
        "offset_dx": 0.0,
        "offset_dy": 0.0,
    }
    cache.update_group("Plugin", "G1", normalized, transformed)
    cache.flush_pending()
    assert cache._state["groups"]["Plugin"]["G1"]["base"]["base_min_x"] == 0.0

    cache.reset()
    assert cache._state["groups"] == {}
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    assert raw["groups"] == {}
