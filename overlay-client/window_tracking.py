"""Cross-platform helpers for tracking the Elite Dangerous game window."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(slots=True)
class WindowState:
    """Geometry details for a tracked window in virtual desktop coordinates."""

    x: int
    y: int
    width: int
    height: int
    is_foreground: bool
    is_visible: bool
    identifier: str = ""


class WindowTracker(Protocol):
    """Simple protocol for retrieving Elite window state."""

    def poll(self) -> Optional[WindowState]:
        ...


def create_elite_window_tracker(logger: logging.Logger, title_hint: str = "elite - dangerous") -> Optional[WindowTracker]:
    """Instantiate a platform-specific tracker for the Elite client."""

    platform = sys.platform
    if platform.startswith("win"):
        try:
            tracker: Optional[WindowTracker] = _WindowsTracker(logger, title_hint)
            return tracker
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Windows tracker unavailable: %s", exc)
            return None
    if platform.startswith("linux"):
        try:
            return _WmctrlTracker(logger, title_hint)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("X11 tracker unavailable: %s", exc)
            return None

    logger.info("Window tracking not implemented for platform '%s'; follow mode disabled", platform)
    return None


try:
    import ctypes
    from ctypes import wintypes
except Exception:  # pragma: no cover - non-Windows platform
    ctypes = None
    wintypes = None


class _WindowsTracker:
    """Locate Elite - Dangerous windows using Win32 APIs."""

    def __init__(self, logger: logging.Logger, title_hint: str) -> None:
        if ctypes is None or wintypes is None:
            raise RuntimeError("ctypes is unavailable; cannot create Windows tracker")
        self._logger = logger
        self._title_hint = title_hint.lower()
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._last_hwnd: Optional[int] = None
        self._enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(self._enum_windows)

    def poll(self) -> Optional[WindowState]:
        hwnd = self._resolve_window()
        if hwnd is None:
            return None
        rect = _RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            self._logger.debug("GetWindowRect failed for hwnd=%s", hex(hwnd))
            return None
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width = max(0, right - left)
        height = max(0, bottom - top)
        if width <= 0 or height <= 0:
            return None
        foreground = self._user32.GetForegroundWindow()
        is_foreground = foreground and hwnd == foreground
        is_visible = bool(self._user32.IsWindowVisible(hwnd)) and not bool(self._user32.IsIconic(hwnd))
        identifier = hex(hwnd)
        return WindowState(
            x=int(left),
            y=int(top),
            width=int(width),
            height=int(height),
            is_foreground=bool(is_foreground),
            is_visible=is_visible,
            identifier=identifier,
        )

    # Internal helpers -------------------------------------------------

    def _resolve_window(self) -> Optional[int]:
        hwnd = self._last_hwnd
        if hwnd and self._is_target(hwnd):
            return hwnd
        self._last_hwnd = None
        self._user32.EnumWindows(self._enum_proc, 0)
        return self._last_hwnd

    def _enum_windows(self, hwnd: int, _: int) -> bool:
        if self._is_target(hwnd):
            self._last_hwnd = hwnd
            return False
        return True

    def _is_target(self, hwnd: int) -> bool:
        if not self._user32.IsWindow(hwnd):
            return False
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return False
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip().lower()
        if not title:
            return False
        if self._title_hint not in title:
            return False
        if not self._user32.IsWindowVisible(hwnd):
            return False
        return True


class _RECT(ctypes.Structure):  # type: ignore[misc]
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _WmctrlTracker:
    """Use wmctrl/xprop to locate Elite windows under X11."""

    _match_re = re.compile(r"elite\s*-\s*dangerous", re.IGNORECASE)

    def __init__(self, logger: logging.Logger, title_hint: str) -> None:
        self._logger = logger
        self._title_hint = title_hint
        self._last_state: Optional[WindowState] = None
        self._last_refresh: float = 0.0
        self._min_interval: float = 0.3
        self._wmctrl_missing = False

    def poll(self) -> Optional[WindowState]:
        if self._wmctrl_missing:
            return None
        now = time.monotonic()
        if self._last_state and now - self._last_refresh < self._min_interval:
            return self._last_state
        try:
            result = subprocess.run(
                ["wmctrl", "-lGx"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
        except FileNotFoundError:
            self._wmctrl_missing = True
            self._logger.warning("wmctrl binary not found; overlay follow mode disabled")
            self._last_state = None
            return None
        except subprocess.SubprocessError as exc:
            self._logger.debug("wmctrl invocation failed: %s", exc)
            self._last_state = None
            self._last_refresh = now
            return None

        self._last_refresh = now
        if result.returncode != 0:
            self._logger.debug("wmctrl returned non-zero status: %s", result.returncode)
            self._last_state = None
            return None

        active_id = self._active_window_id()
        target_state: Optional[WindowState] = None
        for line in result.stdout.splitlines():
            fields = line.split(None, 8)
            if len(fields) < 9:
                continue
            win_id_hex, desktop, x, y, w, h, wm_class, host, title = fields
            if not self._matches_title(title):
                continue
            try:
                x_val = int(x)
                y_val = int(y)
                width = int(w)
                height = int(h)
                win_id = int(win_id_hex, 16)
            except ValueError:
                continue
            is_foreground = active_id is not None and win_id == active_id
            is_visible = width > 0 and height > 0
            target_state = WindowState(
                x=x_val,
                y=y_val,
                width=width,
                height=height,
                is_foreground=is_foreground,
                is_visible=is_visible,
                identifier=win_id_hex,
            )
            break

        self._last_state = target_state
        return target_state

    # Internal helpers -------------------------------------------------

    def _matches_title(self, title: str) -> bool:
        if not title:
            return False
        hint = self._title_hint.lower()
        if hint and hint in title.lower():
            return True
        return bool(self._match_re.search(title))

    def _active_window_id(self) -> Optional[int]:
        try:
            result = subprocess.run(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.5,
            )
        except FileNotFoundError:
            return None
        except subprocess.SubprocessError:
            return None
        if result.returncode != 0 or not result.stdout:
            return None
        match = re.search(r"0x[0-9a-fA-F]+", result.stdout)
        if not match:
            return None
        try:
            return int(match.group(0), 16)
        except ValueError:
            return None
