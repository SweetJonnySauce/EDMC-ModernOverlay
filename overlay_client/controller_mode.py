from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional


@dataclass(frozen=True)
class ModeProfile:
    """Container for per-mode timing settings."""

    write_debounce_ms: int
    offset_write_debounce_ms: int
    status_poll_ms: int
    cache_flush_seconds: float


class ControllerModeProfile:
    """Resolves mode-specific timing profiles with optional overrides."""

    def __init__(
        self,
        *,
        active: ModeProfile,
        inactive: ModeProfile,
        logger: Optional[Callable[..., None]] = None,
    ) -> None:
        self._active = active
        self._inactive = inactive
        self._logger = logger

    def resolve(self, mode: str, overrides: Optional[Mapping[str, object]] = None) -> ModeProfile:
        base = self._active if mode == "active" else self._inactive
        if not overrides:
            return base
        return ModeProfile(
            write_debounce_ms=self._coerce_int(
                overrides.get("write_debounce_ms"), base.write_debounce_ms, minimum=10
            ),
            offset_write_debounce_ms=self._coerce_int(
                overrides.get("offset_write_debounce_ms"), base.offset_write_debounce_ms, minimum=10
            ),
            status_poll_ms=self._coerce_int(overrides.get("status_poll_ms"), base.status_poll_ms, minimum=100),
            cache_flush_seconds=self._coerce_float(
                overrides.get("cache_flush_seconds"), base.cache_flush_seconds, minimum=0.05
            ),
        )

    def log_profile(self, mode: str, profile: ModeProfile, reason: Optional[str] = None) -> None:
        reason_suffix = f" ({reason})" if reason else ""
        self._log(
            "Controller mode profile%s: mode=%s write_debounce_ms=%d offset_debounce_ms=%d status_poll_ms=%d cache_flush=%.2fs",
            reason_suffix,
            mode,
            profile.write_debounce_ms,
            profile.offset_write_debounce_ms,
            profile.status_poll_ms,
            profile.cache_flush_seconds,
        )

    def _log(self, message: str, *args: object) -> None:
        logger = self._logger
        if logger is None:
            return
        try:
            logger(message, *args)
        except Exception:
            pass

    @staticmethod
    def _coerce_int(raw: object, fallback: int, *, minimum: int) -> int:
        try:
            value = int(raw)  # type: ignore[call-overload]
        except Exception:
            value = fallback
        return max(minimum, value)

    @staticmethod
    def _coerce_float(raw: object, fallback: float, *, minimum: float) -> float:
        try:
            value = float(raw)  # type: ignore[call-overload]
        except Exception:
            value = fallback
        return max(minimum, value)


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
