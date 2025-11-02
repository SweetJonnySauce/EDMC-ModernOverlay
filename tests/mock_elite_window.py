#!/usr/bin/env python3
"""Spawn a mock Elite Dangerous game window for local overlay testing."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tkinter as tk

DEFAULT_TITLE = "Elite - Dangerous (Stub)"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "overlay_settings.json"
ENV_WIDTH = "MOCK_ELITE_WIDTH"
ENV_HEIGHT = "MOCK_ELITE_HEIGHT"
def _parse_size_token(token: str) -> tuple[int, int]:
    parts = token.lower().replace("x", " ").split()
    if len(parts) != 2:
        raise ValueError(f"Invalid size token '{token}'. Expected WIDTHxHEIGHT.")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive integers.")
    return width, height


def _load_settings(path: str | None) -> tuple[int | None, int | None]:
    """Best-effort overlay_settings.json reader."""
    if not path:
        return None, None
    try:
        settings_path = Path(path).expanduser().resolve()
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    width = data.get("mock_window_width")
    height = data.get("mock_window_height")
    try:
        width_val = int(width) if width is not None else None
        height_val = int(height) if height is not None else None
    except (TypeError, ValueError):
        return None, None
    return width_val, height_val


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a simple 1280x720 window whose title matches the overlay tracker.",
    )
    parser.add_argument(
        "--title",
        default=DEFAULT_TITLE,
        help="Window title to advertise to the overlay (default: %(default)s)",
    )
    parser.add_argument(
        "--size",
        metavar="WIDTHxHEIGHT",
        help="Shorthand for --width/--height (e.g. 1920x1080).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help=f"Window width in pixels (default: {DEFAULT_WIDTH})",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help=f"Window height in pixels (default: {DEFAULT_HEIGHT})",
    )
    parser.add_argument(
        "--x",
        type=int,
        default=None,
        help="Optional X (left) screen offset in pixels",
    )
    parser.add_argument(
        "--y",
        type=int,
        default=None,
        help="Optional Y (top) screen offset in pixels",
    )
    parser.add_argument(
        "--wm-class",
        dest="wm_class",
        metavar="NAME[:CLASS]",
        default=None,
        help="Override the WM_CLASS/instance for X11 compositors (e.g. 'Elite:Elite.Dangerous').",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS_PATH),
        help="Optional settings file to read mock_window_width/mock_window_height defaults "
        "(default: %(default)s relative to script).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings_width, settings_height = _load_settings(args.settings)

    width = settings_width or DEFAULT_WIDTH
    height = settings_height or DEFAULT_HEIGHT

    env_width = os.getenv(ENV_WIDTH)
    env_height = os.getenv(ENV_HEIGHT)
    if env_width:
        try:
            width = int(env_width)
        except ValueError:
            parser.error(f"Invalid {ENV_WIDTH} value '{env_width}'.")
    if env_height:
        try:
            height = int(env_height)
        except ValueError:
            parser.error(f"Invalid {ENV_HEIGHT} value '{env_height}'.")

    if args.size:
        try:
            width, height = _parse_size_token(args.size)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        if args.width is not None:
            width = args.width
        if args.height is not None:
            height = args.height

    if width <= 0 or height <= 0:
        parser.error("Width and height must be positive integers.")

    root = tk.Tk()
    root.title(args.title)

    # Apply optional WM_CLASS metadata on X11 so tools like wmctrl/xprop see a useful class name.
    if args.wm_class:
        instance, _, class_name = args.wm_class.partition(":")
        class_name = class_name or instance
        try:
            root.tk.call("wm", "class", root._w, class_name)
            root.tk.call("tk", "appname", instance)
        except tk.TclError:
            # Ignore failures; window matching still works via title.
            pass

    geometry = f"{width}x{height}"
    if args.x is not None and args.y is not None:
        geometry += f"+{args.x}+{args.y}"
    root.geometry(geometry)

    root.minsize(width, height)
    root.configure(background="black")

    def _aspect_ratio_label(w: int, h: int) -> str:
        if w <= 0 or h <= 0:
            return ""
        ratio = w / float(h)
        known = [
            (32 / 9, "32:9"),
            (21 / 9, "21:9"),
            (18 / 9, "18:9"),
            (16 / 10, "16:10"),
            (16 / 9, "16:9"),
            (4 / 3, "4:3"),
            (5 / 4, "5:4"),
            (1.0, "1:1"),
        ]
        for target, label in known:
            if target > 0 and abs(ratio - target) / target < 0.03:
                return label
        from math import gcd

        d = gcd(w, h)
        return f"{w // d}:{h // d}"

    aspect = _aspect_ratio_label(width, height)
    ratio_text = f" ({aspect})" if aspect else ""

    info = tk.Label(
        root,
        text=f"{args.title}\n{width}x{height}{ratio_text}",
        fg="#FFA500",
        bg="black",
        font=("Helvetica", 16, "bold"),
    )
    info.pack(expand=True, fill="both")

    root.mainloop()


if __name__ == "__main__":
    main()
