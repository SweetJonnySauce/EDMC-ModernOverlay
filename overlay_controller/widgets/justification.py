from __future__ import annotations

import tkinter as tk

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


