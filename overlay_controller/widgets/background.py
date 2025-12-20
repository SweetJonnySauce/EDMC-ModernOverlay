from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser
from typing import Callable, Optional

_HEX_PATTERN = re.compile(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


class BackgroundWidget(tk.Frame):
    """Background color + border width editor."""

    def __init__(self, parent, *, min_border: int = 0, max_border: int = 10) -> None:
        super().__init__(parent, bd=0, highlightthickness=0)
        self._change_callback: Optional[Callable[[Optional[str], Optional[int]], None]] = None
        self._min_border = min_border
        self._max_border = max_border
        self._color_var = tk.StringVar()
        self._border_var = tk.StringVar(value=str(min_border))

        color_row = tk.Frame(self, bd=0, highlightthickness=0)
        color_row.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(color_row, text="Background (hex)", anchor="w").pack(side="left")
        entry = tk.Entry(color_row, textvariable=self._color_var, width=14)
        entry.pack(side="left", padx=(6, 4))
        entry.bind("<FocusOut>", lambda _e: self._emit_change())
        entry.bind("<KeyRelease>", lambda _e: self._validate_color(lazy=True))
        self._entry = entry
        picker_btn = tk.Button(color_row, text="Pick…", command=self._open_color_picker, width=6)
        picker_btn.pack(side="left")
        self._picker_btn = picker_btn

        border_row = tk.Frame(self, bd=0, highlightthickness=0)
        border_row.pack(fill="x", padx=4, pady=(2, 4))
        tk.Label(border_row, text="Border (px)", anchor="w").pack(side="left")
        spin = tk.Spinbox(
            border_row,
            from_=min_border,
            to=max_border,
            width=4,
            textvariable=self._border_var,
            command=self._emit_change,
        )
        spin.pack(side="left", padx=(6, 4))
        spin.bind("<FocusOut>", lambda _e: self._emit_change())
        spin.bind("<KeyRelease>", lambda _e: self._emit_change())
        self._spin = spin

    def set_focus_request_callback(self, callback: Callable[[int], None]) -> None:
        # Sidebar focus support; noop placeholder for parity with other widgets.
        self._focus_request = callback

    def set_change_callback(self, callback: Callable[[Optional[str], Optional[int]], None]) -> None:
        self._change_callback = callback

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            self._entry.configure(state=state)
            self._spin.configure(state=state)
            self._picker_btn.configure(state=state)
        except Exception:
            pass

    def set_values(self, color: Optional[str], border_width: Optional[int]) -> None:
        display = color or ""
        self._color_var.set(display)
        if border_width is None:
            border_width = self._min_border
        try:
            border_int = max(self._min_border, min(self._max_border, int(border_width)))
        except Exception:
            border_int = self._min_border
        self._border_var.set(str(border_int))
        self._entry.configure(background="white")

    def _open_color_picker(self) -> None:
        current = self._color_var.get().strip()
        initial = current if _HEX_PATTERN.match(current) else None
        picked = colorchooser.askcolor(color=initial)
        if picked is None or picked[1] is None:
            return
        hex_value = picked[1]
        self._color_var.set(hex_value.upper())
        self._emit_change()

    def _validate_color(self, *, lazy: bool = False) -> Optional[str]:
        raw = self._color_var.get().strip()
        if not raw:
            self._entry.configure(background="white")
            return None
        if not raw.startswith("#"):
            raw = "#" + raw
        if not _HEX_PATTERN.match(raw):
            if not lazy:
                self._entry.configure(background="#ffdddd")
            return None
        self._entry.configure(background="white")
        return raw.upper()

    def _emit_change(self) -> None:
        color_value = self._validate_color()
        if color_value is None and self._color_var.get().strip():
            return
        try:
            border_value = int(self._border_var.get())
        except Exception:
            border_value = self._min_border
        border_value = max(self._min_border, min(self._max_border, border_value))
        self._border_var.set(str(border_value))
        if self._change_callback is not None:
            self._change_callback(color_value, border_value)
