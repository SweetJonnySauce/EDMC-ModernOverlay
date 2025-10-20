"""Preferences management and Tk UI for the Modern Overlay plugin."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


PREFERENCES_FILE = "overlay_settings.json"


@dataclass
class Preferences:
    """Simple JSON-backed preferences store."""

    plugin_dir: Path
    capture_output: bool = True
    overlay_opacity: float = 0.0
    show_connection_status: bool = False
    log_payloads: bool = False
    legacy_vertical_scale: float = 1.0
    legacy_horizontal_scale: float = 1.0
    client_log_retention: int = 5
    gridlines_enabled: bool = False
    gridline_spacing: int = 120
    window_width: int = 1920
    window_height: int = 1080
    follow_game_window: bool = True
    origin_x: int = 0
    origin_y: int = 0
    force_render: bool = False
    force_xwayland: bool = False

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
        self.capture_output = bool(data.get("capture_output", True))
        self.overlay_opacity = float(data.get("overlay_opacity", 0.0))
        self.show_connection_status = bool(data.get("show_connection_status", False))
        self.log_payloads = bool(data.get("log_payloads", False))
        try:
            self.legacy_vertical_scale = float(data.get("legacy_vertical_scale", 1.0))
        except (TypeError, ValueError):
            self.legacy_vertical_scale = 1.0
        try:
            self.legacy_horizontal_scale = float(data.get("legacy_horizontal_scale", 1.0))
        except (TypeError, ValueError):
            self.legacy_horizontal_scale = 1.0
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
        try:
            width = int(data.get("window_width", 1920))
        except (TypeError, ValueError):
            width = 1920
        try:
            height = int(data.get("window_height", 1080))
        except (TypeError, ValueError):
            height = 1080
        self.window_width = max(640, width)
        self.window_height = max(360, height)
        self.follow_game_window = bool(data.get("follow_game_window", True))
        try:
            origin_x = int(data.get("origin_x", 0))
        except (TypeError, ValueError):
            origin_x = 0
        try:
            origin_y = int(data.get("origin_y", 0))
        except (TypeError, ValueError):
            origin_y = 0
        self.origin_x = max(0, origin_x)
        self.origin_y = max(0, origin_y)
        self.force_render = bool(data.get("force_render", False))
        self.force_xwayland = bool(data.get("force_xwayland", False))

    def save(self) -> None:
        payload: Dict[str, Any] = {
            "capture_output": bool(self.capture_output),
            "overlay_opacity": float(self.overlay_opacity),
            "show_connection_status": bool(self.show_connection_status),
            "log_payloads": bool(self.log_payloads),
            "legacy_vertical_scale": float(self.legacy_vertical_scale),
            "legacy_horizontal_scale": float(self.legacy_horizontal_scale),
            "client_log_retention": int(self.client_log_retention),
            "gridlines_enabled": bool(self.gridlines_enabled),
            "gridline_spacing": int(self.gridline_spacing),
            "window_width": int(self.window_width),
            "window_height": int(self.window_height),
            "follow_game_window": bool(self.follow_game_window),
            "origin_x": int(self.origin_x),
            "origin_y": int(self.origin_y),
            "force_render": bool(self.force_render),
            "force_xwayland": bool(self.force_xwayland),
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PreferencesPanel:
    """Builds a Tkinter frame that edits Modern Overlay preferences."""

    def __init__(
        self,
        parent,
        preferences: Preferences,
        send_test_callback: Optional[Callable[[str], None]] = None,
        set_opacity_callback: Optional[Callable[[float], None]] = None,
        set_status_callback: Optional[Callable[[bool], None]] = None,
        set_log_payloads_callback: Optional[Callable[[bool], None]] = None,
        set_legacy_scale_callback: Optional[Callable[[float], None]] = None,
        set_gridlines_enabled_callback: Optional[Callable[[bool], None]] = None,
        set_gridline_spacing_callback: Optional[Callable[[int], None]] = None,
        set_window_width_callback: Optional[Callable[[int], None]] = None,
        set_window_height_callback: Optional[Callable[[int], None]] = None,
        set_window_size_callback: Optional[Callable[[int, int], None]] = None,
        set_horizontal_scale_callback: Optional[Callable[[float], None]] = None,
        set_follow_mode_callback: Optional[Callable[[bool], None]] = None,
        set_force_render_callback: Optional[Callable[[bool], None]] = None,
        set_origin_callback: Optional[Callable[[int, int], None]] = None,
        reset_origin_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        import tkinter as tk
        import myNotebook as nb

        self._preferences = preferences
        self._var_capture = tk.BooleanVar(value=preferences.capture_output)
        self._var_opacity = tk.DoubleVar(value=preferences.overlay_opacity)
        self._var_show_status = tk.BooleanVar(value=preferences.show_connection_status)
        self._var_log_payloads = tk.BooleanVar(value=preferences.log_payloads)
        self._var_legacy_scale = tk.DoubleVar(value=preferences.legacy_vertical_scale)
        self._var_horizontal_scale = tk.DoubleVar(value=preferences.legacy_horizontal_scale)
        self._var_log_retention = tk.IntVar(value=max(1, int(preferences.client_log_retention)))
        self._var_gridlines_enabled = tk.BooleanVar(value=preferences.gridlines_enabled)
        self._var_gridline_spacing = tk.IntVar(value=max(10, int(preferences.gridline_spacing)))
        self._var_window_width = tk.IntVar(value=max(640, int(preferences.window_width)))
        self._var_window_height = tk.IntVar(value=max(360, int(preferences.window_height)))
        self._send_test = send_test_callback
        self._test_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")
        self._legacy_client = None
        self._set_opacity = set_opacity_callback
        self._set_status = set_status_callback
        self._set_log_payloads = set_log_payloads_callback
        self._set_legacy_scale = set_legacy_scale_callback
        self._set_gridlines_enabled = set_gridlines_enabled_callback
        self._set_gridline_spacing = set_gridline_spacing_callback
        self._set_window_width = set_window_width_callback
        self._set_window_height = set_window_height_callback
        self._set_window_size = set_window_size_callback
        self._set_horizontal_scale = set_horizontal_scale_callback
        self._legacy_scale_display = tk.StringVar(value=f"{preferences.legacy_vertical_scale:.2f}×")
        self._horizontal_scale_display = tk.StringVar(value=f"{preferences.legacy_horizontal_scale:.2f}×")
        self._var_follow_mode = tk.BooleanVar(value=preferences.follow_game_window)
        self._var_origin_x = tk.StringVar(value=str(max(0, int(getattr(preferences, "origin_x", 0)))))
        self._var_origin_y = tk.StringVar(value=str(max(0, int(getattr(preferences, "origin_y", 0)))))
        self._var_force_render = tk.BooleanVar(value=preferences.force_render)
        self._set_follow_mode = set_follow_mode_callback
        self._set_force_render = set_force_render_callback
        self._set_origin = set_origin_callback
        self._reset_origin = reset_origin_callback
        self._origin_reset_button = None
        self._origin_entries = []
        self._window_size_guard = False
        self._follow_labels: List[Any] = []
        self._follow_label_defaults: Dict[Any, Optional[str]] = {}
        self._disabled_label_fg = "#888888"

        frame = nb.Frame(parent)
        description = (
            "Capture overlay stdout/stderr when EDMC logging is set to DEBUG "
            "(useful for troubleshooting). Changes require restarting the overlay."
        )
        checkbox = tk.Checkbutton(
            frame,
            text="Enable overlay stdout/stderr capture",
            variable=self._var_capture,
            onvalue=True,
            offvalue=False,
            command=self._on_capture_toggle,
        )
        helper = tk.Label(frame, text=description, wraplength=400, justify="left")
        checkbox.grid(row=0, column=0, sticky="w")
        helper.grid(row=1, column=0, sticky="w", pady=(2, 0))

        status_checkbox = tk.Checkbutton(
            frame,
            text="Show connection status message at bottom of overlay",
            variable=self._var_show_status,
            onvalue=True,
            offvalue=False,
            command=self._on_show_status_toggle,
        )
        status_checkbox.grid(row=2, column=0, sticky="w", pady=(10, 0))

        log_checkbox = tk.Checkbutton(
            frame,
            text="Send overlay payloads to the EDMC log",
            variable=self._var_log_payloads,
            onvalue=True,
            offvalue=False,
            command=self._on_log_payload_toggle,
        )
        log_checkbox.grid(row=3, column=0, sticky="w", pady=(4, 0))

        retention_label = tk.Label(frame, text="Overlay client log files to keep (rotate when current file grows).")
        retention_label.grid(row=4, column=0, sticky="w", pady=(6, 0))

        retention_row = tk.Frame(frame)
        retention_spin = tk.Spinbox(
            retention_row,
            from_=1,
            to=20,
            width=5,
            textvariable=self._var_log_retention,
        )
        retention_spin.pack(side="left")
        retention_helper = tk.Label(retention_row, text="(applies next time the overlay restarts)")
        retention_helper.pack(side="left", padx=(8, 0))
        retention_row.grid(row=5, column=0, sticky="w")

        legacy_scale_label = tk.Label(
            frame,
            text="Legacy overlay vertical scale (1.00× keeps original spacing).",
        )
        legacy_scale_label.grid(row=6, column=0, sticky="w", pady=(10, 0))

        legacy_scale_row = tk.Frame(frame)
        legacy_scale = tk.Scale(
            legacy_scale_row,
            variable=self._var_legacy_scale,
            from_=0.5,
            to=2.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=250,
            command=self._on_legacy_scale_change,
        )
        legacy_scale.pack(side="left", fill="x", expand=True)
        legacy_scale_value_label = tk.Label(legacy_scale_row, textvariable=self._legacy_scale_display, width=6, anchor="w")
        legacy_scale_value_label.pack(side="left", padx=(8, 0))
        legacy_scale_row.grid(row=7, column=0, sticky="we")

        horizontal_scale_label = tk.Label(
            frame,
            text="Legacy overlay horizontal scale (1.00× keeps original width).",
        )
        horizontal_scale_label.grid(row=8, column=0, sticky="w", pady=(10, 0))

        horizontal_scale_row = tk.Frame(frame)
        horizontal_scale = tk.Scale(
            horizontal_scale_row,
            variable=self._var_horizontal_scale,
            from_=0.5,
            to=2.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=250,
            command=self._on_horizontal_scale_change,
        )
        horizontal_scale.pack(side="left", fill="x", expand=True)
        horizontal_scale_value_label = tk.Label(horizontal_scale_row, textvariable=self._horizontal_scale_display, width=6, anchor="w")
        horizontal_scale_value_label.pack(side="left", padx=(8, 0))
        horizontal_scale_row.grid(row=9, column=0, sticky="we")

        opacity_label = tk.Label(
            frame,
            text=(
                "Overlay background opacity (0.0 transparent – 1.0 opaque). "
                "Alt+drag is enabled when opacity > 0.5."
            ),
        )
        opacity_label.grid(row=10, column=0, sticky="w", pady=(10, 0))

        opacity_row = tk.Frame(frame)
        opacity_scale = tk.Scale(
            opacity_row,
            variable=self._var_opacity,
            from_=0.0,
            to=1.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            length=250,
            command=self._on_opacity_change,
        )
        opacity_scale.pack(side="left", fill="x")
        opacity_row.grid(row=11, column=0, sticky="we")

        follow_checkbox = tk.Checkbutton(
            frame,
            text="Follow the Elite Dangerous window position and size",
            variable=self._var_follow_mode,
            onvalue=True,
            offvalue=False,
            command=self._on_follow_toggle,
        )
        follow_checkbox.grid(row=12, column=0, sticky="w", pady=(10, 0))

        size_label = tk.Label(frame, text="Overlay window size (pixels; updates immediately):")
        size_label.grid(row=13, column=0, sticky="w", pady=(10, 0))

        size_row = tk.Frame(frame)
        width_label = tk.Label(size_row, text="Width:")
        self._register_follow_label(width_label)
        width_label.pack(side="left")
        width_spin = tk.Spinbox(
            size_row,
            from_=640,
            to=3840,
            increment=20,
            width=6,
            textvariable=self._var_window_width,
            command=self._on_window_width_command,
        )
        width_spin.pack(side="left", padx=(6, 0))
        width_spin.bind("<FocusOut>", self._on_window_width_event)
        width_spin.bind("<Return>", self._on_window_width_event)
        height_label = tk.Label(size_row, text="Height:")
        self._register_follow_label(height_label)
        height_label.pack(side="left", padx=(12, 0))
        height_spin = tk.Spinbox(
            size_row,
            from_=360,
            to=2160,
            increment=20,
            width=6,
            textvariable=self._var_window_height,
            command=self._on_window_height_command,
        )
        height_spin.pack(side="left", padx=(6, 0))
        height_spin.bind("<FocusOut>", self._on_window_height_event)
        height_spin.bind("<Return>", self._on_window_height_event)
        size_row.grid(row=14, column=0, sticky="w", pady=(2, 0))
        self._size_controls = (size_label, size_row, width_spin, height_spin)
        self._follow_checkbox = follow_checkbox

        origin_label = tk.Label(frame, text="Overlay origin (top-left in pixels):")
        self._register_follow_label(origin_label)
        origin_label.grid(row=15, column=0, sticky="w", pady=(10, 0))

        origin_row = tk.Frame(frame)
        origin_x_label = tk.Label(origin_row, text="X:")
        self._register_follow_label(origin_x_label)
        origin_x_label.pack(side="left")
        origin_x_entry = tk.Entry(origin_row, width=7, textvariable=self._var_origin_x)
        origin_x_entry.pack(side="left", padx=(4, 0))
        origin_x_entry.bind("<FocusOut>", self._on_origin_entry_event)
        origin_x_entry.bind("<Return>", self._on_origin_entry_event)
        origin_y_label = tk.Label(origin_row, text="Y:")
        self._register_follow_label(origin_y_label)
        origin_y_label.pack(side="left", padx=(12, 0))
        origin_y_entry = tk.Entry(origin_row, width=7, textvariable=self._var_origin_y)
        origin_y_entry.pack(side="left", padx=(4, 0))
        origin_y_entry.bind("<FocusOut>", self._on_origin_entry_event)
        origin_y_entry.bind("<Return>", self._on_origin_entry_event)
        reset_button = tk.Button(origin_row, text="Reset origin to 0,0", command=self._on_reset_origin_click)
        reset_button.pack(side="left", padx=(12, 0))
        origin_row.grid(row=16, column=0, sticky="w", pady=(2, 0))
        self._origin_entries.extend([origin_x_entry, origin_y_entry])
        self._origin_reset_button = reset_button
        self._update_controls_state()

        force_checkbox = tk.Checkbutton(
            frame,
            text="Keep overlay visible when Elite Dangerous is not the foreground window",
            variable=self._var_force_render,
            onvalue=True,
            offvalue=False,
            command=self._on_force_render_toggle,
        )
        force_checkbox.grid(row=17, column=0, sticky="w", pady=(6, 0))

        grid_checkbox = tk.Checkbutton(
            frame,
            text="Show light gridlines over the overlay background",
            variable=self._var_gridlines_enabled,
            onvalue=True,
            offvalue=False,
            command=self._on_gridlines_toggle,
        )
        grid_checkbox.grid(row=18, column=0, sticky="w", pady=(8, 0))

        grid_spacing_row = tk.Frame(frame)
        grid_spacing_label = tk.Label(grid_spacing_row, text="Grid spacing (pixels):")
        grid_spacing_label.pack(side="left")
        grid_spacing_spin = tk.Spinbox(
            grid_spacing_row,
            from_=10,
            to=400,
            increment=10,
            width=5,
            textvariable=self._var_gridline_spacing,
            command=self._on_gridline_spacing_command,
        )
        grid_spacing_spin.pack(side="left", padx=(6, 0))
        grid_spacing_spin.bind("<FocusOut>", self._on_gridline_spacing_event)
        grid_spacing_spin.bind("<Return>", self._on_gridline_spacing_event)
        grid_spacing_row.grid(row=19, column=0, sticky="w", pady=(2, 0))

        test_label = tk.Label(frame, text="Send test message to overlay:")
        test_label.grid(row=20, column=0, sticky="w", pady=(10, 0))

        test_row = tk.Frame(frame)
        test_entry = tk.Entry(test_row, textvariable=self._test_var, width=50)
        send_button = tk.Button(test_row, text="Send", command=self._on_send_click)
        test_entry.pack(side="left", fill="x", expand=True)
        send_button.pack(side="left", padx=(8, 0))
        test_row.grid(row=21, column=0, sticky="we", pady=(2, 0))
        frame.columnconfigure(0, weight=1)
        test_row.columnconfigure(0, weight=1)

        legacy_label = tk.Label(frame, text="Legacy edmcoverlay compatibility:")
        legacy_label.grid(row=22, column=0, sticky="w", pady=(10, 0))

        legacy_row = tk.Frame(frame)
        legacy_text_btn = tk.Button(legacy_row, text="Send legacy text", command=self._on_legacy_text)
        legacy_rect_btn = tk.Button(legacy_row, text="Send legacy rectangle", command=self._on_legacy_rect)
        legacy_text_btn.pack(side="left")
        legacy_rect_btn.pack(side="left", padx=(8, 0))
        legacy_row.grid(row=23, column=0, sticky="w", pady=(2, 0))

        status_label = tk.Label(frame, textvariable=self._status_var, wraplength=400, justify="left")
        status_label.grid(row=24, column=0, sticky="w", pady=(4, 0))

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        self._preferences.capture_output = bool(self._var_capture.get())
        self._preferences.overlay_opacity = float(self._var_opacity.get())
        self._preferences.show_connection_status = bool(self._var_show_status.get())
        self._preferences.log_payloads = bool(self._var_log_payloads.get())
        self._preferences.legacy_vertical_scale = float(self._var_legacy_scale.get())
        self._preferences.legacy_horizontal_scale = float(self._var_horizontal_scale.get())
        self._preferences.client_log_retention = max(1, int(self._var_log_retention.get()))
        self._preferences.gridlines_enabled = bool(self._var_gridlines_enabled.get())
        self._preferences.gridline_spacing = max(10, int(self._var_gridline_spacing.get()))
        self._preferences.window_width = max(640, int(self._var_window_width.get()))
        self._preferences.window_height = max(360, int(self._var_window_height.get()))
        self._preferences.follow_game_window = bool(self._var_follow_mode.get())
        self._apply_origin_values(self._var_origin_x.get(), self._var_origin_y.get(), persist=False)
        self._preferences.force_render = bool(self._var_force_render.get())
        if self._set_status:
            try:
                self._set_status(self._preferences.show_connection_status)
            except Exception as exc:
                self._status_var.set(f"Failed to update connection status: {exc}")
                return
        if self._set_log_payloads:
            try:
                self._set_log_payloads(self._preferences.log_payloads)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload logging: {exc}")
                return
        if self._set_legacy_scale:
            try:
                self._set_legacy_scale(self._preferences.legacy_vertical_scale)
            except Exception as exc:
                self._status_var.set(f"Failed to update legacy scale: {exc}")
                return
        if self._set_horizontal_scale:
            try:
                self._set_horizontal_scale(self._preferences.legacy_horizontal_scale)
            except Exception as exc:
                self._status_var.set(f"Failed to update horizontal scale: {exc}")
                return
        if self._set_follow_mode:
            try:
                self._set_follow_mode(self._preferences.follow_game_window)
            except Exception as exc:
                self._status_var.set(f"Failed to update follow mode: {exc}")
                return
        if self._set_force_render:
            try:
                self._set_force_render(self._preferences.force_render)
            except Exception as exc:
                self._status_var.set(f"Failed to update force-render option: {exc}")
                return
        self._preferences.save()

    # UI Callbacks --------------------------------------------------------

    def _on_send_click(self) -> None:
        message = self._test_var.get().strip()
        if not message:
            self._status_var.set("Enter a test message first.")
            return
        if not self._send_test:
            self._status_var.set("Overlay not running; message not sent.")
            return
        try:
            self._send_test(message)
        except Exception as exc:  # pragma: no cover - defensive UI handler
            self._status_var.set(f"Failed to send message: {exc}")
            return
        self._status_var.set("Test message sent to overlay.")

    def _on_capture_toggle(self) -> None:
        value = bool(self._var_capture.get())
        self._preferences.capture_output = value
        self._preferences.save()

    def _on_opacity_change(self, value: str) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        numeric = max(0.0, min(1.0, numeric))
        self._var_opacity.set(numeric)
        if self._set_opacity:
            try:
                self._set_opacity(numeric)
            except Exception as exc:
                self._status_var.set(f"Failed to update opacity: {exc}")
                return
        self._preferences.overlay_opacity = numeric
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

    def _on_log_payload_toggle(self) -> None:
        value = bool(self._var_log_payloads.get())
        self._preferences.log_payloads = value
        if self._set_log_payloads:
            try:
                self._set_log_payloads(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update payload logging: {exc}")
                return
        self._preferences.save()

    def _on_legacy_scale_change(self, value: str) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 1.0
        numeric = max(0.5, min(2.0, numeric))
        self._var_legacy_scale.set(numeric)
        self._legacy_scale_display.set(f"{numeric:.2f}×")
        self._preferences.legacy_vertical_scale = numeric
        if self._set_legacy_scale:
            try:
                self._set_legacy_scale(numeric)
            except Exception as exc:
                self._status_var.set(f"Failed to update legacy scale: {exc}")
                return
        self._preferences.save()

    def _on_horizontal_scale_change(self, value: str) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 1.0
        numeric = max(0.5, min(2.0, numeric))
        self._var_horizontal_scale.set(numeric)
        self._horizontal_scale_display.set(f"{numeric:.2f}×")
        self._preferences.legacy_horizontal_scale = numeric
        if self._set_horizontal_scale:
            try:
                self._set_horizontal_scale(numeric)
            except Exception as exc:
                self._status_var.set(f"Failed to update horizontal scale: {exc}")
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
        self._apply_gridline_spacing(self._var_gridline_spacing.get())

    def _on_gridline_spacing_event(self, event) -> None:  # type: ignore[override]
        widget_value = event.widget.get() if hasattr(event, "widget") else self._var_gridline_spacing.get()
        self._apply_gridline_spacing(widget_value)

    def _apply_gridline_spacing(self, raw_value: Any) -> None:
        try:
            spacing = int(raw_value)
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

    def _on_window_width_command(self) -> None:
        self._apply_window_size(self._var_window_width.get(), self._var_window_height.get())

    def _on_window_width_event(self, event) -> None:  # type: ignore[override]
        width = event.widget.get() if hasattr(event, "widget") else self._var_window_width.get()
        self._apply_window_size(width, self._var_window_height.get())

    def _on_window_height_command(self) -> None:
        self._apply_window_size(self._var_window_width.get(), self._var_window_height.get())

    def _on_window_height_event(self, event) -> None:  # type: ignore[override]
        height = event.widget.get() if hasattr(event, "widget") else self._var_window_height.get()
        self._apply_window_size(self._var_window_width.get(), height)

    def _apply_window_size(self, raw_width: Any, raw_height: Any) -> None:
        if self._window_size_guard:
            return
        try:
            width = int(raw_width)
        except (TypeError, ValueError):
            width = self._preferences.window_width
        try:
            height = int(raw_height)
        except (TypeError, ValueError):
            height = self._preferences.window_height
        width = max(640, width)
        height = max(360, height)
        self._window_size_guard = True
        try:
            if self._var_window_width.get() != width:
                self._var_window_width.set(width)
            if self._var_window_height.get() != height:
                self._var_window_height.set(height)
        finally:
            self._window_size_guard = False
        if self._set_window_size:
            try:
                self._set_window_size(width, height)
            except Exception as exc:
                self._status_var.set(f"Failed to update window size: {exc}")
                return
        else:
            if self._set_window_width:
                try:
                    self._set_window_width(width)
                except Exception as exc:
                    self._status_var.set(f"Failed to update window width: {exc}")
                    return
            if self._set_window_height:
                try:
                    self._set_window_height(height)
                except Exception as exc:
                    self._status_var.set(f"Failed to update window height: {exc}")
                    return
            self._preferences.window_width = width
            self._preferences.window_height = height
        if self._set_window_size:
            # The callback updates preferences in place; ensure local copy reflects latest values.
            self._preferences.window_width = width
            self._preferences.window_height = height
        self._preferences.save()

    def _on_follow_toggle(self) -> None:
        value = bool(self._var_follow_mode.get())
        self._preferences.follow_game_window = value
        self._update_controls_state()
        if self._set_follow_mode:
            try:
                self._set_follow_mode(value)
            except Exception as exc:
                self._status_var.set(f"Failed to update follow mode: {exc}")
                return
        self._preferences.save()

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

    def _on_origin_entry_event(self, event) -> None:  # type: ignore[override]
        x_raw = self._var_origin_x.get()
        y_raw = self._var_origin_y.get()
        if hasattr(event, "widget"):
            widget_value = event.widget.get()
            if event.widget == self._origin_entries[0]:
                x_raw = widget_value
            elif len(self._origin_entries) > 1 and event.widget == self._origin_entries[1]:
                y_raw = widget_value
        self._apply_origin_values(x_raw, y_raw)

    def _apply_origin_values(self, raw_x: Any, raw_y: Any, persist: bool = True) -> None:
        try:
            origin_x = int(raw_x)
        except (TypeError, ValueError):
            origin_x = self._preferences.origin_x
        try:
            origin_y = int(raw_y)
        except (TypeError, ValueError):
            origin_y = self._preferences.origin_y
        origin_x = max(0, origin_x)
        origin_y = max(0, origin_y)
        self._var_origin_x.set(str(origin_x))
        self._var_origin_y.set(str(origin_y))
        changed = (origin_x != self._preferences.origin_x) or (origin_y != self._preferences.origin_y)
        self._preferences.origin_x = origin_x
        self._preferences.origin_y = origin_y
        if self._set_origin and changed:
            try:
                self._set_origin(origin_x, origin_y)
            except Exception as exc:
                self._status_var.set(f"Failed to update overlay origin: {exc}")
                return
        if persist:
            self._preferences.save()

    def _on_reset_origin_click(self) -> None:
        self._var_origin_x.set("0")
        self._var_origin_y.set("0")
        self._apply_origin_values(0, 0)
        if self._reset_origin:
            try:
                self._reset_origin()
            except Exception as exc:
                self._status_var.set(f"Failed to reset origin: {exc}")

    def _register_follow_label(self, label) -> None:
        try:
            default = label.cget("foreground")
        except Exception:
            default = None
        self._follow_labels.append(label)
        self._follow_label_defaults[label] = default if default else None

    def _update_controls_state(self) -> None:
        follow_enabled = bool(self._var_follow_mode.get())
        origin_state = "disabled" if follow_enabled else "normal"
        for widget in self._origin_entries:
            try:
                widget.config(state=origin_state)
            except Exception:
                continue
        if self._origin_reset_button is not None:
            try:
                self._origin_reset_button.config(state=origin_state)
            except Exception:
                pass
        size_state = "disabled" if follow_enabled else "normal"
        for widget in getattr(self, "_size_controls", ()):
            try:
                widget.config(state=size_state)
            except Exception:
                pass
        for label in self._follow_labels:
            default_fg = self._follow_label_defaults.get(label)
            target = self._disabled_label_fg if follow_enabled else (default_fg if default_fg is not None else "")
            try:
                label.config(foreground=target)
            except Exception:
                continue

    def update_origin_fields(self, origin_x: int, origin_y: int) -> None:
        origin_x = max(0, int(origin_x))
        origin_y = max(0, int(origin_y))
        self._var_origin_x.set(str(origin_x))
        self._var_origin_y.set(str(origin_y))

    def _legacy_overlay(self):
        if self._legacy_client is None:
            try:
                from EDMCOverlay import edmcoverlay
            except ImportError:
                from . import overlay_api  # pragma: no cover - fallback
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
