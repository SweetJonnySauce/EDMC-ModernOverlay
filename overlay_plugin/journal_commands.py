"""Helpers for responding to in-game chat commands.

The overlay plugin does not receive keyboard/mouse focus while Elite Dangerous
is running, so the only ergonomic way to trigger quick actions while playing is
through Elite's chat system. This module mirrors the pattern used by plugins
like EDR: watch for ``SendText`` journal events authored by the local CMDR,
carve out a small namespace of bang-prefixed commands (``!overlay …``), and
translate them into overlay actions.

Only a couple of workflow-driven commands are implemented for now. Handling the
parsing in a helper keeps :mod:`load.py` from accumulating even more logic and
provides a focused surface for future additions.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable, Mapping, Optional


_LOGGER = logging.getLogger("EDMC.ModernOverlay.Commands")


@dataclass
class _OverlayCommandContext:
    """Lightweight indirection that exposes just the callbacks we need."""

    send_message: Callable[[str], None]
    cycle_next: Optional[Callable[[], None]] = None
    cycle_prev: Optional[Callable[[], None]] = None
    launch_controller: Optional[Callable[[], None]] = None


class JournalCommandHelper:
    """Parse journal ``SendText`` events and dispatch overlay commands."""

    _HELP_TEXT = (
        "Overlay commands: !overlay (launch controller), !overlay next (cycle forward), "
        "!overlay prev (cycle backward), !overlay help"
    )

    def __init__(self, context: _OverlayCommandContext) -> None:
        self._ctx = context

    # Public API ---------------------------------------------------------

    def handle_entry(self, entry: Mapping[str, object]) -> bool:
        """Attempt to process a ``SendText`` journal entry.

        Returns ``True`` when the entry contained a supported overlay command.
        """

        if (entry.get("event") or "").lower() != "sendtext":
            return False
        raw_message = entry.get("Message")
        if not isinstance(raw_message, str):
            return False
        message = raw_message.strip()
        if not message.startswith("!"):
            return False
        content = message[1:].strip()
        if not content:
            return False
        tokens = content.split()
        if not tokens:
            return False
        root = tokens[0].lower()
        args = tokens[1:]
        if root == "overlay":
            handled = self._handle_overlay_command(args)
            if handled:
                _LOGGER.debug("Handled in-game overlay command: %s", message)
            return handled
        return False

    # Implementation details --------------------------------------------

    def _handle_overlay_command(self, args: list[str]) -> bool:
        if not args:
            return self._launch_controller()

        action = args[0].lower()
        if action in {"launch", "open", "controller", "config"}:
            return self._launch_controller()
        if action in {"help", "?"}:
            self._emit_help()
            return True
        if action in {"next", "n"}:
            self._invoke_cycle(self._ctx.cycle_next, success_message="Overlay cycle: next payload.")
            return True
        if action in {"prev", "previous", "p"}:
            self._invoke_cycle(self._ctx.cycle_prev, success_message="Overlay cycle: previous payload.")
            return True

        self._ctx.send_message(f"Unknown overlay command: {action}. Try !overlay help.")
        return True

    def _emit_help(self) -> None:
        self._ctx.send_message(self._HELP_TEXT)

    def _launch_controller(self) -> bool:
        callback = self._ctx.launch_controller
        if callback is None:
            self._ctx.send_message("Overlay Controller command unavailable.")
            return True
        try:
            callback()
        except RuntimeError as exc:
            self._ctx.send_message(f"Overlay Controller launch failed: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.warning("Overlay Controller callback failed: %s", exc)
            self._ctx.send_message("Overlay Controller launch failed; see EDMC log.")
        else:
            self._ctx.send_message("Overlay Controller launching...")
        return True

    def _invoke_cycle(self, callback: Optional[Callable[[], None]], *, success_message: str) -> None:
        if callback is None:
            self._ctx.send_message("Overlay cycle commands are unavailable right now.")
            return
        try:
            callback()
        except RuntimeError as exc:
            self._ctx.send_message(f"Overlay cycle unavailable: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.warning("Overlay cycle callback failed: %s", exc)
            self._ctx.send_message("Overlay cycle failed; see EDMC log for details.")
        else:
            self._ctx.send_message(success_message)


def build_command_helper(
    plugin_runtime: object,
    logger: Optional[logging.Logger] = None,
) -> JournalCommandHelper:
    """Construct a :class:`JournalCommandHelper` for the active plugin runtime."""

    log = logger or _LOGGER

    def _send_overlay_message(text: str) -> None:
        try:
            plugin_runtime.send_test_message(text)
        except Exception as exc:  # pragma: no cover - defensive guard
            log.warning("Failed to send overlay response '%s': %s", text, exc)

    context = _OverlayCommandContext(
        send_message=_send_overlay_message,
        cycle_next=getattr(plugin_runtime, "cycle_payload_next", None),
        cycle_prev=getattr(plugin_runtime, "cycle_payload_prev", None),
        launch_controller=getattr(plugin_runtime, "launch_overlay_controller", None),
    )
    return JournalCommandHelper(context)
