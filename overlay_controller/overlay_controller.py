"""Tkinter scaffolding for the Overlay Controller tool."""

from __future__ import annotations

# ruff: noqa: E402

import atexit
import json
import os
import tkinter as tk
import platform
import re
import subprocess
import sys
import time
import traceback
import logging
import math
from math import ceil
from pathlib import Path
import tempfile
from typing import Any, Callable, Dict, Optional, Tuple

from overlay_plugin.overlay_api import PluginGroupingError, _normalise_background_color, _normalise_border_width

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
# Allow submodule imports when this file is loaded as a standalone module in test harnesses.
if __name__ == "overlay_controller":
    __path__ = [str(PACKAGE_DIR)]
_CONTROLLER_LOGGER: Optional[logging.Logger] = None

from overlay_client.controller_mode import ControllerModeProfile, ModeProfile  # noqa: F401
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED
from overlay_client.logging_utils import build_rotating_file_handler, resolve_log_level, resolve_logs_dir
from overlay_client.window_tracking import create_elite_window_tracker
try:  # When run as a package (`python -m overlay_controller.overlay_controller`)
    from overlay_controller.input_bindings import BindingConfig, BindingManager
    from overlay_controller.gamepad import GamepadBridge
    from overlay_controller.services import ModeTimers, PluginBridge
    from overlay_controller.services.plugin_bridge import ForceRenderOverrideManager
    from overlay_controller.services.group_state import GroupSnapshot
    from overlay_controller.preview import snapshot_math
    from overlay_controller.controller import (
        AppContext,
        EditController,
        FocusManager,
        LayoutBuilder,
        PreviewController,
        log_exception,
        safe_getattr,
        build_app_context,
    )
    from overlay_controller.widgets import AnchorSelectorWidget, alt_modifier_active  # noqa: F401
except ImportError:  # Fallback for spec-from-file/test harness
    from input_bindings import BindingConfig, BindingManager  # type: ignore
    from gamepad import GamepadBridge  # type: ignore
    from services import ModeTimers, PluginBridge  # type: ignore
    from services.plugin_bridge import ForceRenderOverrideManager  # type: ignore
    from services.group_state import GroupSnapshot  # type: ignore
    import preview.snapshot_math as snapshot_math  # type: ignore
    from controller import (  # type: ignore
        AppContext,
        EditController,
        FocusManager,
        LayoutBuilder,
        PreviewController,
        log_exception,
        safe_getattr,
        build_app_context,
    )
    from overlay_controller.widgets import AnchorSelectorWidget, alt_modifier_active  # type: ignore  # noqa: F401
    from overlay_client.window_tracking import create_elite_window_tracker  # type: ignore

ABS_BASE_WIDTH = 1280
ABS_BASE_HEIGHT = 960
ABS_MIN_X = 0.0
ABS_MAX_X = float(ABS_BASE_WIDTH)
ABS_MIN_Y = 0.0
ABS_MAX_Y = float(ABS_BASE_HEIGHT)

_alt_modifier_active = alt_modifier_active


def _resolve_env_log_level_hint() -> Tuple[Optional[int], Optional[str]]:
    raw_value = os.getenv("EDMC_OVERLAY_LOG_LEVEL")
    raw_name = os.getenv("EDMC_OVERLAY_LOG_LEVEL_NAME")
    level_value: Optional[int]
    try:
        level_value = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        level_value = None
    level_name = None
    if raw_name:
        level_name = raw_name.strip() or None
    if level_name is None and level_value is not None:
        level_name = logging.getLevelName(level_value)
    return level_value, level_name


_ENV_LOG_LEVEL_VALUE, _ENV_LOG_LEVEL_NAME = _resolve_env_log_level_hint()
_LOG_LEVEL_OVERRIDE_VALUE: Optional[int] = None
_LOG_LEVEL_OVERRIDE_NAME: Optional[str] = None
_LOG_LEVEL_OVERRIDE_SOURCE: Optional[str] = None
legacy_write_groupings_config = staticmethod(EditController.legacy_write_groupings_config)

def _ForceRenderOverrideManager(
    root: Path,
    *,
    connect: Optional[Callable[..., object]] = None,
    logger: Optional[Callable[[str], None]] = None,
):
    """Compatibility shim returning the service ForceRenderOverrideManager."""

    return ForceRenderOverrideManager(
        port_path=root / "port.json",
        connect=connect,
        logger=logger or _controller_debug,
    )

class OverlayConfigApp(tk.Tk):
    """Basic UI skeleton that mirrors the design mockups."""

    _write_groupings_config = staticmethod(EditController.legacy_write_groupings_config)
    _round_offsets = staticmethod(EditController._round_offsets)

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title("Overlay Controller")
        self.geometry("740x760")
        self._alt_active = False
        self.protocol("WM_DELETE_WINDOW", self.close_application)
        self.base_min_height = 640
        self.minsize(640, self.base_min_height)
        self._closing = False
        self._pending_close_job: str | None = None
        self._focus_close_delay_ms = 200
        self._moving_guard_job: str | None = None
        self._moving_guard_active = False
        self._move_guard_timeout_ms = 500
        self._pending_focus_out = False
        self._drag_offset: tuple[int, int] | None = None
        self._previous_foreground_hwnd: int | None = None

        self._placement_open = False
        self._open_width = 0
        self.sidebar_width = 260
        self.sidebar_pad = 12
        self.sidebar_pad_closed = 0
        self.container_pad_left = 12
        self.container_pad_right_open = 12
        self.container_pad_right_closed = 0
        self.container_pad_vertical = 12
        self.placement_overlay_padding = 4
        self.preview_canvas_padding = 10
        self.placement_min_width = max(450, self._compute_default_placement_width())
        self.closed_min_width = 0
        self.indicator_width = 12
        self.indicator_height = 72
        self.indicator_hit_padding = 0
        self.indicator_hit_width = self.indicator_width + (self.indicator_hit_padding * 2)
        self.indicator_gap = 0

        self._current_right_pad = self.container_pad_right_open
        self._current_sidebar_pad = self.sidebar_pad
        self.indicator_count = 3
        self.widget_focus_area = "sidebar"
        self.widget_select_mode = True
        self.overlay_padding = 8
        self.overlay_border_width = 3
        self._focus_widgets: dict[tuple[str, int], object] = {}
        self._group_controls_enabled = True
        self._current_direction = "right"
        self._groupings_data: dict[str, object] = {}
        self._idprefix_entries: list[tuple[str, str]] = []
        root = Path(__file__).resolve().parents[1]
        self._app_context: AppContext = build_app_context(
            root=root,
            logger=_controller_debug,
        )
        self._groupings_shipped_path = self._app_context.shipped_path
        self._groupings_user_path = self._app_context.user_groupings_path
        self._groupings_loader = self._app_context.groupings_loader
        _controller_debug(
            "Groupings loader configured: shipped=%s user=%s",
            self._groupings_shipped_path,
            self._groupings_user_path,
        )
        self._groupings_path = self._groupings_user_path
        self._groupings_cache_path = self._app_context.cache_path
        self._groupings_cache: dict[str, object] = {}
        self._group_state = self._app_context.group_state
        self._plugin_bridge: PluginBridge | None = self._app_context.plugin_bridge
        self._force_render_override = self._app_context.force_render_override
        self._absolute_user_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._anchor_restore_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._anchor_restore_handles: dict[tuple[str, str], str | None] = {}
        self._absolute_tolerance_px = 0.5
        self._last_preview_signature: tuple[object, ...] | None = None
        self._preview_controller = PreviewController(
            self,
            abs_width=ABS_BASE_WIDTH,
            abs_height=ABS_BASE_HEIGHT,
            padding=self.preview_canvas_padding,
        )
        self._group_snapshots = self._preview_controller.snapshots
        self._edit_controller = EditController(
            self,
            logger=_controller_debug,
        )
        self._mode_profile = self._app_context.mode_profile
        self._mode_timers: ModeTimers | None = None
        self._current_mode_profile = self._mode_profile.resolve("active")
        self._status_poll_handle: object | None = None
        self._debounce_handles: dict[str, object | None] = {}
        self._write_debounce_ms = self._current_mode_profile.write_debounce_ms
        self._offset_write_debounce_ms = self._current_mode_profile.offset_write_debounce_ms
        self._status_poll_interval_ms = self._current_mode_profile.status_poll_ms
        self._mode_timers = ModeTimers(
            self._mode_profile,
            after=self.after,
            after_cancel=self.after_cancel,
            time_source=time.time,
            logger=_controller_debug,
        )
        self._write_debounce_ms = self._mode_timers.write_debounce_ms
        self._offset_write_debounce_ms = self._mode_timers.offset_write_debounce_ms
        self._status_poll_interval_ms = self._mode_timers.status_poll_interval_ms
        self._offset_step_px = 10.0
        self._offset_live_edit_until: float = 0.0
        self._offset_resync_handle: str | None = None
        self._last_edit_ts: float = 0.0
        self._edit_nonce: str = ""
        self._user_overrides_nonce: str = ""
        self._initial_geometry_applied = False
        self._port_path = self._app_context.port_path
        self._settings_path = self._app_context.settings_path
        self._controller_heartbeat_ms = self._app_context.controller_heartbeat_ms
        self._controller_heartbeat_handle: str | None = None
        self._last_override_reload_nonce: Optional[str] = None
        self._last_override_reload_ts: float = 0.0
        self._last_active_group_sent: Optional[tuple[str, str, str]] = None

        self._groupings_cache = self._load_groupings_cache()
        layout_builder = LayoutBuilder(self)
        layout = layout_builder.build(
            sidebar_width=self.sidebar_width,
            sidebar_pad=self.sidebar_pad,
            container_pad_left=self.container_pad_left,
            container_pad_right_open=self.container_pad_right_open,
            container_pad_right_closed=self.container_pad_right_closed,
            container_pad_vertical=self.container_pad_vertical,
            placement_overlay_padding=self.placement_overlay_padding,
            preview_canvas_padding=self.preview_canvas_padding,
            overlay_padding=self.overlay_padding,
            overlay_border_width=self.overlay_border_width,
            placement_min_width=self.placement_min_width,
            sidebar_selectable=True,
            on_sidebar_click=self._handle_sidebar_click,
            on_placement_click=lambda: self._handle_placement_click(),
            on_idprefix_selected=self._handle_idprefix_selected,
            on_offset_changed=self._handle_offset_changed,
            on_absolute_changed=self._handle_absolute_changed,
            on_anchor_changed=self._handle_anchor_changed,
            on_justification_changed=self._handle_justification_changed,
            on_background_changed=self._handle_background_changed,
            load_idprefix_options=self._load_idprefix_options,
        )
        self.container = layout["container"]
        self.placement_frame = layout["placement_frame"]
        self.preview_canvas = layout["preview_canvas"]
        self.sidebar = layout["sidebar"]
        self.sidebar_cells = layout["sidebar_cells"]
        self._focus_widgets = layout["focus_widgets"]
        self.sidebar_context_frame = layout.get("sidebar_context_frame")
        self.indicator_wrapper = layout["indicator_wrapper"]
        self.indicator_canvas = layout["indicator_canvas"]
        self.sidebar_overlay = layout["sidebar_overlay"]
        self.placement_overlay = layout["placement_overlay"]
        self.idprefix_widget = layout["idprefix_widget"]
        self.offset_widget = layout["offset_widget"]
        self.absolute_widget = layout["absolute_widget"]
        self.anchor_widget = layout["anchor_widget"]
        self.justification_widget = layout["justification_widget"]
        self.background_widget = layout["background_widget"]
        self.tip_helper = layout["tip_helper"]
        self._sidebar_focus_index = 0
        self.widget_select_mode = True
        self.sidebar.grid_propagate(True)
        self._binding_config = BindingConfig.load()
        self._binding_manager = BindingManager(self, self._binding_config)
        self._gamepad_bridge = GamepadBridge(
            self,
            self._binding_manager.trigger_action,
            self._binding_manager.has_action,
        )
        self._focus_manager = FocusManager(self, self._binding_manager)
        self._apply_placement_state()
        self._refresh_widget_focus()
        self._handle_idprefix_selected()
        if sys.platform.startswith("win"):
            self.bind_all("<KeyPress-Alt_L>", self._handle_alt_press, add="+")
            self.bind_all("<KeyPress-Alt_R>", self._handle_alt_press, add="+")
            self.bind_all("<KeyRelease-Alt_L>", self._handle_alt_release, add="+")
            self.bind_all("<KeyRelease-Alt_R>", self._handle_alt_release, add="+")
        self._register_focus_bindings()
        self._binding_manager.activate()
        self._gamepad_bridge.start()
        self.bind("<Configure>", self._handle_configure)
        self.bind("<FocusIn>", self._handle_focus_in)
        self.bind("<space>", self._handle_space_key, add="+")
        if sys.platform.startswith("win"):
            self.bind_all("<KeyPress-Alt_L>", self._handle_alt_press, add="+")
            self.bind_all("<KeyPress-Alt_R>", self._handle_alt_press, add="+")
            self.bind_all("<KeyRelease-Alt_L>", self._handle_alt_release, add="+")
            self.bind_all("<KeyRelease-Alt_R>", self._handle_alt_release, add="+")
        self.bind("<ButtonPress-1>", self._start_window_drag, add="+")
        self.bind("<B1-Motion>", self._on_window_drag, add="+")
        self.bind("<ButtonRelease-1>", self._end_window_drag, add="+")
        self._apply_mode_profile("active", reason="startup")
        if self._mode_timers is not None:
            self._status_poll_handle = self._mode_timers.start_status_poll(self._poll_cache_and_status)
        else:
            self._status_poll_handle = self.after(self._current_mode_profile.status_poll_ms, self._poll_cache_and_status)
        self.after(0, self._activate_force_render_override)
        self.after(0, self._start_controller_heartbeat)
        self.after(0, self._center_and_show)

    def _compute_default_placement_width(self) -> int:
        """Return column width needed for a 4:3 preview at the base height."""

        canvas_height = self.base_min_height - (self.container_pad_vertical * 2) - (self.placement_overlay_padding * 2)
        canvas_height = max(1, canvas_height)
        inner_height = max(1, canvas_height - (self.preview_canvas_padding * 2))
        target_inner_width = inner_height * (ABS_BASE_WIDTH / ABS_BASE_HEIGHT)
        horizontal_slack = self.preview_canvas_padding
        frame_width = target_inner_width + (self.preview_canvas_padding * 2) + horizontal_slack
        column_width = frame_width + (self.placement_overlay_padding * 2)
        return int(ceil(column_width))

    def _register_widget_specific_bindings(self) -> None:
        absolute_widget = getattr(self, "absolute_widget", None)
        if absolute_widget is not None:
            targets = absolute_widget.get_binding_targets()
            self._binding_manager.register_action(
                "absolute_focus_next",
                absolute_widget.focus_next_field,
                widgets=targets,
            )
            self._binding_manager.register_action(
                "absolute_focus_prev",
                absolute_widget.focus_previous_field,
                widgets=targets,
            )
    def _register_focus_bindings(self) -> None:
        """Register focus/navigation bindings via FocusManager."""

        self._binding_manager.register_action(
            "indicator_toggle",
            self.toggle_placement_window,
            widgets=[self.indicator_wrapper, self.indicator_canvas],
        )
        self._binding_manager.register_action(
            "sidebar_focus_up",
            self.focus_sidebar_up,
        )
        self._binding_manager.register_action(
            "sidebar_focus_down",
            self.focus_sidebar_down,
        )
        self._binding_manager.register_action(
            "widget_move_left",
            self.move_widget_focus_left,
        )
        self._binding_manager.register_action(
            "widget_move_right",
            self.move_widget_focus_right,
        )
        self._binding_manager.register_action(
            "alt_widget_move_up",
            self.focus_sidebar_up,
        )
        self._binding_manager.register_action(
            "alt_widget_move_down",
            self.focus_sidebar_down,
        )
        self._binding_manager.register_action(
            "alt_widget_move_left",
            self.move_widget_focus_left,
        )
        self._binding_manager.register_action(
            "alt_widget_move_right",
            self.move_widget_focus_right,
        )
        self._binding_manager.register_action("enter_focus", self.enter_focus_mode)
        self._binding_manager.register_action("widget_activate", self._handle_return_key)
        self._binding_manager.register_action("exit_focus", self.exit_focus_mode)
        self._binding_manager.register_action("close_app", self.close_application)
        self._focus_manager.register_widget_bindings()

    def report_callback_exception(self, exc, val, tb) -> None:  # type: ignore[override]
        """Ensure Tk errors are printed to stderr instead of being swallowed."""

        traceback.print_exception(exc, val, tb, file=sys.stderr)


    def _activate_force_render_override(self) -> None:
        manager = safe_getattr(self, "_force_render_override", None)
        if manager is None:
            return
        try:
            manager.activate()
        except Exception as exc:
            log_exception(_controller_debug, "ForceRender override activate failed", exc)

    def _deactivate_force_render_override(self) -> None:
        manager = safe_getattr(self, "_force_render_override", None)
        if manager is None:
            return
        try:
            manager.deactivate()
        except Exception as exc:
            log_exception(_controller_debug, "ForceRender override deactivate failed", exc)

    def _send_plugin_cli(self, payload: Dict[str, Any]) -> bool:
        bridge = safe_getattr(self, "_plugin_bridge", None)
        if bridge is None:
            return False
        try:
            return bool(bridge.send_cli(payload))
        except Exception as exc:
            log_exception(_controller_debug, "Plugin CLI send failed", exc)
            return False

    def _send_controller_heartbeat(self) -> None:
        bridge = getattr(self, "_plugin_bridge", None)
        if bridge is not None:
            try:
                bridge.send_heartbeat()
            except Exception:
                pass
        selection = self._get_current_group_selection()
        if selection is not None:
            plugin_name, label = selection
            self._send_active_group_selection(plugin_name, label)

    def _start_controller_heartbeat(self) -> None:
        self._stop_controller_heartbeat()
        self._send_controller_heartbeat()
        interval = max(1000, int(getattr(self, "_controller_heartbeat_ms", 15000)))
        self._controller_heartbeat_handle = self.after(interval, self._start_controller_heartbeat)

    def _stop_controller_heartbeat(self) -> None:
        handle = getattr(self, "_controller_heartbeat_handle", None)
        if handle is not None:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        self._controller_heartbeat_handle = None

    def _stop_gamepad_bridge(self) -> None:
        bridge = getattr(self, "_gamepad_bridge", None)
        if bridge is not None:
            try:
                bridge.stop()
            except Exception:
                pass

    def toggle_placement_window(self) -> None:
        """Switch between the open and closed placement window layouts."""

        self._placement_open = not self._placement_open
        if not self._placement_open and self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
        self._apply_placement_state()
        self._refresh_widget_focus()

    def focus_sidebar_up(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move sidebar focus upward."""

        return self._focus_manager.focus_sidebar_up(event)

    def focus_sidebar_down(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move sidebar focus downward."""

        return self._focus_manager.focus_sidebar_down(event)

    def _set_sidebar_focus(self, index: int) -> None:
        self._focus_manager.set_sidebar_focus(index)

    def _handle_sidebar_click(self, index: int, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to a sidebar cell and enter focus mode."""

        self._focus_manager.handle_sidebar_click(index)

    def _handle_placement_click(self, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to the placement area and enter focus mode."""

        self._focus_manager.handle_placement_click(_event)

    def move_widget_focus_left(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Handle left arrow behavior in widget select mode."""

        return self._focus_manager.move_widget_focus_left(event)

    def move_widget_focus_right(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Handle right arrow behavior in widget select mode."""

        return self._focus_manager.move_widget_focus_right(event)

    def _update_sidebar_highlight(self) -> None:
        self._focus_manager.update_sidebar_highlight()

    def _update_placement_focus_highlight(self) -> None:
        self._focus_manager.update_placement_focus_highlight()

    def _update_contextual_tip(self) -> None:
        self._focus_manager.update_contextual_tip()

    def _refresh_widget_focus(self) -> None:
        manager = safe_getattr(self, "_focus_manager")
        if manager is not None:
            return manager.refresh_widget_focus()
        # Fallback during early init if focus manager is not yet wired.
        if hasattr(self, "sidebar_cells"):
            self._update_sidebar_highlight()
        self._update_placement_focus_highlight()

    def close_application(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Close the Overlay Controller window."""

        if self._closing:
            return
        if event is not None:
            keysym = getattr(event, "keysym", "") or ""
            if keysym.lower() == "escape" and not self.widget_select_mode:
                self.exit_focus_mode()
                return
            if self._handle_active_widget_key(keysym, event):
                return

        self._finalize_close()

    def _finalize_close(self) -> None:
        """Close immediately, respecting focus mode behavior."""

        _controller_debug("Overlay controller closing (focus_mode=%s)", getattr(self, "widget_select_mode", False))
        self._cancel_pending_close()
        self._pending_focus_out = False
        self._closing = True
        self._cancel_status_poll()
        self._stop_controller_heartbeat()
        self._deactivate_force_render_override()
        self._restore_foreground_window()
        self._stop_gamepad_bridge()
        self.destroy()

    def _handle_focus_in(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Cancel any delayed close when the window regains focus."""

        self._cancel_pending_close()
        self._pending_focus_out = False
        self._drag_offset = None

    def _handle_alt_press(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        if sys.platform.startswith("win"):
            self._alt_active = True

    def _handle_alt_release(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        if sys.platform.startswith("win"):
            self._alt_active = False

    def _start_window_drag(self, event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Begin window drag tracking when a mouse button is pressed."""

        try:
            if event.widget.winfo_toplevel() is not self:
                return
        except Exception:
            return
        try:
            self._drag_offset = (
                event.x_root - self.winfo_rootx(),
                event.y_root - self.winfo_rooty(),
            )
        except Exception:
            self._drag_offset = None

    def _on_window_drag(self, event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Move the window while dragging."""

        if self._drag_offset is None:
            return
        try:
            x = int(event.x_root - self._drag_offset[0])
            y = int(event.y_root - self._drag_offset[1])
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _end_window_drag(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Clear drag tracking when the mouse button is released."""

        self._drag_offset = None

    def _is_focus_out_event(self, event: tk.Event[tk.Misc] | None) -> bool:  # type: ignore[name-defined]
        """Return True if the event represents a real focus loss worth acting on."""

        if event is None:
            return False
        event_type = getattr(event, "type", None)
        event_type_name = getattr(event_type, "name", None) or str(event_type)
        is_focus_out = (
            event_type == tk.EventType.FocusOut
            or event_type_name.endswith("FocusOut")
            or event_type == 9
        )
        if not is_focus_out:
            return False

        mode = getattr(event, "mode", None)
        mode_name = getattr(mode, "name", None) or str(mode)
        mode_label = mode_name.split(".")[-1]
        grab_related = mode in (1, 2, 3) or mode_label in {
            "NotifyGrab",
            "NotifyUngrab",
            "NotifyWhileGrabbed",
        }
        if grab_related:
            return False

        return True

    def _cancel_pending_close(self) -> None:
        if self._pending_close_job is not None:
            try:
                self.after_cancel(self._pending_close_job)
            except Exception:
                pass
            self._pending_close_job = None

    def _schedule_focus_out_close(self) -> None:
        if self._closing:
            # Already on path to close; avoid re-arming timers.
            return
        self._cancel_pending_close()
        self._pending_close_job = self.after_idle(self._finalize_close)

    def _close_if_unfocused(self) -> None:
        self._pending_close_job = None
        self._pending_focus_out = False
        if self._is_focus_within_app():
            self._closing = False
            return
        self._finalize_close()

    def _is_app_focused(self) -> bool:
        try:
            focus_widget = self.focus_get()
        except Exception:
            return False
        return bool(focus_widget and focus_widget.winfo_toplevel() == self)

    def _safe_focus_get(self) -> tk.Misc | None:  # type: ignore[name-defined]
        try:
            return self.focus_get()
        except Exception:
            return None

    def _is_focus_within_app(self) -> bool:
        """Return True if focus is within this window or a known popdown."""

        focus_widget = self._safe_focus_get()
        if focus_widget is None:
            return False
        try:
            if focus_widget.winfo_toplevel() == self:
                return True
        except Exception:
            return False
        try:
            klass = focus_widget.winfo_class().lower()
            name = focus_widget.winfo_name().lower()
        except Exception:
            return False
        return "combobox" in klass or "popdown" in name

    def _is_internal_focus_shift(self, event: tk.Event[tk.Misc] | None) -> bool:  # type: ignore[name-defined]
        """Return True if focus is shifting within our widgets (e.g., combobox popdown)."""

        widgets: list[tk.Misc] = []  # type: ignore[name-defined]
        event_widget = getattr(event, "widget", None)
        if event_widget is not None:
            widgets.append(event_widget)
        focus_widget = self._safe_focus_get()
        if focus_widget is not None:
            widgets.append(focus_widget)

        for widget in widgets:
            try:
                klass = widget.winfo_class().lower()
                name = widget.winfo_name().lower()
            except Exception:
                continue
            if "combobox" in klass or "popdown" in name:
                return True

        return False

    def _get_active_focus_widget(self) -> object | None:
        if self.widget_focus_area == "sidebar":
            key = ("sidebar", getattr(self, "_sidebar_focus_index", -1))
        else:
            return None
        return self._focus_widgets.get(key)

    def _handle_active_widget_key(self, keysym: str, event: tk.Event[tk.Misc] | None = None) -> bool:  # type: ignore[name-defined]
        if self.widget_select_mode:
            return False
        widget = self._get_active_focus_widget()
        if widget is None:
            return False

        lower_keysym = keysym.lower()
        if lower_keysym == "escape":
            self.exit_focus_mode()
            return True
        if lower_keysym == "space":
            handler = getattr(widget, "handle_key", None)
            try:
                handled = bool(handler(keysym, event)) if handler is not None else False
            except Exception:
                handled = True
            if handled:
                return True
            self.exit_focus_mode()
            return True

        handler = getattr(widget, "handle_key", None)
        try:
            handled = bool(handler(keysym, event)) if handler is not None else False
        except Exception:
            handled = True
        # Only consume when explicitly handled; allow text input in focused children.
        return handled

    def _on_focus_mode_entered(self) -> None:
        widget = self._get_active_focus_widget()
        if widget is None:
            return
        handler = getattr(widget, "on_focus_enter", None)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _on_focus_mode_exited(self) -> None:
        widget = self._get_active_focus_widget()
        if widget is None:
            return
        handler = getattr(widget, "on_focus_exit", None)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _load_idprefix_options(self) -> list[str]:
        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                self._groupings_cache = state.refresh_cache()
                options = state.load_options()
                self._groupings_data = getattr(state, "_groupings_data", {})
                self._idprefix_entries = list(state.idprefix_entries)
                return options
            except Exception:
                pass
        loader = getattr(self, "_groupings_loader", None)
        if loader is not None:
            try:
                loader.reload_if_changed()
                payload = loader.merged()
            except Exception:
                payload = {}
        else:
            path = getattr(self, "_groupings_path", None)
            if path is None:
                root = Path(__file__).resolve().parents[1]
                path = root / "overlay_groupings.json"
                self._groupings_path = path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        self._groupings_data = payload if isinstance(payload, dict) else {}
        options: list[str] = []
        self._idprefix_entries.clear()
        cache_groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}
        if isinstance(self._groupings_data, dict):
            for plugin_name, entry in sorted(self._groupings_data.items(), key=lambda item: item[0].casefold()):
                groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
                if not isinstance(groups, dict):
                    continue
                labels = sorted(groups.keys(), key=str.casefold)

                def _prefix(label: str) -> str:
                    for sep in ("-", " "):
                        head, *rest = label.split(sep, 1)
                        if rest:
                            return head.strip().casefold()
                    return label.strip().casefold()

                first_parts = {_prefix(lbl) for lbl in labels}
                show_plugin = len(first_parts) > 1
                plugin_cache = cache_groups.get(plugin_name) if isinstance(cache_groups, dict) else {}
                for label in labels:
                    has_cache = isinstance(plugin_cache, dict) and isinstance(plugin_cache.get(label), dict)
                    if not has_cache:
                        continue
                    display = f"{plugin_name}: {label}" if show_plugin else label
                    options.append(display)
                    self._idprefix_entries.append((plugin_name, label))
        return options

    def _get_group_config(self, plugin_name: str, label: str) -> dict[str, object]:
        entry = self._groupings_data.get(plugin_name) if isinstance(self._groupings_data, dict) else None
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        group = groups.get(label) if isinstance(groups, dict) else None
        return group if isinstance(group, dict) else {}

    def _get_cache_record(
        self, plugin_name: str, label: str
    ) -> tuple[dict[str, object] | None, dict[str, object] | None, float]:
        groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}
        plugin_entry = groups.get(plugin_name) if isinstance(groups, dict) else {}
        entry = plugin_entry.get(label) if isinstance(plugin_entry, dict) else {}
        if not isinstance(entry, dict):
            return None, None, 0.0
        normalized = entry.get("base") or entry.get("normalized")
        normalized = normalized if isinstance(normalized, dict) else None
        transformed = entry.get("transformed")
        transformed = transformed if isinstance(transformed, dict) else None
        timestamp = float(entry.get("last_updated", 0.0)) if isinstance(entry, dict) else 0.0
        return normalized, transformed, timestamp

    def _set_group_controls_enabled(self, enabled: bool) -> None:
        self._group_controls_enabled = bool(enabled)
        widget_names = ("offset_widget", "absolute_widget", "anchor_widget", "justification_widget", "background_widget")
        for name in widget_names:
            widget = getattr(self, name, None)
            setter = getattr(widget, "set_enabled", None)
            if callable(setter):
                try:
                    setter(enabled)
                except Exception:
                    continue
        if not enabled and not self.widget_select_mode and self.widget_focus_area == "sidebar":
            if getattr(self, "_sidebar_focus_index", 0) > 0:
                self.exit_focus_mode()
        self._update_contextual_tip()

    def _compute_absolute_from_snapshot(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        controller = getattr(self, "_preview_controller", None)
        if controller is not None:
            try:
                return controller.compute_absolute_from_snapshot(snapshot)
            except Exception:
                pass
        base_min_x, base_min_y, _, _ = snapshot.base_bounds
        return base_min_x + snapshot.offset_x, base_min_y + snapshot.offset_y

    def _clamp_absolute_value(self, value: float, axis: str) -> float:
        if axis.lower() == "x":
            return max(ABS_MIN_X, min(ABS_MAX_X, value))
        return max(ABS_MIN_Y, min(ABS_MAX_Y, value))

    def _store_absolute_state(
        self, selection: tuple[str, str], absolute_x: float, absolute_y: float, timestamp: float | None = None
    ) -> None:
        ts = time.time() if timestamp is None else timestamp
        state = self._absolute_user_state.setdefault(selection, {})
        state["x"] = absolute_x
        state["y"] = absolute_y
        state["x_ts"] = ts
        state["y_ts"] = ts

    def _build_group_snapshot(self, plugin_name: str, label: str) -> GroupSnapshot | None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is None:
            # Legacy/test fallback when preview controller is not initialized.
            cfg = self._get_group_config(plugin_name, label)
            base_payload, transformed_payload, cache_ts = self._get_cache_record(plugin_name, label)
            if base_payload is None:
                return None
            anchor_token = str(
                cfg.get("idPrefixGroupAnchor")
                or (transformed_payload.get("anchor") if transformed_payload else "nw")
                or "nw"
            ).lower()
            transform_anchor_token = str(
                transformed_payload.get("anchor", anchor_token) if isinstance(transformed_payload, dict) else anchor_token
            ).lower()
            offset_x = float(cfg.get("offsetX", 0.0)) if isinstance(cfg, dict) else 0.0
            offset_y = float(cfg.get("offsetY", 0.0)) if isinstance(cfg, dict) else 0.0
            base_min_x = float(base_payload.get("base_min_x", 0.0))
            base_min_y = float(base_payload.get("base_min_y", 0.0))
            base_max_x = float(base_payload.get("base_max_x", base_min_x))
            base_max_y = float(base_payload.get("base_max_y", base_min_y))
            base_bounds = (base_min_x, base_min_y, base_max_x, base_max_y)
            base_anchor = self._compute_anchor_point(base_min_x, base_max_x, base_min_y, base_max_y, anchor_token)
            trans_min_x = base_min_x + offset_x
            trans_min_y = base_min_y + offset_y
            trans_max_x = base_max_x + offset_x
            trans_max_y = base_max_y + offset_y
            transform_bounds = (trans_min_x, trans_min_y, trans_max_x, trans_max_y)
            transform_anchor = self._compute_anchor_point(
                trans_min_x, trans_max_x, trans_min_y, trans_max_y, transform_anchor_token
            )
            return GroupSnapshot(
                plugin=plugin_name,
                label=label,
                anchor_token=anchor_token,
                transform_anchor_token=transform_anchor_token,
                offset_x=offset_x,
                offset_y=offset_y,
                base_bounds=base_bounds,
                base_anchor=base_anchor,
                transform_bounds=transform_bounds,
                transform_anchor=transform_anchor,
                has_transform=True,
                cache_timestamp=cache_ts,
            )
        return controller.build_group_snapshot(plugin_name, label)

    def _scale_mode_setting(self) -> str:
        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.scale_mode_setting()
            except Exception:
                pass
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
            value = raw.get("scale_mode")
            if isinstance(value, str):
                token = value.strip().lower()
                if token in {"fit", "fill"}:
                    return token
        except Exception:
            pass
        return "fill"

    @staticmethod
    def _clamp_unit(value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number):
            return 0.0
        if number < 0.0:
            return 0.0
        if number > 1.0:
            return 1.0
        return number

    @staticmethod
    def _anchor_point_from_bounds(bounds: tuple[float, float, float, float], anchor: str) -> tuple[float, float]:
        return snapshot_math.anchor_point_from_bounds(bounds, anchor)

    @staticmethod
    def _translate_snapshot_for_fill(
        snapshot: GroupSnapshot,
        viewport_width: float,
        viewport_height: float,
        *,
        scale_mode_value: Optional[str] = None,
        anchor_token_override: Optional[str] = None,
    ) -> GroupSnapshot:
        result = snapshot_math.translate_snapshot_for_fill(
            snapshot,
            viewport_width,
            viewport_height,
            scale_mode_value=scale_mode_value,
            anchor_token_override=anchor_token_override,
        )
        return result  # type: ignore[return-value]

    def _update_absolute_widget_color(self, snapshot: GroupSnapshot | None) -> None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                controller.update_absolute_widget_color(snapshot)
                return
            except Exception:
                pass
        widget = getattr(self, "absolute_widget", None)
        if widget is None:
            return
        try:
            widget.set_text_color(None)
        except Exception:
            pass
        self._update_contextual_tip()

    def _apply_snapshot_to_absolute_widget(
        self, selection: tuple[str, str], snapshot: GroupSnapshot, force_ui: bool = True
    ) -> None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                controller.apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=force_ui)
                return
            except Exception:
                pass
        if not hasattr(self, "absolute_widget"):
            return
        abs_x, abs_y = self._compute_absolute_from_snapshot(snapshot)
        self._store_absolute_state(selection, abs_x, abs_y)
        widget = getattr(self, "absolute_widget", None)
        if widget is None:
            return
        if force_ui:
            try:
                widget.set_px_values(abs_x, abs_y)
            except Exception:
                pass

    def _refresh_current_group_snapshot(self, force_ui: bool = True) -> None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is None:
            return
        controller.refresh_current_group_snapshot(force_ui=force_ui)

    def _get_group_snapshot(self, selection: tuple[str, str] | None = None) -> GroupSnapshot | None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.get_group_snapshot(selection)
            except Exception:
                pass
        key = selection if selection is not None else self._get_current_group_selection()
        if key is None:
            return None
        return self._group_snapshots.get(key)

    def _poll_cache_and_status(self) -> None:
        if self._mode_timers is None:
            self._status_poll_handle = None
        reload_groupings = False
        loader = getattr(self, "_groupings_loader", None)
        state = safe_getattr(self, "_group_state")
        edit_delay_seconds = 5.0
        if state is not None:
            try:
                reload_groupings = bool(
                    state.reload_groupings_if_changed(last_edit_ts=getattr(self, "_last_edit_ts", 0.0), delay_seconds=edit_delay_seconds)
                )
            except Exception:
                reload_groupings = False
        elif loader is not None:
            try:
                # Delay reloads immediately after an edit to avoid reading half-written user file.
                timers = getattr(self, "_mode_timers", None)
                should_reload = False
                if timers is not None:
                    should_reload = timers.should_reload_after_edit(delay_seconds=edit_delay_seconds)
                else:
                    should_reload = time.time() - getattr(self, "_last_edit_ts", 0.0) > edit_delay_seconds
                if should_reload:
                    reload_groupings = bool(loader.reload_if_changed())
            except Exception:
                reload_groupings = False
        try:
            latest = self._load_groupings_cache()
        except Exception:
            latest = None
        if isinstance(latest, dict):
            if self._cache_changed(latest, self._groupings_cache):
                _controller_debug("Group cache refreshed from disk at %s", time.strftime("%H:%M:%S"))
                self._groupings_cache = latest
                self._refresh_idprefix_options()
        if reload_groupings:
            _controller_debug("Groupings reloaded from disk at %s", time.strftime("%H:%M:%S"))
            self._refresh_idprefix_options()
        self._refresh_current_group_snapshot(force_ui=False)
        if self._mode_timers is None:
            self._status_poll_handle = self.after(self._status_poll_interval_ms, self._poll_cache_and_status)
    def _refresh_idprefix_options(self) -> None:
        selection = self._get_current_group_selection()
        options = self._load_idprefix_options()
        selected_index: int | None = None
        if selection is not None:
            try:
                selected_index = next(
                    idx for idx, entry in enumerate(self._idprefix_entries) if entry == selection
                )
            except StopIteration:
                selected_index = None
        if hasattr(self, "idprefix_widget"):
            try:
                self.idprefix_widget.update_options(options, selected_index)
            except Exception:
                pass
        if selected_index is None:
            self._grouping = ""
            self._id_prefix = ""
            self._set_group_controls_enabled(False)
        else:
            try:
                self.idprefix_widget.dropdown.current(selected_index)  # type: ignore[attr-defined]
            except Exception:
                pass
            self._handle_idprefix_selected()

    def _load_groupings_cache(self) -> dict[str, object]:
        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                return state.refresh_cache()
            except Exception:
                pass
        path = getattr(self, "_groupings_cache_path", None)
        if path is None:
            root = Path(__file__).resolve().parents[1]
            path = root / "overlay_group_cache.json"
            self._groupings_cache_path = path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        groups = payload.get("groups") if isinstance(payload, dict) else None
        payload["groups"] = groups if isinstance(groups, dict) else {}
        return payload

    def _cache_changed(self, new_cache: dict[str, object], old_cache: dict[str, object]) -> bool:
        """Return True if cache differs, ignoring timestamp-only churn."""

        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                return state.cache_changed(new_cache)
            except Exception:
                return False

        def _strip_timestamps(node: object) -> object:
            if isinstance(node, dict):
                return {k: _strip_timestamps(v) for k, v in node.items() if k != "last_updated"}
            if isinstance(node, list):
                return [_strip_timestamps(v) for v in node]
            return node

        return _strip_timestamps(new_cache) != _strip_timestamps(old_cache)

    @staticmethod
    def _emit_override_reload_signal(self) -> None:
        controller = getattr(self, "_edit_controller", None)
        if controller is not None:
            try:
                controller._emit_override_reload_signal()
                return
            except Exception:
                pass
        now = time.monotonic()
        last = getattr(self, "_last_override_reload_ts", 0.0)
        if last and now - last < 0.25:
            return
        nonce = f"{int(time.time() * 1000)}-{os.getpid()}"
        self._last_override_reload_ts = now
        self._last_override_reload_nonce = nonce
        payload = {
            "cli": "controller_override_reload",
            "nonce": nonce,
            "edit_nonce": getattr(self, "_user_overrides_nonce", ""),
            "timestamp": time.time(),
        }
        bridge = getattr(self, "_plugin_bridge", None)
        sent = False
        if bridge is not None:
            try:
                sent = bool(bridge.emit_override_reload(nonce=nonce, edit_nonce=payload["edit_nonce"], timestamp=payload["timestamp"]))
            except Exception:
                sent = False
        if not sent:
            self._send_plugin_cli(payload)
        _controller_debug("Controller override reload signal sent (nonce=%s)", nonce)

    def _apply_mode_profile(self, mode: str, reason: str = "apply") -> None:
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            profile = timers.apply_mode(mode, reason=reason)
            self._current_mode_profile = profile
            self._write_debounce_ms = timers.write_debounce_ms
            self._offset_write_debounce_ms = timers.offset_write_debounce_ms
            self._status_poll_interval_ms = timers.status_poll_interval_ms
            self._status_poll_handle = getattr(timers, "_status_poll_handle", None)
            return
        profile = self._mode_profile.resolve(mode)
        previous = getattr(self, "_current_mode_profile", None)
        if previous == profile:
            _controller_debug(
                "Controller mode profile unchanged (%s): write_debounce=%dms offset_debounce=%dms status_poll=%dms reason=%s",
                mode,
                profile.write_debounce_ms,
                profile.offset_write_debounce_ms,
                profile.status_poll_ms,
                reason,
            )
            return
        self._current_mode_profile = profile
        self._write_debounce_ms = max(25, profile.write_debounce_ms)
        self._offset_write_debounce_ms = max(25, profile.offset_write_debounce_ms)
        self._status_poll_interval_ms = max(50, profile.status_poll_ms)
        rescheduled = False
        if self._status_poll_handle is not None:
            self._cancel_status_poll()
            self._status_poll_handle = self.after(self._status_poll_interval_ms, self._poll_cache_and_status)
            rescheduled = True
        _controller_debug(
            "Controller mode profile applied (%s): write_debounce=%dms offset_debounce=%dms status_poll=%dms rescheduled=%s reason=%s",
            mode,
            profile.write_debounce_ms,
            profile.offset_write_debounce_ms,
            profile.status_poll_ms,
            rescheduled,
            reason,
        )

    def _cancel_status_poll(self) -> None:
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            try:
                timers.stop_status_poll()
            finally:
                self._status_poll_handle = None
            return
        handle = self._status_poll_handle
        if handle is None:
            return
        try:
            self.after_cancel(handle)
        except Exception:
            pass
        self._status_poll_handle = None

    def _capture_anchor_restore_state(self, selection: tuple[str, str]) -> bool:
        if selection is None:
            return False
        state = self._absolute_user_state.get(selection, {"x": None, "y": None, "x_ts": 0.0, "y_ts": 0.0})
        x_val = state.get("x")
        y_val = state.get("y")
        if (x_val is None or y_val is None) and hasattr(self, "absolute_widget"):
            try:
                x_widget, y_widget = self.absolute_widget.get_px_values()
                if x_val is None:
                    x_val = x_widget
                if y_val is None:
                    y_val = y_widget
            except Exception:
                pass
        if x_val is None and y_val is None:
            return False
        now = time.time()
        self._anchor_restore_state[selection] = {
            "x": x_val,
            "y": y_val,
            "x_ts": float(state.get("x_ts", now) or now),
            "y_ts": float(state.get("y_ts", now) or now),
        }
        return True

    def _schedule_anchor_restore(self, selection: tuple[str, str]) -> None:
        if selection is None:
            return
        handle = self._anchor_restore_handles.pop(selection, None)
        if handle is not None:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        self._restore_anchor_offsets(selection)

    def _restore_anchor_offsets(self, selection: tuple[str, str]) -> None:
        handle = self._anchor_restore_handles.pop(selection, None)
        if handle is not None:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        if selection != self._get_current_group_selection():
            return
        snapshot = self._anchor_restore_state.pop(selection, None)
        if not isinstance(snapshot, dict):
            return
        x_val = snapshot.get("x")
        y_val = snapshot.get("y")
        if x_val is None and y_val is None:
            return
        now = time.time()
        state = self._absolute_user_state.get(selection, {"x": None, "y": None, "x_ts": 0.0, "y_ts": 0.0})
        if x_val is not None:
            state["x"] = x_val
            state["x_ts"] = max(now, float(snapshot.get("x_ts", now) or now))
        if y_val is not None:
            state["y"] = y_val
            state["y_ts"] = max(now, float(snapshot.get("y_ts", now) or now))
        self._absolute_user_state[selection] = state
        if hasattr(self, "absolute_widget"):
            try:
                self.absolute_widget.set_px_values(state.get("x"), state.get("y"))
            except Exception:
                pass
        self._sync_absolute_for_current_group(force_ui=True, debounce_ms=self._offset_write_debounce_ms, prefer_user=True)
        self._draw_preview()

    def _draw_preview(self) -> None:
        controller = safe_getattr(self, "_preview_controller")
        if controller is None:
            return
        controller.draw_preview()
    def _persist_offsets(
        self, selection: tuple[str, str], offset_x: float, offset_y: float, debounce_ms: int | None = None
    ) -> None:
        self._edit_controller.persist_offsets(selection, offset_x, offset_y, debounce_ms)

    def _handle_idprefix_selected(self, _selection: str | None = None) -> None:
        if not hasattr(self, "idprefix_widget"):
            return
        try:
            idx = int(self.idprefix_widget.dropdown.current())
        except Exception:
            idx = -1
        if not (0 <= idx < len(self._idprefix_entries)):
            self._grouping = ""
            self._id_prefix = ""
            _controller_debug("No cached idPrefix groups available; controls disabled.")
            self._set_group_controls_enabled(False)
            self._send_active_group_selection("", "")
            return
        plugin_name, label = self._idprefix_entries[idx]
        cfg = self._get_group_config(plugin_name, label)
        anchor_name = cfg.get("idPrefixGroupAnchor") if isinstance(cfg, dict) else None
        if hasattr(self, "anchor_widget"):
            try:
                self.anchor_widget.set_anchor(anchor_name)
            except Exception:
                pass
        justification = cfg.get("payloadJustification") if isinstance(cfg, dict) else None
        if hasattr(self, "justification_widget"):
            try:
                self.justification_widget.set_justification(justification)
            except Exception:
                pass
        background_color = cfg.get("backgroundColor") if isinstance(cfg, dict) else None
        background_border_color = cfg.get("backgroundBorderColor") if isinstance(cfg, dict) else None
        background_border = cfg.get("backgroundBorderWidth") if isinstance(cfg, dict) else None
        if hasattr(self, "background_widget"):
            try:
                self.background_widget.set_values(background_color, background_border_color, background_border)
            except Exception:
                pass
        self._sync_absolute_for_current_group(force_ui=True)
        self._sync_offset_pins_for_current_group()
        self._send_active_group_selection(plugin_name, label)

    def _handle_justification_changed(self, justification: str) -> None:
        selection = self._get_current_group_selection()
        if selection is None:
            return
        plugin_name, label = selection
        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.get(plugin_name)
        if not isinstance(entry, dict):
            return
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        if not isinstance(groups, dict):
            return
        group = groups.get(label)
        if not isinstance(group, dict):
            return
        group["payloadJustification"] = justification
        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                state.persist_justification(
                    plugin_name, label, justification, edit_nonce=self._edit_nonce, write=False, invalidate_cache=True
                )
                self._groupings_data = getattr(state, "_groupings_data", self._groupings_data)
                self._groupings_cache = getattr(state, "_groupings_cache", self._groupings_cache)
            except Exception:
                pass
        _controller_debug(
            "Justification changed via justification_widget for %s/%s -> %s",
            plugin_name,
            label,
            justification,
        )
        self._edit_controller.schedule_groupings_config_write()
        if state is None:
            self._invalidate_group_cache_entry(plugin_name, label)
        self._last_edit_ts = time.time()
        self._offset_live_edit_until = max(getattr(self, "_offset_live_edit_until", 0.0) or 0.0, self._last_edit_ts + 5.0)
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            try:
                timers.start_live_edit_window(5.0)
                timers.record_edit()
            except Exception:
                pass
        self._edit_nonce = f"{time.time():.6f}-{os.getpid()}"

    def _handle_background_changed(
        self,
        color: Optional[str],
        border_color: Optional[str],
        border_width: Optional[int],
    ) -> None:
        selection = self._get_current_group_selection()
        if selection is None:
            return
        plugin_name, label = selection
        normalised_color: Optional[str]
        try:
            normalised_color = _normalise_background_color(color) if color else None
        except PluginGroupingError:
            normalised_color = None
        try:
            normalised_border_color = _normalise_background_color(border_color) if border_color else None
        except PluginGroupingError:
            normalised_border_color = None
        try:
            normalised_border = (
                _normalise_border_width(border_width, "backgroundBorderWidth") if border_width is not None else 0
            )
        except PluginGroupingError:
            normalised_border = 0

        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.setdefault(plugin_name, {})
        groups = entry.setdefault("idPrefixGroups", {})
        if not isinstance(groups, dict):
            groups = {}
            entry["idPrefixGroups"] = groups
        group = groups.get(label)
        if not isinstance(group, dict):
            group = {}
            groups[label] = group
        group["backgroundColor"] = normalised_color
        group["backgroundBorderColor"] = normalised_border_color
        group["backgroundBorderWidth"] = normalised_border

        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                state.persist_background(
                    plugin_name,
                    label,
                    normalised_color,
                    normalised_border_color,
                    normalised_border,
                    edit_nonce=self._edit_nonce,
                    write=False,
                    invalidate_cache=True,
                )
                self._groupings_data = getattr(state, "_groupings_data", self._groupings_data)
                self._groupings_cache = getattr(state, "_groupings_cache", self._groupings_cache)
            except Exception:
                pass
        self._edit_controller.schedule_groupings_config_write()
        if state is None:
            self._invalidate_group_cache_entry(plugin_name, label)
        self._last_edit_ts = time.time()
        self._offset_live_edit_until = max(
            getattr(self, "_offset_live_edit_until", 0.0) or 0.0,
            self._last_edit_ts + 5.0,
        )
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            try:
                timers.start_live_edit_window(5.0)
                timers.record_edit()
            except Exception:
                pass
        self._edit_nonce = f"{time.time():.6f}-{os.getpid()}"
        self._draw_preview()
    def _handle_absolute_changed(self, axis: str) -> None:
        selection = self._get_current_group_selection()
        if selection is None or not hasattr(self, "absolute_widget"):
            return
        snapshot = self._get_group_snapshot(selection)
        if snapshot is None:
            return
        x_val, y_val = self.absolute_widget.get_px_values()
        base_x, base_y = self._compute_absolute_from_snapshot(snapshot)
        target_x = x_val if x_val is not None else base_x
        target_y = y_val if y_val is not None else base_y
        axis_token = (axis or "").lower()
        if axis_token in ("x", ""):
            target_x = self._clamp_absolute_value(target_x, "x")
        if axis_token in ("y", ""):
            target_y = self._clamp_absolute_value(target_y, "y")

        self._unpin_offset_if_moved(target_x, target_y)

        base_min_x, base_min_y, _, _ = snapshot.base_bounds
        new_offset_x = target_x - base_min_x
        new_offset_y = target_y - base_min_y
        if (
            abs(new_offset_x - snapshot.offset_x) <= self._absolute_tolerance_px
            and abs(new_offset_y - snapshot.offset_y) <= self._absolute_tolerance_px
        ):
            self._apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=True)
            return

        self._edit_controller.persist_offsets(selection, new_offset_x, new_offset_y, debounce_ms=self._offset_write_debounce_ms)
        self._refresh_current_group_snapshot(force_ui=True)

    def _unpin_offset_if_moved(self, abs_x: float, abs_y: float) -> None:
        widget = getattr(self, "offset_widget", None)
        if widget is None:
            return
        tol = getattr(self, "_absolute_tolerance_px", 0.0) or 0.0
        try:
            if abs(abs_x - ABS_MIN_X) > tol and abs(abs_x - ABS_MAX_X) > tol:
                widget.clear_pins(axis="x")
            if abs(abs_y - ABS_MIN_Y) > tol and abs(abs_y - ABS_MAX_Y) > tol:
                widget.clear_pins(axis="y")
        except Exception:
            pass

    def _handle_offset_changed(self, direction: str, pinned: bool) -> None:
        selection = self._get_current_group_selection()
        if selection is None or not hasattr(self, "absolute_widget"):
            return
        snapshot = self._get_group_snapshot(selection)
        if snapshot is None:
            return
        current_x, current_y = self.absolute_widget.get_px_values()
        if current_x is None or current_y is None:
            current_x, current_y = self._compute_absolute_from_snapshot(snapshot)
        new_x, new_y = current_x, current_y
        anchor_target = None

        if pinned:
            current_anchor = snapshot.anchor_token
            if direction == "left":
                new_x = ABS_MIN_X
            elif direction == "right":
                new_x = ABS_MAX_X
            elif direction == "up":
                new_y = ABS_MIN_Y
            elif direction == "down":
                new_y = ABS_MAX_Y
            else:
                return
            anchor_target = self._resolve_pinned_anchor(current_anchor, direction)
        else:
            step = self._offset_step_px
            if direction == "left":
                new_x = self._clamp_absolute_value(current_x - step, "x")
            elif direction == "right":
                new_x = self._clamp_absolute_value(current_x + step, "x")
            elif direction == "up":
                new_y = self._clamp_absolute_value(current_y - step, "y")
            elif direction == "down":
                new_y = self._clamp_absolute_value(current_y + step, "y")
            else:
                return

        base_min_x, base_min_y, _, _ = snapshot.base_bounds
        new_offset_x = new_x - base_min_x
        new_offset_y = new_y - base_min_y
        if (
            abs(new_offset_x - snapshot.offset_x) <= self._absolute_tolerance_px
            and abs(new_offset_y - snapshot.offset_y) <= self._absolute_tolerance_px
        ):
            self._apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=True)
            return

        self._edit_controller.persist_offsets(selection, new_offset_x, new_offset_y, debounce_ms=self._offset_write_debounce_ms)
        self._refresh_current_group_snapshot(force_ui=True)

        if pinned and anchor_target and hasattr(self, "anchor_widget"):
            try:
                self.anchor_widget.set_anchor(anchor_target)
            except Exception:
                pass
            self._handle_anchor_changed(anchor_target, prefer_user=True)

        # Freeze snapshot rebuilds briefly so cache polls don't snap preview back while holding arrows.
        # Keep preview in "live edit" mode a bit longer so cache polls/actual updates
        # cannot snap the target back while the user is holding the key.
        self._offset_live_edit_until = time.time() + 5.0
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            try:
                timers.start_live_edit_window(5.0)
            except Exception:
                pass
        # Force preview refresh immediately to mirror HUD movement.
        self._last_preview_signature = None
        try:
            self.after_idle(self._draw_preview)
        except Exception:
            self._draw_preview()
        self._schedule_offset_resync()

    def _send_active_group_selection(self, plugin_name: Optional[str], label: Optional[str]) -> None:
        plugin = (str(plugin_name or "").strip())
        group = (str(label or "").strip())
        snapshot = self._get_group_snapshot((plugin, group)) if plugin and group else None
        anchor_token = self._get_live_anchor_token(snapshot) if snapshot is not None else None
        anchor_value = (anchor_token or "").strip().lower()
        key = (plugin, group, anchor_value)
        bridge = getattr(self, "_plugin_bridge", None)
        if bridge is not None:
            try:
                sent = bridge.send_active_group(plugin, group, anchor=anchor_value, edit_nonce=getattr(self, "_edit_nonce", ""))
            except Exception:
                sent = False
            if sent:
                self._last_active_group_sent = key
                _controller_debug(
                    "Controller active group signal sent: %s/%s anchor=%s",
                    plugin or "<none>",
                    group or "<none>",
                    anchor_value or "<none>",
                )
            return
        if key == self._last_active_group_sent:
            return
        payload = {
            "cli": "controller_active_group",
            "plugin": plugin,
            "label": group,
            "anchor": anchor_value,
            "edit_nonce": getattr(self, "_edit_nonce", ""),
        }
        self._send_plugin_cli(payload)
        self._last_active_group_sent = key
        _controller_debug(
            "Controller active group signal sent: %s/%s anchor=%s",
            plugin or "<none>",
            group or "<none>",
            anchor_value or "<none>",
        )

    def _cancel_offset_resync(self) -> None:
        handle = getattr(self, "_offset_resync_handle", None)
        if handle is not None:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        self._offset_resync_handle = None

    def _schedule_offset_resync(self) -> None:
        """After the last offset change, resync preview from fresh snapshot quickly."""

        self._cancel_offset_resync()

        def _resync() -> None:
            self._offset_resync_handle = None
            self._last_preview_signature = None
            try:
                self._refresh_current_group_snapshot(force_ui=True)
            except Exception:
                pass

        try:
            self._offset_resync_handle = self.after(75, _resync)
        except Exception:
            self._offset_resync_handle = None
    def _get_current_group_selection(self) -> tuple[str, str] | None:
        if not hasattr(self, "idprefix_widget"):
            return None
        try:
            idx = int(self.idprefix_widget.dropdown.current())
        except Exception:
            return None
        if not (0 <= idx < len(self._idprefix_entries)):
            return None
        return self._idprefix_entries[idx]
    def _anchor_sides(self, anchor: str) -> tuple[str, str]:
        token = (anchor or "").lower().replace("-", "").replace("_", "")
        h = "center"
        v = "center"
        if token in {"nw", "w", "sw", "left"} or "left" in token:
            h = "left"
        elif token in {"ne", "e", "se", "right"} or "right" in token:
            h = "right"
        if token in {"nw", "n", "ne", "top"} or "top" in token:
            v = "top"
        elif token in {"sw", "s", "se", "bottom"} or "bottom" in token:
            v = "bottom"
        return h, v
    def _sync_absolute_for_current_group(
        self, force_ui: bool = False, debounce_ms: int | None = None, prefer_user: bool = False
    ) -> None:
        _ = debounce_ms, prefer_user
        self._refresh_current_group_snapshot(force_ui=force_ui)

    def _sync_offset_pins_for_current_group(self) -> None:
        widget = getattr(self, "offset_widget", None)
        if widget is None:
            return
        selection = self._get_current_group_selection()
        if selection is None:
            try:
                widget.set_pins(set())
            except Exception:
                pass
            return
        snapshot = self._get_group_snapshot(selection)
        if snapshot is None:
            try:
                widget.set_pins(set())
            except Exception:
                pass
            return

        anchor_name = None
        anchor_widget = getattr(self, "anchor_widget", None)
        if anchor_widget is not None:
            getter = getattr(anchor_widget, "get_anchor", None)
            if callable(getter):
                try:
                    anchor_name = getter()
                except Exception:
                    anchor_name = None
        anchor_token = (anchor_name or snapshot.anchor_token or "nw").strip().lower()
        horizontal, vertical = self._anchor_sides(anchor_token)

        abs_x = abs_y = None
        abs_widget = getattr(self, "absolute_widget", None)
        if abs_widget is not None:
            try:
                abs_x, abs_y = abs_widget.get_px_values()
            except Exception:
                abs_x = abs_y = None
        if abs_x is None or abs_y is None:
            fallback_x, fallback_y = self._compute_absolute_from_snapshot(snapshot)
            if abs_x is None:
                abs_x = fallback_x
            if abs_y is None:
                abs_y = fallback_y

        tol = getattr(self, "_absolute_tolerance_px", 0.0) or 0.0
        pins: set[str] = set()
        if horizontal == "left" and abs(abs_x - ABS_MIN_X) <= tol:
            pins.add("left")
        elif horizontal == "right" and abs(abs_x - ABS_MAX_X) <= tol:
            pins.add("right")
        if vertical == "top" and abs(abs_y - ABS_MIN_Y) <= tol:
            pins.add("up")
        elif vertical == "bottom" and abs(abs_y - ABS_MAX_Y) <= tol:
            pins.add("down")
        try:
            widget.set_pins(pins)
        except Exception:
            pass
    def _select_transformed_for_anchor(self, anchor: str, trans_min: float, trans_max: float, axis: str) -> float:
        horizontal, vertical = self._anchor_sides(anchor)
        side = horizontal if (axis or "").lower() == "x" else vertical
        if side in {"left", "top"}:
            return trans_min
        if side in {"right", "bottom"}:
            return trans_max
        return (trans_min + trans_max) / 2.0

    def _resolve_pinned_anchor(self, current_anchor: str, direction: str) -> str:
        anchor = (current_anchor or "").lower()
        direction = (direction or "").lower()
        horizontal, vertical = self._anchor_sides(anchor)

        if direction in {"left", "right"}:
            horizontal = direction
        elif direction in {"up", "down"}:
            vertical = "top" if direction == "up" else "bottom"

        resolved = {
            ("left", "top"): "nw",
            ("center", "top"): "top",
            ("right", "top"): "ne",
            ("left", "center"): "left",
            ("center", "center"): "center",
            ("right", "center"): "right",
            ("left", "bottom"): "sw",
            ("center", "bottom"): "bottom",
            ("right", "bottom"): "se",
        }.get((horizontal, vertical))

        return resolved or anchor

    def _expected_transformed_anchor(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        bounds = snapshot.transform_bounds
        if bounds is None:
            base_min_x, base_min_y, base_max_x, base_max_y = snapshot.base_bounds
            min_x = base_min_x + snapshot.offset_x
            min_y = base_min_y + snapshot.offset_y
            max_x = base_max_x + snapshot.offset_x
            max_y = base_max_y + snapshot.offset_y
            token = snapshot.anchor_token
        else:
            min_x, min_y, max_x, max_y = bounds
            token = snapshot.transform_anchor_token or snapshot.anchor_token
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0
        token = (token or "nw").strip().lower().replace("-", "").replace("_", "")
        if token in {"nw", "wn"}:
            return min_x, min_y
        if token in {"top", "n"}:
            return mid_x, min_y
        if token in {"ne"}:
            return max_x, min_y
        if token in {"right", "e"}:
            return max_x, mid_y
        if token in {"se"}:
            return max_x, max_y
        if token in {"bottom", "s"}:
            return mid_x, max_y
        if token in {"sw"}:
            return min_x, max_y
        if token in {"left", "w"}:
            return min_x, mid_y
        return mid_x, mid_y
    def _compute_anchor_point(self, min_x: float, max_x: float, min_y: float, max_y: float, anchor: str) -> tuple[float, float]:
        h, v = self._anchor_sides(anchor)
        ax = min_x if h == "left" else max_x if h == "right" else (min_x + max_x) / 2.0
        ay = min_y if v == "top" else max_y if v == "bottom" else (min_y + max_y) / 2.0
        return ax, ay

    def _get_live_anchor_token(self, snapshot: GroupSnapshot) -> str:
        """Best-effort anchor token sourced from the UI."""

        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.get_live_anchor_token(snapshot)
            except Exception:
                pass
        anchor_widget = getattr(self, "anchor_widget", None)
        anchor_name: str | None = None
        if anchor_widget is not None:
            getter = getattr(anchor_widget, "get_anchor", None)
            if callable(getter):
                try:
                    anchor_name = getter()
                except Exception:
                    anchor_name = None
        return (anchor_name or snapshot.anchor_token or "nw").strip().lower()

    def _get_live_absolute_anchor(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        """Return anchor coordinates, preferring unsaved widget values when available."""

        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.get_live_absolute_anchor(snapshot)
            except Exception:
                pass
        default_x, default_y = self._compute_absolute_from_snapshot(snapshot)
        abs_widget = getattr(self, "absolute_widget", None)
        if abs_widget is None:
            return default_x, default_y

        try:
            user_x, user_y = abs_widget.get_px_values()
        except Exception:
            user_x = user_y = None

        resolved_x = default_x if user_x is None else self._clamp_absolute_value(float(user_x), "x")
        resolved_y = default_y if user_y is None else self._clamp_absolute_value(float(user_y), "y")
        return resolved_x, resolved_y

    def _get_target_dimensions(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        """Use the actual placement bounds as the target frame size."""

        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.get_target_dimensions(snapshot)
            except Exception:
                pass
        bounds = snapshot.transform_bounds or snapshot.base_bounds
        min_x, min_y, max_x, max_y = bounds
        width = max(0.0, float(max_x - min_x))
        height = max(0.0, float(max_y - min_y))
        return width, height

    def _bounds_from_anchor_point(
        self, anchor: str, anchor_x: float, anchor_y: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        """Translate an anchor coordinate into bounding box edges."""

        controller = safe_getattr(self, "_preview_controller")
        if controller is not None:
            try:
                return controller.bounds_from_anchor_point(anchor, anchor_x, anchor_y, width, height)
            except Exception:
                pass
        width = max(width, 0.0)
        height = max(height, 0.0)
        horizontal, vertical = self._anchor_sides(anchor)

        if horizontal == "left":
            min_x = anchor_x
            max_x = anchor_x + width
        elif horizontal == "right":
            max_x = anchor_x
            min_x = anchor_x - width
        else:
            min_x = anchor_x - (width / 2.0)
            max_x = min_x + width

        if vertical == "top":
            min_y = anchor_y
            max_y = anchor_y + height
        elif vertical == "bottom":
            max_y = anchor_y
            min_y = anchor_y - height
        else:
            min_y = anchor_y - (height / 2.0)
            max_y = min_y + height

        return min_x, min_y, max_x, max_y

    def _resolve_target_frame(self, snapshot: GroupSnapshot) -> tuple[tuple[float, float, float, float], tuple[float, float]] | None:
        """Return ((min_x, min_y, max_x, max_y), (anchor_x, anchor_y)) for the simulated placement."""

        controller = self.__dict__.get("_preview_controller")
        if controller is not None:
            try:
                return controller.resolve_target_frame(snapshot)
            except Exception:
                pass
        width, height = self._get_target_dimensions(snapshot)
        if width <= 0.0 or height <= 0.0:
            return None
        anchor_token = self._get_live_anchor_token(snapshot)
        anchor_x, anchor_y = self._get_live_absolute_anchor(snapshot)
        bounds = self._bounds_from_anchor_point(anchor_token, anchor_x, anchor_y, width, height)
        return bounds, (anchor_x, anchor_y)


    def _invalidate_group_cache_entry(self, plugin_name: str, label: str) -> None:
        """POC: clear transformed cache for a group and bump timestamp so HUD follows controller."""

        if not plugin_name or not label:
            return
        path = getattr(self, "_groupings_cache_path", None)
        if path is None:
            root = Path(__file__).resolve().parents[1]
            path = root / "overlay_group_cache.json"
            self._groupings_cache_path = path
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        groups = raw.get("groups")
        if not isinstance(groups, dict):
            return
        plugin_entry = groups.get(plugin_name)
        if not isinstance(plugin_entry, dict):
            return
        entry = plugin_entry.get(label)
        if not isinstance(entry, dict):
            return
        entry["transformed"] = None
        base_entry = entry.get("base")
        if isinstance(base_entry, dict):
            base_entry["has_transformed"] = False
            base_entry["edit_nonce"] = getattr(self, "_edit_nonce", "")
        entry["last_updated"] = time.time()
        entry["edit_nonce"] = getattr(self, "_edit_nonce", "")
        try:
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            tmp_path.replace(path)
            self._groupings_cache = raw
        except Exception:
            pass

    def _get_cache_entry(
        self, plugin_name: str, label: str
    ) -> tuple[dict[str, float], dict[str, float], str, float]:
        groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}
        plugin_entry = groups.get(plugin_name) if isinstance(groups, dict) else {}
        entry = plugin_entry.get(label) if isinstance(plugin_entry, dict) else {}
        normalized = entry.get("base") if isinstance(entry, dict) else {}
        transformed = entry.get("transformed") if isinstance(entry, dict) else {}
        norm_vals = {
            "min_x": float(normalized.get("base_min_x", 0.0)) if isinstance(normalized, dict) else 0.0,
            "max_x": float(normalized.get("base_max_x", 0.0)) if isinstance(normalized, dict) else 0.0,
            "min_y": float(normalized.get("base_min_y", 0.0)) if isinstance(normalized, dict) else 0.0,
            "max_y": float(normalized.get("base_max_y", 0.0)) if isinstance(normalized, dict) else 0.0,
        }
        norm_vals["width"] = float(normalized.get("base_width", norm_vals["max_x"] - norm_vals["min_x"])) if isinstance(normalized, dict) else (norm_vals["max_x"] - norm_vals["min_x"])
        norm_vals["height"] = float(normalized.get("base_height", norm_vals["max_y"] - norm_vals["min_y"])) if isinstance(normalized, dict) else (norm_vals["max_y"] - norm_vals["min_y"])
        trans_vals = {
            "min_x": float(transformed.get("trans_min_x", norm_vals["min_x"])) if isinstance(transformed, dict) else norm_vals["min_x"],
            "max_x": float(transformed.get("trans_max_x", norm_vals["max_x"])) if isinstance(transformed, dict) else norm_vals["max_x"],
            "min_y": float(transformed.get("trans_min_y", norm_vals["min_y"])) if isinstance(transformed, dict) else norm_vals["min_y"],
            "max_y": float(transformed.get("trans_max_y", norm_vals["max_y"])) if isinstance(transformed, dict) else norm_vals["max_y"],
        }
        anchor = transformed.get("anchor") if isinstance(transformed, dict) else None
        anchor_name = str(anchor).lower() if isinstance(anchor, str) else "top-left"
        timestamp = float(entry.get("last_updated", 0.0)) if isinstance(entry, dict) else 0.0
        return norm_vals, trans_vals, anchor_name, timestamp
    def _set_config_offsets(self, plugin_name: str, label: str, offset_x: float, offset_y: float) -> None:
        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.get(plugin_name)
        if not isinstance(entry, dict):
            return
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        if not isinstance(groups, dict):
            return
        group = groups.get(label)
        if not isinstance(group, dict):
            return
        # Round to reduce float noise while keeping sub-pixel precision.
        group["offsetX"] = round(offset_x, 3)
        group["offsetY"] = round(offset_y, 3)
    def _handle_anchor_changed(self, anchor: str, prefer_user: bool = False) -> None:
        selection = self._get_current_group_selection()
        if selection is None:
            return
        captured = self._capture_anchor_restore_state(selection)
        plugin_name, label = selection
        if not isinstance(self._groupings_data, dict):
            return
        entry = self._groupings_data.get(plugin_name)
        if not isinstance(entry, dict):
            return
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        if not isinstance(groups, dict):
            return
        group = groups.get(label)
        if not isinstance(group, dict):
            return
        group["idPrefixGroupAnchor"] = anchor
        self._edit_controller.schedule_groupings_config_write()
        state = safe_getattr(self, "_group_state")
        if state is not None:
            try:
                state.persist_anchor(plugin_name, label, anchor, edit_nonce=self._edit_nonce, write=False, invalidate_cache=True)
                self._groupings_data = getattr(state, "_groupings_data", self._groupings_data)
                self._groupings_cache = getattr(state, "_groupings_cache", self._groupings_cache)
            except Exception:
                pass
        _controller_debug(
            "Anchor changed via anchor_widget for %s/%s -> %s (prefer_user=%s)",
            plugin_name,
            label,
            anchor,
            prefer_user,
        )

        self._last_edit_ts = time.time()
        self._offset_live_edit_until = max(getattr(self, "_offset_live_edit_until", 0.0) or 0.0, self._last_edit_ts + 5.0)
        timers = getattr(self, "_mode_timers", None)
        if timers is not None:
            try:
                timers.start_live_edit_window(5.0)
                timers.record_edit()
            except Exception:
                pass
        self._edit_nonce = f"{time.time():.6f}-{os.getpid()}"
        self._sync_absolute_for_current_group(force_ui=True, prefer_user=prefer_user)
        self._draw_preview()
        if captured:
            self._schedule_anchor_restore(selection)
        # Notify client of anchor change for active group selection.
        self._send_active_group_selection(plugin_name, label)
        if state is None:
            self._invalidate_group_cache_entry(plugin_name, label)
        snapshot = self._group_snapshots.get(selection)
        if snapshot is not None:
            snapshot.has_transform = False
            snapshot.transform_bounds = snapshot.base_bounds
            snapshot.transform_anchor_token = snapshot.anchor_token
            snapshot.transform_anchor = snapshot.base_anchor
            snapshot.anchor_token = anchor
            snapshot.transform_anchor_token = anchor
            base_min_x, base_min_y, base_max_x, base_max_y = snapshot.base_bounds
            snapshot.base_anchor = self._compute_anchor_point(base_min_x, base_max_x, base_min_y, base_max_y, anchor)
            snapshot.transform_anchor = snapshot.base_anchor
            self._group_snapshots[selection] = snapshot

    def _on_configure_activity(self) -> None:
        """Track recent move/resize to avoid closing during window drag."""

        self._moving_guard_active = True
        if self._moving_guard_job is not None:
            try:
                self.after_cancel(self._moving_guard_job)
            except Exception:
                pass
        self._moving_guard_job = self.after(self._move_guard_timeout_ms, self._handle_move_guard_expired)
        self._cancel_pending_close()

    def _handle_move_guard_expired(self) -> None:
        self._moving_guard_job = None
        self._moving_guard_active = False
        if self._pending_focus_out and not self._is_app_focused():
            self._schedule_focus_out_close()
        self._pending_focus_out = False

    def enter_focus_mode(self, _event: tk.Event[tk.Misc] | None = None) -> str | None:  # type: ignore[name-defined]
        """Lock the current selection so arrows no longer move it."""

        if not self.widget_select_mode:
            return
        if self.widget_focus_area == "sidebar" and not getattr(self, "_group_controls_enabled", True):
            if getattr(self, "_sidebar_focus_index", 0) > 0:
                return "break"
        self.widget_select_mode = False
        self._on_focus_mode_entered()
        self._refresh_widget_focus()
        return "break"

    def exit_focus_mode(self) -> None:
        """Return to selection mode so the highlight can move again."""

        if self.widget_select_mode:
            return
        self.widget_select_mode = True
        self._on_focus_mode_exited()
        self._refresh_widget_focus()

    def _apply_placement_state(self) -> None:
        """Show the correct placement frame for the current state."""

        self.update_idletasks()
        viewable = False
        try:
            viewable = bool(self.winfo_viewable())
        except Exception:
            viewable = False
        if viewable and not self._initial_geometry_applied:
            current_height = max(self.base_min_height, self.winfo_reqheight())
            self._initial_geometry_applied = True
        else:
            current_height = max(self.winfo_height(), self.base_min_height)
        open_outer_padding = self.container_pad_left + self.container_pad_right_open
        closed_outer_padding = self.container_pad_left + self.container_pad_right_closed
        sidebar_total_open = self.sidebar_width + self.sidebar_pad
        sidebar_total_closed = self.sidebar_width
        open_min_width = open_outer_padding + sidebar_total_open + self.placement_min_width
        closed_min_width = (
            closed_outer_padding + sidebar_total_closed + self.closed_min_width + self.indicator_hit_width
        )

        if self._placement_open:
            self.container.grid_configure(
                padx=(self.container_pad_left, self.container_pad_right_open)
            )
            self._current_right_pad = self.container_pad_right_open
            self.placement_frame.grid(
                row=0,
                column=1,
                sticky="nsew",
                padx=(self.placement_overlay_padding, self.placement_overlay_padding),
                pady=(self.placement_overlay_padding, self.placement_overlay_padding),
            )
            self.container.grid_columnconfigure(1, weight=1, minsize=self.placement_min_width)
            self.update_idletasks()
            target_width = max(self._open_width, self.winfo_reqwidth(), open_min_width)
            self.minsize(open_min_width, self.base_min_height)
            self.geometry(f"{int(target_width)}x{int(current_height)}")
            self._open_width = max(self._open_width, self.winfo_width(), self.winfo_reqwidth(), open_min_width)
            self._current_direction = "left"
        else:
            self.container.grid_configure(
                padx=(self.container_pad_left, self.container_pad_right_closed)
            )
            self._current_right_pad = self.container_pad_right_closed
            self.placement_frame.grid_forget()
            self.container.grid_columnconfigure(1, weight=0, minsize=self.indicator_hit_width)
            self.update_idletasks()
            sidebar_width = max(self.sidebar_width, self.sidebar.winfo_reqwidth())
            pad_between = self.sidebar_pad_closed
            collapsed_width = (
                self.container_pad_left
                + self.container_pad_right_closed
                + pad_between
                + sidebar_width
                + self.indicator_hit_width
            )
            collapsed_width = max(collapsed_width, closed_min_width)
            self.minsize(collapsed_width, self.base_min_height)
            self.geometry(f"{int(collapsed_width)}x{int(current_height)}")
            self._current_direction = "right"

        pad = self.sidebar_pad if self._placement_open else self.sidebar_pad_closed
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, pad))
        self._current_sidebar_pad = pad
        self.update_idletasks()
        self._show_indicator(direction=self._current_direction)
        self._refresh_widget_focus()

    def _show_indicator(self, direction: str) -> None:
        """Display a triangle indicator; direction is 'left' or 'right'."""

        self.update_idletasks()
        sidebar_right = self.sidebar.winfo_x() + self.sidebar.winfo_width()
        pad_between = self._current_sidebar_pad
        gap_available = pad_between if pad_between > 0 else self.indicator_hit_width
        hit_width = min(self.indicator_hit_width, max(self.indicator_width, gap_available))
        self.indicator_wrapper.config(width=hit_width)
        right_bias = max(0, hit_width - self.indicator_width)
        indicator_x = sidebar_right + max(0, (gap_available - hit_width) / 2) - right_bias
        indicator_x = max(0, indicator_x)
        y = max(
            self.container_pad_vertical,
            (self.container.winfo_height() - self.indicator_height) / 2,
        )
        self.indicator_wrapper.place(x=indicator_x, y=y)
        try:
            self.indicator_wrapper.lift()
        except Exception:
            pass
        self.indicator_canvas.configure(width=hit_width, height=self.indicator_height)
        self.indicator_canvas.delete("all")
        arrow_height = self.indicator_height / self.indicator_count
        for i in range(self.indicator_count):
            top = i * arrow_height
            if direction == "left":
                base_x = hit_width
                tip_x = max(0, base_x - self.indicator_width)
            else:
                base_x = max(0, hit_width - self.indicator_width)
                tip_x = hit_width
            points = (
                base_x,
                top,
                base_x,
                top + arrow_height,
                tip_x,
                top + (arrow_height / 2),
            )
            self.indicator_canvas.create_polygon(*points, fill="black")

    def _hide_indicator(self) -> None:
        """Hide the collapse indicator."""

        self.indicator_canvas.place_forget()

    def _handle_configure(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Re-center the indicator when the window is resized."""

        self._show_indicator(direction=self._current_direction)
        self._on_configure_activity()
        self._refresh_widget_focus()

    def _handle_return_key(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if self._handle_active_widget_key("Return", event):
            return "break"
        return None

    def _handle_space_key(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if self._handle_active_widget_key("space", event):
            return "break"
        return None

    def _center_and_show(self) -> None:
        """Center the window before making it visible to avoid jumpiness."""

        self._capture_foreground_window()
        self._center_on_screen()
        try:
            self.deiconify()
            self.lift()
            self._raise_on_windows()
            self._focus_on_show()
        except Exception:
            pass
        # Ensure indicator is positioned after the first real layout pass.
        try:
            self.after_idle(self._apply_placement_state)
            self.after_idle(lambda: self._show_indicator(direction=self._current_direction))
        except Exception:
            pass

    def _get_elite_window_bounds(self) -> tuple[int, int, int, int] | None:
        """Best-effort probe for the Elite Dangerous window for centering."""

        logger = _ensure_controller_logger(PLUGIN_ROOT) or logging.getLogger("overlay_controller.window_probe")
        try:
            tracker = create_elite_window_tracker(logger)
        except Exception as exc:
            _controller_debug("Elite window tracker unavailable: %s", exc)
            return None
        if tracker is None:
            return None
        try:
            state = tracker.poll()
        except Exception as exc:
            _controller_debug("Elite window probe failed: %s", exc)
            return None
        if state is None or state.width <= 0 or state.height <= 0:
            return None

        x = state.global_x if state.global_x is not None else state.x
        y = state.global_y if state.global_y is not None else state.y
        if x is None or y is None:
            return None

        _controller_debug(
            "Centering controller on Elite window at %dx%d+%d+%d",
            state.width,
            state.height,
            x,
            y,
        )
        return int(x), int(y), int(state.width), int(state.height)

    def _center_on_screen(self) -> None:
        """Position the window at the center of the available screen."""

        self.update_idletasks()
        width = max(1, self.winfo_width() or self.winfo_reqwidth())
        height = max(1, self.winfo_height() or self.winfo_reqheight())
        target_bounds = self._get_elite_window_bounds()
        if target_bounds is None:
            origin_x, origin_y, screen_width, screen_height = self._get_primary_screen_bounds()
        else:
            origin_x, origin_y, screen_width, screen_height = target_bounds

        x = int(origin_x + (screen_width - width) / 2)
        y = int(origin_y + (screen_height - height) / 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _get_primary_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) for the primary monitor."""

        # Platform-specific primary monitor detection; fallback to Tk defaults.
        bounds = self._get_windows_primary_bounds()
        if bounds:
            return bounds

        bounds = self._get_xrandr_primary_bounds()
        if bounds:
            return bounds

        width = max(1, self.winfo_screenwidth())
        height = max(1, self.winfo_screenheight())
        return 0, 0, width, height

    def _get_windows_primary_bounds(self) -> tuple[int, int, int, int] | None:
        if platform.system() != "Windows":
            return None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # Ensure correct dimensions on high-DPI displays.
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            return 0, 0, width, height
        except Exception:
            return None

    def _get_xrandr_primary_bounds(self) -> tuple[int, int, int, int] | None:
        if platform.system() != "Linux":
            return None
        try:
            result = subprocess.run(
                ["xrandr", "--query"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None

        for line in result.stdout.splitlines():
            if " primary " not in line:
                continue
            match = re.search(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", line)
            if not match:
                continue
            width, height, x, y = map(int, match.groups())
            return x, y, width, height

        return None

    def _raise_on_windows(self) -> None:
        """Best-effort bring-to-front for Windows without staying always-on-top."""

        if platform.system() != "Windows":
            return
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            hwnd = self.winfo_id()

            SW_SHOW = 5
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2

            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, 0)
            cur_tid = kernel32.GetCurrentThreadId()

            attached = False
            try:
                if fg_tid and fg_tid != cur_tid:
                    attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))

                user32.ShowWindow(hwnd, SW_SHOW)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                user32.SetFocus(hwnd)
                user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )
                user32.SetWindowPos(
                    hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )
            finally:
                if attached:
                    try:
                        user32.AttachThreadInput(fg_tid, cur_tid, False)
                    except Exception:
                        pass
        except Exception:
            pass

    def _focus_on_show(self) -> None:
        """Attempt to give the controller focus after showing it."""

        try:
            if platform.system() == "Windows":
                self.focus_force()
                self.after_idle(lambda: self.focus_force())
            else:
                self.focus_set()
                self.after_idle(lambda: self.focus_set())
        except Exception:
            pass

    def _capture_foreground_window(self) -> None:
        """Remember the current foreground window before we take focus (Windows only)."""

        self._previous_foreground_hwnd = None
        if platform.system() != "Windows":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            hwnd = int(user32.GetForegroundWindow())
            self._previous_foreground_hwnd = hwnd or None
        except Exception:
            self._previous_foreground_hwnd = None

    def _restore_foreground_window(self) -> None:
        """Best-effort restore focus to the window that was foreground before we opened."""

        if platform.system() != "Windows":
            self._previous_foreground_hwnd = None
            return

        target_hwnd = self._previous_foreground_hwnd
        self._previous_foreground_hwnd = None
        if not target_hwnd:
            return

        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            current_hwnd = None
            try:
                current_hwnd = int(self.winfo_id())
            except Exception:
                current_hwnd = None
            if current_hwnd and current_hwnd == int(target_hwnd):
                return

            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, 0)
            cur_tid = kernel32.GetCurrentThreadId()

            attached = False
            try:
                if fg_tid and fg_tid != cur_tid:
                    attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))
                user32.SetForegroundWindow(target_hwnd)
                user32.SetActiveWindow(target_hwnd)
                user32.SetFocus(target_hwnd)
            finally:
                if attached:
                    try:
                        user32.AttachThreadInput(fg_tid, cur_tid, False)
                    except Exception:
                        pass
        except Exception:
            pass


def _log_startup_failure(root_path: Path, exc: BaseException) -> None:
    """Write controller startup failures to a log file (best effort)."""
    _append_controller_log(
        root_path,
        [
            "Failed to start overlay controller:",
            *traceback.format_exception(type(exc), exc, exc.__traceback__),
        ],
        announce=True,
    )


def _log_startup_event(root_path: Path, message: str) -> None:
    """Write a simple startup confirmation to the controller log."""
    _append_controller_log(root_path, [message], announce=True)


def _append_controller_log(root_path: Path, lines: list[str], *, announce: bool = False) -> None:
    # Align controller logs with overlay_client/overlay_payloads location (…/EDMarketConnector/logs/EDMCModernOverlay)
    logger = _ensure_controller_logger(root_path)
    wrote = False
    if logger is not None:
        for line in lines:
            logger.info(line.rstrip("\n"))
        wrote = True
    else:
        try:
            for line in lines:
                sys.stderr.write(line if line.endswith("\n") else line + "\n")
        except Exception:
            pass
    if announce:
        try:
            log_path = _resolve_controller_log_path(root_path)
            sys.stderr.write(
                f"[overlay-controller] log {'written' if wrote else 'failed'} at {log_path}\n"
            )
        except Exception:
            pass


def _resolve_controller_log_path(root_path: Path) -> Path:
    log_dir = resolve_logs_dir(root_path, log_dir_name="EDMCModernOverlay")
    return log_dir / "overlay_controller.log"


def _ensure_controller_logger(root_path: Path) -> Optional[logging.Logger]:
    global _CONTROLLER_LOGGER
    if _CONTROLLER_LOGGER is not None:
        return _CONTROLLER_LOGGER
    try:
        log_dir = resolve_logs_dir(root_path, log_dir_name="EDMCModernOverlay")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        handler = None
        try:
            handler = build_rotating_file_handler(
                log_dir,
                "overlay_controller.log",
                retention=5,
                max_bytes=512 * 1024,
                formatter=formatter,
            )
        except Exception:
            fallback_dir = Path(tempfile.gettempdir()) / "EDMCModernOverlay" / "controller_logs"
            try:
                handler = build_rotating_file_handler(
                    fallback_dir,
                    "overlay_controller.log",
                    retention=5,
                    max_bytes=512 * 1024,
                    formatter=formatter,
                )
            except Exception:
                handler = None
        if handler is None:
            return None
        logger = logging.getLogger("EDMCModernOverlay.Controller")
        resolved_level = resolve_log_level(DEBUG_CONFIG_ENABLED)
        level_source = "default"
        hint_level: Optional[int] = None
        hint_name: Optional[str] = None
        hint_source: Optional[str] = None

        def _coerce_candidate(value: Optional[int], name: Optional[str]) -> tuple[Optional[int], Optional[str]]:
            candidate = value
            candidate_name = name
            if candidate is None and candidate_name:
                attr = getattr(logging, candidate_name.upper(), None)
                if isinstance(attr, int):
                    candidate = int(attr)
            if candidate is not None and candidate_name is None:
                candidate_name = logging.getLevelName(candidate)
            return candidate, candidate_name

        if _LOG_LEVEL_OVERRIDE_VALUE is not None or _LOG_LEVEL_OVERRIDE_NAME:
            candidate, candidate_name = _coerce_candidate(_LOG_LEVEL_OVERRIDE_VALUE, _LOG_LEVEL_OVERRIDE_NAME)
            if candidate is not None:
                resolved_level = int(candidate)
                level_source = _LOG_LEVEL_OVERRIDE_SOURCE or "override"
                hint_level = resolved_level
                hint_name = candidate_name or logging.getLevelName(hint_level)
                hint_source = level_source
        elif _ENV_LOG_LEVEL_VALUE is not None or _ENV_LOG_LEVEL_NAME:
            candidate, candidate_name = _coerce_candidate(_ENV_LOG_LEVEL_VALUE, _ENV_LOG_LEVEL_NAME)
            if candidate is not None:
                resolved_level = int(candidate)
                level_source = "env"
                hint_level = resolved_level
                hint_name = candidate_name or logging.getLevelName(hint_level)
                hint_source = level_source

        dev_override_applied = False
        if DEBUG_CONFIG_ENABLED and resolved_level > logging.DEBUG:
            dev_override_applied = True
            if hint_level is None:
                hint_level = resolved_level
                hint_name = logging.getLevelName(hint_level)
                hint_source = level_source
            resolved_level = logging.DEBUG

        logger.setLevel(resolved_level)
        logger.propagate = False
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.debug(
            "Controller logger initialised: path=%s level=%s retention=%d max_bytes=%d",
            getattr(handler, "baseFilename", log_dir / "overlay_controller.log"),
            logging.getLevelName(logger.level),
            5,
            512 * 1024,
        )
        if dev_override_applied:
            logger.info(
                "Controller logger level forced to DEBUG via dev-mode override (original hint=%s from %s)",
                hint_name or logging.getLevelName(hint_level or logging.DEBUG),
                hint_source or level_source,
            )
        elif level_source in {"env", "override"}:
            level_name = hint_name or logging.getLevelName(resolved_level)
            telemetry_level = resolved_level if resolved_level >= logging.INFO else logging.INFO
            logger.log(
                telemetry_level,
                "Controller logger level forced to %s via %s",
                level_name,
                level_source,
            )
        _CONTROLLER_LOGGER = logger
        return logger
    except Exception:
        return None


def _controller_debug(message: str, *args: object) -> None:
    logger = _ensure_controller_logger(PLUGIN_ROOT)
    if logger is not None:
        logger.debug(message, *args)
    else:
        try:
            sys.stderr.write((message % args) + "\n")
        except Exception:
            pass


def set_log_level_hint(value: Optional[int], name: Optional[str] = None, source: str = "override") -> None:
    """Test hook to override the controller log level without relying on env."""

    global _LOG_LEVEL_OVERRIDE_VALUE, _LOG_LEVEL_OVERRIDE_NAME, _LOG_LEVEL_OVERRIDE_SOURCE, _CONTROLLER_LOGGER
    _LOG_LEVEL_OVERRIDE_VALUE = value
    _LOG_LEVEL_OVERRIDE_NAME = name
    _LOG_LEVEL_OVERRIDE_SOURCE = source
    _CONTROLLER_LOGGER = None


def launch() -> None:
    """Entry point used by other modules."""

    root_path = Path(__file__).resolve().parents[1]
    _controller_debug("Launching overlay controller: python=%s cwd=%s", sys.executable, Path.cwd())
    if _ENV_LOG_LEVEL_VALUE is not None or _ENV_LOG_LEVEL_NAME:
        _controller_debug(
            "EDMC log level hint: value=%s name=%s",
            _ENV_LOG_LEVEL_VALUE,
            _ENV_LOG_LEVEL_NAME or "unknown",
        )
    pid_path = root_path / "overlay_controller.pid"
    try:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    else:
        atexit.register(lambda: pid_path.unlink(missing_ok=True))

    try:
        app = OverlayConfigApp()
        _log_startup_event(root_path, "Overlay controller started")
        app.mainloop()
    except Exception as exc:
        _controller_debug("Overlay controller launch failed: %s", exc)
        _log_startup_failure(root_path, exc)
        raise


if __name__ == "__main__":
    launch()
_CONTROLLER_LOGGER: Optional[logging.Logger] = None
