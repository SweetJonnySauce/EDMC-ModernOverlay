from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from overlay_controller.widgets.common import alt_modifier_active


class IdPrefixGroupWidget(tk.Frame):
    """Composite control with a dropdown selector (placeholder for future inputs)."""

    def __init__(self, parent: tk.Widget, options: list[str] | None = None) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._choices = options or []
        self._selection = tk.StringVar()
        self._dropdown_posted = False
        self._request_focus: Callable[[], None] | None = None
        self._on_selection_changed: Callable[[str | None], None] | None = None
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
        # Ensure arrow keys stay local to this widget/popdown so we can handle navigation ourselves.
        for seq in ("<Left>", "<Right>", "<Up>", "<Down>"):
            self.dropdown.bind(seq, self._handle_arrow_key, add="+")
            for class_name in block_classes:
                try:
                    self.dropdown.bind_class(class_name, seq, self._handle_arrow_key, add="+")
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

    def update_options(self, options: list[str], selected_index: int | None = None) -> None:
        """Replace dropdown options and apply selection if provided."""

        self._choices = options or []
        try:
            self.dropdown.configure(values=self._choices)
        except Exception:
            pass
        if selected_index is not None and 0 <= selected_index < len(self._choices):
            try:
                self.dropdown.current(selected_index)
            except Exception:
                selected_index = None
        if selected_index is None:
            try:
                self._selection.set("")
                self.dropdown.set("")
            except Exception:
                pass

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

    def _sync_dropdown_selection(self, index: int) -> None:
        """Best-effort highlight sync for the ttk popdown listbox."""

        try:
            popdown = self.dropdown.tk.call("ttk::combobox::PopdownWindow", self.dropdown)
            listbox = f"{popdown}.f.l"
            exists = bool(int(self.dropdown.tk.call("winfo", "exists", listbox)))
            if not exists:
                return
            self.dropdown.tk.call(listbox, "selection", "clear", 0, "end")
            self.dropdown.tk.call(listbox, "selection", "set", index)
            self.dropdown.tk.call(listbox, "activate", index)
            self.dropdown.tk.call(listbox, "see", index)
        except Exception:
            return

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
        try:
            self.dropdown.current(target_index)
            self.dropdown.event_generate("<<ComboboxSelected>>")
            self._sync_dropdown_selection(target_index)
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

    def set_focus_request_callback(self, callback: Callable[[], None] | None) -> None:
        """Register a callback that requests host focus when a control is clicked."""

        self._request_focus = callback

    def set_selection_change_callback(self, callback: Callable[[str | None], None] | None) -> None:
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
        self._dropdown_posted = False

    def _post_dropdown(self) -> None:
        """Open the combobox dropdown without synthesizing key events."""

        try:
            self.dropdown.tk.call("ttk::combobox::Post", self.dropdown)
            self._dropdown_posted = True
            try:
                popdown = self.dropdown.tk.call("ttk::combobox::PopdownWindow", self.dropdown)
                listbox = f"{popdown}.f.l"
                exists = bool(int(self.dropdown.tk.call("winfo", "exists", listbox)))
                if exists:
                    current = self.dropdown.current()
                    self.dropdown.tk.call(listbox, "activate", current)
                    self.dropdown.tk.call("focus", listbox)
            except Exception:
                pass
            try:
                self.update_idletasks()
            except Exception:
                pass
        except Exception:
            pass

    def _navigate(self, step: int) -> bool:
        """Advance selection and sync an open dropdown listbox if present."""

        changed = self._advance_selection(step)
        if changed:
            try:
                current = int(self.dropdown.current())
            except Exception:
                current = None
            if current is not None:
                self._sync_dropdown_selection(current)
        return changed

    def handle_key(self, keysym: str, event: tk.Event[tk.Misc] | None = None) -> str | None:  # type: ignore[name-defined]
        """Process keys while this widget has focus mode active."""

        if alt_modifier_active(self, event):
            return "break"

        key = keysym.lower()
        if key == "left":
            self._advance_selection(-1)
            return "break"
        elif key == "right":
            self._advance_selection(1)
            return "break"
        elif key == "down":
            if not self._is_dropdown_open():
                if self._dropdown_posted:
                    self._dropdown_posted = False
                    self._navigate(1)
                    return "break"
                else:
                    self._post_dropdown()
                    return "break"
            self._dropdown_posted = False
            self._navigate(1)
            return "break"
        elif key == "up":
            self._navigate(-1)
            return "break"
        elif key in {"return", "space"}:
            try:
                if self._is_dropdown_open():
                    focus_target = self.dropdown.tk.call("focus")
                    if focus_target:
                        self.dropdown.tk.call("event", "generate", focus_target, "<Return>")
                    else:
                        self.dropdown.event_generate("<Return>")
                else:
                    self.dropdown.event_generate("<Return>")
            except Exception:
                pass
            return "break"
        return None

    def _handle_arrow_key(self, event: tk.Event[tk.Misc]) -> str | None:  # type: ignore[name-defined]
        """Capture arrow keys while focused to avoid bubbling to parent bindings."""

        return self.handle_key(event.keysym, event)


__all__ = ["IdPrefixGroupWidget"]
