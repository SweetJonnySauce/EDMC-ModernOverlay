from __future__ import annotations

import time
from typing import Callable, Dict, Mapping, Optional

from overlay_client.legacy_processor import TraceCallback, process_legacy_payload  # type: ignore
from overlay_client.legacy_store import LegacyItem, LegacyItemStore  # type: ignore


class PayloadModel:
    """Owns the legacy item store and handles ingest/TTL."""

    def __init__(self, trace_logger: Callable[[str, str, str, Mapping[str, object]], None]) -> None:
        self._store = LegacyItemStore()
        # Attach the legacy store trace hook so existing tracing continues to work.
        setattr(self._store, "_trace_callback", lambda stage, item: trace_logger(
            getattr(item, "plugin", None),
            getattr(item, "item_id", ""),
            stage,
            {"kind": getattr(item, "kind", "unknown")},
        ))
        self._trace_logger = trace_logger

    @property
    def store(self) -> LegacyItemStore:
        return self._store

    def ingest(self, payload: Dict[str, object], *, trace_fn: Optional[TraceCallback] = None) -> bool:
        """Ingest a legacy payload into the store. Returns True if state changed."""

        return process_legacy_payload(self._store, payload, trace_fn=trace_fn)

    def purge_expired(self, now: Optional[float] = None) -> bool:
        """Purge expired items; returns True if any were removed."""

        return self._store.purge_expired(now or time.monotonic())

    # Convenience wrappers to match previous direct store access ----------------

    def set(self, item_id: str, item: LegacyItem) -> None:
        self._store.set(item_id, item)

    def get(self, item_id: str) -> Optional[LegacyItem]:
        return self._store.get(item_id)

    def items(self):
        return self._store.items()

    def __iter__(self):
        return iter(self._store.items())

    def __len__(self):
        return len(list(self._store.items()))
