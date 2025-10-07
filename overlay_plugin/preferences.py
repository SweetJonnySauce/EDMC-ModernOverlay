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
    legacy_vertical_scale: float = 1.0

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

    def save(self) -> None:
        payload: Dict[str, Any] = {
            "capture_output": bool(self.capture_output),
            "overlay_opacity": float(self.overlay_opacity),
            "show_connection_status": bool(self.show_connection_status),
            "log_payloads": bool(self.log_payloads),
            "legacy_vertical_scale": float(self.legacy_vertical_scale),
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
    ) -> None:
        import tkinter as tk
        import myNotebook as nb

        self._preferences = preferences
        self._var_capture = tk.BooleanVar(value=preferences.capture_output)
        self._var_opacity = tk.DoubleVar(value=preferences.overlay_opacity)
        self._var_show_status = tk.BooleanVar(value=preferences.show_connection_status)
        self._var_log_payloads = tk.BooleanVar(value=preferences.log_payloads)
        self._var_legacy_scale = tk.DoubleVar(value=preferences.legacy_vertical_scale)
        self._send_test = send_test_callback
        self._test_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")
        self._legacy_client = None
        self._set_opacity = set_opacity_callback
        self._set_status = set_status_callback
        self._set_log_payloads = set_log_payloads_callback
        self._set_legacy_scale = set_legacy_scale_callback
        self._legacy_scale_display = tk.StringVar(value=f"{preferences.legacy_vertical_scale:.2f}×")

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

        legacy_scale_label = tk.Label(
            frame,
            text="Legacy overlay vertical scale (1.00× keeps original spacing).",
        )
        legacy_scale_label.grid(row=4, column=0, sticky="w", pady=(10, 0))

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
        legacy_scale_row.grid(row=5, column=0, sticky="we")

        opacity_label = tk.Label(
            frame,
            text=(
                "Overlay background opacity (0.0 transparent – 1.0 opaque). "
                "Alt+drag is enabled when opacity > 0.5."
            ),
        )
        opacity_label.grid(row=6, column=0, sticky="w", pady=(10, 0))

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
        opacity_row.grid(row=7, column=0, sticky="we")

        test_label = tk.Label(frame, text="Send test message to overlay:")
        test_label.grid(row=8, column=0, sticky="w", pady=(10, 0))

        test_row = tk.Frame(frame)
        test_entry = tk.Entry(test_row, textvariable=self._test_var, width=50)
        send_button = tk.Button(test_row, text="Send", command=self._on_send_click)
        test_entry.pack(side="left", fill="x", expand=True)
        send_button.pack(side="left", padx=(8, 0))
        test_row.grid(row=9, column=0, sticky="we", pady=(2, 0))
        frame.columnconfigure(0, weight=1)
        test_row.columnconfigure(0, weight=1)

        legacy_label = tk.Label(frame, text="Legacy edmcoverlay compatibility:")
        legacy_label.grid(row=10, column=0, sticky="w", pady=(10, 0))

        legacy_row = tk.Frame(frame)
        legacy_text_btn = tk.Button(legacy_row, text="Send legacy text", command=self._on_legacy_text)
        legacy_rect_btn = tk.Button(legacy_row, text="Send legacy rectangle", command=self._on_legacy_rect)
        legacy_text_btn.pack(side="left")
        legacy_rect_btn.pack(side="left", padx=(8, 0))
        legacy_row.grid(row=11, column=0, sticky="w", pady=(2, 0))

        status_label = tk.Label(frame, textvariable=self._status_var, wraplength=400, justify="left", fg="#808080")
        status_label.grid(row=12, column=0, sticky="w", pady=(4, 0))

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
