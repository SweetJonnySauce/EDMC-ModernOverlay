"""Follow/window orchestration and platform hooks mixin for the overlay window."""
from __future__ import annotations

import logging
import sys
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import QGuiApplication, QWindow, QScreen
from PyQt6.QtWidgets import QApplication

from overlay_client.follow_geometry import (
    ScreenInfo,
    _apply_aspect_guard,
    _apply_title_bar_offset,
    _convert_native_rect_to_qt,
)
from overlay_client.window_tracking import WindowState

_CLIENT_LOGGER = logging.getLogger("EDMC.ModernOverlay.Client")

# Keep defaults local to avoid import cycles while matching overlay_client values.
DEFAULT_WINDOW_BASE_WIDTH = 1280
DEFAULT_WINDOW_BASE_HEIGHT = 960


class FollowSurfaceMixin:
    """Follow/window orchestration, platform hooks, and visibility helpers."""

    def _apply_drag_state(self) -> None:
        window = self.windowHandle()
        _CLIENT_LOGGER.debug(
            "Applying drag state: drag_enabled=%s transparent=%s move_mode=%s window=%s flags=%s",
            self._drag_enabled,
            not self._drag_enabled,
            self._move_mode,
            bool(window),
            hex(int(window.flags())) if window is not None else "none",
        )
        self._interaction_controller.set_click_through(not self._drag_enabled, force=True, reason="apply_drag_state")
        if not self._drag_enabled:
            self._move_mode = False
            self._drag_active = False
            self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False
        self.raise_()

    def _poll_modifiers(self) -> None:
        if not self._drag_enabled or self._drag_active:
            return
        modifiers = QApplication.queryKeyboardModifiers()
        alt_down = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if alt_down and not self._move_mode:
            self._move_mode = True
            self._suspend_follow(0.75)
            if not self._cursor_saved:
                self._saved_cursor = self.cursor()
                self._cursor_saved = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif not alt_down and self._move_mode:
            self._move_mode = False
            if self._cursor_saved:
                self.setCursor(self._saved_cursor)
                self._cursor_saved = False

    def _set_click_through(self, transparent: bool) -> None:
        self._interaction_controller.set_click_through(transparent, force=True, reason="external_set_click_through")

    def _restore_drag_interactivity(self) -> None:
        self._interaction_controller.restore_drag_interactivity(self._drag_enabled, self._drag_active, self.format_scale_debug)

    def _set_children_click_through(self, transparent: bool) -> None:
        for child_name in ("message_label",):
            child = getattr(self, child_name, None)
            if child is not None:
                try:
                    child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
                except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                    _CLIENT_LOGGER.debug("Failed to set click-through on child %s: %s", child_name, exc)
                except Exception as exc:  # pragma: no cover - unexpected Qt errors
                    _CLIENT_LOGGER.warning("Unexpected error setting click-through on child %s: %s", child_name, exc)

    def _clear_transient_parent_ids(self) -> None:
        self._transient_parent_window = None
        self._transient_parent_id = None

    # Follow mode ----------------------------------------------------------

    def _start_tracking(self) -> None:
        if not self._window_tracker or not self._follow_enabled:
            return
        self._follow_controller.set_follow_enabled(True)
        self._follow_controller.set_drag_state(self._drag_active, self._move_mode)
        self._follow_controller.start()

    def _stop_tracking(self) -> None:
        self._follow_controller.stop()

    def _set_wm_override(
        self,
        rect: Tuple[int, int, int, int],
        tracker_tuple: Optional[Tuple[int, int, int, int]],
        reason: str,
        classification: str = "wm_intervention",
    ) -> None:
        self._follow_controller.record_override(rect, tracker_tuple, reason, classification)

    def _clear_wm_override(self, reason: str) -> None:
        self._follow_controller.clear_override(reason)

    def _suspend_follow(self, delay: float = 0.75) -> None:
        self._follow_controller.suspend(delay)

    def _refresh_follow_geometry(self) -> None:
        state = self._follow_controller.refresh()
        if state is None:
            if self._follow_controller.last_poll_attempted and self._follow_controller.last_state_missing:
                self._handle_missing_follow_state()
            return
        self._last_tracker_state = self._follow_controller.last_tracker_state
        self._apply_follow_state(state)

    def _convert_native_rect_to_qt(
        self,
        rect: Tuple[int, int, int, int],
    ) -> Tuple[Tuple[int, int, int, int], Optional[Tuple[str, float, float, float]]]:
        screen_info = self._screen_info_for_native_rect(rect)
        return _convert_native_rect_to_qt(
            rect,
            screen_info,
            physical_clamp_enabled=getattr(self, "_physical_clamp_enabled", False),
            physical_clamp_overrides=getattr(self, "_physical_clamp_overrides", None),
        )

    def _apply_title_bar_offset(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        scale_y: float = 1.0,
    ) -> Tuple[Tuple[int, int, int, int], int]:
        adjusted, offset = _apply_title_bar_offset(
            geometry,
            title_bar_enabled=self._title_bar_enabled,
            title_bar_height=self._title_bar_height,
            scale_y=scale_y,
            previous_offset=self._last_title_bar_offset,
        )
        self._last_title_bar_offset = offset
        return adjusted, offset

    def _apply_aspect_guard(
        self,
        geometry: Tuple[int, int, int, int],
        *,
        original_geometry: Optional[Tuple[int, int, int, int]] = None,
        applied_title_offset: int = 0,
    ) -> Tuple[int, int, int, int]:
        adjusted, self._aspect_guard_skip_logged = _apply_aspect_guard(
            geometry,
            base_width=DEFAULT_WINDOW_BASE_WIDTH,
            base_height=DEFAULT_WINDOW_BASE_HEIGHT,
            original_geometry=original_geometry,
            applied_title_offset=applied_title_offset,
            aspect_guard_skip_logged=self._aspect_guard_skip_logged,
        )
        return adjusted

    def _apply_follow_state(self, state: WindowState) -> None:
        self._lost_window_logged = False

        tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple = self._normalise_tracker_geometry(state)

        target_tuple = self._resolve_and_apply_geometry(tracker_qt_tuple, desired_tuple)
        self._post_process_follow_state(state, target_tuple)

    def _normalise_tracker_geometry(
        self,
        state: WindowState,
    ) -> Tuple[
        Tuple[int, int, int, int],
        Tuple[int, int, int, int],
        Optional[Tuple[str, float, float, float]],
        Tuple[int, int, int, int],
    ]:
        tracker_global_x = state.global_x if state.global_x is not None else state.x
        tracker_global_y = state.global_y if state.global_y is not None else state.y
        width = max(1, state.width)
        height = max(1, state.height)
        tracker_native_tuple = (
            tracker_global_x,
            tracker_global_y,
            width,
            height,
        )
        if tracker_native_tuple != self._last_raw_window_log:
            _CLIENT_LOGGER.debug(
                "Raw tracker window geometry: pos=(%d,%d) size=%dx%d",
                tracker_global_x,
                tracker_global_y,
                width,
                height,
            )
            self._last_raw_window_log = tracker_native_tuple

        tracker_qt_tuple, normalisation_info = self._convert_native_rect_to_qt(tracker_native_tuple)
        if normalisation_info is not None and tracker_qt_tuple != tracker_native_tuple:
            screen_name, norm_scale_x, norm_scale_y, device_ratio = normalisation_info
            snapshot = (tracker_native_tuple, tracker_qt_tuple, screen_name, norm_scale_x, norm_scale_y)
            if snapshot != self._last_normalised_tracker:
                _CLIENT_LOGGER.debug(
                    "Normalised tracker geometry using screen '%s': native=%s scale=%.3fx%.3f dpr=%.3f -> qt=%s",
                    screen_name,
                    tracker_native_tuple,
                    norm_scale_x,
                    norm_scale_y,
                    device_ratio,
                    tracker_qt_tuple,
                )
                self._last_normalised_tracker = snapshot
        else:
            self._last_normalised_tracker = None

        window_handle = self.windowHandle()
        if window_handle is not None:
            try:
                window_dpr = window_handle.devicePixelRatio()
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                _CLIENT_LOGGER.debug("Failed to read devicePixelRatio, defaulting to 0.0: %s", exc)
                window_dpr = 0.0
            except Exception as exc:  # pragma: no cover - unexpected Qt errors
                _CLIENT_LOGGER.warning("Unexpected devicePixelRatio failure, defaulting to 0.0: %s", exc)
                window_dpr = 0.0
            if window_dpr and normalisation_info is not None:
                screen_name, norm_scale_x, norm_scale_y, device_ratio = normalisation_info
                snapshot = (screen_name, float(window_dpr), norm_scale_x, norm_scale_y)
                if snapshot != self._last_device_ratio_log:
                    _CLIENT_LOGGER.debug(
                        "Device pixel ratio diagnostics: window_dpr=%.3f screen='%s' scale_x=%.3f scale_y=%.3f device_ratio=%.3f",
                        float(window_dpr),
                        screen_name,
                        norm_scale_x,
                        norm_scale_y,
                        device_ratio,
                    )
                    self._last_device_ratio_log = snapshot

        scale_y = normalisation_info[2] if normalisation_info is not None else 1.0
        desired_tuple, applied_title_offset = self._apply_title_bar_offset(tracker_qt_tuple, scale_y=scale_y)
        desired_tuple = self._apply_aspect_guard(
            desired_tuple,
            original_geometry=tracker_qt_tuple,
            applied_title_offset=applied_title_offset,
        )
        return tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple

    def _resolve_and_apply_geometry(
        self,
        tracker_qt_tuple: Tuple[int, int, int, int],
        desired_tuple: Tuple[int, int, int, int],
    ) -> Tuple[int, int, int, int]:
        override_rect = self._follow_controller.wm_override
        override_tracker = self._follow_controller.wm_override_tracker
        override_expired = self._follow_controller.override_expired()

        def _current_geometry() -> Tuple[int, int, int, int]:
            current_rect = self.frameGeometry()
            return (
                current_rect.x(),
                current_rect.y(),
                current_rect.width(),
                current_rect.height(),
            )

        def _move_to_screen(target: Tuple[int, int, int, int]) -> None:
            self._move_to_screen(QRect(*target))

        def _set_geometry(target: Tuple[int, int, int, int]) -> None:
            self._last_set_geometry = target
            self.setGeometry(QRect(*target))
            self.raise_()

        def _classify_override(target: Tuple[int, int, int, int], actual: Tuple[int, int, int, int]) -> str:
            classification = self._classify_geometry_override(target, actual)
            if classification == "layout":
                try:
                    size_hint = self.sizeHint()
                except Exception:
                    size_hint = None
                try:
                    min_hint = self.minimumSizeHint()
                except Exception:
                    min_hint = None
                _CLIENT_LOGGER.debug(
                    "Adopting layout-constrained geometry from WM: tracker=%s actual=%s sizeHint=%s minimumSizeHint=%s",
                    tracker_qt_tuple,
                    actual,
                    size_hint,
                    min_hint,
                )
            else:
                _CLIENT_LOGGER.debug(
                    "Adopting WM authoritative geometry: tracker=%s actual=%s (classification=%s)",
                    tracker_qt_tuple,
                    actual,
                    classification,
                )
            return classification

        target_tuple = self._window_controller.resolve_and_apply_geometry(
            tracker_qt_tuple,
            desired_tuple,
            override_rect=override_rect,
            override_tracker=override_tracker,
            override_expired=override_expired,
            current_geometry_fn=_current_geometry,
            move_to_screen_fn=_move_to_screen,
            set_geometry_fn=_set_geometry,
            sync_base_dimensions_fn=self._sync_base_dimensions_to_widget,
            classify_override_fn=_classify_override,
            clear_override_fn=self._clear_wm_override,
            set_override_fn=self._set_wm_override,
            format_scale_debug_fn=self.format_scale_debug,
        )

        self._last_geometry_log = target_tuple
        return target_tuple

    def _post_process_follow_state(
        self,
        state: WindowState,
        target_tuple: Tuple[int, int, int, int],
    ) -> None:
        def _ensure_parent(identifier: str) -> None:
            self._ensure_transient_parent(state)

        def _fullscreen_hint() -> bool:
            if (
                not sys.platform.startswith("linux")
                or self._fullscreen_hint_logged
                or self._window_controller._fullscreen_hint_logged  # internal flag mirrors hint emission
                or not state.is_foreground
            ):
                return False
            screen = self.windowHandle().screen() if self.windowHandle() else None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return False
            geometry = screen.geometry()
            if state.width >= geometry.width() and state.height >= geometry.height():
                _CLIENT_LOGGER.info(
                    "Overlay running in compositor-managed mode; for true fullscreen use borderless windowed in Elite or enable compositor vsync. (%s)",
                    self.format_scale_debug(),
                )
                self._fullscreen_hint_logged = True
                return True
            return False

        normalized_state = WindowState(
            x=state.x,
            y=state.y,
            width=state.width,
            height=state.height,
            is_foreground=state.is_foreground,
            is_visible=state.is_visible,
            identifier=state.identifier,
            global_x=state.global_x if state.global_x is not None else state.x,
            global_y=state.global_y if state.global_y is not None else state.y,
        )

        self._window_controller.post_process_follow_state(
            normalized_state,
            target_tuple,
            force_render=self._force_render,
            update_follow_visibility_fn=self._update_follow_visibility,
            update_auto_scale_fn=self._update_auto_legacy_scale,
            ensure_transient_parent_fn=_ensure_parent,
            fullscreen_hint_fn=_fullscreen_hint,
            is_visible_fn=lambda: self.isVisible(),
        )
        # Mirror controller flag back to overlay state for future checks.
        self._fullscreen_hint_logged = self._window_controller._fullscreen_hint_logged

    def _ensure_transient_parent(self, state: WindowState) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self._is_wayland():
            if self._transient_parent_window is not None:
                window_handle = self.windowHandle()
                if window_handle is not None:
                    try:
                        window_handle.setTransientParent(None)
                    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                        _CLIENT_LOGGER.debug("Failed to clear transient parent on Wayland: %s", exc)
                    except Exception as exc:  # pragma: no cover - unexpected Qt errors
                        _CLIENT_LOGGER.warning("Unexpected error clearing transient parent on Wayland: %s", exc)
                self._transient_parent_window = None
                self._transient_parent_id = None
            return
        identifier = state.identifier
        if not identifier or identifier == self._transient_parent_id:
            return
        window_handle = self.windowHandle()
        if window_handle is None:
            return
        try:
            native_id = int(identifier, 16)
        except ValueError:
            return
        try:
            parent_window = QWindow.fromWinId(native_id)
        except Exception as exc:  # pragma: no cover - defensive guard
            _CLIENT_LOGGER.debug("Failed to wrap native window %s: %s; %s", identifier, exc, self.format_scale_debug())
            return
        if parent_window is None:
            return
        window_handle.setTransientParent(parent_window)
        self._transient_parent_window = parent_window
        self._transient_parent_id = identifier
        _CLIENT_LOGGER.debug("Set overlay transient parent to Elite window %s; %s", identifier, self.format_scale_debug())

    def _handle_missing_follow_state(self) -> None:
        if not self._lost_window_logged:
            _CLIENT_LOGGER.debug("Elite Dangerous window not found; waiting for window to appear; %s", self.format_scale_debug())
            self._lost_window_logged = True
        if self._last_follow_state is None:
            if self._force_render:
                self._update_follow_visibility(True)
                if sys.platform.startswith("linux"):
                    self._platform_controller.apply_click_through(True)
                    self._restore_drag_interactivity()
            else:
                self._update_follow_visibility(False)
            return
        if self._force_render:
            self._update_follow_visibility(True)
            if sys.platform.startswith("linux"):
                self._platform_controller.apply_click_through(True)
                self._restore_drag_interactivity()
        else:
            self._last_follow_state = None
            self._clear_wm_override(reason="follow state lost")
            self._update_follow_visibility(False)

    def _update_follow_visibility(self, show: bool) -> None:
        new_state = self._visibility_helper.update_visibility(
            show,
            is_visible_fn=lambda: self.isVisible(),
            show_fn=lambda: self.show(),
            hide_fn=lambda: self.hide(),
            raise_fn=lambda: self.raise_(),
            apply_drag_state_fn=self._apply_drag_state,
            format_scale_debug_fn=self.format_scale_debug,
        )
        # keep compatibility for any consumers expecting cached state
        self._last_visibility_state = new_state

    def _move_to_screen(self, rect: QRect) -> None:
        window = self.windowHandle()
        if window is None:
            return
        screen = self._screen_for_rect(rect)
        if screen is not None and window.screen() is not screen:
            _CLIENT_LOGGER.debug(
                "Moving overlay to screen %s; %s",
                self._describe_screen(screen),
                self.format_scale_debug(),
            )
            window.setScreen(screen)
            self._last_screen_name = self._describe_screen(screen)
        elif screen is not None:
            self._last_screen_name = self._describe_screen(screen)

    def _screen_for_rect(self, rect: QRect):
        screens = QGuiApplication.screens()
        if not screens:
            return None
        best_screen = None
        best_area = 0
        for screen in screens:
            area = rect.intersected(screen.geometry())
            intersection_area = area.width() * area.height()
            if intersection_area > best_area:
                best_area = intersection_area
                best_screen = screen
        if best_screen is not None:
            return best_screen
        primary = QGuiApplication.primaryScreen()
        return primary or screens[0]

    def _screen_for_native_rect(self, rect: QRect) -> Optional[QScreen]:
        screens = QGuiApplication.screens()
        if not screens:
            return None
        best_screen: Optional[QScreen] = None
        best_area = 0
        for screen in screens:
            try:
                native_geometry = screen.nativeGeometry()
            except AttributeError:
                native_geometry = screen.geometry()
            area = rect.intersected(native_geometry)
            intersection_area = max(area.width(), 0) * max(area.height(), 0)
            if intersection_area > best_area:
                best_area = intersection_area
                best_screen = screen
        if best_screen is not None:
            return best_screen
        return QGuiApplication.primaryScreen()

    def _screen_info_for_native_rect(self, rect: Tuple[int, int, int, int]) -> Optional[ScreenInfo]:
        native_rect = QRect(*rect)
        screen = self._screen_for_native_rect(native_rect)
        if screen is None:
            return None
        try:
            native_geometry = screen.nativeGeometry()
        except AttributeError:
            native_geometry = screen.geometry()
        logical_geometry = screen.geometry()
        device_ratio = 1.0
        screen_name = screen.name() or screen.manufacturer() or "unknown"
        try:
            device_ratio = float(screen.devicePixelRatio())
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _CLIENT_LOGGER.debug("devicePixelRatio unavailable for screen %s; defaulting to 1.0 (%s)", screen_name, exc)
            device_ratio = 1.0
        if device_ratio <= 0.0:
            device_ratio = 1.0
        return ScreenInfo(
            name=screen_name,
            logical_geometry=(
                logical_geometry.x(),
                logical_geometry.y(),
                logical_geometry.width(),
                logical_geometry.height(),
            ),
            native_geometry=(
                native_geometry.x(),
                native_geometry.y(),
                native_geometry.width(),
                native_geometry.height(),
            ),
            device_ratio=device_ratio,
        )

    def _describe_screen(self, screen) -> str:
        if screen is None:
            return "unknown"
        try:
            geometry = screen.geometry()
            return f"{screen.name()} {geometry.width()}x{geometry.height()}@({geometry.x()},{geometry.y()})"
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _CLIENT_LOGGER.debug("Failed to describe screen %r: %s", screen, exc)
            return str(screen)
        except Exception as exc:  # pragma: no cover - unexpected Qt errors
            _CLIENT_LOGGER.warning("Unexpected error describing screen %r: %s", screen, exc)
            return str(screen)

    def _sync_base_dimensions_to_widget(self) -> None:
        width_px, height_px = self._current_physical_size()
        self._base_width = max(int(round(width_px)), 1)
        self._base_height = max(int(round(height_px)), 1)

    def _classify_geometry_override(
        self,
        tracker_tuple: Tuple[int, int, int, int],
        actual_tuple: Tuple[int, int, int, int],
    ) -> str:
        """Identify whether a WM override stems from internal layout constraints."""
        try:
            min_hint = self.minimumSizeHint()
        except Exception:
            min_hint = None
        try:
            size_hint = self.sizeHint()
        except Exception:
            size_hint = None
        return self._compute_geometry_override_classification(tracker_tuple, actual_tuple, min_hint, size_hint)

    @staticmethod
    def _compute_geometry_override_classification(
        tracker_tuple: Tuple[int, int, int, int],
        actual_tuple: Tuple[int, int, int, int],
        min_hint: Optional[QSize],
        size_hint: Optional[QSize],
        *,
        tolerance: int = 2,
    ) -> str:
        tracker_width = tracker_tuple[2]
        tracker_height = tracker_tuple[3]
        actual_width = actual_tuple[2]
        actual_height = actual_tuple[3]
        width_diff = actual_width - tracker_width
        height_diff = actual_height - tracker_height

        if width_diff < 0 or height_diff < 0:
            return "wm_intervention"

        min_width = max(min_hint.width() if isinstance(min_hint, QSize) else 0, 0)
        min_height = max(min_hint.height() if isinstance(min_hint, QSize) else 0, 0)
        size_width = max(size_hint.width() if isinstance(size_hint, QSize) else 0, 0)
        size_height = max(size_hint.height() if isinstance(size_hint, QSize) else 0, 0)

        within_preferred_width = size_width <= 0 or actual_width <= size_width + tolerance
        within_preferred_height = size_height <= 0 or actual_height <= size_height + tolerance

        width_constrained = (
            width_diff > 0
            and min_width > 0
            and actual_width >= (min_width - tolerance)
            and within_preferred_width
        )
        height_constrained = (
            height_diff > 0
            and min_height > 0
            and actual_height >= (min_height - tolerance)
            and within_preferred_height
        )

        if width_constrained or height_constrained:
            return "layout"
        return "wm_intervention"
