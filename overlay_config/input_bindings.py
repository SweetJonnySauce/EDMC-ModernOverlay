"""Infrastructure for configurable control schemes and key bindings."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

DEFAULT_CONFIG_PATH = Path(__file__).with_name("keybindings.json")

# Default layout that can be extended by the user later on.
DEFAULT_CONFIG = {
    "active_scheme": "keyboard_default",
    "schemes": {
        "keyboard_default": {
            "device_type": "keyboard",
            "display_name": "Keyboard (default)",
            "bindings": {
                "toggle_placement": ["<space>"],
                "close_app": ["<Escape>"],
            },
        }
    },
}


@dataclass
class ControlScheme:
    """Container for a set of bindings and some metadata."""

    name: str
    device_type: str
    display_name: str
    bindings: Dict[str, List[str]]


@dataclass
class BindingConfig:
    """Representation of the configuration file contents."""

    schemes: Dict[str, ControlScheme]
    active_scheme: str
    source_path: Path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "BindingConfig":
        """Load config from disk, creating the default file if missing."""

        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))

        payload = json.loads(path.read_text())
        schemes = {
            name: ControlScheme(
                name=name,
                device_type=spec.get("device_type", "keyboard"),
                display_name=spec.get("display_name", name),
                bindings={
                    action: list(inputs or [])
                    for action, inputs in (spec.get("bindings") or {}).items()
                },
            )
            for name, spec in payload.get("schemes", {}).items()
        }

        active = payload.get("active_scheme")
        if active not in schemes:
            raise ValueError(
                f"Active scheme '{active}' is not defined in keybindings file {path}"
            )

        return cls(schemes=schemes, active_scheme=active, source_path=path)

    def get_scheme(self, name: Optional[str] = None) -> ControlScheme:
        """Return the requested scheme or the currently active one."""

        scheme_name = name or self.active_scheme
        try:
            return self.schemes[scheme_name]
        except KeyError as exc:
            raise ValueError(f"Unknown control scheme '{scheme_name}'") from exc


class BindingManager:
    """Handles applying bindings for the active scheme to a Tk widget."""

    def __init__(self, widget: "tk.Misc", config: BindingConfig) -> None:  # type: ignore[name-defined]  # noqa: F821
        self.widget = widget
        self.config = config
        self._handlers: Dict[str, Callable] = {}
        self._bound_sequences: List[str] = []
        self._cached_wrappers: Dict[str, Callable] = {}

    def register_action(self, action_name: str, handler: Callable) -> None:
        """Associate an action identifier with a callable."""

        self._handlers[action_name] = handler
        # Drop cached wrapper so a future activate() re-evaluates the signature.
        self._cached_wrappers.pop(action_name, None)

    def activate(self, scheme_name: Optional[str] = None) -> None:
        """Apply the bindings for the currently active scheme."""

        self._unbind_sequences(self._bound_sequences)
        self._bound_sequences.clear()

        scheme = self.config.get_scheme(scheme_name)
        for action, sequences in scheme.bindings.items():
            if action not in self._handlers:
                continue
            callback = self._get_wrapped_handler(action)
            for sequence in sequences:
                normalized = self._normalize_sequence(sequence)
                self.widget.bind(normalized, callback, add="+")
                self._bound_sequences.append(normalized)

    def _unbind_sequences(self, sequences: Iterable[str]) -> None:
        for sequence in sequences:
            try:
                self.widget.unbind(sequence)
            except Exception:
                # Some widgets do not implement unbind; ignore in that case.
                pass

    def _get_wrapped_handler(self, action: str) -> Callable:
        if action in self._cached_wrappers:
            return self._cached_wrappers[action]

        handler = self._handlers[action]
        takes_event = self._handler_accepts_event(handler)

        def _callback(event: object) -> None:
            if takes_event:
                handler(event)
            else:
                handler()

        self._cached_wrappers[action] = _callback
        return _callback

    @staticmethod
    def _handler_accepts_event(handler: Callable) -> bool:
        try:
            signature = inspect.signature(handler)
        except (TypeError, ValueError):
            return False
        params = list(signature.parameters.values())
        return len(params) >= 1

    @staticmethod
    def _normalize_sequence(sequence: str) -> str:
        seq = sequence.strip()
        if not seq:
            raise ValueError("Binding sequence cannot be empty")
        if not seq.startswith("<"):
            seq = f"<{seq}>"
        return seq
