from __future__ import annotations

import time
import logging
import os
from typing import Callable, Dict, Mapping, Optional, Tuple, Any

from overlay_client.legacy_processor import (
    TraceCallback,
    process_legacy_payload,
    _hashable_payload_snapshot,
    _extract_plugin,
)  # type: ignore
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
        self._last_snapshots: Dict[str, Tuple[Tuple[Any, ...], Optional[int]]] = {}
        self._dedupe_log_state: Dict[str, Dict[str, float | int]] = {}
        dedupe_env = (os.getenv("EDMC_OVERLAY_INGEST_DEDUPE") or "1").strip().lower()
        self._dedupe_enabled = dedupe_env not in {"0", "false", "no", "off"}

    @property
    def store(self) -> LegacyItemStore:
        return self._store

    def ingest(
        self,
        payload: Dict[str, object],
        *,
        trace_fn: Optional[TraceCallback] = None,
        override_generation: Optional[int] = None,
        group_label: Optional[str] = None,
    ) -> bool:
        """Ingest a legacy payload into the store. Returns True if state changed."""

        item_id = payload.get("id")
        item_type = payload.get("type")
        snapshot: Optional[Tuple[Any, ...]] = None
        if self._dedupe_enabled and isinstance(item_id, str) and isinstance(item_type, str):
            try:
                snapshot = _hashable_payload_snapshot(item_type, payload)
            except Exception:
                snapshot = None
            if snapshot is not None:
                last_entry = self._last_snapshots.get(item_id)
                if last_entry is not None:
                    last_snapshot, last_generation = last_entry
                else:
                    last_snapshot, last_generation = None, None
                if last_snapshot == snapshot and (last_generation == override_generation or override_generation is None):
                    ttl = max(int(payload.get("ttl", 4)), 0)
                    expiry = None if ttl <= 0 else time.monotonic() + ttl
                    existing = self._store.get(item_id)
                    if existing is not None:
                        existing.expiry = expiry
                        plugin_name = _extract_plugin(payload) or "unknown"
                        item_id_token = item_id.casefold()
                        reason = (
                            "controller_heartbeat"
                            if item_id_token in {"overlay-controller-status", "edmcmodernoverlay-controller-status"}
                            else None
                        )
                        details = {
                            "item_id": item_id,
                            "plugin": plugin_name,
                            "snapshot": snapshot,
                            "group": group_label or "",
                        }
                        if reason:
                            details["reason"] = reason
                        if trace_fn:
                            trace_fn("payload_model:dedupe_skipped", payload, details)
                        else:
                            logger = logging.getLogger("EDMC.ModernOverlay.Client")
                            if logger.isEnabledFor(logging.DEBUG):
                                now = time.monotonic()
                                key = group_label or plugin_name
                                state = self._dedupe_log_state.setdefault(key, {"count": 0, "last": now})
                                state["count"] = int(state.get("count", 0)) + 1
                                last_log = float(state.get("last", now))
                                if now - last_log >= 5.0:
                                    prefix = "payload_model:dedupe_skipped"
                                    if reason:
                                        prefix += f" ({reason})"
                                    logger.debug(
                                        "%s plugin=%s group=%s id=%s count=%d window=%.1fs",
                                        prefix,
                                        plugin_name,
                                        group_label or "",
                                        item_id,
                                        state["count"],
                                        now - last_log,
                                    )
                                    state["count"] = 0
                                    state["last"] = now
                        return False

        changed = process_legacy_payload(self._store, payload, trace_fn=trace_fn)
        if changed and snapshot is not None and isinstance(item_id, str):
            self._last_snapshots[item_id] = (snapshot, override_generation)
        return changed

    def purge_expired(self, now: Optional[float] = None) -> bool:
        """Purge expired items; returns True if any were removed."""

        before_ids = {item_id for item_id, _ in self._store.items()}
        changed = self._store.purge_expired(now or time.monotonic())
        after_ids = {item_id for item_id, _ in self._store.items()}
        removed = before_ids - after_ids
        if removed:
            for item_id in removed:
                self._last_snapshots.pop(item_id, None)
        return changed

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
