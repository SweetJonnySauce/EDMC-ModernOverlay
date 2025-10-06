"""Public helper API for interacting with EDMC-ModernOverlay."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, MutableMapping, Optional

_LOGGER = logging.getLogger("EDMC.ModernOverlay.API")
_MAX_MESSAGE_BYTES = 16_384

_publisher: Optional[Callable[[Mapping[str, Any]], bool]] = None


def register_publisher(publisher: Callable[[Mapping[str, Any]], bool]) -> None:
    """Register a callable that delivers overlay payloads.

    The EDMC-ModernOverlay plugin calls this during startup so other plugins can
    publish messages without depending on transport details.
    """

    global _publisher
    _publisher = publisher


def unregister_publisher() -> None:
    """Clear the registered publisher (called when the plugin stops)."""

    global _publisher
    _publisher = None


def send_overlay_message(message: Mapping[str, Any]) -> bool:
    """Publish a payload to the Modern Overlay broadcaster.

    Parameters
    ----------
    message:
        Mapping containing JSON-serialisable values. Must include an ``event``
        field. A ``timestamp`` is added automatically when omitted.

    Returns
    -------
    bool
        ``True`` if the message was handed to the broadcaster, ``False``
        otherwise.
    """

    publisher = _publisher
    if publisher is None:
        _log_warning("Overlay publisher unavailable (plugin not running?)")
        return False

    payload = _normalise_message(message)
    if payload is None:
        return False

    try:
        serialised = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        _log_warning(f"Overlay message is not JSON serialisable: {exc}")
        return False

    payload_size = len(serialised.encode("utf-8"))
    if payload_size > _MAX_MESSAGE_BYTES:
        _log_warning(
            "Overlay message exceeds size limit (%d > %d bytes)",
            payload_size,
            _MAX_MESSAGE_BYTES,
        )
        return False

    try:
        return bool(publisher(payload))
    except Exception as exc:  # pragma: no cover - defensive guard
        _log_warning(f"Overlay publisher raised error: {exc}")
        return False


def _normalise_message(message: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    if not isinstance(message, Mapping):
        _log_warning("Overlay message must be a mapping/dict")
        return None
    if not message:
        _log_warning("Overlay message is empty")
        return None

    payload: MutableMapping[str, Any] = dict(message)
    event = payload.get("event")
    if not isinstance(event, str) or not event:
        _log_warning("Overlay message requires a non-empty 'event' string")
        return None

    if "timestamp" not in payload:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    return payload


def _log_warning(message: str, *args: Any) -> None:
    _emit(logging.WARNING, message, *args)


def _emit(level: int, message: str, *args: Any) -> None:
    try:
        from config import config as edmc_config  # type: ignore

        logger_obj = getattr(edmc_config, "logger", None)
        if logger_obj:
            logger_obj.log(level, f"[EDMC-ModernOverlay] {message % args if args else message}")
            return
    except Exception:
        pass
    if args:
        _LOGGER.log(level, message, *args)
    else:
        _LOGGER.log(level, message)
