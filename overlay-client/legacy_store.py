from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass
class LegacyItem:
    item_id: str
    kind: str
    data: Dict[str, Any]
    expiry: Optional[float] = None
    plugin: Optional[str] = None


class LegacyItemStore:
    """Container for LegacyOverlay items with TTL handling."""

    def __init__(self) -> None:
        self._items: Dict[str, LegacyItem] = {}

    def clear(self) -> None:
        self._items.clear()

    def remove(self, item_id: str) -> None:
        self._items.pop(item_id, None)

    def set(self, item_id: str, item: LegacyItem) -> None:
        if item.item_id != item_id:
            item.item_id = item_id
        self._items[item_id] = item
        trace_cb = getattr(self, "_trace_callback", None)
        if callable(trace_cb):
            try:
                trace_cb("legacy_store:set", item)
            except Exception:
                pass

    def get(self, item_id: str) -> Optional[LegacyItem]:
        return self._items.get(item_id)

    def items(self) -> Iterable[Tuple[str, LegacyItem]]:
        return self._items.items()

    def values(self) -> Iterable[LegacyItem]:
        return self._items.values()

    def purge_expired(self, now: float) -> bool:
        expired = [
            key for key, item in self._items.items()
            if item.expiry is not None and item.expiry < now
        ]
        for key in expired:
            self._items.pop(key, None)
        return bool(expired)
