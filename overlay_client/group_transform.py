"""Grouping support for fill-mode transforms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class GroupKey:
    plugin: str
    suffix: Optional[str] = None

    def as_tuple(self) -> Tuple[str, Optional[str]]:
        return self.plugin, self.suffix


@dataclass
class GroupTransform:
    dx: float = 0.0
    dy: float = 0.0
    band_min_x: float = 0.0
    band_max_x: float = 0.0
    band_min_y: float = 0.0
    band_max_y: float = 0.0
    band_anchor_x: float = 0.0
    band_anchor_y: float = 0.0
    bounds_min_x: float = 0.0
    bounds_min_y: float = 0.0
    bounds_max_x: float = 0.0
    bounds_max_y: float = 0.0
    anchor_token: str = "nw"
    payload_justification: str = "left"
    marker_label_position: str = "below"
    background_color: Optional[str] = None
    background_border_color: Optional[str] = None
    background_border_width: int = 0


@dataclass
class GroupBounds:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def update_point(self, x: float, y: float) -> None:
        if x < self.min_x:
            self.min_x = x
        if x > self.max_x:
            self.max_x = x
        if y < self.min_y:
            self.min_y = y
        if y > self.max_y:
            self.max_y = y

    def update_rect(self, left: float, top: float, right: float, bottom: float) -> None:
        self.update_point(left, top)
        self.update_point(right, bottom)

    def is_valid(self) -> bool:
        return self.min_x <= self.max_x and self.min_y <= self.max_y


class GroupTransformCache:
    """Memoises fill-mode offsets for plugin/prefix groups."""

    def __init__(self) -> None:
        self._transforms: Dict[Tuple[str, Optional[str]], GroupTransform] = {}

    def reset(self) -> None:
        self._transforms.clear()

    def get(self, key: GroupKey) -> Optional[GroupTransform]:
        return self._transforms.get(key.as_tuple())

    def set(self, key: GroupKey, transform: GroupTransform) -> None:
        self._transforms[key.as_tuple()] = transform
