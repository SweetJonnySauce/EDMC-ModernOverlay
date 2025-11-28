"""Controller for follow/window orchestration (geometry and visibility decisions).

This module is intended to stay free of Qt types; callers inject thin adapters for
Qt interactions (geometry getters/setters, screen descriptors, logging).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

Geometry = Tuple[int, int, int, int]
NormalisationInfo = Optional[Tuple[str, float, float, float]]


@dataclass
class FollowContext:
    title_bar_enabled: bool
    title_bar_height: int
    base_width: int
    base_height: int


class WindowController:
    """Pure orchestrator for follow/window geometry and visibility decisions."""

    def __init__(
        self,
        *,
        log_fn: Callable[[str], None],
    ) -> None:
        self._log = log_fn
        self._last_title_bar_offset = 0
        self._aspect_guard_skip_logged = False
        self._last_raw_window_log: Optional[Geometry] = None
        self._last_normalised_tracker: Optional[Tuple[Geometry, Geometry, str, float, float]] = None
        self._last_device_ratio_log: Optional[Tuple[str, float, float, float]] = None

    # Placeholder methods for future wiring; concrete logic stays in OverlayWindow for now.
    # These will be filled as geometry and visibility orchestration moves here in later stages.
