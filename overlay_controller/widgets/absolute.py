from __future__ import annotations

import tkinter as tk

ABS_BASE_WIDTH = 1280
ABS_BASE_HEIGHT = 960

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
