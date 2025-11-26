from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from overlay_client.grouping_helper import FillGroupingHelper  # type: ignore
from overlay_client.group_transform import GroupKey, GroupTransform  # type: ignore
from overlay_client.render_pipeline import RenderSettings  # type: ignore


class GroupingAdapter:
    """Adapter exposing FillGroupingHelper via a narrow interface for the render pipeline."""

    def __init__(self, helper: FillGroupingHelper, owner: Any) -> None:
        self._helper = helper
        self._owner = owner

    def set_render_settings(self, settings: RenderSettings) -> None:
        try:
            self._helper.set_render_settings(settings)
        except Exception:
            pass

    def prepare(self, mapper: Any) -> None:
        self._helper.prepare(mapper)

    def reset(self) -> None:
        self._helper.reset()

    def group_key_for(self, item_id: str, plugin_name: Optional[str]) -> GroupKey:
        return self._helper.group_key_for(item_id, plugin_name)

    def get_transform(self, key: GroupKey) -> Optional[GroupTransform]:
        return self._helper.get_transform(key)

    def items(self) -> Iterable[Tuple[str, Any]]:
        store = getattr(self._helper._owner, "_payload_model").store  # type: ignore[attr-defined]
        return store.items()

    def build_commands_for_pass(
        self,
        mapper: Any,
        overlay_bounds_hint: Optional[Dict[Tuple[str, Optional[str]], Any]],
        *,
        collect_only: bool = False,
    ):
        """Delegate command construction to the owner for now."""
        return self._owner._build_legacy_commands_for_pass(  # type: ignore[attr-defined]
            mapper,
            overlay_bounds_hint,
            collect_only=collect_only,
        )
