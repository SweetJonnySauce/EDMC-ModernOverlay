"""Cross-platform helpers for tracking the Elite Dangerous game window."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple


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
    global_x: Optional[int] = None
    global_y: Optional[int] = None


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
    """Use wmctrl/xwininfo to locate Elite windows under X11."""

    _match_re = re.compile(r"elite\s*-\s*dangerous", re.IGNORECASE)

    def __init__(self, logger: logging.Logger, title_hint: str) -> None:
        self._logger = logger
        self._title_hint = title_hint
        self._last_state: Optional[WindowState] = None
        self._last_refresh: float = 0.0
        self._min_interval: float = 0.3
        self._wmctrl_missing = False
        self._last_logged_identifier: Optional[str] = None
        self._monitor_offsets = self._load_monitor_offsets()
        if self._monitor_offsets:
            self._logger.debug("Detected monitor offsets: %s", self._monitor_offsets)

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
        best_state: Optional[WindowState] = None
        best_area = 0
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
            candidate = WindowState(
                x=x_val,
                y=y_val,
                width=width,
                height=height,
                is_foreground=is_foreground,
                is_visible=is_visible,
                identifier=win_id_hex,
            )
            if is_foreground:
                target_state = candidate
                break
            area = max(width, 0) * max(height, 0)
            if area > best_area:
                best_state = candidate
                best_area = area

        if target_state is None:
            target_state = best_state

        if target_state is None:
            if self._last_logged_identifier is not None:
                self._logger.debug("wmctrl tracker did not locate an Elite Dangerous window")
                self._last_logged_identifier = None
            self._last_state = None
            return None

        augmented = self._augment_with_global_coordinates(target_state)
        self._last_state = augmented
        return augmented

    # Internal helpers -------------------------------------------------

    def _augment_with_global_coordinates(self, state: WindowState) -> WindowState:
        geometry = self._absolute_geometry(state.identifier)
        abs_x: Optional[int]
        abs_y: Optional[int]
        width = state.width
        height = state.height
        if geometry is not None:
            abs_x, abs_y, abs_width, abs_height = geometry
            if abs_width:
                width = abs_width
            if abs_height:
                height = abs_height
        else:
            abs_x = None
            abs_y = None

        monitor_info = None
        if abs_x is not None and abs_y is not None and self._monitor_offsets:
            monitor_info = self._find_monitor_for_rect(abs_x, abs_y, width, height, relative=False)
        if monitor_info is None and self._monitor_offsets:
            monitor_info = self._find_monitor_for_rect(state.x, state.y, state.width, state.height, relative=True)

        if monitor_info is not None:
            name, offset_x, offset_y, mon_w, mon_h = monitor_info
            global_x = abs_x if abs_x is not None else state.x + offset_x
            global_y = abs_y if abs_y is not None else state.y + offset_y
            if abs_x is None or abs_y is None or (global_x, global_y) != (abs_x, abs_y):
                self._logger.debug(
                    "Monitor %s offsets applied: offset=(%d,%d) raw=(%s,%s) global=(%d,%d) size=%dx%d",
                    name,
                    offset_x,
                    offset_y,
                    abs_x if abs_x is not None else "n/a",
                    abs_y if abs_y is not None else "n/a",
                    global_x,
                    global_y,
                    mon_w,
                    mon_h,
                )
            abs_x = global_x
            abs_y = global_y

        if abs_x is None or abs_y is None:
            return WindowState(
                x=state.x,
                y=state.y,
                width=width,
                height=height,
                is_foreground=state.is_foreground,
                is_visible=state.is_visible,
                identifier=state.identifier,
                global_x=None,
                global_y=None,
            )

        return WindowState(
            x=abs_x,
            y=abs_y,
            width=width,
            height=height,
            is_foreground=state.is_foreground,
            is_visible=state.is_visible,
            identifier=state.identifier,
            global_x=abs_x,
            global_y=abs_y,
        )

    def _find_monitor_for_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        relative: bool,
    ) -> Optional[Tuple[str, int, int, int, int]]:
        if not self._monitor_offsets:
            return None
        best: Optional[Tuple[str, int, int, int, int]] = None
        best_area = 0
        for name, offset_x, offset_y, mon_w, mon_h in self._monitor_offsets:
            global_x = x + offset_x if relative else x
            global_y = y + offset_y if relative else y
            overlap_w = max(0, min(global_x + width, offset_x + mon_w) - max(global_x, offset_x))
            overlap_h = max(0, min(global_y + height, offset_y + mon_h) - max(global_y, offset_y))
            area = overlap_w * overlap_h
            if area > best_area:
                best_area = area
                best = (name, offset_x, offset_y, mon_w, mon_h)
        return best

    def _load_monitor_offsets(self) -> List[Tuple[str, int, int, int, int]]:
        if not sys.platform.startswith("linux"):
            return []
        try:
            result = subprocess.run(
                ["xrandr", "--listmonitors"],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.5,
            )
        except FileNotFoundError:
            self._logger.debug("xrandr binary not found; monitor offsets unavailable")
            return []
        except subprocess.SubprocessError as exc:
            self._logger.debug("xrandr invocation failed: %s", exc)
            return []
        if result.returncode != 0 or not result.stdout:
            self._logger.debug("xrandr --listmonitors returned status %s", result.returncode)
            return []

        monitors: List[Tuple[str, int, int, int, int]] = []
        pattern = re.compile(r"\s*\d+:\s+\+[*-]?([\w.-]+)\s+(\d+)/(?:\d+)x(\d+)/(?:\d+)\+(-?\d+)\+(-?\d+)")
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            try:
                name = match.group(1)
                width = int(match.group(2))
                height = int(match.group(3))
                offset_x = int(match.group(4))
                offset_y = int(match.group(5))
            except ValueError:
                continue
            monitors.append((name, offset_x, offset_y, width, height))
        return monitors

    def _absolute_geometry(self, win_id_hex: str) -> Optional[Tuple[int, int, int, int]]:
        try:
            result = subprocess.run(
                ["xwininfo", "-id", win_id_hex],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.5,
            )
        except FileNotFoundError:
            return None
        except subprocess.SubprocessError as exc:
            self._logger.debug("xwininfo invocation failed: %s", exc)
            return None
        if result.returncode != 0:
            self._logger.debug(
                "xwininfo returned non-zero status %s for window %s",
                result.returncode,
                win_id_hex,
            )
            return None
        if win_id_hex != self._last_logged_identifier:
            self._logger.debug("xwininfo dump for %s:\n%s", win_id_hex, result.stdout.strip())
            self._last_logged_identifier = win_id_hex
        abs_x = abs_y = width = height = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Absolute upper-left X:"):
                try:
                    abs_x = int(line.split(":", 1)[1])
                except ValueError:
                    abs_x = None
            elif line.startswith("Absolute upper-left Y:"):
                try:
                    abs_y = int(line.split(":", 1)[1])
                except ValueError:
                    abs_y = None
            elif line.startswith("Width:"):
                try:
                    width = int(line.split(":", 1)[1])
                except ValueError:
                    width = None
            elif line.startswith("Height:"):
                try:
                    height = int(line.split(":", 1)[1])
                except ValueError:
                    height = None
            if abs_x is not None and abs_y is not None and width is not None and height is not None:
                break
        if abs_x is None or abs_y is None:
            return None
        return abs_x, abs_y, width or 0, height or 0

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
