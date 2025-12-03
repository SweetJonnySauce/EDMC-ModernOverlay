from overlay_client.controller_mode import ControllerModeProfile, ModeProfile
from overlay_client.setup_surface import SetupSurfaceMixin


def test_apply_controller_mode_profile_updates_cache_debounce():
    logs = []

    class Dummy(SetupSurfaceMixin):  # type: ignore[misc]
        def __init__(self):
            # Provide just the attributes used by _apply_controller_mode_profile
            self._mode_profile_overrides = {}
            self._mode_profile = ControllerModeProfile(
                active=ModeProfile(
                    write_debounce_ms=50,
                    offset_write_debounce_ms=50,
                    status_poll_ms=750,
                    cache_flush_seconds=0.5,
                ),
                inactive=ModeProfile(
                    write_debounce_ms=200,
                    offset_write_debounce_ms=200,
                    status_poll_ms=2500,
                    cache_flush_seconds=5.0,
                ),
                logger=lambda msg, *args: logs.append(msg % args if args else msg),
            )
            self._current_mode_profile = None
            self._cache_debounce_updates = []

        def _set_group_cache_debounce(self, debounce_seconds: float) -> None:
            self._cache_debounce_updates.append(debounce_seconds)

    dummy = Dummy()

    dummy._apply_controller_mode_profile("active", reason="test-active")
    assert dummy._cache_debounce_updates == [0.5]
    assert dummy._current_mode_profile.cache_flush_seconds == 0.5

    # Applying the same profile should no-op and not append
    dummy._apply_controller_mode_profile("active", reason="unchanged")
    assert dummy._cache_debounce_updates == [0.5]

    # Switching to inactive updates debounce
    dummy._apply_controller_mode_profile("inactive", reason="test-inactive")
    assert dummy._cache_debounce_updates == [0.5, 5.0]
    assert dummy._current_mode_profile.cache_flush_seconds == 5.0
