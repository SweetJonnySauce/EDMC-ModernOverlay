"""Drop-in compatibility layer for legacy `edmcoverlay` consumers."""
from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterable, Sequence
from typing import Any, Dict, Mapping, Optional

try:  # Import relative to package when bundled within EDMCModernOverlay
    from ..version import __version__ as _MODERN_OVERLAY_VERSION
except Exception:  # pragma: no cover - fallback when running directly from checkout
    from version import __version__ as _MODERN_OVERLAY_VERSION

try:
    # Prefer package import so we share the same module instance where the plugin registers the publisher.
    from ..overlay_plugin import overlay_api as _overlay_api  # type: ignore
    if "overlay_plugin.overlay_api" not in sys.modules:
        sys.modules["overlay_plugin.overlay_api"] = _overlay_api
    send_overlay_message = _overlay_api.send_overlay_message  # type: ignore
except Exception:  # pragma: no cover - fall back for standalone/legacy contexts
    try:
        from overlay_plugin import overlay_api as _overlay_api  # type: ignore
        send_overlay_message = _overlay_api.send_overlay_message  # type: ignore
    except Exception:
        def send_overlay_message(_payload: Mapping[str, Any]) -> bool:  # type: ignore
            return False

LOGGER = logging.getLogger("EDMC.ModernOverlay.Legacy")
MODERN_OVERLAY_IDENTITY: Dict[str, str] = {
    "plugin": "EDMCModernOverlay",
    "version": _MODERN_OVERLAY_VERSION,
}
"""Public marker advertised to other plugins to detect Modern Overlay."""

_UNAVAILABLE_WARN_TS: float = 0.0
_UNAVAILABLE_SUPPRESSED: int = 0


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


_CONTENT_KEYS = {
    "text",
    "Text",
    "shape",
    "Shape",
    "vector",
    "Vector",
    "message",
    "Message",
    "x",
    "X",
    "y",
    "Y",
    "w",
    "W",
    "h",
    "H",
}


def _is_id_only_payload(message: Mapping[str, Any]) -> bool:
    if not isinstance(message, Mapping):
        return False
    for key in _CONTENT_KEYS:
        if key not in message:
            continue
        value = message[key]
        if isinstance(value, str):
            if value.strip():
                return False
        elif isinstance(value, Mapping):
            if value:
                return False
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if len(value):
                return False
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
            return False
        elif value not in (None, 0, 0.0, False):
            return False
    return True


def _point_has_marker_or_text(point: Mapping[str, Any]) -> bool:
    marker = point.get("marker")
    if marker:
        return True
    text = point.get("text")
    if text is None:
        return False
    return str(text) != ""


def _normalise_vector_points(
    raw_vector: Any,
    *,
    item_id: Optional[str],
    plugin: Optional[str],
) -> Optional[list[Dict[str, Any]]]:
    if not isinstance(raw_vector, list):
        return None
    points: list[Dict[str, Any]] = []
    for entry in raw_vector:
        if isinstance(entry, Mapping):
            try:
                points.append(dict(entry))
            except Exception:
                continue
    if len(points) >= 2:
        return points
    if len(points) == 1:
        return points if _point_has_marker_or_text(points[0]) else None
    return None


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
    plugin = _legacy_coerce_str(_lookup("plugin", "Plugin", "plugin_name", "PluginName", "source_plugin"))

    if text is not None and text != "":
        payload = {
            "type": "message",
            "id": item_id or "",
            "text": str(text),
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }
        if plugin:
            payload["plugin"] = plugin
        return payload

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
            normalised_points = _normalise_vector_points(vector, item_id=item_id, plugin=plugin)
            if normalised_points is None:
                LOGGER.warning("Dropping vect payload with insufficient points: id=%s vector=%s", item_id, vector)
                return None
            payload["vector"] = normalised_points
        else:
            if isinstance(vector, list):
                payload["vector"] = vector
        if plugin:
            payload["plugin"] = plugin
        return payload

    if ttl <= 0 and item_id:
        payload = {
            "type": "legacy_clear",
            "id": item_id,
            "ttl": ttl,
        }
        if plugin:
            payload["plugin"] = plugin
        return payload

    if item_id and text in (None, "") and not shape and _is_id_only_payload(message):
        payload = {
            "type": "legacy_clear",
            "id": item_id,
            "ttl": 0,
        }
        if plugin:
            payload["plugin"] = plugin
        LOGGER.debug("ID-only payload treated as legacy_clear: id=%s plugin=%s", item_id, plugin)
        return payload

    if item_id and text == "":
        payload = {
            "type": "message",
            "id": item_id,
            "text": "",
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }
        if plugin:
            payload["plugin"] = plugin
        return payload

    raw_value = dict(msg)
    payload = {"type": "raw", "raw": raw_value, "id": item_id or "", "ttl": ttl}
    if plugin and "plugin" not in payload:
        payload["plugin"] = plugin
    return payload


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
        ttl: int = 4,
        size: str = "normal",
    ) -> None:
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            ttl = 4
        if not isinstance(size, str):
            size = "normal"
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
        global _UNAVAILABLE_WARN_TS, _UNAVAILABLE_SUPPRESSED
        if not send_overlay_message(message):
            now = time.monotonic()
            if now - _UNAVAILABLE_WARN_TS >= 30.0:
                suppressed = _UNAVAILABLE_SUPPRESSED
                _UNAVAILABLE_SUPPRESSED = 0
                _UNAVAILABLE_WARN_TS = now
                if suppressed:
                    LOGGER.warning(
                        "EDMCModernOverlay is not available to accept messages [%d suppressed]",
                        suppressed,
                    )
                else:
                    LOGGER.warning("EDMCModernOverlay is not available to accept messages")
            else:
                _UNAVAILABLE_SUPPRESSED += 1
            return

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
