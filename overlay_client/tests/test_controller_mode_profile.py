from overlay_client.controller_mode import ControllerModeProfile, ModeProfile


def test_controller_mode_profile_resolves_and_overrides():
    profile = ControllerModeProfile(
        active=ModeProfile(write_debounce_ms=75, offset_write_debounce_ms=75, status_poll_ms=750, cache_flush_seconds=1.0),
        inactive=ModeProfile(
            write_debounce_ms=200,
            offset_write_debounce_ms=200,
            status_poll_ms=2500,
            cache_flush_seconds=5.0,
        ),
    )

    active = profile.resolve("active")
    assert active.write_debounce_ms == 75
    assert active.cache_flush_seconds == 1.0

    overrides = {
        "write_debounce_ms": 5,
        "offset_write_debounce_ms": 2,
        "status_poll_ms": 10,
        "cache_flush_seconds": 0.01,
    }
    inactive = profile.resolve("inactive", overrides)
    # Overrides apply but respect minimum clamps.
    assert inactive.write_debounce_ms == 10
    assert inactive.offset_write_debounce_ms == 10
    assert inactive.status_poll_ms == 100
    assert inactive.cache_flush_seconds == 0.05

