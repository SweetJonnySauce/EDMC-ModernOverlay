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
