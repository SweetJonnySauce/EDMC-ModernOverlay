from overlay_client.controller_mode import ControllerModeTracker


def test_controller_mode_active_and_timeout():
    events = []

    def on_change(prev, curr):
        events.append((prev, curr))

    armed = []
    cancelled = []

    tracker = ControllerModeTracker(timeout_seconds=5.0, on_state_change=on_change)

    def arm(seconds: float) -> None:
        armed.append(seconds)

    def cancel() -> None:
        cancelled.append(True)

    tracker.configure_timeout_hooks(arm_timeout=arm, cancel_timeout=cancel)

    tracker.mark_active()
    assert tracker.state == "active"
    assert armed == [5.0]
    assert cancelled == []
    assert events == [("inactive", "active")]

    tracker.mark_inactive()
    assert tracker.state == "inactive"
    assert cancelled  # cancel called when marking inactive
    assert events[-1] == ("active", "inactive")


def test_controller_mode_duplicate_active_resets_timer_only():
    resets = []
    tracker = ControllerModeTracker(timeout_seconds=2.0)

    def arm(seconds: float) -> None:
        resets.append(seconds)

    def cancel() -> None:
        resets.append("cancel")

    tracker.configure_timeout_hooks(arm_timeout=arm, cancel_timeout=cancel)

    tracker.mark_active()
    tracker.mark_active()

    # Expect cancel+arm for second activation, no state change event required
    assert resets == [2.0, "cancel", 2.0]
    assert tracker.state == "active"
