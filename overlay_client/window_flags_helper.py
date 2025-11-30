from __future__ import annotations

import sys
from typing import Callable, Optional

from PyQt6.QtCore import Qt


class WindowFlagsHelper:
    """Manages click-through and drag/window-flag state via injected Qt callbacks."""

    def __init__(
        self,
        *,
        is_wayland_fn: Callable[[], bool],
        log_fn: Callable[[str, object], None],
        prepare_window_fn: Callable[[object], None],
        apply_click_through_fn: Callable[[bool], None],
        set_transient_parent_fn: Callable[[Optional[object]], None],
        clear_transient_parent_ids_fn: Callable[[], None],
        window_handle_fn: Callable[[], Optional[object]],
        set_widget_attribute_fn: Callable[[Qt.WidgetAttribute, bool], None],
        set_window_flag_fn: Callable[[Qt.WindowType, bool], None],
        ensure_visible_fn: Callable[[], None],
        raise_fn: Callable[[], None],
        set_children_attr_fn: Callable[[bool], None],
        transparent_input_supported: bool,
        set_window_transparent_input_fn: Callable[[bool], None],
    ) -> None:
        self._is_wayland = is_wayland_fn
        self._prepare_window = prepare_window_fn
        self._apply_click_through = apply_click_through_fn
        self._set_transient_parent = set_transient_parent_fn
        self._clear_transient_parent_ids = clear_transient_parent_ids_fn
        self._window_handle = window_handle_fn
        self._set_widget_attribute = set_widget_attribute_fn
        self._set_window_flag = set_window_flag_fn
        self._ensure_visible = ensure_visible_fn
        self._raise = raise_fn
        self._set_children_attr = set_children_attr_fn
        self._transparent_input_supported = transparent_input_supported
        self._set_window_transparent_input = set_window_transparent_input_fn
        self._log = log_fn

    def set_click_through(self, transparent: bool) -> None:
        self._set_widget_attribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        self._set_children_attr(transparent)
        self._set_window_flag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._set_window_flag(Qt.WindowType.FramelessWindowHint, True)
        if self._is_wayland():
            self._set_window_flag(Qt.WindowType.Tool, False)
        else:
            self._set_window_flag(Qt.WindowType.Tool, True)
        self._ensure_visible()
        window = self._window_handle()
        self._log(
            "Set click-through to %s (WA_Transparent=%s window_flag=%s)",
            transparent,
            False,  # caller can log actual flag if needed; kept for parity
            "unknown" if window is None else "set",
        )
        if window is not None:
            self._prepare_window(window)
            self._apply_click_through(transparent)
            if self._transparent_input_supported:
                self._set_window_transparent_input(transparent)
        self._raise()

    def restore_drag_interactivity(self, drag_enabled: bool, drag_active: bool, format_scale_debug: Callable[[], str]) -> None:
        if not drag_enabled or drag_active:
            return
        self._log(
            "Restoring interactive overlay input because drag is enabled; %s",
            format_scale_debug(),
        )
        self.set_click_through(False)

    def handle_force_render_enter(self) -> None:
        if sys.platform.startswith("linux") and self._is_wayland():
            window_handle = self._window_handle()
            if window_handle is not None:
                try:
                    self._set_transient_parent(None)
                except Exception:
                    pass
            self._clear_transient_parent_ids()
        if sys.platform.startswith("linux"):
            self._apply_click_through(True)
