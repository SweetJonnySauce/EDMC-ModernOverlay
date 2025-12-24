from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from collections.abc import Iterable, Sequence
from typing import Any, Callable, Mapping, MutableMapping, Optional
import json

from overlay_client.legacy_store import LegacyItem, LegacyItemStore

LOGGER = logging.getLogger("EDMC.ModernOverlay.LegacyProcessor")


def _hashable_payload_snapshot(item_type: str, payload: Mapping[str, Any]) -> tuple:
    if item_type == "message":
        return (
            payload.get("text", ""),
            payload.get("color", ""),
            payload.get("x", 0),
            payload.get("y", 0),
            payload.get("size", ""),
            payload.get("__mo_transform__", None),
        )
    if item_type == "shape":
        shape_name = str(payload.get("shape") or "").lower()
        if shape_name == "rect":
            return (
                shape_name,
                payload.get("color", ""),
                payload.get("fill", ""),
                payload.get("x", 0),
                payload.get("y", 0),
                payload.get("w", 0),
                payload.get("h", 0),
                payload.get("__mo_transform__", None),
            )
        if shape_name == "vect":
            vector = payload.get("vector") or []
            points = []
            if isinstance(vector, list):
                for entry in vector:
                    if not isinstance(entry, Mapping):
                        continue
                    points.append(
                        (
                            entry.get("x", 0),
                            entry.get("y", 0),
                            entry.get("color", ""),
                            (entry.get("marker") or "").lower(),
                            entry.get("text", ""),
                        )
                    )
            return (
                shape_name,
                payload.get("color", ""),
                tuple(points),
                payload.get("__mo_transform__", None),
            )
    return (item_type, json.dumps(payload, sort_keys=True, default=str))


TraceCallback = Callable[[str, Mapping[str, Any], Mapping[str, Any]], None]


def _extract_plugin(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("plugin", "plugin_name", "source_plugin"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    meta = payload.get("meta")
    if isinstance(meta, Mapping):
        for key in ("plugin", "plugin_name", "source_plugin"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                return value
    raw = payload.get("raw")
    if isinstance(raw, Mapping):
        for key in ("plugin", "plugin_name", "source_plugin"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _point_has_marker_or_text(point: Mapping[str, Any]) -> bool:
    marker = point.get("marker")
    if marker:
        return True
    text = point.get("text")
    if text is None:
        return False
    return str(text) != ""


_LEGACY_CONTENT_KEYS = {
    "text",
    "Text",
    "shape",
    "Shape",
    "vector",
    "Vector",
    "points",
    "Points",
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


def _is_id_only_mapping(payload: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    for key in _LEGACY_CONTENT_KEYS:
        if key not in payload:
            continue
        value = payload[key]
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


def process_legacy_payload(
    store: LegacyItemStore,
    payload: Mapping[str, Any],
    trace_fn: Optional[TraceCallback] = None,
) -> bool:
    """Process a legacy payload and update the store.

    Returns True when the caller should trigger a repaint.
    """

    item_type = payload.get("type")
    item_id = payload.get("id")
    if item_type == "clear_all":
        store.clear()
        return True
    if item_type in {"legacy_clear", "clear"}:
        if isinstance(item_id, str) and item_id:
            store.remove(item_id)
            return True
        return False
    if not isinstance(item_id, str):
        return False

    ttl = max(int(payload.get("ttl", 4)), 0)
    expiry = None if ttl <= 0 else time.monotonic() + ttl
    plugin_name = _extract_plugin(payload)

    now_iso = datetime.now(UTC).isoformat()

    if item_type == "message":
        text = payload.get("text", "")
        if not text:
            store.remove(item_id)
            return True
        if trace_fn:
            snapshot = _hashable_payload_snapshot(item_type, payload)
            trace_fn(
                "legacy_processor:dedupe_snapshot",
                payload,
                {"item_id": item_id, "plugin": plugin_name, "snapshot": snapshot},
            )
        data = {
            "text": text,
            "color": payload.get("color", "white"),
            "x": int(payload.get("x", 0)),
            "y": int(payload.get("y", 0)),
            "size": payload.get("size", "normal"),
        }
        data["__mo_ttl__"] = ttl
        transform_meta = payload.get("__mo_transform__")
        if isinstance(transform_meta, Mapping):
            try:
                data["__mo_transform__"] = dict(transform_meta)
            except Exception:
                data["__mo_transform__"] = transform_meta
            raw_payload = payload.get("raw")
            if isinstance(raw_payload, MutableMapping):
                try:
                    raw_copy = dict(transform_meta)
                except Exception:
                    raw_copy = transform_meta
                raw_payload.setdefault("__mo_transform__", {}).update(raw_copy if isinstance(raw_copy, Mapping) else {})
        data["__mo_updated__"] = now_iso
        store.set(item_id, LegacyItem(item_id=item_id, kind="message", data=data, expiry=expiry, plugin=plugin_name))
        return True

    if item_type == "shape":
        shape_name = str(payload.get("shape") or "").lower()
        message = dict(payload)
        if shape_name == "rect":
            data = {
                "color": message.get("color", "white"),
                "fill": message.get("fill") or "#00000000",
                "x": int(message.get("x", 0)),
                "y": int(message.get("y", 0)),
                "w": int(message.get("w", 0)),
                "h": int(message.get("h", 0)),
            }
            data["__mo_ttl__"] = ttl
            if trace_fn:
                snapshot = _hashable_payload_snapshot("shape", payload)
                trace_fn(
                    "legacy_processor:dedupe_snapshot",
                    payload,
                    {"item_id": item_id, "plugin": plugin_name, "snapshot": snapshot},
                )
            transform_meta = message.get("__mo_transform__")
            if isinstance(transform_meta, Mapping):
                try:
                    transform_meta = dict(transform_meta)
                except Exception:
                    transform_meta = None
            if transform_meta is not None:
                data["__mo_transform__"] = transform_meta
            data["__mo_updated__"] = now_iso
            store.set(
                item_id,
                LegacyItem(item_id=item_id, kind="rect", data=data, expiry=expiry, plugin=plugin_name),
            )
            return True
        if shape_name == "vect":
            vector = message.get("vector")
            if not isinstance(vector, list):
                if trace_fn:
                    trace_fn(
                        "legacy_processor:vector_drop",
                        payload,
                        {
                            "plugin": plugin_name,
                            "item_id": item_id,
                            "reason": "vector_not_list",
                        },
                    )
                LOGGER.warning("Dropping vect payload with invalid vector list: id=%s vector=%s", item_id, vector)
                return False
            points = []
            for entry in vector:
                if not isinstance(entry, Mapping):
                    continue
                try:
                    x_val = int(entry.get("x", 0))
                    y_val = int(entry.get("y", 0))
                except (TypeError, ValueError):
                    continue
                point = {
                    "x": x_val,
                    "y": y_val,
                }
                if entry.get("color"):
                    point["color"] = str(entry["color"])
                if entry.get("marker"):
                    point["marker"] = str(entry["marker"]).lower()
                if entry.get("text"):
                    point["text"] = str(entry["text"])
                points.append(point)
            if not points:
                if trace_fn:
                    trace_fn(
                        "legacy_processor:vector_drop",
                        payload,
                        {
                            "plugin": plugin_name,
                            "item_id": item_id,
                            "reason": "no_valid_points",
                        },
                    )
                LOGGER.warning("Dropping vect payload with insufficient points: id=%s vector=%s", item_id, vector)
                return False
            if len(points) == 1 and not _point_has_marker_or_text(points[0]):
                if trace_fn:
                    trace_fn(
                        "legacy_processor:vector_drop",
                        payload,
                        {
                            "plugin": plugin_name,
                            "item_id": item_id,
                            "reason": "single_point_without_marker_or_text",
                        },
                    )
                LOGGER.warning("Dropping vect payload with insufficient points: id=%s vector=%s", item_id, vector)
                return False
            data = {
                "base_color": message.get("color", "white"),
                "points": points,
            }
            data["__mo_ttl__"] = ttl
            if trace_fn:
                snapshot = _hashable_payload_snapshot("shape", payload)
                trace_fn(
                    "legacy_processor:dedupe_snapshot",
                    payload,
                    {"item_id": item_id, "plugin": plugin_name, "snapshot": snapshot},
                )
            transform_meta = message.get("__mo_transform__")
            if isinstance(transform_meta, Mapping):
                try:
                    transform_meta = dict(transform_meta)
                except Exception:
                    transform_meta = None
            if transform_meta is not None:
                data["__mo_transform__"] = transform_meta
            data["__mo_updated__"] = now_iso
            if trace_fn:
                trace_fn(
                    "legacy_processor:vector_normalised",
                    payload,
                    {
                        "plugin": plugin_name,
                        "item_id": item_id,
                        "points": points,
                        "base_color": data["base_color"],
                    },
                )
            store.set(
                item_id,
                LegacyItem(
                    item_id=item_id,
                    kind="vector",
                    data=data,
                    expiry=expiry,
                    plugin=plugin_name,
                ),
            )
            return True

        # For other shapes we keep the payload for future support/logging
        enriched = dict(message)
        enriched["__mo_ttl__"] = ttl
        enriched.setdefault("timestamp", datetime.now(UTC).isoformat())
        store.set(
            item_id,
            LegacyItem(
                item_id=item_id,
                kind=f"shape:{shape_name}" if shape_name else "shape",
                data=enriched,
                expiry=expiry,
                plugin=plugin_name,
            ),
        )
        return True

    if item_type == "raw":
        raw_payload = payload.get("raw")
        if isinstance(item_id, str) and item_id and _is_id_only_mapping(raw_payload):
            store.remove(item_id)
            return True
        return False

    return False
UTC = getattr(datetime, "UTC", timezone.utc)
