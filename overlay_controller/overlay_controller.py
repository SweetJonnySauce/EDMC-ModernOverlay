"""Tkinter scaffolding for the Overlay Controller tool."""

from __future__ import annotations

import json
import tkinter as tk
import platform
import re
import subprocess
from pathlib import Path
from tkinter import ttk

from input_bindings import BindingConfig, BindingManager
from selection_overlay import SelectionOverlay

ABS_BASE_WIDTH = 1280
ABS_BASE_HEIGHT = 960


class IdPrefixGroupWidget(tk.Frame):
    """Composite control with a dropdown selector (placeholder for future inputs)."""

    def __init__(self, parent: tk.Widget, options: list[str] | None = None) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._choices = options or []
        self._selection = tk.StringVar()
        self._request_focus: callable | None = None

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
        self._build_triangles()
        self.dropdown.bind("<Button-1>", self._handle_dropdown_click, add="+")

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(0, weight=1)

        self.dropdown.grid(row=0, column=1, padx=0, pady=0)

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
        if target_index == current_index:
            return False

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
    def handle_key(self, keysym: str, event: tk.Event[tk.Misc] | None = None) -> bool:  # type: ignore[name-defined]
        """Process keys while this widget has focus mode active."""

        def _alt_pressed(evt: object | None) -> bool:
            state = getattr(evt, "state", 0) or 0
            return bool(state & 0x0008) or bool(state & 0x20000)

        if _alt_pressed(event):
            return True

        key = keysym.lower()
        if key == "space":
            try:
                if self._is_dropdown_open():
                    focus_target = self.dropdown.tk.call("focus")
                    if focus_target:
                        self.dropdown.tk.call("event", "generate", focus_target, "<Return>")
                    else:
                        self.dropdown.event_generate("<Return>")
                else:
                    self.dropdown.event_generate("<Down>")
            except Exception:
                pass
            return True
        if key == "left":
            return self._advance_selection(-1)
        if key == "right":
            return self._advance_selection(1)
        if key == "down":
            try:
                self.dropdown.event_generate("<Down>")
            except Exception:
                pass
            return True
        if key == "return":
            if self._is_dropdown_open():
                try:
                    self.dropdown.event_generate("<Return>")
                except Exception:
                    pass
            return True
        return False


class OffsetSelectorWidget(tk.Frame):
    """Simple four-way offset selector with triangular arrow buttons."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self.button_size = 30
        self._arrows: dict[str, tuple[tk.Canvas, int]] = {}
        self._pinned: set[str] = set()
        self._default_color = "black"
        self._active_color = "#ff9900"
        self._request_focus: callable | None = None
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
            highlightthickness=1,
            relief="solid",
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
        canvas.bind("<Button-1>", lambda _e, d=direction: self._handle_click(d))
        self._arrows[direction] = (canvas, polygon_id)

    def _opposite(self, direction: str) -> str:
        mapping = {"up": "down", "down": "up", "left": "right", "right": "left"}
        return mapping.get(direction, "")

    def _apply_arrow_colors(self) -> None:
        for direction, (canvas, poly_id) in self._arrows.items():
            color = self._active_color if direction in self._pinned else self._default_color
            try:
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

    def _flash_arrow(self, direction: str, flash_ms: int = 140) -> None:
        entry = self._arrows.get(direction)
        if not entry:
            return
        canvas, poly_id = entry
        try:
            canvas.itemconfigure(poly_id, fill=self._active_color, outline=self._active_color)
            canvas.after(
                flash_ms,
                self._apply_arrow_colors,
            )
        except Exception:
            pass

    def _handle_click(self, direction: str) -> None:
        """Handle mouse click on an arrow, ensuring focus is acquired first."""

        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        try:
            self.focus_set()
        except Exception:
            pass
        self.handle_key(direction)

    def on_focus_enter(self) -> None:
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

        state = getattr(event, "state", 0) or 0
        return bool(state & 0x0008) or bool(state & 0x20000)

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def handle_key(self, keysym: str, event: object | None = None) -> bool:
        key = keysym.lower()
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

        self._flash_arrow(key)
        return True


class AbsoluteXYWidget(tk.Frame):
    """Absolute X/Y input widget with focus-aware navigation."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: callable | None = None
        self._active_field: str = "x"
        self._x_var = tk.StringVar()
        self._y_var = tk.StringVar()

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

        for field, entry in self._entries.items():
            entry.bind("<Button-1>", lambda _e, f=field: self._handle_entry_click(f), add="+")
            entry.bind("<FocusIn>", lambda _e, f=field: self._set_active_field(f), add="+")

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def _set_active_field(self, field: str) -> None:
        if field not in ("x", "y"):
            return
        self._active_field = field

    def _focus_field(self, field: str) -> None:
        self._set_active_field(field)
        entry = self._entries.get(field)
        if entry is None:
            return
        try:
            entry.focus_set()
            entry.icursor("end")
        except Exception:
            pass

    def _handle_entry_click(self, field: str) -> str:
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        self._focus_field(field)
        return "break"

    def on_focus_enter(self) -> None:
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

        self._focus_field(self._active_field)

    def _parse_value(self, raw: str, axis: str) -> float:
        """Parse value using percent/pixel rules from plugin_group_manager."""

        token = (raw or "").strip()
        if not token:
            raise ValueError(f"{axis} value is empty")

        base = ABS_BASE_WIDTH if axis.upper() == "X" else ABS_BASE_HEIGHT
        multiplier = 1.0
        mode = "px"
        token_lower = token.lower()
        if token_lower.endswith("px"):
            token = token[:-2].strip()
            multiplier = 100.0 / base
        elif token.endswith("%"):
            token = token[:-1].strip()
            mode = "%"
        else:
            multiplier = 100.0 / base
        try:
            numeric = float(token)
        except ValueError:
            raise ValueError(
                f"{axis} must be a percent with '%' (e.g. 50%) or a pixel value (e.g. 640 or 640px) relative to a 1280x960 window."
            ) from None
        numeric *= multiplier
        if numeric < 0.0 or numeric > 100.0:
            raise ValueError(f"{axis} value must be between 0 and 100 (received {numeric:g}).")
        return numeric

    def get_values(self) -> tuple[str, str]:
        return self._x_var.get(), self._y_var.get()

    def parse_values(self) -> tuple[float | None, float | None]:
        """Return parsed percent values or None if empty."""

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

    def handle_key(self, keysym: str, event: object | None = None) -> bool:
        key = keysym.lower()
        if key == "down" and self._active_field == "x":
            self._focus_field("y")
            return True
        if key == "up" and self._active_field == "y":
            self._focus_field("x")
            return True
        return False

class OverlayConfigApp(tk.Tk):
    """Basic UI skeleton that mirrors the design mockups."""

    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title("Overlay Controller")
        self.geometry("720x560")
        self.minsize(640, 420)
        self._closing = False
        self._pending_close_job: str | None = None
        self._focus_close_delay_ms = 200
        self._moving_guard_job: str | None = None
        self._moving_guard_active = False
        self._move_guard_timeout_ms = 500
        self._pending_focus_out = False
        self._drag_offset: tuple[int, int] | None = None

        self._placement_open = False
        self._open_width = 0
        self.sidebar_width = 260
        self.sidebar_pad = 12
        self.sidebar_pad_closed = 0
        self.container_pad_left = 12
        self.container_pad_right_open = 12
        self.container_pad_right_closed = 0
        self.container_pad_vertical = 12
        self.placement_min_width = 450
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
        self.placement_overlay_padding = 4
        self.overlay_border_width = 3
        self._focus_widgets: dict[tuple[str, int], object] = {}
        self._current_direction = "right"
        self._adjusting_geometry = False

        self._build_layout()
        self._binding_config = BindingConfig.load()
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
        self._binding_manager.activate()
        self.bind("<Configure>", self._handle_configure)
        self.bind("<FocusIn>", self._handle_focus_in)
        self.bind("<space>", self._handle_space_key, add="+")
        self.bind("<ButtonPress-1>", self._start_window_drag, add="+")
        self.bind("<B1-Motion>", self._on_window_drag, add="+")
        self.bind("<ButtonRelease-1>", self._end_window_drag, add="+")
        self.after(0, self._center_and_show)

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
        self.container.grid_columnconfigure(0, weight=1, minsize=self.sidebar_width)
        self.container.grid_columnconfigure(1, weight=1)

        # Placement window placeholder (open state)
        self.placement_frame = tk.Frame(
            self.container,
            bd=0,
            relief="flat",
            background="#f5f5f5",
        )
        placement_label = tk.Label(
            self.placement_frame,
            text="placement window (open)",
            anchor="nw",
            bg="#f5f5f5",
            padx=8,
            pady=6,
        )
        placement_label.pack(fill="both", expand=True)
        self.placement_frame.bind("<Button-1>", self._handle_placement_click, add="+")
        placement_label.bind("<Button-1>", self._handle_placement_click, add="+")

        # Sidebar with individual selector sections
        self.sidebar = tk.Frame(
            self.container,
            width=self.sidebar_width,
            bd=0,
            highlightthickness=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, self.sidebar_pad))
        self._build_sidebar_sections()
        self.sidebar.grid_propagate(False)

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
            ("idprefix group selector", 0),
            ("offset selector", 0),
            ("absolute x/y", 0),
            ("anchor selector", 0),
            ("payload justification", 0),
            ("zoom selector (future implementation)", 1),
        ]

        self.sidebar_cells: list[tk.Frame] = []
        self._sidebar_focus_index = 0
        self.widget_select_mode = True

        for index, (label_text, weight) in enumerate(sections):
            frame = tk.Frame(
                self.sidebar,
                bd=0,
                relief="flat",
                width=0 if index == 0 else 220,
                height=0 if index == 0 else 80,
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
            if index == 0:
                self.idprefix_widget = IdPrefixGroupWidget(frame, options=self._load_idprefix_options())
                self.idprefix_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.idprefix_widget.pack(fill="both", expand=True, padx=0, pady=0)
                self._focus_widgets[("sidebar", index)] = self.idprefix_widget
            elif index == 1:
                self.offset_widget = OffsetSelectorWidget(frame)
                self.offset_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.offset_widget.pack(expand=True)
                self._focus_widgets[("sidebar", index)] = self.offset_widget
            elif index == 2:
                self.absolute_widget = AbsoluteXYWidget(frame)
                self.absolute_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.absolute_widget.pack(fill="both", expand=True, padx=0, pady=0)
                self._focus_widgets[("sidebar", index)] = self.absolute_widget
            else:
                text_label = tk.Label(frame, text=label_text, anchor="center", padx=6, pady=6)
                text_label.pack(fill="both", expand=True)
            frame.bind(
                "<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+"
            )
            for child in frame.winfo_children():
                child.bind("<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+")
            grow_weight = 1 if index == len(sections) - 1 else 0
            self.sidebar.grid_rowconfigure(index, weight=grow_weight)
            self.sidebar_cells.append(frame)

        self.sidebar.grid_columnconfigure(0, weight=1)

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
        if self.widget_focus_area == "placement":
            self.widget_focus_area = "sidebar"
            self._refresh_widget_focus()
        elif self.widget_focus_area == "sidebar" and self._placement_open:
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
        if self.widget_focus_area == "sidebar":
            if not self._placement_open:
                self._placement_open = True
                self._apply_placement_state()
            self.widget_focus_area = "placement"
            self._refresh_widget_focus()
        elif self.widget_focus_area == "placement":
            self.widget_focus_area = "placement"
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

    def _refresh_widget_focus(self) -> None:
        if hasattr(self, "sidebar_cells"):
            self._update_sidebar_highlight()
        self._update_placement_focus_highlight()
        try:
            self.indicator_wrapper.lift()
        except Exception:
            pass

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

        self._cancel_pending_close()
        self._pending_focus_out = False
        self._closing = True
        self.destroy()

    def _handle_focus_in(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Cancel any delayed close when the window regains focus."""

        self._cancel_pending_close()
        self._pending_focus_out = False
        self._drag_offset = None

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

        def select() -> bool:
            handler = getattr(widget, "handle_key", None)
            if handler is None:
                return False
            try:
                return bool(handler("space", event))
            except Exception:
                return True

        lower_keysym = keysym.lower()
        if lower_keysym == "escape":
            self.exit_focus_mode()
            return True
        if lower_keysym == "space":
            return select() or True

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
        root = Path(__file__).resolve().parents[1]
        path = root / "overlay_groupings.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        options: list[str] = []
        if isinstance(payload, dict):
            for plugin_name, entry in sorted(payload.items(), key=lambda item: item[0].casefold()):
                groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
                if not isinstance(groups, dict):
                    continue
                for label in sorted(groups.keys(), key=str.casefold):
                    options.append(f"{plugin_name} — {label}")
        return options

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
        current_height = max(self.winfo_height(), 420)
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
            self.minsize(open_min_width, 420)
            self.geometry(f"{int(target_width)}x{int(current_height)}")
            self._open_width = max(self._open_width, self.winfo_width(), self.winfo_reqwidth(), open_min_width)
            self._enforce_placement_aspect()
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
            self.minsize(collapsed_width, 420)
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

    def _enforce_placement_aspect(self) -> None:
        """Keep the placement area near a 4:3 ratio by adjusting height instead of width."""

        if not self._placement_open or self._adjusting_geometry:
            return
        self.update_idletasks()
        sidebar_width = max(self.sidebar_width, self.sidebar.winfo_width())
        container_width = max(1, self.container.winfo_width())
        available_width = container_width - (
            self.container_pad_left + self.container_pad_right_open + sidebar_width + self._current_sidebar_pad
        )
        placement_width = max(self.placement_min_width, available_width)
        desired_height = int(placement_width * (3 / 4))
        min_height = 420
        target_height = max(min_height, desired_height + (self.container_pad_vertical * 2))
        current_width = max(1, self.winfo_width())
        current_height = max(1, self.winfo_height())
        if abs(target_height - current_height) <= 1:
            return
        self._adjusting_geometry = True
        try:
            self.geometry(f"{int(current_width)}x{int(target_height)}")
        finally:
            self._adjusting_geometry = False

    def _handle_configure(self, _event: tk.Event[tk.Misc]) -> None:  # type: ignore[name-defined]
        """Re-center the indicator when the window is resized."""

        if self._placement_open:
            self._enforce_placement_aspect()
        else:
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

        self._center_on_screen()
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass
        # Ensure indicator is positioned after the first real layout pass.
        try:
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


def launch() -> None:
    """Entry point used by other modules."""

    app = OverlayConfigApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
