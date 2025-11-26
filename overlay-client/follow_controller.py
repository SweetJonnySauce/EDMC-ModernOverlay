from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from window_tracking import WindowState  # type: ignore


class FollowController:
    """Encapsulates follow-mode polling and WM override state."""

    _WM_OVERRIDE_TTL = 1.25  # seconds

    def __init__(
        self,
        poll_fn: Callable[[], Optional[WindowState]],
        logger,
        tracking_timer,
        *,
        debug_suffix: Callable[[], str],
    ) -> None:
        self._poll_fn = poll_fn
        self._logger = logger
        self._timer = tracking_timer
        self._debug_suffix = debug_suffix
        self._wm_authoritative_rect: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_tracker: Optional[Tuple[int, int, int, int]] = None
        self._wm_override_timestamp: float = 0.0
        self._wm_override_reason: Optional[str] = None
        self._wm_override_classification: Optional[str] = None
        self._last_tracker_state: Optional[Tuple[str, int, int, int, int]] = None
        self._follow_resume_at: float = 0.0
        self._follow_enabled: bool = True
        self._drag_active: bool = False
        self._move_mode: bool = False
        self._last_poll_attempted: bool = False
        self._last_state_missing: bool = False

    # Public API -------------------------------------------------------------

    def set_follow_enabled(self, enabled: bool) -> None:
        self._follow_enabled = bool(enabled)

    def set_drag_state(self, drag_active: bool, move_mode: bool) -> None:
        self._drag_active = drag_active
        self._move_mode = move_mode

    def start(self) -> None:
        if not self._follow_enabled:
            return
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def suspend(self, delay: float = 0.75) -> None:
        self._follow_resume_at = max(self._follow_resume_at, time.monotonic() + max(0.0, delay))

    def reset_resume_window(self) -> None:
        self._follow_resume_at = 0.0

    def refresh(self) -> Optional[WindowState]:
        self._last_poll_attempted = False
        self._last_state_missing = False
        if not self._follow_enabled:
            return None
        now = time.monotonic()
        if self._drag_active or self._move_mode:
            self.suspend(0.75)
            self._logger.debug("Skipping follow refresh: drag/move active; %s", self._debug_suffix())
            return None
        if now < self._follow_resume_at:
            self._logger.debug("Skipping follow refresh: awaiting resume window; %s", self._debug_suffix())
            return None
        try:
            state = self._poll_fn()
            self._last_poll_attempted = True
        except Exception as exc:  # pragma: no cover - defensive guard
            self._logger.debug("Window tracker poll failed: %s; %s", exc, self._debug_suffix())
            return None
        if state is None:
            self._last_state_missing = True
            return None
        global_x = state.global_x if state.global_x is not None else state.x
        global_y = state.global_y if state.global_y is not None else state.y
        tracker_key = (state.identifier, global_x, global_y, state.width, state.height)
        if tracker_key != self._last_tracker_state:
            self._logger.debug(
                "Tracker state: id=%s global=(%d,%d) size=%dx%d foreground=%s visible=%s; %s",
                state.identifier,
                global_x,
                global_y,
                state.width,
                state.height,
                state.is_foreground,
                state.is_visible,
                self._debug_suffix(),
            )
            self._last_tracker_state = tracker_key
        return state

    # WM override state -----------------------------------------------------

    def record_override(
        self,
        rect: Tuple[int, int, int, int],
        tracker_tuple: Optional[Tuple[int, int, int, int]],
        reason: str,
        classification: str = "wm_intervention",
    ) -> None:
        self._wm_authoritative_rect = rect
        self._wm_override_tracker = tracker_tuple
        self._wm_override_timestamp = time.monotonic()
        self._wm_override_reason = reason
        self._wm_override_classification = classification
        self._logger.debug(
            "Recorded WM authoritative rect (%s, classification=%s): actual=%s tracker=%s; %s",
            reason,
            classification,
            rect,
            tracker_tuple,
            self._debug_suffix(),
        )

    def clear_override(self, reason: str) -> None:
        if self._wm_authoritative_rect is None:
            return
        self._logger.debug(
            "Clearing WM authoritative rect (%s); %s",
            reason,
            self._debug_suffix(),
        )
        self._wm_authoritative_rect = None
        self._wm_override_tracker = None
        self._wm_override_timestamp = 0.0
        self._wm_override_reason = None
        self._wm_override_classification = None

    # Accessors -------------------------------------------------------------

    @property
    def wm_override(self) -> Optional[Tuple[int, int, int, int]]:
        return self._wm_authoritative_rect

    @property
    def wm_override_tracker(self) -> Optional[Tuple[int, int, int, int]]:
        return self._wm_override_tracker

    @property
    def wm_override_timestamp(self) -> float:
        return self._wm_override_timestamp

    @property
    def wm_override_classification(self) -> Optional[str]:
        return self._wm_override_classification

    @property
    def last_tracker_state(self) -> Optional[Tuple[str, int, int, int, int]]:
        return self._last_tracker_state

    @property
    def last_poll_attempted(self) -> bool:
        return self._last_poll_attempted

    @property
    def last_state_missing(self) -> bool:
        return self._last_state_missing

    def override_expired(self) -> bool:
        if self._wm_authoritative_rect is None:
            return False
        if self._wm_override_classification in ("layout", "layout_constraint"):
            return False
        return (time.monotonic() - self._wm_override_timestamp) >= self._WM_OVERRIDE_TTL
