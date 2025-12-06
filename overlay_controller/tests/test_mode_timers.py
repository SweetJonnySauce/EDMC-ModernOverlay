from overlay_client.controller_mode import ControllerModeProfile, ModeProfile
from overlay_controller.services.mode_timers import ModeTimers


class TimeStub:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


class AfterHarness:
    def __init__(self) -> None:
        self.scheduled: list[tuple[str, int, object]] = []
        self.cancelled: list[object] = []

    def after(self, ms: int, cb) -> str:
        handle = f"h{len(self.scheduled) + 1}"
        self.scheduled.append((handle, ms, cb))
        return handle

    def cancel(self, handle: object) -> None:
        self.cancelled.append(handle)

    def run(self, handle: str) -> None:
        for h, _ms, cb in list(self.scheduled):
            if h == handle:
                cb()
                return
        raise AssertionError(f"Handle {handle} not found")


def build_profile() -> ControllerModeProfile:
    return ControllerModeProfile(
        active=ModeProfile(write_debounce_ms=75, offset_write_debounce_ms=75, status_poll_ms=50, cache_flush_seconds=1.0),
        inactive=ModeProfile(write_debounce_ms=200, offset_write_debounce_ms=200, status_poll_ms=2500, cache_flush_seconds=5.0),
    )


def test_apply_mode_clamps_and_reschedules_poll() -> None:
    harness = AfterHarness()
    timers = ModeTimers(
        build_profile(),
        after=harness.after,
        after_cancel=harness.cancel,
        time_source=lambda: 0.0,
    )

    first_handle = timers.start_status_poll(lambda: None)
    assert harness.scheduled and harness.scheduled[-1][1] == 50

    timers.apply_mode("inactive", reason="test")

    assert harness.cancelled == [first_handle]
    # New schedule should use inactive poll interval (clamped >=50).
    assert harness.scheduled[-1][1] == 2500
    assert timers.write_debounce_ms == 200
    assert timers.offset_write_debounce_ms == 200
    assert timers.status_poll_interval_ms == 2500


def test_status_poll_reschedules_after_callback() -> None:
    harness = AfterHarness()
    poll_calls: list[str] = []
    timers = ModeTimers(
        build_profile(),
        after=harness.after,
        after_cancel=harness.cancel,
        time_source=lambda: 0.0,
    )

    handle = timers.start_status_poll(lambda: poll_calls.append("poll"))
    harness.run(handle)

    assert poll_calls == ["poll"]
    # A new poll should be scheduled after callback execution.
    assert len(harness.scheduled) >= 2
    _, delay_ms, _cb = harness.scheduled[-1]
    assert delay_ms == timers.status_poll_interval_ms


def test_debounce_helpers_use_write_and_offset_intervals() -> None:
    harness = AfterHarness()
    timers = ModeTimers(
        build_profile(),
        after=harness.after,
        after_cancel=harness.cancel,
        time_source=lambda: 0.0,
    )

    timers.schedule_debounce("config", lambda: None)
    timers.schedule_offset_debounce("offset", lambda: None)

    assert harness.scheduled[0][1] == timers.write_debounce_ms
    assert harness.scheduled[1][1] == timers.offset_write_debounce_ms

    # Re-scheduling should cancel prior handle.
    timers.schedule_debounce("config", lambda: None, delay_ms=30)
    assert harness.cancelled and harness.cancelled[-1] == harness.scheduled[0][0]
    assert harness.scheduled[-1][1] == 30


def test_live_edit_and_reload_guard_respect_timestamps() -> None:
    clock = TimeStub(0.0)
    timers = ModeTimers(
        build_profile(),
        after=lambda _ms, _cb: None,
        after_cancel=lambda _h: None,
        time_source=clock.now,
    )

    timers.start_live_edit_window(5.0)
    assert timers.live_edit_active() is True

    clock.value = 4.0
    assert timers.live_edit_active() is True

    clock.value = 6.0
    assert timers.live_edit_active() is False

    timers.record_edit()
    assert timers.should_reload_after_edit(delay_seconds=5.0) is False
    clock.value = 11.5
    assert timers.should_reload_after_edit(delay_seconds=5.0) is True
