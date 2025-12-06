from __future__ import annotations

import sys
import tkinter as tk


def alt_modifier_active(widget: tk.Misc | None, event: object | None) -> bool:
    """Return True when Alt is genuinely held down, with Windows-friendly detection."""

    state = getattr(event, "state", 0) or 0
    alt_mask = bool(state & 0x0008) or bool(state & 0x20000)
    if sys.platform.startswith("win"):
        try:
            root = widget.winfo_toplevel() if widget is not None else None
        except Exception:
            root = None
        if root is not None and hasattr(root, "_alt_active"):
            if not alt_mask:
                try:
                    root._alt_active = False  # type: ignore[attr-defined]
                except Exception:
                    pass
                return False
            return bool(getattr(root, "_alt_active", False))
    return alt_mask


__all__ = ["alt_modifier_active"]
