"""Controller for follow/window orchestration (geometry and visibility decisions).

This module is intended to stay free of Qt types; callers inject thin adapters for
Qt interactions (geometry getters/setters, screen descriptors, logging).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from overlay_client.follow_geometry import _resolve_wm_override  # type: ignore

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
        self._last_geometry_log: Optional[Geometry] = None

    # Placeholder methods for future wiring; concrete logic stays in OverlayWindow for now.
    # These will be filled as geometry and visibility orchestration moves here in later stages.

    def resolve_and_apply_geometry(
        self,
        tracker_qt_tuple: Geometry,
        desired_tuple: Geometry,
        *,
        override_rect: Optional[Geometry],
        override_tracker: Optional[Geometry],
        override_expired: bool,
        current_geometry_fn: Callable[[], Geometry],
        move_to_screen_fn: Callable[[Geometry], None],
        set_geometry_fn: Callable[[Geometry], None],
        sync_base_dimensions_fn: Callable[[], None],
        classify_override_fn: Callable[[Geometry, Geometry], str],
        clear_override_fn: Callable[[str], None],
        set_override_fn: Callable[[Geometry, Geometry, str, str], None],
        format_scale_debug_fn: Callable[[], str],
    ) -> Geometry:
        target_tuple, clear_override_reason = _resolve_wm_override(
            tracker_qt_tuple,
            desired_tuple,
            override_rect,
            override_tracker,
            override_expired,
        )
        if clear_override_reason:
            clear_override_fn(reason=clear_override_reason)

        actual_tuple = current_geometry_fn()

        if target_tuple != self._last_geometry_log:
            self._log(f"Calculated overlay geometry: target={target_tuple}; {format_scale_debug_fn()}")

        needs_geometry_update = actual_tuple != target_tuple

        if needs_geometry_update:
            self._log(f"Applying geometry via setGeometry: target={target_tuple}; {format_scale_debug_fn()}")
            move_to_screen_fn(target_tuple)
            set_geometry_fn(target_tuple)
            sync_base_dimensions_fn()
            actual_tuple = current_geometry_fn()
        else:
            sync_base_dimensions_fn()

        if actual_tuple != target_tuple:
            self._log(
                f"Window manager override detected: actual={actual_tuple} target={target_tuple}; {format_scale_debug_fn()}"
            )
            classification = classify_override_fn(target_tuple, actual_tuple)
            if classification == "layout":
                set_override_fn(actual_tuple, tracker_qt_tuple, "geometry mismatch", classification)
            else:
                set_override_fn(actual_tuple, tracker_qt_tuple, "geometry mismatch", classification)
            target_tuple = actual_tuple
        elif override_rect and tracker_qt_tuple == target_tuple:
            clear_override_fn(reason="tracker matched actual")

        self._last_geometry_log = target_tuple
        return target_tuple
