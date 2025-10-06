"""Preferences management and Tk UI for the Modern Overlay plugin."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


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

    def __init__(self, parent, preferences: Preferences) -> None:
        import tkinter as tk
        import myNotebook as nb

        self._preferences = preferences
        self._var_capture = tk.BooleanVar(value=preferences.capture_output)

        frame = nb.Frame(parent)
        description = (
            "Capture overlay stdout/stderr when EDMC logging is set to DEBUG "
            "(useful for troubleshooting)"
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

        self._frame = frame

    @property
    def frame(self):  # pragma: no cover - Tk integration
        return self._frame

    def apply(self) -> None:
        self._preferences.capture_output = bool(self._var_capture.get())
        self._preferences.save()
