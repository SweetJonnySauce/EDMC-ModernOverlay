"""Drop-in compatibility layer for legacy `edmcoverlay` consumers."""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

try:
    from overlay_plugin.overlay_api import send_overlay_message
except Exception:  # pragma: no cover - EDMC will make this available at runtime
    def send_overlay_message(_payload: Mapping[str, Any]) -> bool:  # type: ignore
        return False

LOGGER = logging.getLogger("EDMC.ModernOverlay.Legacy")


def trace(msg: str) -> str:
    LOGGER.debug("Legacy trace: %s", msg)
    return msg


def ensure_service(*_args, **_kwargs) -> None:
    """Legacy helper was responsible for launching an .exe.

    Modern Overlay manages its own watchdog so nothing to do here.
    """


class Overlay:
    """Compatibility client emulating `edmcoverlay.Overlay`."""

    def __init__(self, server: str = "127.0.0.1", port: Optional[int] = None, args: Optional[list[str]] = None) -> None:
        self.server = server
        self.port = port
        self.args = args or []
        self._connected = False

    def connect(self) -> None:
        """Original client opened a socket; here it's a no-op."""

        self._connected = True

    def send_raw(self, msg: Dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            raise TypeError("send_raw expects a dict payload")
        command = msg.get("command")
        if command == "exit":
            send_overlay_message({"event": "LegacyOverlay", "type": "clear_all"})
            return
        self._emit_payload({"type": "raw", "raw": dict(msg)})

    def send_message(
        self,
        msgid: str,
        text: str,
        color: str,
        x: int,
        y: int,
        *,
        ttl: int = 4,
        size: str = "normal",
    ) -> None:
        payload = {
            "type": "message",
            "id": msgid,
            "text": text,
            "color": color,
            "x": int(x),
            "y": int(y),
            "ttl": ttl,
            "size": size,
        }
        self._emit_payload(payload)

    def send_shape(
        self,
        shapeid: str,
        shape: str,
        color: str,
        fill: str,
        x: int,
        y: int,
        w: int,
        h: int,
        ttl: int,
    ) -> None:
        payload = {
            "type": "shape",
            "shape": shape,
            "id": shapeid,
            "color": color,
            "fill": fill,
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "ttl": ttl,
        }
        self._emit_payload(payload)

    # ------------------------------------------------------------------

    def _emit_payload(self, payload: Mapping[str, Any]) -> None:
        ensure_service()
        message = {
            "event": "LegacyOverlay",
            **payload,
        }
        if not send_overlay_message(message):
            raise RuntimeError("EDMC-ModernOverlay is not available to accept messages")


# Backwards compatibility: some callers import `Overlay` at module level
__all__ = ["Overlay", "ensure_service", "trace"]
