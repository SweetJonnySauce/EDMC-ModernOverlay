from __future__ import annotations

import tkinter as tk

class SidebarTipHelper(tk.Frame):
    """Lightweight helper that shows context-aware tips for the sidebar widgets."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bd=0, highlightthickness=0, bg=parent.cget("background"))
        self._default_primary = "Handy tips will show up here in the future."
        self._primary_var = tk.StringVar(value=self._default_primary)
        self._secondary_var = tk.StringVar(value="")

        primary = tk.Label(
            self,
            textvariable=self._primary_var,
            justify="left",
            anchor="nw",
            wraplength=220,
            padx=6,
            pady=4,
            bg=self.cget("background"),
            fg="#1f1f1f",
        )
        secondary = tk.Label(
            self,
            textvariable=self._secondary_var,
            justify="left",
            anchor="nw",
            wraplength=220,
            padx=6,
            pady=2,
            bg=self.cget("background"),
            fg="#555555",
            font=("TkDefaultFont", 8),
        )

        primary.pack(fill="x")
        secondary.pack(fill="x")

    def set_context(self, primary: str | None = None, secondary: str | None = None) -> None:
        self._primary_var.set(primary or self._default_primary)
        self._secondary_var.set(secondary or "")


