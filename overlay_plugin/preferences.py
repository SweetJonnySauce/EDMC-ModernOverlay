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

    def save(self) -> None:
        payload: Dict[str, Any] = {"capture_output": bool(self.capture_output)}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PreferencesPanel:
    """Builds a Tkinter frame that edits Modern Overlay preferences."""

    def __init__(self, parent, preferences: Preferences, send_test_callback: Optional[Callable[[str], None]] = None) -> None:
        import tkinter as tk
        import myNotebook as nb

        self._preferences = preferences
        self._var_capture = tk.BooleanVar(value=preferences.capture_output)
        self._send_test = send_test_callback
        self._test_var = tk.StringVar()
        self._status_var = tk.StringVar(value="")

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

        test_label = tk.Label(frame, text="Send test message to overlay:")
        test_label.grid(row=2, column=0, sticky="w", pady=(10, 0))

        test_row = tk.Frame(frame)
        test_entry = tk.Entry(test_row, textvariable=self._test_var, width=50)
        send_button = tk.Button(test_row, text="Send", command=self._on_send_click)
        test_entry.pack(side="left", fill="x", expand=True)
        send_button.pack(side="left", padx=(8, 0))
        test_row.grid(row=3, column=0, sticky="we", pady=(2, 0))
        frame.columnconfigure(0, weight=1)
        test_row.columnconfigure(0, weight=1)

        status_label = tk.Label(frame, textvariable=self._status_var, wraplength=400, justify="left", fg="#808080")
        status_label.grid(row=4, column=0, sticky="w", pady=(4, 0))

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        self._preferences.capture_output = bool(self._var_capture.get())
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
