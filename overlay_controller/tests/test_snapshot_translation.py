import math

import overlay_controller.overlay_controller as oc
from overlay_controller.preview import snapshot_math


def _make_snapshot() -> oc._GroupSnapshot:
    base_bounds = (100.0, 100.0, 200.0, 200.0)
    anchor = (100.0, 100.0)
    return oc._GroupSnapshot(
        plugin="PluginB",
        label="G1",
        anchor_token="nw",
        transform_anchor_token="nw",
        offset_x=0.0,
        offset_y=0.0,
        base_bounds=base_bounds,
        base_anchor=anchor,
        transform_bounds=base_bounds,
        transform_anchor=anchor,
        has_transform=False,
        cache_timestamp=0.0,
    )


def test_translate_snapshot_fill_overflow_applies_shift():
    snap = _make_snapshot()
    translated = snapshot_math.translate_snapshot_for_fill(
        snap,
        1280.0,
        720.0,
        scale_mode_value="fill",
        anchor_token_override="nw",
    )
    assert translated is not None
    assert translated.has_transform
    trans_min_x, trans_min_y, _, _ = translated.transform_bounds
    # For 1280x720 Fill, expect upward shift from y=100 -> ~75 (anchor-based proportional remap).
    assert math.isclose(trans_min_y, 75.0, rel_tol=1e-3, abs_tol=1e-3)
    assert trans_min_x == snap.base_bounds[0]
    assert math.isclose(translated.transform_anchor[1], 75.0, rel_tol=1e-3, abs_tol=1e-3)


def test_translate_snapshot_fit_no_shift():
    snap = _make_snapshot()
    translated = snapshot_math.translate_snapshot_for_fill(
        snap,
        1280.0,
        720.0,
        scale_mode_value="fit",
        anchor_token_override="nw",
    )
    assert translated is snap or not translated.has_transform
    # No translation; bounds remain the same.
    assert translated.transform_bounds == snap.transform_bounds


def test_translate_snapshot_anchor_override_changes_shift():
    snap = _make_snapshot()
    translated = snapshot_math.translate_snapshot_for_fill(
        snap,
        1280.0,
        720.0,
        scale_mode_value="fill",
        anchor_token_override="center",
    )
    assert translated.has_transform
    trans_min_x, trans_min_y, _, _ = translated.transform_bounds
    # Center anchor should shift further up than NW (dy ~ -37.5 -> y ~ 62.5)
    assert math.isclose(trans_min_y, 62.5, rel_tol=1e-3, abs_tol=1e-3)
    assert math.isclose(translated.transform_anchor[1], 112.5, rel_tol=1e-3, abs_tol=1e-3)
