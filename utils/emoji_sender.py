#!/usr/bin/env python3
"""Tk helper for sending emoji messages to the overlay."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import tkinter as tk
from tkinter import ttk, messagebox

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from EDMCOverlay import edmcoverlay
except Exception as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(f"Failed to import edmcoverlay shim: {exc}")


DEFAULT_EMOJIS = [
    "📝",  # memo
    "🎯",  # direct hit
    "⚠️",  # warning sign
    "✅",  # check mark
    "🚀",  # rocket
    "💰",  # money bag
    "💀",  # skull
    "🔥",  # fire
    "🛰️",  # satellite
    "🧭",  # compass
    "🧊",  # ice cube
    "🧪",  # test tube
    "🧬",  # dna
    "🧰",  # toolbox
    "🤖",  # robot
    "⚗️",  # alembic
    "⚓",  # anchor
    "⚙️",  # gear
    "⚡",  # high voltage
    "⚔️",  # crossed swords
    "⚖️",  # scales
    "🛡️",  # shield
    "🛠️",  # hammer and wrench
    "🛸",  # flying saucer
    "🧯",  # fire extinguisher
    "🧨",  # firecracker
    "📡",  # satellite antenna
    "🧲",  # magnet
    "🗺️",  # world map
    "🧮",  # abacus
]


@dataclass(frozen=True)
class EmojiChoice:
    index: int
    glyph: str
    name: str
    codepoint: str
    escape: str


def _build_choices(symbols: Iterable[str]) -> List[EmojiChoice]:
    choices: List[EmojiChoice] = []
    for idx, raw in enumerate(symbols, start=1):
        if not raw:
            continue
        glyph = str(raw)[0]
        try:
            name = unicodedata.name(glyph)
        except ValueError:
            name = "UNKNOWN"
        codepoint = f"U+{ord(glyph):04X}"
        escape = f"\\N{{{name}}}" if name != "UNKNOWN" else ""
        choices.append(EmojiChoice(index=idx, glyph=glyph, name=name, codepoint=codepoint, escape=escape))
    return choices


class EmojiSenderApp:
    def __init__(self, choices: List[EmojiChoice], args: argparse.Namespace) -> None:
        self._choices = choices
        self._args = args
        self._overlay: Optional[edmcoverlay.Overlay] = None
        self._selected: EmojiChoice = choices[0]
        self._text_dirty = bool(args.text)

        self._root = tk.Tk()
        self._root.title("Emoji Sender")
        self._root.geometry("960x520")
        self._root.minsize(820, 440)

        self._glyph_var = tk.StringVar(value=self._selected.glyph)
        self._name_var = tk.StringVar(value=self._format_name(self._selected))
        self._code_var = tk.StringVar(value=self._selected.codepoint)
        self._escape_var = tk.StringVar(value=self._selected.escape or "N/A")
        self._text_var = tk.StringVar(value=args.text or self._selected.glyph)
        self._color_var = tk.StringVar(value=args.color)
        self._x_var = tk.StringVar(value=str(args.x))
        self._y_var = tk.StringVar(value=str(args.y))
        self._ttl_var = tk.StringVar(value=str(args.ttl))
        self._id_var = tk.StringVar(value=args.id or "")
        self._size_var = tk.StringVar(value=args.size)
        self._status_var = tk.StringVar(value="Select an emoji and press Send.")

        self._build_ui()
        self._apply_initial_selection(args.emoji)

    @staticmethod
    def _format_name(choice: EmojiChoice) -> str:
        if choice.name == "UNKNOWN":
            return "Unknown emoji"
        return choice.name.title()

    def _build_ui(self) -> None:
        main = ttk.Frame(self._root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        list_frame = ttk.Frame(main)
        list_frame.pack(side=tk.LEFT, fill=tk.Y)

        columns = ("glyph", "name", "code", "escape")
        self._tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=14,
        )
        self._tree.heading("glyph", text="Emoji")
        self._tree.heading("name", text="Name")
        self._tree.heading("code", text="Codepoint")
        self._tree.heading("escape", text="Python")
        self._tree.column("glyph", width=70, minwidth=60, anchor="center")
        self._tree.column("name", width=220, minwidth=180, anchor="w")
        self._tree.column("code", width=110, minwidth=90, anchor="w")
        self._tree.column("escape", width=180, minwidth=140, anchor="w")

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.Y)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._choice_ids: dict[str, EmojiChoice] = {}
        for choice in self._choices:
            iid = str(choice.index)
            self._choice_ids[iid] = choice
            self._tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(choice.glyph, self._format_name(choice), choice.codepoint, choice.escape or "—"),
            )
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.selection_set(str(self._choices[0].index))

        detail = ttk.Frame(main, padding=(10, 0))
        detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail.rowconfigure(2, weight=1)
        detail.columnconfigure(1, weight=1)

        glyph_frame = ttk.Frame(detail)
        glyph_frame.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))
        glyph_label = ttk.Label(glyph_frame, textvariable=self._glyph_var, font=("Segoe UI", 44))
        glyph_label.grid(row=0, column=0, sticky="w")
        ttk.Button(
            glyph_frame,
            text="📋",
            width=3,
            command=lambda: self._copy_field("emoji", self._glyph_var.get()),
        ).grid(row=1, column=0, pady=(6, 0), sticky="w")

        info_frame = ttk.Frame(detail)
        info_frame.grid(row=0, column=1, sticky="nw")
        ttk.Label(info_frame, text="Unicode name:").grid(row=0, column=0, sticky="w", columnspan=2)
        name_entry = ttk.Entry(info_frame, textvariable=self._name_var, state="readonly")
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(info_frame, text="Codepoint:").grid(row=2, column=0, sticky="w")
        code_entry = ttk.Entry(info_frame, textvariable=self._code_var, state="readonly")
        code_entry.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            info_frame,
            text="📋",
            width=3,
            command=lambda: self._copy_field("Codepoint", self._code_var.get()),
        ).grid(row=3, column=1, padx=(6, 0))
        ttk.Label(info_frame, text="Python escape:").grid(row=4, column=0, sticky="w")
        escape_entry = ttk.Entry(info_frame, textvariable=self._escape_var, state="readonly")
        escape_entry.grid(row=5, column=0, sticky="ew")
        ttk.Button(
            info_frame,
            text="📋",
            width=3,
            command=lambda: self._copy_field("Python escape", self._escape_var.get()),
        ).grid(row=5, column=1, padx=(6, 0))
        info_frame.columnconfigure(0, weight=1)

        form = ttk.Frame(detail)
        form.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky="nsew")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Text").grid(row=0, column=0, sticky="w")
        text_entry = ttk.Entry(form, textvariable=self._text_var)
        text_entry.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        text_entry.bind("<KeyRelease>", self._on_text_edit)

        ttk.Label(form, text="Color").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self._color_var).grid(row=1, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(form, text="X").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self._x_var).grid(row=2, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(form, text="Y").grid(row=3, column=0, sticky="w")
        ttk.Entry(form, textvariable=self._y_var).grid(row=3, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(form, text="TTL (s)").grid(row=4, column=0, sticky="w")
        ttk.Entry(form, textvariable=self._ttl_var).grid(row=4, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(form, text="Size").grid(row=5, column=0, sticky="w")
        size_menu = ttk.OptionMenu(
            form,
            self._size_var,
            self._size_var.get(),
            "small",
            "normal",
            "large",
        )
        size_menu.grid(row=5, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(form, text="Payload ID").grid(row=6, column=0, sticky="w")
        ttk.Entry(form, textvariable=self._id_var).grid(row=6, column=1, sticky="ew", padx=(5, 0))

        buttons = ttk.Frame(detail)
        buttons.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Send", command=self._on_send).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(buttons, text="Close", command=self._root.destroy).grid(row=0, column=1, sticky="e")

        status_frame = ttk.Frame(self._root, padding=10)
        status_frame.pack(fill=tk.X)
        ttk.Label(status_frame, textvariable=self._status_var).pack(anchor="w")

    def _apply_initial_selection(self, token: Optional[str]) -> None:
        if not token:
            return
        token = token.strip()
        for idx, choice in enumerate(self._choices):
            if token == choice.glyph or token.lower() == choice.name.lower():
                iid = str(choice.index)
                self._tree.selection_set(iid)
                self._tree.see(iid)
                self._set_choice(choice)
                break

    def _set_choice(self, choice: EmojiChoice) -> None:
        previous = self._selected
        self._selected = choice
        self._glyph_var.set(choice.glyph)
        self._name_var.set(self._format_name(choice))
        self._code_var.set(choice.codepoint)
        self._escape_var.set(choice.escape or "N/A")
        current_text = self._text_var.get()
        if not self._text_dirty or current_text == previous.glyph or not current_text:
            self._text_var.set(choice.glyph)
            self._text_dirty = False
    def _on_tree_select(self, _event) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        choice = self._choice_ids.get(selection[0])
        if choice:
            self._set_choice(choice)

    def _on_text_edit(self, _event) -> None:
        self._text_dirty = True

    def _overlay_client(self) -> edmcoverlay.Overlay:
        if self._overlay is None:
            self._overlay = edmcoverlay.Overlay()
        return self._overlay

    def _on_send(self) -> None:
        text = self._text_var.get().strip()
        if not text:
            messagebox.showerror("Emoji Sender", "Enter text to send.")
            return
        try:
            x_val = int(float(self._x_var.get()))
            y_val = int(float(self._y_var.get()))
            ttl_val = max(0, int(float(self._ttl_var.get())))
        except (TypeError, ValueError):
            messagebox.showerror("Emoji Sender", "X, Y, and TTL must be numeric.")
            return
        payload_id = self._id_var.get().strip() or f"emoji-{self._selected.index}"
        color = self._color_var.get().strip() or "#80d0ff"
        size = self._size_var.get()
        overlay = self._overlay_client()
        try:
            overlay.send_message(payload_id, text, color, x_val, y_val, ttl=ttl_val, size=size)
        except Exception as exc:
            messagebox.showerror("Emoji Sender", f"Failed to send payload: {exc}")
            self._status_var.set("Send failed.")
            return
        suffix = f" {self._selected.escape}" if self._selected.escape else ""
        self._status_var.set(
            f"Sent {self._selected.glyph} ({self._selected.codepoint}{suffix}) as '{text}' with id '{payload_id}'."
        )

    def _copy_field(self, label: str, value: str) -> None:
        if not value or value == "N/A" or value == "—":
            messagebox.showinfo("Emoji Sender", f"No {label.lower()} available to copy.")
            return
        try:
            self._root.clipboard_clear()
            self._root.clipboard_append(value)
        except Exception as exc:
            messagebox.showerror("Emoji Sender", f"Failed to copy {label.lower()}: {exc}")
            return
        self._status_var.set(f"Copied {label.lower()} to clipboard.")

    def run(self) -> None:
        self._root.mainloop()


def _print_choices(choices: Iterable[EmojiChoice]) -> None:
    print(" #  Glyph  Codepoint   Unicode name")
    print("--- -----  ----------  ------------")
    for choice in choices:
        label = choice.name.title() if choice.name != "UNKNOWN" else "Unknown"
        print(f"{choice.index:>2}  {choice.glyph}    {choice.codepoint:<10}  {label}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tk helper for sending emoji payloads to the overlay.")
    parser.add_argument("--emoji", help="Preselect an emoji by glyph or Unicode name.")
    parser.add_argument("--text", help="Preset overlay text (defaults to the emoji glyph).")
    parser.add_argument("--color", default="#80d0ff", help="Text color (default: %(default)s).")
    parser.add_argument("--size", default="normal", choices=("small", "normal", "large"), help="Legacy size label.")
    parser.add_argument("--ttl", type=int, default=8, help="Seconds to keep the message on screen.")
    parser.add_argument("--x", type=int, default=60, help="X coordinate in legacy 1280x960 space.")
    parser.add_argument("--y", type=int, default=120, help="Y coordinate in legacy 1280x960 space.")
    parser.add_argument("--id", help="Optional payload id (default: based on selection).")
    parser.add_argument(
        "--emojis",
        nargs="+",
        help="Override the default emoji list (provide glyphs or \\N{NAME} literals).",
    )
    parser.add_argument("--list", action="store_true", help="List emoji choices and exit.")
    args = parser.parse_args()

    symbols = args.emojis or DEFAULT_EMOJIS
    resolved_symbols: List[str] = []
    for symbol in symbols:
        token = symbol.strip()
        if not token:
            continue
        if token.startswith("\\N{") and token.endswith("}"):
            try:
                resolved_symbols.append(unicodedata.lookup(token[3:-1]))
                continue
            except KeyError:
                raise SystemExit(f"Unknown Unicode name in {token!r}")
        resolved_symbols.append(token)

    choices = _build_choices(resolved_symbols)
    if not choices:
        raise SystemExit("No emoji choices available.")

    if args.list:
        _print_choices(choices)
        return

    app = EmojiSenderApp(choices, args)
    app.run()


if __name__ == "__main__":
    main()
