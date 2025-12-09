from __future__ import annotations

import math
import time
from typing import Callable, List, Mapping, Optional, Tuple

from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from overlay_client.group_transform import GroupTransform  # type: ignore
from overlay_client.viewport_transform import LegacyMapper, ViewportState, legacy_scale_components  # type: ignore


class DebugOverlayView:
    """Renders the debug diagnostics panel and overlay outline."""

    def __init__(
        self,
        apply_font_fallbacks: Callable[[QFont], None],
        line_width: Callable[[str], int],
    ) -> None:
        self._apply_font_fallbacks = apply_font_fallbacks
        self._line_width = line_width

    def paint_debug_overlay(
        self,
        painter: QPainter,
        *,
        show_debug_overlay: bool,
        frame_geometry: QRect,
        width_px: float,
        height_px: float,
        mapper: LegacyMapper,
        viewport_state: ViewportState,
        font_family: str,
        font_scale_diag: float,
        font_min_point: float,
        font_max_point: float,
        debug_message_pt: float,
        debug_status_pt: float,
        debug_legacy_pt: float,
        aspect_ratio_label_fn: Callable[[int, int], Optional[str]],
        last_screen_name: Optional[str],
        describe_screen_fn: Callable[[object], str],
        active_screen,
        last_follow_state,
        follow_controller,
        last_raw_window_log: Optional[Tuple[int, int, int, int]],
        title_bar_enabled: bool,
        title_bar_height: int,
        last_title_bar_offset: int,
        debug_overlay_corner: str,
        legacy_preset_point_size_fn: Callable[[str, ViewportState, LegacyMapper], float],
        env_override_debug: Optional[Mapping[str, object]] = None,
    ) -> None:
        if not show_debug_overlay:
            return

        state = viewport_state
        scale_x, scale_y = legacy_scale_components(mapper, state)
        diagonal_scale = font_scale_diag
        if diagonal_scale <= 0.0:
            diagonal_scale = math.sqrt((scale_x * scale_x + scale_y * scale_y) / 2.0)
        size_labels = [("S", "small"), ("N", "normal"), ("L", "large"), ("H", "huge")]
        legacy_sizes_str = " ".join(
            "{}={:.1f}".format(label, legacy_preset_point_size_fn(name, state, mapper))
            for label, name in size_labels
        )
        monitor_desc = last_screen_name or describe_screen_fn(active_screen)
        active_ratio = None
        if active_screen is not None:
            try:
                geo = active_screen.geometry()
                active_ratio = aspect_ratio_label_fn(geo.width(), geo.height())
            except Exception:
                active_ratio = None
        active_line = f"  active={monitor_desc or 'unknown'}"
        if active_ratio:
            active_line += f" ({active_ratio})"
        monitor_lines = ["Monitor:", active_line]
        if last_follow_state is not None:
            tracker_ratio = aspect_ratio_label_fn(
                max(1, int(last_follow_state.width)),
                max(1, int(last_follow_state.height)),
            )
            tracker_line = "  tracker=({},{}) {}x{}".format(
                last_follow_state.x,
                last_follow_state.y,
                last_follow_state.width,
                last_follow_state.height,
            )
            if tracker_ratio:
                tracker_line += f" ({tracker_ratio})"
            monitor_lines.append(tracker_line)
        override_rect = follow_controller.wm_override
        override_class = follow_controller.wm_override_classification
        if override_rect is not None and override_class is not None:
            rect = override_rect
            monitor_lines.append(
                "  wm_rect=({},{}) {}x{} [{}]".format(
                    rect[0],
                    rect[1],
                    rect[2],
                    rect[3],
                    override_class,
                )
            )

        widget_ratio = aspect_ratio_label_fn(frame_geometry.width(), frame_geometry.height())
        frame_ratio = aspect_ratio_label_fn(frame_geometry.width(), frame_geometry.height())
        phys_ratio = aspect_ratio_label_fn(int(round(width_px)), int(round(height_px)))
        overlay_lines = ["Overlay:"]
        widget_line = "  widget={}x{}".format(frame_geometry.width(), frame_geometry.height())
        if widget_ratio:
            widget_line += f" ({widget_ratio})"
        overlay_lines.append(widget_line)
        frame_line = "  frame={}x{}".format(frame_geometry.width(), frame_geometry.height())
        if frame_ratio:
            frame_line += f" ({frame_ratio})"
        overlay_lines.append(frame_line)
        phys_line = "  phys={}x{}".format(int(round(width_px)), int(round(height_px)))
        if phys_ratio:
            phys_line += f" ({phys_ratio})"
        overlay_lines.append(phys_line)
        if last_raw_window_log is not None:
            raw_x, raw_y, raw_w, raw_h = last_raw_window_log
            raw_ratio = aspect_ratio_label_fn(raw_w, raw_h)
            raw_line = "  raw=({},{}) {}x{}".format(raw_x, raw_y, raw_w, raw_h)
            if raw_ratio:
                raw_line += f" ({raw_ratio})"
            overlay_lines.append(raw_line)

        transform = mapper.transform
        scaling_lines = [
            "Scaling:",
            "  mode={} base_scale={:.4f}".format(transform.mode.value, transform.scale),
            "  scaled_canvas={:.1f}x{:.1f} offset=({:.1f},{:.1f})".format(
                transform.scaled_size[0],
                transform.scaled_size[1],
                mapper.offset_x,
                mapper.offset_y,
            ),
            "  overflow_x={} overflow_y={}".format(
                "yes" if transform.overflow_x else "no",
                "yes" if transform.overflow_y else "no",
            ),
        ]

        font_lines = [
            "Fonts:",
            "  scale_x={:.2f} scale_y={:.2f} diag={:.2f}".format(scale_x, scale_y, diagonal_scale),
            "  ui_scale={:.2f}".format(font_scale_diag),
            "  bounds={:.1f}-{:.1f}".format(font_min_point, font_max_point),
            "  message={:.1f} status={:.1f} legacy={:.1f}".format(
                debug_message_pt,
                debug_status_pt,
                debug_legacy_pt,
            ),
            "  legacy presets: {}".format(legacy_sizes_str),
        ]

        settings_lines = [
            "Settings:",
            "  title_bar_compensation={}".format("on" if title_bar_enabled else "off"),
            "  title_bar_height={}".format(title_bar_height),
            "  applied_offset={}".format(last_title_bar_offset),
        ]

        env_override_lines = self._format_env_override_lines(env_override_debug)

        info_lines = (
            monitor_lines
            + [""]
            + overlay_lines
            + [""]
            + scaling_lines
            + [""]
            + font_lines
            + [""]
            + settings_lines
        )
        if env_override_lines:
            info_lines += [""] + env_override_lines
        painter.save()
        debug_font = QFont(font_family or "", 10)
        self._apply_font_fallbacks(debug_font)
        painter.setFont(debug_font)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        text_width = max(metrics.horizontalAdvance(line) for line in info_lines)
        padding = 6
        panel_width = text_width + padding * 2
        panel_height = line_height * len(info_lines) + padding * 2
        rect = QRect(0, 0, panel_width, panel_height)
        margin = 10
        corner = debug_overlay_corner
        if corner in {"NW", "SW"}:
            left = margin
        else:
            left = max(margin, frame_geometry.width() - panel_width - margin)
        if corner in {"NW", "NE"}:
            top = margin
        else:
            top = max(margin, frame_geometry.height() - panel_height - margin)
        rect.moveTo(left, top)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(220, 220, 220))
        for index, line in enumerate(info_lines):
            painter.drawText(
                rect.left() + padding,
                rect.top() + padding + metrics.ascent() + index * line_height,
                line,
            )
        painter.restore()

    @staticmethod
    def _format_env_override_lines(env_override_debug: Optional[Mapping[str, object]]) -> List[str]:
        if not env_override_debug:
            return []
        applied = set()
        skipped_env = set()
        skipped_existing = set()
        values_block: Mapping[str, object] = {}
        try:
            applied = set(env_override_debug.get("applied", []) or [])
            skipped_env = set(env_override_debug.get("skipped_env", []) or [])
            skipped_existing = set(env_override_debug.get("skipped_existing", []) or [])
            maybe_values = env_override_debug.get("values")
            if isinstance(maybe_values, Mapping):
                values_block = maybe_values
        except Exception:
            applied = set()
            skipped_env = set()
            skipped_existing = set()
            values_block = {}

        keys_of_interest = (
            "QT_AUTO_SCREEN_SCALE_FACTOR",
            "QT_ENABLE_HIGHDPI_SCALING",
            "QT_SCALE_FACTOR",
            "EDMC_OVERLAY_FORCE_XWAYLAND",
        )
        lines: List[str] = []
        for key in keys_of_interest:
            raw_value = values_block.get(key) if isinstance(values_block, Mapping) else None
            text = ""
            try:
                text = str(raw_value) if raw_value is not None else ""
            except Exception:
                text = ""
            value = "<unset>" if raw_value is None else (text if text else "<empty>")
            marker = ""
            if key in applied:
                marker = " [applied]"
            elif key in skipped_env:
                marker = " [preset]"
            elif key in skipped_existing:
                marker = " [existing]"
            lines.append(f"  {key}={value}{marker}")
        if not lines:
            return []
        return ["Env overrides:"] + lines

    def paint_overlay_outline(
        self,
        painter: QPainter,
        *,
        debug_outline: bool,
        mapper: LegacyMapper,
        window_width: float,
        window_height: float,
    ) -> None:
        if not debug_outline:
            return
        transform = mapper.transform
        offset_x, offset_y = transform.offset
        scaled_w, scaled_h = transform.scaled_size
        window_w = window_width
        window_h = window_height
        left = offset_x
        top = offset_y
        right = offset_x + scaled_w
        bottom = offset_y + scaled_h
        overflow_left = left < 0.0
        overflow_right = right > window_w
        overflow_top = top < 0.0
        overflow_bottom = bottom > window_h
        vis_left = max(left, 0.0)
        vis_right = min(right, window_w)
        vis_top = max(top, 0.0)
        vis_bottom = min(bottom, window_h)

        painter.save()
        pen = QPen(QColor(255, 136, 0))
        pen.setWidth(self._line_width("viewport_indicator"))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)

        def draw_vertical_line(x_pos: float) -> None:
            if vis_top >= vis_bottom:
                return
            x = int(round(x_pos))
            painter.drawLine(x, int(round(vis_top)), x, int(round(vis_bottom)))

        def draw_horizontal_line(y_pos: float) -> None:
            if vis_left >= vis_right:
                return
            y = int(round(y_pos))
            painter.drawLine(int(round(vis_left)), y, int(round(vis_right)), y)

        arrow_length = 18.0
        arrow_span_min = 60.0
        arrow_count = 3

        arrow_tip_margin = 4.0

        def draw_vertical_arrows(edge_x: float, direction: int) -> None:
            span_start = max(vis_top, 0.0)
            span_end = min(vis_bottom, window_h)
            if span_end <= span_start:
                span_start = 0.0
                span_end = window_h
            span = max(span_end - span_start, arrow_span_min)
            step = span / (arrow_count + 1)
            if direction > 0:
                tip_x = min(edge_x - arrow_tip_margin, window_w - arrow_tip_margin)
                base_x = tip_x - arrow_length
            else:
                tip_x = max(edge_x + arrow_tip_margin, arrow_tip_margin)
                base_x = tip_x + arrow_length
            for i in range(1, arrow_count + 1):
                y = span_start + step * i
                painter.drawLine(int(round(base_x)), int(round(y)), int(round(tip_x)), int(round(y)))
                painter.drawLine(
                    int(round(tip_x)),
                    int(round(y)),
                    int(round(tip_x - direction * arrow_length * 0.45)),
                    int(round(y - arrow_length * 0.4)),
                )
                painter.drawLine(
                    int(round(tip_x)),
                    int(round(y)),
                    int(round(tip_x - direction * arrow_length * 0.45)),
                    int(round(y + arrow_length * 0.4)),
                )

        def draw_horizontal_arrows(edge_y: float, direction: int) -> None:
            span_start = max(vis_left, 0.0)
            span_end = min(vis_right, window_w)
            if span_end <= span_start:
                span_start = 0.0
                span_end = window_w
            span = max(span_end - span_start, arrow_span_min)
            step = span / (arrow_count + 1)
            for i in range(1, arrow_count + 1):
                x = span_start + step * i
                if direction > 0:
                    tip_y = min(edge_y - arrow_tip_margin, window_h - arrow_tip_margin)
                    base_y = tip_y - arrow_length
                else:
                    tip_y = max(edge_y + arrow_tip_margin, arrow_tip_margin)
                    base_y = tip_y + arrow_length
                painter.drawLine(int(round(x)), int(round(base_y)), int(round(x)), int(round(tip_y)))
                painter.drawLine(
                    int(round(x)),
                    int(round(tip_y)),
                    int(round(x - arrow_length * 0.35)),
                    int(round(tip_y - direction * arrow_length * 0.4)),
                )
                painter.drawLine(
                    int(round(x)),
                    int(round(tip_y)),
                    int(round(x + arrow_length * 0.35)),
                    int(round(tip_y - direction * arrow_length * 0.4)),
                )

        if not overflow_left:
            draw_vertical_line(vis_left)
        else:
            draw_vertical_arrows(max(vis_left, 0.0), direction=-1)

        if not overflow_right:
            draw_vertical_line(vis_right)
        else:
            draw_vertical_arrows(min(vis_right, window_w), direction=1)

        if not overflow_top:
            draw_horizontal_line(vis_top)
        else:
            draw_horizontal_arrows(max(vis_top, 0.0), direction=-1)

        if not overflow_bottom:
            draw_horizontal_line(vis_bottom)
        else:
            draw_horizontal_arrows(min(vis_bottom, window_h), direction=1)

        painter.restore()


class CycleOverlayView:
    """Renders the payload cycle overlay and keeps cycle items in sync."""

    def sync_cycle_items(
        self,
        *,
        cycle_enabled: bool,
        payload_model,
        cycle_current_id: Optional[str],
    ) -> Tuple[Optional[str], List[str]]:
        if not cycle_enabled:
            return cycle_current_id, []
        ids = [item_id for item_id, _ in payload_model.store.items()]
        new_current = cycle_current_id
        if new_current and new_current not in ids:
            new_current = None
        return new_current, ids

    def paint_cycle_overlay(
        self,
        painter: QPainter,
        *,
        cycle_enabled: bool,
        cycle_current_id: Optional[str],
        compute_legacy_mapper: Callable[[], LegacyMapper],
        font_family: str,
        window_width: float,
        window_height: float,
        cycle_anchor_points: Mapping[str, Tuple[float, float]],
        payload_model,
        grouping_helper,
    ) -> None:
        if not cycle_enabled:
            return
        current_id = cycle_current_id
        if not current_id:
            return
        mapper = compute_legacy_mapper()
        anchor = cycle_anchor_points.get(current_id)
        plugin_name = "unknown"
        current_item = payload_model.get(current_id)
        if current_item is not None:
            name = current_item.plugin
            if isinstance(name, str) and name:
                plugin_name = name
        group_transform: Optional[GroupTransform] = None
        if current_item is not None:
            group_transform = grouping_helper.transform_for_item(current_item.item_id, current_item.plugin)
        id_line = f"Payload id: {current_id}"
        plugin_line = f"Plugin name: {plugin_name}"
        center_line = f"Center: {anchor[0]}, {anchor[1]}" if anchor is not None else "Center: -, -"
        data = current_item.data if current_item is not None else {}
        info_lines: List[str] = []
        if current_item is not None:
            if current_item.expiry is None:
                info_lines.append("ttl: ∞")
            else:
                monotonic_now = getattr(payload_model, "monotonic_now", None)
                now = monotonic_now() if callable(monotonic_now) else time.monotonic()
                remaining = max(0.0, current_item.expiry - now)
                info_lines.append(f"ttl: {remaining:.1f}s")
        updated_iso = data.get("__mo_updated__") if isinstance(data, Mapping) else None
        if isinstance(updated_iso, str):
            try:
                info_lines.append(f"last seen: {payload_model.describe_iso(updated_iso)}")
            except Exception:
                info_lines.append(f"last seen: {updated_iso}")
        kind_label = current_item.kind if current_item is not None else None
        if kind_label == "message":
            size_label = str(data.get("size", "unknown"))
            info_lines.append(f"type: message (size={size_label})")
        elif kind_label == "rect":
            w_val = data.get("w")
            h_val = data.get("h")
            if isinstance(w_val, (int, float)) and isinstance(h_val, (int, float)):
                info_lines.append(f"type: rect (w={w_val}, h={h_val})")
            else:
                info_lines.append("type: rect")
        elif kind_label == "vector":
            points_data = data.get("points")
            if isinstance(points_data, list):
                info_lines.append(f"type: vector (points={len(points_data)})")
            else:
                info_lines.append("type: vector")
        elif kind_label:
            info_lines.append(f"type: {kind_label}")

        def _fmt_number(value: any) -> Optional[str]:
            if isinstance(value, (int, float)):
                return f"{value:g}"
            return None

        transform_meta = data.get("__mo_transform__") if isinstance(data, Mapping) else None
        if isinstance(transform_meta, Mapping):
            original = transform_meta.get("original")
            if isinstance(original, Mapping):
                raw_x_fmt = _fmt_number(original.get("x"))
                raw_y_fmt = _fmt_number(original.get("y"))
                trans_x_fmt = _fmt_number(data.get("x"))
                trans_y_fmt = _fmt_number(data.get("y"))
                if raw_x_fmt is not None and raw_y_fmt is not None and trans_x_fmt is not None and trans_y_fmt is not None:
                    info_lines.append(f"coords: ({raw_x_fmt},{raw_y_fmt}) → ({trans_x_fmt},{trans_y_fmt})")
                raw_w_fmt = _fmt_number(original.get("w"))
                raw_h_fmt = _fmt_number(original.get("h"))
                trans_w_fmt = _fmt_number(data.get("w"))
                trans_h_fmt = _fmt_number(data.get("h"))
                if (
                    raw_w_fmt is not None
                    and raw_h_fmt is not None
                    and trans_w_fmt is not None
                    and trans_h_fmt is not None
                ):
                    info_lines.append(f"size: {raw_w_fmt}x{raw_h_fmt} → {trans_w_fmt}x{trans_h_fmt}")
            anchor_token = transform_meta.get("anchor_token")
            if isinstance(anchor_token, str) and anchor_token:
                info_lines.append(f"anchor_token: {anchor_token}")
            transform_ref = transform_meta.get("transform_reference")
            if isinstance(transform_ref, Mapping):
                min_x_fmt = _fmt_number(transform_ref.get("min_x"))
                min_y_fmt = _fmt_number(transform_ref.get("min_y"))
                max_x_fmt = _fmt_number(transform_ref.get("max_x"))
                max_y_fmt = _fmt_number(transform_ref.get("max_y"))
                if (
                    min_x_fmt is not None
                    and min_y_fmt is not None
                    and max_x_fmt is not None
                    and max_y_fmt is not None
                ):
                    info_lines.append(f"transform reference: ({min_x_fmt},{min_y_fmt})-({max_x_fmt},{max_y_fmt})")
            transform_bounds = transform_meta.get("transform_bounds")
            if isinstance(transform_bounds, Mapping):
                min_x_fmt = _fmt_number(transform_bounds.get("min_x"))
                min_y_fmt = _fmt_number(transform_bounds.get("min_y"))
                max_x_fmt = _fmt_number(transform_bounds.get("max_x"))
                max_y_fmt = _fmt_number(transform_bounds.get("max_y"))
                if (
                    min_x_fmt is not None
                    and min_y_fmt is not None
                    and max_x_fmt is not None
                    and max_y_fmt is not None
                ):
                    info_lines.append(f"transform bounds: ({min_x_fmt},{min_y_fmt})-({max_x_fmt},{max_y_fmt})")

        if group_transform is not None:
            def _fmt_transform_value(value) -> Optional[str]:
                if isinstance(value, (int, float)):
                    return f"{value:g}"
                return None
            anchor_x_fmt = _fmt_transform_value(getattr(group_transform, "band_anchor_x", None))
            anchor_y_fmt = _fmt_transform_value(getattr(group_transform, "band_anchor_y", None))
            band_min_x_fmt = _fmt_transform_value(getattr(group_transform, "band_min_x", None))
            band_max_x_fmt = _fmt_transform_value(getattr(group_transform, "band_max_x", None))
            band_min_y_fmt = _fmt_transform_value(getattr(group_transform, "band_min_y", None))
            band_max_y_fmt = _fmt_transform_value(getattr(group_transform, "band_max_y", None))
            if anchor_x_fmt is not None and anchor_y_fmt is not None:
                info_lines.append(f"group anchor: {anchor_x_fmt},{anchor_y_fmt}")
            if (
                band_min_x_fmt is not None
                and band_max_x_fmt is not None
                and band_min_y_fmt is not None
                and band_max_y_fmt is not None
            ):
                info_lines.append(f"group bounds: ({band_min_x_fmt},{band_min_y_fmt})-({band_max_x_fmt},{band_max_y_fmt})")

        painter.save()
        highlight_color = QColor(255, 136, 0)
        painter.setPen(highlight_color)
        safe_family = font_family or getattr(mapper.transform, "font_family", "") or ""
        font = QFont(safe_family, 12)
        painter.setFont(font)
        display_lines = [id_line, plugin_line, center_line] + info_lines
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        text_width = max(metrics.horizontalAdvance(line) for line in display_lines) if display_lines else 0
        padding = 10
        panel_width = text_width + padding * 2
        panel_height = line_height * len(display_lines) + padding * 2
        visible_w = max(float(window_width), 1.0)
        visible_h = max(float(window_height), 1.0)
        transform = mapper.transform
        if transform.overflow_x:
            center_x = mapper.offset_x + visible_w / 2.0
        else:
            center_x = mapper.offset_x + max(transform.scaled_size[0], 1.0) / 2.0
        if transform.overflow_y:
            center_y = mapper.offset_y + visible_h / 2.0
        else:
            center_y = mapper.offset_y + max(transform.scaled_size[1], 1.0) / 2.0
        rect_left = int(round(center_x - panel_width / 2.0))
        rect_top = int(round(center_y - panel_height / 2.0))
        rect_left = max(0, min(rect_left, int(visible_w - panel_width)))
        rect_top = max(0, min(rect_top, int(visible_h - panel_height)))
        rect = QRect(rect_left, rect_top, int(round(panel_width)), int(round(panel_height)))

        painter.setBrush(QColor(0, 0, 0, 180))
        pen = QPen(highlight_color)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 6, 6)
        for index, line in enumerate(display_lines):
            painter.drawText(
                rect.left() + padding,
                rect.top() + padding + metrics.ascent() + index * line_height,
                line,
            )

        if anchor is not None and isinstance(anchor, tuple) and len(anchor) == 2:
            # Anchors are already stored in screen-space pixels.
            anchor_px = (int(round(anchor[0])), int(round(anchor[1])))
            start_x = min(max(anchor_px[0], rect.left()), rect.right())
            start_y = min(max(anchor_px[1], rect.top()), rect.bottom())
            painter.drawLine(QPoint(start_x, start_y), QPoint(anchor_px[0], anchor_px[1]))
            painter.drawEllipse(QPoint(anchor_px[0], anchor_px[1]), 4, 4)
        painter.restore()
