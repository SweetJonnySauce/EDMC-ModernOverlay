from __future__ import annotations

from typing import Callable, Optional


class ControllerModeTracker:
    """Tracks controller Active/Inactive state with a timeout-based heartbeat."""

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        on_state_change: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._state: str = "inactive"
        self._timeout_seconds = max(0.5, float(timeout_seconds))
        self._on_state_change = on_state_change
        self._arm_timeout: Optional[Callable[[float], None]] = None
        self._cancel_timeout: Optional[Callable[[], None]] = None

    @property
    def state(self) -> str:
        return self._state

    def configure_timeout_hooks(
        self,
        *,
        arm_timeout: Callable[[float], None],
        cancel_timeout: Callable[[], None],
    ) -> None:
        self._arm_timeout = arm_timeout
        self._cancel_timeout = cancel_timeout

    def mark_active(self) -> None:
        previous = self._state
        self._state = "active"
        if self._cancel_timeout is not None and previous == "active":
            try:
                self._cancel_timeout()
            except Exception:
                pass
        if self._arm_timeout is not None:
            try:
                self._arm_timeout(self._timeout_seconds)
            except Exception:
                pass
        if self._on_state_change is not None and previous != self._state:
            try:
                self._on_state_change(previous, self._state)
            except Exception:
                pass

    def mark_inactive(self) -> None:
        previous = self._state
        self._state = "inactive"
        if self._cancel_timeout is not None:
            try:
                self._cancel_timeout()
            except Exception:
                pass
        if self._on_state_change is not None and previous != self._state:
            try:
                self._on_state_change(previous, self._state)
            except Exception:
                pass
