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


def _legacy_coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _legacy_coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    stringified = str(value)
    return stringified if stringified else None


def normalise_legacy_payload(message: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate raw legacy overlay payloads into structured events."""

    msg = dict(message)

    def _lookup(*keys: str) -> Any:
        for key in keys:
            if key in msg:
                return msg[key]
        return None

    item_id = _legacy_coerce_str(_lookup("id", "Id"))
    text = _lookup("text", "Text")
    shape = _legacy_coerce_str(_lookup("shape", "Shape"))
    ttl = _legacy_coerce_int(_lookup("ttl", "TTL"), default=4)

    if text is not None and text != "":
        return {
            "type": "message",
            "id": item_id or "",
            "text": str(text),
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }

    if shape:
        shape_lower = shape.lower()
        payload: Dict[str, Any] = {
            "type": "shape",
            "shape": shape,
            "id": item_id or "",
            "color": _lookup("color", "Color") or "white",
            "fill": _lookup("fill", "Fill"),
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "w": _legacy_coerce_int(_lookup("w", "W"), 0),
            "h": _legacy_coerce_int(_lookup("h", "H"), 0),
            "ttl": ttl,
        }
        vector = _lookup("vector", "Vector")
        if shape_lower == "vect":
            if not isinstance(vector, list) or len(vector) < 2:
                LOGGER.warning("Dropping vect payload with insufficient points: id=%s vector=%s", item_id, vector)
                return None
            payload["vector"] = vector
        else:
            if isinstance(vector, list):
                payload["vector"] = vector
        return payload

    if ttl <= 0 and item_id:
        return {
            "type": "legacy_clear",
            "id": item_id,
            "ttl": ttl,
        }

    if item_id and text == "":
        return {
            "type": "message",
            "id": item_id,
            "text": "",
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }

    raw_value = dict(msg)
    return {"type": "raw", "raw": raw_value, "id": item_id or "", "ttl": ttl}


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
        original_message = dict(msg)
        command = msg.get("command")
        if command is not None:
            self._handle_command(command)
            return

        payload = self._normalise_raw_payload(dict(msg))
        if payload is None:
            LOGGER.debug("Legacy raw payload dropped (unable to normalise): %s", msg)
            return
        payload.setdefault("legacy_raw", original_message)
        self._emit_payload(payload)

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

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        return _legacy_coerce_int(value, default)

    @staticmethod
    def _coerce_str(value: Any) -> Optional[str]:
        return _legacy_coerce_str(value)

    def _handle_command(self, command: Any) -> None:
        command_str = self._coerce_str(command)
        if not command_str:
            return
        lowered = command_str.lower()
        if lowered == "exit":
            send_overlay_message({"event": "LegacyOverlay", "type": "clear_all"})
            return
        if lowered == "noop":
            return
        LOGGER.debug("Ignoring unknown legacy overlay command: %s", command_str)

    def _normalise_raw_payload(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert legacy edmcoverlay payloads into structured events.

        Returns ``None`` when the payload cannot be translated into a supported
        message.
        """

        return normalise_legacy_payload(msg)


# Backwards compatibility: some callers import `Overlay` at module level
__all__ = ["Overlay", "ensure_service", "trace", "normalise_legacy_payload"]
