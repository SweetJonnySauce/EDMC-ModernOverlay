from __future__ import annotations

import math

from overlay_client.viewport_helper import ScaleMode
from overlay_client.viewport_transform import LegacyMapper
from overlay_client.window_utils import (
    aspect_ratio_label,
    compute_legacy_mapper,
    current_physical_size,
    legacy_preset_point_size,
    line_width,
    viewport_state,
)


def test_current_physical_size_uses_ratio_and_guards() -> None:
    assert current_physical_size(100, 50, 2.0) == (200.0, 100.0)
    # Non-positive ratio falls back to 1.0
    assert current_physical_size(100, 50, 0.0) == (100.0, 50.0)


def test_aspect_ratio_label_prefers_known_ratio() -> None:
    assert aspect_ratio_label(1920, 1080) == "16:9"
    # Falls back to simplified fraction
    assert aspect_ratio_label(17, 11) == "17:11"


def test_compute_legacy_mapper_defaults_to_fit() -> None:
    mapper = compute_legacy_mapper("fit", 1280, 960)
    assert math.isclose(mapper.scale_x, 1.0, rel_tol=1e-9)
    assert math.isclose(mapper.scale_y, 1.0, rel_tol=1e-9)
    assert mapper.transform.mode is ScaleMode.FIT
    assert mapper.offset_x == 0.0
    assert mapper.offset_y == 0.0


def test_viewport_state_sanitises_ratio() -> None:
    state = viewport_state(0.0, 0.0, 0.0)
    assert state.width == 1.0
    assert state.height == 1.0
    assert state.device_ratio == 1.0


def test_legacy_preset_point_size_offsets_from_normal() -> None:
    state = viewport_state(1280.0, 960.0, 1.0)
    mapper: LegacyMapper = compute_legacy_mapper("fit", 1280.0, 960.0)
    base_kwargs = {
        "state": state,
        "mapper": mapper,
        "font_scale_diag": 1.0,
        "font_min_point": 1.0,
        "font_max_point": 200.0,
        "legacy_font_step": 2.0,
    }
    assert math.isclose(legacy_preset_point_size("small", **base_kwargs), 8.0)
    assert math.isclose(legacy_preset_point_size("normal", **base_kwargs), 10.0)
    assert math.isclose(legacy_preset_point_size("huge", **base_kwargs), 14.0)
    base_kwargs["legacy_font_step"] = 0.0
    assert math.isclose(legacy_preset_point_size("small", **base_kwargs), 10.0)
    assert math.isclose(legacy_preset_point_size("huge", **base_kwargs), 10.0)


def test_line_width_rounds_and_clamps() -> None:
    widths = {"grid": "3.6", "invalid": "abc"}
    defaults = {"grid": 1, "invalid": 2}
    assert line_width(widths, defaults, "grid") == 4
    assert line_width(widths, defaults, "invalid") == 2
