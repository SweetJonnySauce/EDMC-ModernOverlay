"""Helpers for drawing selection highlights around Tk widgets."""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class SelectionOverlay:
    """Reusable highlight frame that can wrap any widget."""

    def __init__(self, parent: tk.Widget, padding: int, border_width: int) -> None:
        self._parent = parent
        self._padding = padding
        self._border_width = border_width
        self._frame = tk.Frame(
            parent,
            bd=0,
            highlightthickness=0,
            background=parent.cget("background"),
        )

    def hide(self) -> None:
        """Hide the overlay frame."""

        self._frame.place_forget()

    def show(self, target: tk.Widget, outline_color: str) -> None:
        """Wrap the given widget with the overlay highlight."""

        target.update_idletasks()
        width = target.winfo_width()
        height = target.winfo_height()
        x = target.winfo_x()
        y = target.winfo_y()

        pad = self._padding
        overlay_width = max(width + (pad * 2), self._border_width * 2)
        overlay_height = max(height + (pad * 2), self._border_width * 2)
        self._frame.configure(background=self._parent.cget("background"))
        self._frame.place(x=x - pad, y=y - pad, width=overlay_width, height=overlay_height)
        self._frame.configure(
            highlightthickness=self._border_width,
            highlightbackground=outline_color,
            highlightcolor=outline_color,
            bd=0,
        )
        self._frame.tkraise()
        target.tkraise(self._frame)
