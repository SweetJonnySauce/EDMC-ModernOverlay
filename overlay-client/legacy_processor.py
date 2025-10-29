from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Mapping, Any

from legacy_store import LegacyItem, LegacyItemStore


def process_legacy_payload(store: LegacyItemStore, payload: Mapping[str, Any]) -> bool:
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

    if item_type == "message":
        text = payload.get("text", "")
        if not text:
            store.remove(item_id)
            return True
        data = {
            "text": text,
            "color": payload.get("color", "white"),
            "x": int(payload.get("x", 0)),
            "y": int(payload.get("y", 0)),
            "size": payload.get("size", "normal"),
        }
        store.set(item_id, LegacyItem(kind="message", data=data, expiry=expiry))
        return True

    if item_type == "shape":
        shape_name = str(payload.get("shape") or "").lower()
        if shape_name == "rect":
            data = {
                "color": payload.get("color", "white"),
                "fill": payload.get("fill") or "#00000000",
                "x": int(payload.get("x", 0)),
                "y": int(payload.get("y", 0)),
                "w": int(payload.get("w", 0)),
                "h": int(payload.get("h", 0)),
            }
            store.set(item_id, LegacyItem(kind="rect", data=data, expiry=expiry))
            return True
        # For other shapes we keep the payload for future support
        enriched = dict(payload)
        enriched.setdefault("timestamp", datetime.now(UTC).isoformat())
        store.set(item_id, LegacyItem(kind=f"shape:{shape_name}" if shape_name else "shape", data=enriched, expiry=expiry))
        return True

    if item_type == "raw":
        return False

    return False
