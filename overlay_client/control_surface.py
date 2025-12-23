"""External control/API surface mixin for the overlay window."""
from __future__ import annotations

import logging
import math
import sys
import time
from typing import Any, Dict, List, Mapping, Optional

from PyQt6.QtGui import QGuiApplication, QPainter

from overlay_client.group_transform import GroupTransform
from overlay_client.legacy_store import LegacyItem
from overlay_client.override_reload import force_reload_overrides, parse_reload_nonce
from overlay_client.payload_transform import (
    build_payload_transform_context,
    remap_axis_value,
    transform_components,
)
from overlay_client.platform_context import PlatformContext
from overlay_client.viewport_helper import BASE_HEIGHT, BASE_WIDTH, ScaleMode
from overlay_client.viewport_transform import LegacyMapper, build_viewport

_CLIENT_LOGGER = logging.getLogger("EDMC.ModernOverlay.Client")

DEFAULT_WINDOW_BASE_HEIGHT = 960
DEFAULT_WINDOW_BASE_WIDTH = 1280


class ControlSurfaceMixin:
    """Setter/status surface, cycle helpers, repaint scheduling, and config toggles."""

    def set_force_render(self, force: bool) -> None:
        flag = bool(force)
        if flag == self._force_render:
            return
        self._force_render = flag
        if flag:
            self._interaction_controller.handle_force_render_enter()
            self._update_follow_visibility(True)
            if sys.platform.startswith("linux"):
                self._interaction_controller.restore_drag_interactivity(
                    self._drag_enabled,
                    self._drag_active,
                    self.format_scale_debug,
                )
            if self._last_follow_state:
                self._apply_follow_state(self._last_follow_state)
        else:
            if (
                self._follow_enabled
                and self._last_follow_state
                and not self._last_follow_state.is_foreground
            ):
                self._update_follow_visibility(False)

    def set_physical_clamp_enabled(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == getattr(self, "_physical_clamp_enabled", False):
            return
        self._physical_clamp_enabled = flag
        _CLIENT_LOGGER.debug("Physical clamp %s", "enabled" if flag else "disabled")
        if getattr(self, "_follow_controller", None) and self._follow_controller.wm_override is not None:
            self._clear_wm_override(reason="physical_clamp_updated")
        if getattr(self, "_follow_controller", None):
            self._follow_controller.reset_resume_window()
        if getattr(self, "_follow_enabled", False) and getattr(self, "_window_tracker", None) is not None:
            self._refresh_follow_geometry()
        elif getattr(self, "_last_follow_state", None) is not None:
            self._apply_follow_state(self._last_follow_state)
        else:
            self.update()

    def set_physical_clamp_overrides(self, overrides: Optional[Mapping[str, Any]]) -> None:
        raw_overrides = overrides or {}
        normalised: Dict[str, float] = {}
        for name, raw_scale in raw_overrides.items():
            try:
                screen_name = str(name).strip()
            except Exception:
                continue
            if not screen_name:
                continue
            try:
                scale = float(raw_scale)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(scale) or scale <= 0.0:
                continue
            clamped = max(0.5, min(3.0, scale))
            normalised[screen_name] = clamped
        if normalised == getattr(self, "_physical_clamp_overrides", {}):
            return
        self._physical_clamp_overrides = normalised
        _CLIENT_LOGGER.debug("Per-monitor clamp overrides updated: %s", normalised)
        if getattr(self, "_follow_controller", None):
            self._follow_controller.reset_resume_window()
        if getattr(self, "_follow_enabled", False) and getattr(self, "_window_tracker", None) is not None:
            self._refresh_follow_geometry()
        elif getattr(self, "_last_follow_state", None) is not None:
            self._apply_follow_state(self._last_follow_state)
        else:
            self.update()

    def set_debug_overlay(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._show_debug_overlay:
            return
        self._show_debug_overlay = flag
        _CLIENT_LOGGER.debug("Debug overlay %s", "enabled" if flag else "disabled")
        self.update()

    def set_scale_mode(self, mode: str) -> None:
        value = str(mode or "fit").strip().lower()
        if value not in {"fit", "fill"}:
            value = "fit"
        if value == self._scale_mode:
            return
        self._scale_mode = value
        _CLIENT_LOGGER.debug("Overlay scale mode set to %s", value)
        self._publish_metrics()
        self.update()

    def set_payload_nudge(self, enabled: Optional[bool], gutter: Optional[int] = None) -> None:
        changed = False
        if enabled is not None:
            flag = bool(enabled)
            if flag != self._payload_nudge_enabled:
                self._payload_nudge_enabled = flag
                changed = True
        if gutter is not None:
            try:
                numeric = int(gutter)
            except (TypeError, ValueError):
                numeric = self._payload_nudge_gutter
            numeric = max(0, min(numeric, 500))
            if numeric != self._payload_nudge_gutter:
                self._payload_nudge_gutter = numeric
                changed = True
        if changed:
            _CLIENT_LOGGER.debug(
                "Payload nudge updated: enabled=%s gutter=%d",
                self._payload_nudge_enabled,
                self._payload_nudge_gutter,
            )
            self.update()

    def set_payload_log_delay(self, delay_seconds: Optional[float]) -> None:
        try:
            numeric = float(delay_seconds)
        except (TypeError, ValueError):
            numeric = self._payload_log_delay
        numeric = max(0.0, numeric)
        if math.isclose(numeric, self._payload_log_delay_base, rel_tol=1e-9, abs_tol=1e-9):
            return
        self._payload_log_delay_base = numeric
        self._update_payload_log_delay_for_mode(self.controller_mode_state())
        now = time.monotonic()
        for key in self._group_log_pending_base.keys():
            self._group_log_next_allowed[key] = now + self._payload_log_delay
        _CLIENT_LOGGER.debug("Payload log delay updated to %.2fs", self._payload_log_delay)

    def set_cycle_payload_enabled(self, enabled: Optional[bool]) -> None:
        flag = bool(enabled)
        if flag == self._cycle_payload_enabled:
            return
        self._cycle_payload_enabled = flag
        if flag:
            _CLIENT_LOGGER.debug("Payload ID cycling enabled")
            self._sync_cycle_items()
        else:
            _CLIENT_LOGGER.debug("Payload ID cycling disabled")
            self._cycle_payload_ids = []
            self._cycle_current_id = None
        self.update()

    def set_cycle_payload_copy_enabled(self, enabled: Optional[bool]) -> None:
        if enabled is None:
            return
        flag = bool(enabled)
        if flag == self._cycle_copy_clipboard:
            return
        self._cycle_copy_clipboard = flag
        _CLIENT_LOGGER.debug("Copy payload ID on cycle %s", "enabled" if flag else "disabled")

    def cycle_payload_step(self, step: int) -> None:
        if not self._cycle_payload_enabled:
            return
        self._sync_cycle_items()
        if not self._cycle_payload_ids:
            return
        current_id = self._cycle_current_id
        try:
            index = self._cycle_payload_ids.index(current_id) if current_id else 0
        except ValueError:
            index = 0
        next_index = (index + step) % len(self._cycle_payload_ids)
        self._cycle_current_id = self._cycle_payload_ids[next_index]
        _CLIENT_LOGGER.debug(
            "Cycle payload step=%s index=%d/%d id=%s",
            step,
            next_index + 1,
            len(self._cycle_payload_ids),
            self._cycle_current_id,
        )
        if self._cycle_copy_clipboard and self._cycle_current_id:
            try:
                clipboard = QGuiApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(self._cycle_current_id)
            except Exception as exc:
                _CLIENT_LOGGER.warning("Failed to copy payload ID '%s' to clipboard: %s", self._cycle_current_id, exc)
        self.update()

    def handle_cycle_action(self, action: str) -> None:
        if not action:
            return
        action_lower = action.lower()
        if action_lower == "next":
            self.cycle_payload_step(1)
        elif action_lower == "prev":
            self.cycle_payload_step(-1)
        elif action_lower == "reset":
            self._sync_cycle_items()
            self.update()

    def _sync_cycle_items(self) -> None:
        if not self._cycle_payload_enabled:
            return
        ids = [item_id for item_id, _ in self._payload_model.store.items()]
        previous_id = self._cycle_current_id
        self._cycle_payload_ids = ids
        if not ids:
            self._cycle_current_id = None
            return
        if previous_id in ids:
            self._cycle_current_id = previous_id
        else:
            self._cycle_current_id = ids[0]

    def _register_cycle_anchor(self, item_id: str, x: int, y: int) -> None:
        self._cycle_anchor_points[item_id] = (int(x), int(y))

    def _resolve_group_override_pattern(
        self,
        legacy_item: Optional[LegacyItem],
    ) -> Optional[str]:
        if legacy_item is None:
            return None
        override_manager = getattr(self, "_override_manager", None)
        if override_manager is None:
            return None
        plugin_name = legacy_item.plugin
        group_key = override_manager.grouping_key_for(plugin_name, legacy_item.item_id)
        if group_key is None:
            return None
        plugin_label, suffix = group_key
        if not override_manager.group_is_configured(plugin_label, suffix):
            return None
        if isinstance(suffix, str) and suffix:
            return f"group:{suffix}"
        label = plugin_label if isinstance(plugin_label, str) and plugin_label else (legacy_item.plugin or "plugin")
        label = str(label).strip() or "plugin"
        return f"group:{label}"

    def _format_override_lines(self, legacy_item: Optional[LegacyItem]) -> List[str]:
        if legacy_item is None:
            return []
        data = legacy_item.data
        if not isinstance(data, Mapping):
            return []
        transform_meta = data.get("__mo_transform__")
        lines: List[str] = []
        pattern_value: Optional[str] = None
        if isinstance(transform_meta, Mapping):
            for section_name in ("scale", "offset", "pivot"):
                block = transform_meta.get(section_name)
                if not isinstance(block, Mapping):
                    continue
                parts: List[str] = []
                for key, value in block.items():
                    if not isinstance(value, (int, float)):
                        continue
                    if section_name == "scale":
                        if math.isclose(value, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                            continue
                    else:
                        if math.isclose(value, 0.0, rel_tol=1e-6, abs_tol=1e-6):
                            continue
                    parts.append(f"{key}={value:g}")
                if parts:
                    lines.append(f"{section_name}: " + ", ".join(parts))
            pattern = transform_meta.get("pattern")
            if isinstance(pattern, str) and pattern:
                pattern_value = pattern
        group_pattern = self._resolve_group_override_pattern(legacy_item)
        if pattern_value:
            lines.append(f"override pattern: {pattern_value}")
        elif group_pattern:
            lines.append(f"override pattern: {group_pattern}")
        return lines

    def _format_transform_chain(
        self,
        legacy_item: Optional[LegacyItem],
        mapper: LegacyMapper,
        group_transform: Optional[GroupTransform],
    ) -> List[str]:
        if legacy_item is None:
            return []
        data = legacy_item.data
        if not isinstance(data, Mapping):
            return []

        lines: List[str] = []
        transform_meta = data.get("__mo_transform__")
        pivot_x_meta, pivot_y_meta, scale_x_meta, scale_y_meta, offset_x_meta, offset_y_meta = transform_components(transform_meta)

        state = self._viewport_state()
        fill = build_viewport(mapper, state, group_transform, BASE_WIDTH, BASE_HEIGHT)
        transform_context = build_payload_transform_context(fill)
        transform_context = build_payload_transform_context(fill)
        transform_context = build_payload_transform_context(fill)

        if mapper.transform.mode is ScaleMode.FILL:
            lines.append(
                "fill overflow: x={}, y={}".format(
                    "yes" if fill.overflow_x else "no",
                    "yes" if fill.overflow_y else "no",
                )
            )
            band_line = (
                "fill band: x={:.3f}..{:.3f}, y={:.3f}..{:.3f}, anchor=({:.3f},{:.3f})".format(
                    fill.band_min_x,
                    fill.band_max_x,
                    fill.band_min_y,
                    fill.band_max_y,
                    fill.band_anchor_x,
                    fill.band_anchor_y,
                )
            )
            lines.append(band_line)
            if group_transform is not None:
                logical_anchor_x = group_transform.band_anchor_x * BASE_WIDTH
                logical_anchor_y = group_transform.band_anchor_y * BASE_HEIGHT
                anchor_overlay_x = remap_axis_value(logical_anchor_x, transform_context.axis_x)
                anchor_overlay_y = remap_axis_value(logical_anchor_y, transform_context.axis_y)
                if (
                    math.isfinite(logical_anchor_x)
                    and math.isfinite(logical_anchor_y)
                    and math.isfinite(anchor_overlay_x)
                    and math.isfinite(anchor_overlay_y)
                ):
                    lines.append(
                        "group anchor: logical=({:.1f},{:.1f}) overlay=({:.1f},{:.1f}) norm=({:.3f},{:.3f})".format(
                            logical_anchor_x,
                            logical_anchor_y,
                            anchor_overlay_x,
                            anchor_overlay_y,
                            group_transform.band_anchor_x,
                            group_transform.band_anchor_y,
                        )
                    )

        if not math.isclose(scale_x_meta, 1.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(scale_y_meta, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override scale: x={:.3f}, y={:.3f}".format(scale_x_meta, scale_y_meta))
        if not math.isclose(offset_x_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(offset_y_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override offset: x={:.1f}, y={:.1f}".format(offset_x_meta, offset_y_meta))
        if not math.isclose(pivot_x_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6) or not math.isclose(pivot_y_meta, 0.0, rel_tol=1e-6, abs_tol=1e-6):
            lines.append("override pivot: x={:.1f}, y={:.1f}".format(pivot_x_meta, pivot_y_meta))

        return lines

    def _paint_cycle_overlay(self, painter: QPainter) -> None:
        self._cycle_current_id, ids = self._cycle_overlay_view.sync_cycle_items(
            cycle_enabled=self._cycle_payload_enabled,
            payload_model=self._payload_model,
            cycle_current_id=self._cycle_current_id,
        )
        self._cycle_payload_ids = ids
        self._cycle_overlay_view.paint_cycle_overlay(
            painter,
            cycle_enabled=self._cycle_payload_enabled,
            cycle_current_id=self._cycle_current_id,
            compute_legacy_mapper=self._compute_legacy_mapper,
            font_family=self._font_family,
            window_width=float(self.width()),
            window_height=float(self.height()),
            cycle_anchor_points=self._cycle_anchor_points,
            payload_model=self._payload_model,
            grouping_helper=self._grouping_helper,
        )

    def set_font_bounds(self, min_point: Optional[float], max_point: Optional[float]) -> None:
        changed = False
        if min_point is not None:
            try:
                min_value = float(min_point)
            except (TypeError, ValueError):
                min_value = self._font_min_point
            min_value = max(1.0, min(min_value, 48.0))
            if not math.isclose(min_value, self._font_min_point, rel_tol=1e-3):
                self._font_min_point = min_value
                changed = True
        if max_point is not None:
            try:
                max_value = float(max_point)
            except (TypeError, ValueError):
                max_value = self._font_max_point
            max_value = max(self._font_min_point, min(max_value, 72.0))
            if not math.isclose(max_value, self._font_max_point, rel_tol=1e-3):
                self._font_max_point = max_value
                changed = True
        if self._font_max_point < self._font_min_point:
            self._font_max_point = self._font_min_point
            changed = True
        if changed:
            _CLIENT_LOGGER.debug(
                "Font bounds updated: min=%.1f max=%.1f",
                self._font_min_point,
                self._font_max_point,
            )
            self._update_label_fonts()
            self._refresh_legacy_items()
            self.update()
            self._notify_font_bounds_changed()

    def set_legacy_font_step(self, step: Optional[float]) -> None:
        if step is None:
            return
        try:
            step_value = float(step)
        except (TypeError, ValueError):
            step_value = getattr(self, "_legacy_font_step", 2.0)
        step_value = max(0.0, min(step_value, 10.0))
        if math.isclose(step_value, getattr(self, "_legacy_font_step", 2.0), rel_tol=1e-3):
            return
        self._legacy_font_step = step_value
        _CLIENT_LOGGER.debug("Legacy font step updated: %.1f", self._legacy_font_step)
        self._refresh_legacy_items()
        self.update()

    def display_message(self, message: str, *, ttl: Optional[float] = None) -> None:
        self._message_clear_timer.stop()
        self._state["message"] = message
        self.message_label.setText(message)
        if ttl is not None and ttl > 0:
            self._message_clear_timer.start(int(ttl * 1000))

    def _clear_message(self) -> None:
        self._state["message"] = ""
        self.message_label.clear()

    def set_status_text(self, status: str) -> None:
        self._status_presenter.set_status_text(status)
        self._status_raw = self._status_presenter.status_raw
        self._status = self._status_presenter.status

    def _format_status_message(self, status: str) -> str:
        message = status or ""
        if "Connected to 127.0.0.1:" not in message:
            return message
        platform_label = self._platform_controller.platform_label()
        suffix = f" on {platform_label}"
        if message.endswith(suffix):
            return message
        return f"{message}{suffix}"

    def set_show_status(self, show: bool) -> None:
        self._status_presenter.set_show_status(show)
        self._show_status = self._status_presenter.show_status

    def set_status_bottom_margin(self, margin: Optional[int]) -> None:
        self._status_presenter.set_status_bottom_margin(
            margin if margin is not None else self._status_presenter.status_bottom_margin,
            coerce_fn=lambda value, default: self._coerce_non_negative(value, default=default),
        )
        self._status_bottom_margin = self._status_presenter.status_bottom_margin

    def set_debug_overlay_corner(self, corner: Optional[str]) -> None:
        normalised = self._normalise_debug_corner(corner)
        if normalised == self._debug_overlay_corner:
            return
        self._debug_overlay_corner = normalised
        _CLIENT_LOGGER.debug("Debug overlay corner updated to %s", self._debug_overlay_corner)
        if self._show_debug_overlay:
            self.update()

    def _show_overlay_status_message(self, status: str) -> None:
        message = (status or "").strip()
        if not message:
            return
        bottom_margin = max(0, self._status_bottom_margin)
        x_pos = 10
        y_pos = max(0, DEFAULT_WINDOW_BASE_HEIGHT - bottom_margin)
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": message,
            "color": "#ffffff",
            "x": x_pos,
            "y": y_pos,
            "ttl": 0,
            "size": "normal",
            "plugin": "EDMCModernOverlay",
        }
        _CLIENT_LOGGER.debug(
            "Legacy status message dispatched: text='%s' ttl=%s x=%s y=%s",
            message,
            payload["ttl"],
            payload["x"],
            payload["y"],
        )
        self.handle_legacy_payload(payload)

    def _dismiss_overlay_status_message(self) -> None:
        payload = {
            "type": "message",
            "id": "__status_banner__",
            "text": "",
            "ttl": 0,
            "plugin": "EDMCModernOverlay",
        }
        self.handle_legacy_payload(payload)

    def _normalise_debug_corner(self, corner: Optional[str]) -> str:
        if not corner:
            return "NW"
        value = str(corner).strip().upper()
        return value if value in {"NW", "NE", "SW", "SE"} else "NW"

    @staticmethod
    def _coerce_non_negative(value: Optional[int], *, default: int) -> int:
        try:
            numeric = int(value) if value is not None else default
        except (TypeError, ValueError):
            numeric = default
        return max(0, numeric)

    def _invalidate_grid_cache(self) -> None:
        self._grid_pixmap = None
        self._grid_pixmap_params = None

    def _mark_legacy_cache_dirty(self) -> None:
        self._render_pipeline.mark_dirty()

    def _record_repaint_event(self, reason: str) -> None:
        metrics = self._repaint_metrics
        if not metrics.get("enabled"):
            return
        counts = metrics.setdefault("counts", {})
        counts["total"] = counts.get("total", 0) + 1
        counts[reason] = counts.get(reason, 0) + 1
        now = time.monotonic()
        last_ts_raw = metrics.get("last_ts")
        last_ts = float(last_ts_raw) if last_ts_raw is not None else None
        if last_ts is None or now - last_ts > 0.1:
            burst = 1
        else:
            burst = int(metrics.get("burst_current", 0)) + 1
        metrics["burst_current"] = burst
        metrics["last_ts"] = now
        if burst > metrics.get("burst_max", 0):
            metrics["burst_max"] = burst
            _CLIENT_LOGGER.debug(
                "Repaint burst updated (%s): current=%d max=%d interval=%.3fs totals=%s",
                reason,
                burst,
                metrics["burst_max"],
                (now - last_ts) if last_ts is not None else 0.0,
                counts,
            )

    def _request_repaint(self, reason: str, *, immediate: bool = False) -> None:
        self._record_repaint_event(reason)
        debounce_enabled = bool(getattr(self, "_repaint_debounce_enabled", True))
        timer = getattr(self, "_repaint_timer", None)
        effective_immediate = immediate or not debounce_enabled or timer is None
        if self._repaint_debounce_log:
            should_log = effective_immediate or timer is None or not timer.isActive()
            if should_log:
                path_label = "immediate" if effective_immediate else "debounced"
                now = time.monotonic()
                last = self._repaint_log_last or {}
                if (
                    last.get("reason") != reason
                    or last.get("path") != path_label
                    or now - float(last.get("ts", 0.0)) > 1.0
                ):
                    _CLIENT_LOGGER.debug(
                        "Repaint request: reason=%s path=%s debounce_enabled=%s timer_active=%s",
                        reason,
                        path_label,
                        debounce_enabled,
                        timer.isActive() if timer is not None else False,
                    )
                    self._repaint_log_last = {"reason": reason, "path": path_label, "ts": now}
        if effective_immediate:
            if timer is not None and timer.isActive():
                timer.stop()
            self.update()
            return
        if not timer.isActive():
            timer.start()

    def _trigger_debounced_repaint(self) -> None:
        self.update()

    @staticmethod
    def _should_bypass_debounce(payload: Mapping[str, Any]) -> bool:
        """Allow immediate repaint for fast animations/short-lived payloads."""

        if payload.get("animate"):
            return True
        ttl_raw = payload.get("ttl")
        try:
            ttl_value = float(ttl_raw)
        except (TypeError, ValueError):
            return False
        return 0.0 < ttl_value <= 1.0

    def _emit_paint_stats(self) -> None:
        if not self._repaint_debounce_log:
            return
        counts = getattr(self, "_repaint_metrics", {}).get("counts", {})
        stats = getattr(self, "_paint_stats", {})
        paint_count = stats.get("paint_count", 0) if isinstance(stats, dict) else 0
        stats["paint_count"] = 0
        last_state = getattr(self, "_paint_log_state", {}) or {}
        ingest_total = counts.get("ingest", 0) if isinstance(counts, dict) else 0
        purge_total = counts.get("purge", 0) if isinstance(counts, dict) else 0
        total_total = counts.get("total", 0) if isinstance(counts, dict) else 0
        ingest_delta = ingest_total - int(last_state.get("last_ingest", 0))
        purge_delta = purge_total - int(last_state.get("last_purge", 0))
        total_delta = total_total - int(last_state.get("last_total", 0))
        self._paint_log_state = {
            "last_ingest": ingest_total,
            "last_purge": purge_total,
            "last_total": total_total,
        }
        _CLIENT_LOGGER.debug(
            "Repaint stats: paints=%d ingest_delta=%d purge_delta=%d total_delta=%d ingest_total=%s purge_total=%s total=%s",
            paint_count,
            ingest_delta,
            purge_delta,
            total_delta,
            ingest_total,
            purge_total,
            total_total,
        )
        measure_stats = getattr(self, "_measure_stats", {})
        if isinstance(measure_stats, dict) and measure_stats.get("calls"):
            _CLIENT_LOGGER.debug(
                "Text measure stats: calls=%d hits=%d misses=%d resets=%d (window=5s)",
                measure_stats.get("calls", 0),
                measure_stats.get("cache_hit", 0),
                measure_stats.get("cache_miss", 0),
                measure_stats.get("cache_reset", 0),
            )
            measure_stats["calls"] = 0
            measure_stats["cache_hit"] = 0
            measure_stats["cache_miss"] = 0
            measure_stats["cache_reset"] = 0

    def set_background_opacity(self, opacity: float) -> None:
        try:
            value = float(opacity)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        if value != self._background_opacity:
            self._background_opacity = value
            self._invalidate_grid_cache()
            self.update()

    def set_payload_opacity(self, opacity: int) -> None:
        try:
            value = int(opacity)
        except (TypeError, ValueError):
            value = getattr(self, "_payload_opacity", 100)
        value = max(0, min(value, 100))
        if value != getattr(self, "_payload_opacity", 100):
            self._payload_opacity = value
            self.update()

    def set_drag_enabled(self, enabled: bool) -> None:
        enabled_flag = bool(enabled)
        if enabled_flag != self._drag_enabled:
            self._drag_enabled = enabled_flag
            _CLIENT_LOGGER.debug(
                "Drag enabled set to %s (platform=%s); %s",
                self._drag_enabled,
                QGuiApplication.platformName(),
                self.format_scale_debug(),
            )
            self._apply_drag_state()

    def set_legacy_scale_y(self, scale: float, *, auto: bool = False) -> None:
        _CLIENT_LOGGER.debug("Legacy scale control ignored (requested scale_y=%s)", scale)

    def set_legacy_scale_x(self, scale: float, *, auto: bool = False) -> None:
        _CLIENT_LOGGER.debug("Legacy scale control ignored (requested scale_x=%s)", scale)

    def set_gridlines(self, *, enabled: bool, spacing: Optional[int] = None) -> None:
        self._gridlines_enabled = bool(enabled)
        if spacing is not None:
            try:
                numeric = int(spacing)
            except (TypeError, ValueError):
                numeric = self._gridline_spacing
            self._gridline_spacing = max(10, numeric)
        self._invalidate_grid_cache()
        self.update()

    def set_title_bar_compensation(self, enabled: Optional[bool], height: Optional[int]) -> None:
        changed = False
        if enabled is not None:
            flag = bool(enabled)
            if flag != self._title_bar_enabled:
                self._title_bar_enabled = flag
                changed = True
        if height is not None:
            try:
                numeric = int(height)
            except (TypeError, ValueError):
                numeric = self._title_bar_height
            numeric = max(0, numeric)
            if numeric != self._title_bar_height:
                self._title_bar_height = numeric
                changed = True
        if changed:
            if self._follow_controller.wm_override is not None:
                self._clear_wm_override(reason="title_bar_compensation_changed")
            _CLIENT_LOGGER.debug(
                "Title bar compensation updated: enabled=%s height=%d",
                self._title_bar_enabled,
                self._title_bar_height,
            )
            self._follow_controller.reset_resume_window()
            if self._follow_enabled and self._window_tracker is not None:
                self._refresh_follow_geometry()
            elif self._last_follow_state is not None:
                self._apply_follow_state(self._last_follow_state)
            else:
                self.update()

    def set_window_dimensions(self, width: Optional[int], height: Optional[int]) -> None:
        _CLIENT_LOGGER.debug(
            "Ignoring explicit window size request (%s x %s); overlay follows game window geometry.",
            width,
            height,
        )

    def set_log_retention(self, retention: int) -> None:
        try:
            value = int(retention)
        except (TypeError, ValueError):
            value = self._log_retention
        value = max(1, value)
        self._log_retention = value

    def handle_legacy_payload(self, payload: Dict[str, Any]) -> None:
        self._handle_legacy(payload)

    def handle_override_reload(self, payload: Optional[Mapping[str, Any]] = None) -> None:
        nonce = parse_reload_nonce(payload)
        if nonce and nonce == getattr(self, "_last_override_reload_nonce", None):
            _CLIENT_LOGGER.debug("Override reload ignored (duplicate nonce=%s)", nonce)
            return
        self._last_override_reload_nonce = nonce or getattr(self, "_last_override_reload_nonce", None)
        try:
            force_reload_overrides(
                self._override_manager,
                self._grouping_helper,
                self._payload_model,
                _CLIENT_LOGGER.debug,
            )
            self._mark_legacy_cache_dirty()
            self._request_repaint("override_reload", immediate=True)
            _CLIENT_LOGGER.debug("Override reload handled (nonce=%s)", nonce or "none")
            self._controller_override_ts = time.time()
        except Exception as exc:
            _CLIENT_LOGGER.debug("Override reload failed: %s", exc, exc_info=exc)

    def apply_override_payload(self, payload: Optional[Mapping[str, Any]]) -> None:
        if payload is None or not isinstance(payload, Mapping):
            return
        overrides = payload.get("overrides")
        nonce = payload.get("nonce")
        try:
            overrides_map = overrides if isinstance(overrides, Mapping) else None
            nonce_val = str(nonce or "").strip()
        except Exception:
            return
        mgr = getattr(self, "_override_manager", None)
        if mgr is None:
            return
        try:
            if nonce_val:
                mgr._controller_active_nonce = nonce_val  # type: ignore[attr-defined]
                mgr._controller_active_nonce_ts = time.time()  # type: ignore[attr-defined]
            mgr.apply_override_payload(overrides_map, nonce_val)
            self._mark_legacy_cache_dirty()
            self._request_repaint("override_payload", immediate=True)
            _CLIENT_LOGGER.debug("Override payload applied (nonce=%s)", nonce_val or "none")
            self._controller_override_ts = time.time()
        except Exception as exc:
            _CLIENT_LOGGER.debug("Override payload failed: %s", exc, exc_info=exc)

    def set_active_controller_group(self, plugin: Optional[str], label: Optional[str], anchor: Optional[str] = None, edit_nonce: Optional[str] = None) -> None:
        plugin_name = str(plugin or "").strip()
        label_name = str(label or "").strip()
        anchor_token = str(anchor or "").strip().lower() if anchor is not None else None
        nonce_value = str(edit_nonce or "").strip()
        new_value: Optional[tuple[str, str]] = (plugin_name, label_name) if plugin_name and label_name else None
        current_group = getattr(self, "_controller_active_group", None)
        current_anchor = getattr(self, "_controller_active_anchor", None)
        current_nonce = getattr(self, "_controller_active_nonce", "")
        if new_value == current_group and anchor_token == current_anchor and nonce_value == current_nonce:
            return
        self._controller_active_group = new_value
        self._controller_active_anchor = anchor_token
        self._controller_active_nonce = nonce_value
        now = time.time()
        self._controller_active_nonce_ts = now
        if nonce_value:
            self._controller_override_ts = max(self._controller_override_ts, now)
        mgr = getattr(self, "_override_manager", None)
        if mgr is not None:
            try:
                mgr._controller_active_nonce = nonce_value  # type: ignore[attr-defined]
                mgr._controller_active_nonce_ts = now  # type: ignore[attr-defined]
            except Exception:
                pass
        self._request_repaint("controller_target", immediate=True)

    def update_platform_context(self, context_payload: Optional[Dict[str, Any]]) -> None:
        if context_payload is None:
            return
        session = str(context_payload.get("session_type") or self._platform_context.session_type)
        compositor = str(context_payload.get("compositor") or self._platform_context.compositor)
        force_value = context_payload.get("force_xwayland")
        if force_value is None:
            force_flag = self._platform_context.force_xwayland
        else:
            force_flag = bool(force_value)
        flatpak_value = context_payload.get("flatpak")
        if flatpak_value is None:
            flatpak_flag = self._platform_context.flatpak
        else:
            flatpak_flag = bool(flatpak_value)
        flatpak_app_value = context_payload.get("flatpak_app")
        if flatpak_app_value is None:
            flatpak_app_label = self._platform_context.flatpak_app
        else:
            flatpak_app_label = str(flatpak_app_value)
        new_context = PlatformContext(
            session_type=session,
            compositor=compositor,
            force_xwayland=force_flag,
            flatpak=flatpak_flag,
            flatpak_app=flatpak_app_label,
        )
        if new_context == self._platform_context:
            return
        self._platform_context = new_context
        self._platform_controller.update_context(new_context)
        self._platform_controller.prepare_window(self.windowHandle())
        self._platform_controller.apply_click_through(True)
        self._interaction_controller.reapply_current(reason="platform_context_update")
        self._restore_drag_interactivity()
        _CLIENT_LOGGER.debug(
            "Platform context updated: session=%s compositor=%s force_xwayland=%s flatpak=%s",
            new_context.session_type or "unknown",
            new_context.compositor or "unknown",
            new_context.force_xwayland,
            new_context.flatpak,
        )
        self._status = self._format_status_message(self._status_raw)
        if self._show_status and self._status:
            self._show_overlay_status_message(self._status)
