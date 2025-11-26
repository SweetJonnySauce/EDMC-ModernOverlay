from __future__ import annotations

import time
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
    ) -> Optional[Dict[str, Any]]:
        owner = self._owner
        grouping_helper = getattr(owner, "_grouping_helper")
        try:
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
        now_monotonic = owner._monotonic_now() if hasattr(owner, "_monotonic_now") else time.monotonic()
        legacy_items = getattr(owner, "_payload_model").store
        passes = 2 if legacy_items else 1
        for pass_index in range(passes):
            (
                commands,
                bounds_by_group,
                overlay_bounds_by_group,
                effective_anchor_by_group,
                transform_by_group,
            ) = owner._build_legacy_commands_for_pass(
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
            pending_payload = owner._group_log_pending_base.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = owner._logged_group_bounds.get(key)
            should_schedule = pending_payload is not None or last_logged != bounds_tuple
            if should_schedule:
                if pending_tuple != bounds_tuple or pending_payload is None:
                    owner._group_log_pending_base[key] = payload_dict
                    delay_target = (
                        now_monotonic
                        if getattr(owner, "_payload_log_delay", 0.0) <= 0.0
                        else (now_monotonic or 0.0) + getattr(owner, "_payload_log_delay", 0.0)
                    )
                    owner._group_log_next_allowed[key] = delay_target
            else:
                owner._group_log_pending_base.pop(key, None)
                owner._group_log_next_allowed.pop(key, None)
            if has_transformed:
                transform_candidates[key] = (plugin_label or "", suffix or "")
            else:
                owner._group_log_pending_transform.pop(key, None)
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
        trace_helper = owner._group_trace_helper(report_overlay_bounds, commands)
        trace_helper()
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
            transform_tuple = (
                report_bounds.min_x,
                report_bounds.min_y,
                report_bounds.max_x,
                report_bounds.max_y,
            )
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
            pending_payload = owner._group_log_pending_transform.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = owner._logged_group_transforms.get(key)
            should_schedule = pending_payload is not None or last_logged != transform_tuple
            if not should_schedule:
                owner._group_log_pending_transform.pop(key, None)
                continue
            if pending_payload is None or pending_tuple != transform_tuple:
                owner._group_log_pending_transform[key] = {
                    **transform_payload,
                    "bounds_tuple": transform_tuple,
                }
                if key not in owner._group_log_pending_base:
                    base_snapshot = latest_base_payload.get(key)
                    if base_snapshot is not None:
                        owner._group_log_pending_base[key] = base_snapshot
                    delay_target = (
                        now_monotonic
                        if getattr(owner, "_payload_log_delay", 0.0) <= 0.0
                        else (now_monotonic or 0.0) + getattr(owner, "_payload_log_delay", 0.0)
                    )
                    owner._group_log_next_allowed[key] = delay_target
        owner._update_group_cache_from_payloads(cache_base_payloads, cache_transform_payloads)
        owner._flush_group_log_entries(active_group_keys)
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
            cache = self._rebuild_legacy_render_cache(mapper, signature, context.settings)
        if cache is None:
            return

        commands = cache.get("commands") or []
        anchor_translation_by_group = cache.get("anchor_translation_by_group") or {}
        translations = cache.get("translations") or {}
        overlay_bounds_for_draw = cache.get("overlay_bounds_for_draw") or {}
        overlay_bounds_base = cache.get("overlay_bounds_base") or {}
        report_overlay_bounds = cache.get("report_overlay_bounds") or {}
        transform_by_group = cache.get("transform_by_group") or {}

        collect_debug_helpers = owner._dev_mode_enabled and owner._debug_config.group_bounds_outline
        if collect_debug_helpers:
            final_bounds_map = overlay_bounds_for_draw if overlay_bounds_for_draw else overlay_bounds_base
            owner._debug_group_bounds_final = owner._clone_overlay_bounds_map(final_bounds_map)
            owner._debug_group_state = owner._build_group_debug_state(
                owner._debug_group_bounds_final,
                transform_by_group,
                translations,
                canonical_bounds=report_overlay_bounds,
            )
        else:
            owner._debug_group_bounds_final = {}
            owner._debug_group_state = {}

        window_width = max(owner.width(), 0)
        window_height = max(owner.height(), 0)
        draw_vertex_markers = owner._dev_mode_enabled and owner._debug_config.payload_vertex_markers
        vertex_points: List[Tuple[int, int]] = []
        for command in commands:
            key_tuple = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key_tuple, (0.0, 0.0))
            nudge_x, nudge_y = translations.get(key_tuple, (0, 0))
            justification_dx = getattr(command, "justification_dx", 0.0)
            payload_offset_x = translation_x + justification_dx + nudge_x
            payload_offset_y = translation_y + nudge_y
            owner._log_offscreen_payload(command, payload_offset_x, payload_offset_y, window_width, window_height)
            command.paint(owner, painter, payload_offset_x, payload_offset_y)
            if draw_vertex_markers and command.bounds:
                left, top, right, bottom = command.bounds
                group_corners = [
                    (left, top),
                    (right, top),
                    (left, bottom),
                    (right, bottom),
                ]
                trace_vertices = owner._should_trace_payload(
                    getattr(command.legacy_item, "plugin", None),
                    command.legacy_item.item_id,
                )
                for px, py in group_corners:
                    adjusted_x = int(round(float(px) + payload_offset_x))
                    adjusted_y = int(round(float(py) + payload_offset_y))
                    vertex_points.append((adjusted_x, adjusted_y))
                    if trace_vertices:
                        owner._log_legacy_trace(
                            command.legacy_item.plugin,
                            command.legacy_item.item_id,
                            "debug:payload_vertex",
                            {
                                "pixel_x": adjusted_x,
                                "pixel_y": adjusted_y,
                                "payload_kind": getattr(command.legacy_item, "kind", "unknown"),
                            },
                        )
        if draw_vertex_markers and vertex_points:
            owner._draw_payload_vertex_markers(painter, vertex_points)
        if collect_debug_helpers:
            owner._draw_group_debug_helpers(painter, mapper)
@dataclass(frozen=True)
class RenderSettings:
    font_family: str
    font_fallbacks: Tuple[str, ...]
    preset_point_size: Callable[[str], float]
