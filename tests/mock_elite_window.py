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
DEFAULT_HEIGHT = 960
DEFAULT_SCALE_MODE = "fill"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "overlay_settings.json"
ENV_WIDTH = "MOCK_ELITE_WIDTH"
ENV_HEIGHT = "MOCK_ELITE_HEIGHT"
BASE_WIDTH = float(DEFAULT_WIDTH)
BASE_HEIGHT = float(DEFAULT_HEIGHT)
VALID_SCALE_MODES = {"fit", "fill"}

def _parse_size_token(token: str) -> tuple[int, int]:
    parts = token.lower().replace("x", " ").split()
    if len(parts) != 2:
        raise ValueError(f"Invalid size token '{token}'. Expected WIDTHxHEIGHT.")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive integers.")
    return width, height


def _load_settings(path: str | None) -> tuple[int | None, int | None, str | None]:
    """Best-effort overlay_settings.json reader."""
    if not path:
        return None, None, None
    try:
        settings_path = Path(path).expanduser().resolve()
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None
    width = data.get("mock_window_width")
    height = data.get("mock_window_height")
    scale_mode_raw = data.get("scale_mode")
    try:
        width_val = int(width) if width is not None else None
        height_val = int(height) if height is not None else None
    except (TypeError, ValueError):
        return None, None, None
    if isinstance(scale_mode_raw, str):
        scale_mode_val = scale_mode_raw.strip().lower() or None
    else:
        scale_mode_val = None
    return width_val, height_val, scale_mode_val


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a simple 1280x960 window whose title matches the overlay tracker.",
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
    parser.add_argument(
        "--payload-label",
        dest="payload_label",
        default="",
        help="Optional label describing the active payload (displayed near the top of the window).",
    )
    parser.add_argument(
        "--label-file",
        dest="label_file",
        default="",
        help="Optional path to a text file whose contents should be mirrored in the payload label.",
    )
    parser.add_argument(
        "--crosshair-x",
        type=float,
        default=None,
        help="Optional horizontal crosshair position as a percentage (0-100).",
    )
    parser.add_argument(
        "--crosshair-y",
        type=float,
        default=None,
        help="Optional vertical crosshair position as a percentage (0-100).",
    )
    parser.add_argument(
        "--scale-mode",
        dest="scale_mode",
        choices=sorted(VALID_SCALE_MODES),
        default=None,
        help="Scale mode used by the overlay client when mapping legacy coordinates (default: from settings.json or fill).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings_width, settings_height, settings_scale_mode = _load_settings(args.settings)

    width = settings_width or DEFAULT_WIDTH
    height = settings_height or DEFAULT_HEIGHT
    initial_scale_mode = args.scale_mode or settings_scale_mode or DEFAULT_SCALE_MODE
    if initial_scale_mode not in VALID_SCALE_MODES:
        initial_scale_mode = DEFAULT_SCALE_MODE

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
        from math import gcd

        d = gcd(w, h)
        simplified_w = w // d
        simplified_h = h // d
        known_exact = {
            (32, 9): "32:9",
            (21, 9): "21:9",
            (18, 9): "18:9",
            (16, 10): "16:10",
            (16, 9): "16:9",
            (12, 5): "12:5",
            (4, 3): "4:3",
            (5, 4): "5:4",
            (3, 2): "3:2",
            (1, 1): "1:1",
        }
        exact_label = known_exact.get((simplified_w, simplified_h))
        if exact_label:
            return exact_label
        known = [
            (32 / 9, "32:9"),
            (21 / 9, "21:9"),
            (18 / 9, "18:9"),
            (16 / 10, "16:10"),
            (16 / 9, "16:9"),
            (12 / 5, "12:5"),
            (4 / 3, "4:3"),
            (5 / 4, "5:4"),
            (1.0, "1:1"),
        ]
        for target, label in known:
            if target > 0 and abs(ratio - target) / target < 0.03:
                return label
        return f"{w // d}:{h // d}"

    overlay = tk.Canvas(root, highlightthickness=0, bd=0, bg=root.cget("bg"))
    overlay.pack(expand=True, fill="both")

    payload_var = tk.StringVar(value=str(args.payload_label or "").strip())
    cursor_label_id: int | None = None
    logical_cursor_label_id: int | None = None
    transform_state = {
        "scale": 1.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "base_offset_x": 0.0,
        "base_offset_y": 0.0,
    }
    cursor_state = {"x": None, "y": None}
    scale_mode_state = {"value": initial_scale_mode}
    settings_watch = {
        "path": Path(args.settings).expanduser().resolve() if not args.scale_mode else None,
        "mtime": None,
    }

    def _overlay_to_canvas(x_overlay: float, y_overlay: float) -> tuple[float, float]:
        scale = transform_state.get("scale", 1.0)
        if scale <= 0:
            scale = 1.0
        base_offset_x = transform_state.get("base_offset_x", 0.0)
        base_offset_y = transform_state.get("base_offset_y", 0.0)
        return x_overlay * scale + base_offset_x, y_overlay * scale + base_offset_y

    def _canvas_to_logical(x_canvas: float, y_canvas: float) -> tuple[float, float]:
        scale = transform_state.get("scale", 1.0)
        if scale <= 0:
            scale = 1.0
        base_offset_x = transform_state.get("base_offset_x", 0.0)
        base_offset_y = transform_state.get("base_offset_y", 0.0)
        logical_x = (x_canvas - base_offset_x) / scale
        logical_y = (y_canvas - base_offset_y) / scale
        return logical_x, logical_y

    if settings_watch["path"] is not None:
        try:
            settings_watch["mtime"] = settings_watch["path"].stat().st_mtime
        except OSError:
            settings_watch["mtime"] = None

    def _format_cursor_text(overlay_x: float | None, overlay_y: float | None) -> str:
        if overlay_x is None or overlay_y is None:
            return "Overlay cursor: x=--, y=--"
        return f"Overlay cursor: x={overlay_x:.1f}, y={overlay_y:.1f}"

    def _format_logical_cursor_text(logical_x: float | None, logical_y: float | None) -> str:
        if logical_x is None or logical_y is None:
            return "Logical cursor: x=--, y=--"
        return f"Logical cursor: x={logical_x:.1f}, y={logical_y:.1f}"

    def _reset_cursor_label(*_) -> None:
        cursor_state["x"] = None
        cursor_state["y"] = None
        if cursor_label_id is not None:
            overlay.itemconfigure(cursor_label_id, text=_format_cursor_text(None, None))
        if logical_cursor_label_id is not None:
            overlay.itemconfigure(logical_cursor_label_id, text=_format_logical_cursor_text(None, None))

    def _update_cursor_label(event=None) -> None:
        if event is not None:
            cursor_state["x"] = float(event.x)
            cursor_state["y"] = float(event.y)
        canvas_x = cursor_state["x"]
        canvas_y = cursor_state["y"]
        text = _format_cursor_text(None, None)
        logical_text = _format_logical_cursor_text(None, None)
        if canvas_x is not None and canvas_y is not None:
            scale = transform_state.get("scale", 1.0)
            if scale <= 0:
                scale = 1.0
            offset_x = transform_state.get("offset_x", 0.0)
            offset_y = transform_state.get("offset_y", 0.0)
            base_offset_x = transform_state.get("base_offset_x", 0.0)
            base_offset_y = transform_state.get("base_offset_y", 0.0)
            if scale_mode_state["value"] == "fit":
                overlay_x = (canvas_x - offset_x) / scale
                overlay_y = (canvas_y - offset_y) / scale
            else:
                overlay_x = canvas_x
                overlay_y = canvas_y
            text = _format_cursor_text(overlay_x, overlay_y)
            logical_x = (canvas_x - base_offset_x) / scale
            logical_y = (canvas_y - base_offset_y) / scale
            logical_text = _format_logical_cursor_text(logical_x, logical_y)
        if cursor_label_id is not None:
            overlay.itemconfigure(cursor_label_id, text=text)
        if logical_cursor_label_id is not None:
            overlay.itemconfigure(logical_cursor_label_id, text=logical_text)

    overlay.bind("<Motion>", _update_cursor_label, add="+")
    overlay.bind("<Leave>", _reset_cursor_label, add="+")

    def _refresh_scale_mode_from_settings() -> bool:
        path = settings_watch["path"]
        if path is None:
            return False
        try:
            stat_result = path.stat()
        except OSError:
            return False
        mtime = stat_result.st_mtime
        if settings_watch["mtime"] is not None and mtime <= settings_watch["mtime"]:
            return False
        settings_watch["mtime"] = mtime
        _, _, new_mode = _load_settings(str(path))
        if new_mode in VALID_SCALE_MODES and new_mode != scale_mode_state["value"]:
            scale_mode_state["value"] = new_mode
            return True
        return False

    def _poll_scale_mode() -> None:
        changed = _refresh_scale_mode_from_settings()
        if changed:
            _redraw_overlay()
        root.after(500, _poll_scale_mode)

    def _redraw_overlay(event=None) -> None:
        nonlocal cursor_label_id, logical_cursor_label_id
        _refresh_scale_mode_from_settings()
        active_mode = scale_mode_state["value"]
        width = max(root.winfo_width(), 1)
        height = max(root.winfo_height(), 1)
        overlay.configure(width=width, height=height)
        overlay.delete("all")

        width_f = float(width)
        height_f = float(height)

        if active_mode == "fit":
            scale = min(width_f / BASE_WIDTH, height_f / BASE_HEIGHT)
            scaled_w = BASE_WIDTH * scale
            scaled_h = BASE_HEIGHT * scale
            offset_x = (width_f - scaled_w) / 2.0
            offset_y = (height_f - scaled_h) / 2.0
            base_offset_x = offset_x
            base_offset_y = offset_y
        else:
            scale = max(width_f / BASE_WIDTH, height_f / BASE_HEIGHT)
            scaled_w = BASE_WIDTH * scale
            scaled_h = BASE_HEIGHT * scale
            offset_x = 0.0
            offset_y = 0.0
            base_offset_x = 0.0
            base_offset_y = 0.0
        if scale <= 0:
            scale = 1.0
        transform_state["scale"] = scale
        transform_state["offset_x"] = offset_x
        transform_state["offset_y"] = offset_y
        transform_state["base_offset_x"] = base_offset_x
        transform_state["base_offset_y"] = base_offset_y

        cursor_label_id = overlay.create_text(
            10,
            10,
            text=_format_cursor_text(None, None),
            fill="#FFA500",
            font=("Helvetica", 12, "bold"),
            anchor="nw",
            tags=("label", "label-cursor"),
        )
        if active_mode == "fill":
            logical_cursor_label_id = overlay.create_text(
                10,
                28,
                text=_format_logical_cursor_text(None, None),
                fill="#FFA500",
                font=("Helvetica", 12, "bold"),
                anchor="nw",
                tags=("label", "label-cursor-logical"),
            )
        else:
            logical_cursor_label_id = None

        aspect = _aspect_ratio_label(width, height)
        ratio_text = f" ({aspect})" if aspect else ""
        info_text = f"{args.title}\n{width}x{height}{ratio_text}\nmode: {active_mode.upper()}"
        info_id = overlay.create_text(
            width / 2,
            20,
            text=info_text,
            fill="#FFA500",
            font=("Helvetica", 16, "bold"),
            anchor="n",
            tags=("label", "label-info"),
        )

        payload_text = payload_var.get().strip()
        payload_y = 80  # fallback spacing if bbox lookup fails
        bbox = overlay.bbox(info_id)
        if bbox:
            payload_y = bbox[3] + 30
        if payload_text:
            overlay.create_text(
                width / 2,
                payload_y,
                text=payload_text,
                fill="#00AAFF",
                font=("Helvetica", 18, "bold"),
                anchor="n",
                tags=("label", "label-payload"),
            )

        if args.crosshair_x is not None:
            x_percent = max(0.0, min(100.0, float(args.crosshair_x))) / 100.0
            x_canvas = x_percent * width_f
            logical_x, _ = _canvas_to_logical(x_canvas, 0.0)
            x_pos = int(round(x_canvas))
            overlay.create_line(
                x_pos,
                0,
                x_pos,
                height,
                fill="#FF8800",
                dash=(6, 4),
                width=2,
                tags=("crosshair", "crosshair-vertical"),
            )
            label_offset = 8
            label_x = x_pos + label_offset
            label_anchor = "nw"
            if label_x > width - 20:
                label_x = x_pos - label_offset
                label_anchor = "ne"
            overlay.create_text(
                label_x,
                18,
                text=f"x={logical_x:.1f}",
                fill="#FF8800",
                font=("Helvetica", 12, "bold"),
                anchor=label_anchor,
                tags=("crosshair", "crosshair-vertical", "crosshair-label"),
            )

        if args.crosshair_y is not None:
            y_percent = max(0.0, min(100.0, float(args.crosshair_y))) / 100.0
            y_canvas = y_percent * height_f
            _, logical_y = _canvas_to_logical(0.0, y_canvas)
            y_pos = int(round(y_canvas))
            overlay.create_line(
                0,
                y_pos,
                width,
                y_pos,
                fill="#FF8800",
                dash=(6, 4),
                width=2,
                tags=("crosshair", "crosshair-horizontal"),
            )
            label_offset = 8
            label_y = y_pos - label_offset
            label_anchor = "w"
            if label_y < 20:
                label_y = y_pos + label_offset
                label_anchor = "w"
            overlay.create_text(
                12,
                label_y,
                text=f"y={logical_y:.1f}",
                fill="#FF8800",
                font=("Helvetica", 12, "bold"),
                anchor=label_anchor,
                tags=("crosshair", "crosshair-horizontal", "crosshair-label"),
            )

        overlay.tag_raise("crosshair")
        overlay.tag_raise("label")
        _update_cursor_label()

    payload_var.trace_add("write", lambda *_: _redraw_overlay())

    label_path = Path(args.label_file).expanduser() if args.label_file else None

    def _poll_label() -> None:
        if label_path:
            try:
                new_text = label_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                new_text = ""
            except OSError:
                new_text = payload_var.get()
            if payload_var.get() != new_text:
                payload_var.set(new_text)
        root.after(250, _poll_label)

    if label_path:
        _poll_label()

    if settings_watch["path"] is not None:
        root.after(500, _poll_scale_mode)

    root.after_idle(_redraw_overlay)
    root.bind("<Configure>", _redraw_overlay, add="+")

    root.mainloop()


if __name__ == "__main__":
    main()
