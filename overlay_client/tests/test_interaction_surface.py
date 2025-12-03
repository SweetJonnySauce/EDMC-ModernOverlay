from __future__ import annotations

from typing import Optional, Tuple

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PyQt6.QtGui import QMouseEvent, QMoveEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication, QWidget

from overlay_client.interaction_surface import InteractionSurfaceMixin


class _FollowStub:
    def __init__(self) -> None:
        self.drag_state_calls: list[Tuple[bool, bool]] = []

    def set_drag_state(self, active: bool, move_mode: bool) -> None:
        self.drag_state_calls.append((active, move_mode))


class _InteractionStubWindow(InteractionSurfaceMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._invalidate_calls = 0
        self._auto_scale_calls: list[Tuple[int, int]] = []
        self._metrics_calls = 0
        self._describe_calls: list[object] = []
        self._override_calls: list[Tuple[Tuple[int, int, int, int], Optional[Tuple[int, int, int, int]], str, str]] = []
        self._suspend_follow_calls: list[float] = []
        self._apply_drag_state_calls = 0

        self._follow_controller = _FollowStub()
        self._follow_enabled = True
        self._window_tracker: Optional[object] = None
        self._last_follow_state = None
        self._last_set_geometry: Optional[Tuple[int, int, int, int]] = None
        self._last_move_log: Optional[Tuple[int, int]] = None

        self._drag_enabled = False
        self._drag_active = False
        self._drag_offset = QPoint()
        self._move_mode = False
        self._cursor_saved = False
        self._saved_cursor = self.cursor()
        self._enforcing_follow_size = False

        self._grid_pixmap = None
        self._grid_pixmap_params = None

    def _invalidate_grid_cache(self) -> None:
        self._invalidate_calls += 1

    def _update_auto_legacy_scale(self, width: int, height: int) -> None:
        self._auto_scale_calls.append((width, height))

    def _publish_metrics(self) -> None:
        self._metrics_calls += 1

    def _describe_screen(self, screen: object) -> str:
        self._describe_calls.append(screen)
        return "desc"

    def format_scale_debug(self) -> str:
        return "scale-debug"

    def _set_wm_override(
        self,
        rect: Tuple[int, int, int, int],
        tracker_tuple: Optional[Tuple[int, int, int, int]],
        reason: str,
        classification: str = "wm_intervention",
    ) -> None:
        self._override_calls.append((rect, tracker_tuple, reason, classification))

    def _suspend_follow(self, delay: float = 0.75) -> None:
        self._suspend_follow_calls.append(delay)

    def _apply_drag_state(self) -> None:
        self._apply_drag_state_calls += 1

    def setGeometry(self, *args, **kwargs) -> None:  # type: ignore[override]
        if args and len(args) == 1:
            rect = args[0]
        else:
            rect = args
        self._last_geometry_set = rect  # type: ignore[attr-defined]
        super().setGeometry(*args, **kwargs)


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.mark.pyqt_required
def test_resize_event_enforces_follow_size_and_skips_metrics(qt_app):
    window = _InteractionStubWindow()
    window._follow_enabled = True
    window._window_tracker = object()
    window._last_set_geometry = (10, 20, 30, 40)

    event = QResizeEvent(QSize(50, 60), QSize(5, 5))
    window.resizeEvent(event)

    assert window._invalidate_calls == 1
    assert window._enforcing_follow_size is True
    assert window._auto_scale_calls == []
    assert window._metrics_calls == 0
    assert window._last_geometry_set == window.geometry()  # type: ignore[attr-defined]
    assert window._last_geometry_set.getRect() == (10, 20, 30, 40)  # type: ignore[attr-defined]


@pytest.mark.pyqt_required
def test_drag_events_toggle_state_and_offsets(qt_app):
    window = _InteractionStubWindow()
    window._drag_enabled = True
    window._move_mode = True
    window._follow_enabled = True
    window.setGeometry(0, 0, 100, 100)

    press_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(0, 0),
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(press_event)

    assert window._drag_active is True
    assert window._follow_controller.drag_state_calls == [(True, True)]
    assert window._suspend_follow_calls == [1.0]
    assert window._drag_offset == QPoint(10, 10)
    assert press_event.isAccepted()
    assert window._cursor_saved is True

    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(0, 0),
        QPointF(20, 20),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseMoveEvent(move_event)
    assert move_event.isAccepted()
    assert window.pos() == QPoint(10, 10)

    release_event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(0, 0),
        QPointF(20, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseReleaseEvent(release_event)

    assert window._drag_active is False
    assert window._follow_controller.drag_state_calls[-1] == (False, True)
    assert window._suspend_follow_calls[-1] == 0.5
    assert window._apply_drag_state_calls == 1
    assert release_event.isAccepted()
    assert window._cursor_saved is False


@pytest.mark.pyqt_required
def test_move_event_records_override_for_geometry_delta(qt_app):
    window = _InteractionStubWindow()
    window._follow_enabled = True
    window._last_set_geometry = (0, 0, 20, 20)
    window.setGeometry(10, 10, 20, 20)
    window._last_move_log = None

    move_event = QMoveEvent(QPoint(10, 10), QPoint(0, 0))
    window.moveEvent(move_event)

    assert window._override_calls == [((10, 10, 20, 20), None, "moveEvent delta", "wm_intervention")]
    assert window._last_move_log == (10, 10)
    assert window._describe_calls == [None]
