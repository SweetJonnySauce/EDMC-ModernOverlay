#!/usr/bin/env python3
"""GUI helper for registering plugin group metadata via the overlay API."""
from __future__ import annotations

# ruff: noqa: E402

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from overlay_plugin import overlay_api
from overlay_plugin.overlay_api import PluginGroupingError

_DEFAULT_VALUES = {
    "plugin_group": "Example Plugin",
    "matching_prefixes": "example-\nexample-alt-",
    "id_prefix_group": "status",
    "id_prefixes": "example-status-\nexample-alert-",
    "anchor": "ne",
}


class PluginGroupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Modern Overlay Plugin Group Helper")
        self.resizable(False, False)

        self.path_var = tk.StringVar(value=str(ROOT_DIR / "overlay_groupings.json"))
        self.plugin_var = tk.StringVar(value=_DEFAULT_VALUES["plugin_group"])
        self.id_group_var = tk.StringVar(value=_DEFAULT_VALUES["id_prefix_group"])
        self.anchor_var = tk.StringVar(value=_DEFAULT_VALUES["anchor"])
        self.response_var = tk.StringVar(value="Response: pending")

        self._build_form()

    def _build_form(self) -> None:
        padding = {"padx": 8, "pady": 4}
        container = ttk.Frame(self)
        container.grid(row=0, column=0, sticky="nsew")

        ttk.Label(container, text="overlay_groupings.json path").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(container, textvariable=self.path_var, width=60).grid(row=0, column=1, **padding)

        ttk.Label(container, text="pluginGroup").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(container, textvariable=self.plugin_var, width=40).grid(row=1, column=1, **padding)

        ttk.Label(container, text="matchingPrefixes (one per line)").grid(row=2, column=0, sticky="nw", **padding)
        self.matching_entry = tk.Text(container, width=40, height=4)
        self.matching_entry.grid(row=2, column=1, **padding)
        self.matching_entry.insert("1.0", _DEFAULT_VALUES["matching_prefixes"])

        ttk.Label(container, text="idPrefixGroup").grid(row=3, column=0, sticky="w", **padding)
        ttk.Entry(container, textvariable=self.id_group_var, width=40).grid(row=3, column=1, **padding)

        ttk.Label(container, text="idPrefixes (one per line)").grid(row=4, column=0, sticky="nw", **padding)
        self.id_prefix_entry = tk.Text(container, width=40, height=4)
        self.id_prefix_entry.grid(row=4, column=1, **padding)
        self.id_prefix_entry.insert("1.0", _DEFAULT_VALUES["id_prefixes"])

        ttk.Label(container, text="idPrefixGroupAnchor").grid(row=5, column=0, sticky="w", **padding)
        ttk.Entry(container, textvariable=self.anchor_var, width=20).grid(row=5, column=1, sticky="w", **padding)

        button_row = ttk.Frame(container)
        button_row.grid(row=6, column=0, columnspan=2, sticky="ew", **padding)
        ttk.Button(button_row, text="Submit", command=self._handle_submit).pack(side=tk.LEFT, padx=4)
        ttk.Button(button_row, text="Reset Defaults", command=self._reset_defaults).pack(side=tk.LEFT, padx=4)

        ttk.Label(container, textvariable=self.response_var).grid(row=7, column=0, columnspan=2, sticky="w", **padding)

    def _reset_defaults(self) -> None:
        self.plugin_var.set(_DEFAULT_VALUES["plugin_group"])
        self.id_group_var.set(_DEFAULT_VALUES["id_prefix_group"])
        self.anchor_var.set(_DEFAULT_VALUES["anchor"])
        self.matching_entry.delete("1.0", tk.END)
        self.matching_entry.insert("1.0", _DEFAULT_VALUES["matching_prefixes"])
        self.id_prefix_entry.delete("1.0", tk.END)
        self.id_prefix_entry.insert("1.0", _DEFAULT_VALUES["id_prefixes"])
        self.response_var.set("Response: pending")

    def _handle_submit(self) -> None:
        path = Path(self.path_var.get()).expanduser()
        plugin_group = self.plugin_var.get().strip()
        matching = _split_lines(self.matching_entry.get("1.0", tk.END))
        id_group = self.id_group_var.get().strip() or None
        id_prefixes = _split_lines(self.id_prefix_entry.get("1.0", tk.END))
        anchor = self.anchor_var.get().strip() or None

        overlay_api.register_grouping_store(path)
        try:
            updated = overlay_api.define_plugin_group(
                plugin_group=plugin_group,
                matching_prefixes=matching,
                id_prefix_group=id_group,
                id_prefixes=id_prefixes,
                id_prefix_group_anchor=anchor,
            )
        except PluginGroupingError as exc:
            overlay_api.unregister_grouping_store()
            self.response_var.set(f"Response: 400 (validation error) – {exc}")
            return
        except Exception as exc:
            overlay_api.unregister_grouping_store()
            self.response_var.set(f"Response: 500 (unexpected error) – {exc}")
            return
        else:
            overlay_api.unregister_grouping_store()

        if updated:
            self.response_var.set("Response: 200 (group updated)")
        else:
            self.response_var.set("Response: 204 (no changes)")


def _split_lines(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    tokens = [item.strip() for item in raw.replace(",", "\n").splitlines()]
    entries = [token for token in tokens if token]
    return entries or None


def main() -> int:
    app = PluginGroupApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
