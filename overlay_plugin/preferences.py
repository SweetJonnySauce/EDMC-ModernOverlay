"""Preferences management and Tk UI for the Modern Overlay plugin."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional


PREFERENCES_FILE = "overlay_settings.json"


@dataclass
class Preferences:
    """Simple JSON-backed preferences store."""

    plugin_dir: Path
    capture_output: bool = True
    overlay_opacity: float = 0.0
    show_connection_status: bool = False
    log_payloads: bool = False
    client_log_retention: int = 5
    gridlines_enabled: bool = False
    gridline_spacing: int = 120
    force_render: bool = False
    force_xwayland: bool = False
    show_debug_overlay: bool = False

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

    def save(self) -> None:
        payload: Dict[str, Any] = {
            "capture_output": bool(self.capture_output),
            "overlay_opacity": float(self.overlay_opacity),
            "show_connection_status": bool(self.show_connection_status),
            "log_payloads": bool(self.log_payloads),
            "client_log_retention": int(self.client_log_retention),
            "gridlines_enabled": bool(self.gridlines_enabled),
            "gridline_spacing": int(self.gridline_spacing),
            "force_render": bool(self.force_render),
            "force_xwayland": bool(self.force_xwayland),
            "show_debug_overlay": bool(self.show_debug_overlay),
        }
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PreferencesPanel:
    """Builds a Tkinter frame that edits Modern Overlay preferences."""

    def __init__(
        self,
        parent,
        preferences: Preferences,
        send_test_callback: Optional[Callable[[str, Optional[int], Optional[int]], None]] = None,
        set_opacity_callback: Optional[Callable[[float], None]] = None,
        set_status_callback: Optional[Callable[[bool], None]] = None,
        set_log_payloads_callback: Optional[Callable[[bool], None]] = None,
        set_gridlines_enabled_callback: Optional[Callable[[bool], None]] = None,
        set_gridline_spacing_callback: Optional[Callable[[int], None]] = None,
        set_force_render_callback: Optional[Callable[[bool], None]] = None,
        set_debug_overlay_callback: Optional[Callable[[bool], None]] = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk
        import myNotebook as nb

        self._preferences = preferences
        self._style = ttk.Style()
        self._frame_style, self._spinbox_style, self._scale_style = self._init_theme_styles(nb)
        self._var_capture = tk.BooleanVar(value=preferences.capture_output)
        self._var_opacity = tk.DoubleVar(value=preferences.overlay_opacity)
        self._var_show_status = tk.BooleanVar(value=preferences.show_connection_status)
        self._var_log_payloads = tk.BooleanVar(value=preferences.log_payloads)
        self._var_gridlines_enabled = tk.BooleanVar(value=preferences.gridlines_enabled)
        self._var_gridline_spacing = tk.IntVar(value=max(10, int(preferences.gridline_spacing)))
        self._var_force_render = tk.BooleanVar(value=preferences.force_render)

        self._send_test = send_test_callback
        self._set_opacity = set_opacity_callback
        self._set_status = set_status_callback
        self._set_log_payloads = set_log_payloads_callback
        self._set_gridlines_enabled = set_gridlines_enabled_callback
        self._set_gridline_spacing = set_gridline_spacing_callback
        self._set_force_render = set_force_render_callback
        self._set_debug_overlay = set_debug_overlay_callback

        self._legacy_client = None
        self._test_var = tk.StringVar()
        self._test_x_var = tk.StringVar()
        self._test_y_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")
        self._var_debug_overlay = tk.BooleanVar(value=preferences.show_debug_overlay)

        frame = nb.Frame(parent)

        checkbox = nb.Checkbutton(
            frame,
            text="Enable overlay stdout/stderr capture",
            variable=self._var_capture,
            onvalue=True,
            offvalue=False,
            command=self._on_capture_toggle,
        )
        helper = nb.Label(
            frame,
            text=(
                "Capture overlay stdout/stderr when EDMC logging is set to DEBUG "
                "(useful for troubleshooting). Changes require restarting the overlay."
            ),
            wraplength=400,
            justify="left",
        )
        checkbox.grid(row=0, column=0, sticky="w")
        helper.grid(row=1, column=0, sticky="w", pady=(2, 0))

        status_checkbox = nb.Checkbutton(
            frame,
            text="Show connection status message at bottom of overlay",
            variable=self._var_show_status,
            onvalue=True,
            offvalue=False,
            command=self._on_show_status_toggle,
        )
        status_checkbox.grid(row=2, column=0, sticky="w", pady=(10, 0))

        log_checkbox = nb.Checkbutton(
            frame,
            text="Send overlay payloads to the EDMC log",
            variable=self._var_log_payloads,
            onvalue=True,
            offvalue=False,
            command=self._on_log_payload_toggle,
        )
        log_checkbox.grid(row=3, column=0, sticky="w", pady=(4, 0))

        debug_checkbox = nb.Checkbutton(
            frame,
            text="Show debug overlay metrics (frame size, scaling)",
            variable=self._var_debug_overlay,
            onvalue=True,
            offvalue=False,
            command=self._on_debug_overlay_toggle,
        )
        debug_checkbox.grid(row=4, column=0, sticky="w", pady=(6, 0))

        retention_row = ttk.Frame(frame, style=self._frame_style)
        retention_label = nb.Label(retention_row, text="Overlay client log files to keep (rotate when current file grows).")
        retention_label.pack(side="left")
        self._retention_var = tk.IntVar(value=int(self._preferences.client_log_retention))
        retention_spin = ttk.Spinbox(
            retention_row,
            from_=1,
            to=20,
            increment=1,
            width=5,
            command=self._on_log_retention_command,
            textvariable=self._retention_var,
            style=self._spinbox_style,
        )
        retention_spin.pack(side="left", padx=(6, 0))
        retention_spin.bind("<FocusOut>", self._on_log_retention_event)
        retention_spin.bind("<Return>", self._on_log_retention_event)
        retention_row.grid(row=5, column=0, sticky="w", pady=(6, 0))

        opacity_label = nb.Label(
            frame,
            text="Overlay background opacity (0.0 transparent – 1.0 opaque). Alt+drag is enabled when opacity > 0.5.",
        )
        opacity_label.grid(row=6, column=0, sticky="w", pady=(10, 0))

        opacity_row = ttk.Frame(frame, style=self._frame_style)
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
        opacity_row.grid(row=7, column=0, sticky="we")

        force_checkbox = nb.Checkbutton(
            frame,
            text="Keep overlay visible when Elite Dangerous is not the foreground window",
            variable=self._var_force_render,
            onvalue=True,
            offvalue=False,
            command=self._on_force_render_toggle,
        )
        force_checkbox.grid(row=8, column=0, sticky="w", pady=(10, 0))

        grid_checkbox = nb.Checkbutton(
            frame,
            text="Show light gridlines over the overlay background",
            variable=self._var_gridlines_enabled,
            onvalue=True,
            offvalue=False,
            command=self._on_gridlines_toggle,
        )
        grid_checkbox.grid(row=9, column=0, sticky="w", pady=(8, 0))

        grid_spacing_row = ttk.Frame(frame, style=self._frame_style)
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
        grid_spacing_row.grid(row=10, column=0, sticky="w", pady=(2, 0))

        test_label = nb.Label(frame, text="Send test message to overlay:")
        test_label.grid(row=11, column=0, sticky="w", pady=(10, 0))

        test_row = ttk.Frame(frame, style=self._frame_style)
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
        test_row.grid(row=12, column=0, sticky="we", pady=(2, 0))
        frame.columnconfigure(0, weight=1)
        test_row.columnconfigure(0, weight=1)

        legacy_label = nb.Label(frame, text="Legacy edmcoverlay compatibility:")
        legacy_label.grid(row=13, column=0, sticky="w", pady=(10, 0))

        legacy_row = ttk.Frame(frame, style=self._frame_style)
        legacy_text_btn = nb.Button(legacy_row, text="Send legacy text", command=self._on_legacy_text)
        legacy_rect_btn = nb.Button(legacy_row, text="Send legacy rectangle", command=self._on_legacy_rect)
        legacy_text_btn.pack(side="left")
        legacy_rect_btn.pack(side="left", padx=(8, 0))
        legacy_row.grid(row=14, column=0, sticky="w", pady=(2, 0))

        status_label = nb.Label(frame, textvariable=self._status_var, wraplength=400, justify="left")
        status_label.grid(row=15, column=0, sticky="w", pady=(4, 0))

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        self._preferences.save()

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

    def _on_log_retention_command(self) -> None:
        self._apply_log_retention()

    def _on_log_retention_event(self, _event) -> None:  # pragma: no cover - Tk event
        self._apply_log_retention()

    def _apply_log_retention(self) -> None:
        try:
            value = int(self._retention_var.get())
        except Exception:
            value = self._preferences.client_log_retention
        value = max(1, value)
        self._preferences.client_log_retention = value
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
