from __future__ import annotations

from typing import Any, Mapping, Optional

from overlay_client.legacy_store import LegacyItemStore
from overlay_client.payload_model import PayloadModel
from overlay_client.plugin_overrides import PluginOverrideManager
from overlay_client.grouping_helper import FillGroupingHelper


def force_reload_overrides(
    override_manager: PluginOverrideManager,
    grouping_helper: FillGroupingHelper,
    payload_model: PayloadModel,
    log_fn,
) -> None:
    """Force-reload overrides and refresh grouping state."""

    override_manager.force_reload()
    grouping_helper.reset()
    try:
        payload_model._last_snapshots.clear()  # type: ignore[attr-defined]
    except Exception:
        pass

    store: LegacyItemStore = payload_model.store
    for item_id, item in list(store.items()):
        payload: dict[str, Any] = {"id": item_id}
        if item.plugin:
            payload["plugin"] = item.plugin
        try:
            inferred = override_manager.infer_plugin_name(payload)
        except Exception as exc:
            log_fn("Override reload: inference failed for %s: %s", item_id, exc)
            continue
        if inferred and inferred != item.plugin:
            item.plugin = inferred
            store.set(item_id, item)

    log_fn(
        "Override reload applied: generation=%d items=%d",
        getattr(override_manager, "generation", -1),
        len(list(store.items())),
    )


def parse_reload_nonce(payload: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(payload, Mapping):
        return ""
    raw = payload.get("nonce")
    if isinstance(raw, str):
        return raw.strip()
    if raw is None:
        return ""
    try:
        return str(raw)
    except Exception:
        return ""
