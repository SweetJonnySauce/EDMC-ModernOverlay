"""Window/viewport utility helpers for the overlay client (pure calculations)."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Mapping, Optional

from overlay_client.viewport_helper import ScaleMode, compute_viewport_transform  # type: ignore
from overlay_client.viewport_transform import LegacyMapper, ViewportState, scaled_point_size as viewport_scaled_point_size  # type: ignore


def current_physical_size(frame_width: int, frame_height: int, device_ratio: float) -> tuple[float, float]:
    width = max(frame_width, 1)
    height = max(frame_height, 1)
    ratio = device_ratio
    if not (isinstance(ratio, (int, float)) and math.isfinite(ratio) and ratio > 0.0):
        ratio = 1.0
    return width * ratio, height * ratio


def aspect_ratio_label(width: int, height: int) -> Optional[str]:
    if width <= 0 or height <= 0:
        return None
    ratio = width / float(height)
    known_ratios = (
        ("32:9", 32 / 9),
        ("21:9", 21 / 9),
        ("18:9", 18 / 9),
        ("16:10", 16 / 10),
        ("16:9", 16 / 9),
        ("3:2", 3 / 2),
        ("4:3", 4 / 3),
        ("5:4", 5 / 4),
        ("1:1", 1.0),
    )
    for label, target in known_ratios:
        if target <= 0:
            continue
        if abs(ratio - target) / target < 0.03:
            return label
    frac = Fraction(width, height).limit_denominator(100)
    return f"{frac.numerator}:{frac.denominator}"


def compute_legacy_mapper(scale_mode_value: str, width: float, height: float) -> LegacyMapper:
    safe_width = max(float(width), 1.0)
    safe_height = max(float(height), 1.0)
    try:
        mode_enum = ScaleMode((scale_mode_value or "fit").strip().lower())
    except ValueError:
        mode_enum = ScaleMode.FIT
    transform = compute_viewport_transform(safe_width, safe_height, mode_enum)
    base_scale = max(transform.scale, 0.0)
    scale_x = base_scale
    scale_y = base_scale
    offset_x = transform.offset[0]
    offset_y = transform.offset[1]
    return LegacyMapper(
        scale_x=max(scale_x, 0.0),
        scale_y=max(scale_y, 0.0),
        offset_x=offset_x,
        offset_y=offset_y,
        transform=transform,
    )


def viewport_state(width: float, height: float, device_ratio: float) -> ViewportState:
    safe_width = max(float(width), 1.0)
    safe_height = max(float(height), 1.0)
    ratio = device_ratio
    if not (isinstance(ratio, (int, float)) and math.isfinite(ratio) and ratio > 0.0):
        ratio = 1.0
    return ViewportState(width=safe_width, height=safe_height, device_ratio=ratio)


def legacy_preset_point_size(
    preset: str,
    state: ViewportState,
    mapper: LegacyMapper,
    font_scale_diag: float,
    font_min_point: float,
    font_max_point: float,
    legacy_font_step: float,
) -> float:
    normal_point = viewport_scaled_point_size(
        state,
        10.0,
        font_scale_diag,
        font_min_point,
        font_max_point,
        mapper,
        use_physical=True,
    )
    try:
        step = float(legacy_font_step)
    except (TypeError, ValueError):
        step = 2.0
    step = max(0.0, min(step, 10.0))
    offsets = {
        "small": -step,
        "normal": 0.0,
        "large": step,
        "huge": step * 2.0,
    }
    target = normal_point + offsets.get(preset.lower(), 0.0)
    return max(1.0, target)


def line_width(line_widths: Mapping[str, Any], defaults: Mapping[str, int], key: str) -> int:
    default = defaults.get(key, 1)
    value = line_widths.get(key, default)
    try:
        width = int(round(float(value)))
    except (TypeError, ValueError):
        width = default
    return max(0, width)
