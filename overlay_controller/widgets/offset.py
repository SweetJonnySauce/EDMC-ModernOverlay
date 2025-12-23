from __future__ import annotations

import sys
import tkinter as tk

from overlay_controller.widgets.common import alt_modifier_active

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

        return alt_modifier_active(self, event)

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

    def set_pins(self, directions: object | None) -> None:
        """Replace pinned highlights without emitting change callbacks."""

        if not directions:
            new_pins: set[str] = set()
        else:
            new_pins = {str(item).lower() for item in directions if str(item).lower() in {"up", "down", "left", "right"}}
        if "left" in new_pins and "right" in new_pins:
            new_pins.discard("right")
        if "up" in new_pins and "down" in new_pins:
            new_pins.discard("down")
        if new_pins == self._pinned:
            return
        self._pinned = new_pins
        self._apply_arrow_colors()

