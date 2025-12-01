from __future__ import annotations

import sys
from typing import Any, Dict, Tuple

import pytest

OVERLAY_ROOT = __file__.rsplit("/overlay_client/tests/", 1)[0]
if OVERLAY_ROOT not in sys.path:
    sys.path.append(OVERLAY_ROOT)

# PyQt-dependent tests are guarded by the pyqt_required marker.
try:
    from PyQt6.QtCore import QPoint, QRect
except Exception:  # pragma: no cover - import guard
    pytest.skip("PyQt6 not available", allow_module_level=True)

from overlay_client.debug_cycle_overlay import CycleOverlayView  # noqa: E402
from overlay_client.viewport_helper import ScaleMode, compute_viewport_transform  # noqa: E402
from overlay_client.viewport_transform import LegacyMapper  # noqa: E402


class _FakeFontMetrics:
    def height(self) -> int:
        return 10

    def ascent(self) -> int:
        return 8

    def horizontalAdvance(self, text: str) -> int:
        # simple width approximation
        return len(text) * 5


class _FakePainter:
    def __init__(self) -> None:
        self.drawn_rect: QRect | None = None
        self.lines: list[Tuple[QPoint, QPoint]] = []
        self.ellipses: list[QPoint] = []

    def save(self) -> None:
        return None

    def restore(self) -> None:
        return None

    def setPen(self, *_: Any, **__: Any) -> None:
        return None

    def setBrush(self, *_: Any, **__: Any) -> None:
        return None

    def setFont(self, *_: Any, **__: Any) -> None:
        return None

    def fontMetrics(self) -> _FakeFontMetrics:
        return _FakeFontMetrics()

    def drawRoundedRect(self, rect: QRect, *_: Any, **__: Any) -> None:
        self.drawn_rect = rect

    def drawText(self, *_: Any, **__: Any) -> None:
        return None

    def drawLine(self, start: QPoint, end: QPoint) -> None:
        self.lines.append((start, end))

    def drawEllipse(self, center: QPoint, *_: Any, **__: Any) -> None:
        self.ellipses.append(center)


class _FakeItem:
    def __init__(self) -> None:
        self.item_id = "id1"
        self.plugin = "tester"
        self.expiry = None
        self.kind = "message"
        self.data: Dict[str, Any] = {"size": "normal"}


class _FakePayloadModel:
    def __init__(self) -> None:
        self._item = _FakeItem()

    def get(self, item_id: str) -> _FakeItem | None:
        return self._item if item_id == "id1" else None

    def describe_iso(self, value: str) -> str:
        return value


class _FakeGroupingHelper:
    def transform_for_item(self, *_: Any, **__: Any) -> None:
        return None


@pytest.mark.pyqt_required
def test_cycle_overlay_centers_on_visible_area_with_overflow() -> None:
    transform = compute_viewport_transform(400, 300, ScaleMode.FILL)
    mapper = LegacyMapper(
        scale_x=transform.scale,
        scale_y=transform.scale,
        offset_x=transform.offset[0],
        offset_y=transform.offset[1],
        transform=transform,
    )
    painter = _FakePainter()
    view = CycleOverlayView()
    window_width = 400.0
    window_height = 300.0

    view.paint_cycle_overlay(
        painter,
        cycle_enabled=True,
        cycle_current_id="id1",
        compute_legacy_mapper=lambda: mapper,
        font_family="TestFont",
        window_width=window_width,
        window_height=window_height,
        cycle_anchor_points={"id1": (500.0, 500.0)},  # outside visible area to exercise clamping
        payload_model=_FakePayloadModel(),
        grouping_helper=_FakeGroupingHelper(),
    )

    assert painter.drawn_rect is not None, "Panel should be drawn"
    rect = painter.drawn_rect
    # Center near the visible window center even when the mapper scaled size overflows.
    expected_center_x = window_width / 2.0
    expected_center_y = window_height / 2.0
    assert abs(rect.center().x() - expected_center_x) < rect.width()
    assert abs(rect.center().y() - expected_center_y) < rect.height()
    # Panel stays inside the visible window bounds.
    assert 0 <= rect.left() <= window_width - rect.width()
    assert 0 <= rect.top() <= window_height - rect.height()
