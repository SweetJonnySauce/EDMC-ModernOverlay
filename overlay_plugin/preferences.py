"""Preferences management and Tk UI for the Modern Overlay plugin."""
from __future__ import annotations

import json
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional


PREFERENCES_FILE = "overlay_settings.json"
STATUS_BASE_MARGIN = 20
LEGACY_STATUS_SLOT_MARGIN = 17
STATUS_GUTTER_MAX = 500
STATUS_GUTTER_DEFAULT = 50
LATEST_RELEASE_URL = "https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest"


@dataclass
class Preferences:
    """Simple JSON-backed preferences store."""

    plugin_dir: Path
    overlay_opacity: float = 0.0
    show_connection_status: bool = False
    debug_overlay_corner: str = "NW"
    client_log_retention: int = 5
    gridlines_enabled: bool = False
    gridline_spacing: int = 120
    force_render: bool = False
    force_xwayland: bool = False
    show_debug_overlay: bool = False
    min_font_point: float = 6.0
    max_font_point: float = 24.0
    title_bar_enabled: bool = False
    title_bar_height: int = 0
    cycle_payload_ids: bool = False
    copy_payload_id_on_cycle: bool = False
    scale_mode: str = "fit"
    nudge_overflow_payloads: bool = False
    payload_nudge_gutter: int = 30
    status_message_gutter: int = STATUS_GUTTER_DEFAULT

    def __post_init__(self) -> None:
        self.plugin_dir = Path(self.plugin_dir)
        self._path = self.plugin_dir / PREFERENCES_FILE
        self._load()

    # Persistence ---------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            return
        self.overlay_opacity = float(data.get("overlay_opacity", 0.0))
        self.show_connection_status = bool(data.get("show_connection_status", False))
        corner_value = str(data.get("debug_overlay_corner", "NW")) if data.get("debug_overlay_corner") is not None else "NW"
        self.debug_overlay_corner = corner_value.strip().upper() if corner_value else "NW"
        if self.debug_overlay_corner not in {"NW", "NE", "SW", "SE"}:
            self.debug_overlay_corner = "NW"
        try:
            retention = int(data.get("client_log_retention", 5))
        except (TypeError, ValueError):
            retention = 5
        self.client_log_retention = max(1, retention)
        self.gridlines_enabled = bool(data.get("gridlines_enabled", False))
        try:
            spacing = int(data.get("gridline_spacing", 120))
        except (TypeError, ValueError):
            spacing = 120
        self.gridline_spacing = max(10, spacing)
        self.force_render = bool(data.get("force_render", False))
        self.force_xwayland = bool(data.get("force_xwayland", False))
        self.show_debug_overlay = bool(data.get("show_debug_overlay", False))
        try:
            min_font = float(data.get("min_font_point", 6.0))
        except (TypeError, ValueError):
            min_font = 6.0
        try:
            max_font = float(data.get("max_font_point", 24.0))
        except (TypeError, ValueError):
            max_font = 24.0
        self.min_font_point = max(1.0, min(min_font, 48.0))
        self.max_font_point = max(self.min_font_point, min(max_font, 72.0))
        self.title_bar_enabled = bool(data.get("title_bar_enabled", False))
        try:
            bar_height = int(data.get("title_bar_height", 0))
        except (TypeError, ValueError):
            bar_height = 0
        self.title_bar_height = max(0, bar_height)
        self.cycle_payload_ids = bool(data.get("cycle_payload_ids", False))
        self.copy_payload_id_on_cycle = bool(data.get("copy_payload_id_on_cycle", False))
        mode = str(data.get("scale_mode", "fit") or "fit").strip().lower()
        self.scale_mode = mode if mode in {"fit", "fill"} else "fit"
        self.nudge_overflow_payloads = bool(data.get("nudge_overflow_payloads", False))
        try:
            gutter = int(data.get("payload_nudge_gutter", 30))
        except (TypeError, ValueError):
            gutter = 30
        self.payload_nudge_gutter = max(0, min(gutter, 500))
        try:
            status_gutter = int(data.get("status_message_gutter", STATUS_GUTTER_DEFAULT))
        except (TypeError, ValueError):
            status_gutter = STATUS_GUTTER_DEFAULT
        if "status_message_gutter" not in data:
            legacy_slots = int(bool(data.get("show_ed_bandwidth"))) + int(bool(data.get("show_ed_fps")))
            status_gutter = max(status_gutter, LEGACY_STATUS_SLOT_MARGIN * legacy_slots)
        self.status_message_gutter = max(0, min(status_gutter, STATUS_GUTTER_MAX))

    def save(self) -> None:
        payload: Dict[str, Any] = {
            "overlay_opacity": float(self.overlay_opacity),
            "show_connection_status": bool(self.show_connection_status),
            "debug_overlay_corner": str(self.debug_overlay_corner or "NW"),
            "client_log_retention": int(self.client_log_retention),
            "gridlines_enabled": bool(self.gridlines_enabled),
            "gridline_spacing": int(self.gridline_spacing),
            "force_render": bool(self.force_render),
            "force_xwayland": bool(self.force_xwayland),
            "show_debug_overlay": bool(self.show_debug_overlay),
            "min_font_point": float(self.min_font_point),
            "max_font_point": float(self.max_font_point),
            "status_bottom_margin": int(self.status_bottom_margin()),
            "title_bar_enabled": bool(self.title_bar_enabled),
            "title_bar_height": int(self.title_bar_height),
            "cycle_payload_ids": bool(self.cycle_payload_ids),
            "copy_payload_id_on_cycle": bool(self.copy_payload_id_on_cycle),
            "scale_mode": str(self.scale_mode or "fit"),
            "nudge_overflow_payloads": bool(self.nudge_overflow_payloads),
            "payload_nudge_gutter": int(self.payload_nudge_gutter),
            "status_message_gutter": int(self.status_message_gutter),
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def status_bottom_margin(self) -> int:
        return STATUS_BASE_MARGIN + int(max(0, self.status_message_gutter))


class PreferencesPanel:
    """Builds a Tkinter frame that edits Modern Overlay preferences."""

    def __init__(
        self,
        parent,
        preferences: Preferences,
        send_test_callback: Optional[Callable[[str, Optional[int], Optional[int]], None]] = None,
        set_opacity_callback: Optional[Callable[[float], None]] = None,
        set_status_callback: Optional[Callable[[bool], None]] = None,
        set_status_gutter_callback: Optional[Callable[[int], None]] = None,
        set_debug_overlay_corner_callback: Optional[Callable[[str], None]] = None,
        set_gridlines_enabled_callback: Optional[Callable[[bool], None]] = None,
        set_gridline_spacing_callback: Optional[Callable[[int], None]] = None,
        set_payload_nudge_callback: Optional[Callable[[bool], None]] = None,
        set_payload_gutter_callback: Optional[Callable[[int], None]] = None,
        set_force_render_callback: Optional[Callable[[bool], None]] = None,
        set_title_bar_config_callback: Optional[Callable[[bool, int], None]] = None,
        set_debug_overlay_callback: Optional[Callable[[bool], None]] = None,
        set_font_min_callback: Optional[Callable[[float], None]] = None,
        set_font_max_callback: Optional[Callable[[float], None]] = None,
        set_cycle_payload_callback: Optional[Callable[[bool], None]] = None,
        set_cycle_payload_copy_callback: Optional[Callable[[bool], None]] = None,
        set_scale_mode_callback: Optional[Callable[[str], None]] = None,
        cycle_payload_prev_callback: Optional[Callable[[], None]] = None,
        cycle_payload_next_callback: Optional[Callable[[], None]] = None,
        restart_overlay_callback: Optional[Callable[[], None]] = None,
        dev_mode: bool = False,
        plugin_version: Optional[str] = None,
        version_update_available: bool = False,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk
        import tkinter.font as tkfont
        import myNotebook as nb

        self._preferences = preferences
        self._style = ttk.Style()
        self._frame_style, self._spinbox_style, self._scale_style = self._init_theme_styles(nb)
        self._var_opacity = tk.DoubleVar(value=preferences.overlay_opacity)
        self._var_show_status = tk.BooleanVar(value=preferences.show_connection_status)
        self._var_status_gutter = tk.IntVar(value=max(0, int(preferences.status_message_gutter)))
        self._var_debug_overlay_corner = tk.StringVar(value=(preferences.debug_overlay_corner or "NW"))
        self._var_gridlines_enabled = tk.BooleanVar(value=preferences.gridlines_enabled)
        self._var_gridline_spacing = tk.IntVar(value=max(10, int(preferences.gridline_spacing)))
        self._var_payload_nudge = tk.BooleanVar(value=preferences.nudge_overflow_payloads)
        self._var_payload_gutter = tk.IntVar(value=max(0, int(preferences.payload_nudge_gutter)))
        self._var_force_render = tk.BooleanVar(value=preferences.force_render)
        self._var_title_bar_enabled = tk.BooleanVar(value=preferences.title_bar_enabled)
        self._var_title_bar_height = tk.IntVar(value=int(preferences.title_bar_height))
        self._var_debug_overlay = tk.BooleanVar(value=preferences.show_debug_overlay)
        self._var_min_font = tk.DoubleVar(value=float(preferences.min_font_point))
        self._var_max_font = tk.DoubleVar(value=float(preferences.max_font_point))
        self._var_cycle_payload = tk.BooleanVar(value=preferences.cycle_payload_ids)
        self._var_cycle_copy = tk.BooleanVar(value=preferences.copy_payload_id_on_cycle)
        self._scale_mode_options = [
            ("Fit (preserve aspect)", "fit"),
            ("Fill (proportional rescale)", "fill"),
        ]
        self._var_scale_mode_display = tk.StringVar(value=self._display_for_scale_mode(preferences.scale_mode))

        self._send_test = send_test_callback
        self._set_opacity = set_opacity_callback
        self._set_status = set_status_callback
        self._set_status_gutter = set_status_gutter_callback
        self._set_debug_overlay_corner = set_debug_overlay_corner_callback
        self._set_gridlines_enabled = set_gridlines_enabled_callback
        self._set_gridline_spacing = set_gridline_spacing_callback
        self._set_payload_nudge = set_payload_nudge_callback
        self._set_payload_gutter = set_payload_gutter_callback
        self._set_force_render = set_force_render_callback
        self._set_title_bar_config = set_title_bar_config_callback
        self._set_debug_overlay = set_debug_overlay_callback
        self._set_font_min = set_font_min_callback
        self._set_font_max = set_font_max_callback
        self._set_cycle_payload = set_cycle_payload_callback
        self._set_cycle_payload_copy = set_cycle_payload_copy_callback
        self._set_scale_mode = set_scale_mode_callback
        self._cycle_prev_callback = cycle_payload_prev_callback
        self._cycle_next_callback = cycle_payload_next_callback
        self._restart_overlay = restart_overlay_callback

        self._legacy_client = None
        self._title_bar_height_spin = None
        self._cycle_prev_btn = None
        self._cycle_next_btn = None
        self._cycle_copy_checkbox = None
        self._restart_button = None
        self._managed_fonts = []
        self._status_gutter_apply_in_progress = False
        self._var_status_gutter.trace_add("write", self._on_status_gutter_trace)
        self._plugin_version = (plugin_version or "").strip()
        self._version_update_available = bool(version_update_available)
        self._test_var = tk.StringVar()
        self._test_x_var = tk.StringVar()
        self._test_y_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")
        self._dev_mode = bool(dev_mode)

        frame = nb.Frame(parent)

        header_frame = ttk.Frame(frame, style=self._frame_style)
        header_frame.grid(row=0, column=0, sticky="we")
        header_frame.columnconfigure(0, weight=1)
        header_frame.columnconfigure(1, weight=0)

        if self._plugin_version:
            version_column = ttk.Frame(header_frame, style=self._frame_style)
            version_column.grid(row=0, column=1, sticky="ne")
            version_label = nb.Label(
                version_column,
                text=f"Version {self._plugin_version}",
                cursor="hand2",
                foreground="#1a73e8",
            )
            try:
                link_font = tkfont.Font(root=parent, font=version_label.cget("font"))
                link_font.configure(underline=True)
                self._managed_fonts.append(link_font)
                version_label.configure(font=link_font)
            except Exception:
                pass
            version_label.grid(row=0, column=0, sticky="e")
            version_label.bind("<Button-1>", self._open_release_link)
            version_label.bind("<Return>", self._open_release_link)
            version_label.bind(
                "<Enter>", lambda _event, widget=version_label: widget.configure(foreground="#0b57d0")
            )
            version_label.bind(
                "<Leave>", lambda _event, widget=version_label: widget.configure(foreground="#1a73e8")
            )
            if self._version_update_available:
                warning_label = nb.Label(
                    version_column,
                    text="A newer version is available",
                    foreground="#c62828",
                )
                warning_label.grid(row=1, column=0, sticky="e", pady=(2, 0))

        user_section = ttk.Frame(frame, style=self._frame_style)
        user_section.grid(row=1, column=0, sticky="we")
        user_section.columnconfigure(0, weight=1)
        user_row = 0

        scale_mode_row = ttk.Frame(user_section, style=self._frame_style)
        scale_mode_label = nb.Label(scale_mode_row, text="Overlay scaling mode:")
        scale_mode_label.pack(side="left")
        self._scale_mode_combo = ttk.Combobox(
            scale_mode_row,
            values=[label for label, _ in self._scale_mode_options],
            state="readonly",
            width=28,
            textvariable=self._var_scale_mode_display,
        )
        self._scale_mode_combo.pack(side="left", padx=(8, 0))
        self._scale_mode_combo.bind("<<ComboboxSelected>>", self._on_scale_mode_change)
        scale_mode_row.grid(row=user_row, column=0, sticky="w")
        user_row += 1

        status_row = ttk.Frame(user_section, style=self._frame_style)
        status_checkbox = nb.Checkbutton(
            status_row,
            text="Show connection status message at bottom of overlay",
            variable=self._var_show_status,
            onvalue=True,
            offvalue=False,
            command=self._on_show_status_toggle,
        )
        status_checkbox.pack(side="left")
        gutter_label = nb.Label(status_row, text="Gutter (px):")
        gutter_label.pack(side="left", padx=(16, 4))
        status_gutter_spin = ttk.Spinbox(
            status_row,
            from_=0,
            to=STATUS_GUTTER_MAX,
            increment=5,
            width=5,
            textvariable=self._var_status_gutter,
            command=self._on_status_gutter_command,
            style=self._spinbox_style,
        )
        status_gutter_spin.pack(side="left")
        status_gutter_spin.bind("<FocusOut>", self._on_status_gutter_event)
        status_gutter_spin.bind("<Return>", self._on_status_gutter_event)

        status_row.grid(row=user_row, column=0, sticky="w", pady=(12, 0))
        user_row += 1

        debug_checkbox = nb.Checkbutton(
            user_section,
            text="Show debug overlay metrics (frame size, scaling)",
            variable=self._var_debug_overlay,
            onvalue=True,
            offvalue=False,
            command=self._on_debug_overlay_toggle,
        )
        debug_checkbox.grid(row=user_row, column=0, sticky="w", pady=(8, 0))
        user_row += 1

        corner_row = ttk.Frame(user_section, style=self._frame_style)
        corner_label = nb.Label(corner_row, text="Debug overlay corner:")
        corner_label.pack(side="left")
        for label, value in (("NW", "NW"), ("NE", "NE"), ("SW", "SW"), ("SE", "SE")):
            rb = nb.Radiobutton(
                corner_row,
                text=label,
                value=value,
                variable=self._var_debug_overlay_corner,
                command=self._on_debug_overlay_corner_change,
            )
            rb.pack(side="left", padx=(6, 0))
        corner_row.grid(row=user_row, column=0, sticky="w", pady=(4, 0))
        user_row += 1

        font_row = ttk.Frame(user_section, style=self._frame_style)
        font_label = nb.Label(font_row, text="Font scaling bounds (pt):")
        font_label.pack(side="left")
        min_spin = ttk.Spinbox(
            font_row,
            from_=1.0,
            to=72.0,
            increment=0.5,
            width=5,
            textvariable=self._var_min_font,
            command=self._on_font_bounds_command,
            style=self._spinbox_style,
        )
        min_spin.pack(side="left", padx=(6, 0))
        min_spin.bind("<FocusOut>", self._on_font_bounds_event)
        min_spin.bind("<Return>", self._on_font_bounds_event)
        nb.Label(font_row, text="–").pack(side="left", padx=(4, 4))
        max_spin = ttk.Spinbox(
            font_row,
            from_=1.0,
            to=72.0,
            increment=0.5,
            width=5,
            textvariable=self._var_max_font,
            command=self._on_font_bounds_command,
            style=self._spinbox_style,
        )
        max_spin.pack(side="left")
        max_spin.bind("<FocusOut>", self._on_font_bounds_event)
        max_spin.bind("<Return>", self._on_font_bounds_event)
        font_row.grid(row=user_row, column=0, sticky="w", pady=(8, 0))
        user_row += 1

        title_bar_row = ttk.Frame(user_section, style=self._frame_style)
        title_bar_checkbox = nb.Checkbutton(
            title_bar_row,
            text="Compensate for Elite Dangerous title bar",
            variable=self._var_title_bar_enabled,
            onvalue=True,
            offvalue=False,
            command=self._on_title_bar_toggle,
        )
        title_bar_checkbox.pack(side="left")
        title_bar_height_label = nb.Label(title_bar_row, text="Height (px):")
        title_bar_height_label.pack(side="left", padx=(12, 4))
        title_bar_height_spin = ttk.Spinbox(
            title_bar_row,
            from_=0,
            to=200,
            increment=1,
            width=4,
            textvariable=self._var_title_bar_height,
            command=self._on_title_bar_height_command,
            style=self._spinbox_style,
        )
        title_bar_height_spin.pack(side="left")
        title_bar_height_spin.bind("<FocusOut>", self._on_title_bar_height_event)
        title_bar_height_spin.bind("<Return>", self._on_title_bar_height_event)
        if not self._var_title_bar_enabled.get():
            title_bar_height_spin.state(["disabled"])
        self._title_bar_height_spin = title_bar_height_spin
        title_bar_row.grid(row=user_row, column=0, sticky="w", pady=(8, 0))
        user_row += 1

        nudge_row = ttk.Frame(user_section, style=self._frame_style)
        nudge_checkbox = nb.Checkbutton(
            nudge_row,
            text="Nudge overflowing payloads back into view",
            variable=self._var_payload_nudge,
            onvalue=True,
            offvalue=False,
            command=self._on_payload_nudge_toggle,
        )
        nudge_checkbox.pack(side="left")
        gutter_label = nb.Label(nudge_row, text="Gutter (px):")
        gutter_label.pack(side="left", padx=(12, 4))
        gutter_spin = ttk.Spinbox(
            nudge_row,
            from_=0,
            to=500,
            increment=5,
            width=6,
            textvariable=self._var_payload_gutter,
            command=self._on_payload_gutter_command,
            style=self._spinbox_style,
        )
        gutter_spin.pack(side="left")
        gutter_spin.bind("<FocusOut>", self._on_payload_gutter_event)
        gutter_spin.bind("<Return>", self._on_payload_gutter_event)
        nudge_row.grid(row=user_row, column=0, sticky="w", pady=(8, 0))
        user_row += 1

        next_row = 2
        if self._dev_mode:
            dev_label = nb.Label(frame, text="Developer Settings")
            try:
                dev_font = tkfont.Font(root=parent, font=dev_label.cget("font"))
            except Exception:
                dev_font = None
            else:
                try:
                    dev_font.configure(weight="bold")
                    self._managed_fonts.append(dev_font)
                    dev_label.configure(font=dev_font)
                except Exception:
                    pass
            dev_frame = ttk.LabelFrame(frame, labelwidget=dev_label, padding=(8, 8))
            dev_frame.grid(row=next_row, column=0, sticky="we", pady=(16, 0))
            dev_frame.columnconfigure(0, weight=1)
            dev_row = 0

            restart_row = ttk.Frame(dev_frame, style=self._frame_style)
            restart_btn = nb.Button(restart_row, text="Restart overlay client", command=self._on_restart_overlay)
            if self._restart_overlay is None:
                restart_btn.configure(state="disabled")
            restart_btn.pack(side="left")
            restart_row.grid(row=dev_row, column=0, sticky="w")
            self._restart_button = restart_btn
            dev_row += 1

            opacity_label = nb.Label(
                dev_frame,
                text="Overlay background opacity (0.0 transparent – 1.0 opaque).",
            )
            opacity_label.grid(row=dev_row, column=0, sticky="w", pady=(12, 0))
            dev_row += 1

            opacity_row = ttk.Frame(dev_frame, style=self._frame_style)
            opacity_scale = ttk.Scale(
                opacity_row,
                variable=self._var_opacity,
                from_=0.0,
                to=1.0,
                orient=tk.HORIZONTAL,
                length=250,
                command=self._on_opacity_change,
                style=self._scale_style,
            )
            opacity_scale.pack(side="left", fill="x")
            opacity_row.grid(row=dev_row, column=0, sticky="we")
            dev_row += 1

            force_checkbox = nb.Checkbutton(
                dev_frame,
                text="Keep overlay visible when Elite Dangerous is not the foreground window",
                variable=self._var_force_render,
                onvalue=True,
                offvalue=False,
                command=self._on_force_render_toggle,
            )
            force_checkbox.grid(row=dev_row, column=0, sticky="w", pady=(12, 0))
            dev_row += 1

            grid_checkbox = nb.Checkbutton(
                dev_frame,
                text="Show light gridlines over the overlay background",
                variable=self._var_gridlines_enabled,
                onvalue=True,
                offvalue=False,
                command=self._on_gridlines_toggle,
            )
            grid_checkbox.grid(row=dev_row, column=0, sticky="w", pady=(10, 0))
            dev_row += 1

            grid_spacing_row = ttk.Frame(dev_frame, style=self._frame_style)
            grid_spacing_label = nb.Label(grid_spacing_row, text="Grid spacing (pixels):")
            grid_spacing_label.pack(side="left")
            grid_spacing_spin = ttk.Spinbox(
                grid_spacing_row,
                from_=10,
                to=400,
                increment=10,
                width=5,
                textvariable=self._var_gridline_spacing,
                command=self._on_gridline_spacing_command,
                style=self._spinbox_style,
            )
            grid_spacing_spin.pack(side="left", padx=(6, 0))
            grid_spacing_spin.bind("<FocusOut>", self._on_gridline_spacing_event)
            grid_spacing_spin.bind("<Return>", self._on_gridline_spacing_event)
            grid_spacing_row.grid(row=dev_row, column=0, sticky="w", pady=(2, 0))
            dev_row += 1

            cycle_row = ttk.Frame(dev_frame, style=self._frame_style)
            cycle_checkbox = nb.Checkbutton(
                cycle_row,
                text="Cycle through Payload IDs",
                variable=self._var_cycle_payload,
                onvalue=True,
                offvalue=False,
                command=self._on_cycle_payload_toggle,
            )
            self._cycle_prev_btn = nb.Button(cycle_row, text="<", width=3, command=self._on_cycle_payload_prev)
            self._cycle_next_btn = nb.Button(cycle_row, text=">", width=3, command=self._on_cycle_payload_next)
            self._cycle_copy_checkbox = nb.Checkbutton(
                cycle_row,
                text="Copy current payload ID to clipboard",
                variable=self._var_cycle_copy,
                onvalue=True,
                offvalue=False,
                command=self._on_cycle_copy_toggle,
            )
            cycle_checkbox.pack(side="left")
            self._cycle_prev_btn.pack(side="left", padx=(8, 0))
            self._cycle_next_btn.pack(side="left", padx=(4, 0))
            self._cycle_copy_checkbox.pack(side="left", padx=(12, 0))
            cycle_row.grid(row=dev_row, column=0, sticky="w", pady=(12, 0))
            dev_row += 1

            test_label = nb.Label(dev_frame, text="Send test message to overlay:")
            test_label.grid(row=dev_row, column=0, sticky="w", pady=(12, 0))
            dev_row += 1

            test_row = ttk.Frame(dev_frame, style=self._frame_style)
            test_entry = nb.EntryMenu(test_row, textvariable=self._test_var, width=40)
            x_label = nb.Label(test_row, text="X:")
            x_entry = nb.EntryMenu(test_row, textvariable=self._test_x_var, width=6)
            y_label = nb.Label(test_row, text="Y:")
            y_entry = nb.EntryMenu(test_row, textvariable=self._test_y_var, width=6)
            send_button = nb.Button(test_row, text="Send", command=self._on_send_click)
            test_entry.pack(side="left", fill="x", expand=True)
            x_label.pack(side="left", padx=(8, 2))
            x_entry.pack(side="left")
            y_label.pack(side="left", padx=(8, 2))
            y_entry.pack(side="left")
            send_button.pack(side="left", padx=(8, 0))
            test_row.grid(row=dev_row, column=0, sticky="we", pady=(2, 0))
            test_row.columnconfigure(0, weight=1)
            dev_row += 1

            legacy_label = nb.Label(dev_frame, text="Legacy edmcoverlay compatibility:")
            legacy_label.grid(row=dev_row, column=0, sticky="w", pady=(12, 0))
            dev_row += 1

            legacy_row = ttk.Frame(dev_frame, style=self._frame_style)
            legacy_text_btn = nb.Button(legacy_row, text="Send legacy text", command=self._on_legacy_text)
            legacy_rect_btn = nb.Button(legacy_row, text="Send legacy rectangle", command=self._on_legacy_rect)
            legacy_text_btn.pack(side="left")
            legacy_rect_btn.pack(side="left", padx=(8, 0))
            legacy_row.grid(row=dev_row, column=0, sticky="w", pady=(2, 0))
            dev_row += 1

            next_row += 1

        self._update_cycle_button_state()

        status_label = nb.Label(frame, textvariable=self._status_var, wraplength=400, justify="left")
        status_label.grid(row=next_row, column=0, sticky="w", pady=(10, 0))
        frame.columnconfigure(0, weight=1)

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        self._preferences.save()

    def _display_for_scale_mode(self, mode: str) -> str:
        value = (mode or "fit").strip().lower()
        for label, key in self._scale_mode_options:
            if key == value:
                return label
        return self._scale_mode_options[0][0]

    def _value_for_scale_mode_label(self, label: str) -> str:
        for option_label, key in self._scale_mode_options:
            if option_label == label:
                return key
        return self._scale_mode_options[0][1]

    def _init_theme_styles(self, nb):
        try:
            bg = nb.PAGEBG
            fg = nb.PAGEFG
        except AttributeError:
            bg = fg = None
        frame_style = "OverlayPrefs.TFrame"
        spin_style = "OverlayPrefs.TSpinbox"
        scale_style = "OverlayPrefs.Horizontal.TScale"
        self._style.configure(frame_style, background=bg)
        self._style.configure(spin_style, arrowsize=12)
        if bg is not None and fg is not None:
            self._style.configure(spin_style, fieldbackground=bg, foreground=fg, background=bg)
            self._style.configure(scale_style, background=bg)
        return frame_style, spin_style, scale_style

    def _on_opacity_change(self, value: str) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        numeric = max(0.0, min(1.0, numeric))
        self._var_opacity.set(numeric)
        self._preferences.overlay_opacity = numeric
        if self._set_opacity:
            try:
                self._set_opacity(numeric)
            except Exception as exc:
                self._status_var.set(f"Failed to update opacity: {exc}")
                return
        self._preferences.save()

    def _on_show_status_toggle(self) -> None:
        value = bool(self._var_show_status.get())
        self._preferences.show_connection_status = value
        if self._set_status:
            try:
                self._set_status(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update connection status: {exc}")
                return
        self._preferences.save()

    def _on_status_gutter_command(self) -> None:
        self._apply_status_gutter()

    def _on_status_gutter_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_status_gutter()

    def _on_status_gutter_trace(self, *_args) -> None:
        if self._status_gutter_apply_in_progress:
            return
        self._apply_status_gutter()

    def _open_release_link(self, _event=None) -> None:
        try:
            webbrowser.open_new(LATEST_RELEASE_URL)
        except Exception as exc:
            self._status_var.set(f"Failed to open release notes: {exc}")

    def _apply_status_gutter(self) -> None:
        if self._status_gutter_apply_in_progress:
            return
        self._status_gutter_apply_in_progress = True
        try:
            gutter = int(self._var_status_gutter.get())
        except (TypeError, ValueError):
            gutter = self._preferences.status_message_gutter
        gutter = max(0, min(gutter, STATUS_GUTTER_MAX))
        if str(gutter) != str(self._var_status_gutter.get()):
            self._var_status_gutter.set(gutter)
        old_value = self._preferences.status_message_gutter
        if self._set_status_gutter:
            try:
                self._set_status_gutter(gutter)
            except Exception as exc:
                self._status_var.set(f"Failed to update status gutter: {exc}")
                self._var_status_gutter.set(old_value)
                self._status_gutter_apply_in_progress = False
                return
        elif gutter == old_value:
            self._status_gutter_apply_in_progress = False
            return
        self._preferences.status_message_gutter = gutter
        self._preferences.save()
        self._status_gutter_apply_in_progress = False

    def _on_debug_overlay_corner_change(self) -> None:
        value = (self._var_debug_overlay_corner.get() or "NW").upper()
        if value not in {"NW", "NE", "SW", "SE"}:
            value = "NW"
        self._preferences.debug_overlay_corner = value
        if self._set_debug_overlay_corner:
            try:
                self._set_debug_overlay_corner(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update debug overlay corner: {exc}")
                return
        self._preferences.save()

    def _update_cycle_button_state(self) -> None:
        state = "normal" if self._var_cycle_payload.get() else "disabled"
        for button in (self._cycle_prev_btn, self._cycle_next_btn, self._cycle_copy_checkbox):
            if button is not None:
                try:
                    button.configure(state=state)
                except Exception:
                    pass

    def _on_cycle_payload_toggle(self) -> None:
        value = bool(self._var_cycle_payload.get())
        try:
            if self._set_cycle_payload:
                self._set_cycle_payload(value)
            else:
                self._preferences.cycle_payload_ids = value
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update payload cycling: {exc}")
            self._var_cycle_payload.set(not value)
            self._preferences.cycle_payload_ids = bool(self._var_cycle_payload.get())
            self._update_cycle_button_state()
            return
        self._preferences.cycle_payload_ids = value
        self._update_cycle_button_state()

    def _on_cycle_copy_toggle(self) -> None:
        value = bool(self._var_cycle_copy.get())
        if not self._var_cycle_payload.get():  # Should not be reachable because checkbox disabled, but guard anyway.
            value = False
            self._var_cycle_copy.set(False)
        try:
            if self._set_cycle_payload_copy:
                self._set_cycle_payload_copy(value)
            else:
                self._preferences.copy_payload_id_on_cycle = value
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update copy-on-cycle setting: {exc}")
            self._var_cycle_copy.set(self._preferences.copy_payload_id_on_cycle)
            return
        self._preferences.copy_payload_id_on_cycle = value
        self._preferences.save()

    def _on_cycle_payload_prev(self) -> None:
        if not self._var_cycle_payload.get():
            return
        if self._cycle_prev_callback:
            try:
                self._cycle_prev_callback()
            except Exception as exc:
                self._status_var.set(f"Failed to cycle payload IDs: {exc}")

    def _on_cycle_payload_next(self) -> None:
        if not self._var_cycle_payload.get():
            return
        if self._cycle_next_callback:
            try:
                self._cycle_next_callback()
            except Exception as exc:
                self._status_var.set(f"Failed to cycle payload IDs: {exc}")

    def _on_restart_overlay(self) -> None:
        if self._restart_overlay is None:
            self._status_var.set("Overlay restart unavailable.")
            return
        try:
            self._restart_overlay()
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Failed to restart overlay: {exc}")
            return
        self._status_var.set("Overlay restart requested.")

    def _on_force_render_toggle(self) -> None:
        value = bool(self._var_force_render.get())
        self._preferences.force_render = value
        if self._set_force_render:
            try:
                self._set_force_render(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update force-render option: {exc}")
                return
        self._preferences.save()

    def _on_title_bar_toggle(self) -> None:
        enabled = bool(self._var_title_bar_enabled.get())
        height = self._apply_title_bar_height()
        self._preferences.title_bar_enabled = enabled
        if self._title_bar_height_spin is not None:
            if enabled:
                self._title_bar_height_spin.state(["!disabled"])
            else:
                self._title_bar_height_spin.state(["disabled"])
        if self._set_title_bar_config:
            try:
                self._set_title_bar_config(enabled, height)
            except Exception as exc:
                self._status_var.set(f"Failed to update title bar compensation: {exc}")
                return
        self._preferences.save()

    def _on_title_bar_height_command(self) -> None:
        self._apply_title_bar_height(update_remote=True)

    def _on_title_bar_height_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_title_bar_height(update_remote=True)

    def _apply_title_bar_height(self, update_remote: bool = False) -> int:
        try:
            value = int(self._var_title_bar_height.get())
        except Exception:
            value = self._preferences.title_bar_height
        value = max(0, value)
        self._var_title_bar_height.set(value)
        self._preferences.title_bar_height = value
        if update_remote and self._set_title_bar_config:
            try:
                self._set_title_bar_config(bool(self._var_title_bar_enabled.get()), value)
            except Exception as exc:
                self._status_var.set(f"Failed to update title bar height: {exc}")
                return value
        if update_remote:
            self._preferences.save()
        return value

    def _on_debug_overlay_toggle(self) -> None:
        value = bool(self._var_debug_overlay.get())
        self._preferences.show_debug_overlay = value
        if self._set_debug_overlay:
            try:
                self._set_debug_overlay(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update debug overlay: {exc}")
                return
        self._preferences.save()

    def _on_gridlines_toggle(self) -> None:
        enabled = bool(self._var_gridlines_enabled.get())
        self._preferences.gridlines_enabled = enabled
        if self._set_gridlines_enabled:
            try:
                self._set_gridlines_enabled(enabled)
            except Exception as exc:
                self._status_var.set(f"Failed to update gridlines: {exc}")
                return
        self._preferences.save()

    def _on_gridline_spacing_command(self) -> None:
        self._apply_gridline_spacing()

    def _on_gridline_spacing_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_gridline_spacing()

    def _apply_gridline_spacing(self) -> None:
        try:
            spacing = int(self._var_gridline_spacing.get())
        except (TypeError, ValueError):
            spacing = self._preferences.gridline_spacing
        spacing = max(10, spacing)
        self._var_gridline_spacing.set(spacing)
        self._preferences.gridline_spacing = spacing
        if self._set_gridline_spacing:
            try:
                self._set_gridline_spacing(spacing)
            except Exception as exc:
                self._status_var.set(f"Failed to update grid spacing: {exc}")
                return
        self._preferences.save()

    def _on_payload_nudge_toggle(self) -> None:
        enabled = bool(self._var_payload_nudge.get())
        self._preferences.nudge_overflow_payloads = enabled
        if self._set_payload_nudge:
            try:
                self._set_payload_nudge(enabled)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload nudging: {exc}")
                self._var_payload_nudge.set(not enabled)
                self._preferences.nudge_overflow_payloads = bool(self._var_payload_nudge.get())
                return
        self._preferences.save()

    def _on_payload_gutter_command(self) -> None:
        self._apply_payload_gutter()

    def _on_payload_gutter_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_payload_gutter()

    def _apply_payload_gutter(self) -> None:
        try:
            gutter = int(self._var_payload_gutter.get())
        except (TypeError, ValueError):
            gutter = self._preferences.payload_nudge_gutter
        gutter = max(0, min(gutter, 500))
        self._var_payload_gutter.set(gutter)
        self._preferences.payload_nudge_gutter = gutter
        if self._set_payload_gutter:
            try:
                self._set_payload_gutter(gutter)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload gutter: {exc}")
                return
        self._preferences.save()

    def _on_scale_mode_change(self, _event=None) -> None:
        selection = self._var_scale_mode_display.get()
        mode = self._value_for_scale_mode_label(selection)
        if mode == self._preferences.scale_mode:
            return
        try:
            if self._set_scale_mode:
                self._set_scale_mode(mode)
            else:
                self._preferences.scale_mode = mode
                self._preferences.save()
        except Exception as exc:
            self._status_var.set(f"Failed to update scaling mode: {exc}")
            self._var_scale_mode_display.set(self._display_for_scale_mode(self._preferences.scale_mode))
            return
        self._preferences.scale_mode = mode
        self._var_scale_mode_display.set(self._display_for_scale_mode(mode))
        self._preferences.save()

    def _on_font_bounds_command(self) -> None:
        self._apply_font_bounds()

    def _on_font_bounds_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_font_bounds()

    def _apply_font_bounds(self) -> None:
        try:
            min_value = float(self._var_min_font.get())
        except (TypeError, ValueError):
            min_value = self._preferences.min_font_point
        try:
            max_value = float(self._var_max_font.get())
        except (TypeError, ValueError):
            max_value = self._preferences.max_font_point
        min_value = max(1.0, min(min_value, 48.0))
        max_value = max(min_value, min(max_value, 72.0))
        self._var_min_font.set(min_value)
        self._var_max_font.set(max_value)
        callback_failed = False
        if self._set_font_min:
            try:
                self._set_font_min(min_value)
            except Exception as exc:
                self._status_var.set(f"Failed to update minimum font size: {exc}")
                callback_failed = True
        if self._set_font_max:
            try:
                self._set_font_max(max_value)
            except Exception as exc:
                self._status_var.set(f"Failed to update maximum font size: {exc}")
                callback_failed = True
        if callback_failed:
            return
        self._preferences.min_font_point = min_value
        self._preferences.max_font_point = max_value
        self._preferences.save()

    def _on_send_click(self) -> None:
        message = self._test_var.get().strip()
        if not message:
            self._status_var.set("Enter a test message first.")
            return
        if not self._send_test:
            self._status_var.set("Overlay not running; message not sent.")
            return
        x_raw = self._test_x_var.get().strip()
        y_raw = self._test_y_var.get().strip()
        x_val: Optional[int] = None
        y_val: Optional[int] = None
        if x_raw or y_raw:
            if not x_raw or not y_raw:
                self._status_var.set("Provide both X and Y coordinates or leave both blank.")
                return
            try:
                x_val = max(0, int(float(x_raw)))
            except (TypeError, ValueError):
                self._status_var.set("X coordinate must be a number.")
                return
            try:
                y_val = max(0, int(float(y_raw)))
            except (TypeError, ValueError):
                self._status_var.set("Y coordinate must be a number.")
                return
            self._test_x_var.set(str(x_val))
            self._test_y_var.set(str(y_val))
        try:
            if x_val is None or y_val is None:
                self._send_test(message, None, None)  # type: ignore[arg-type]
            else:
                self._send_test(message, x_val, y_val)
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Failed to send message: {exc}")
            return
        if x_val is None or y_val is None:
            self._status_var.set("Test message sent to overlay.")
        else:
            self._status_var.set(f"Test message sent to overlay at ({x_val}, {y_val}).")

    def _legacy_overlay(self):
        if self._legacy_client is None:
            try:
                from EDMCOverlay import edmcoverlay
            except ImportError:
                self._status_var.set("Legacy API not available.")
                return None
            self._legacy_client = edmcoverlay.Overlay()
        return self._legacy_client

    def _on_legacy_text(self) -> None:
        overlay = self._legacy_overlay()
        if overlay is None:
            return
        message = self._test_var.get().strip() or "Hello from edmcoverlay"
        try:
            overlay.send_message("modernoverlay-test", message, "#80d0ff", 60, 120, ttl=5, size="large")
        except Exception as exc:
            self._status_var.set(f"Legacy text failed: {exc}")
            return
        self._status_var.set("Legacy text sent via edmcoverlay API.")

    def _on_legacy_rect(self) -> None:
        overlay = self._legacy_overlay()
        if overlay is None:
            return
        try:
            overlay.send_shape(
                "modernoverlay-test-rect",
                "rect",
                "#80d0ff",
                "#20004080",
                40,
                80,
                400,
                120,
                ttl=5,
            )
        except Exception as exc:
            self._status_var.set(f"Legacy rectangle failed: {exc}")
            return
        self._status_var.set("Legacy rectangle sent via edmcoverlay API.")
