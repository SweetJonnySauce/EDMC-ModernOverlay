import group_cache


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

