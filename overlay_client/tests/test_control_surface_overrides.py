from __future__ import annotations

import sys
import types
from typing import Any, Optional

# Prefer real PyQt6; fall back to lightweight stubs only if unavailable (CI/headless).
try:  # pragma: no cover - exercised in environments with PyQt6 present
    from PyQt6 import QtCore as _QtCore  # noqa: F401
    from PyQt6 import QtGui as _QtGui  # noqa: F401
    from PyQt6 import QtWidgets as _QtWidgets  # noqa: F401
except Exception:  # pragma: no cover - lightweight stub path
    if "PyQt6" not in sys.modules:
        sys.modules["PyQt6"] = types.ModuleType("PyQt6")
    if "PyQt6.QtCore" not in sys.modules:
        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.Qt = types.SimpleNamespace(KeyboardModifier=types.SimpleNamespace(AltModifier=1))
        sys.modules["PyQt6.QtCore"] = qtcore
    if "PyQt6.QtGui" not in sys.modules:
        qtgui = types.ModuleType("PyQt6.QtGui")

        class _QFont:
            def __init__(self, *args, **kwargs) -> None:
                self._family = ""

            def family(self) -> str:
                return self._family

            def setFamilies(self, families):
                self._family = families[0] if families else ""

            def setFallbackFamilies(self, families):
                return

        class _QFontMetrics:
            def __init__(self, font) -> None:
                self._font = font

        qtgui.QFont = _QFont
        qtgui.QFontMetrics = _QFontMetrics
        qtgui.QGuiApplication = type(
            "QGuiApplication",
            (),
            {"primaryScreen": staticmethod(lambda: None), "screens": staticmethod(lambda: [])},
        )
        qtgui.QWindow = type(
            "QWindow",
            (),
            {"setFlag": lambda self, *args, **kwargs: None},
        )
        qtgui.QPainter = object
        sys.modules["PyQt6.QtGui"] = qtgui
    if "PyQt6.QtWidgets" not in sys.modules:
        qtwidgets = types.ModuleType("PyQt6.QtWidgets")
        qtwidgets.QApplication = type(
            "QApplication",
            (),
            {"queryKeyboardModifiers": staticmethod(lambda: 0)},
        )
        qtwidgets.QWidget = type(
            "QWidget",
            (),
            {"windowHandle": lambda self: None, "winId": lambda self: 0},
        )
        sys.modules["PyQt6.QtWidgets"] = qtwidgets

from overlay_client.control_surface import ControlSurfaceMixin


class _StubFollowController:
    def __init__(self) -> None:
        self.reset_resume_window_calls = 0

    def reset_resume_window(self) -> None:
        self.reset_resume_window_calls += 1


class _StubWindow(ControlSurfaceMixin):
    def __init__(self, *, follow_enabled: bool = True, has_tracker: bool = True) -> None:
        self._physical_clamp_overrides = {}
        self._follow_controller = _StubFollowController()
        self._follow_enabled = follow_enabled
        self._window_tracker = object() if has_tracker else None
        self._last_follow_state: Optional[tuple[Any, ...]] = ("state",)
        self.refresh_called = 0
        self.apply_called = 0
        self.update_called = 0

    def _refresh_follow_geometry(self) -> None:
        self.refresh_called += 1

    def _apply_follow_state(self, state) -> None:  # pragma: no cover - simple counter
        self.apply_called += 1

    def update(self) -> None:  # pragma: no cover - simple counter
        self.update_called += 1


def test_set_physical_clamp_overrides_applies_and_refreshes() -> None:
    window = _StubWindow()

    window.set_physical_clamp_overrides({"DisplayPort-2": 4.0})

    assert window._physical_clamp_overrides == {"DisplayPort-2": 3.0}
    assert window._follow_controller.reset_resume_window_calls == 1
    assert window.refresh_called == 1
    assert window.apply_called == 0
    assert window.update_called == 0


def test_set_physical_clamp_overrides_no_change_noops() -> None:
    window = _StubWindow()
    window.set_physical_clamp_overrides({"DisplayPort-2": 1.25})

    window.set_physical_clamp_overrides({"DisplayPort-2": 1.25})

    assert window._follow_controller.reset_resume_window_calls == 1
    assert window.refresh_called == 1


def test_set_physical_clamp_overrides_empty_map_noops() -> None:
    window = _StubWindow()

    window.set_physical_clamp_overrides({})

    assert window._physical_clamp_overrides == {}
    assert window._follow_controller.reset_resume_window_calls == 0
    assert window.refresh_called == 0


def test_set_physical_clamp_overrides_applies_when_follow_disabled() -> None:
    window = _StubWindow(follow_enabled=False, has_tracker=False)

    window.set_physical_clamp_overrides({"HDMI-0": 0.75})

    assert window._physical_clamp_overrides == {"HDMI-0": 0.75}
    assert window._follow_controller.reset_resume_window_calls == 1
    assert window.refresh_called == 0
    assert window.apply_called == 1
    assert window.update_called == 0


def test_set_physical_clamp_overrides_ignores_invalid_values() -> None:
    window = _StubWindow()

    window.set_physical_clamp_overrides({"DisplayPort-2": 0, "HDMI-0": float("nan")})

    assert window._physical_clamp_overrides == {}
    assert window._follow_controller.reset_resume_window_calls == 0
    assert window.refresh_called == 0
