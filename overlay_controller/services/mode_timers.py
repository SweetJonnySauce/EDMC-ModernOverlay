from __future__ import annotations

import time
from typing import Callable, Optional

from overlay_client.controller_mode import ControllerModeProfile, ModeProfile

AfterFn = Callable[[int, Callable[[], None]], object]
AfterCancelFn = Callable[[object], None]
LoggerFn = Callable[[str, object], None] | Callable[[str], None]


def _noop_log(message: str, *args: object) -> None:
    return None


class ModeTimers:
    """Owns mode profile application, poll scheduling, debounce helpers, and live-edit guard."""

    def __init__(
        self,
        mode_profile: ControllerModeProfile,
        *,
        after: AfterFn,
        after_cancel: AfterCancelFn,
        time_source: Callable[[], float] = time.time,
        logger: Optional[LoggerFn] = None,
    ) -> None:
        self._mode_profile = mode_profile
        self._after = after
        self._after_cancel = after_cancel
        self._time = time_source
        self._logger = logger or _noop_log

        self._current_mode_profile: ModeProfile = mode_profile.resolve("active")
        self.write_debounce_ms = self._clamp_write(self._current_mode_profile.write_debounce_ms)
        self.offset_write_debounce_ms = self._clamp_write(self._current_mode_profile.offset_write_debounce_ms)
        self.status_poll_interval_ms = self._clamp_poll(self._current_mode_profile.status_poll_ms)
        self.cache_flush_seconds = float(self._current_mode_profile.cache_flush_seconds)

        self._status_poll_handle: object | None = None
        self._poll_callback: Callable[[], None] | None = None
        self._debounce_handles: dict[str, object] = {}
        self._live_edit_until: float = 0.0
        self._last_edit_ts: float = 0.0

    def apply_mode(self, mode: str, *, reason: str = "apply") -> ModeProfile:
        profile = self._mode_profile.resolve(mode)
        if profile == self._current_mode_profile:
            self._log(
                "Mode unchanged (%s): write=%d offset=%d poll=%d reason=%s",
                mode,
                profile.write_debounce_ms,
                profile.offset_write_debounce_ms,
                profile.status_poll_ms,
                reason,
            )
            return profile
        self._current_mode_profile = profile
        self.write_debounce_ms = self._clamp_write(profile.write_debounce_ms)
        self.offset_write_debounce_ms = self._clamp_write(profile.offset_write_debounce_ms)
        self.status_poll_interval_ms = self._clamp_poll(profile.status_poll_ms)
        self.cache_flush_seconds = float(profile.cache_flush_seconds)
        rescheduled = False
        if self._status_poll_handle is not None:
            self.stop_status_poll()
            self._status_poll_handle = self._after(self.status_poll_interval_ms, self._run_status_poll)
            rescheduled = True
        self._log(
            "Mode applied (%s): write=%d offset=%d poll=%d rescheduled=%s reason=%s",
            mode,
            profile.write_debounce_ms,
            profile.offset_write_debounce_ms,
            profile.status_poll_ms,
            rescheduled,
            reason,
        )
        return profile

    def start_status_poll(self, callback: Callable[[], None]) -> object:
        self._poll_callback = callback
        self.stop_status_poll()
        self._status_poll_handle = self._after(self.status_poll_interval_ms, self._run_status_poll)
        return self._status_poll_handle

    def stop_status_poll(self) -> None:
        handle = self._status_poll_handle
        self._status_poll_handle = None
        if handle is not None:
            try:
                self._after_cancel(handle)
            except Exception:
                pass

    def _run_status_poll(self) -> None:
        self._status_poll_handle = None
        try:
            if self._poll_callback is not None:
                self._poll_callback()
        finally:
            self._status_poll_handle = self._after(self.status_poll_interval_ms, self._run_status_poll)

    def schedule_debounce(self, key: str, callback: Callable[[], None], *, delay_ms: int | None = None) -> object:
        existing = self._debounce_handles.pop(key, None)
        if existing is not None:
            try:
                self._after_cancel(existing)
            except Exception:
                pass
        delay = self.write_debounce_ms if delay_ms is None else delay_ms
        handle = self._after(delay, callback)
        self._debounce_handles[key] = handle
        return handle

    def cancel_debounce(self, key: str) -> None:
        handle = self._debounce_handles.pop(key, None)
        if handle is None:
            return
        try:
            self._after_cancel(handle)
        except Exception:
            pass

    def schedule_offset_debounce(self, key: str, callback: Callable[[], None], *, delay_ms: int | None = None) -> object:
        delay = self.offset_write_debounce_ms if delay_ms is None else delay_ms
        return self.schedule_debounce(key, callback, delay_ms=delay)

    def record_edit(self) -> None:
        self._last_edit_ts = self._time()

    def should_reload_after_edit(self, *, delay_seconds: float) -> bool:
        if self._last_edit_ts <= 0.0:
            return True
        return (self._time() - self._last_edit_ts) > max(0.0, delay_seconds)

    def start_live_edit_window(self, duration_seconds: float) -> None:
        now = self._time()
        deadline = now + max(0.0, duration_seconds)
        if deadline > self._live_edit_until:
            self._live_edit_until = deadline

    def live_edit_active(self) -> bool:
        return self._time() < self._live_edit_until

    @staticmethod
    def _clamp_write(value: int) -> int:
        return max(25, int(value))

    @staticmethod
    def _clamp_poll(value: int) -> int:
        return max(50, int(value))

    def _log(self, message: str, *args: object) -> None:
        try:
            self._logger(message, *args)
        except TypeError:
            try:
                self._logger(message % args if args else message)
            except Exception:
                pass
        except Exception:
            pass
