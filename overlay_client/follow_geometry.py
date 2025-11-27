"""Follow/geometry calculation helpers for the overlay client."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional, Tuple

_LOGGER_NAME = "EDMC.ModernOverlay.Client"
_CLIENT_LOGGER = logging.getLogger(_LOGGER_NAME)

Geometry = Tuple[int, int, int, int]
NormalisationInfo = Tuple[str, float, float, float]


@dataclass(frozen=True)
class ScreenInfo:
    name: str
    logical_geometry: Geometry
    native_geometry: Geometry
    device_ratio: float


def _convert_native_rect_to_qt(
    rect: Geometry,
    screen_info: Optional[ScreenInfo],
) -> Tuple[Geometry, Optional[NormalisationInfo]]:
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        return rect, None
    if screen_info is None:
        return rect, None

    logical_geometry = screen_info.logical_geometry
    native_geometry = screen_info.native_geometry
    device_ratio = screen_info.device_ratio

    native_width = native_geometry[2]
    native_height = native_geometry[3]

    if device_ratio <= 0.0:
        device_ratio = 1.0

    scale_x = logical_geometry[2] / native_width if native_width else 1.0
    scale_y = logical_geometry[3] / native_height if native_height else 1.0

    if math.isclose(scale_x, 1.0, abs_tol=1e-4):
        scale_x = 1.0 / device_ratio
    if math.isclose(scale_y, 1.0, abs_tol=1e-4):
        scale_y = 1.0 / device_ratio

    native_origin_x = native_geometry[0]
    native_origin_y = native_geometry[1]
    if math.isclose(native_origin_x, logical_geometry[0], abs_tol=1e-4):
        native_origin_x = logical_geometry[0] * device_ratio
    if math.isclose(native_origin_y, logical_geometry[1], abs_tol=1e-4):
        native_origin_y = logical_geometry[1] * device_ratio

    qt_x = logical_geometry[0] + (x - native_origin_x) * scale_x
    qt_y = logical_geometry[1] + (y - native_origin_y) * scale_y
    qt_width = width * scale_x
    qt_height = height * scale_y
    converted = (
        int(round(qt_x)),
        int(round(qt_y)),
        max(1, int(round(qt_width))),
        max(1, int(round(qt_height))),
    )
    normalisation_info: NormalisationInfo = (
        screen_info.name,
        float(scale_x),
        float(scale_y),
        float(device_ratio),
    )
    return converted, normalisation_info


def _apply_title_bar_offset(
    geometry: Geometry,
    *,
    title_bar_enabled: bool,
    title_bar_height: int,
    scale_y: float = 1.0,
    previous_offset: int = 0,
) -> Tuple[Geometry, int]:
    if not title_bar_enabled or title_bar_height <= 0:
        if previous_offset != 0:
            _CLIENT_LOGGER.debug(
                "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                title_bar_enabled,
                title_bar_height,
                0,
                float(scale_y),
            )
        return geometry, 0
    x, y, width, height = geometry
    if height <= 1:
        if previous_offset != 0:
            _CLIENT_LOGGER.debug(
                "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                title_bar_enabled,
                title_bar_height,
                0,
                float(scale_y),
            )
        return geometry, 0
    safe_scale = max(scale_y, 0.0)
    scaled_offset = float(title_bar_height) * safe_scale
    offset = min(int(round(scaled_offset)), max(0, height - 1))
    if offset <= 0:
        if previous_offset != 0:
            _CLIENT_LOGGER.debug(
                "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
                title_bar_enabled,
                title_bar_height,
                0,
                float(scale_y),
            )
        return geometry, 0
    adjusted_height = max(1, height - offset)
    if offset != previous_offset:
        _CLIENT_LOGGER.debug(
            "Title bar offset updated: enabled=%s height=%d offset=%d scale_y=%.3f",
            title_bar_enabled,
            title_bar_height,
            offset,
            float(scale_y),
        )
    return (x, y + offset, width, adjusted_height), offset


def _apply_aspect_guard(
    geometry: Geometry,
    *,
    base_width: int,
    base_height: int,
    original_geometry: Optional[Geometry] = None,
    applied_title_offset: int = 0,
    aspect_guard_skip_logged: bool = False,
) -> Tuple[Geometry, bool]:
    x, y, width, height = geometry
    if width <= 0 or height <= 0:
        return geometry, aspect_guard_skip_logged
    base_ratio = base_width / float(base_height)
    current_ratio = width / float(height)
    original_ratio = None
    if original_geometry is not None:
        _, _, original_width, original_height = original_geometry
        if original_width > 0 and original_height > 0:
            original_ratio = original_width / float(original_height)
    ratio_for_check = original_ratio if original_ratio is not None else current_ratio
    if abs(ratio_for_check - base_ratio) > 0.04:
        if not aspect_guard_skip_logged:
            _CLIENT_LOGGER.debug(
                "Aspect guard skipped: tracker_ratio=%.3f current_ratio=%.3f base_ratio=%.3f offset=%d",
                ratio_for_check,
                current_ratio,
                base_ratio,
                int(applied_title_offset),
            )
            aspect_guard_skip_logged = True
        return geometry, aspect_guard_skip_logged
    aspect_guard_skip_logged = False
    expected_height = int(round(width * base_height / float(base_width)))
    tolerance = max(2, int(round(expected_height * 0.01)))
    if height <= expected_height:
        return geometry, aspect_guard_skip_logged
    height_delta = height - expected_height
    max_delta = max(6, int(round(width * 0.02)))
    if height_delta > max_delta:
        return geometry, aspect_guard_skip_logged
    if height_delta > 0:
        adjusted = (x, y, width, expected_height)
        _CLIENT_LOGGER.debug(
            "Aspect guard trimmed overlay height: width=%d height=%d expected=%d tolerance=%d -> adjusted=%s",
            width,
            height,
            expected_height,
            tolerance,
            adjusted,
        )
        return adjusted, aspect_guard_skip_logged
    return geometry, aspect_guard_skip_logged


def _resolve_wm_override(
    tracker_qt_tuple: Geometry,
    desired_tuple: Geometry,
    override_rect: Optional[Geometry],
    override_tracker: Optional[Geometry],
    override_expired: bool,
) -> Tuple[Geometry, Optional[str]]:
    target_tuple = desired_tuple
    clear_reason = None
    if override_rect is not None:
        if tracker_qt_tuple == override_rect:
            clear_reason = "tracker realigned with WM"
        elif override_tracker is not None and tracker_qt_tuple != override_tracker:
            clear_reason = "tracker changed"
        elif override_expired:
            clear_reason = "override timeout"
        else:
            target_tuple = override_rect
    return target_tuple, clear_reason
