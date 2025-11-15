#!/usr/bin/env python3
"""Simple UI to tweak idPrefixGroup anchors."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
GROUPINGS_PATH = ROOT_DIR / "overlay_groupings.json"

ANCHOR_CHOICES: Tuple[str, ...] = ("nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right")


def _load_groupings() -> Dict[str, dict]:
    try:
        raw = json.loads(GROUPINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        messagebox.showerror("Missing File", f"Could not find {GROUPINGS_PATH}")
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        messagebox.showerror("Invalid JSON", f"Failed to parse overlay_groupings.json:\n{exc}")
        raise SystemExit(1)
    if isinstance(raw, dict):
        # Filter out schema metadata entries so we only work with plugin definitions.
        filtered = {name: entry for name, entry in raw.items() if isinstance(entry, dict) and name != "$schema"}
        if not filtered:
            messagebox.showerror("No Groups", "overlay_groupings.json does not contain any idPrefixGroups.")
            raise SystemExit(1)
        return filtered
    messagebox.showerror("Invalid Format", "overlay_groupings.json must contain a JSON object at the root.")
    raise SystemExit(1)


def _write_groupings(data: Dict[str, dict]) -> None:
    GROUPINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class AnchorPointAdjuster(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Anchor Point Adjuster")
        self.resizable(False, False)
        self._data = _load_groupings()
        self._groups = self._build_group_index()
        if not self._groups:
            messagebox.showinfo("No Groups", "No idPrefixGroups defined in overlay_groupings.json.")
            self.destroy()
            return
        self.selected_group: Optional[Dict[str, str]] = None
        self.anchor_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self._build_ui()
        self.after(0, self._load_initial_selection)

    def _build_group_index(self) -> List[Dict[str, str]]:
        groups: List[Dict[str, str]] = []
        for plugin_name, entry in sorted(self._data.items(), key=lambda item: item[0].casefold()):
            block = entry.get("idPrefixGroups")
            if not isinstance(block, dict):
                continue
            for label in sorted(block.keys(), key=str.casefold):
                spec = block[label]
                if not isinstance(spec, dict):
                    continue
                groups.append(
                    {
                        "display": f"{plugin_name} — {label}",
                        "plugin": plugin_name,
                        "group": label,
                    }
                )
        return groups

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="Select idPrefixGroup:").grid(row=0, column=0, sticky="w")

        self.combo = ttk.Combobox(
            container,
            values=[item["display"] for item in self._groups],
            state="readonly",
            width=38,
        )
        self.combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        self.combo.bind("<<ComboboxSelected>>", lambda _event: self._load_selected_group())

        ttk.Label(container, text="Anchor:").grid(row=2, column=0, sticky="w")
        ttk.Label(container, textvariable=self.anchor_var, font=("TkDefaultFont", 12, "bold")).grid(
            row=2, column=1, sticky="e"
        )

        button_row = ttk.Frame(container)
        button_row.grid(row=3, column=0, columnspan=2, pady=(8, 4))
        for child_weight in (0, 1, 2):
            button_row.columnconfigure(child_weight, weight=1)
        ttk.Button(button_row, text="◀ Previous", command=lambda: self._cycle_anchor(-1)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(button_row, text="Next ▶", command=lambda: self._cycle_anchor(1)).grid(row=0, column=1, sticky="ew")

        instructions = (
            "Use the dropdown to pick an idPrefixGroup.\n"
            "Click the arrows or press Left/Right/KP arrow keys to cycle anchors.\n"
            "Changes are applied immediately."
        )
        ttk.Label(container, text=instructions, wraplength=320, justify="left").grid(
            row=4, column=0, columnspan=2, pady=(6, 0), sticky="w"
        )
        ttk.Label(container, textvariable=self.status_var, foreground="#555555").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        for key in ("<Left>", "<Right>", "<KP_Left>", "<KP_Right>"):
            self.bind(key, self._handle_key)

    def _handle_key(self, event) -> None:
        if event.keysym in {"Left", "KP_Left"}:
            self._cycle_anchor(-1)
        elif event.keysym in {"Right", "KP_Right"}:
            self._cycle_anchor(1)

    def _load_initial_selection(self) -> None:
        if not self._groups:
            return
        self.combo.current(0)
        self._load_selected_group()

    def _load_selected_group(self) -> None:
        index = self.combo.current()
        if index < 0 or index >= len(self._groups):
            return
        self.selected_group = self._groups[index]
        current_anchor = self._current_anchor_token()
        self.anchor_var.set(current_anchor)
        self.status_var.set("")

    def _current_anchor_token(self) -> str:
        if not self.selected_group:
            return "nw"
        plugin = self.selected_group["plugin"]
        group_label = self.selected_group["group"]
        entry = self._data.get(plugin, {})
        block = entry.get("idPrefixGroups") if isinstance(entry, dict) else None
        spec = block.get(group_label) if isinstance(block, dict) else None
        token = spec.get("idPrefixGroupAnchor") if isinstance(spec, dict) else None
        if isinstance(token, str) and token.strip():
            cleaned = token.strip().lower()
            if cleaned in ANCHOR_CHOICES:
                return cleaned
        return "nw"

    def _cycle_anchor(self, step: int) -> None:
        if not self.selected_group:
            return
        current = self._current_anchor_token()
        try:
            idx = ANCHOR_CHOICES.index(current)
        except ValueError:
            idx = 0
        next_idx = (idx + step) % len(ANCHOR_CHOICES)
        self._apply_anchor(ANCHOR_CHOICES[next_idx])

    def _apply_anchor(self, anchor: str) -> None:
        if not self.selected_group:
            return
        plugin = self.selected_group["plugin"]
        group_label = self.selected_group["group"]
        entry = self._data.setdefault(plugin, {})
        groups = entry.setdefault("idPrefixGroups", {})
        spec = groups.setdefault(group_label, {})
        spec["idPrefixGroupAnchor"] = anchor
        try:
            _write_groupings(self._data)
        except OSError as exc:
            messagebox.showerror("Write Failed", f"Failed to write overlay_groupings.json:\n{exc}")
            return
        self.anchor_var.set(anchor)
        self.status_var.set(f"Updated {plugin} / {group_label} to anchor '{anchor}'.")


def main() -> None:
    app = AnchorPointAdjuster()
    if app.winfo_exists():
        app.mainloop()


if __name__ == "__main__":
    main()
