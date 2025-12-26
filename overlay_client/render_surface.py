"""Rendering/payload/debug surface mixin extracted from overlay_client."""
from __future__ import annotations

import logging
import sys
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen

from overlay_client.anchor_helpers import CommandContext, build_baseline_bounds, compute_justification_offsets
from overlay_client.group_transform import GroupKey, GroupTransform
from overlay_client.legacy_processor import TraceCallback
from overlay_client.legacy_store import LegacyItem
from overlay_client.offscreen_logger import log_offscreen_payload
from overlay_client.paint_commands import (
    _LegacyPaintCommand,
    _MessagePaintCommand,
    _RectPaintCommand,
    _VectorPaintCommand,
)
from overlay_client.payload_builders import build_group_context
from overlay_client.render_pipeline import PayloadSnapshot, RenderContext, RenderSettings
from overlay_client.viewport_transform import (
    LegacyMapper,
    ViewportState,
    build_viewport,
    compute_proportional_translation,
    legacy_scale_components,
)
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode
from overlay_client.opacity_utils import apply_global_payload_opacity, coerce_percent
from overlay_client.window_utils import legacy_preset_point_size as util_legacy_preset_point_size, line_width as util_line_width

_CLIENT_LOGGER = logging.getLogger("EDMC.ModernOverlay.Client")


@dataclass
class _ScreenBounds:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def include_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        self.min_x = min(self.min_x, left, right)
        self.max_x = max(self.max_x, left, right)
        self.min_y = min(self.min_y, top, bottom)
        self.max_y = max(self.max_y, top, bottom)

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y

    def translate(self, dx: float, dy: float) -> None:
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return
        self.min_x += dx
        self.max_x += dx
        self.min_y += dy
        self.max_y += dy


@dataclass
class _OverlayBounds:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def include_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        self.min_x = min(self.min_x, left, right)
        self.max_x = max(self.max_x, left, right)
        self.min_y = min(self.min_y, top, bottom)
        self.max_y = max(self.max_y, top, bottom)

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y

    def translate(self, dx: float, dy: float) -> None:
        if not (math.isfinite(dx) and math.isfinite(dy)):
            return
        self.min_x += dx
        self.max_x += dx
        self.min_y += dy
        self.max_y += dy


@dataclass
class _GroupDebugState:
    anchor_token: str
    justification: str
    use_transformed: bool
    anchor_point: Optional[Tuple[float, float]]
    anchor_logical: Optional[Tuple[float, float]]
    nudged: bool


@dataclass(frozen=True)
class _MeasuredText:
    width: int
    ascent: int
    descent: int



_LINE_WIDTH_DEFAULTS_FALLBACK: Dict[str, int] = {
    "grid": 1,
    "legacy_rect": 2,
    "group_outline": 1,
    "viewport_indicator": 4,
    "vector_line": 2,
    "vector_marker": 2,
    "vector_cross": 2,
    "cycle_connector": 2,
}


class RenderSurfaceMixin:
    """Rendering, payload, and debug helpers for the overlay window."""

    def _update_auto_legacy_scale(self, width: int, height: int) -> None:
        mapper = self._compute_legacy_mapper()
        try:
            ratio = self.devicePixelRatioF()
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _CLIENT_LOGGER.debug("devicePixelRatioF unavailable, defaulting to 1.0: %s", exc)
            ratio = 1.0
        except Exception as exc:  # pragma: no cover - unexpected Qt errors
            _CLIENT_LOGGER.warning("Unexpected devicePixelRatioF failure, defaulting to 1.0: %s", exc)
            ratio = 1.0
        if ratio <= 0.0:
            ratio = 1.0
        state = ViewportState(width=float(max(width, 1)), height=float(max(height, 1)), device_ratio=ratio)
        overlay_module = sys.modules.get("overlay_client.overlay_client")
        scale_fn = getattr(overlay_module, "legacy_scale_components", legacy_scale_components)
        scale_x, scale_y = scale_fn(mapper, state)
        transform = mapper.transform
        diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        self._font_scale_diag = diagonal_scale
        self._update_message_font()
        current = (
            round(scale_x, 4),
            round(scale_y, 4),
            round(diagonal_scale, 4),
            round(transform.scale, 4),
            round(transform.scaled_size[0], 1),
            round(transform.scaled_size[1], 1),
            round(mapper.offset_x, 1),
            round(mapper.offset_y, 1),
            transform.mode.value,
            transform.overflow_x,
            transform.overflow_y,
        )
        if self._last_logged_scale != current:
            width_px, height_px = self._current_physical_size()
            _CLIENT_LOGGER.debug(
                (
                    "Overlay scaling updated: window=%dx%d px mode=%s base_scale=%.4f "
                    "scale_x=%.3f scale_y=%.3f diag=%.2f scaled=%.1fx%.1f "
                    "offset=(%.1f,%.1f) overflow_x=%d overflow_y=%d message_pt=%.1f"
                ),
                int(round(width_px)),
                int(round(height_px)),
                transform.mode.value,
                transform.scale,
                scale_x,
                scale_y,
                diagonal_scale,
                transform.scaled_size[0],
                transform.scaled_size[1],
                mapper.offset_x,
                mapper.offset_y,
                1 if transform.overflow_x else 0,
                1 if transform.overflow_y else 0,
                self._debug_message_point_size,
            )
            self._last_logged_scale = current

    def _extract_plugin_name(self, payload: Mapping[str, Any]) -> Optional[str]:
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
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is not None:
            inferred = override_manager.infer_plugin_name(payload)
            if inferred:
                return inferred
        return None

    def _should_trace_payload(self, plugin: Optional[str], message_id: str) -> bool:
        cfg = self._debug_config
        if not cfg.trace_enabled:
            return False
        if cfg.trace_payload_ids:
            if not message_id:
                return False
            if not any(message_id.startswith(prefix) for prefix in cfg.trace_payload_ids):
                return False
        return True

    @staticmethod
    def _format_trace_points(points: Any) -> List[Tuple[Any, Any]]:
        formatted: List[Tuple[Any, Any]] = []
        if isinstance(points, list):
            for entry in points:
                if isinstance(entry, Mapping):
                    formatted.append((entry.get("x"), entry.get("y")))
                elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    formatted.append((entry[0], entry[1]))
        return formatted

    def _log_legacy_trace(
        self,
        plugin: Optional[str],
        message_id: str,
        stage: str,
        info: Mapping[str, Any],
    ) -> None:
        if not self._should_trace_payload(plugin, message_id):
            return
        serialisable: Dict[str, Any] = {}
        for key, value in info.items():
            if key in {"points", "scaled_points"}:
                serialisable[key] = self._format_trace_points(value)
            else:
                serialisable[key] = value
        _CLIENT_LOGGER.debug(
            "trace plugin=%s id=%s stage=%s info=%s",
            plugin or "unknown",
            message_id,
            stage,
            serialisable,
        )

    def _trace_legacy_store_event(self, stage: str, item: LegacyItem) -> None:
        details: Dict[str, Any] = {"kind": item.kind}
        if item.kind == "vector":
            details["points"] = item.data.get("points")
        self._log_legacy_trace(item.plugin, item.item_id, stage, details)

    def _current_override_nonce(self) -> str:
        controller_nonce = getattr(self, "_controller_active_nonce", "") or ""
        if controller_nonce:
            return controller_nonce
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is not None:
            getter = getattr(override_manager, "current_override_nonce", None)
            if callable(getter):
                try:
                    token = getter()
                    if token:
                        return str(token)
                except Exception:
                    return ""
        return ""

    def _current_override_generation_ts(self) -> float:
        override_manager = getattr(self, "_override_manager", None)
        generation_ts = 0.0
        if override_manager is not None:
            getter = getattr(override_manager, "override_generation_timestamp", None)
            if callable(getter):
                try:
                    generation_ts = float(getter())
                except Exception:
                    generation_ts = 0.0
        controller_ts = getattr(self, "_controller_override_ts", 0.0)
        nonce_ts = getattr(self, "_controller_active_nonce_ts", 0.0)
        for candidate in (controller_ts, nonce_ts):
            if candidate and candidate > generation_ts:
                generation_ts = candidate
        return generation_ts

    def _handle_legacy(self, payload: Dict[str, Any]) -> None:
        plugin_name = self._extract_plugin_name(payload)
        message_id = str(payload.get("id") or "")
        self._override_manager.apply(payload)
        inferred = self._override_manager.infer_plugin_name(payload)
        if inferred:
            payload["plugin"] = inferred
            plugin_name = inferred
        else:
            plugin_name = self._extract_plugin_name(payload)
        trace_enabled = self._should_trace_payload(plugin_name, message_id)
        if trace_enabled and str(payload.get("shape") or "").lower() == "vect":
            self._log_legacy_trace(plugin_name, message_id, "post_override", {"points": payload.get("vector")})
        trace_fn: Optional[TraceCallback] = None
        if trace_enabled:
            def trace_fn(stage: str, _payload: Mapping[str, Any], extra: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, message_id, stage, extra)

        group_label = self._override_manager.grouping_label_for_id(message_id)
        if self._payload_model.ingest(
            payload,
            trace_fn=trace_fn,
            override_generation=self._override_manager.generation,
            group_label=group_label,
        ):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self._mark_legacy_cache_dirty()
            self._request_repaint("ingest", immediate=self._should_bypass_debounce(payload))

    def _purge_legacy(self) -> None:
        now = time.monotonic()
        previous_count = len(self._payload_model)
        if self._payload_model.purge_expired(now):
            if self._cycle_payload_enabled:
                self._sync_cycle_items()
            self._mark_legacy_cache_dirty()
            expired_count = max(0, previous_count - len(self._payload_model))
            if expired_count and self._repaint_metrics.get("enabled"):
                _CLIENT_LOGGER.debug(
                    "Expired payloads purged: count=%d timer_active=%s",
                    expired_count,
                    getattr(self, "_repaint_timer", None).isActive() if getattr(self, "_repaint_timer", None) else False,
                )
            self._request_repaint("purge")
        if not len(self._payload_model):
            self._group_log_pending_base.clear()
            self._group_log_pending_transform.clear()
            self._group_log_next_allowed.clear()
            self._logged_group_bounds.clear()
            self._logged_group_transforms.clear()

    def _paint_legacy(self, painter: QPainter) -> None:
        mapper = self._compute_legacy_mapper()
        state = self._viewport_state()
        context = RenderContext(
            width=max(self.width(), 0),
            height=max(self.height(), 0),
            mapper=mapper,
            dev_mode=self._dev_mode_enabled,
            debug_bounds=self._debug_config.group_bounds_outline,
            debug_vertices=self._debug_config.payload_vertex_markers,
            settings=RenderSettings(
                font_family=self._font_family,
                font_fallbacks=self._font_fallbacks,
                preset_point_size=lambda label, s=state, m=mapper: self._legacy_preset_point_size(label, s, m),
            ),
            grouping=self._grouping_adapter,
        )
        snapshot = PayloadSnapshot(items_count=len(list(self._payload_model.store.items())))
        self._render_pipeline.paint(painter, context, snapshot)
        payload_results = getattr(self._render_pipeline, "_last_payload_results", None)
        if payload_results:
            latest_base_payload = payload_results.get("latest_base_payload") or {}
            transform_candidates = payload_results.get("transform_candidates") or {}
            translations = payload_results.get("translations") or {}
            report_overlay_bounds = payload_results.get("report_overlay_bounds") or {}
            transform_by_group = payload_results.get("transform_by_group") or {}
            overlay_bounds_for_draw = payload_results.get("overlay_bounds_for_draw") or {}
            overlay_bounds_base = payload_results.get("overlay_bounds_base") or {}
            commands = payload_results.get("commands") or []
            translated_bounds_by_group = payload_results.get("translated_bounds_by_group") or {}
            trace_helper = self._group_trace_helper(report_overlay_bounds, commands)
            trace_helper()
            # Preserve existing behavior for log buffers/trace helper.
            self._apply_group_logging_payloads(
                latest_base_payload,
                transform_candidates,
                translations,
                report_overlay_bounds,
                commands,
            )
            anchor_translations = payload_results.get("anchor_translation_by_group") or {}
            # Preserve debug helpers/logging behavior.
            self._maybe_collect_debug_helpers(
                commands,
                overlay_bounds_for_draw,
                overlay_bounds_base,
                transform_by_group,
                translations,
                report_overlay_bounds,
                mapper,
            )
            try:
                self._last_overlay_bounds_for_target = self._clone_overlay_bounds_map(overlay_bounds_for_draw)
                self._last_transform_by_group = dict(transform_by_group)
            except Exception:
                pass
            self._update_last_visible_overlay_bounds_for_target(overlay_bounds_for_draw, commands)
            # Paint commands and collect offscreen/debug helpers.
            self._render_commands(
                painter,
                commands,
                anchor_translations,
                translations,
                translated_bounds_by_group,
                overlay_bounds_for_draw,
                overlay_bounds_base,
                report_overlay_bounds,
                transform_by_group,
                mapper,
            )

    def _apply_group_logging_payloads(
        self,
        latest_base_payload: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
        transform_candidates: Mapping[Tuple[str, Optional[str]], Tuple[str, Optional[str]]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        commands: Sequence[_LegacyPaintCommand],
    ) -> None:
        """Apply group logging/cache updates using payload data returned by the render pipeline."""
        payload_results = getattr(self._render_pipeline, "_last_payload_results", {}) or {}
        cache_base_payloads = payload_results.get("cache_base_payloads") or {}
        cache_transform_payloads = payload_results.get("cache_transform_payloads") or {}
        active_group_keys: Set[Tuple[str, Optional[str]]] = payload_results.get("active_group_keys") or set()
        now_monotonic = self._monotonic_now() if hasattr(self, "_monotonic_now") else time.monotonic()
        mode_state = self.controller_mode_state() if hasattr(self, "controller_mode_state") else "inactive"
        visible_groups = self._visible_group_keys(commands)
        if visible_groups:
            cache_base_payloads = {key: payload for key, payload in cache_base_payloads.items() if key in visible_groups}
            cache_transform_payloads = {
                key: payload for key, payload in cache_transform_payloads.items() if key in visible_groups
            }
        else:
            cache_base_payloads = {}
            cache_transform_payloads = {}

        for key, payload in latest_base_payload.items():
            edit_nonce = str(payload.get("edit_nonce") or "")
            last_nonce = self._group_cache_generations.get(key)
            if edit_nonce and edit_nonce != last_nonce:
                self._logged_group_bounds.pop(key, None)
                self._logged_group_transforms.pop(key, None)
                self._group_log_pending_base.pop(key, None)
                self._group_log_pending_transform.pop(key, None)
                self._group_cache_generations[key] = edit_nonce
            elif not edit_nonce:
                self._group_cache_generations.pop(key, None)
            bounds_tuple = payload.get("bounds_tuple")
            pending_payload = self._group_log_pending_base.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = self._logged_group_bounds.get(key)
            should_schedule = pending_payload is not None or last_logged != bounds_tuple
            if should_schedule:
                if pending_payload is None or pending_tuple != bounds_tuple:
                    self._group_log_pending_base[key] = dict(payload)
                    delay_target = (
                        now_monotonic
                        if self._payload_log_delay <= 0.0
                        else (now_monotonic or 0.0) + self._payload_log_delay
                    )
                    self._group_log_next_allowed[key] = delay_target
            else:
                self._group_log_pending_base.pop(key, None)
                self._group_log_next_allowed.pop(key, None)
            if not payload.get("has_transformed"):
                self._group_log_pending_transform.pop(key, None)

        for key, _labels in transform_candidates.items():
            report_bounds = report_overlay_bounds.get(key)
            if report_bounds is None or not report_bounds.is_valid():
                self._group_log_pending_transform.pop(key, None)
                continue
            transform_payload = cache_transform_payloads.get(key)
            if transform_payload is None:
                continue
            transform_tuple = (
                report_bounds.min_x,
                report_bounds.min_y,
                report_bounds.max_x,
                report_bounds.max_y,
            )
            pending_payload = self._group_log_pending_transform.get(key)
            pending_tuple = pending_payload.get("bounds_tuple") if pending_payload else None
            last_logged = self._logged_group_transforms.get(key)
            should_schedule = pending_payload is not None or last_logged != transform_tuple
            if not should_schedule:
                self._group_log_pending_transform.pop(key, None)
                continue
            if pending_payload is None or pending_tuple != transform_tuple:
                self._group_log_pending_transform[key] = {
                    **transform_payload,
                    "bounds_tuple": transform_tuple,
                }
                if key not in self._group_log_pending_base:
                    base_snapshot = latest_base_payload.get(key)
                    if base_snapshot is not None:
                        self._group_log_pending_base[key] = dict(base_snapshot)
                delay_target = (
                    now_monotonic
                    if self._payload_log_delay <= 0.0
                    else (now_monotonic or 0.0) + self._payload_log_delay
                )
                self._group_log_next_allowed[key] = delay_target

        updated_cache_keys = self._update_group_cache_from_payloads(cache_base_payloads, cache_transform_payloads)
        self._flush_group_log_entries(active_group_keys)
        if updated_cache_keys:
            now = time.monotonic()
            for key in updated_cache_keys:
                snapshot = cache_base_payloads.get(key, {})
                self._cache_write_metadata[key] = {
                    "edit_nonce": str(snapshot.get("edit_nonce") or ""),
                    "controller_ts": snapshot.get("controller_ts", 0.0),
                    "timestamp": now,
                }
            if mode_state == "active":
                self._force_group_cache_flush()

    def _maybe_collect_debug_helpers(
        self,
        commands: Sequence[Any],
        overlay_bounds_for_draw: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        overlay_bounds_base: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        mapper: LegacyMapper,
    ) -> None:
        collect_debug_helpers = self._dev_mode_enabled and self._debug_config.group_bounds_outline
        if collect_debug_helpers:
            final_bounds_map = overlay_bounds_for_draw if overlay_bounds_for_draw else overlay_bounds_base
            self._debug_group_bounds_final = self._clone_overlay_bounds_map(final_bounds_map)
            self._debug_group_state = self._build_group_debug_state(
                self._debug_group_bounds_final,
                transform_by_group,
                translations,
                canonical_bounds=report_overlay_bounds,
            )
        else:
            self._debug_group_bounds_final = {}
            self._debug_group_state = {}

    def _render_commands(
        self,
        painter: QPainter,
        commands: Sequence[Any],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        translated_bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_for_draw: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        overlay_bounds_base: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        report_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        mapper: LegacyMapper,
    ) -> None:
        collect_debug_helpers = self._dev_mode_enabled and self._debug_config.group_bounds_outline
        window_width = max(self.width(), 0)
        window_height = max(self.height(), 0)
        draw_vertex_markers = self._dev_mode_enabled and self._debug_config.payload_vertex_markers
        self._paint_group_backgrounds(
            painter,
            transform_by_group,
            translated_bounds_by_group,
            translations,
        )
        vertex_points: List[Tuple[int, int]] = []
        for command in commands:
            key_tuple = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key_tuple, (0.0, 0.0))
            nudge_x, nudge_y = translations.get(key_tuple, (0, 0))
            justification_dx = getattr(command, "justification_dx", 0.0)
            payload_offset_x = translation_x + justification_dx + nudge_x
            payload_offset_y = translation_y + nudge_y
            log_offscreen_payload(
                command=command,
                offset_x=payload_offset_x,
                offset_y=payload_offset_y,
                window_width=window_width,
                window_height=window_height,
                offscreen_payloads=self._offscreen_payloads,
                log_fn=_CLIENT_LOGGER.warning,
            )
            command.paint(self, painter, payload_offset_x, payload_offset_y)
            if draw_vertex_markers and command.bounds:
                left, top, right, bottom = command.bounds
                group_corners = [
                    (left, top),
                    (right, top),
                    (left, bottom),
                    (right, bottom),
                ]
                trace_vertices = self._should_trace_payload(
                    getattr(command.legacy_item, "plugin", None),
                    command.legacy_item.item_id,
                )
                for px, py in group_corners:
                    adjusted_x = int(round(float(px) + payload_offset_x))
                    adjusted_y = int(round(float(py) + payload_offset_y))
                    vertex_points.append((adjusted_x, adjusted_y))
                    if trace_vertices:
                        self._log_legacy_trace(
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
            self._draw_payload_vertex_markers(painter, vertex_points)
        if collect_debug_helpers:
            self._draw_group_debug_helpers(painter, mapper)

    def _paint_group_backgrounds(
        self,
        painter: QPainter,
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        translated_bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
    ) -> None:
        if not transform_by_group:
            return
        for key, transform in transform_by_group.items():
            if transform is None:
                continue
            fill_value = getattr(transform, "background_color", None)
            border_value = getattr(transform, "background_border_color", None)
            if not fill_value and not border_value:
                continue
            bounds = translated_bounds_by_group.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            try:
                border_width = int(getattr(transform, "background_border_width", 0) or 0)
            except Exception:
                border_width = 0
            nudge_x, nudge_y = translations.get(key, (0, 0))
            left = bounds.min_x + nudge_x
            right = bounds.max_x + nudge_x
            top = bounds.min_y + nudge_y
            bottom = bounds.max_y + nudge_y
            left_px = int(round(left - border_width))
            top_px = int(round(top - border_width))
            width_px = int(round((right - left) + border_width * 2))
            height_px = int(round((bottom - top) + border_width * 2))
            if fill_value:
                q_color = self._qcolor_from_background(fill_value)
                if q_color is not None:
                    q_color = self._apply_payload_opacity_color(q_color)
                    painter.save()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(q_color))
                    painter.drawRect(left_px, top_px, width_px, height_px)
                    painter.restore()
            if border_value:
                q_border = self._qcolor_from_background(border_value)
                if q_border is not None:
                    q_border = self._apply_payload_opacity_color(q_border)
                    outer_left = left_px - 1
                    outer_top = top_px - 1
                    outer_right = left_px + width_px + 1
                    outer_bottom = top_px + height_px + 1
                    painter.save()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(q_border))
                    painter.drawRect(outer_left, outer_top, outer_right - outer_left, 1)
                    painter.drawRect(outer_left, outer_bottom - 1, outer_right - outer_left, 1)
                    painter.drawRect(outer_left, top_px, 1, height_px)
                    painter.drawRect(outer_right - 1, top_px, 1, height_px)
                    painter.restore()

    @staticmethod
    def _qcolor_from_background(value: object) -> Optional[QColor]:
        if not isinstance(value, str):
            return None
        token = value.strip()
        if not token:
            return None
        if not token.startswith("#"):
            if len(token) in (6, 8) and all(ch in "0123456789abcdefABCDEF" for ch in token):
                token = "#" + token
            else:
                q_color = QColor(token)
                return q_color if q_color.isValid() else None
        if len(token) == 9:
            hex_part = token[1:]
            if not all(ch in "0123456789abcdefABCDEF" for ch in hex_part):
                return None
            try:
                alpha = int(hex_part[0:2], 16)
                red = int(hex_part[2:4], 16)
                green = int(hex_part[4:6], 16)
                blue = int(hex_part[6:8], 16)
            except ValueError:
                return None
            return QColor(red, green, blue, alpha)
        q_color = QColor(token)
        return q_color if q_color.isValid() else None

    def _build_legacy_commands_for_pass(
        self,
        mapper: LegacyMapper,
        overlay_bounds_hint: Optional[Dict[Tuple[str, Optional[str]], _OverlayBounds]],
        collect_only: bool = False,
    ) -> Tuple[
        List[_LegacyPaintCommand],
        Dict[Tuple[str, Optional[str]], _ScreenBounds],
        Dict[Tuple[str, Optional[str]], _OverlayBounds],
        Dict[Tuple[str, Optional[str]], Tuple[float, float]],
        Dict[Tuple[str, Optional[str]], Optional[GroupTransform]],
    ]:
        commands: List[_LegacyPaintCommand] = []
        bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        effective_anchor_by_group: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        transform_by_group: Dict[Tuple[str, Optional[str]], Optional[GroupTransform]] = {}
        for item_id, legacy_item in self._payload_model.store.items():
            group_key = self._group_coordinator.resolve_group_key(
                item_id,
                legacy_item.plugin,
                self._override_manager,
            )
            group_transform = self._grouping_helper.get_transform(group_key)
            transform_by_group[group_key.as_tuple()] = group_transform
            has_explicit_offset = False
            if group_transform is not None:
                dx = getattr(group_transform, "dx", 0.0)
                dy = getattr(group_transform, "dy", 0.0)
                has_explicit_offset = bool(dx) or bool(dy)
            overlay_hint = None
            if overlay_bounds_hint and not has_explicit_offset:
                overlay_hint = overlay_bounds_hint.get(group_key.as_tuple())
            if legacy_item.kind == "message":
                command = self._build_message_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            elif legacy_item.kind == "rect":
                command = self._build_rect_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            elif legacy_item.kind == "vector":
                command = self._build_vector_command(
                    legacy_item,
                    mapper,
                    group_key,
                    group_transform,
                    overlay_hint,
                    collect_only=collect_only,
                )
            else:
                command = None
            if command is None:
                continue
            if not collect_only:
                commands.append(command)
                if command.bounds:
                    bounds = bounds_by_group.setdefault(command.group_key.as_tuple(), _ScreenBounds())
                    bounds.include_rect(*command.bounds)
                if command.effective_anchor is not None:
                    effective_anchor_by_group[command.group_key.as_tuple()] = command.effective_anchor
            if command.overlay_bounds:
                overlay_bounds = overlay_bounds_by_group.setdefault(command.group_key.as_tuple(), _OverlayBounds())
                overlay_bounds.include_rect(*command.overlay_bounds)
            if collect_only:
                continue
        return commands, bounds_by_group, overlay_bounds_by_group, effective_anchor_by_group, transform_by_group

    def _prepare_anchor_translations(
        self,
        mapper: LegacyMapper,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_by_group: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        effective_anchor_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
    ) -> Tuple[Dict[Tuple[str, Optional[str]], Tuple[float, float]], Dict[Tuple[str, Optional[str]], _ScreenBounds]]:
        cloned_bounds: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for key, bounds in bounds_by_group.items():
            if bounds is None or not bounds.is_valid():
                continue
            clone = _ScreenBounds()
            clone.min_x = bounds.min_x
            clone.max_x = bounds.max_x
            clone.min_y = bounds.min_y
            clone.max_y = bounds.max_y
            cloned_bounds[key] = clone
        translations: Dict[Tuple[str, Optional[str]], Tuple[float, float]] = {}
        base_scale = mapper.transform.scale
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key in bounds_by_group:
            translation_overlay_x: Optional[float]
            translation_overlay_y: Optional[float]
            bounds = overlay_bounds_by_group.get(key)
            token = None
            transform = transform_by_group.get(key)
            if transform is not None:
                token = getattr(transform, "anchor_token", None)
            translation_overlay_x = translation_overlay_y = None
            if bounds is not None and bounds.is_valid() and token:
                user_anchor = self._anchor_from_overlay_bounds(bounds, token)
                if user_anchor is not None:
                    translation_overlay_x = bounds.min_x - user_anchor[0]
                    translation_overlay_y = bounds.min_y - user_anchor[1]
            if translation_overlay_x is None or translation_overlay_y is None:
                continue
            if not (math.isfinite(translation_overlay_x) and math.isfinite(translation_overlay_y)):
                continue
            translation_px_x = translation_overlay_x * base_scale
            translation_px_y = translation_overlay_y * base_scale
            translations[key] = (translation_px_x, translation_px_y)
            clone = cloned_bounds.get(key)
            if clone is not None:
                clone.translate(translation_px_x, translation_px_y)
        return translations, cloned_bounds

    def _apply_payload_justification(
        self,
        commands: Sequence[_LegacyPaintCommand],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        translated_bounds_by_group: Dict[Tuple[str, Optional[str]], _ScreenBounds],
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        base_overlay_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _ScreenBounds]:
        command_contexts: List[CommandContext] = []
        for command in commands:
            command.justification_dx = 0.0
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            transform = transform_by_group.get(key)
            justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
            suffix = command.group_key.suffix
            plugin = getattr(command.legacy_item, "plugin", None)
            item_id = command.legacy_item.item_id
            command_contexts.append(
                CommandContext(
                    identifier=id(command),
                    key=key,
                    bounds=(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])),
                    raw_min_x=command.raw_min_x,
                    right_just_multiplier=getattr(command, "right_just_multiplier", 0),
                    justification=justification,
                    suffix=suffix,
                    plugin=plugin,
                    item_id=item_id,
                )
            )

        def _trace(plugin: Optional[str], item_id: str, stage: str, details: Dict[str, float]) -> None:
            self._log_legacy_trace(plugin, item_id, stage, details)

        command_by_identifier = {id(command): command for command in commands}
        justify_base_bounds: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        justify_overlay_bounds: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        for ctx in command_contexts:
            if ctx.justification not in {"center", "right"}:
                continue
            cmd = command_by_identifier.get(ctx.identifier)
            if cmd is None:
                continue
            if cmd.base_overlay_bounds:
                bounds = justify_base_bounds.setdefault(ctx.key, _OverlayBounds())
                bounds.include_rect(*cmd.base_overlay_bounds)
            if cmd.overlay_bounds:
                bounds = justify_overlay_bounds.setdefault(ctx.key, _OverlayBounds())
                bounds.include_rect(*cmd.overlay_bounds)

        base_bounds_map: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        for key, bounds in base_overlay_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            base_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        for key, bounds in justify_base_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            base_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        overlay_bounds_map: Dict[Tuple[str, Optional[str]], Tuple[float, float, float, float]] = {}
        for key, bounds in overlay_bounds_by_group.items():
            if bounds is None or not bounds.is_valid():
                continue
            overlay_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        for key, bounds in justify_overlay_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            overlay_bounds_map[key] = (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
        baseline_bounds = build_baseline_bounds(base_bounds_map, overlay_bounds_map)

        offset_map = compute_justification_offsets(
            command_contexts,
            transform_by_group,
            baseline_bounds,
            base_scale,
            trace_fn=_trace,
        )
        if not offset_map:
            return translated_bounds_by_group

        updated_bounds: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for command in commands:
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            command.justification_dx = offset_map.get(id(command), 0.0)
            translation_x, translation_y = anchor_translation_by_group.get(key, (0.0, 0.0))
            offset_x = translation_x + command.justification_dx
            offset_y = translation_y
            clone = updated_bounds.setdefault(key, _ScreenBounds())
            clone.include_rect(
                float(bounds[0]) + offset_x,
                float(bounds[1]) + offset_y,
                float(bounds[2]) + offset_x,
                float(bounds[3]) + offset_y,
            )
        for key, original in translated_bounds_by_group.items():
            if key in updated_bounds:
                continue
            clone = _ScreenBounds()
            clone.min_x = original.min_x
            clone.max_x = original.max_x
            clone.min_y = original.min_y
            clone.max_y = original.max_y
            updated_bounds[key] = clone
        return updated_bounds

    def _rebuild_translated_bounds(
        self,
        commands: Sequence[_LegacyPaintCommand],
        anchor_translation_by_group: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        baseline_bounds: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
    ) -> Dict[Tuple[str, Optional[str]], _ScreenBounds]:
        updated: Dict[Tuple[str, Optional[str]], _ScreenBounds] = {}
        for command in commands:
            bounds = command.bounds
            if not bounds:
                continue
            key = command.group_key.as_tuple()
            translation_x, translation_y = anchor_translation_by_group.get(key, (0.0, 0.0))
            justification_dx = getattr(command, "justification_dx", 0.0)
            offset_x = translation_x
            offset_y = translation_y
            if justification_dx:
                offset_x += justification_dx
            clone = updated.setdefault(key, _ScreenBounds())
            clone.include_rect(
                float(bounds[0]) + offset_x,
                float(bounds[1]) + offset_y,
                float(bounds[2]) + offset_x,
                float(bounds[3]) + offset_y,
            )
        for key, original in baseline_bounds.items():
            if key in updated:
                continue
            clone = _ScreenBounds()
            clone.min_x = original.min_x
            clone.max_x = original.max_x
            clone.min_y = original.min_y
            clone.max_y = original.max_y
            updated[key] = clone
        return updated

    @staticmethod
    def _anchor_from_overlay_bounds(bounds: _OverlayBounds, token: Optional[str]) -> Optional[Tuple[float, float]]:
        if bounds is None or not bounds.is_valid():
            return None
        token = (token or "nw").strip().lower()
        min_x = bounds.min_x
        max_x = bounds.max_x
        min_y = bounds.min_y
        max_y = bounds.max_y
        mid_x = (min_x + max_x) / 2.0
        mid_y = (min_y + max_y) / 2.0
        if token in {"nw"}:
            return min_x, min_y
        if token in {"ne"}:
            return max_x, min_y
        if token in {"left", "west"}:
            return min_x, mid_y
        if token in {"right", "east"}:
            return max_x, mid_y
        if token in {"sw"}:
            return min_x, max_y
        if token in {"se"}:
            return max_x, max_y
        if token == "top":
            return mid_x, min_y
        if token == "bottom":
            return mid_x, max_y
        if token == "center":
            return mid_x, mid_y
        # fallback to base (nw)
        return min_x, min_y

    @staticmethod
    def _right_justification_delta(
        transform: Optional[GroupTransform],
        payload_min_x: Optional[float],
    ) -> float:
        if transform is None or payload_min_x is None:
            return 0.0
        justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
        if justification != "right":
            return 0.0
        reference = getattr(transform, "bounds_min_x", None)
        try:
            reference_value = float(reference)
            payload_value = float(payload_min_x)
        except (TypeError, ValueError):
            return 0.0
        if not (math.isfinite(reference_value) and math.isfinite(payload_value)):
            return 0.0
        delta = payload_value - reference_value
        if math.isclose(delta, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            return 0.0
        return delta

    def _legacy_preset_point_size(self, preset: str, state: ViewportState, mapper: LegacyMapper) -> float:
        """Return the scaled font size for a legacy preset relative to normal."""
        return util_legacy_preset_point_size(
            preset,
            state,
            mapper,
            self._font_scale_diag,
            self._font_min_point,
            self._font_max_point,
            getattr(self, "_legacy_font_step", 2.0),
        )

    def _invalidate_text_cache(self, reason: Optional[str] = None) -> None:
        cache = getattr(self, "_text_cache", None)
        block_cache = getattr(self, "_text_block_cache", None)
        if isinstance(cache, dict):
            cache.clear()
        if isinstance(block_cache, dict):
            block_cache.clear()
        self._text_cache_generation += 1
        if isinstance(self._measure_stats, dict):
            self._measure_stats["cache_reset"] = self._measure_stats.get("cache_reset", 0) + 1
        if reason and self._dev_mode_enabled:
            _CLIENT_LOGGER.debug("Text cache invalidated (%s)", reason)

    def _ensure_text_cache_context(self, family: str) -> None:
        fallback_tuple: Tuple[str, ...] = tuple(getattr(self, "_font_fallbacks", ()))
        try:
            device_ratio = float(self.devicePixelRatioF())
        except Exception:
            device_ratio = 1.0
        if device_ratio <= 0.0 or not math.isfinite(device_ratio):
            device_ratio = 1.0
        context = (family, fallback_tuple, round(device_ratio, 3))
        if context != getattr(self, "_text_cache_context", None):
            self._text_cache_context = context
            self._invalidate_text_cache("font/dpi change")

    def _measure_text(self, text: str, point_size: float, font_family: Optional[str] = None) -> Tuple[int, int, int]:
        stats = getattr(self, "_measure_stats", None)
        if isinstance(stats, dict):
            stats["calls"] = stats.get("calls", 0) + 1
        cache = getattr(self, "_text_cache", None)
        family = font_family or self._font_family
        normalised = str(text)
        has_newline = "\n" in normalised or "\r" in normalised
        if has_newline:
            normalised = normalised.replace("\r\n", "\n").replace("\r", "\n")
        try:
            ensure_context = getattr(self, "_ensure_text_cache_context", None)
            if callable(ensure_context):
                ensure_context(family)
        except Exception:
            pass
        key = (text, point_size, family)
        if cache is not None:
            cached = cache.get(key)
            if cached is not None:
                stats["cache_hit"] = stats.get("cache_hit", 0) + 1 if isinstance(stats, dict) else 0
                return cached
        if self._text_measurer is not None:
            if has_newline:
                lines = normalised.split("\n") or [""]
                max_width = 0
                line_height = 0
                ascent = 0
                for idx, line in enumerate(lines):
                    measured = self._text_measurer(line, point_size, font_family or self._font_family)
                    if idx == 0:
                        ascent = max(0, int(measured.ascent))
                    line_width = max(0, int(measured.width))
                    if line_width > max_width:
                        max_width = line_width
                    line_height = max(line_height, int(measured.ascent + measured.descent))
                total_height = line_height * max(1, len(lines))
                descent = max(0, total_height - ascent)
                measured_tuple = (max_width, ascent, descent)
                if cache is not None:
                    stats["cache_miss"] = stats.get("cache_miss", 0) + 1 if isinstance(stats, dict) else 0
                    cache[key] = measured_tuple
                    if len(cache) > self._TEXT_CACHE_MAX:
                        cache.pop(next(iter(cache)))
                return measured_tuple
            measured = self._text_measurer(text, point_size, font_family or self._font_family)
            return measured.width, measured.ascent, measured.descent
        metrics_font = QFont(family)
        self._apply_font_fallbacks(metrics_font)
        metrics_font.setPointSizeF(point_size)
        metrics_font.setWeight(QFont.Weight.Normal)
        metrics = QFontMetrics(metrics_font)
        if has_newline:
            lines = normalised.split("\n") or [""]
            max_width = 0
            for line in lines:
                try:
                    advance = metrics.horizontalAdvance(line)
                except Exception:
                    advance = 0
                if advance > max_width:
                    max_width = advance
            line_spacing = max(metrics.lineSpacing(), metrics.height(), 0)
            if line_spacing <= 0:
                line_spacing = metrics.ascent() + metrics.descent()
            total_height = line_spacing * max(1, len(lines))
            ascent = metrics.ascent()
            descent = max(0, int(total_height - ascent))
            measured = (max(0, max_width), ascent, descent)
        else:
            measured = (metrics.horizontalAdvance(text), metrics.ascent(), metrics.descent())
        if cache is not None:
            stats["cache_miss"] = stats.get("cache_miss", 0) + 1 if isinstance(stats, dict) else 0
            cache[key] = measured
            if len(cache) > self._TEXT_CACHE_MAX:
                cache.pop(next(iter(cache)))
        return measured

    def set_text_measurer(self, measurer: Optional[Callable[[str, float, str], _MeasuredText]]) -> None:
        self._text_measurer = measurer

    def _build_message_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_MessagePaintCommand]:
        item = legacy_item.data
        item_id = legacy_item.item_id
        plugin_name = legacy_item.plugin
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        color = QColor(str(item.get("color", "white")))
        size = str(item.get("size", "normal")).lower()
        state = self._viewport_state()
        scaled_point_size = self._legacy_preset_point_size(size, state, mapper)
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        base_offset_x = group_ctx.base_offset_x
        base_offset_y = group_ctx.base_offset_y
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        transform_meta = item.get("__mo_transform__")
        self._debug_legacy_point_size = scaled_point_size
        raw_left = float(item.get("x", 0))
        raw_top = float(item.get("y", 0))
        (
            adjusted_left,
            adjusted_top,
            base_left_logical,
            base_top_logical,
            effective_anchor,
            translation_dx,
            translation_dy,
        ) = self._compute_message_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            overlay_bounds_hint,
            raw_left,
            raw_top,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_enabled,
            collect_only,
        )
        text = str(item.get("text", ""))
        text_width, ascent, descent = self._measure_text(text, scaled_point_size, self._font_family)
        metrics_font = QFont(self._font_family)
        self._apply_font_fallbacks(metrics_font)
        metrics_font.setPointSizeF(scaled_point_size)
        metrics_font.setWeight(QFont.Weight.Normal)
        metrics = QFontMetrics(metrics_font)
        line_spacing = max(metrics.lineSpacing(), metrics.height(), 0)
        if line_spacing <= 0:
            line_spacing = ascent + descent
        x = int(round(fill.screen_x(adjusted_left)))
        payload_point_y = int(round(fill.screen_y(adjusted_top)))
        baseline = int(round(payload_point_y + ascent))
        center_x = x + text_width // 2
        top = baseline - ascent
        bottom = baseline + descent
        center_y = int(round((top + bottom) / 2.0))
        bounds = (x, top, x + text_width, bottom)
        overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        base_overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        if scale > 0.0:
            overlay_left = (bounds[0] - base_offset_x) / scale
            overlay_top = (bounds[1] - base_offset_y) / scale
            overlay_right = (bounds[2] - base_offset_x) / scale
            overlay_bottom = (bounds[3] - base_offset_y) / scale
            overlay_bounds = (overlay_left, overlay_top, overlay_right, overlay_bottom)
            base_x = int(round(fill.screen_x(base_left_logical)))
            base_base_y = int(round(fill.screen_y(base_top_logical)))
            base_baseline = int(round(base_base_y + ascent))
            base_top = base_baseline - ascent
            base_bottom = base_baseline + descent
            base_bounds = (base_x, base_top, base_x + text_width, base_bottom)
            base_overlay_left = (base_bounds[0] - base_offset_x) / scale
            base_overlay_top = (base_bounds[1] - base_offset_y) / scale
            base_overlay_right = (base_bounds[2] - base_offset_x) / scale
            base_overlay_bottom = (base_bounds[3] - base_offset_y) / scale
            base_overlay_bounds = (
                base_overlay_left,
                base_overlay_top,
                base_overlay_right,
                base_overlay_bottom,
            )
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:message_output",
                {
                    "adjusted_x": adjusted_left,
                    "adjusted_y": adjusted_top,
                    "pixel_x": x,
                    "baseline": baseline,
                    "text_width": text_width,
                    "font_size": scaled_point_size,
                    "mode": mapper.transform.mode.value,
                },
            )
        trace_fn = None
        if trace_enabled and not collect_only:
            def trace_fn(stage: str, details: Mapping[str, Any]) -> None:
                self._log_legacy_trace(plugin_name, item_id, stage, details)
        command = _MessagePaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            text=text,
            color=color,
            point_size=scaled_point_size,
            x=x,
            baseline=baseline,
            text_width=text_width,
            ascent=ascent,
            descent=descent,
            line_spacing=line_spacing,
            cycle_anchor=(center_x, center_y),
            trace_fn=trace_fn,
            base_overlay_bounds=base_overlay_bounds,
            debug_vertices=[(x, payload_point_y)],
            raw_min_x=raw_left,
            right_just_multiplier=2,
        )
        return command

    def _build_rect_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_RectPaintCommand]:
        item = legacy_item.data
        item_id = legacy_item.item_id
        plugin_name = legacy_item.plugin
        border_spec = str(item.get("color", "white"))
        fill_spec = str(item.get("fill", "#00000000"))

        if not border_spec or border_spec.lower() == "none":
            pen = QPen(Qt.PenStyle.NoPen)
        else:
            border_color = QColor(border_spec)
            if not border_color.isValid():
                pen = QPen(Qt.PenStyle.NoPen)
            else:
                pen = QPen(border_color)
                pen.setWidth(self._line_width("legacy_rect"))

        if not fill_spec or fill_spec.lower() == "none":
            brush = QBrush(Qt.BrushStyle.NoBrush)
        else:
            fill_color = QColor(fill_spec)
            if not fill_color.isValid():
                fill_color = QColor("#00000000")
            brush = QBrush(fill_color)

        state = self._viewport_state()
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        transform_meta = item.get("__mo_transform__")
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        raw_x = float(item.get("x", 0))
        raw_y = float(item.get("y", 0))
        raw_w = float(item.get("w", 0))
        raw_h = float(item.get("h", 0))
        transformed_overlay, base_overlay_points, reference_overlay_bounds, effective_anchor = self._compute_rect_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            raw_x,
            raw_y,
            raw_w,
            raw_h,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_enabled,
            collect_only,
        )
        xs_overlay = [pt[0] for pt in transformed_overlay]
        ys_overlay = [pt[1] for pt in transformed_overlay]
        min_x_overlay = min(xs_overlay)
        max_x_overlay = max(xs_overlay)
        min_y_overlay = min(ys_overlay)
        max_y_overlay = max(ys_overlay)
        x = int(round(fill.screen_x(min_x_overlay)))
        y = int(round(fill.screen_y(min_y_overlay)))
        w = max(1, int(round(max(0.0, max_x_overlay - min_x_overlay) * scale)))
        h = max(1, int(round(max(0.0, max_y_overlay - min_y_overlay) * scale)))
        center_x = x + w // 2
        center_y = y + h // 2
        bounds = (x, y, x + w, y + h)
        overlay_bounds = (min_x_overlay, min_y_overlay, max_x_overlay, max_y_overlay)
        base_overlay_bounds: Optional[Tuple[float, float, float, float]] = None
        if base_overlay_points:
            base_xs = [pt[0] for pt in base_overlay_points]
            base_ys = [pt[1] for pt in base_overlay_points]
            base_min_x = min(base_xs)
            base_max_x = max(base_xs)
            base_min_y = min(base_ys)
            base_max_y = max(base_ys)
            base_overlay_bounds = (base_min_x, base_min_y, base_max_x, base_max_y)
        command = _RectPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            pen=pen,
            brush=brush,
            x=x,
            y=y,
            width=w,
            height=h,
            cycle_anchor=(center_x, center_y),
            base_overlay_bounds=base_overlay_bounds,
            reference_overlay_bounds=reference_overlay_bounds,
            debug_vertices=[
                (x, y),
                (x + w, y),
                (x, y + h),
                (x + w, y + h),
            ],
            raw_min_x=raw_x,
            right_just_multiplier=2,
        )
        if trace_enabled and not collect_only:
            self._log_legacy_trace(
                plugin_name,
                item_id,
                "paint:rect_output",
                {
                    "adjusted_x": min_x_overlay,
                    "adjusted_y": min_y_overlay,
                    "adjusted_w": max_x_overlay - min_x_overlay,
                    "adjusted_h": max_y_overlay - min_y_overlay,
                    "pixel_x": x,
                    "pixel_y": y,
                    "pixel_w": w,
                    "pixel_h": h,
                    "mode": mapper.transform.mode.value,
                },
            )
        return command

    def _build_vector_command(
        self,
        legacy_item: LegacyItem,
        mapper: LegacyMapper,
        group_key: GroupKey,
        group_transform: Optional[GroupTransform],
        overlay_bounds_hint: Optional[_OverlayBounds],
        collect_only: bool = False,
    ) -> Optional[_VectorPaintCommand]:
        item_id = legacy_item.item_id
        item = legacy_item.data
        plugin_name = legacy_item.plugin
        trace_enabled = self._should_trace_payload(plugin_name, item_id)
        state = self._viewport_state()
        offset_x, offset_y = self._group_offsets(group_transform)
        group_ctx = build_group_context(
            mapper,
            state,
            group_transform,
            overlay_bounds_hint,
            offset_x,
            offset_y,
            group_anchor_point=self._group_anchor_point,
            group_base_point=self._group_base_point,
        )
        fill = group_ctx.fill
        transform_context = group_ctx.transform_context
        scale = group_ctx.scale
        selected_anchor = group_ctx.selected_anchor
        base_anchor_point = group_ctx.base_anchor_point
        anchor_for_transform = group_ctx.anchor_for_transform
        base_translation_dx = group_ctx.base_translation_dx
        base_translation_dy = group_ctx.base_translation_dy
        raw_points = item.get("points") or []
        transform_meta = item.get("__mo_transform__")
        (
            vector_payload,
            screen_points,
            overlay_bounds,
            base_overlay_bounds,
            effective_anchor,
            raw_min_x,
            trace_fn,
        ) = self._compute_vector_transform(
            plugin_name,
            item_id,
            fill,
            transform_context,
            transform_meta,
            mapper,
            group_transform,
            item,
            raw_points,
            offset_x,
            offset_y,
            selected_anchor,
            base_anchor_point,
            anchor_for_transform,
            base_translation_dx,
            base_translation_dy,
            trace_enabled,
            collect_only,
        )
        if vector_payload is None:
            return None
        bounds: Optional[Tuple[int, int, int, int]]
        cycle_anchor: Optional[Tuple[int, int]]
        if screen_points:
            xs = [pt[0] for pt in screen_points]
            ys = [pt[1] for pt in screen_points]
            bounds = (min(xs), min(ys), max(xs), max(ys))
            cycle_anchor = (
                int(round((min(xs) + max(xs)) / 2.0)),
                int(round((min(ys) + max(ys)) / 2.0)),
            )
        else:
            bounds = None
            cycle_anchor = None
        command = _VectorPaintCommand(
            group_key=group_key,
            group_transform=group_transform,
            legacy_item=legacy_item,
            bounds=bounds,
            overlay_bounds=overlay_bounds,
            effective_anchor=effective_anchor,
            debug_log=None,
            vector_payload=vector_payload,
            scale=scale,
            base_offset_x=fill.base_offset_x,
            base_offset_y=fill.base_offset_y,
            trace_fn=trace_fn,
            cycle_anchor=cycle_anchor,
            base_overlay_bounds=base_overlay_bounds,
            debug_vertices=tuple(screen_points),
            raw_min_x=raw_min_x,
            right_just_multiplier=2 if raw_min_x is not None else 0,
        )
        return command

    def _compute_group_nudges(
        self,
        bounds_by_group: Mapping[Tuple[str, Optional[str]], _ScreenBounds],
    ) -> Dict[Tuple[str, Optional[str]], Tuple[int, int]]:
        return self._group_coordinator.compute_group_nudges(
            bounds_by_group,
            self.width(),
            self.height(),
            self._payload_nudge_enabled,
            self._payload_nudge_gutter,
        )

    def _collect_base_overlay_bounds(
        self,
        commands: Sequence[_LegacyPaintCommand],
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        bounds_map: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        if not commands:
            return bounds_map
        for command in commands:
            if not command.base_overlay_bounds:
                continue
            bounds = bounds_map.setdefault(command.group_key.as_tuple(), _OverlayBounds())
            bounds.include_rect(*command.base_overlay_bounds)
        return bounds_map

    def _build_group_debug_state(
        self,
        final_bounds: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        transform_by_group: Mapping[Tuple[str, Optional[str]], Optional[GroupTransform]],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        canonical_bounds: Optional[Mapping[Tuple[str, Optional[str]], _OverlayBounds]] = None,
    ) -> Dict[Tuple[str, Optional[str]], _GroupDebugState]:
        state: Dict[Tuple[str, Optional[str]], _GroupDebugState] = {}
        for key, bounds in final_bounds.items():
            if bounds is None or not bounds.is_valid():
                continue
            transform = transform_by_group.get(key)
            use_transformed = self._has_user_group_transform(transform)
            anchor_token = (getattr(transform, "anchor_token", "nw") or "nw").strip().lower()
            justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
            anchor_point = self._anchor_from_overlay_bounds(bounds, anchor_token)
            if anchor_point is None:
                anchor_point = (bounds.min_x, bounds.min_y)
            anchor_logical = anchor_point
            if canonical_bounds is not None:
                logical_bounds = canonical_bounds.get(key)
                if logical_bounds is not None and logical_bounds.is_valid():
                    logical_anchor = self._anchor_from_overlay_bounds(logical_bounds, anchor_token)
                    if logical_anchor is not None:
                        anchor_logical = logical_anchor
            nudged = bool(translations.get(key))
            state[key] = _GroupDebugState(
                anchor_token=anchor_token or "nw",
                justification=justification or "left",
                use_transformed=use_transformed,
                anchor_point=anchor_point,
                anchor_logical=anchor_logical,
                nudged=nudged,
            )
        return state

    def _has_user_group_transform(self, transform: Optional[GroupTransform]) -> bool:
        if transform is None:
            return False
        anchor = (getattr(transform, "anchor_token", "nw") or "nw").strip().lower()
        justification = (getattr(transform, "payload_justification", "left") or "left").strip().lower()
        if anchor and anchor != "nw":
            return True
        if justification and justification not in {"", "left"}:
            return True
        return False

    def _group_trace_helper(
        self,
        bounds_map: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        commands: Sequence[_LegacyPaintCommand],
    ) -> Callable[[], None]:
        def _emit() -> None:
            for key, bounds in bounds_map.items():
                if bounds is None or not bounds.is_valid():
                    continue
                sample_command = next((cmd for cmd in commands if cmd.group_key.as_tuple() == key), None)
                if sample_command is None:
                    continue
                legacy_item = sample_command.legacy_item
                if not self._should_trace_payload(legacy_item.plugin, legacy_item.item_id):
                    continue
                self._log_legacy_trace(
                    legacy_item.plugin,
                    legacy_item.item_id,
                    "group:aggregate_bounds",
                    {
                        "group_key": key,
                        "trans_min_x": bounds.min_x,
                        "trans_max_x": bounds.max_x,
                        "trans_min_y": bounds.min_y,
                        "trans_max_y": bounds.max_y,
                    },
                )

        return _emit

    def _update_group_cache_from_payloads(
        self,
        base_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
        transform_payloads: Mapping[Tuple[str, Optional[str]], Mapping[str, Any]],
    ) -> Set[Tuple[str, Optional[str]]]:
        return set(
            self._group_coordinator.update_cache_from_payloads(
                base_payloads=base_payloads,
                transform_payloads=transform_payloads,
            )
            or []
        )

    def _force_group_cache_flush(self) -> None:
        cache = getattr(self, "_group_cache", None)
        if cache is None:
            return
        min_interval = max(0.05, getattr(self, "_controller_active_flush_interval", 0.1))
        now = time.monotonic()
        last = getattr(self, "_last_cache_flush_ts", 0.0)
        if last and now - last < min_interval:
            return
        try:
            cache.flush_pending()
            self._last_cache_flush_ts = now
            _CLIENT_LOGGER.debug("Forced cache flush after controller edit (interval %.2fs)", min_interval)
        except Exception as exc:
            _CLIENT_LOGGER.debug("Forced cache flush failed: %s", exc, exc_info=exc)

    def reset_group_cache(self) -> None:
        cache = getattr(self, "_group_cache", None)
        if cache is not None and hasattr(cache, "reset"):
            try:
                cache.reset()
            except Exception as exc:
                _CLIENT_LOGGER.debug("Failed to reset group cache: %s", exc, exc_info=exc)
        for attr in (
            "_last_visible_overlay_bounds_for_target",
            "_last_overlay_bounds_for_target",
            "_last_transform_by_group",
        ):
            current = getattr(self, attr, None)
            if isinstance(current, dict):
                current.clear()
            else:
                setattr(self, attr, {})
        repaint = getattr(self, "_request_repaint", None)
        if callable(repaint):
            try:
                repaint("group_cache_reset", immediate=True)
            except Exception:
                pass

    def _draw_payload_vertex_markers(self, painter: QPainter, points: Sequence[Tuple[int, int]]) -> None:
        if not points:
            return
        painter.save()
        pen = QPen(QColor("#ff3333"))
        pen.setWidth(max(1, self._line_width("vector_marker")))
        painter.setPen(pen)
        span = 3
        for x, y in points:
            painter.drawLine(x - span, y - span, x + span, y + span)
            painter.drawLine(x - span, y + span, x + span, y - span)
        painter.restore()

    def _draw_group_debug_helpers(self, painter: QPainter, mapper: LegacyMapper) -> None:
        if not self._debug_group_state:
            return
        painter.save()
        outline_pen = QPen(QColor("#ffa500"))
        outline_pen.setWidth(self._line_width("group_outline"))
        outline_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(outline_pen)
        text_pen = QPen(QColor("#ffffff"))
        font = QFont(self._font_family)
        self._apply_font_fallbacks(font)
        font.setWeight(QFont.Weight.Normal)
        font.setPointSizeF(max(font.pointSizeF(), 9.0))
        painter.setFont(font)
        for key, debug_state in self._debug_group_state.items():
            if self._debug_group_filter and key != self._debug_group_filter:
                continue
            bounds = self._debug_group_bounds_final.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            rect = self._overlay_bounds_to_rect(bounds, mapper)
            painter.setPen(outline_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            anchor_point = debug_state.anchor_point
            if anchor_point is None:
                continue
            anchor_pixel = self._overlay_point_to_screen(anchor_point, mapper)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawEllipse(QPoint(anchor_pixel[0], anchor_pixel[1]), 5, 5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(text_pen)
            anchor_label_point = debug_state.anchor_logical or anchor_point
            label = f"{debug_state.anchor_token.upper()} ({anchor_label_point[0]:.1f}, {anchor_label_point[1]:.1f})"
            if debug_state.nudged:
                label += " nudged"
            metrics = painter.fontMetrics()
            label_pos = self._anchor_label_position(
                debug_state.anchor_token,
                anchor_pixel,
                metrics.horizontalAdvance(label),
                metrics.ascent(),
                metrics.descent(),
                max(self.width(), 0),
                max(self.height(), 0),
            )
            painter.drawText(label_pos[0], label_pos[1], label)
            painter.setPen(outline_pen)
        painter.restore()

    def _flush_group_log_entries(self, active_keys: Set[Tuple[str, Optional[str]]]) -> None:
        now = time.monotonic()
        for key in list(self._group_log_pending_base.keys()):
            next_allowed = self._group_log_next_allowed.get(key, now)
            is_active = key in active_keys
            should_flush = (not is_active) or now >= next_allowed
            if not should_flush:
                continue
            payload = self._group_log_pending_base.pop(key, None)
            self._group_log_next_allowed.pop(key, None)
            if payload:
                bounds_tuple = payload.pop("bounds_tuple", None)
                if bounds_tuple != self._logged_group_bounds.get(key):
                    self._emit_group_base_log(payload)
                    if bounds_tuple is not None:
                        self._logged_group_bounds[key] = bounds_tuple
            transform_payload = self._group_log_pending_transform.pop(key, None)
            if transform_payload:
                transform_tuple = transform_payload.pop("bounds_tuple", None)
                if transform_tuple != self._logged_group_transforms.get(key):
                    self._emit_group_transform_log(transform_payload)
                    if transform_tuple is not None:
                        self._logged_group_transforms[key] = transform_tuple
            if not is_active:
                self._logged_group_bounds.pop(key, None)
                self._logged_group_transforms.pop(key, None)

    def _emit_group_base_log(self, payload: Mapping[str, Any]) -> None:
        log_parts = [
            "group-base-values",
            f"plugin={payload.get('plugin', '')}",
            f"idPrefix_group={payload.get('suffix', '')}",
            f"base_min_x={float(payload.get('min_x', 0.0)):.1f}",
            f"base_min_y={float(payload.get('min_y', 0.0)):.1f}",
            f"base_width={float(payload.get('width', 0.0)):.1f}",
            f"base_height={float(payload.get('height', 0.0)):.1f}",
            f"base_max_x={float(payload.get('max_x', 0.0)):.1f}",
            f"base_max_y={float(payload.get('max_y', 0.0)):.1f}",
            f"has_transformed={bool(payload.get('has_transformed', False))}",
            f"offset_x={float(payload.get('offset_x', 0.0)):.1f}",
            f"offset_y={float(payload.get('offset_y', 0.0)):.1f}",
        ]
        _CLIENT_LOGGER.debug(" ".join(log_parts))

    def _emit_group_transform_log(self, payload: Mapping[str, Any]) -> None:
        log_parts = [
            "group-transformed-values",
            f"plugin={payload.get('plugin', '')}",
            f"idPrefix_group={payload.get('suffix', '')}",
            f"trans_min_x={float(payload.get('min_x', 0.0)):.1f}",
            f"trans_min_y={float(payload.get('min_y', 0.0)):.1f}",
            f"trans_width={float(payload.get('width', 0.0)):.1f}",
            f"trans_height={float(payload.get('height', 0.0)):.1f}",
            f"trans_max_x={float(payload.get('max_x', 0.0)):.1f}",
            f"trans_max_y={float(payload.get('max_y', 0.0)):.1f}",
            f"anchor={payload.get('anchor', 'nw')}",
            f"justification={payload.get('justification', 'left')}",
            f"nudge_dx={payload.get('nudge_dx', 0)}",
            f"nudge_dy={payload.get('nudge_dy', 0)}",
            f"nudged={payload.get('nudged', False)}",
            f"offset_dx={float(payload.get('offset_dx', 0.0)):.1f}",
            f"offset_dy={float(payload.get('offset_dy', 0.0)):.1f}",
        ]
        _CLIENT_LOGGER.debug(" ".join(log_parts))

    def _overlay_bounds_to_rect(self, bounds: _OverlayBounds, mapper: LegacyMapper) -> QRect:
        scale = mapper.transform.scale
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            scale = 1.0
        width = max(1, int(round((bounds.max_x - bounds.min_x) * scale)))
        height = max(1, int(round((bounds.max_y - bounds.min_y) * scale)))
        x = int(round(bounds.min_x * scale + mapper.offset_x))
        y = int(round(bounds.min_y * scale + mapper.offset_y))
        return QRect(x, y, width, height)

    def _overlay_point_to_screen(self, point: Tuple[float, float], mapper: LegacyMapper) -> Tuple[int, int]:
        scale = mapper.transform.scale
        if not math.isfinite(scale) or math.isclose(scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            scale = 1.0
        x = int(round(point[0] * scale + mapper.offset_x))
        y = int(round(point[1] * scale + mapper.offset_y))
        return x, y

    @staticmethod
    def _overlay_bounds_from_cache_entry(
        entry: Mapping[str, Any],
        *,
        prefer_transformed: bool = True,
    ) -> Tuple[Optional[_OverlayBounds], Optional[str], float, float]:
        if not isinstance(entry, Mapping):
            return None, None, 0.0, 0.0
        base = entry.get("base") if isinstance(entry, Mapping) else None
        transformed = entry.get("transformed") if isinstance(entry, Mapping) else None

        def _f(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        width = height = 0.0
        if prefer_transformed and isinstance(transformed, Mapping):
            min_x = _f(transformed.get("trans_min_x"))
            min_y = _f(transformed.get("trans_min_y"))
            max_x = _f(transformed.get("trans_max_x"))
            max_y = _f(transformed.get("trans_max_y"))
            anchor = transformed.get("anchor") if isinstance(transformed.get("anchor"), str) else None
            width = _f(transformed.get("trans_width"), max_x - min_x)
            height = _f(transformed.get("trans_height"), max_y - min_y)
        else:
            anchor = None
            if not isinstance(base, Mapping):
                return None, None, 0.0, 0.0
            min_x = _f(base.get("base_min_x"))
            min_y = _f(base.get("base_min_y"))
            max_x = _f(base.get("base_max_x"))
            max_y = _f(base.get("base_max_y"))
            width = _f(base.get("base_width"), max_x - min_x)
            height = _f(base.get("base_height"), max_y - min_y)
        bounds = _OverlayBounds(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
        if not bounds.is_valid():
            return None, None, 0.0, 0.0
        return bounds, anchor or "nw", width if width else (max_x - min_x), height if height else (max_y - min_y)

    @staticmethod
    def _build_bounds_with_anchor(width: float, height: float, anchor: str, anchor_x: float, anchor_y: float) -> _OverlayBounds:
        w = max(0.0, float(width))
        h = max(0.0, float(height))
        token = (anchor or "nw").strip().lower()
        if token == "center":
            min_x = anchor_x - w / 2.0
            min_y = anchor_y - h / 2.0
        elif token in {"n", "top"}:
            min_x = anchor_x - w / 2.0
            min_y = anchor_y
        elif token in {"s", "bottom"}:
            min_x = anchor_x - w / 2.0
            min_y = anchor_y - h
        elif token in {"e", "right"}:
            min_x = anchor_x - w
            min_y = anchor_y - h / 2.0
        elif token in {"w", "left"}:
            min_x = anchor_x
            min_y = anchor_y - h / 2.0
        elif token in {"ne"}:
            min_x = anchor_x - w
            min_y = anchor_y
        elif token in {"se"}:
            min_x = anchor_x - w
            min_y = anchor_y - h
        elif token in {"sw"}:
            min_x = anchor_x
            min_y = anchor_y - h
        else:  # nw and default
            min_x = anchor_x
            min_y = anchor_y
        return _OverlayBounds(min_x=min_x, min_y=min_y, max_x=min_x + w, max_y=min_y + h)

    def _paint_controller_target_box(self, painter: QPainter) -> None:
        active_group = getattr(self, "_controller_active_group", None)
        if not active_group:
            return
        mode_state = getattr(self, "controller_mode_state", None)
        if callable(mode_state) and mode_state() != "active":
            return
        transform_map = getattr(self, "_last_transform_by_group", {}) or {}
        mapper = self._compute_legacy_mapper()
        anchor_override = getattr(self, "_controller_active_anchor", None)
        preview_mode = "last"
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is not None:
            try:
                preview_mode = override_manager.group_controller_preview_box_mode(active_group[0], active_group[1])
            except Exception:
                preview_mode = "last"
        if isinstance(preview_mode, str):
            preview_mode = preview_mode.strip().lower()
        if preview_mode not in {"last", "max"}:
            preview_mode = "last"
        bounds_map = getattr(self, "_last_visible_overlay_bounds_for_target", None)
        if not isinstance(bounds_map, dict) or not bounds_map:
            bounds_map = getattr(self, "_last_overlay_bounds_for_target", {}) or {}
        bounds = None
        anchor_token = None
        if preview_mode == "last":
            bounds = self._resolve_bounds_for_active_group(active_group, bounds_map)
            if bounds is None or not bounds.is_valid():
                bounds, anchor_token = self._fallback_bounds_from_cache(
                    active_group,
                    mapper,
                    anchor_override=anchor_override,
                    cache_mode="last",
                )
            if bounds is None or not bounds.is_valid():
                bounds, anchor_token = self._fallback_bounds_from_cache(active_group, mapper, anchor_override=anchor_override)
        else:
            bounds, anchor_token = self._fallback_bounds_from_cache(
                active_group,
                mapper,
                anchor_override=anchor_override,
                cache_mode="max",
            )
            if bounds is None or not bounds.is_valid():
                bounds = self._resolve_bounds_for_active_group(active_group, bounds_map)
            if bounds is None or not bounds.is_valid():
                bounds, anchor_token = self._fallback_bounds_from_cache(
                    active_group,
                    mapper,
                    anchor_override=anchor_override,
                    cache_mode="last",
                )
            if bounds is None or not bounds.is_valid():
                bounds, anchor_token = self._fallback_bounds_from_cache(active_group, mapper, anchor_override=anchor_override)
        if bounds is None or not bounds.is_valid():
            return
        rect = self._overlay_bounds_to_rect(bounds, mapper)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        pen = QPen(QColor(255, 140, 0))
        pen.setWidth(max(1, self._line_width("group_outline")))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRect(rect)

        transform = transform_map.get(active_group)
        if anchor_token is None and transform is not None:
            anchor_token = getattr(transform, "anchor_token", None)
        if anchor_token is None and anchor_override:
            anchor_token = anchor_override
        anchor_point = self._anchor_from_overlay_bounds(bounds, anchor_token) if anchor_token else None
        if anchor_point is None:
            return
        anchor_px = self._overlay_point_to_screen(anchor_point, mapper)
        marker_pen = QPen(QColor(0, 0, 0))
        marker_pen.setWidth(max(1, self._line_width("vector_marker")))
        painter.setPen(marker_pen)
        painter.setBrush(QColor(255, 255, 255))
        radius = 5
        painter.drawEllipse(QPoint(anchor_px[0], anchor_px[1]), radius, radius)

    def _update_last_visible_overlay_bounds_for_target(
        self,
        overlay_bounds_for_draw: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
        commands: Sequence[_LegacyPaintCommand],
    ) -> None:
        if not overlay_bounds_for_draw:
            return
        visible_groups = self._visible_group_keys(commands)
        if not visible_groups:
            return
        cloned_bounds = self._clone_overlay_bounds_map(overlay_bounds_for_draw)
        last_visible = getattr(self, "_last_visible_overlay_bounds_for_target", {}) or {}
        if not isinstance(last_visible, dict):
            last_visible = {}
        for key in visible_groups:
            bounds = cloned_bounds.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            if (bounds.max_x - bounds.min_x) <= 0.0 or (bounds.max_y - bounds.min_y) <= 0.0:
                continue
            last_visible[key] = bounds
        self._last_visible_overlay_bounds_for_target = last_visible

    def _visible_group_keys(self, commands: Sequence[_LegacyPaintCommand]) -> Set[Tuple[str, Optional[str]]]:
        visible_groups: Set[Tuple[str, Optional[str]]] = set()
        for command in commands:
            if command.overlay_bounds is None and command.bounds is None:
                continue
            if self._command_is_visible_for_target(command):
                visible_groups.add(command.group_key.as_tuple())
        return visible_groups

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _command_is_visible_for_target(self, command: _LegacyPaintCommand) -> bool:
        bounds = command.overlay_bounds or command.bounds
        if bounds is not None:
            if (bounds[2] - bounds[0]) <= 0.0 or (bounds[3] - bounds[1]) <= 0.0:
                return False
        if isinstance(command, _MessagePaintCommand):
            text = str(getattr(command, "text", "") or "")
            ttl_raw = command.legacy_item.data.get("__mo_ttl__")
            ttl_val = self._safe_float(ttl_raw, default=-1.0)
            if ttl_val == 0.0 and not text.strip():
                return False
            return True
        if isinstance(command, _RectPaintCommand):
            item = command.legacy_item.data
            width = self._safe_float(item.get("w"), default=0.0)
            height = self._safe_float(item.get("h"), default=0.0)
            if width <= 0.0 or height <= 0.0:
                return False
            return True
        if isinstance(command, _VectorPaintCommand):
            points = command.legacy_item.data.get("points")
            return bool(points)
        return True

    @staticmethod
    def _match_group_key(target: Tuple[str, Optional[str]], candidates: Mapping[Tuple[str, Optional[str]], Any]) -> Optional[Tuple[str, Optional[str]]]:
        if target in candidates:
            return target
        tgt_plugin = (target[0] or "").casefold()
        tgt_suffix = (target[1] or "").casefold() if target[1] is not None else None
        for key in candidates.keys():
            plugin_cf = (key[0] or "").casefold()
            suffix_cf = (key[1] or "").casefold() if key[1] is not None else None
            if plugin_cf == tgt_plugin and suffix_cf == tgt_suffix:
                return key
        return None

    def _resolve_bounds_for_active_group(
        self,
        active_group: Tuple[str, Optional[str]],
        bounds_map: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
    ) -> Optional[_OverlayBounds]:
        matched = self._match_group_key(active_group, bounds_map)
        if matched is None:
            return None
        return bounds_map.get(matched)

    def _fallback_bounds_from_cache(
        self,
        active_group: Tuple[str, Optional[str]],
        mapper: Optional[LegacyMapper] = None,
        anchor_override: Optional[str] = None,
        cache_mode: Optional[str] = None,
        require_transformed: bool = False,
    ) -> Tuple[Optional[_OverlayBounds], Optional[str]]:
        cache = getattr(self, "_group_cache", None)
        if cache is None or not hasattr(cache, "get_group"):
            return None, None
        plugin, suffix = active_group
        entry = None
        try:
            entry = cache.get_group(plugin, suffix)
        except Exception:
            entry = None
        if entry is None:
            # try case-insensitive match across cache
            try:
                groups = getattr(cache, "_state", {}).get("groups", {})
                if isinstance(groups, dict):
                    for p_key, plugin_entry in groups.items():
                        if not isinstance(plugin_entry, dict):
                            continue
                        if (p_key or "").casefold() != (plugin or "").casefold():
                            continue
                        for s_key, group_entry in plugin_entry.items():
                            if (s_key or "").casefold() == (suffix or "").casefold():
                                entry = group_entry
                                break
                        if entry is not None:
                            break
            except Exception:
                entry = None
        if entry is None:
            return None, None
        mode_token = (cache_mode or "transformed").strip().lower()
        token_override = anchor_override
        override_manager = getattr(self, "_override_manager", None)
        base_meta = entry.get("base") if isinstance(entry, Mapping) else {}

        def _safe_float(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        default_offset_x = _safe_float(base_meta.get("offset_x"))
        default_offset_y = _safe_float(base_meta.get("offset_y"))
        offset_dx = default_offset_x
        offset_dy = default_offset_y
        anchor_token_override: Optional[str] = None
        if override_manager is not None:
            try:
                offset_dx, offset_dy = override_manager.group_offsets(plugin, suffix)
            except Exception:
                offset_dx, offset_dy = default_offset_x, default_offset_y
            try:
                _, anchor_token = override_manager.group_preserve_fill_aspect(plugin, suffix)
                anchor_token_override = anchor_token
            except Exception:
                anchor_token_override = None

        base_bounds, base_anchor_token, base_width, base_height = self._overlay_bounds_from_cache_entry(
            entry or {}, prefer_transformed=False
        )
        if base_bounds is None or not base_bounds.is_valid():
            return None, None
        cache_anchor_token = base_anchor_token
        bounds = base_bounds
        width = base_width
        height = base_height

        def _payload_kind(payload: Any) -> str:
            if not isinstance(payload, Mapping):
                return ""
            for key in payload.keys():
                if key.startswith("trans_"):
                    return "transformed"
            for key in payload.keys():
                if key.startswith("base_"):
                    return "base"
            return ""

        cache_payload = None
        payload_kind = ""
        if isinstance(entry, Mapping):
            if mode_token == "last":
                cache_payload = entry.get("last_visible_transformed")
            elif mode_token == "max":
                cache_payload = entry.get("max_transformed")
            else:
                cache_payload = entry.get("transformed")
            payload_kind = _payload_kind(cache_payload)

        transformed = None
        if mode_token in {"last", "max"} and payload_kind == "base":
            cached_bounds, _cached_anchor, cached_width, cached_height = self._overlay_bounds_from_cache_entry(
                {"base": cache_payload}, prefer_transformed=False
            )
            if cached_bounds is not None and cached_bounds.is_valid():
                bounds = cached_bounds
                width = cached_width
                height = cached_height
        else:
            if payload_kind == "transformed":
                transformed = cache_payload
            elif mode_token not in {"last", "max"}:
                transformed = cache_payload if isinstance(cache_payload, Mapping) else None
        if require_transformed and not isinstance(transformed, Mapping):
            return None, None

        def _offsets_match(payload: Mapping[str, Any], target_dx: float, target_dy: float) -> bool:
            tol = 0.5
            cache_dx = _safe_float(payload.get("offset_dx"))
            cache_dy = _safe_float(payload.get("offset_dy"))
            return abs(cache_dx - target_dx) <= tol and abs(cache_dy - target_dy) <= tol

        def _entry_nonce_value(obj: Mapping[str, Any]) -> str:
            raw_nonce = obj.get("edit_nonce")
            if isinstance(raw_nonce, str):
                return raw_nonce.strip()
            base_block = obj.get("base")
            if isinstance(base_block, Mapping):
                embedded = base_block.get("edit_nonce")
                if isinstance(embedded, str):
                    return embedded.strip()
            return ""

        use_cached_transform = False
        target_nonce = self._current_override_nonce()
        entry_nonce = _entry_nonce_value(entry if isinstance(entry, Mapping) else {})
        entry_last_updated = _safe_float(entry.get("last_updated"))
        generation_ts = self._current_override_generation_ts()
        if isinstance(transformed, Mapping):
            nonce_ok = not target_nonce or not entry_nonce or entry_nonce == target_nonce
            timestamp_ok = not generation_ts or entry_last_updated >= generation_ts - 1e-6
            if nonce_ok and timestamp_ok and _offsets_match(transformed, offset_dx, offset_dy):
                cached_bounds, cached_anchor, cached_width, cached_height = self._overlay_bounds_from_cache_entry(
                    {"transformed": transformed}, prefer_transformed=True
                )
                if cached_bounds is not None and cached_bounds.is_valid():
                    bounds = cached_bounds
                    cache_anchor_token = cached_anchor or cache_anchor_token
                    width = cached_width
                    height = cached_height
                    use_cached_transform = True

        if require_transformed and not use_cached_transform:
            return None, None
        if not use_cached_transform and (offset_dx or offset_dy):
            bounds.translate(offset_dx, offset_dy)

        token = token_override or anchor_token_override or cache_anchor_token or "nw"
        source_anchor = cache_anchor_token or "nw"
        if token != source_anchor and width > 0.0 and height > 0.0:
            try:
                anchor_abs = self._anchor_from_overlay_bounds(bounds, source_anchor) or (
                    bounds.min_x,
                    bounds.min_y,
                )
                bounds = self._build_bounds_with_anchor(width, height, token, anchor_abs[0], anchor_abs[1])
            except Exception:
                pass

        if mapper is not None and not use_cached_transform:
            try:
                bounds = self._apply_fill_translation_from_cache(bounds, token, mapper)
            except Exception:
                pass
        return bounds, token

    def _apply_fill_translation_from_cache(
        self,
        bounds: _OverlayBounds,
        anchor_token: Optional[str],
        mapper: LegacyMapper,
    ) -> _OverlayBounds:
        if bounds is None or not bounds.is_valid():
            return bounds
        transform = mapper.transform
        if transform.mode is not ScaleMode.FILL:
            return bounds
        if not (transform.overflow_x or transform.overflow_y):
            return bounds

        def _clamp_unit(value: float) -> float:
            if not math.isfinite(value):
                return 0.0
            if value < 0.0:
                return 0.0
            if value > 1.0:
                return 1.0
            return value

        base_width = BASE_WIDTH if BASE_WIDTH > 0.0 else 1.0
        base_height = BASE_HEIGHT if BASE_HEIGHT > 0.0 else 1.0
        anchor_point = self._anchor_from_overlay_bounds(bounds, anchor_token or "nw")
        if anchor_point is None:
            anchor_point = (bounds.min_x, bounds.min_y)
        group_transform = GroupTransform(
            dx=0.0,
            dy=0.0,
            band_min_x=_clamp_unit(bounds.min_x / base_width),
            band_max_x=_clamp_unit(bounds.max_x / base_width),
            band_min_y=_clamp_unit(bounds.min_y / base_height),
            band_max_y=_clamp_unit(bounds.max_y / base_height),
            band_anchor_x=_clamp_unit(anchor_point[0] / base_width),
            band_anchor_y=_clamp_unit(anchor_point[1] / base_height),
            bounds_min_x=bounds.min_x,
            bounds_min_y=bounds.min_y,
            bounds_max_x=bounds.max_x,
            bounds_max_y=bounds.max_y,
            anchor_token=(anchor_token or "nw").strip().lower(),
            payload_justification="left",
        )
        try:
            viewport_state = self._viewport_state()
        except Exception:
            viewport_state = ViewportState(width=float(self.width()), height=float(self.height()), device_ratio=1.0)
        fill = build_viewport(mapper, viewport_state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        dx, dy = compute_proportional_translation(fill, group_transform, anchor_point)
        if dx or dy:
            bounds.translate(dx, dy)
        return bounds

    @staticmethod
    def _anchor_label_position(
        anchor_token: str,
        anchor_px: Tuple[int, int],
        label_width: int,
        ascent: int,
        descent: int,
        canvas_width: int,
        canvas_height: int,
    ) -> Tuple[int, int]:
        token = (anchor_token or "nw").lower()
        x, y = anchor_px
        if "w" in token or token in {"left"}:
            draw_x = x - label_width - 6
        elif "e" in token or token in {"right"}:
            draw_x = x + 6
        else:
            draw_x = x - label_width // 2
        if "n" in token or token in {"top"}:
            draw_y = y - 6
        elif "s" in token or token in {"bottom"}:
            draw_y = y + ascent + 6
        else:
            draw_y = y + ascent // 2
        margin = 8
        if canvas_width > 0:
            min_x = margin
            max_x = max(margin, canvas_width - margin - label_width)
            draw_x = min(max(draw_x, min_x), max_x)
        if canvas_height > 0:
            top = draw_y - ascent
            bottom = draw_y + descent
            min_top = margin
            max_bottom = max(margin, canvas_height - margin)
            if top < min_top:
                shift = min_top - top
                draw_y += shift
                bottom += shift
            if bottom > max_bottom:
                shift = bottom - max_bottom
                draw_y -= shift
        return draw_x, draw_y

    @staticmethod
    def _clone_overlay_bounds_map(
        overlay_bounds_by_group: Mapping[Tuple[str, Optional[str]], _OverlayBounds],
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        cloned: Dict[Tuple[str, Optional[str]], _OverlayBounds] = {}
        for key, bounds in overlay_bounds_by_group.items():
            clone = _OverlayBounds()
            clone.min_x = bounds.min_x
            clone.max_x = bounds.max_x
            clone.min_y = bounds.min_y
            clone.max_y = bounds.max_y
            cloned[key] = clone
        return cloned

    def _apply_anchor_translations_to_overlay_bounds(
        self,
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        anchor_translations: Mapping[Tuple[str, Optional[str]], Tuple[float, float]],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        if not anchor_translations:
            return overlay_bounds_by_group
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key, (dx_px, dy_px) in anchor_translations.items():
            bounds = overlay_bounds_by_group.get(key)
            if bounds is None or not bounds.is_valid():
                continue
            bounds.translate(dx_px / base_scale, dy_px / base_scale)
        return overlay_bounds_by_group

    def _apply_group_nudges_to_overlay_bounds(
        self,
        overlay_bounds_by_group: Dict[Tuple[str, Optional[str]], _OverlayBounds],
        translations: Mapping[Tuple[str, Optional[str]], Tuple[int, int]],
        base_scale: float,
    ) -> Dict[Tuple[str, Optional[str]], _OverlayBounds]:
        if not translations:
            return overlay_bounds_by_group
        if not math.isfinite(base_scale) or math.isclose(base_scale, 0.0, rel_tol=1e-9, abs_tol=1e-9):
            base_scale = 1.0
        for key, (dx_px, dy_px) in translations.items():
            bounds = overlay_bounds_by_group.get(key)
            if bounds is None:
                continue
            bounds.translate(dx_px / base_scale, dy_px / base_scale)
        return overlay_bounds_by_group


    def _paint_debug_overlay(self, painter: QPainter) -> None:
        self._debug_overlay_view.paint_debug_overlay(
            painter,
            show_debug_overlay=self._show_debug_overlay,
            frame_geometry=self.frameGeometry(),
            width_px=self._current_physical_size()[0],
            height_px=self._current_physical_size()[1],
            mapper=self._compute_legacy_mapper(),
            viewport_state=self._viewport_state(),
            font_family=self._font_family,
            font_scale_diag=self._font_scale_diag,
            font_min_point=self._font_min_point,
            font_max_point=self._font_max_point,
            debug_message_pt=self._debug_message_point_size,
            debug_status_pt=self._debug_status_point_size,
            debug_legacy_pt=self._debug_legacy_point_size,
            aspect_ratio_label_fn=self._aspect_ratio_label,
            last_screen_name=self._last_screen_name,
            describe_screen_fn=self._describe_screen,
            active_screen=self.windowHandle().screen() if self.windowHandle() else None,
            last_follow_state=self._last_follow_state,
            follow_controller=self._follow_controller,
            last_raw_window_log=self._last_raw_window_log,
            title_bar_enabled=self._title_bar_enabled,
            title_bar_height=self._title_bar_height,
            last_title_bar_offset=self._last_title_bar_offset,
            debug_overlay_corner=self._debug_overlay_corner,
            legacy_preset_point_size_fn=self._legacy_preset_point_size,
            env_override_debug=getattr(self, "_env_override_debug", None),
        )

    def _paint_overlay_outline(self, painter: QPainter) -> None:
        self._debug_overlay_view.paint_overlay_outline(
            painter,
            debug_outline=self._debug_config.overlay_outline,
            mapper=self._compute_legacy_mapper(),
            window_width=float(self.width()),
            window_height=float(self.height()),
        )
        self._paint_controller_target_box(painter)

    def _apply_legacy_scale(self) -> None:
        self.update()

    def _apply_window_dimensions(self, *, force: bool = False) -> None:
        return

    def _payload_opacity_percent(self) -> int:
        return coerce_percent(getattr(self, "_payload_opacity", 100), 100)

    def _apply_payload_opacity_color(self, color: QColor) -> QColor:
        return apply_global_payload_opacity(color, self._payload_opacity_percent())

    def _line_width(self, key: str) -> int:
        defaults = getattr(self, "_line_width_defaults", _LINE_WIDTH_DEFAULTS_FALLBACK)
        return util_line_width(self._line_widths, defaults, key)
