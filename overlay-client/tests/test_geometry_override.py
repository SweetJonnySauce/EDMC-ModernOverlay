"""Tests for geometry override classification logic."""
import sys
from pathlib import Path

from PyQt6.QtCore import QSize

sys.path.append(str(Path(__file__).resolve().parents[1]))

from overlay_client import OverlayWindow  # noqa: E402


def test_classifies_layout_when_actual_matches_size_hints() -> None:
    tracker = (0, 0, 1286, 752)
    actual = (0, 0, 1394, 752)
    min_hint = QSize(1394, 740)
    size_hint = QSize(1394, 752)

    classification = OverlayWindow._compute_geometry_override_classification(tracker, actual, min_hint, size_hint)

    assert classification == "layout"


def test_classifies_wm_when_actual_smaller_than_tracker() -> None:
    tracker = (0, 0, 1286, 752)
    actual = (0, 0, 1260, 752)
    min_hint = QSize(1200, 700)
    size_hint = QSize(1260, 752)

    classification = OverlayWindow._compute_geometry_override_classification(tracker, actual, min_hint, size_hint)

    assert classification == "wm_intervention"


def test_classifies_wm_when_hints_do_not_require_growth() -> None:
    tracker = (0, 0, 1286, 752)
    actual = (0, 0, 1300, 752)
    min_hint = QSize(1200, 700)
    size_hint = QSize(1250, 740)

    classification = OverlayWindow._compute_geometry_override_classification(tracker, actual, min_hint, size_hint)

    assert classification == "wm_intervention"


def test_classifies_layout_for_fractional_follow_sizes() -> None:
    tracker = (100, 200, 1285, 719)
    actual = (100, 200, 1292, 723)
    min_hint = QSize(1290, 720)
    size_hint = QSize(1292, 723)

    classification = OverlayWindow._compute_geometry_override_classification(tracker, actual, min_hint, size_hint, tolerance=3)

    assert classification == "layout"


def test_aspect_guard_trims_small_delta_for_near_16_9() -> None:
    dummy = type("DummyWindow", (), {"_aspect_guard_skip_logged": False})()
    geometry = (0, 0, 1920, 1100)
    original = (0, 0, 1920, 1080)

    adjusted = OverlayWindow._apply_aspect_guard(
        dummy, geometry, original_geometry=original, applied_title_offset=0
    )

    assert adjusted == (0, 0, 1920, 1080)
    assert dummy._aspect_guard_skip_logged is False


def test_aspect_guard_leaves_16_10_window_after_compensation() -> None:
    dummy = type("DummyWindow", (), {"_aspect_guard_skip_logged": False})()
    geometry = (0, 0, 1920, 1170)
    original = (0, 0, 1920, 1200)

    adjusted = OverlayWindow._apply_aspect_guard(
        dummy, geometry, original_geometry=original, applied_title_offset=30
    )

    assert adjusted == geometry
    assert dummy._aspect_guard_skip_logged is True
