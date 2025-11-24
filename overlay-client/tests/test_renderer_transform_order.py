from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if not os.getenv("PYQT_TESTS"):
    pytest.skip("PYQT_TESTS not set; skipping PyQt-dependent test", allow_module_level=True)

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from payload_transform import apply_transform_meta_to_point  # noqa: E402


def test_transform_meta_applies_fill_translation_before_scaling() -> None:
    meta = {
        "pivot": {"x": 27.0, "y": 587.0},
        "scale": {"x": 2.0, "y": 1.0},
        "offset": {"x": 0.0, "y": 150.0},
    }

    no_fill = apply_transform_meta_to_point(meta, 124.0, 464.0, 0.0, 0.0)
    with_fill = apply_transform_meta_to_point(meta, 124.0, 464.0, 10.0, -5.0)

    assert no_fill == pytest.approx((221.0, 614.0))
    assert with_fill == pytest.approx((231.0, 609.0))


def test_transform_meta_defaults_to_fill_only_when_metadata_missing() -> None:
    result = apply_transform_meta_to_point(None, 50.0, 75.0, -5.0, 12.0)

    assert result == pytest.approx((45.0, 87.0))
