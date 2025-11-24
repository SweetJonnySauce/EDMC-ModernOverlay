from __future__ import annotations

import sys
from pathlib import Path

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[1]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.append(str(OVERLAY_ROOT))

from group_transform import GroupBounds  # noqa: E402
from legacy_store import LegacyItem  # noqa: E402
import payload_transform  # noqa: E402
from overlay_client import _OverlayBounds  # type: ignore  # noqa: E402

pytestmark = pytest.mark.pyqt_required


def _make_message(text: str, scale: float) -> LegacyItem:
    return LegacyItem(
        item_id="msg",
        kind="message",
        data={
            "text": text,
            "x": 0,
            "y": 0,
            "size": "normal",
            "__mo_transform__": {"scale": {"x": scale, "y": scale}},
        },
        expiry=None,
        plugin="test",
    )


def test_message_bounds_fit_mode_scales_with_viewport(monkeypatch) -> None:
    fake_width = 200
    fake_height = 40

    def fake_measure(_metrics, _text):
        return fake_width, fake_height

    monkeypatch.setattr(payload_transform, "_measure_text_block", fake_measure)

    bounds = GroupBounds()
    item = _make_message("line1\nline2", scale=0.5)
    payload_transform.accumulate_group_bounds(
        bounds,
        item,
        pixels_per_overlay_unit=2.0,
        font_family="Eurostile",
        preset_point_size=lambda _label: 12.0,
    )

    assert bounds.is_valid()
    width = bounds.max_x - bounds.min_x
    height = bounds.max_y - bounds.min_y
    assert width == pytest.approx(fake_width / 2.0)
    assert height == pytest.approx(fake_height / 2.0)


def test_message_bounds_fill_mode_uses_text_measurements(monkeypatch) -> None:
    fake_width = 240
    fake_height = 30

    def fake_measure(_metrics, _text):
        return fake_width, fake_height

    monkeypatch.setattr(payload_transform, "_measure_text_block", fake_measure)

    bounds = GroupBounds()
    item = _make_message("sample", scale=1.0)
    payload_transform.accumulate_group_bounds(
        bounds,
        item,
        pixels_per_overlay_unit=1.0,
        font_family="Eurostile",
        preset_point_size=lambda _label: 12.0,
    )

    assert bounds.is_valid()
    assert (bounds.max_x - bounds.min_x) == pytest.approx(fake_width)
    assert (bounds.max_y - bounds.min_y) == pytest.approx(fake_height)


def test_overlay_bounds_dataclass_tracks_min_max() -> None:
    bounds = _OverlayBounds()
    bounds.include_rect(10.0, 20.0, 30.0, 60.0)
    bounds.include_rect(15.0, 10.0, 25.0, 55.0)

    assert bounds.is_valid()
    assert bounds.min_x == pytest.approx(10.0)
    assert bounds.max_x == pytest.approx(30.0)
    assert bounds.min_y == pytest.approx(10.0)
    assert bounds.max_y == pytest.approx(60.0)
