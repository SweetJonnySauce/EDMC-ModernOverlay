"""Tkinter scaffolding for the Overlay Controller tool."""

from __future__ import annotations

# ruff: noqa: E402

import atexit
import json
import os
import tkinter as tk
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
import logging
import math
from math import ceil
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any, Dict, Optional, Tuple

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_CONTROLLER_LOGGER: Optional[logging.Logger] = None

from overlay_client.controller_mode import ControllerModeProfile, ModeProfile
from overlay_client.debug_config import DEBUG_CONFIG_ENABLED
from overlay_client.logging_utils import build_rotating_file_handler, resolve_log_level, resolve_logs_dir
from overlay_plugin.groupings_diff import diff_groupings, is_empty_diff
from overlay_plugin.groupings_loader import GroupingsLoader
from overlay_client.group_transform import GroupTransform
from overlay_client.viewport_helper import BASE_HEIGHT as VC_BASE_HEIGHT, BASE_WIDTH as VC_BASE_WIDTH, ScaleMode
from overlay_client.viewport_transform import ViewportState, build_viewport, compute_proportional_translation
from overlay_client.window_utils import compute_legacy_mapper
try:  # When run as a package (`python -m overlay_controller.overlay_controller`)
    from overlay_controller.input_bindings import BindingConfig, BindingManager
    from overlay_controller.selection_overlay import SelectionOverlay
    from overlay_controller.services import GroupStateService
except ImportError:  # Fallback for spec-from-file/test harness
    from input_bindings import BindingConfig, BindingManager  # type: ignore
    from selection_overlay import SelectionOverlay  # type: ignore
    from services import GroupStateService  # type: ignore

ABS_BASE_WIDTH = 1280
ABS_BASE_HEIGHT = 960
ABS_MIN_X = 0.0
ABS_MAX_X = float(ABS_BASE_WIDTH)
ABS_MIN_Y = 0.0
ABS_MAX_Y = float(ABS_BASE_HEIGHT)


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


@dataclass
class _GroupSnapshot:
    plugin: str
    label: str
    anchor_token: str  # desired/configured anchor
    transform_anchor_token: str
    offset_x: float
    offset_y: float
    base_bounds: Tuple[float, float, float, float]
    base_anchor: Tuple[float, float]
    transform_bounds: Optional[Tuple[float, float, float, float]]
    transform_anchor: Optional[Tuple[float, float]]
    has_transform: bool = False
    cache_timestamp: float = 0.0


def _alt_modifier_active(widget: tk.Misc | None, event: object | None) -> bool:  # type: ignore[name-defined]
    """Return True when Alt is genuinely held down, with Windows-friendly detection."""

    state = getattr(event, "state", 0) or 0
    alt_mask = bool(state & 0x0008) or bool(state & 0x20000)
    if sys.platform.startswith("win"):
        try:
            root = widget.winfo_toplevel() if widget is not None else None
        except Exception:
            root = None
        if root is not None and hasattr(root, "_alt_active"):
            if not alt_mask:
                try:
                    root._alt_active = False  # type: ignore[attr-defined]
                except Exception:
                    pass
                return False
            return bool(getattr(root, "_alt_active", False))
    return alt_mask


class _ForceRenderOverrideManager:
    """Manages temporary force-render overrides while the controller is open."""

    def __init__(self, root: Path) -> None:
        self._settings_path = root / "overlay_settings.json"
        self._port_path = root / "port.json"
        self._active = False
        self._previous_force: Optional[bool] = None
        self._previous_allow: Optional[bool] = None

    def activate(self) -> None:
        if self._active:
            return
        current_force, current_allow = self._read_force_settings()
        self._previous_force = current_force
        self._previous_allow = current_allow
        response = self._send_override({"cli": "force_render_override", "allow": True, "force_render": True})
        if response is not None:
            previous_force = response.get("previous_force_render")
            if isinstance(previous_force, bool):
                self._previous_force = previous_force
            previous_allow = response.get("previous_allow")
            if isinstance(previous_allow, bool):
                self._previous_allow = previous_allow
        else:
            if self._previous_force is None:
                self._previous_force = False
            if self._previous_allow is None:
                self._previous_allow = False
            self._update_settings_file(force=True, allow=True)
        self._active = True

    def deactivate(self) -> None:
        if not self._active:
            return
        restore_force = self._previous_force if self._previous_force is not None else False
        restore_allow = self._previous_allow if self._previous_allow is not None else False
        response = self._send_override(
            {
                "cli": "force_render_override",
                "allow": restore_allow,
                "force_render": restore_force,
            }
        )
        if response is None:
            self._log("Overlay CLI unavailable while restoring force-render override; writing settings file directly.")
            self._update_settings_file(force=restore_force, allow=restore_allow)
        else:
            self._update_settings_file(force=restore_force, allow=restore_allow)
        self._active = False
        self._previous_force = None
        self._previous_allow = None

    def _send_override(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        port = self._load_port()
        if port is None:
            return None
        message = json.dumps(payload, ensure_ascii=False)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
                sock.settimeout(2.0)
                writer = sock.makefile("w", encoding="utf-8", newline="\n")
                reader = sock.makefile("r", encoding="utf-8")
                writer.write(message)
                writer.write("\n")
                writer.flush()
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    line = reader.readline()
                    if not line:
                        break
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(response, dict):
                        status = response.get("status")
                        if status == "ok":
                            return response
                        if status == "error":
                            error_msg = response.get("error")
                            if error_msg:
                                self._log(f"Overlay client rejected force-render override: {error_msg}")
                            return None
        except OSError:
            return None
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return None
        return None

    def _load_port(self) -> Optional[int]:
        try:
            data = json.loads(self._port_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        port = data.get("port")
        if not isinstance(port, int) or port <= 0:
            return None
        return port

    def _read_force_settings(self) -> tuple[bool, bool]:
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False, False
        except json.JSONDecodeError:
            return False, False
        return bool(raw.get("force_render", False)), bool(raw.get("allow_force_render_release", False))

    def _update_settings_file(self, force: bool, allow: bool) -> None:
        try:
            raw = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except json.JSONDecodeError:
            raw = {}
        raw["force_render"] = bool(force)
        raw["allow_force_render_release"] = bool(allow)
        try:
            self._settings_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _log(message: str) -> None:
        print(f"[overlay-controller] {message}", file=sys.stderr)


class IdPrefixGroupWidget(tk.Frame):
    """Composite control with a dropdown selector (placeholder for future inputs)."""

    def __init__(self, parent: tk.Widget, options: list[str] | None = None) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._choices = options or []
        self._selection = tk.StringVar()
        self._dropdown_posted = False
        self._request_focus: callable | None = None
        self._on_selection_changed: callable | None = None
        self.dropdown = ttk.Combobox(
            self,
            values=self._choices,
            state="readonly",
            textvariable=self._selection,
            width=24,
        )
        if self._choices:
            self.dropdown.current(0)
        alt_sequences = (
            "<Alt-Up>",
            "<Alt-Down>",
            "<Alt-Left>",
            "<Alt-Right>",
            "<Alt-KeyPress-Up>",
            "<Alt-KeyPress-Down>",
            "<Alt-KeyPress-Left>",
            "<Alt-KeyPress-Right>",
        )
        block_classes = ("TComboboxListbox", "Listbox", "TComboboxPopdown")
        for seq in alt_sequences:
            self.dropdown.bind(seq, lambda _e: "break")
            for class_name in block_classes:
                try:
                    self.dropdown.bind_class(class_name, seq, lambda _e: "break")
                except Exception:
                    continue
        # Ensure arrow keys stay local to this widget/popdown so we can handle navigation ourselves.
        for seq in ("<Left>", "<Right>", "<Up>", "<Down>"):
            self.dropdown.bind(seq, self._handle_arrow_key, add="+")
            for class_name in block_classes:
                try:
                    self.dropdown.bind_class(class_name, seq, self._handle_arrow_key, add="+")
                except Exception:
                    continue
        self._build_triangles()
        self.dropdown.bind("<Button-1>", self._handle_dropdown_click, add="+")
        self.dropdown.bind("<<ComboboxSelected>>", self._handle_selection_change, add="+")

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(0, weight=1)

        self.dropdown.grid(row=0, column=1, padx=0, pady=0)

    def update_options(self, options: list[str], selected_index: int | None = None) -> None:
        """Replace dropdown options and apply selection if provided."""

        self._choices = options or []
        try:
            self.dropdown.configure(values=self._choices)
        except Exception:
            pass
        if selected_index is not None and 0 <= selected_index < len(self._choices):
            try:
                self.dropdown.current(selected_index)
            except Exception:
                selected_index = None
        if selected_index is None:
            try:
                self._selection.set("")
                self.dropdown.set("")
            except Exception:
                pass

    def on_focus_enter(self) -> None:
        """Called when the host enters focus mode for this widget."""

        try:
            self.dropdown.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        """Called when the host exits focus mode for this widget."""

        try:
            # Return focus to the toplevel so no inner control keeps focus.
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def _is_dropdown_open(self) -> bool:
        """Return True when the combobox popdown is visible."""

        try:
            popdown = self.dropdown.tk.call("ttk::combobox::PopdownWindow", self.dropdown)
            return bool(int(self.dropdown.tk.call("winfo", "viewable", popdown)))
        except Exception:
            return False

    def _advance_selection(self, step: int = 1) -> bool:
        """Move selection by the given step; returns True if it changed."""

        count = len(self._choices)
        if not count:
            return False
        try:
            current_index = int(self.dropdown.current())
        except Exception:
            current_index = -1
        if current_index < 0:
            current_index = 0

        target_index = (current_index + step) % count
        try:
            self.dropdown.current(target_index)
            self.dropdown.event_generate("<<ComboboxSelected>>")
            return True
        except Exception:
            return False

    def _build_triangles(self) -> None:
        """Add clickable triangles on either side of the combobox."""

        def _make_button(column: int, direction: str) -> None:
            btn = tk.Canvas(
                self,
                width=28,
                height=28,
                bd=0,
                highlightthickness=0,
                bg=self.cget("background"),
            )
            size = 28
            inset = 6
            if direction == "left":
                points = (inset, size / 2, size - inset, inset, size - inset, size - inset)
            else:
                points = (size - inset, size / 2, inset, inset, inset, size - inset)
            btn.create_polygon(*points, fill="black", outline="black")
            btn.grid(row=0, column=column, padx=4, pady=0)

            def _on_click(_event: object) -> str | None:
                if self._request_focus:
                    try:
                        self._request_focus()
                    except Exception:
                        pass
                try:
                    self.dropdown.focus_set()
                except Exception:
                    pass
                self._advance_selection(-1 if direction == "left" else 1)
                return "break"

            btn.bind("<Button-1>", _on_click)
            if not hasattr(self, "_triangle_buttons"):
                self._triangle_buttons: list[tk.Canvas] = []
            self._triangle_buttons.append(btn)

        _make_button(0, "left")
        _make_button(2, "right")

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def set_selection_change_callback(self, callback: callable | None) -> None:
        """Register a callback invoked when the selection changes."""

        self._on_selection_changed = callback

    def _handle_dropdown_click(self, _event: object) -> None:
        """Ensure the widget enters focus/selection before native dropdown handling."""

        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        try:
            self.dropdown.focus_set()
        except Exception:
            pass

    def _handle_selection_change(self, _event: object | None = None) -> None:
        if self._on_selection_changed:
            try:
                self._on_selection_changed(self.dropdown.get())
            except Exception:
                pass
        self._dropdown_posted = False

    def _post_dropdown(self) -> None:
        """Open the combobox dropdown without synthesizing key events."""

        try:
            self.dropdown.tk.call("ttk::combobox::Post", self.dropdown)
            self._dropdown_posted = True
            try:
                popdown = self.dropdown.tk.call("ttk::combobox::PopdownWindow", self.dropdown)
                listbox = f"{popdown}.f.l"
                exists = bool(int(self.dropdown.tk.call("winfo", "exists", listbox)))
                if exists:
                    current = self.dropdown.current()
                    self.dropdown.tk.call(listbox, "activate", current)
                    self.dropdown.tk.call("focus", listbox)
            except Exception:
                pass
            try:
                self.update_idletasks()
            except Exception:
                pass
        except Exception:
            pass

    def _navigate(self, step: int) -> bool:
        """Advance selection and sync an open dropdown listbox if present."""

        changed = self._advance_selection(step)
        if changed and self._is_dropdown_open():
            try:
                popdown = self.dropdown.tk.call("ttk::combobox::PopdownWindow", self.dropdown)
                listbox = f"{popdown}.f.l"
                exists = bool(int(self.dropdown.tk.call("winfo", "exists", listbox)))
                if exists:
                    current = self.dropdown.current()
                    self.dropdown.tk.call(listbox, "selection", "clear", 0, "end")
                    self.dropdown.tk.call(listbox, "selection", "set", current)
                    self.dropdown.tk.call(listbox, "see", current)
            except Exception:
                pass
        return changed

    def handle_key(self, keysym: str, event: tk.Event[tk.Misc] | None = None) -> str | None:  # type: ignore[name-defined]
        """Process keys while this widget has focus mode active."""

        if _alt_modifier_active(self, event):
            return "break"

        key = keysym.lower()
        if key == "left":
            self._advance_selection(-1)
            return "break"
        elif key == "right":
            self._advance_selection(1)
            return "break"
        elif key == "down":
            if not self._is_dropdown_open():
                if self._dropdown_posted:
                    self._dropdown_posted = False
                    self._navigate(1)
                    return "break"
                else:
                    self._post_dropdown()
                    return "break"
            self._dropdown_posted = False
            self._navigate(1)
            return "break"
        elif key == "up":
            self._navigate(-1)
            return "break"
        elif key in {"return", "space"}:
            try:
                if self._is_dropdown_open():
                    focus_target = self.dropdown.tk.call("focus")
                    if focus_target:
                        self.dropdown.tk.call("event", "generate", focus_target, "<Return>")
                    else:
                        self.dropdown.event_generate("<Return>")
                else:
                    self._post_dropdown()
            except Exception:
                pass
            return "break"
        return None

    def _handle_arrow_key(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        """Capture arrow keys while focused to avoid bubbling to parent bindings."""

        return self.handle_key(event.keysym, event)


class SidebarTipHelper(tk.Frame):
    """Lightweight helper that shows context-aware tips for the sidebar widgets."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._default_primary = "Handy tips will show up here in the future."
        self._primary_var = tk.StringVar(value=self._default_primary)
        self._secondary_var = tk.StringVar(value="")

        primary = tk.Label(
            self,
            textvariable=self._primary_var,
            justify="left",
            anchor="nw",
            wraplength=220,
            padx=6,
            pady=4,
            bg=self.cget("background"),
            fg="#1f1f1f",
        )
        secondary = tk.Label(
            self,
            textvariable=self._secondary_var,
            justify="left",
            anchor="nw",
            wraplength=220,
            padx=6,
            pady=2,
            bg=self.cget("background"),
            fg="#555555",
            font=("TkDefaultFont", 8),
        )

        primary.pack(fill="x")
        secondary.pack(fill="x")

    def set_context(self, primary: str | None = None, secondary: str | None = None) -> None:
        self._primary_var.set(primary or self._default_primary)
        self._secondary_var.set(secondary or "")


class OffsetSelectorWidget(tk.Frame):
    """Simple four-way offset selector with triangular arrow buttons."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self.button_size = 36
        self._arrows: dict[str, tuple[tk.Canvas, int]] = {}
        self._pinned: set[str] = set()
        self._default_color = "black"
        self._active_color = "#ff9900"
        self._disabled_color = "#b0b0b0"
        self._request_focus: callable | None = None
        self._on_change: callable | None = None
        self._enabled = True
        self._flash_handles: dict[str, str | None] = {}
        self._build_grid()

    def _build_grid(self) -> None:
        for i in range(3):
            self.grid_columnconfigure(i, weight=1)
            self.grid_rowconfigure(i, weight=1)

        self._add_arrow("up", row=0, column=1)
        self._add_arrow("left", row=1, column=0)
        self._add_arrow("right", row=1, column=2)
        self._add_arrow("down", row=2, column=1)

        spacer = tk.Frame(self, width=self.button_size, height=self.button_size, bd=0, highlightthickness=0)
        spacer.grid(row=1, column=1, padx=4, pady=4)

    def _add_arrow(self, direction: str, row: int, column: int) -> None:
        canvas = tk.Canvas(
            self,
            width=self.button_size,
            height=self.button_size,
            bd=0,
            highlightthickness=0,
            relief="flat",
            bg=self.cget("background"),
        )
        size = self.button_size
        inset = 7
        if direction == "up":
            points = (size / 2, inset, size - inset, size - inset, inset, size - inset)
        elif direction == "down":
            points = (inset, inset, size - inset, inset, size / 2, size - inset)
        elif direction == "left":
            points = (inset, size / 2, size - inset, inset, size - inset, size - inset)
        else:  # right
            points = (inset, inset, inset, size - inset, size - inset, size / 2)
        polygon_id = canvas.create_polygon(*points, fill=self._default_color, outline=self._default_color)
        canvas.grid(row=row, column=column, padx=4, pady=4)
        canvas.bind("<Button-1>", lambda event, d=direction: self._handle_click(d, event))
        self._arrows[direction] = (canvas, polygon_id)

    def _opposite(self, direction: str) -> str:
        mapping = {"up": "down", "down": "up", "left": "right", "right": "left"}
        return mapping.get(direction, "")

    def _apply_arrow_colors(self) -> None:
        base_color = self._disabled_color if not self._enabled else self._default_color
        active_color = self._disabled_color if not self._enabled else self._active_color
        for direction, (canvas, poly_id) in self._arrows.items():
            color = active_color if direction in self._pinned else base_color
            try:
                canvas.configure(
                    highlightbackground=canvas.cget("bg"),
                    highlightcolor=canvas.cget("bg"),
                    highlightthickness=0,
                )
                canvas.itemconfigure(poly_id, fill=color, outline=color)
            except Exception:
                continue

    def _pin_direction(self, direction: str) -> None:
        """Pin a direction, keeping only one pin per axis."""

        if direction in {"left", "right"}:
            self._pinned.difference_update({"left", "right"})
        else:
            self._pinned.difference_update({"up", "down"})
        self._pinned.add(direction)
        self._apply_arrow_colors()
        self._emit_change(direction, pinned=True)

    def _flash_arrow(self, direction: str, flash_ms: int = 140) -> None:
        entry = self._arrows.get(direction)
        if not entry:
            return
        canvas, poly_id = entry
        self._cancel_flash(direction)

        def _reset() -> None:
            self._flash_handles[direction] = None
            self._apply_arrow_colors()

        try:
            canvas.itemconfigure(poly_id, fill=self._active_color, outline=self._active_color)
            handle = canvas.after(flash_ms, _reset)
            self._flash_handles[direction] = handle
        except Exception:
            self._flash_handles[direction] = None

    def _handle_click(self, direction: str, event: object | None = None) -> None:
        """Handle mouse click on an arrow, ensuring focus is acquired first."""

        if not self._enabled:
            return
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        try:
            self.focus_set()
        except Exception:
            pass

        self.handle_key(direction, event)

        # Clear any stale Alt flag after processing the click so Alt+click still pins.
        if sys.platform.startswith("win"):
            try:
                root = self.winfo_toplevel()
                if root is not None and hasattr(root, "_alt_active"):
                    root._alt_active = False  # type: ignore[attr-defined]
            except Exception:
                pass

    def on_focus_enter(self) -> None:
        if not self._enabled:
            return
        try:
            self.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def _is_alt_pressed(self, event: object | None) -> bool:
        """Best-effort check for an active Alt/Mod1 modifier."""

        return _alt_modifier_active(self, event)

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def handle_key(self, keysym: str, event: object | None = None) -> bool:
        key = keysym.lower()
        if not self._enabled:
            return False
        if key not in {"up", "down", "left", "right"}:
            return False

        alt_pressed = self._is_alt_pressed(event)
        opposite = self._opposite(key)

        if alt_pressed:
            self._pin_direction(key)
        elif opposite in self._pinned:
            # Non-Alt opposite press clears that axis' pin.
            self._pinned.discard(opposite)
            self._apply_arrow_colors()
            self._emit_change(opposite, pinned=False)

        self._flash_arrow(key)
        self._emit_change(key, pinned=False)
        return True

    def set_change_callback(self, callback: callable | None) -> None:
        self._on_change = callback

    def _emit_change(self, direction: str, pinned: bool) -> None:
        if self._on_change is None:
            return
        if not self._enabled:
            return
        try:
            self._on_change(direction, pinned)
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._pinned.clear()
            self._cancel_flash()
        self._apply_arrow_colors()

    def _cancel_flash(self, direction: str | None = None) -> None:
        """Cancel any outstanding flash timers for one or all arrows."""

        targets = [direction] if direction else list(self._flash_handles.keys())
        for dir_key in targets:
            handle = self._flash_handles.get(dir_key)
            if handle is None:
                continue
            canvas_entry = self._arrows.get(dir_key)
            canvas = canvas_entry[0] if canvas_entry else None
            if canvas is None:
                continue
            try:
                canvas.after_cancel(handle)
            except Exception:
                pass
            self._flash_handles[dir_key] = None

    def clear_pins(self, axis: str | None = None) -> bool:
        """Clear pinned highlights for the given axis ('x' or 'y') or both."""

        removed = False
        if axis == "x":
            removed = bool(self._pinned.intersection({"left", "right"}))
            self._pinned.difference_update({"left", "right"})
        elif axis == "y":
            removed = bool(self._pinned.intersection({"up", "down"}))
            self._pinned.difference_update({"up", "down"})
        else:
            removed = bool(self._pinned)
            self._pinned.clear()

        if removed:
            self._apply_arrow_colors()
        return removed


class JustificationWidget(tk.Frame):
    """Three-option justification selector with focus-aware navigation."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: callable | None = None
        self._has_focus = False
        self._active_index = 0
        self._choices = ["Left", "Center", "Right"]
        self._icons: list[tk.Canvas] = []
        self._on_change: callable | None = None
        self._enabled = True
        self._build_icons()

    def _build_icons(self) -> None:
        pad = 4
        for idx, _label in enumerate(self._choices):
            canvas = tk.Canvas(
                self,
                width=36,
                height=26,
                bd=0,
                highlightthickness=0,
                bg=self.cget("background"),
            )
            canvas.grid(row=0, column=idx, padx=(pad if idx else 0, pad), pady=(pad, pad))
            canvas.bind("<Button-1>", lambda _e, i=idx: self._handle_click(i))
            self._icons.append(canvas)
        for i in range(len(self._choices)):
            self.grid_columnconfigure(i, weight=1)
        self._apply_styles()

    def _apply_styles(self) -> None:
        disabled = not self._enabled
        base_bg = self.cget("background")
        active_bg = "#e6e6e6" if disabled else ("#dce6ff" if self._has_focus else base_bg)
        inactive_bg = "#e6e6e6" if disabled else base_bg
        outline_color = "#b5b5b5" if disabled else ("#4a4a4a" if self._has_focus else "#9a9a9a")
        bar_color = "#9a9a9a" if disabled else ("#1c1c1c" if self._has_focus else "#555555")
        for idx, canvas in enumerate(self._icons):
            is_active = idx == self._active_index
            canvas.configure(bg=active_bg if is_active else inactive_bg)
            canvas.delete("all")
            w = int(canvas.cget("width"))
            h = int(canvas.cget("height"))
            if is_active:
                canvas.create_rectangle(1, 1, w - 1, h - 1, outline=outline_color, width=1)

            # Draw three bars plus a baseline with equal vertical spacing.
            margin = 4
            spacing = max(1.0, (h - (margin * 2)) / 3)
            bar_heights = [margin + spacing * i for i in range(3)]
            bar_lengths = [w * 0.7, w * 0.6, w * 0.4]
            top_length = bar_lengths[0]
            for y, length in zip(bar_heights, bar_lengths):
                if idx == 0:  # left
                    x0 = 4
                elif idx == 1:  # center
                    x0 = (w - length) / 2
                else:  # right
                    x0 = w - length - 4
                x1 = x0 + length
                canvas.create_line(x0, y, x1, y, fill=bar_color, width=2, capstyle="round")
            # Draw a final baseline matching the top bar length.
            baseline_y = margin + spacing * 3
            if idx == 0:  # left
                base_x0 = 4
            elif idx == 1:  # center
                base_x0 = (w - top_length) / 2
            else:  # right
                base_x0 = w - top_length - 4
            base_x1 = base_x0 + top_length
            canvas.create_line(base_x0, baseline_y, base_x1, baseline_y, fill=bar_color, width=2, capstyle="round")

    def _handle_click(self, index: int) -> str | None:
        if not self._enabled:
            return "break"
        if not self._has_focus and self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        self._active_index = max(0, min(len(self._choices) - 1, index))
        self._apply_styles()
        self._emit_change()
        return "break"

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def on_focus_enter(self) -> None:
        if not self._enabled:
            return
        self._has_focus = True
        self._apply_styles()
        try:
            self.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        self._has_focus = False
        self._apply_styles()
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def handle_key(self, keysym: str, _event: object | None = None) -> bool:
        if not self._has_focus or not self._enabled:
            return False
        key = keysym.lower()
        if key not in {"left", "right"}:
            return False
        delta = -1 if key == "left" else 1
        new_index = (self._active_index + delta) % len(self._choices)
        if new_index == self._active_index:
            return False
        self._active_index = new_index
        self._apply_styles()
        self._emit_change()
        return True

    def set_justification(self, name: str | None) -> None:
        mapping = {"left": 0, "center": 1, "right": 2}
        idx = mapping.get((name or "left").strip().lower(), 0)
        if idx != self._active_index:
            self._active_index = idx
            self._apply_styles()

    def get_justification(self) -> str:
        return ["left", "center", "right"][self._active_index]

    def set_change_callback(self, callback: callable | None) -> None:
        self._on_change = callback

    def _emit_change(self) -> None:
        if self._on_change is None:
            return
        if not self._enabled:
            return
        try:
            self._on_change(self.get_justification())
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._has_focus = False
        self._apply_styles()


class AnchorSelectorWidget(tk.Frame):
    """3x3 anchor grid with movable highlight."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: callable | None = None
        self._has_focus = False
        self._active_index = 0  # start at NW
        self._on_change: callable | None = None
        self._enabled = True
        self._needs_static = True
        self._layout: dict[str, object] | None = None
        self.canvas = tk.Canvas(
            self,
            width=120,
            height=120,
            bd=0,
            highlightthickness=0,
            bg=self.cget("background"),
        )
        self.canvas.pack(fill="both", expand=True)
        self._draw_handle: str | None = None
        self.canvas.bind("<Configure>", lambda _e: self._schedule_draw())
        self.after_idle(self._schedule_draw)
        self.canvas.bind("<Button-1>", self._handle_click)
        self._positions: list[tuple[float, float]] = []

    def _draw(self) -> None:
        self._draw_handle = None
        w = max(1, int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth()))
        h = max(1, int(self.canvas.winfo_height() or self.canvas.winfo_reqheight()))
        size = min(w, h)
        grid_size = min(size * 0.85, size - 24)
        spacing = max(10.0, grid_size / 2)
        grid_extent = spacing * 2
        offset_x = (w - grid_extent) / 2
        offset_y = (h - grid_extent) / 2
        xs = [offset_x + spacing * i for i in range(3)]
        ys = [offset_y + spacing * i for i in range(3)]
        disabled = not self._enabled
        line_color = "#a0a0a0" if disabled else ("#2b2b2b" if self._has_focus else "#888888")
        dot_color = "#8a8a8a" if disabled else "#000000"
        highlight_color = "#707070" if disabled else "#000000"
        focus_fill = "#dcdcdc" if disabled else "#cfe6ff"
        focus_outline = "#b5b5b5" if disabled else "#5a7cae"
        palette = (disabled, self._has_focus)

        if self._layout is None or self._layout.get("size") != (w, h):
            self._needs_static = True
        if self._layout is None or self._layout.get("palette") != palette:
            self._needs_static = True

        if self._needs_static:
            self.canvas.delete("all")
            positions: list[tuple[float, float]] = []
            for j in range(3):
                for i in range(3):
                    positions.append((xs[i], ys[j]))
            self._positions = positions

            # Outer square (dashed)
            self.canvas.create_line(xs[0], ys[0], xs[2], ys[0], fill=line_color, dash=(2, 3), tags=("static",))
            self.canvas.create_line(xs[2], ys[0], xs[2], ys[2], fill=line_color, dash=(2, 3), tags=("static",))
            self.canvas.create_line(xs[2], ys[2], xs[0], ys[2], fill=line_color, dash=(2, 3), tags=("static",))
            self.canvas.create_line(xs[0], ys[2], xs[0], ys[0], fill=line_color, dash=(2, 3), tags=("static",))

            dot_r = 8
            for idx, (px, py) in enumerate(positions):
                self.canvas.create_oval(
                    px - dot_r,
                    py - dot_r,
                    px + dot_r,
                    py + dot_r,
                    outline=dot_color,
                    fill=dot_color,
                    tags=("static",),
                )
                if idx == 4:
                    self.canvas.create_oval(
                        px - (dot_r + 4),
                        py - (dot_r + 4),
                        px + (dot_r + 4),
                        py + (dot_r + 4),
                        outline=highlight_color,
                        width=2,
                        tags=("static",),
                    )

            self._layout = {
                "size": (w, h),
                "positions": self._positions,
                "highlight_size": spacing,
                "palette": palette,
            }
            self._needs_static = False

        # Anchor dot stays centered; highlight moves relative to center based on anchor.
        center_x, center_y = self._positions[4] if len(self._positions) >= 5 else (w / 2, h / 2)
        highlight_size = spacing
        anchor_tokens = [
            "nw",
            "top",
            "ne",
            "left",
            "center",
            "right",
            "sw",
            "bottom",
            "se",
        ]
        anchor_token = anchor_tokens[self._active_index] if 0 <= self._active_index < len(anchor_tokens) else "nw"

        def _highlight_origin(token: str) -> tuple[float, float]:
            if token in {"nw"}:
                return center_x, center_y
            if token in {"ne"}:
                return center_x - highlight_size, center_y
            if token in {"sw"}:
                return center_x, center_y - highlight_size
            if token in {"se"}:
                return center_x - highlight_size, center_y - highlight_size
            if token in {"top", "n"}:
                return center_x - highlight_size / 2, center_y
            if token in {"bottom", "s"}:
                return center_x - highlight_size / 2, center_y - highlight_size
            if token in {"left", "w"}:
                return center_x, center_y - highlight_size / 2
            if token in {"right", "e"}:
                return center_x - highlight_size, center_y - highlight_size / 2
            # center/default
            return center_x - highlight_size / 2, center_y - highlight_size / 2

        hx0, hy0 = _highlight_origin(anchor_token)
        hx1 = hx0 + highlight_size
        hy1 = hy0 + highlight_size
        self.canvas.delete("highlight")
        # Draw highlight first so dots render above it.
        if self._has_focus:
            self.canvas.create_rectangle(
                hx0, hy0, hx1, hy1, fill=focus_fill, outline=focus_outline, width=1.2, tags=("highlight",)
            )
        else:
            self.canvas.create_rectangle(hx0, hy0, hx1, hy1, outline=line_color, width=1, tags=("highlight",))
        try:
            self.canvas.tag_lower("highlight")
            self.canvas.tag_raise("static")
        except Exception:
            pass

    def _handle_click(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if not self._enabled:
            return "break"
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        if self._positions:
            ex = getattr(event, "x", None)
            ey = getattr(event, "y", None)
            if ex is not None and ey is not None:
                try:
                    idx = self._anchor_index_from_point(ex, ey)
                    if idx != self._active_index:
                        self._active_index = idx
                        self._schedule_draw()
                        self._emit_change()
                except Exception:
                    pass
        return "break"

    def _anchor_index_from_point(self, x: float, y: float) -> int:
        if len(self._positions) < 9:
            return self._active_index
        center_x, center_y = self._positions[4]
        spacing = abs(self._positions[1][0] - self._positions[0][0]) if len(self._positions) > 1 else 0.0
        tol = spacing * 0.2 if spacing > 0 else 5.0
        dx = x - center_x
        dy = y - center_y

        def _token_for(dx: float, dy: float) -> str:
            # Click location is where the box should be relative to the anchor, so we invert.
            if abs(dx) <= tol and abs(dy) <= tol:
                return "center"
            if abs(dx) <= tol:
                return "bottom" if dy < 0 else "top"
            if abs(dy) <= tol:
                return "right" if dx < 0 else "left"
            if dx < 0 and dy < 0:
                return "se"
            if dx > 0 and dy < 0:
                return "sw"
            if dx < 0 and dy > 0:
                return "ne"
            return "nw"

        token = _token_for(dx, dy)
        mapping = {
            "nw": 0,
            "top": 1,
            "ne": 2,
            "left": 3,
            "center": 4,
            "right": 5,
            "sw": 6,
            "bottom": 7,
            "se": 8,
        }
        return mapping.get(token, self._active_index)

    def _schedule_draw(self) -> None:
        if self._draw_handle is not None:
            return
        try:
            handle = self.after_idle(self._draw)
            self._draw_handle = handle
        except Exception:
            self._draw_handle = None

    def set_focus_request_callback(self, callback: callable | None) -> None:
        self._request_focus = callback

    def on_focus_enter(self) -> None:
        if not self._enabled:
            return
        self._has_focus = True
        self._needs_static = True
        self._schedule_draw()
        try:
            self.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        self._has_focus = False
        self._needs_static = True
        self._schedule_draw()
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def handle_key(self, keysym: str, _event: object | None = None) -> str | None:
        if not self._has_focus or not self._enabled:
            return None
        # Ignore modified arrows (e.g., Alt+Arrow) to keep behavior consistent with bindings.
        alt_pressed = _alt_modifier_active(self, _event)
        if alt_pressed:
            return None

        key = keysym.lower()
        deltas = {
            "left": (-1, 0),
            "right": (1, 0),
            "up": (0, -1),
            "down": (0, 1),
        }
        delta = deltas.get(key)
        if delta is None:
            return None

        tokens = [
            "nw",
            "top",
            "ne",
            "left",
            "center",
            "right",
            "sw",
            "bottom",
            "se",
        ]
        token = tokens[self._active_index] if 0 <= self._active_index < len(tokens) else "center"
        coords = {
            "nw": (1, 1),
            "top": (0, 1),
            "ne": (-1, 1),
            "left": (1, 0),
            "center": (0, 0),
            "right": (-1, 0),
            "sw": (1, -1),
            "bottom": (0, -1),
            "se": (-1, -1),
        }
        coord = coords.get(token, (0, 0))
        new_coord = (max(-1, min(1, coord[0] + delta[0])), max(-1, min(1, coord[1] + delta[1])))
        target_token = None
        for tok, c in coords.items():
            if c == new_coord:
                target_token = tok
                break
        if target_token is None:
            return "break"
        mapping = {
            "nw": 0,
            "top": 1,
            "ne": 2,
            "left": 3,
            "center": 4,
            "right": 5,
            "sw": 6,
            "bottom": 7,
            "se": 8,
        }
        idx = mapping.get(target_token, self._active_index)
        if idx == self._active_index:
            return "break"
        self._active_index = idx
        self._schedule_draw()
        self._emit_change()
        return "break"

    def set_anchor(self, name: str | None) -> None:
        mapping = {
            "nw": 0,  # legacy aliases
            "n": 1,
            "top": 1,
            "ne": 2,
            "w": 3,
            "left": 3,
            "center": 4,
            "c": 4,
            "e": 5,
            "right": 5,
            "sw": 6,
            "s": 7,
            "bottom": 7,
            "se": 8,
        }
        idx = mapping.get((name or "nw").strip().lower(), 0)
        if idx != self._active_index:
            self._active_index = idx
            self._draw()

    def get_anchor(self) -> str:
        mapping = {
            0: "nw",
            1: "top",
            2: "ne",
            3: "left",
            4: "center",
            5: "right",
            6: "sw",
            7: "bottom",
            8: "se",
        }
        return mapping.get(self._active_index, "nw")

    def set_change_callback(self, callback: callable | None) -> None:
        self._on_change = callback

    def _emit_change(self) -> None:
        if self._on_change is None:
            return
        if not self._enabled:
            return
        try:
            self._on_change(self.get_anchor())
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._has_focus = False
        self._needs_static = True
        self._schedule_draw()


class AbsoluteXYWidget(tk.Frame):
    """Absolute X/Y input widget with focus-aware navigation."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: callable | None = None
        self._active_field: str = "x"
        self._x_var = tk.StringVar()
        self._y_var = tk.StringVar()
        self._on_change: callable | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=0)
        self.grid_columnconfigure(3, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        x_label = tk.Label(self, text="X:", anchor="e", padx=4, pady=2, bg=self.cget("background"))
        y_label = tk.Label(self, text="Y:", anchor="e", padx=4, pady=2, bg=self.cget("background"))
        x_entry = tk.Entry(self, textvariable=self._x_var, width=8)
        y_entry = tk.Entry(self, textvariable=self._y_var, width=8)

        x_label.grid(row=0, column=1, sticky="e")
        x_entry.grid(row=0, column=2, padx=(2, 24))
        y_label.grid(row=1, column=1, sticky="e")
        y_entry.grid(row=1, column=2, padx=(2, 24))

        self._entries = {"x": x_entry, "y": y_entry}
        self._labels = (x_label, y_label)
        self._enabled = True
        try:
            self._default_fg = str(x_entry.cget("fg"))
        except Exception:
            self._default_fg = "black"
        try:
            self._label_default_fg = str(x_label.cget("fg"))
        except Exception:
            self._label_default_fg = "black"
        self._disabled_fg = "#7a7a7a"

        for field, entry in self._entries.items():
            entry.bind("<Button-1>", lambda _e, f=field: self._handle_entry_click(f), add="+")
            entry.bind("<FocusIn>", lambda _e, f=field: self._handle_entry_focus_event(f), add="+")
            entry.bind("<FocusOut>", lambda _e, f=field: self._emit_change(f), add="+")

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def set_change_callback(self, callback: callable | None) -> None:
        """Register a callback invoked when user edits a field."""

        self._on_change = callback

    def _set_active_field(self, field: str) -> None:
        if field not in ("x", "y"):
            return
        self._active_field = field

    def _handle_entry_focus_event(self, field: str) -> None:
        if not self._enabled:
            return
        if field not in ("x", "y"):
            return
        self._set_active_field(field)
        entry = self._entries.get(field)
        if entry is None:
            return
        try:
            entry.select_range(0, tk.END)
            entry.icursor("end")
        except Exception:
            pass

    def _focus_field(self, field: str) -> None:
        if not self._enabled:
            return
        entry = self._entries.get(field)
        if entry is None:
            return
        self._set_active_field(field)
        try:
            entry.focus_set()
            entry.select_range(0, tk.END)
            entry.icursor("end")
        except Exception:
            pass

    def focus_next_field(self, _event: object | None = None) -> str:
        if not self._enabled:
            return "break"
        current = self._active_field
        self._emit_change(current)
        next_field = "y" if current == "x" else "x"
        self._focus_field(next_field)
        return "break"

    def focus_previous_field(self, _event: object | None = None) -> str:
        if not self._enabled:
            return "break"
        current = self._active_field
        self._emit_change(current)
        prev_field = "x" if current == "y" else "y"
        self._focus_field(prev_field)
        return "break"

    def get_binding_targets(self) -> list[tk.Widget]:  # type: ignore[name-defined]
        return [self._entries["x"], self._entries["y"]]

    def _handle_entry_click(self, field: str) -> str:
        if not self._enabled:
            return "break"
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        self._focus_field(field)
        return "break"

    def _emit_change(self, field: str) -> None:
        if self._on_change is None:
            return
        if not self._enabled:
            return
        try:
            self._on_change(field)
        except Exception:
            pass

    def on_focus_enter(self) -> None:
        if not self._enabled:
            return
        self._focus_field(self._active_field)
        entry = self._entries.get(self._active_field)
        if entry is not None:
            try:
                entry.select_range(0, "end")
            except Exception:
                pass

    def on_focus_exit(self) -> None:
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def focus_set(self) -> None:  # type: ignore[override]
        """Forward focus to the active entry so typing works immediately."""

        if not self._enabled:
            return
        self._focus_field(self._active_field)

    def _parse_value(self, raw: str, axis: str) -> float:
        """Parse px or % into pixel values on a 1280x960 base."""

        token = (raw or "").strip()
        if not token:
            raise ValueError(f"{axis} value is empty")

        base = ABS_BASE_WIDTH if axis.upper() == "X" else ABS_BASE_HEIGHT
        token_lower = token.lower()
        if token_lower.endswith("px"):
            token = token[:-2].strip()
        mode = "%"
        if token.endswith("%"):
            token = token[:-1].strip()
        else:
            mode = "px"
        try:
            numeric = float(token)
        except ValueError:
            raise ValueError(
                f"{axis} must be a percent (e.g. 50%) or pixel value (e.g. 640 or 640px) relative to a 1280x960 window."
            ) from None
        if mode == "%":
            numeric = (numeric / 100.0) * base
        return numeric

    def get_values(self) -> tuple[str, str]:
        return self._x_var.get(), self._y_var.get()

    def parse_values(self) -> tuple[float | None, float | None]:
        """Return parsed pixel values or None if empty."""

        results: list[float | None] = []
        for raw, axis in ((self._x_var.get(), "X"), (self._y_var.get(), "Y")):
            token = (raw or "").strip()
            if not token:
                results.append(None)
                continue
            try:
                results.append(self._parse_value(token, axis))
            except ValueError:
                results.append(None)
        return results[0], results[1]

    def set_px_values(self, x: float | None, y: float | None) -> None:
        def _fmt(val: float | None) -> str:
            if val is None:
                return ""
            if abs(val - round(val)) < 0.01:
                return str(int(round(val)))
            return f"{val:.2f}".rstrip("0").rstrip(".")

        def _update_entry(entry: tk.Entry, value: str) -> None:
            current_state = entry.cget("state")
            if current_state == "disabled":
                entry.configure(state="normal")
                entry.delete(0, tk.END)
                entry.insert(0, value)
                entry.configure(state="disabled")
            else:
                entry.delete(0, tk.END)
                entry.insert(0, value)

        _update_entry(self._entries["x"], _fmt(x))
        _update_entry(self._entries["y"], _fmt(y))

    def get_px_values(self) -> tuple[float | None, float | None]:
        return self.parse_values()

    def handle_key(self, keysym: str, event: object | None = None) -> bool:
        key = keysym.lower()
        if not self._enabled:
            return False
        if key in {"tab", "return", "kp_enter", "down"}:
            self.focus_next_field()
            return True
        if key in {"iso_left_tab", "shift-tab", "up"}:
            self.focus_previous_field()
            return True
        return False

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        label_fg = self._label_default_fg if enabled else self._disabled_fg
        for label in self._labels:
            try:
                label.configure(fg=label_fg)
            except Exception:
                pass
        for entry in self._entries.values():
            try:
                entry.configure(
                    state=state,
                    fg=self._default_fg if enabled else self._disabled_fg,
                    disabledforeground=self._disabled_fg,
                )
            except Exception:
                pass

    def set_text_color(self, color: str | None) -> None:
        fg = color or self._default_fg
        for entry in self._entries.values():
            entry.configure(fg=fg)

class OverlayConfigApp(tk.Tk):
    """Basic UI skeleton that mirrors the design mockups."""

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
        self._groupings_shipped_path = root / "overlay_groupings.json"
        self._groupings_user_path = Path(
            os.environ.get("MODERN_OVERLAY_USER_GROUPINGS_PATH", root / "overlay_groupings.user.json")
        )
        self._groupings_loader = GroupingsLoader(self._groupings_shipped_path, self._groupings_user_path)
        _controller_debug(
            "Groupings loader configured: shipped=%s user=%s",
            self._groupings_shipped_path,
            self._groupings_user_path,
        )
        self._groupings_path = self._groupings_user_path
        self._groupings_cache_path = root / "overlay_group_cache.json"
        self._groupings_cache: dict[str, object] = {}
        self._group_state = GroupStateService(
            root=root,
            shipped_path=self._groupings_shipped_path,
            user_groupings_path=self._groupings_user_path,
            cache_path=self._groupings_cache_path,
            loader=self._groupings_loader,
        )
        self._force_render_override = _ForceRenderOverrideManager(root)
        self._absolute_user_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._group_snapshots: dict[tuple[str, str], _GroupSnapshot] = {}
        self._anchor_restore_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._anchor_restore_handles: dict[tuple[str, str], str | None] = {}
        self._absolute_tolerance_px = 0.5
        self._last_preview_signature: tuple[object, ...] | None = None
        self._mode_profile = ControllerModeProfile(
            active=ModeProfile(
                write_debounce_ms=75,
                offset_write_debounce_ms=75,
                status_poll_ms=50,
                cache_flush_seconds=1.0,
            ),
            inactive=ModeProfile(
                write_debounce_ms=200,
                offset_write_debounce_ms=200,
                status_poll_ms=2500,
                cache_flush_seconds=5.0,
            ),
            logger=_controller_debug,
        )
        self._current_mode_profile = self._mode_profile.resolve("active")
        self._status_poll_handle: str | None = None
        self._debounce_handles: dict[str, str | None] = {}
        self._write_debounce_ms = self._current_mode_profile.write_debounce_ms
        self._offset_write_debounce_ms = self._current_mode_profile.offset_write_debounce_ms
        self._status_poll_interval_ms = self._current_mode_profile.status_poll_ms
        self._offset_step_px = 10.0
        self._offset_live_edit_until: float = 0.0
        self._offset_resync_handle: str | None = None
        self._last_edit_ts: float = 0.0
        self._edit_nonce: str = ""
        self._user_overrides_nonce: str = ""
        self._initial_geometry_applied = False
        self._port_path = root / "port.json"
        self._controller_heartbeat_ms = 15000
        self._controller_heartbeat_handle: str | None = None
        self._last_override_reload_nonce: Optional[str] = None
        self._last_override_reload_ts: float = 0.0
        self._last_active_group_sent: Optional[tuple[str, str, str]] = None

        self._groupings_cache = self._load_groupings_cache()
        self._build_layout()
        self._handle_idprefix_selected()
        self._binding_config = BindingConfig.load()
        if sys.platform.startswith("win"):
            self.bind_all("<KeyPress-Alt_L>", self._handle_alt_press, add="+")
            self.bind_all("<KeyPress-Alt_R>", self._handle_alt_press, add="+")
            self.bind_all("<KeyRelease-Alt_L>", self._handle_alt_release, add="+")
            self.bind_all("<KeyRelease-Alt_R>", self._handle_alt_release, add="+")
        self._binding_manager = BindingManager(self, self._binding_config)
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
        self._register_widget_specific_bindings()
        self._binding_manager.activate()
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

    def report_callback_exception(self, exc, val, tb) -> None:  # type: ignore[override]
        """Ensure Tk errors are printed to stderr instead of being swallowed."""

        traceback.print_exception(exc, val, tb, file=sys.stderr)

    def _build_layout(self) -> None:
        """Create the split view with placement and sidebar sections."""

        self.container = tk.Frame(self)
        self.container.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(self.container_pad_left, self.container_pad_right_open),
            pady=(self.container_pad_vertical, self.container_pad_vertical),
        )

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=0, minsize=self.sidebar_width)
        self.container.grid_columnconfigure(1, weight=1)

        # Placement window placeholder (open state)
        self.placement_frame = tk.Frame(
            self.container,
            bd=0,
            relief="flat",
            background="#f5f5f5",
        )
        self.preview_canvas = tk.Canvas(
            self.placement_frame,
            bd=0,
            highlightthickness=1,
            relief="solid",
            background="#202020",
        )
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Button-1>", self._handle_placement_click, add="+")
        self.placement_frame.bind("<Button-1>", self._handle_placement_click, add="+")
        self.preview_canvas.bind("<Configure>", lambda _e: self._draw_preview())

        # Sidebar with individual selector sections
        self.sidebar = tk.Frame(
            self.container,
            width=self.sidebar_width,
            bd=0,
            highlightthickness=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="ns", padx=(0, self.sidebar_pad))
        self._build_sidebar_sections()
        self.sidebar.grid_propagate(True)

        indicator_bg = self.container.cget("background")
        self.indicator_wrapper = tk.Frame(
            self.container,
            width=self.indicator_hit_width,
            height=self.indicator_height,
            bd=0,
            highlightthickness=0,
            bg=indicator_bg,
        )
        self.indicator_wrapper.pack_propagate(False)
        self.indicator_canvas = tk.Canvas(
            self.indicator_wrapper,
            width=self.indicator_hit_width,
            height=self.indicator_height,
            highlightthickness=0,
            bg=indicator_bg,
        )
        self.indicator_canvas.pack(fill="both", expand=True)

        self.sidebar_overlay = SelectionOverlay(
            parent=self.sidebar,
            padding=self.overlay_padding,
            border_width=self.overlay_border_width,
        )
        self.placement_overlay = SelectionOverlay(
            parent=self.container,
            padding=self.placement_overlay_padding,
            border_width=self.overlay_border_width,
            corner_radius=0,
        )
        self._apply_placement_state()
        self._refresh_widget_focus()

    def _build_sidebar_sections(self) -> None:
        """Create labeled boxes that will hold future controls."""

        sections = [
            ("idprefix group selector", 0, True),
            ("offset selector", 0, True),
            ("absolute x/y", 0, True),
            ("anchor selector", 0, True),
            ("payload justification", 0, True),
            ("Handy tips will show up here in the future", 1, False),
        ]

        self.sidebar_cells: list[tk.Frame] = []
        self._sidebar_focus_index = 0
        self.widget_select_mode = True
        selectable_index = 0

        for index, (label_text, weight, is_selectable) in enumerate(sections):
            default_height = 120 if label_text == "anchor selector" else 80
            frame = tk.Frame(
                self.sidebar,
                bd=0,
                relief="flat",
                width=0 if index == 0 else 220,
                height=0 if index == 0 else default_height,
            )
            frame.grid(
                row=index,
                column=0,
                sticky="nsew",
                pady=(
                    self.overlay_padding if index == 0 else 1,
                    self.overlay_padding if index == len(sections) - 1 else 1,
                ),
                padx=(self.overlay_padding, self.overlay_padding),
            )
            frame.grid_propagate(True)

            focus_index = selectable_index if is_selectable else None
            if is_selectable:
                selectable_index += 1

            if index == 0:
                self.idprefix_widget = IdPrefixGroupWidget(frame, options=self._load_idprefix_options())
                if is_selectable and focus_index is not None:
                    self.idprefix_widget.set_focus_request_callback(
                        lambda idx=focus_index: self._handle_sidebar_click(idx)
                    )
                self.idprefix_widget.set_selection_change_callback(lambda _sel=None: self._handle_idprefix_selected())
                self.idprefix_widget.pack(fill="both", expand=True, padx=0, pady=0)
                if is_selectable and focus_index is not None:
                    self._focus_widgets[("sidebar", focus_index)] = self.idprefix_widget
            elif index == 1:
                self.offset_widget = OffsetSelectorWidget(frame)
                if is_selectable and focus_index is not None:
                    self.offset_widget.set_focus_request_callback(
                        lambda idx=focus_index: self._handle_sidebar_click(idx)
                    )
                self.offset_widget.set_change_callback(self._handle_offset_changed)
                self.offset_widget.pack(expand=True)
                if is_selectable and focus_index is not None:
                    self._focus_widgets[("sidebar", focus_index)] = self.offset_widget
            elif index == 2:
                self.absolute_widget = AbsoluteXYWidget(frame)
                if is_selectable and focus_index is not None:
                    self.absolute_widget.set_focus_request_callback(
                        lambda idx=focus_index: self._handle_sidebar_click(idx)
                    )
                self.absolute_widget.set_change_callback(self._handle_absolute_changed)
                self.absolute_widget.pack(fill="both", expand=True, padx=0, pady=0)
                if is_selectable and focus_index is not None:
                    self._focus_widgets[("sidebar", focus_index)] = self.absolute_widget
            elif index == 3:
                frame.configure(height=140)
                frame.grid_propagate(False)
                self.anchor_widget = AnchorSelectorWidget(frame)
                if is_selectable and focus_index is not None:
                    self.anchor_widget.set_focus_request_callback(
                        lambda idx=focus_index: self._handle_sidebar_click(idx)
                    )
                self.anchor_widget.set_change_callback(self._handle_anchor_changed)
                self.anchor_widget.pack(fill="both", expand=True, padx=4, pady=4)
                if is_selectable and focus_index is not None:
                    self._focus_widgets[("sidebar", focus_index)] = self.anchor_widget
            elif index == 4:
                self.justification_widget = JustificationWidget(frame)
                if is_selectable and focus_index is not None:
                    self.justification_widget.set_focus_request_callback(
                        lambda idx=focus_index: self._handle_sidebar_click(idx)
                    )
                self.justification_widget.set_change_callback(self._handle_justification_changed)
                self.justification_widget.pack(fill="both", expand=True, padx=4, pady=4)
                if is_selectable and focus_index is not None:
                    self._focus_widgets[("sidebar", focus_index)] = self.justification_widget
            else:
                self.tip_helper = SidebarTipHelper(frame)
                self.tip_helper.pack(fill="both", expand=True, padx=2, pady=2)

            if is_selectable and focus_index is not None:
                frame.bind(
                    "<Button-1>", lambda event, idx=focus_index: self._handle_sidebar_click(idx), add="+"
                )
                for child in frame.winfo_children():
                    child.bind("<Button-1>", lambda event, idx=focus_index: self._handle_sidebar_click(idx), add="+")

            grow_weight = 1 if index == len(sections) - 1 else 0
            row_opts = {"weight": grow_weight}
            if index == 3:
                row_opts["minsize"] = 220
            self.sidebar.grid_rowconfigure(index, **row_opts)
            if is_selectable and focus_index is not None:
                self.sidebar_cells.append(frame)
            else:
                self.sidebar_context_frame = frame

        self.sidebar.grid_columnconfigure(0, weight=1)

    def _activate_force_render_override(self) -> None:
        manager = getattr(self, "_force_render_override", None)
        if manager is None:
            return
        try:
            manager.activate()
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def _deactivate_force_render_override(self) -> None:
        manager = getattr(self, "_force_render_override", None)
        if manager is None:
            return
        try:
            manager.deactivate()
        except Exception:
            traceback.print_exc(file=sys.stderr)

    def _send_plugin_cli(self, payload: Dict[str, Any]) -> None:
        port_path = getattr(self, "_port_path", Path(__file__).resolve().parents[1] / "port.json")
        try:
            data = json.loads(port_path.read_text(encoding="utf-8"))
            port = int(data.get("port", 0))
        except Exception:
            return
        if port <= 0:
            return
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as sock:
                writer = sock.makefile("w", encoding="utf-8", newline="\n")
                writer.write(json.dumps(payload, ensure_ascii=False))
                writer.write("\n")
                writer.flush()
        except Exception:
            return

    def _send_controller_heartbeat(self) -> None:
        self._send_plugin_cli({"cli": "controller_heartbeat"})
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

    def toggle_placement_window(self) -> None:
        """Switch between the open and closed placement window layouts."""

        self._placement_open = not self._placement_open
        if not self._placement_open and self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
        self._apply_placement_state()
        self._refresh_widget_focus()

    def focus_sidebar_up(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move sidebar focus upward."""

        if not self.widget_select_mode:
            if self._handle_active_widget_key("Up", event):
                return "break"
            return
        if not getattr(self, "sidebar_cells", None):
            return
        new_index = max(0, self._sidebar_focus_index - 1)
        self._set_sidebar_focus(new_index)
        self._refresh_widget_focus()

    def focus_sidebar_down(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move sidebar focus downward."""

        if not self.widget_select_mode:
            if self._handle_active_widget_key("Down", event):
                return "break"
            return
        if not getattr(self, "sidebar_cells", None):
            return
        new_index = min(len(self.sidebar_cells) - 1, self._sidebar_focus_index + 1)
        self._set_sidebar_focus(new_index)
        self._refresh_widget_focus()

    def _set_sidebar_focus(self, index: int) -> None:
        if not (0 <= index < len(self.sidebar_cells)):
            return
        self._sidebar_focus_index = index
        self._update_sidebar_highlight()

    def _handle_sidebar_click(self, index: int, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to a sidebar cell and enter focus mode."""

        if not getattr(self, "sidebar_cells", None):
            return
        if not (0 <= index < len(self.sidebar_cells)):
            return
        block_focus = (not getattr(self, "_group_controls_enabled", True)) and index > 0
        if block_focus:
            if not self.widget_select_mode:
                self.exit_focus_mode()
            self.widget_focus_area = "sidebar"
            self._set_sidebar_focus(index)
            self._refresh_widget_focus()
            try:
                self.focus_set()
            except Exception:
                pass
            return
        if not self.widget_select_mode and index != getattr(self, "_sidebar_focus_index", -1):
            self._on_focus_mode_exited()
        self.widget_focus_area = "sidebar"
        self._set_sidebar_focus(index)
        self.widget_select_mode = False
        self._on_focus_mode_entered()
        self._refresh_widget_focus()
        if self.widget_select_mode:
            try:
                self.focus_set()
            except Exception:
                pass
        else:
            target = self._get_active_focus_widget()
            focus_target = getattr(target, "focus_set", None)
            if callable(focus_target):
                try:
                    focus_target()
                except Exception:
                    pass

    def _handle_placement_click(self, _event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Move selection to the placement area and enter focus mode."""

        if not self._placement_open:
            return
        if not self.widget_select_mode and self.widget_focus_area == "sidebar":
            self._on_focus_mode_exited()
        self.widget_focus_area = "placement"
        self.widget_select_mode = False
        self._refresh_widget_focus()
        if self.widget_select_mode:
            try:
                self.focus_set()
            except Exception:
                pass

    def move_widget_focus_left(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Handle left arrow behavior in widget select mode."""

        if not self.widget_select_mode:
            if self._handle_active_widget_key("Left", event):
                return "break"
            return
        if self._placement_open:
            self._placement_open = False
            self._apply_placement_state()
            self.widget_focus_area = "sidebar"
            self._refresh_widget_focus()

    def move_widget_focus_right(self, event: tk.Event[tk.Misc] | None = None) -> None:  # type: ignore[name-defined]
        """Handle right arrow behavior in widget select mode."""

        if not self.widget_select_mode:
            if self._handle_active_widget_key("Right", event):
                return "break"
            return
        if not self._placement_open:
            self._placement_open = True
            self._apply_placement_state()
        self.widget_focus_area = "sidebar"
        self._refresh_widget_focus()

    def _update_sidebar_highlight(self) -> None:
        if not self.sidebar_cells:
            self.sidebar_overlay.hide()
            return
        if self.widget_focus_area != "sidebar":
            self.sidebar_overlay.hide()
            return

        frame = self.sidebar_cells[self._sidebar_focus_index]
        color = "#888888" if self.widget_select_mode else "#000000"
        self.sidebar_overlay.show(frame, color)

    def _update_placement_focus_highlight(self) -> None:
        is_active = self.widget_focus_area == "placement" and self._placement_open
        if not is_active:
            self.placement_overlay.hide()
            return

        color = "#888888" if self.widget_select_mode else "#000000"
        self.placement_overlay.show(self.placement_frame, color)

    def _update_contextual_tip(self) -> None:
        helper = getattr(self, "tip_helper", None)
        if helper is None:
            return
        primary: str | None = None
        secondary: str | None = None
        controls_enabled = getattr(self, "_group_controls_enabled", True)
        in_sidebar = self.widget_focus_area == "sidebar" and bool(getattr(self, "sidebar_cells", None))

        if not in_sidebar:
            primary = "Use arrow keys to move between controls."
            secondary = "Press Enter to focus a control; Esc exits focus mode."
            helper.set_context(primary, secondary)
            return

        idx = max(0, min(getattr(self, "_sidebar_focus_index", 0), len(self.sidebar_cells) - 1))
        if not controls_enabled and idx > 0:
            primary = "Waiting for overlay cache to populate this group."
            secondary = "Controls unlock once the latest payload arrives."
            helper.set_context(primary, secondary)
            return

        select_mode = self.widget_select_mode
        if select_mode:
            focus_hint = "Press Space to edit; arrows move the selection."
        else:
            focus_hint = "Press Space to exit."

        if idx == 0:
            primary = "Pick an ID prefix group to adjust."
            secondary = "Select the overlay group you want to adjust."
            if select_mode:
                secondary = "Select the overlay group you want to adjust; arrows move the selection."
                focus_hint = "Press Space to edit."
        elif idx == 1:
            primary = "Use Alt-click / Alt-arrow to move the overlay group to the screen edge."
        elif idx == 2:
            primary = "Set exact coordinates for this group."
            secondary = "Enter px or % values; Tab switches fields."
        elif idx == 3:
            primary = "Choose the anchor point used for transforms."
            secondary = "Use arrows or click dots to move the highlight."
        elif idx == 4:
            primary = "Set payload justification."
            secondary = "Left/Center/Right controls text alignment."

        if focus_hint:
            secondary = f"{secondary} {focus_hint}" if secondary else focus_hint

        helper.set_context(primary, secondary)

    def _refresh_widget_focus(self) -> None:
        if hasattr(self, "sidebar_cells"):
            self._update_sidebar_highlight()
        self._update_placement_focus_highlight()
        try:
            self.indicator_wrapper.lift()
        except Exception:
            pass
        self._update_contextual_tip()

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
        if lower_keysym in {"escape", "space"}:
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
        state = self.__dict__.get("_group_state")
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
        widget_names = ("offset_widget", "absolute_widget", "anchor_widget", "justification_widget")
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

    def _compute_absolute_from_snapshot(self, snapshot: _GroupSnapshot) -> tuple[float, float]:
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

    def _build_group_snapshot(self, plugin_name: str, label: str) -> _GroupSnapshot | None:
        state = self.__dict__.get("_group_state")
        if state is not None:
            try:
                snapshot = state.snapshot(plugin_name, label)
            except Exception:
                snapshot = None
            if snapshot is None:
                return None
            return _GroupSnapshot(
                plugin=snapshot.plugin,
                label=snapshot.label,
                anchor_token=snapshot.anchor_token,
                transform_anchor_token=snapshot.transform_anchor_token,
                offset_x=snapshot.offset_x,
                offset_y=snapshot.offset_y,
                base_bounds=snapshot.base_bounds,
                base_anchor=snapshot.base_anchor,
                transform_bounds=snapshot.transform_bounds,
                transform_anchor=snapshot.transform_anchor,
                has_transform=snapshot.has_transform,
                cache_timestamp=snapshot.cache_timestamp,
            )
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
        def _transformed_matches_offsets(payload: dict[str, object]) -> bool:
            tol = 0.5
            try:
                tx = float(payload.get("offset_dx", 0.0))
                ty = float(payload.get("offset_dy", 0.0))
            except Exception:
                return False
            return abs(tx - offset_x) <= tol and abs(ty - offset_y) <= tol

        # edit_ts retained for potential future gating/debug.
        use_transformed = False  # POC: ignore cached transforms to avoid snap-backs
        if use_transformed and transformed_payload:
            trans_min_x = float(transformed_payload.get("trans_min_x", base_min_x))
            trans_min_y = float(transformed_payload.get("trans_min_y", base_min_y))
            trans_max_x = float(transformed_payload.get("trans_max_x", base_max_x))
            trans_max_y = float(transformed_payload.get("trans_max_y", base_max_y))
            has_transform = True
        else:
            # Synthesize transform from base + offsets so preview "Actual" tracks target.
            trans_min_x = base_min_x + offset_x
            trans_min_y = base_min_y + offset_y
            trans_max_x = base_max_x + offset_x
            trans_max_y = base_max_y + offset_y
            has_transform = True
        transform_bounds = (trans_min_x, trans_min_y, trans_max_x, trans_max_y)
        transform_anchor = self._compute_anchor_point(
            trans_min_x, trans_max_x, trans_min_y, trans_max_y, transform_anchor_token
        )
        return _GroupSnapshot(
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
            has_transform=has_transform,
            cache_timestamp=cache_ts,
        )

    def _scale_mode_setting(self) -> str:
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
        min_x, min_y, max_x, max_y = bounds
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0
        token = (anchor or "nw").strip().lower()
        if token in {"c", "center"}:
            return mid_x, mid_y
        if token in {"n", "top"}:
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
        return min_x, min_y

    @staticmethod
    def _translate_snapshot_for_fill(
        snapshot: _GroupSnapshot,
        viewport_width: float,
        viewport_height: float,
        *,
        scale_mode_value: Optional[str] = None,
        anchor_token_override: Optional[str] = None,
    ) -> _GroupSnapshot:
        if snapshot is None or snapshot.has_transform:
            return snapshot
        scale_mode = (scale_mode_value or "fill").strip().lower()
        mapper = compute_legacy_mapper(scale_mode, float(max(viewport_width, 1.0)), float(max(viewport_height, 1.0)))
        transform = mapper.transform
        if transform.mode is not ScaleMode.FILL or not (transform.overflow_x or transform.overflow_y):
            return snapshot
        base_bounds = snapshot.base_bounds
        anchor_token = anchor_token_override or snapshot.transform_anchor_token or snapshot.anchor_token or "nw"
        anchor_point = OverlayConfigApp._anchor_point_from_bounds(base_bounds, anchor_token)
        base_width = VC_BASE_WIDTH if VC_BASE_WIDTH > 0.0 else 1.0
        base_height = VC_BASE_HEIGHT if VC_BASE_HEIGHT > 0.0 else 1.0
        clamp = OverlayConfigApp._clamp_unit
        group_transform = GroupTransform(
            dx=0.0,
            dy=0.0,
            band_min_x=clamp(base_bounds[0] / base_width),
            band_max_x=clamp(base_bounds[2] / base_width),
            band_min_y=clamp(base_bounds[1] / base_height),
            band_max_y=clamp(base_bounds[3] / base_height),
            band_anchor_x=clamp(anchor_point[0] / base_width),
            band_anchor_y=clamp(anchor_point[1] / base_height),
            bounds_min_x=base_bounds[0],
            bounds_min_y=base_bounds[1],
            bounds_max_x=base_bounds[2],
            bounds_max_y=base_bounds[3],
            anchor_token=anchor_token,
            payload_justification="left",
        )
        viewport_state = ViewportState(width=float(max(viewport_width, 1.0)), height=float(max(viewport_height, 1.0)))
        fill = build_viewport(mapper, viewport_state, group_transform, VC_BASE_WIDTH, VC_BASE_HEIGHT)
        dx, dy = compute_proportional_translation(fill, group_transform, anchor_point)
        if not (dx or dy):
            return snapshot
        trans_bounds = (
            base_bounds[0] + dx,
            base_bounds[1] + dy,
            base_bounds[2] + dx,
            base_bounds[3] + dy,
        )
        trans_anchor = (anchor_point[0] + dx, anchor_point[1] + dy)
        return _GroupSnapshot(
            plugin=snapshot.plugin,
            label=snapshot.label,
            anchor_token=snapshot.anchor_token,
            transform_anchor_token=anchor_token,
            offset_x=snapshot.offset_x,
            offset_y=snapshot.offset_y,
            base_bounds=snapshot.base_bounds,
            base_anchor=snapshot.base_anchor,
            transform_bounds=trans_bounds,
            transform_anchor=trans_anchor,
            has_transform=True,
            cache_timestamp=snapshot.cache_timestamp,
        )

    def _update_absolute_widget_color(self, snapshot: _GroupSnapshot | None) -> None:
        widget = getattr(self, "absolute_widget", None)
        if widget is None:
            return
        # Absolute preview now mirrors controller target; keep default text color.
        try:
            widget.set_text_color(None)
        except Exception:
            pass
        self._update_contextual_tip()

    def _apply_snapshot_to_absolute_widget(
        self, selection: tuple[str, str], snapshot: _GroupSnapshot, force_ui: bool = True
    ) -> None:
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
        selection = self._get_current_group_selection()
        if selection is None:
            self._set_group_controls_enabled(False)
            self._update_absolute_widget_color(None)
            self._draw_preview()
            return
        plugin_name, label = selection

        # While the user is actively holding offset arrows, prefer the in-memory snapshot
        # so the preview target does not snap back when the cache polls.
        now = time.time()
        if now < getattr(self, "_offset_live_edit_until", 0.0):
            snapshot = self._group_snapshots.get(selection)
            if snapshot is not None:
                self._set_group_controls_enabled(True)
                self._apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=force_ui)
                self._update_absolute_widget_color(snapshot)
                self._draw_preview()
                return

        snapshot = self._build_group_snapshot(plugin_name, label)
        if snapshot is None:
            self._group_snapshots.pop(selection, None)
            self._set_group_controls_enabled(False)
            self._update_absolute_widget_color(None)
            self._draw_preview()
            return
        self._group_snapshots[selection] = snapshot
        self._set_group_controls_enabled(True)
        self._apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=force_ui)
        self._update_absolute_widget_color(snapshot)
        self._draw_preview()

    def _get_group_snapshot(self, selection: tuple[str, str] | None = None) -> _GroupSnapshot | None:
        key = selection if selection is not None else self._get_current_group_selection()
        if key is None:
            return None
        return self._group_snapshots.get(key)

    def _poll_cache_and_status(self) -> None:
        self._status_poll_handle = None
        reload_groupings = False
        loader = getattr(self, "_groupings_loader", None)
        state = self.__dict__.get("_group_state")
        if state is not None:
            try:
                reload_groupings = bool(
                    state.reload_groupings_if_changed(last_edit_ts=getattr(self, "_last_edit_ts", 0.0), delay_seconds=5.0)
                )
            except Exception:
                reload_groupings = False
        elif loader is not None:
            try:
                # Delay reloads immediately after an edit to avoid reading half-written user file.
                if time.time() - getattr(self, "_last_edit_ts", 0.0) > 5.0:
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
        state = self.__dict__.get("_group_state")
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

        state = self.__dict__.get("_group_state")
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

    def _write_groupings_config(self) -> None:
        state = self.__dict__.get("_group_state")
        if state is None:
            # Fallback to legacy in-controller write path when service is unavailable (legacy tests/harness).
            user_path = getattr(self, "_groupings_user_path", None) or getattr(self, "_groupings_path", None)
            if user_path is None:
                return

            shipped_path = getattr(self, "_groupings_shipped_path", None)
            if shipped_path is None:
                root = Path(__file__).resolve().parents[1]
                shipped_path = root / "overlay_groupings.json"
                self._groupings_shipped_path = shipped_path

            try:
                shipped_raw = json.loads(shipped_path.read_text(encoding="utf-8"))
            except Exception:
                shipped_raw = {}

            merged_view = getattr(self, "_groupings_data", None)
            if not isinstance(merged_view, dict):
                merged_view = {}
            else:
                merged_view = OverlayConfigApp._round_offsets(merged_view)

            try:
                diff = diff_groupings(shipped_raw, merged_view)
            except Exception:
                return

            if is_empty_diff(diff):
                if user_path.exists():
                    try:
                        user_path.write_text("{}\n", encoding="utf-8")
                        _controller_debug("Cleared user groupings file; no overrides to persist.")
                    except Exception:
                        pass
                else:
                    _controller_debug("Skip writing user groupings: no diff to persist.")
                return

            try:
                payload = dict(diff) if isinstance(diff, dict) else {}
                payload["_edit_nonce"] = getattr(self, "_user_overrides_nonce", "")
                text = json.dumps(payload, indent=2) + "\n"
                tmp_path = user_path.with_suffix(user_path.suffix + ".tmp")
                tmp_path.write_text(text, encoding="utf-8")
                tmp_path.replace(user_path)
                merged_payload = dict(merged_view)
                merged_payload["_edit_nonce"] = getattr(self, "_user_overrides_nonce", "")
                self._send_plugin_cli(
                    {"cli": "controller_overrides_payload", "overrides": merged_payload, "nonce": merged_payload["_edit_nonce"]}
                )
            except Exception:
                return
        try:
            state._write_groupings_config(edit_nonce=getattr(self, "_user_overrides_nonce", ""))
            merged_payload = getattr(state, "_groupings_data", {})
            if isinstance(merged_payload, dict):
                merged_payload = dict(merged_payload)
                merged_payload["_edit_nonce"] = getattr(self, "_user_overrides_nonce", "")
                self._send_plugin_cli(
                    {"cli": "controller_overrides_payload", "overrides": merged_payload, "nonce": merged_payload["_edit_nonce"]}
                )
        except Exception:
            return

    @staticmethod
    def _round_offsets(payload: dict[str, object]) -> dict[str, object]:
        """Return a copy with offsetX/offsetY rounded to 3 decimals to avoid float noise."""

        result: dict[str, object] = {}
        for plugin_name, plugin_entry in payload.items():
            if not isinstance(plugin_entry, dict):
                result[plugin_name] = plugin_entry
                continue
            plugin_copy: dict[str, object] = dict(plugin_entry)
            groups = plugin_entry.get("idPrefixGroups")
            if isinstance(groups, dict):
                groups_copy: dict[str, object] = {}
                for label, group_entry in groups.items():
                    if not isinstance(group_entry, dict):
                        groups_copy[label] = group_entry
                        continue
                    group_copy: dict[str, object] = dict(group_entry)
                    if "offsetX" in group_copy and isinstance(group_copy["offsetX"], (int, float)):
                        group_copy["offsetX"] = round(float(group_copy["offsetX"]), 3)
                    if "offsetY" in group_copy and isinstance(group_copy["offsetY"], (int, float)):
                        group_copy["offsetY"] = round(float(group_copy["offsetY"]), 3)
                    groups_copy[label] = group_copy
                plugin_copy["idPrefixGroups"] = groups_copy
            result[plugin_name] = plugin_copy
        return result

    def _write_groupings_cache(self) -> None:
        # Controller is read-only for overlay_group_cache.json; no-op to avoid clobbering client data.
        return

    def _flush_groupings_config(self) -> None:
        self._debounce_handles["config_write"] = None
        self._last_edit_ts = time.time()
        self._user_overrides_nonce = self._edit_nonce
        self._write_groupings_config()
        self._emit_override_reload_signal()

    def _flush_groupings_cache(self) -> None:
        self._debounce_handles["cache_write"] = None
        # Read-only cache; skip writes.

    def _schedule_debounce(self, key: str, callback: callable, delay_ms: int | None = None) -> None:
        """Schedule a debounced callback keyed by name."""

        existing = self._debounce_handles.get(key)
        if existing is not None:
            try:
                self.after_cancel(existing)
            except Exception:
                pass
        delay = self._write_debounce_ms if delay_ms is None else delay_ms
        handle = self.after(delay, callback)
        self._debounce_handles[key] = handle

    def _schedule_groupings_config_write(self, delay_ms: int | None = None) -> None:
        self._schedule_debounce("config_write", self._flush_groupings_config, delay_ms)

    def _schedule_groupings_cache_write(self, delay_ms: int | None = None) -> None:
        # Cache is maintained by overlay client; avoid scheduling writes from controller.
        existing = self._debounce_handles.pop("cache_write", None)
        if existing is not None:
            try:
                self.after_cancel(existing)
            except Exception:
                pass

    def _emit_override_reload_signal(self) -> None:
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
        self._send_plugin_cli(payload)
        _controller_debug("Controller override reload signal sent (nonce=%s)", nonce)

    def _apply_mode_profile(self, mode: str, reason: str = "apply") -> None:
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
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding = getattr(self, "preview_canvas_padding", 10)
        inner_w = max(1, width - 2 * padding)
        inner_h = max(1, height - 2 * padding)

        selection = self._get_current_group_selection()
        snapshot = self._get_group_snapshot(selection) if selection is not None else None
        preview_bounds: tuple[float, float, float, float] | None = None
        preview_anchor_token: str | None = None
        preview_anchor_abs: tuple[float, float] | None = None
        if snapshot is not None:
            live_anchor_token = self._get_live_anchor_token(snapshot)
            snapshot = self._translate_snapshot_for_fill(
                snapshot,
                inner_w,
                inner_h,
                scale_mode_value=self._scale_mode_setting(),
                anchor_token_override=live_anchor_token,
            )
            target_frame = self._resolve_target_frame(snapshot)
            if target_frame is not None:
                bounds, anchor_point = target_frame
                preview_bounds = bounds
                preview_anchor_token = live_anchor_token
                preview_anchor_abs = anchor_point
            else:
                bounds = snapshot.transform_bounds or snapshot.base_bounds
                preview_bounds = bounds
                preview_anchor_token = snapshot.transform_anchor_token or snapshot.anchor_token
                preview_anchor_abs = self._compute_anchor_point(
                    bounds[0],
                    bounds[2],
                    bounds[1],
                    bounds[3],
                    preview_anchor_token,
                )

        signature_snapshot = (
            snapshot.base_bounds if snapshot is not None else None,
            snapshot.transform_bounds if snapshot is not None else None,
            snapshot.anchor_token if snapshot is not None else None,
            snapshot.transform_anchor_token if snapshot is not None else None,
            snapshot.offset_x if snapshot is not None else None,
            snapshot.offset_y if snapshot is not None else None,
            snapshot.cache_timestamp if snapshot is not None else None,
        )
        current_signature = (
            width,
            height,
            padding,
            selection,
            signature_snapshot,
            preview_bounds,
            preview_anchor_abs,
        )
        if self._last_preview_signature == current_signature:
            return
        self._last_preview_signature = current_signature

        canvas.delete("all")
        if selection is None:
            canvas.create_text(width // 2, height // 2, text="(select a group)", fill="#888888")
            return
        if snapshot is None:
            canvas.create_text(width // 2, height // 2, text="(awaiting cache)", fill="#888888")
            return

        label = selection[1]
        base_min_x, base_min_y, base_max_x, base_max_y = snapshot.base_bounds
        preview_bounds = preview_bounds or (snapshot.transform_bounds or snapshot.base_bounds)
        trans_min_x, trans_min_y, trans_max_x, trans_max_y = preview_bounds
        preview_anchor_token = preview_anchor_token or snapshot.transform_anchor_token or snapshot.anchor_token

        scale = max(0.01, min(inner_w / float(ABS_BASE_WIDTH), inner_h / float(ABS_BASE_HEIGHT)))
        content_w = ABS_BASE_WIDTH * scale
        content_h = ABS_BASE_HEIGHT * scale
        offset_x = padding + max(0.0, (inner_w - content_w) / 2.0)
        offset_y = padding + max(0.0, (inner_h - content_h) / 2.0)

        canvas.create_rectangle(
            offset_x,
            offset_y,
            offset_x + content_w,
            offset_y + content_h,
            outline="#555555",
            dash=(3, 3),
        )

        def _rect_color(fill: str) -> dict[str, object]:
            return {"fill": fill, "outline": "#000000", "width": 1}

        norm_x0 = offset_x + base_min_x * scale
        norm_y0 = offset_y + base_min_y * scale
        norm_x1 = offset_x + base_max_x * scale
        norm_y1 = offset_y + base_max_y * scale
        canvas.create_rectangle(norm_x0, norm_y0, norm_x1, norm_y1, **_rect_color("#66a3ff"))
        label_text = "Original Placement"
        label_font = ("TkDefaultFont", 8, "bold")
        inside = (norm_x1 - norm_x0) >= 110 and (norm_y1 - norm_y0) >= 20
        label_fill = "#ffffff" if not inside else "#1c2b4a"
        label_x = norm_x0 + 4 if inside else norm_x1 + 6
        label_y = norm_y0 + 12 if inside else norm_y0
        canvas.create_text(
            label_x,
            label_y,
            text=label_text,
            anchor="nw",
            fill=label_fill,
            font=label_font,
        )

        trans_x0 = offset_x + trans_min_x * scale
        trans_y0 = offset_y + trans_min_y * scale
        trans_x1 = offset_x + trans_max_x * scale
        trans_y1 = offset_y + trans_max_y * scale
        canvas.create_rectangle(trans_x0, trans_y0, trans_x1, trans_y1, **_rect_color("#ffa94d"))
        actual_label = "Target Placement"
        actual_inside = (trans_x1 - trans_x0) >= 110 and (trans_y1 - trans_y0) >= 20
        actual_fill = "#ffffff" if not actual_inside else "#5a2d00"
        actual_label_x = trans_x0 + 4 if actual_inside else trans_x1 + 6
        actual_label_y = trans_y0 + 12 if actual_inside else trans_y0
        canvas.create_text(
            actual_label_x,
            actual_label_y,
            text=actual_label,
            anchor="nw",
            fill=actual_fill,
            font=("TkDefaultFont", 8, "bold"),
        )

        if preview_anchor_abs is not None:
            anchor_px, anchor_py = preview_anchor_abs
            anchor_screen_x = offset_x + anchor_px * scale
            anchor_screen_y = offset_y + anchor_py * scale
            anchor_radius = 4
            canvas.create_oval(
                anchor_screen_x - anchor_radius,
                anchor_screen_y - anchor_radius,
                anchor_screen_x + anchor_radius,
                anchor_screen_y + anchor_radius,
                fill="#ffffff",
                outline="#000000",
                width=1,
            )

        canvas.create_text(
            padding + 6,
            padding + 6,
            text=f"{label}",
            anchor="nw",
            fill="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
        )
    def _persist_offsets(
        self, selection: tuple[str, str], offset_x: float, offset_y: float, debounce_ms: int | None = None
    ) -> None:
        plugin_name, label = selection
        self._edit_nonce = f"{time.time():.6f}-{os.getpid()}"
        state = self.__dict__.get("_group_state")
        if state is not None:
            try:
                state.persist_offsets(
                    plugin_name,
                    label,
                    offset_x,
                    offset_y,
                    edit_nonce=self._edit_nonce,
                    write=False,
                    invalidate_cache=True,
                )
                self._groupings_data = getattr(state, "_groupings_data", self._groupings_data)
                self._groupings_cache = getattr(state, "_groupings_cache", self._groupings_cache)
            except Exception:
                self._set_config_offsets(plugin_name, label, offset_x, offset_y)
        else:
            self._set_config_offsets(plugin_name, label, offset_x, offset_y)
        self._last_edit_ts = time.time()
        if state is None:
            self._invalidate_group_cache_entry(plugin_name, label)
        delay = self._offset_write_debounce_ms if debounce_ms is None else debounce_ms
        self._schedule_groupings_config_write(delay)
        snapshot = self._group_snapshots.get(selection)
        if snapshot is not None:
            snapshot.offset_x = offset_x
            snapshot.offset_y = offset_y
            # Clear any cached transform so preview/HUD stay aligned until client rewrites.
            snapshot.has_transform = False
            snapshot.transform_bounds = snapshot.base_bounds
            snapshot.transform_anchor_token = snapshot.anchor_token
            snapshot.transform_anchor = snapshot.base_anchor
            self._group_snapshots[selection] = snapshot
        _controller_debug(
            "Target updated for %s/%s: offset_x=%.1f offset_y=%.1f debounce_ms=%s",
            plugin_name,
            label,
            offset_x,
            offset_y,
            debounce_ms,
        )

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
        self._sync_absolute_for_current_group(force_ui=True)
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
        state = self.__dict__.get("_group_state")
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
        self._schedule_groupings_config_write()
        if state is None:
            self._invalidate_group_cache_entry(plugin_name, label)
        self._last_edit_ts = time.time()
        self._offset_live_edit_until = max(getattr(self, "_offset_live_edit_until", 0.0) or 0.0, self._last_edit_ts + 5.0)
        self._edit_nonce = f"{time.time():.6f}-{os.getpid()}"
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

        self._persist_offsets(selection, new_offset_x, new_offset_y, debounce_ms=self._offset_write_debounce_ms)
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

        self._persist_offsets(selection, new_offset_x, new_offset_y, debounce_ms=self._offset_write_debounce_ms)
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

    def _expected_transformed_anchor(self, snapshot: _GroupSnapshot) -> tuple[float, float]:
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

    def _get_live_anchor_token(self, snapshot: _GroupSnapshot) -> str:
        """Best-effort anchor token sourced from the UI."""

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

    def _get_live_absolute_anchor(self, snapshot: _GroupSnapshot) -> tuple[float, float]:
        """Return anchor coordinates, preferring unsaved widget values when available."""

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

    def _get_target_dimensions(self, snapshot: _GroupSnapshot) -> tuple[float, float]:
        """Use the actual placement bounds as the target frame size."""

        bounds = snapshot.transform_bounds or snapshot.base_bounds
        min_x, min_y, max_x, max_y = bounds
        width = max(0.0, float(max_x - min_x))
        height = max(0.0, float(max_y - min_y))
        return width, height

    def _bounds_from_anchor_point(
        self, anchor: str, anchor_x: float, anchor_y: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        """Translate an anchor coordinate into bounding box edges."""

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

    def _resolve_target_frame(self, snapshot: _GroupSnapshot) -> tuple[tuple[float, float, float, float], tuple[float, float]] | None:
        """Return ((min_x, min_y, max_x, max_y), (anchor_x, anchor_y)) for the simulated placement."""

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
        self._schedule_groupings_config_write()
        state = self.__dict__.get("_group_state")
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

    def _center_on_screen(self) -> None:
        """Position the window at the center of the available screen."""

        self.update_idletasks()
        width = max(1, self.winfo_width() or self.winfo_reqwidth())
        height = max(1, self.winfo_height() or self.winfo_reqheight())
        origin_x, origin_y, screen_width, screen_height = self._get_primary_screen_bounds()

        x = max(0, int(origin_x + (screen_width - width) / 2))
        y = max(0, int(origin_y + (screen_height - height) / 2))
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
        handler = build_rotating_file_handler(
            log_dir,
            "overlay_controller.log",
            retention=5,
            max_bytes=512 * 1024,
            formatter=formatter,
        )
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
