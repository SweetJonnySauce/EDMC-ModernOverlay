from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from overlay_client import OverlayClient  # noqa: E402


def test_compensation_preserves_right_margin_on_16x9():
    delta = OverlayClient._compute_compensation_delta(
        min_val=1080.0,
        max_val=1120.0,
        base_scale=1.5,
        effective_scale=1.0,
        base_offset=0.0,
        extent=1920.0,
    )

    assert delta == pytest.approx(1120.0 * (1.5 / 1.0 - 1.0))


def test_compensation_scales_for_ultrawide_windows():
    delta = OverlayClient._compute_compensation_delta(
        min_val=1080.0,
        max_val=1120.0,
        base_scale=2.0,
        effective_scale=1.0,
        base_offset=0.0,
        extent=2560.0,
    )

    assert delta == pytest.approx(1120.0 * (2.0 / 1.0 - 1.0))


def test_compensation_prefers_left_margin_when_smaller():
    delta = OverlayClient._compute_compensation_delta(
        min_val=30.0,
        max_val=200.0,
        base_scale=1.5,
        effective_scale=1.0,
        base_offset=0.0,
        extent=1920.0,
    )

    assert delta == pytest.approx(30.0 * (1.5 / 1.0 - 1.0))
