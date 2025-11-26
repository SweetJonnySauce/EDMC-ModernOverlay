"""Helpers for drawing selection highlights around Tk widgets."""

from __future__ import annotations

import tkinter as tk


class SelectionOverlay:
    """Reusable highlight frame that can wrap any widget."""

    def __init__(
        self,
        parent: tk.Widget,
        padding: int,
        border_width: int,
        corner_radius: int | None = None,
    ) -> None:
        self._parent = parent
        self._padding = padding
        self._border_width = border_width
        computed_radius = max(8, padding * 2)
        if corner_radius is None:
            self._corner_radius = computed_radius
        else:
            self._corner_radius = max(0, corner_radius)
        self._frame = tk.Frame(
            parent,
            bd=0,
            highlightthickness=0,
            background=parent.cget("background"),
        )
        self._canvas = tk.Canvas(
            self._frame,
            bd=0,
            highlightthickness=0,
            background=parent.cget("background"),
        )
        self._canvas.pack(fill="both", expand=True)

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
        self._canvas.configure(
            background=self._parent.cget("background"),
            width=overlay_width,
            height=overlay_height,
        )
        self._draw_rounded_outline(overlay_width, overlay_height, outline_color)
        self._frame.lift()
        target.lift(self._frame)

    def _draw_rounded_outline(self, width: int, height: int, color: str) -> None:
        """Draw a rounded rectangle outline to act as the selection highlight."""

        self._canvas.delete("all")
        bw = max(1, self._border_width)
        x1 = bw / 2
        y1 = bw / 2
        x2 = width - bw / 2
        y2 = height - bw / 2

        max_radius = max(0.0, min((x2 - x1) / 2, (y2 - y1) / 2))
        radius = min(float(self._corner_radius), max_radius)
        if radius <= 0:
            self._canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=bw)
            return

        # Arcs for corners
        self._canvas.create_arc(
            x1,
            y1,
            x1 + 2 * radius,
            y1 + 2 * radius,
            start=90,
            extent=90,
            style="arc",
            outline=color,
            width=bw,
        )
        self._canvas.create_arc(
            x2 - 2 * radius,
            y1,
            x2,
            y1 + 2 * radius,
            start=0,
            extent=90,
            style="arc",
            outline=color,
            width=bw,
        )
        self._canvas.create_arc(
            x2 - 2 * radius,
            y2 - 2 * radius,
            x2,
            y2,
            start=270,
            extent=90,
            style="arc",
            outline=color,
            width=bw,
        )
        self._canvas.create_arc(
            x1,
            y2 - 2 * radius,
            x1 + 2 * radius,
            y2,
            start=180,
            extent=90,
            style="arc",
            outline=color,
            width=bw,
        )

        # Connect the arcs with straight segments.
        self._canvas.create_line(
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            fill=color,
            width=bw,
            capstyle="round",
            joinstyle="round",
        )
        self._canvas.create_line(
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            fill=color,
            width=bw,
            capstyle="round",
            joinstyle="round",
        )
        self._canvas.create_line(
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            fill=color,
            width=bw,
            capstyle="round",
            joinstyle="round",
        )
        self._canvas.create_line(
            x1,
            y1 + radius,
            x1,
            y2 - radius,
            fill=color,
            width=bw,
            capstyle="round",
            joinstyle="round",
        )
