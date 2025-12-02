from types import SimpleNamespace

import overlay_controller.overlay_controller as oc


def test_apply_mode_profile_clamps_and_reschedules():
    sent = []

    fake = SimpleNamespace(
        _mode_profile=oc.ControllerModeProfile(
            active=oc.ModeProfile(write_debounce_ms=10, offset_write_debounce_ms=5, status_poll_ms=100, cache_flush_seconds=0.5),
            inactive=oc.ModeProfile(write_debounce_ms=200, offset_write_debounce_ms=200, status_poll_ms=2500, cache_flush_seconds=5.0),
        ),
        _current_mode_profile=None,
        _status_poll_handle="handle",
        after=lambda ms, cb: sent.append(ms) or "new_handle",
        _debounce_handles={},
        _cancel_status_poll=lambda: sent.append("cancel"),
        _write_debounce_ms=None,
        _offset_write_debounce_ms=None,
        _status_poll_interval_ms=None,
        _poll_cache_and_status=lambda: None,
    )

    oc.OverlayConfigApp._apply_mode_profile(fake, "active", reason="test")

    # Clamped minimums applied
    assert fake._write_debounce_ms == 25
    assert fake._offset_write_debounce_ms == 25
    assert fake._status_poll_interval_ms == 250
    # Cancel then after scheduled
    assert sent == ["cancel", 250]
    assert fake._status_poll_handle == "new_handle"
