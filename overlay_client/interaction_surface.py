"""Interaction/event surface mixin extracted from overlay_client."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QWidget

_CLIENT_LOGGER = logging.getLogger("EDMC.ModernOverlay.Client")


class InteractionSurfaceMixin:
    """Handles interaction/event overrides for the overlay window."""

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        QWidget.resizeEvent(self, event)
        self._invalidate_grid_cache()
        size = event.size()
        if self._enforcing_follow_size:
            self._enforcing_follow_size = False
            self._update_auto_legacy_scale(max(size.width(), 1), max(size.height(), 1))
            return
        expected_size: Optional[Tuple[int, int]] = None
        if (
            self._follow_enabled
            and self._last_set_geometry is not None
            and (self._window_tracker is not None or self._last_follow_state is not None)
        ):
            expected_size = (self._last_set_geometry[2], self._last_set_geometry[3])
        if expected_size and (size.width(), size.height()) != expected_size:
            self._enforcing_follow_size = True
            target_rect = QRect(*self._last_set_geometry)
            self.setGeometry(target_rect)
            return
        self._update_auto_legacy_scale(max(size.width(), 1), max(size.height(), 1))
        self._publish_metrics()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_enabled
            and self._move_mode
        ):
            self._drag_active = True
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            self._suspend_follow(1.0)
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if not self._cursor_saved:
                self._saved_cursor = self.cursor()
                self._cursor_saved = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            _CLIENT_LOGGER.debug(
                "Drag initiated at pos=%s offset=%s (from %s) move_mode=%s",
                self.frameGeometry().topLeft(),
                self._drag_offset,
                event.globalPosition().toPoint(),
                self._move_mode,
            )
            event.accept()
            return
        QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            event.accept()
            return
        QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            self._suspend_follow(0.5)
            self.raise_()
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False
            self._apply_drag_state()
            _CLIENT_LOGGER.debug("Drag finished; overlay frame=%s", self.frameGeometry())
            event.accept()
            return
        QWidget.mouseReleaseEvent(self, event)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        QWidget.moveEvent(self, event)
        frame = self.frameGeometry()
        current = (frame.x(), frame.y())
        if current != self._last_move_log:
            screen_desc = self._describe_screen(self.windowHandle().screen() if self.windowHandle() else None)
            _CLIENT_LOGGER.debug(
                "Overlay moveEvent: pos=(%d,%d) frame=%s last_set=%s monitor=%s; %s",
                frame.x(),
                frame.y(),
                (frame.x(), frame.y(), frame.width(), frame.height()),
                self._last_set_geometry,
                screen_desc,
                self.format_scale_debug(),
            )
            if (
                self._follow_enabled
                and self._last_set_geometry is not None
                and (frame.x(), frame.y(), frame.width(), frame.height()) != self._last_set_geometry
            ):
                self._set_wm_override(
                    (frame.x(), frame.y(), frame.width(), frame.height()),
                    tracker_tuple=None,
                    reason="moveEvent delta",
                    classification="wm_intervention",
                )
            self._last_move_log = current
