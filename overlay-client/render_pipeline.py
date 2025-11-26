from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Tuple, List, Callable

from PyQt6.QtGui import QPainter

from viewport_helper import ScaleMode  # type: ignore
from group_transform import GroupTransform  # type: ignore


@dataclass(frozen=True)
class RenderContext:
    width: int
    height: int
    mapper: Any
    dev_mode: bool
    debug_bounds: bool
    debug_vertices: bool
    settings: "RenderSettings"
    grouping: Any


@dataclass(frozen=True)
class PayloadSnapshot:
    items_count: int


class LegacyRenderPipeline:
    """Encapsulates legacy render command construction and caching."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner
        self._legacy_cache_dirty: bool = True
        self._legacy_cache_signature: Optional[Tuple[Any, ...]] = None
        self._legacy_render_cache: Optional[Dict[str, Any]] = None
        self._last_payload_results: Optional[Dict[str, Any]] = None

    def mark_dirty(self) -> None:
        self._legacy_cache_dirty = True
        self._legacy_cache_signature = None

    def _legacy_render_signature(self, context: RenderContext, snapshot: PayloadSnapshot) -> Tuple[Any, ...]:
        transform = context.mapper.transform
        return (
            context.width,
            context.height,
            getattr(transform, "mode", None),
            getattr(transform, "scale", None),
            getattr(transform, "offset", None),
            getattr(transform, "overflow_x", None),
            getattr(transform, "overflow_y", None),
            snapshot.items_count,
            context.dev_mode,
            context.debug_bounds,
            context.debug_vertices,
        )

    def _rebuild_legacy_render_cache(
        self,
        mapper: Any,
        signature: Tuple[Any, ...],
        settings: RenderSettings,
        grouping: Any,
    ) -> Optional[Dict[str, Any]]:
        owner = self._owner
        grouping_helper = grouping or getattr(self._owner, "_grouping_helper")
        try:
            if hasattr(grouping_helper, "set_render_settings"):
                grouping_helper.set_render_settings(settings)
        except Exception:
            pass
        if mapper.transform.mode is ScaleMode.FILL:
            grouping_helper.prepare(mapper)
        else:
            grouping_helper.reset()
        overlay_bounds_hint: Optional[Dict[Tuple[str, Optional[str]], Any]] = None
        commands: List[Any] = []
        bounds_by_group: Dict[Tuple[str, Optional[str]], Any] = {}
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], Any] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        transform_by_group: Dict[Tuple[str, Optional[str]], Optional[GroupTransform]] = {}
        legacy_items = getattr(owner, "_payload_model").store
        passes = 2 if legacy_items else 1
        for pass_index in range(passes):
            if hasattr(grouping_helper, "build_commands_for_pass"):
                (
                    commands,
                    bounds_by_group,
                    overlay_bounds_by_group,
                    effective_anchor_by_group,
                    transform_by_group,
                ) = grouping_helper.build_commands_for_pass(
                    mapper,
                    overlay_bounds_hint,
                    collect_only=(pass_index == 0 and passes > 1),
                )
            else:
                (
                    commands,
                    bounds_by_group,
                    overlay_bounds_by_group,
                    effective_anchor_by_group,
                    transform_by_group,
                ) = owner._build_legacy_commands_for_pass(  # type: ignore[attr-defined]
                    mapper,
                    overlay_bounds_hint,
                    collect_only=(pass_index == 0 and passes > 1),
                )
            overlay_bounds_hint = overlay_bounds_by_group
            if not legacy_items:
                break

        anchor_translation_by_group, translated_bounds_by_group = owner._prepare_anchor_translations(
            mapper,
            bounds_by_group,
            overlay_bounds_by_group,
            effective_anchor_by_group,
            transform_by_group,
        )
        overlay_bounds_base = owner._collect_base_overlay_bounds(commands)
        transform_candidates: Dict[Tuple[str, Optional[str]], Tuple[str, Optional[str]]] = {}
        latest_base_payload: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        cache_base_payloads: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        cache_transform_payloads: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        active_group_keys: Set[Tuple[str, Optional[str]]] = set()
        offsets_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        for key, logical_bounds in overlay_bounds_base.items():
            if logical_bounds is None or not logical_bounds.is_valid():
                continue
            active_group_keys.add(key)
            plugin_label, suffix = key
            min_x = logical_bounds.min_x
            min_y = logical_bounds.min_y
            max_x = logical_bounds.max_x
            max_y = logical_bounds.max_y
            width = max_x - min_x
            height = max_y - min_y
            group_transform = transform_by_group.get(key)
            offset_x, offset_y = owner._group_offsets(group_transform)
            has_offset = bool(offset_x or offset_y)
            has_transformed = bool(
                (group_transform is not None and owner._has_user_group_transform(group_transform))
                or has_offset
            )
            offsets_by_group[key] = (offset_x, offset_y)
            base_min_x = min_x - offset_x
            base_max_x = max_x - offset_x
            base_min_y = min_y - offset_y
            base_max_y = max_y - offset_y
            bounds_tuple = (
                base_min_x,
                base_min_y,
                base_max_x,
                base_max_y,
            )
            payload_dict = {
                "plugin": plugin_label or "",
                "suffix": suffix or "",
                "min_x": base_min_x,
                "min_y": base_min_y,
                "max_x": base_max_x,
                "max_y": base_max_y,
                "width": width,
                "height": height,
                "has_transformed": has_transformed,
                "offset_x": offset_x,
                "offset_y": offset_y,
                "bounds_tuple": bounds_tuple,
            }
            latest_base_payload[key] = payload_dict
            cache_base_payloads[key] = dict(payload_dict)
            if has_transformed:
                transform_candidates[key] = (plugin_label or "", suffix or "")
        report_overlay_bounds = owner._clone_overlay_bounds_map(overlay_bounds_base)
        report_overlay_bounds = owner._apply_anchor_translations_to_overlay_bounds(
            report_overlay_bounds,
            anchor_translation_by_group,
            mapper.transform.scale,
        )
        overlay_bounds_for_draw = owner._clone_overlay_bounds_map(overlay_bounds_by_group)
        overlay_bounds_for_draw = owner._apply_anchor_translations_to_overlay_bounds(
            overlay_bounds_for_draw,
            anchor_translation_by_group,
            mapper.transform.scale,
        )
        translated_bounds_by_group = owner._apply_payload_justification(
            commands,
            transform_by_group,
            anchor_translation_by_group,
            translated_bounds_by_group,
            overlay_bounds_for_draw,
            overlay_bounds_base,
            mapper.transform.scale,
        )
        translations = owner._compute_group_nudges(translated_bounds_by_group)
        overlay_bounds_for_draw = owner._apply_group_nudges_to_overlay_bounds(
            overlay_bounds_for_draw,
            translations,
            mapper.transform.scale,
        )
        for key, labels in transform_candidates.items():
            plugin_label, suffix_label = labels
            report_bounds = report_overlay_bounds.get(key)
            if report_bounds is None or not report_bounds.is_valid():
                continue
            width_t = report_bounds.max_x - report_bounds.min_x
            height_t = report_bounds.max_y - report_bounds.min_y
            group_transform = transform_by_group.get(key)
            offset_x, offset_y = offsets_by_group.get(key, (0.0, 0.0))
            anchor_token = "nw"
            justification_token = "left"
            if group_transform is not None:
                anchor_token = (getattr(group_transform, "anchor_token", "nw") or "nw").strip().lower()
                raw_just = getattr(group_transform, "payload_justification", "") or "left"
                justification_token = raw_just.strip().lower() if isinstance(raw_just, str) else "left"
            nudge_x, nudge_y = translations.get(key, (0, 0))
            nudged = bool(nudge_x or nudge_y)
            transform_payload = {
                "plugin": plugin_label,
                "suffix": suffix_label,
                "min_x": report_bounds.min_x,
                "min_y": report_bounds.min_y,
                "max_x": report_bounds.max_x,
                "max_y": report_bounds.max_y,
                "width": width_t,
                "height": height_t,
                "anchor": anchor_token,
                "justification": justification_token,
                "nudge_dx": nudge_x,
                "nudge_dy": nudge_y,
                "nudged": nudged,
                "offset_dx": offset_x,
                "offset_dy": offset_y,
            }
            cache_transform_payloads[key] = dict(transform_payload)
        self._last_payload_results = {
            "cache_base_payloads": cache_base_payloads,
            "cache_transform_payloads": cache_transform_payloads,
            "active_group_keys": active_group_keys,
            "latest_base_payload": latest_base_payload,
            "transform_candidates": transform_candidates,
            "translations": translations,
            "report_overlay_bounds": report_overlay_bounds,
            "transform_by_group": transform_by_group,
            "overlay_bounds_for_draw": overlay_bounds_for_draw,
            "overlay_bounds_base": overlay_bounds_base,
            "anchor_translation_by_group": anchor_translation_by_group,
            "commands": commands,
        }
        self._legacy_render_cache = {
            "commands": commands,
            "anchor_translation_by_group": anchor_translation_by_group,
            "translations": translations,
            "overlay_bounds_for_draw": overlay_bounds_for_draw,
            "overlay_bounds_base": overlay_bounds_base,
            "report_overlay_bounds": report_overlay_bounds,
            "transform_by_group": transform_by_group,
        }
        self._legacy_cache_signature = signature
        self._legacy_cache_dirty = False
        return self._legacy_render_cache

    def paint(self, painter: QPainter, context: RenderContext, snapshot: PayloadSnapshot) -> None:
        owner = self._owner
        owner._cycle_anchor_points = {}
        mapper = context.mapper
        signature = self._legacy_render_signature(context, snapshot)
        cache = self._legacy_render_cache
        if cache is None or self._legacy_cache_dirty or signature != self._legacy_cache_signature:
            cache = self._rebuild_legacy_render_cache(mapper, signature, context.settings, context.grouping)
        if cache is None:
            return
        # Rendering is handled by the owner; pipeline only prepares data and caches.
@dataclass(frozen=True)
class RenderSettings:
    font_family: str
    font_fallbacks: Tuple[str, ...]
    preset_point_size: Callable[[str], float]
