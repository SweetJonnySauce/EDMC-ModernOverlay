"""Cross-platform helpers for tracking the Elite Dangerous game window."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Protocol, Tuple


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


MonitorSnapshot = Tuple[str, int, int, int, int]
MonitorProvider = Callable[[], List[MonitorSnapshot]]

_TITLE_PATTERN = re.compile(r"elite\s*-\s*dangerous", re.IGNORECASE)
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _matches_window_title(title: str, hint: str) -> bool:
    if not title:
        return False
    lowered = title.lower()
    if hint and hint in lowered:
        return True
    return bool(_TITLE_PATTERN.search(title))


def _invoke_monitor_provider(provider: Optional[MonitorProvider], logger: logging.Logger) -> List[MonitorSnapshot]:
    if provider is None:
        return []
    try:
        snapshot = provider()
    except Exception as exc:
        logger.debug("Monitor provider failed: %s", exc)
        return []
    return list(snapshot)


def _find_monitor_for_rect(
    monitors: List[MonitorSnapshot],
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    relative: bool,
) -> Optional[MonitorSnapshot]:
    best: Optional[MonitorSnapshot] = None
    best_area = 0
    for name, offset_x, offset_y, mon_w, mon_h in monitors:
        global_x = x + offset_x if relative else x
        global_y = y + offset_y if relative else y
        overlap_w = max(0, min(global_x + width, offset_x + mon_w) - max(global_x, offset_x))
        overlap_h = max(0, min(global_y + height, offset_y + mon_h) - max(global_y, offset_y))
        area = overlap_w * overlap_h
        if area > best_area:
            best_area = area
            best = (name, offset_x, offset_y, mon_w, mon_h)
    return best


def _augment_state_with_monitors(
    state: WindowState,
    monitors: List[MonitorSnapshot],
    logger: logging.Logger,
    *,
    absolute_geometry: Optional[Tuple[int, int, int, int]] = None,
) -> WindowState:
    width = state.width
    height = state.height
    abs_x: Optional[int]
    abs_y: Optional[int]

    if absolute_geometry is not None:
        abs_x, abs_y, abs_width, abs_height = absolute_geometry
        if abs_width:
            width = abs_width
        if abs_height:
            height = abs_height
    else:
        abs_x = None
        abs_y = None

    monitor_info = None
    if abs_x is not None and abs_y is not None and monitors:
        monitor_info = _find_monitor_for_rect(monitors, abs_x, abs_y, width, height, relative=False)
    if monitor_info is None and monitors:
        monitor_info = _find_monitor_for_rect(monitors, state.x, state.y, state.width, state.height, relative=True)

    if monitor_info is not None:
        name, offset_x, offset_y, mon_w, mon_h = monitor_info
        global_x = abs_x if abs_x is not None else state.x + offset_x
        global_y = abs_y if abs_y is not None else state.y + offset_y
        if abs_x is None or abs_y is None or (global_x, global_y) != (abs_x, abs_y):
            logger.debug(
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


class WindowTracker(Protocol):
    """Simple protocol for retrieving Elite window state."""

    def poll(self) -> Optional[WindowState]:
        ...

    def set_monitor_provider(self, provider: Optional[MonitorProvider]) -> None:
        ...


def create_elite_window_tracker(
    logger: logging.Logger,
    title_hint: str = "elite - dangerous",
    monitor_provider: Optional[MonitorProvider] = None,
) -> Optional[WindowTracker]:
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
        session = (os.environ.get("EDMC_OVERLAY_SESSION_TYPE") or os.environ.get("XDG_SESSION_TYPE") or "").lower()
        compositor = (os.environ.get("EDMC_OVERLAY_COMPOSITOR") or "").lower()
        force_xwayland = os.environ.get("EDMC_OVERLAY_FORCE_XWAYLAND") == "1"
        if session == "wayland" and not force_xwayland:
            tracker = _create_wayland_tracker(logger, title_hint, monitor_provider, compositor)
            if tracker is not None:
                return tracker
            logger.debug(
                "Wayland compositor '%s' not yet supported for follow mode; attempting X11 fallback",
                compositor or "unknown",
            )
        try:
            return _WmctrlTracker(logger, title_hint, monitor_provider)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("X11 tracker unavailable: %s", exc)
            return None

    logger.info("Window tracking not implemented for platform '%s'; follow mode disabled", platform)
    return None


def _create_wayland_tracker(
    logger: logging.Logger,
    title_hint: str,
    monitor_provider: Optional[MonitorProvider],
    compositor_hint: str,
) -> Optional[WindowTracker]:
    compositor = (compositor_hint or "").lower()
    env = os.environ
    if not compositor:
        if env.get("SWAYSOCK"):
            compositor = "sway"
        elif env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            compositor = "hyprland"
        elif "KDE" in (env.get("XDG_CURRENT_DESKTOP") or "").upper() or env.get("KDE_FULL_SESSION"):
            compositor = "kwin"
        elif "GNOME" in (env.get("XDG_CURRENT_DESKTOP") or "").upper() or env.get("GNOME_SHELL_SESSION_MODE"):
            compositor = "gnome-shell"
    if compositor in {"sway", "wlroots", "wayfire"}:
        return _SwayTracker(logger, title_hint, monitor_provider)
    if compositor == "hyprland":
        return _HyprlandTracker(logger, title_hint, monitor_provider)
    if compositor == "kwin":
        return _KWinTracker(logger, title_hint, monitor_provider)
    if compositor in {"gnome-shell", "mutter"}:
        logger.info(
            "GNOME Shell Wayland compositor detected; follow mode requires the EDMC Modern Overlay GNOME extension."
        )
        return None
    if compositor == "cosmic":
        logger.info("COSMIC Wayland compositor detected; follow mode backend not yet implemented.")
        return None
    if compositor:
        logger.info("No Wayland tracker available for compositor '%s'", compositor)
    else:
        logger.info("Wayland compositor not reported; no follow-mode backend selected")
    return None


ctypes: Any
wintypes: Any
try:
    import ctypes as _ctypes
    from ctypes import wintypes as _wintypes

    ctypes = _ctypes
    wintypes = _wintypes
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
        try:
            dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
            self._dwm_get_window_attribute = dwmapi.DwmGetWindowAttribute
            self._dwm_get_window_attribute.argtypes = [  # type: ignore[attr-defined]
                wintypes.HWND,
                ctypes.c_uint,
                ctypes.POINTER(_RECT),
                ctypes.c_uint,
            ]
            self._dwm_get_window_attribute.restype = ctypes.c_int  # type: ignore[attr-defined]
        except Exception:
            self._dwm_get_window_attribute = None
        self._last_hwnd: Optional[int] = None
        self._enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(self._enum_windows)

    def poll(self) -> Optional[WindowState]:
        hwnd = self._resolve_window()
        if hwnd is None:
            return None
        rect = self._window_bounds(hwnd)
        if rect is None:
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

    def set_monitor_provider(self, provider: Optional[MonitorProvider]) -> None:
        # Monitor offsets are only used on X11/Wayland; Windows tracker ignores this hook.
        return None

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

    def _window_bounds(self, hwnd: int) -> Optional[_RECT]:
        rect = _RECT()
        if self._dwm_get_window_attribute is not None:
            result = self._dwm_get_window_attribute(
                hwnd,
                ctypes.c_uint(_DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result == 0:
                return rect
            self._logger.debug("DwmGetWindowAttribute failed with %s; falling back to GetWindowRect", result)
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            self._logger.debug("GetWindowRect failed for hwnd=%s", hex(hwnd))
            return None
        return rect

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

    def __init__(
        self,
        logger: logging.Logger,
        title_hint: str,
        monitor_provider: Optional[MonitorProvider],
    ) -> None:
        self._logger = logger
        self._title_hint = title_hint.lower()
        self._last_state: Optional[WindowState] = None
        self._last_refresh: float = 0.0
        self._min_interval: float = 0.3
        self._wmctrl_missing = False
        self._last_logged_identifier: Optional[str] = None
        self._monitor_provider = monitor_provider

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

        monitor_offsets = _invoke_monitor_provider(self._monitor_provider, self._logger)
        augmented = self._augment_with_global_coordinates(target_state, monitor_offsets)
        self._last_state = augmented
        return augmented

    # Internal helpers -------------------------------------------------

    def set_monitor_provider(self, provider: Optional[MonitorProvider]) -> None:
        self._monitor_provider = provider

    def _augment_with_global_coordinates(
        self,
        state: WindowState,
        monitor_offsets: List[MonitorSnapshot],
    ) -> WindowState:
        geometry = self._absolute_geometry(state.identifier) if monitor_offsets else None
        return _augment_state_with_monitors(
            state,
            monitor_offsets,
            self._logger,
            absolute_geometry=geometry,
        )

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
        return _matches_window_title(title, self._title_hint)

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


class _WaylandTrackerBase:
    """Shared helpers for Wayland-based trackers."""

    def __init__(
        self,
        logger: logging.Logger,
        title_hint: str,
        monitor_provider: Optional[MonitorProvider],
    ) -> None:
        self._logger = logger
        self._title_hint = title_hint.lower()
        self._monitor_provider = monitor_provider
        self._last_state: Optional[WindowState] = None
        self._last_refresh: float = 0.0
        self._refresh_interval: float = 0.3

    def set_monitor_provider(self, provider: Optional[MonitorProvider]) -> None:
        self._monitor_provider = provider

    def _maybe_use_cache(self) -> Optional[WindowState]:
        now = time.monotonic()
        if self._last_state is not None and now - self._last_refresh < self._refresh_interval:
            return self._last_state
        self._last_refresh = now
        return None

    def _complete(self, state: Optional[WindowState]) -> Optional[WindowState]:
        self._last_state = state
        return state

    def _monitors(self) -> List[MonitorSnapshot]:
        return _invoke_monitor_provider(self._monitor_provider, self._logger)

    def _matches(self, title: str) -> bool:
        return _matches_window_title(title, self._title_hint)


class _SwayTracker(_WaylandTrackerBase):
    """Use swaymsg on wlroots compositors such as Sway or Wayfire."""

    def __init__(
        self,
        logger: logging.Logger,
        title_hint: str,
        monitor_provider: Optional[MonitorProvider],
    ) -> None:
        super().__init__(logger, title_hint, monitor_provider)
        self._binary_missing = False

    def poll(self) -> Optional[WindowState]:
        cached = self._maybe_use_cache()
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                ["swaymsg", "-t", "get_tree"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
        except FileNotFoundError:
            if not self._binary_missing:
                self._logger.warning("swaymsg not found; Wayland follow mode disabled for wlroots compositor")
                self._binary_missing = True
            return self._complete(None)
        except subprocess.SubprocessError as exc:
            self._logger.debug("swaymsg invocation failed: %s", exc)
            return self._complete(None)

        if result.returncode != 0 or not result.stdout:
            self._logger.debug("swaymsg returned status %s", result.returncode)
            return self._complete(None)

        try:
            tree = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self._logger.debug("Failed to parse sway tree JSON: %s", exc)
            return self._complete(None)

        focused, fallback = self._extract_window(tree)
        state = focused or fallback
        if state is None:
            return self._complete(None)

        monitors = self._monitors()
        augmented = _augment_state_with_monitors(state, monitors, self._logger)
        return self._complete(augmented)

    def _extract_window(self, root: dict) -> Tuple[Optional[WindowState], Optional[WindowState]]:
        target: Optional[WindowState] = None
        best: Optional[WindowState] = None
        best_area = 0
        stack = [root]
        while stack:
            node = stack.pop()
            name = node.get("name") or ""
            if self._matches(name):
                rect = node.get("rect") or {}
                try:
                    x = int(rect.get("x", 0))
                    y = int(rect.get("y", 0))
                    width = int(rect.get("width", 0))
                    height = int(rect.get("height", 0))
                except (TypeError, ValueError):
                    width = height = 0
                    x = y = 0
                if width > 0 and height > 0:
                    identifier = str(node.get("id", ""))
                    state = WindowState(
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        is_foreground=bool(node.get("focused")),
                        is_visible=True,
                        identifier=identifier,
                    )
                    if node.get("focused"):
                        return state, best
                    area = width * height
                    if area > best_area:
                        best_area = area
                        best = state
            for key in ("nodes", "floating_nodes"):
                children = node.get(key, [])
                if isinstance(children, list):
                    stack.extend(children)
        return target, best


class _HyprlandTracker(_WaylandTrackerBase):
    """Use hyprctl JSON output on Hyprland."""

    def __init__(
        self,
        logger: logging.Logger,
        title_hint: str,
        monitor_provider: Optional[MonitorProvider],
    ) -> None:
        super().__init__(logger, title_hint, monitor_provider)
        self._binary_missing = False
        self._active_query_supported = True

    def poll(self) -> Optional[WindowState]:
        cached = self._maybe_use_cache()
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
        except FileNotFoundError:
            if not self._binary_missing:
                self._logger.warning("hyprctl not found; Wayland follow mode disabled for Hyprland")
                self._binary_missing = True
            return self._complete(None)
        except subprocess.SubprocessError as exc:
            self._logger.debug("hyprctl invocation failed: %s", exc)
            return self._complete(None)

        if result.returncode != 0 or not result.stdout:
            self._logger.debug("hyprctl returned status %s", result.returncode)
            return self._complete(None)

        try:
            clients = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self._logger.debug("Failed to parse hyprctl clients JSON: %s", exc)
            return self._complete(None)

        active_address = None
        if self._active_query_supported:
            try:
                active = subprocess.run(
                    ["hyprctl", "activewindow", "-j"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                )
                if active.returncode == 0 and active.stdout:
                    data = json.loads(active.stdout)
                    active_address = str(data.get("address"))
            except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
                self._active_query_supported = False

        target: Optional[WindowState] = None
        best: Optional[WindowState] = None
        best_area = 0
        if isinstance(clients, list):
            for client in clients:
                title = str(client.get("title") or "")
                if not self._matches(title):
                    continue
                at = client.get("at") or client.get("position") or [client.get("x"), client.get("y")]
                size = client.get("size") or [client.get("width"), client.get("height")]
                try:
                    x = int(at[0])
                    y = int(at[1])
                    width = int(size[0])
                    height = int(size[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if width <= 0 or height <= 0:
                    continue
                identifier = str(client.get("address") or "")
                is_focused = bool(client.get("focused")) or (active_address is not None and identifier == active_address)
                state = WindowState(
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    is_foreground=is_focused,
                    is_visible=bool(client.get("mapped", True)) and not bool(client.get("hidden", False)),
                    identifier=identifier or title,
                )
                if is_focused:
                    target = state
                    break
                area = width * height
                if area > best_area:
                    best_area = area
                    best = state

        state: Optional[WindowState] = target or best
        if state is None:
            return self._complete(None)

        monitors = self._monitors()
        augmented = _augment_state_with_monitors(state, monitors, self._logger)
        return self._complete(augmented)


class _KWinTracker(_WaylandTrackerBase):
    """Use the KWin DBus interface on KDE Plasma Wayland."""

    def __init__(
        self,
        logger: logging.Logger,
        title_hint: str,
        monitor_provider: Optional[MonitorProvider],
    ) -> None:
        super().__init__(logger, title_hint, monitor_provider)
        self._kwin = None
        self._pydbus_available = True
        self._warned = False

    def _ensure_interface(self) -> bool:
        if self._kwin is not None:
            return True
        if not self._pydbus_available:
            return False
        try:
            from pydbus import SessionBus  # type: ignore
        except Exception as exc:
            if not self._warned:
                self._logger.warning("pydbus is required for KDE Wayland tracking: %s", exc)
                self._warned = True
            self._pydbus_available = False
            return False
        try:
            bus = SessionBus()
            self._kwin = bus.get("org.kde.KWin", "/KWin")
            return True
        except Exception as exc:
            if not self._warned:
                self._logger.warning("Failed to connect to KWin via DBus: %s", exc)
                self._warned = True
            return False

    def poll(self) -> Optional[WindowState]:
        cached = self._maybe_use_cache()
        if cached is not None:
            return cached
        if not self._ensure_interface():
            return self._complete(None)

        try:
            window_ids = list(self._kwin.windowList())  # type: ignore[operator]
        except Exception as exc:
            self._logger.debug("KWin windowList query failed: %s", exc)
            return self._complete(None)

        try:
            active_window = str(self._kwin.activeWindow())  # type: ignore[operator]
        except Exception:
            active_window = ""

        target: Optional[WindowState] = None
        best: Optional[WindowState] = None
        best_area = 0

        for window_id in window_ids:
            try:
                info = dict(self._kwin.windowInfo(window_id))  # type: ignore[operator]
            except Exception:
                continue
            title = str(info.get("caption") or info.get("visibleName") or "")
            if not self._matches(title):
                continue
            geometry = info.get("geometry") or {}
            try:
                x = int(geometry.get("x", 0))
                y = int(geometry.get("y", 0))
                width = int(geometry.get("width", 0))
                height = int(geometry.get("height", 0))
            except (TypeError, ValueError):
                continue
            if width <= 0 or height <= 0:
                continue
            identifier = str(window_id)
            is_foreground = identifier == active_window
            is_visible = not bool(info.get("minimized", False))
            state = WindowState(
                x=x,
                y=y,
                width=width,
                height=height,
                is_foreground=is_foreground,
                is_visible=is_visible,
                identifier=identifier,
            )
            if is_foreground:
                target = state
                break
            area = width * height
            if area > best_area:
                best_area = area
                best = state

        state: Optional[WindowState] = target or best
        if state is None:
            return self._complete(None)

        monitors = self._monitors()
        augmented = _augment_state_with_monitors(state, monitors, self._logger)
        return self._complete(augmented)
