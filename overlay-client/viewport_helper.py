"""Helpers for computing overlay scaling transforms."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

BASE_WIDTH = 1280.0
BASE_HEIGHT = 720.0
_EPSILON = 1e-9


class ScaleMode(str, Enum):
    FIT = "fit"
    FILL = "fill"


@dataclass(frozen=True)
class ViewportTransform:
    """Resolved scale/offset details for rendering the legacy canvas."""

    mode: ScaleMode
    scale: float
    offset: Tuple[float, float]
    scaled_size: Tuple[float, float]
    overflow_x: bool
    overflow_y: bool

    @property
    def scale_x(self) -> float:
        return self.scale

    @property
    def scale_y(self) -> float:
        return self.scale


def _normalise_dimensions(width: float, height: float) -> Tuple[float, float]:
    if width <= 0 or height <= 0:
        raise ValueError("window dimensions must be positive")
    return float(width), float(height)


def compute_viewport_transform(width: float, height: float, mode: ScaleMode) -> ViewportTransform:
    """Return the viewport mapping for the given window size.

    In FIT mode the legacy canvas is uniformly scaled to fit entirely within
    the window and centred (letter-/pillarboxing as needed).

    In FILL mode the canvas is uniformly scaled so *at least* one dimension
    matches the window. The scaled canvas may extend beyond the window in the
    opposite axis; overflow flags indicate which edges need proportional
    remapping downstream.
    """

    window_w, window_h = _normalise_dimensions(width, height)

    if mode is ScaleMode.FIT:
        scale = min(window_w / BASE_WIDTH, window_h / BASE_HEIGHT)
        scale = max(scale, 0.0)
        scaled_w = BASE_WIDTH * scale
        scaled_h = BASE_HEIGHT * scale
        offset_x = (window_w - scaled_w) / 2.0
        offset_y = (window_h - scaled_h) / 2.0
        overflow_x = scaled_w - window_w > _EPSILON
        overflow_y = scaled_h - window_h > _EPSILON
    elif mode is ScaleMode.FILL:
        scale = max(window_w / BASE_WIDTH, window_h / BASE_HEIGHT)
        scale = max(scale, 0.0)
        scaled_w = BASE_WIDTH * scale
        scaled_h = BASE_HEIGHT * scale
        offset_x = 0.0
        offset_y = 0.0
        overflow_x = scaled_w - window_w > _EPSILON
        overflow_y = scaled_h - window_h > _EPSILON
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported scale mode: {mode}")

    return ViewportTransform(
        mode=mode,
        scale=scale,
        offset=(offset_x, offset_y),
        scaled_size=(scaled_w, scaled_h),
        overflow_x=overflow_x,
        overflow_y=overflow_y,
    )
