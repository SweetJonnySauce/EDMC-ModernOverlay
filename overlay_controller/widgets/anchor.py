from __future__ import annotations

import tkinter as tk

from overlay_controller.widgets.common import alt_modifier_active

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
        alt_pressed = alt_modifier_active(self, _event)
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


