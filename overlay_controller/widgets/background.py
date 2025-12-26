from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser
from typing import Callable, Optional

_HEX_DIGITS = set("0123456789ABCDEFabcdef")
_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_COLOR_DIALOG_PATCHED = False


class BackgroundWidget(tk.Frame):
    """Background color + border width editor."""

    def __init__(self, parent, *, min_border: int = 0, max_border: int = 10) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._request_focus: Optional[Callable[[], None]] = None
        self._change_callback: Optional[Callable[[Optional[str], Optional[str], Optional[int]], None]] = None
        self._min_border = min_border
        self._max_border = max_border
        self._color_var = tk.StringVar()
        self._border_color_var = tk.StringVar()
        self._border_var = tk.StringVar(value=str(min_border))
        self._active_field = "color"
        self._enabled = True
        self._picker_open = False
        self._pre_key_state: tuple[tk.Widget, int, int | None, bool] | None = None

        color_row = tk.Frame(self, bd=0, highlightthickness=0, bg=self.cget("background"))
        color_row.pack(fill="x", padx=4, pady=(4, 2))
        color_label = tk.Label(color_row, text="Background color", anchor="w", bg=self.cget("background"))
        color_label.pack(side="left")
        entry = tk.Entry(color_row, textvariable=self._color_var, width=14)
        entry.pack(side="left", padx=(6, 4))
        entry.bind("<Button-1>", lambda _e: self._handle_entry_click("color"), add="+")
        entry.bind("<space>", self._handle_space_exit, add="+")
        entry.bind("<FocusIn>", lambda _e: self._handle_focus_event("color"), add="+")
        entry.bind("<FocusOut>", lambda _e: self._emit_change())
        entry.bind("<KeyRelease>", lambda _e: self._validate_color("color", lazy=True))
        entry.bind("<KeyPress-Left>", lambda e: self._record_pre_key_state(e, -1), add="+")
        entry.bind("<KeyPress-Right>", lambda e: self._record_pre_key_state(e, 1), add="+")
        self._entry = entry
        picker_btn = tk.Button(color_row, text="Pick…", command=lambda: self._handle_picker_click("color"), width=6)
        picker_btn.pack(side="left")
        picker_btn.bind("<FocusIn>", lambda _e: self._handle_focus_event("pick"), add="+")
        picker_btn.bind("<Return>", lambda e: self._handle_picker_keypress("color", e), add="+")
        picker_btn.bind("<KP_Enter>", lambda e: self._handle_picker_keypress("color", e), add="+")
        picker_btn.bind("<space>", lambda e: self._handle_picker_keypress("color", e), add="+")
        self._picker_btn = picker_btn

        border_color_row = tk.Frame(self, bd=0, highlightthickness=0, bg=self.cget("background"))
        border_color_row.pack(fill="x", padx=4, pady=(2, 2))
        border_color_label = tk.Label(
            border_color_row, text="Border color", anchor="w", bg=self.cget("background")
        )
        border_color_label.pack(side="left")
        border_entry = tk.Entry(border_color_row, textvariable=self._border_color_var, width=14)
        border_entry.pack(side="left", padx=(6, 4))
        border_entry.bind("<Button-1>", lambda _e: self._handle_entry_click("border_color"), add="+")
        border_entry.bind("<space>", self._handle_space_exit, add="+")
        border_entry.bind("<FocusIn>", lambda _e: self._handle_focus_event("border_color"), add="+")
        border_entry.bind("<FocusOut>", lambda _e: self._emit_change())
        border_entry.bind("<KeyRelease>", lambda _e: self._validate_color("border_color", lazy=True))
        border_entry.bind("<KeyPress-Left>", lambda e: self._record_pre_key_state(e, -1), add="+")
        border_entry.bind("<KeyPress-Right>", lambda e: self._record_pre_key_state(e, 1), add="+")
        self._border_entry = border_entry
        border_picker_btn = tk.Button(
            border_color_row,
            text="Pick…",
            command=lambda: self._handle_picker_click("border_color"),
            width=6,
        )
        border_picker_btn.pack(side="left")
        border_picker_btn.bind("<FocusIn>", lambda _e: self._handle_focus_event("border_pick"), add="+")
        border_picker_btn.bind("<Return>", lambda e: self._handle_picker_keypress("border_color", e), add="+")
        border_picker_btn.bind("<KP_Enter>", lambda e: self._handle_picker_keypress("border_color", e), add="+")
        border_picker_btn.bind("<space>", lambda e: self._handle_picker_keypress("border_color", e), add="+")
        self._border_picker_btn = border_picker_btn

        border_row = tk.Frame(self, bd=0, highlightthickness=0, bg=self.cget("background"))
        border_row.pack(fill="x", padx=4, pady=(2, 4))
        border_label = tk.Label(border_row, text="Border (px)", anchor="w", bg=self.cget("background"))
        border_label.pack(side="left")
        spin = tk.Spinbox(
            border_row,
            from_=min_border,
            to=max_border,
            width=4,
            textvariable=self._border_var,
            command=self._emit_change,
            repeatdelay=0,
            repeatinterval=0,
        )
        spin.pack(side="left", padx=(6, 4))
        spin.bind("<Button-1>", self._handle_spin_click, add="+")
        spin.bind("<space>", self._handle_space_exit, add="+")
        spin.bind("<FocusIn>", lambda _e: self._handle_focus_event("border"), add="+")
        spin.bind("<FocusOut>", lambda _e: self._emit_change())
        spin.bind("<KeyRelease>", lambda _e: self._emit_change(commit_border=False))
        spin.bind("<KeyPress-Left>", lambda e: self._record_pre_key_state(e, -1), add="+")
        spin.bind("<KeyPress-Right>", lambda e: self._record_pre_key_state(e, 1), add="+")
        self._spin = spin
        self._bind_focus_target(self, None)
        self._bind_focus_target(color_row, "color")
        self._bind_focus_target(color_label, "color")
        self._bind_focus_target(border_color_row, "border_color")
        self._bind_focus_target(border_color_label, "border_color")
        self._bind_focus_target(border_row, "border")
        self._bind_focus_target(border_label, "border")

    def set_focus_request_callback(self, callback: Callable[[], None] | None) -> None:
        self._request_focus = callback

    def set_change_callback(self, callback: Callable[[Optional[str], Optional[str], Optional[int]], None]) -> None:
        self._change_callback = callback

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        try:
            self._entry.configure(state=state)
            self._border_entry.configure(state=state)
            self._spin.configure(state=state)
            self._picker_btn.configure(state=state)
            self._border_picker_btn.configure(state=state)
        except Exception:
            pass

    def set_values(self, color: Optional[str], border_color: Optional[str], border_width: Optional[int]) -> None:
        display = color or ""
        border_display = border_color or ""
        self._color_var.set(display)
        self._border_color_var.set(border_display)
        if border_width is None:
            border_width = self._min_border
        try:
            border_int = max(self._min_border, min(self._max_border, int(border_width)))
        except Exception:
            border_int = self._min_border
        self._border_var.set(str(border_int))
        self._entry.configure(background="white")
        self._border_entry.configure(background="white")

    def on_focus_enter(self) -> None:
        if not self._enabled:
            return
        self._focus_field(self._active_field)

    def on_focus_exit(self) -> None:
        try:
            self.winfo_toplevel().focus_set()
        except Exception:
            pass

    def get_binding_targets(self) -> list[tk.Widget]:  # type: ignore[name-defined]
        return [self._entry, self._border_entry, self._spin]

    def focus_next_field(self, _event: object | None = None) -> str:
        if not self._enabled:
            return "break"
        self._emit_change()
        if self._active_field in ("color", "pick"):
            next_field = "border_color"
        elif self._active_field in ("border_color", "border_pick"):
            next_field = "border"
        else:
            next_field = "color"
        self._focus_field(next_field)
        return "break"

    def focus_previous_field(self, _event: object | None = None) -> str:
        if not self._enabled:
            return "break"
        self._emit_change()
        if self._active_field in ("border",):
            prev_field = "border_color"
        elif self._active_field in ("border_color", "border_pick"):
            prev_field = "color"
        else:
            prev_field = "border"
        self._focus_field(prev_field)
        return "break"

    def handle_key(self, keysym: str, _event: object | None = None) -> bool:
        if not self._enabled:
            return False
        key = keysym.lower()
        if key in {"left", "right"}:
            if not self._should_move_horizontal(_event, 1 if key == "right" else -1):
                return False
            self._move_horizontal(1 if key == "right" else -1)
            return True
        if key in {"return", "kp_enter", "space"} and self._active_field in {"pick", "border_pick"}:
            target = "color" if self._active_field == "pick" else "border_color"
            self._open_color_picker(target)
            return True
        if key in {"down", "return", "kp_enter"}:
            self.focus_next_field()
            return True
        if key == "up":
            self.focus_previous_field()
            return True
        return False

    def focus_set(self) -> None:  # type: ignore[override]
        if not self._enabled:
            return
        self._focus_field(self._active_field)

    def _set_active_field(self, field: str) -> None:
        if field not in ("color", "pick", "border_color", "border_pick", "border"):
            return
        self._active_field = field
        self._pre_key_state = None

    def _focus_field(self, field: str) -> None:
        self._set_active_field(field)
        if field == "color":
            target = self._entry
        elif field == "pick":
            target = self._picker_btn
        elif field == "border_color":
            target = self._border_entry
        elif field == "border_pick":
            target = self._border_picker_btn
        else:
            target = self._spin
        try:
            target.focus_set()
            try:
                if field in ("pick", "border_pick"):
                    return
                if hasattr(target, "select_range"):
                    target.select_range(0, tk.END)
                else:
                    target.selection_range(0, tk.END)
                target.icursor("end")
            except Exception:
                pass
        except Exception:
            pass

    def _handle_focus_event(self, field: str) -> None:
        if not self._enabled:
            return
        self._set_active_field(field)
        if field in ("pick", "border_pick"):
            return
        if field == "color":
            target = self._entry
        elif field == "border_color":
            target = self._border_entry
        else:
            target = self._spin
        try:
            if hasattr(target, "select_range"):
                target.select_range(0, tk.END)
            else:
                target.selection_range(0, tk.END)
            target.icursor("end")
        except Exception:
            pass

    def _handle_entry_click(self, field: str) -> str:
        if not self._enabled:
            return "break"
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        if field not in ("color", "border_color"):
            field = "color"
        self._set_active_field(field)
        self._focus_field(field)
        return "break"

    def _handle_space_exit(self, _event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if not self._enabled:
            return "break"
        try:
            root = self.winfo_toplevel()
        except Exception:
            root = None
        if root is not None:
            handler = getattr(root, "exit_focus_mode", None)
            if callable(handler):
                try:
                    handler()
                except Exception:
                    pass
        return "break"

    def _handle_container_click(self, field: str | None) -> str:
        if not self._enabled:
            return "break"
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        if field:
            self._set_active_field(field)
        self._focus_field(self._active_field)
        return "break"

    def _bind_focus_target(self, widget: tk.Widget, field: str | None) -> None:
        widget.bind("<Button-1>", lambda _e, f=field: self._handle_container_click(f), add="+")

    def _handle_spin_click(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        if not self._enabled:
            return "break"
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        self._set_active_field("border")
        element = None
        try:
            element = self._spin.identify(event.x, event.y)
        except Exception:
            element = None
        if element in {"buttonup", "buttondown"}:
            try:
                self._spin.focus_set()
            except Exception:
                pass
            return None
        self._focus_field("border")
        return "break"

    def _handle_picker_click(self, target: str) -> None:
        if not self._enabled:
            return
        if self._request_focus:
            try:
                self._request_focus()
            except Exception:
                pass
        field = "pick" if target == "color" else "border_pick"
        self._set_active_field(field)
        self._focus_field(field)
        self._open_color_picker(target)

    def _handle_picker_keypress(self, target: str, _event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        self._handle_picker_click(target)
        return "break"

    def _open_color_picker(self, target: str) -> None:
        if self._picker_open:
            return
        self._picker_open = True
        if target == "border_color":
            target_var = self._border_color_var
        else:
            target_var = self._color_var
        original_value = target_var.get()
        try:
            self._ensure_color_dialog_bindings()
            rgb, alpha_value, had_alpha = self._parse_color_value(target_var.get())
            if alpha_value is None:
                alpha_value = 255
            initial = None
            if rgb is not None:
                initial = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
            parent = None
            try:
                parent = self.winfo_toplevel()
            except Exception:
                parent = None
            try:
                picked = colorchooser.askcolor(color=initial, parent=parent)
            except tk.TclError:
                picked = colorchooser.askcolor(parent=parent)
            if picked is None or picked[1] is None:
                target_var.set(original_value)
                return
            hex_value = picked[1].lstrip("#")
            if len(hex_value) != 6 or not all(ch in "0123456789abcdefABCDEF" for ch in hex_value):
                target_var.set(original_value)
                return
            hex_value = hex_value.upper()
            if had_alpha and alpha_value is not None:
                alpha_int = max(0, min(255, int(alpha_value)))
                result = f"#{alpha_int:02X}{hex_value}"
            else:
                result = f"#{hex_value}"
            target_var.set(result)
            self._emit_change()
        finally:
            self._picker_open = False

    def _validate_color(self, field: str, *, lazy: bool = False) -> Optional[str]:
        if field == "border_color":
            target_var = self._border_color_var
            entry = self._border_entry
        else:
            target_var = self._color_var
            entry = self._entry
        raw = target_var.get().strip()
        if not raw:
            entry.configure(background="white")
            return None
        token = self._normalise_color_text(raw)
        if token is None:
            if not lazy:
                entry.configure(background="#ffdddd")
            return None
        entry.configure(background="white")
        return token

    def _emit_change(self, *, commit_border: bool = True) -> None:
        color_value = self._validate_color("color")
        if color_value is None and self._color_var.get().strip():
            return
        border_color_value = self._validate_color("border_color")
        if border_color_value is None and self._border_color_var.get().strip():
            return
        raw_border = self._border_var.get().strip()
        if not raw_border:
            if not commit_border:
                return
            border_value = self._min_border
            self._border_var.set(str(border_value))
        else:
            try:
                border_value = int(raw_border)
            except Exception:
                if not commit_border:
                    return
                border_value = self._min_border
                self._border_var.set(str(border_value))
            else:
                if not commit_border:
                    if border_value < self._min_border or border_value > self._max_border:
                        return
                else:
                    border_value = max(self._min_border, min(self._max_border, border_value))
                    self._border_var.set(str(border_value))
        if self._change_callback is not None:
            self._change_callback(color_value, border_color_value, border_value)

    def _move_horizontal(self, delta: int) -> None:
        order = ("color", "pick", "border_color", "border_pick", "border")
        try:
            idx = order.index(self._active_field)
        except ValueError:
            idx = 0
        next_idx = (idx + delta) % len(order)
        self._focus_field(order[next_idx])

    def _should_move_horizontal(self, event: object | None, delta: int) -> bool:
        if self._active_field in ("pick", "border_pick"):
            return True
        widget = getattr(event, "widget", None) if event is not None else None
        if widget not in (self._entry, self._border_entry, self._spin):
            try:
                widget = self.winfo_toplevel().focus_get()
            except Exception:
                widget = None
        if widget not in (self._entry, self._border_entry, self._spin):
            return False
        pre_state = self._consume_pre_key_state(widget, delta)
        if pre_state is not None:
            pre_insert, pre_selection = pre_state
            if pre_selection or pre_insert is None:
                return False
            try:
                end_idx = int(widget.index(tk.END))
            except Exception:
                return False
            at_edge = pre_insert <= 0 if delta < 0 else pre_insert >= end_idx
            return at_edge
        if self._selection_exists(widget):
            return False
        try:
            insert_idx = int(widget.index(tk.INSERT))
            end_idx = int(widget.index(tk.END))
        except Exception:
            return False
        at_edge = insert_idx <= 0 if delta < 0 else insert_idx >= end_idx
        return at_edge

    def _record_pre_key_state(self, event: tk.Event[tk.Misc], delta: int) -> None:  # type: ignore[name-defined]
        widget = getattr(event, "widget", None)
        if widget not in (self._entry, self._border_entry, self._spin):
            return
        try:
            insert_idx = int(widget.index(tk.INSERT))
        except Exception:
            insert_idx = None
        self._pre_key_state = (widget, delta, insert_idx, self._selection_exists(widget))

    def _consume_pre_key_state(self, widget: tk.Widget, delta: int) -> tuple[int | None, bool] | None:
        state = self._pre_key_state
        self._pre_key_state = None
        if state is None:
            return None
        stored_widget, stored_delta, insert_idx, has_selection = state
        if stored_widget is widget and stored_delta == delta:
            return insert_idx, has_selection
        return None

    @staticmethod
    def _parse_color_value(raw: str) -> tuple[tuple[int, int, int] | None, int | None, bool]:
        token = (raw or "").strip()
        if not token:
            return None, None, False
        if token.startswith("#"):
            token = token[1:]
        if len(token) not in (6, 8):
            return None, None, False
        try:
            if len(token) == 8:
                alpha = int(token[0:2], 16)
                red = int(token[2:4], 16)
                green = int(token[4:6], 16)
                blue = int(token[6:8], 16)
            else:
                red = int(token[0:2], 16)
                green = int(token[2:4], 16)
                blue = int(token[4:6], 16)
        except Exception:
            return None, None, False
        if len(token) == 8:
            return (red, green, blue), alpha, True
        return (red, green, blue), 255, False

    def _ensure_color_dialog_bindings(self) -> None:
        global _COLOR_DIALOG_PATCHED
        if _COLOR_DIALOG_PATCHED:
            return
        try:
            script = r"""
if {![info exists ::edmcoverlay_color_dialog_patched]} {
    if {[llength [info commands ::tk::dialog::color::BuildDialog]] == 0} {
        catch {auto_load ::tk::dialog::color::BuildDialog}
    }
    if {[llength [info commands ::tk::dialog::color::BuildDialog]]} {
        rename ::tk::dialog::color::BuildDialog ::tk::dialog::color::BuildDialog_orig
        proc ::tk::dialog::color::BuildDialog {w} {
            ::tk::dialog::color::BuildDialog_orig $w
            upvar ::tk::dialog::color::[winfo name $w] data
            foreach color {red green blue} {
                set entry $data($color,entry)
                bind $entry <KeyRelease> [list tk::dialog::color::HandleRGBEntry $w]
                bind $entry <FocusOut> [list tk::dialog::color::HandleRGBEntry $w]
            }
            if {[winfo exists $w.top.sel.ent]} {
                bind $w.top.sel.ent <KeyRelease> [list tk::dialog::color::HandleSelEntry $w]
                bind $w.top.sel.ent <FocusOut> [list tk::dialog::color::HandleSelEntry $w]
            }
        }
    }
    set ::edmcoverlay_color_dialog_patched 1
}
"""
            self.tk.eval(script)
        except Exception:
            return
        _COLOR_DIALOG_PATCHED = True

    @staticmethod
    def _normalise_color_text(raw: str) -> Optional[str]:
        token = (raw or "").strip()
        if not token:
            return None
        hex_part = token[1:] if token.startswith("#") else token
        if len(hex_part) in (6, 8) and all(ch in _HEX_DIGITS for ch in hex_part):
            return "#" + hex_part.upper()
        if _NAME_PATTERN.match(token):
            return token
        return None

    @staticmethod
    def _selection_exists(widget: tk.Widget) -> bool:
        try:
            if widget.selection_present():
                return True
        except Exception:
            pass
        try:
            widget.index("sel.first")
            widget.index("sel.last")
            return True
        except tk.TclError:
            return False
        except Exception:
            return False
