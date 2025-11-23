"""Tkinter scaffolding for the Overlay Controller tool."""

from __future__ import annotations

import json
import tkinter as tk
import platform
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from tkinter import ttk

from input_bindings import BindingConfig, BindingManager
from selection_overlay import SelectionOverlay

ABS_BASE_WIDTH = 1280
ABS_BASE_HEIGHT = 960
ABS_MIN_X = 0.0
ABS_MAX_X = float(ABS_BASE_WIDTH)
ABS_MIN_Y = 0.0
ABS_MAX_Y = float(ABS_BASE_HEIGHT)


class IdPrefixGroupWidget(tk.Frame):
    """Composite control with a dropdown selector (placeholder for future inputs)."""

    def __init__(self, parent: tk.Widget, options: list[str] | None = None) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._choices = options or []
        self._selection = tk.StringVar()
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
        self._build_triangles()
        self.dropdown.bind("<Button-1>", self._handle_dropdown_click, add="+")
        self.dropdown.bind("<<ComboboxSelected>>", self._handle_selection_change, add="+")

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
        self.button_size = 36
        self._arrows: dict[str, tuple[tk.Canvas, int]] = {}
        self._pinned: set[str] = set()
        self._default_color = "black"
        self._active_color = "#ff9900"
        self._request_focus: callable | None = None
        self._on_change: callable | None = None
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
        self._emit_change(direction, pinned=True)

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
            self._emit_change(opposite, pinned=False)

        self._flash_arrow(key)
        self._emit_change(key, pinned=False)
        return True

    def set_change_callback(self, callback: callable | None) -> None:
        self._on_change = callback

    def _emit_change(self, direction: str, pinned: bool) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(direction, pinned)
        except Exception:
            pass


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
        active_bg = "#dce6ff" if self._has_focus else self.cget("background")
        inactive_bg = self.cget("background")
        outline_color = "#4a4a4a" if self._has_focus else "#9a9a9a"
        bar_color = "#1c1c1c" if self._has_focus else "#555555"
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
        if not self._has_focus:
            if self._request_focus:
                try:
                    self._request_focus()
                except Exception:
                    pass
            return "break"
        self._active_index = max(0, min(len(self._choices) - 1, index))
        self._apply_styles()
        self._emit_change()
        return "break"

    def set_focus_request_callback(self, callback: callable | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def on_focus_enter(self) -> None:
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
        if not self._has_focus:
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
        try:
            self._on_change(self.get_justification())
        except Exception:
            pass


class AnchorSelectorWidget(tk.Frame):
    """3x3 anchor grid with movable highlight."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: callable | None = None
        self._has_focus = False
        self._active_index = 0  # start at NW
        self._on_change: callable | None = None
        self.canvas = tk.Canvas(
            self,
            width=120,
            height=120,
            bd=0,
            highlightthickness=0,
            bg=self.cget("background"),
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.after_idle(self._draw)
        self.canvas.bind("<Button-1>", self._handle_click)
        self._positions: list[tuple[float, float]] = []

    def _draw(self) -> None:
        self.canvas.delete("all")
        self.canvas.update_idletasks()
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
        line_color = "#2b2b2b" if self._has_focus else "#888888"
        dot_color = "#000000"
        highlight_color = "#000000"

        # Outer square (dashed)
        self.canvas.create_line(xs[0], ys[0], xs[2], ys[0], fill=line_color, dash=(2, 3))
        self.canvas.create_line(xs[2], ys[0], xs[2], ys[2], fill=line_color, dash=(2, 3))
        self.canvas.create_line(xs[2], ys[2], xs[0], ys[2], fill=line_color, dash=(2, 3))
        self.canvas.create_line(xs[0], ys[2], xs[0], ys[0], fill=line_color, dash=(2, 3))

        positions: list[tuple[float, float]] = []
        for j in range(3):
            for i in range(3):
                positions.append((xs[i], ys[j]))
        self._positions = positions

        # Highlight square anchored on active dot
        px, py = positions[self._active_index]
        highlight_size = spacing
        min_x, max_x = xs[0], xs[2]
        min_y, max_y = ys[0], ys[2]
        hx0 = min(max(px - highlight_size / 2, min_x), max_x - highlight_size)
        hy0 = min(max(py - highlight_size / 2, min_y), max_y - highlight_size)
        hx1 = hx0 + highlight_size
        hy1 = hy0 + highlight_size
        if self._has_focus:
            self.canvas.create_rectangle(hx0, hy0, hx1, hy1, fill="#cfe6ff", outline="#5a7cae", width=1.2)
        else:
            self.canvas.create_rectangle(hx0, hy0, hx1, hy1, outline=line_color, width=1)

        dot_r = 8
        for idx, (px, py) in enumerate(positions):
            self.canvas.create_oval(
                px - dot_r,
                py - dot_r,
                px + dot_r,
                py + dot_r,
                outline=dot_color,
                fill=dot_color,
            )
            if idx == self._active_index:
                self.canvas.create_oval(
                    px - (dot_r + 4),
                    py - (dot_r + 4),
                    px + (dot_r + 4),
                    py + (dot_r + 4),
                    outline=highlight_color,
                    width=2,
                )

    def _handle_click(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
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
                    nearest = min(
                        enumerate(self._positions),
                        key=lambda item: (item[1][0] - ex) ** 2 + (item[1][1] - ey) ** 2,
                    )[0]
                    if nearest != self._active_index:
                        self._active_index = nearest
                        self._draw()
                        self._emit_change()
                except Exception:
                    pass
        return "break"

    def set_focus_request_callback(self, callback: callable | None) -> None:
        self._request_focus = callback

    def on_focus_enter(self) -> None:
        self._has_focus = True
        self._draw()
        try:
            self.focus_set()
        except Exception:
            pass

    def on_focus_exit(self) -> None:
        self._has_focus = False
        self._draw()
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def handle_key(self, keysym: str, _event: object | None = None) -> bool:
        if not self._has_focus:
            return False
        # Ignore modified arrows (e.g., Alt+Arrow) to keep behavior consistent with bindings.
        state = getattr(_event, "state", 0) or 0
        alt_pressed = bool(state & 0x0008) or bool(state & 0x20000)
        if alt_pressed:
            return False

        key = keysym.lower()
        row, col = divmod(self._active_index, 3)
        if key == "left" and col > 0:
            col -= 1
        elif key == "right" and col < 2:
            col += 1
        elif key == "up" and row > 0:
            row -= 1
        elif key == "down" and row < 2:
            row += 1
        else:
            return False
        self._active_index = row * 3 + col
        self._draw()
        self._emit_change()
        return True

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
        try:
            self._on_change(self.get_anchor())
        except Exception:
            pass


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

        for field, entry in self._entries.items():
            entry.bind("<Button-1>", lambda _e, f=field: self._handle_entry_click(f), add="+")
            entry.bind("<FocusIn>", lambda _e, f=field: self._set_active_field(f), add="+")
            entry.bind("<FocusOut>", lambda _e, f=field: self._emit_change(f), add="+")
            entry.bind("<Return>", lambda _e, f=field: self._emit_change(f) or "break", add="+")

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

    def _emit_change(self, field: str) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(field)
        except Exception:
            pass

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

        self._x_var.set(_fmt(x))
        self._y_var.set(_fmt(y))

    def get_px_values(self) -> tuple[float | None, float | None]:
        return self.parse_values()

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
        self.geometry("740x760")
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
        self._groupings_data: dict[str, object] = {}
        self._idprefix_entries: list[tuple[str, str]] = []
        root = Path(__file__).resolve().parents[1]
        self._groupings_path = root / "overlay_groupings.json"
        self._groupings_cache_path = root / "overlay_group_cache.json"
        self._groupings_cache: dict[str, object] = {}
        self._absolute_user_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._anchor_restore_state: dict[tuple[str, str], dict[str, float | None]] = {}
        self._anchor_restore_handles: dict[tuple[str, str], str | None] = {}
        self._absolute_tolerance_px = 0.5
        self._debounce_handles: dict[str, str | None] = {}
        self._write_debounce_ms = 300
        self._offset_write_debounce_ms = 600
        self._offset_step_px = 10.0

        self._build_layout()
        self._groupings_cache = self._load_groupings_cache()
        self._handle_idprefix_selected()
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
            if index == 0:
                self.idprefix_widget = IdPrefixGroupWidget(frame, options=self._load_idprefix_options())
                self.idprefix_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.idprefix_widget.set_selection_change_callback(lambda _sel=None: self._handle_idprefix_selected())
                self.idprefix_widget.pack(fill="both", expand=True, padx=0, pady=0)
                self._focus_widgets[("sidebar", index)] = self.idprefix_widget
            elif index == 1:
                self.offset_widget = OffsetSelectorWidget(frame)
                self.offset_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.offset_widget.set_change_callback(self._handle_offset_changed)
                self.offset_widget.pack(expand=True)
                self._focus_widgets[("sidebar", index)] = self.offset_widget
            elif index == 2:
                self.absolute_widget = AbsoluteXYWidget(frame)
                self.absolute_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.absolute_widget.set_change_callback(self._handle_absolute_changed)
                self.absolute_widget.pack(fill="both", expand=True, padx=0, pady=0)
                self._focus_widgets[("sidebar", index)] = self.absolute_widget
            elif index == 3:
                frame.configure(height=140)
                frame.grid_propagate(False)
                self.anchor_widget = AnchorSelectorWidget(frame)
                self.anchor_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.anchor_widget.set_change_callback(self._handle_anchor_changed)
                self.anchor_widget.pack(fill="both", expand=True, padx=4, pady=4)
                self._focus_widgets[("sidebar", index)] = self.anchor_widget
            elif index == 4:
                self.justification_widget = JustificationWidget(frame)
                self.justification_widget.set_focus_request_callback(lambda idx=index: self._handle_sidebar_click(idx))
                self.justification_widget.set_change_callback(self._handle_justification_changed)
                self.justification_widget.pack(fill="both", expand=True, padx=4, pady=4)
                self._focus_widgets[("sidebar", index)] = self.justification_widget
            else:
                text_label = tk.Label(frame, text=label_text, anchor="center", padx=6, pady=6)
                text_label.pack(fill="both", expand=True)
            frame.bind(
                "<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+"
            )
            for child in frame.winfo_children():
                child.bind("<Button-1>", lambda event, idx=index: self._handle_sidebar_click(idx), add="+")
            grow_weight = 1 if index == len(sections) - 1 else 0
            row_opts = {"weight": grow_weight}
            if index == 3:
                row_opts["minsize"] = 220
            self.sidebar.grid_rowconfigure(index, **row_opts)
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
                for label in labels:
                    display = f"{plugin_name}: {label}" if show_plugin else label
                    options.append(display)
                    self._idprefix_entries.append((plugin_name, label))
        return options

    def _get_group_config(self, plugin_name: str, label: str) -> dict[str, object]:
        entry = self._groupings_data.get(plugin_name) if isinstance(self._groupings_data, dict) else None
        groups = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        group = groups.get(label) if isinstance(groups, dict) else None
        return group if isinstance(group, dict) else {}

    def _load_groupings_cache(self) -> dict[str, object]:
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

    def _write_groupings_config(self) -> None:
        path = getattr(self, "_groupings_path", None)
        if path is None:
            return
        try:
            text = json.dumps(self._groupings_data, indent=2, sort_keys=True)
            path.write_text(text + "\n", encoding="utf-8")
        except Exception:
            pass

    def _write_groupings_cache(self) -> None:
        # Controller is read-only for overlay_group_cache.json; no-op to avoid clobbering client data.
        return

    def _flush_groupings_config(self) -> None:
        self._debounce_handles["config_write"] = None
        self._write_groupings_config()

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

    def _select_transformed_for_anchor(self, anchor: str, trans_min: float, trans_max: float, axis: str) -> float:
        horizontal, vertical = self._anchor_sides(anchor)
        side = horizontal if (axis or "").lower() == "x" else vertical
        if side in {"left", "top"}:
            return trans_min
        if side in {"right", "bottom"}:
            return trans_max
        return (trans_min + trans_max) / 2.0

    def _rebuild_transformed_span(self, anchor: str, user_val: float, norm_span: float, axis: str) -> tuple[float, float]:
        span = max(0.0, norm_span)
        horizontal, vertical = self._anchor_sides(anchor)
        side = horizontal if (axis or "").lower() == "x" else vertical
        if side in {"left", "top"}:
            start = user_val
        elif side in {"right", "bottom"}:
            start = user_val - span
        else:
            start = user_val - (span / 2.0)
        return start, start + span

    def _split_anchor(self, anchor: str) -> tuple[str, str]:
        anchor = (anchor or "").lower()
        x_side = "center"
        y_side = "center"
        if "left" in anchor:
            x_side = "left"
        elif "right" in anchor:
            x_side = "right"
        if "top" in anchor or anchor == "n":
            y_side = "top"
        elif "bottom" in anchor or anchor == "s":
            y_side = "bottom"
        return x_side, y_side

    def _combine_anchor(self, x_side: str, y_side: str) -> str:
        x_side = x_side or "center"
        y_side = y_side or "center"
        if x_side == "left" and y_side == "top":
            return "nw"
        if x_side == "right" and y_side == "top":
            return "ne"
        if x_side == "left" and y_side == "bottom":
            return "sw"
        if x_side == "right" and y_side == "bottom":
            return "se"
        if x_side == "left":
            return "left"
        if x_side == "right":
            return "right"
        if y_side == "top":
            return "top"
        if y_side == "bottom":
            return "bottom"
        return "center"

    def _resolve_pinned_anchor(self, current_anchor: str, direction: str) -> str:
        anchor = (current_anchor or "").lower()
        direction = (direction or "").lower()
        mapping = {
            ("ne", "down"): "se",
            ("ne", "left"): "nw",
            ("top", "right"): "ne",
            ("top", "left"): "nw",
            ("top", "down"): "bottom",
            ("nw", "right"): "ne",
            ("nw", "down"): "sw",
            ("left", "up"): "nw",
            ("left", "down"): "sw",
            ("left", "right"): "right",
            ("sw", "up"): "nw",
            ("sw", "right"): "se",
            ("bottom", "left"): "sw",
            ("bottom", "right"): "se",
            ("bottom", "up"): "top",
            ("se", "left"): "sw",
            ("se", "up"): "ne",
            ("center", "up"): "top",
            ("center", "left"): "left",
            ("center", "down"): "bottom",
            ("center", "right"): "right",
        }
        return mapping.get((anchor, direction), anchor)

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

    def _compute_anchor_point(self, min_x: float, max_x: float, min_y: float, max_y: float, anchor: str) -> tuple[float, float]:
        h, v = self._anchor_sides(anchor)
        ax = min_x if h == "left" else max_x if h == "right" else (min_x + max_x) / 2.0
        ay = min_y if v == "top" else max_y if v == "bottom" else (min_y + max_y) / 2.0
        return ax, ay

    def _build_rect_from_anchor(self, anchor: str, width: float, height: float, anchor_x: float, anchor_y: float) -> tuple[float, float, float, float]:
        h, v = self._anchor_sides(anchor)
        if h == "left":
            min_x = anchor_x
            max_x = anchor_x + width
        elif h == "right":
            min_x = anchor_x - width
            max_x = anchor_x
        else:
            min_x = anchor_x - (width / 2.0)
            max_x = anchor_x + (width / 2.0)

        if v == "top":
            min_y = anchor_y
            max_y = anchor_y + height
        elif v == "bottom":
            min_y = anchor_y - height
            max_y = anchor_y
        else:
            min_y = anchor_y - (height / 2.0)
            max_y = anchor_y + (height / 2.0)

        return min_x, min_y, max_x, max_y

    def _draw_preview(self) -> None:
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding = 10
        inner_w = max(1, width - 2 * padding)
        inner_h = max(1, height - 2 * padding)
        canvas.create_rectangle(
            padding,
            padding,
            width - padding,
            height - padding,
            outline="#555555",
            dash=(3, 3),
        )

        selection = self._get_current_group_selection()
        if selection is None:
            canvas.create_text(width // 2, height // 2, text="(select a group)", fill="#888888")
            return
        plugin_name, label = selection
        norm_vals, trans_vals, cache_anchor, _ts = self._get_cache_entry(plugin_name, label)
        cfg = self._get_group_config(plugin_name, label)
        cfg_anchor = cfg.get("idPrefixGroupAnchor") if isinstance(cfg, dict) else None
        anchor = None
        if hasattr(self, "anchor_widget"):
            try:
                anchor = self.anchor_widget.get_anchor()
            except Exception:
                anchor = None
        if not anchor:
            anchor = cache_anchor or cfg_anchor or "nw"
        offset_x_cfg = float(cfg.get("offsetX", 0.0)) if isinstance(cfg, dict) else 0.0
        offset_y_cfg = float(cfg.get("offsetY", 0.0)) if isinstance(cfg, dict) else 0.0

        scale = max(0.01, min(inner_w / float(ABS_BASE_WIDTH), inner_h / float(ABS_BASE_HEIGHT)))
        origin_x = padding
        origin_y = padding

        def _rect_color(fill: str) -> dict[str, object]:
            return {"fill": fill, "outline": "#000000", "width": 1}

        norm_x0 = origin_x + norm_vals["min_x"] * scale
        norm_y0 = origin_y + norm_vals["min_y"] * scale
        norm_x1 = origin_x + norm_vals["max_x"] * scale
        norm_y1 = origin_y + norm_vals["max_y"] * scale
        canvas.create_rectangle(norm_x0, norm_y0, norm_x1, norm_y1, **_rect_color("#66a3ff"))

        norm_width = norm_vals["max_x"] - norm_vals["min_x"]
        norm_height = norm_vals["max_y"] - norm_vals["min_y"]
        norm_anchor_x, norm_anchor_y = self._compute_anchor_point(
            norm_vals["min_x"], norm_vals["max_x"], norm_vals["min_y"], norm_vals["max_y"], anchor
        )

        # Current transformed anchor from cache, then shift so target anchor = normalized anchor + offsets.
        trans_anchor_cur_x, trans_anchor_cur_y = self._compute_anchor_point(
            trans_vals["min_x"], trans_vals["max_x"], trans_vals["min_y"], trans_vals["max_y"], anchor
        )
        target_anchor_x = norm_anchor_x + offset_x_cfg
        target_anchor_y = norm_anchor_y + offset_y_cfg
        dx = target_anchor_x - trans_anchor_cur_x
        dy = target_anchor_y - trans_anchor_cur_y

        trans_min_x = trans_vals["min_x"] + dx
        trans_max_x = trans_vals["max_x"] + dx
        trans_min_y = trans_vals["min_y"] + dy
        trans_max_y = trans_vals["max_y"] + dy

        trans_x0 = origin_x + trans_min_x * scale
        trans_y0 = origin_y + trans_min_y * scale
        trans_x1 = origin_x + trans_max_x * scale
        trans_y1 = origin_y + trans_max_y * scale
        canvas.create_rectangle(trans_x0, trans_y0, trans_x1, trans_y1, **_rect_color("#ffa94d"))

        def _draw_anchor(ax: float, ay: float, color: str) -> None:
            px = origin_x + ax * scale
            py = origin_y + ay * scale
            r = 4
            canvas.create_oval(px - r, py - r, px + r, py + r, fill=color, outline="#000000")

        _draw_anchor(norm_anchor_x, norm_anchor_y, "#66a3ff")
        _draw_anchor(target_anchor_x, target_anchor_y, "#ffa94d")

        canvas.create_text(
            padding + 6,
            padding + 6,
            text=f"{label}",
            anchor="nw",
            fill="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
        )

    def _draw_preview(self) -> None:
        canvas = getattr(self, "preview_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding = 10
        inner_w = max(1, width - 2 * padding)
        inner_h = max(1, height - 2 * padding)
        canvas.create_rectangle(
            padding,
            padding,
            width - padding,
            height - padding,
            outline="#555555",
            dash=(3, 3),
        )

        selection = self._get_current_group_selection()
        if selection is None:
            canvas.create_text(width // 2, height // 2, text="(select a group)", fill="#888888")
            return
        plugin_name, label = selection
        norm_vals, trans_vals, anchor_name, _ts = self._get_cache_entry(plugin_name, label)

        scale = max(0.01, min(inner_w / float(ABS_BASE_WIDTH), inner_h / float(ABS_BASE_HEIGHT)))
        offset_x = padding
        offset_y = padding

        def _rect_color(fill: str) -> dict[str, object]:
            return {"fill": fill, "outline": "#000000", "width": 1}

        # Normalized rectangle
        norm_x0 = offset_x + norm_vals["min_x"] * scale
        norm_y0 = offset_y + norm_vals["min_y"] * scale
        norm_x1 = offset_x + norm_vals["max_x"] * scale
        norm_y1 = offset_y + norm_vals["max_y"] * scale
        canvas.create_rectangle(norm_x0, norm_y0, norm_x1, norm_y1, **_rect_color("#66a3ff"))

        # Transformed rectangle
        trans_x0 = offset_x + trans_vals["min_x"] * scale
        trans_y0 = offset_y + trans_vals["min_y"] * scale
        trans_x1 = offset_x + trans_vals["max_x"] * scale
        trans_y1 = offset_y + trans_vals["max_y"] * scale
        canvas.create_rectangle(trans_x0, trans_y0, trans_x1, trans_y1, **_rect_color("#ffa94d"))

        # Draw anchor indicator on the transformed rectangle.
        anchor_px, anchor_py = self._compute_anchor_point(
            trans_vals["min_x"],
            trans_vals["max_x"],
            trans_vals["min_y"],
            trans_vals["max_y"],
            anchor_name,
        )
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

    def _get_cache_entry(
        self, plugin_name: str, label: str
    ) -> tuple[dict[str, float], dict[str, float], str, float]:
        groups = self._groupings_cache.get("groups") if isinstance(self._groupings_cache, dict) else {}
        plugin_entry = groups.get(plugin_name) if isinstance(groups, dict) else {}
        entry = plugin_entry.get(label) if isinstance(plugin_entry, dict) else {}
        normalized = entry.get("normalized") if isinstance(entry, dict) else {}
        transformed = entry.get("transformed") if isinstance(entry, dict) else {}
        norm_vals = {
            "min_x": float(normalized.get("norm_min_x", 0.0)) if isinstance(normalized, dict) else 0.0,
            "max_x": float(normalized.get("norm_max_x", 0.0)) if isinstance(normalized, dict) else 0.0,
            "min_y": float(normalized.get("norm_min_y", 0.0)) if isinstance(normalized, dict) else 0.0,
            "max_y": float(normalized.get("norm_max_y", 0.0)) if isinstance(normalized, dict) else 0.0,
        }
        norm_vals["width"] = norm_vals["max_x"] - norm_vals["min_x"]
        norm_vals["height"] = norm_vals["max_y"] - norm_vals["min_y"]
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

    def _update_cache_entry(
        self,
        plugin_name: str,
        label: str,
        trans_vals: dict[str, float],
        anchor: str,
        timestamp: float,
    ) -> None:
        if not isinstance(self._groupings_cache, dict):
            self._groupings_cache = {"groups": {}}
        groups = self._groupings_cache.setdefault("groups", {})
        plugin_entry = groups.setdefault(plugin_name, {})
        entry = plugin_entry.get(label)
        if not isinstance(entry, dict):
            entry = {}
            plugin_entry[label] = entry
        normalized = entry.get("base") if isinstance(entry, dict) else None
        if not isinstance(normalized, dict):
            normalized = {}
        transformed = entry.get("transformed") if isinstance(entry, dict) else None
        if not isinstance(transformed, dict):
            transformed = {}
        transformed["trans_min_x"] = trans_vals.get("min_x", transformed.get("trans_min_x", 0.0))
        transformed["trans_max_x"] = trans_vals.get("max_x", transformed.get("trans_max_x", transformed.get("trans_min_x", 0.0)))
        transformed["trans_min_y"] = trans_vals.get("min_y", transformed.get("trans_min_y", 0.0))
        transformed["trans_max_y"] = trans_vals.get("max_y", transformed.get("trans_max_y", transformed.get("trans_min_y", 0.0)))
        transformed["anchor"] = anchor
        entry["transformed"] = transformed
        entry["base"] = normalized
        entry["last_updated"] = timestamp

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
        group["offsetX"] = offset_x
        group["offsetY"] = offset_y

    def _handle_idprefix_selected(self, _selection: str | None = None) -> None:
        if not hasattr(self, "idprefix_widget"):
            return
        try:
            idx = int(self.idprefix_widget.dropdown.current())
        except Exception:
            idx = -1
        if not (0 <= idx < len(self._idprefix_entries)):
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
        self._draw_preview()

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
        self._schedule_groupings_config_write()

    def _handle_absolute_changed(self, axis: str) -> None:
        selection = self._get_current_group_selection()
        if selection is None or not hasattr(self, "absolute_widget"):
            return
        plugin_name, label = selection
        x_val, y_val = self.absolute_widget.get_px_values()
        state = self._absolute_user_state.get(selection, {"x": None, "y": None, "x_ts": 0.0, "y_ts": 0.0})
        now = time.time()
        if axis == "x" and x_val is not None:
            state["x"] = x_val
            state["x_ts"] = now
        if axis == "y" and y_val is not None:
            state["y"] = y_val
            state["y_ts"] = now
        self._absolute_user_state[selection] = state
        self._sync_absolute_for_current_group(force_ui=False)

    def _handle_offset_changed(self, direction: str, pinned: bool) -> None:
        selection = self._get_current_group_selection()
        if selection is None or not hasattr(self, "absolute_widget"):
            return
        plugin_name, label = selection
        x_val, y_val = self.absolute_widget.get_px_values()
        x_val = x_val if x_val is not None else 0.0
        y_val = y_val if y_val is not None else 0.0

        if pinned:
            current_anchor = "center"
            if hasattr(self, "anchor_widget"):
                try:
                    current_anchor = self.anchor_widget.get_anchor()
                except Exception:
                    pass
            if direction == "left":
                x_val = ABS_MIN_X
            elif direction == "right":
                x_val = ABS_MAX_X
            elif direction == "up":
                y_val = ABS_MIN_Y
            elif direction == "down":
                y_val = ABS_MAX_Y
            else:
                return
            anchor_target = self._resolve_pinned_anchor(current_anchor, direction)
        else:
            step = self._offset_step_px
            anchor_target = None
            if direction == "left":
                x_val = max(ABS_MIN_X, x_val - step)
            elif direction == "right":
                x_val = min(ABS_MAX_X, x_val + step)
            elif direction == "up":
                y_val = max(ABS_MIN_Y, y_val - step)
            elif direction == "down":
                y_val = min(ABS_MAX_Y, y_val + step)
            else:
                return

        now = time.time()
        state = self._absolute_user_state.get(selection, {"x": None, "y": None, "x_ts": 0.0, "y_ts": 0.0})
        state["x"] = x_val
        state["y"] = y_val
        state["x_ts"] = now
        state["y_ts"] = now
        self._absolute_user_state[selection] = state
        self.absolute_widget.set_px_values(x_val, y_val)
        if pinned and hasattr(self, "anchor_widget"):
            try:
                self.anchor_widget.set_anchor(anchor_target)
            except Exception:
                pass
            self._handle_anchor_changed(anchor_target, prefer_user=True)
        self._sync_absolute_for_current_group(
            force_ui=False, debounce_ms=self._offset_write_debounce_ms, prefer_user=pinned
        )
        self._draw_preview()

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

        norm_vals, trans_vals, _existing_anchor, cache_ts = self._get_cache_entry(plugin_name, label)
        cache_ts_write = max(cache_ts, time.time())
        self._update_cache_entry(plugin_name, label, trans_vals, anchor, cache_ts_write)
        self._schedule_groupings_cache_write()
        self._sync_absolute_for_current_group(force_ui=True, prefer_user=prefer_user)
        self._draw_preview()
        if captured:
            self._schedule_anchor_restore(selection)

    def _sync_axis(
        self,
        anchor: str,
        norm_min: float,
        norm_max: float,
        trans_min: float,
        trans_max: float,
        offset: float,
        user_val: float | None,
        user_ts: float,
        cache_ts: float,
        axis: str,
        prefer_user: bool,
    ) -> tuple[float, float, float, float, float, float, float]:
        base_val = norm_min
        current_transformed = self._select_transformed_for_anchor(anchor, trans_min, trans_max, axis)

        resolved_user = user_val if user_val is not None else current_transformed
        resolved_user_ts = user_ts
        resolved_offset = offset
        resolved_cache_val = current_transformed
        resolved_cache_ts = cache_ts

        if prefer_user and user_val is not None:
            cache_ts = -1.0

        if cache_ts > user_ts:
            resolved_user = current_transformed
            resolved_user_ts = cache_ts
            resolved_offset = resolved_user - base_val
        elif cache_ts < user_ts and user_val is not None:
            resolved_offset = user_val - base_val
            resolved_cache_val = user_val
            resolved_cache_ts = time.time()
        else:
            expected = base_val + offset
            if abs(expected - resolved_user) > self._absolute_tolerance_px:
                resolved_offset = resolved_user - base_val

        norm_span = norm_max - norm_min
        new_min, new_max = self._rebuild_transformed_span(anchor, resolved_cache_val, norm_span, axis)

        return (
            resolved_offset,
            resolved_user,
            resolved_cache_val,
            resolved_cache_ts,
            resolved_user_ts,
            new_min,
            new_max,
        )

    def _sync_absolute_for_current_group(
        self, force_ui: bool = False, debounce_ms: int | None = None, prefer_user: bool = False
    ) -> None:
        if not hasattr(self, "absolute_widget"):
            return
        selection = self._get_current_group_selection()
        if selection is None:
            return
        plugin_name, label = selection

        cfg = self._get_group_config(plugin_name, label)
        offset_x = float(cfg.get("offsetX", 0.0)) if isinstance(cfg, dict) else 0.0
        offset_y = float(cfg.get("offsetY", 0.0)) if isinstance(cfg, dict) else 0.0

        norm_vals, trans_vals, anchor, cache_ts = self._get_cache_entry(plugin_name, label)
        base_norm_min_x = norm_vals["min_x"] - offset_x
        base_norm_max_x = norm_vals["max_x"] - offset_x
        base_norm_min_y = norm_vals["min_y"] - offset_y
        base_norm_max_y = norm_vals["max_y"] - offset_y

        state = self._absolute_user_state.get(selection, {"x": None, "y": None, "x_ts": 0.0, "y_ts": 0.0})
        user_x = state.get("x")
        user_y = state.get("y")
        user_x_ts = float(state.get("x_ts", 0.0) or 0.0)
        user_y_ts = float(state.get("y_ts", 0.0) or 0.0)

        offset_x_res, user_x_res, cache_x_res, cache_ts_x, user_ts_x, new_tx_min, new_tx_max = self._sync_axis(
            anchor,
            base_norm_min_x,
            base_norm_max_x,
            trans_vals["min_x"],
            trans_vals["max_x"],
            offset_x,
            user_x,
            user_x_ts,
            cache_ts,
            "x",
            prefer_user,
        )

        offset_y_res, user_y_res, cache_y_res, cache_ts_y, user_ts_y, new_ty_min, new_ty_max = self._sync_axis(
            anchor,
            base_norm_min_y,
            base_norm_max_y,
            trans_vals["min_y"],
            trans_vals["max_y"],
            offset_y,
            user_y,
            user_y_ts,
            cache_ts,
            "y",
            prefer_user,
        )

        state["x"] = offset_x_res
        state["y"] = offset_y_res
        state["x_ts"] = user_ts_x
        state["y_ts"] = user_ts_y
        self._absolute_user_state[selection] = state

        cfg_changed = (
            abs(offset_x_res - offset_x) > self._absolute_tolerance_px
            or abs(offset_y_res - offset_y) > self._absolute_tolerance_px
        )
        cache_changed = (
            abs(cache_ts_x - cache_ts) > 1e-9
            or abs(cache_ts_y - cache_ts) > 1e-9
            or abs(new_tx_min - trans_vals["min_x"]) > self._absolute_tolerance_px
            or abs(new_tx_max - trans_vals["max_x"]) > self._absolute_tolerance_px
            or abs(new_ty_min - trans_vals["min_y"]) > self._absolute_tolerance_px
            or abs(new_ty_max - trans_vals["max_y"]) > self._absolute_tolerance_px
        )

        if cfg_changed:
            self._set_config_offsets(plugin_name, label, offset_x_res, offset_y_res)
            self._schedule_groupings_config_write(debounce_ms)

        if cache_changed:
            cache_ts_write = max(cache_ts_x, cache_ts_y, time.time())
            trans_vals_update = {
                "min_x": new_tx_min,
                "max_x": new_tx_max,
                "min_y": new_ty_min,
                "max_y": new_ty_max,
            }
            self._update_cache_entry(plugin_name, label, trans_vals_update, anchor, cache_ts_write)
            self._schedule_groupings_cache_write(debounce_ms)

        update_ui = True
        if not update_ui:
            try:
                current_x, current_y = self.absolute_widget.get_px_values()
            except Exception:
                current_x = current_y = None
            if offset_x_res is None:
                if current_x is not None:
                    update_ui = True
            elif current_x is None or abs(current_x - offset_x_res) > self._absolute_tolerance_px:
                update_ui = True
            if offset_y_res is None:
                if current_y is not None:
                    update_ui = True
            elif current_y is None or abs(current_y - offset_y_res) > self._absolute_tolerance_px:
                update_ui = True
        if update_ui:
            self.absolute_widget.set_px_values(offset_x_res, offset_y_res)
        self._draw_preview()

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

    def _enforce_placement_aspect(self) -> None:
        """Keep the placement area near a 4:3 ratio by adjusting height instead of width."""

        if not self._placement_open or self._adjusting_geometry:
            return
        self.update_idletasks()
        sidebar_width = max(self.sidebar_width, self.sidebar.winfo_width())
        min_height = getattr(self, "base_min_height", 420)
        current_height = max(min_height, self.winfo_height() or 0)
        available_height = max(1, current_height - (self.container_pad_vertical * 2))
        placement_width = max(self.placement_min_width, available_height * (4 / 3))
        total_width = (
            self.container_pad_left
            + self.container_pad_right_open
            + sidebar_width
            + self._current_sidebar_pad
            + placement_width
        )
        placement_height = placement_width * (3 / 4)
        target_height = max(min_height, placement_height + (self.container_pad_vertical * 2))
        current_width = max(1, self.winfo_width())
        if abs(target_height - current_height) <= 1 and abs(total_width - current_width) <= 1:
            return
        self._adjusting_geometry = True
        try:
            self.geometry(f"{int(total_width)}x{int(target_height)}")
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
