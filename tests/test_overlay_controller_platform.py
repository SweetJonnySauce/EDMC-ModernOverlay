from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import importlib.util
import sys


def _load_overlay_controller_module():
    root = Path(__file__).resolve().parents[1]
    oc_dir = root / "overlay_controller"
    sys.path.insert(0, str(oc_dir))
    path = oc_dir / "overlay_controller.py"
    spec = importlib.util.spec_from_file_location("overlay_controller", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


oc = _load_overlay_controller_module()


def _set_platform(monkeypatch, name: str) -> None:
    monkeypatch.setattr(oc.platform, "system", lambda: name)


def test_get_windows_primary_bounds(monkeypatch):
    _set_platform(monkeypatch, "Windows")
    user32_calls: list[tuple[str, tuple[int, ...]]] = []

    class DummyUser32:
        def SetProcessDPIAware(self):
            user32_calls.append(("dpi", ()))

        def GetSystemMetrics(self, idx: int) -> int:
            user32_calls.append(("metrics", (idx,)))
            return {0: 1920, 1: 1080}[idx]

    dummy = SimpleNamespace(windll=SimpleNamespace(user32=DummyUser32()))
    monkeypatch.setitem(sys.modules, "ctypes", dummy)

    result = oc.OverlayConfigApp._get_windows_primary_bounds(SimpleNamespace())

    assert result == (0, 0, 1920, 1080)
    assert any(call[0] == "dpi" for call in user32_calls)
    assert ("metrics", (0,)) in user32_calls and ("metrics", (1,)) in user32_calls


def test_get_xrandr_primary_bounds(monkeypatch):
    _set_platform(monkeypatch, "Linux")
    stdout = "HDMI-0 connected primary 2560x1440+1920+0 (normal left inverted right x axis y axis)\n"
    monkeypatch.setattr(
        oc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=stdout),
    )

    result = oc.OverlayConfigApp._get_xrandr_primary_bounds(SimpleNamespace())

    assert result == (1920, 0, 2560, 1440)


def test_get_xrandr_primary_bounds_without_primary(monkeypatch):
    _set_platform(monkeypatch, "Linux")
    monkeypatch.setattr(
        oc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="DP-1 connected 1920x1080+0+0"),
    )

    result = oc.OverlayConfigApp._get_xrandr_primary_bounds(SimpleNamespace())

    assert result is None


def test_raise_on_windows_invokes_topmost(monkeypatch):
    _set_platform(monkeypatch, "Windows")
    user32_ops: list[str] = []

    class DummyUser32:
        def GetForegroundWindow(self):
            user32_ops.append("get_foreground")
            return 1

        def GetWindowThreadProcessId(self, _hwnd, _):
            user32_ops.append("get_tid")
            return 10

        def AttachThreadInput(self, *_args):
            user32_ops.append("attach")
            return True

        def ShowWindow(self, *_args):
            user32_ops.append("show")

        def BringWindowToTop(self, *_args):
            user32_ops.append("bring_to_top")

        def SetForegroundWindow(self, *_args):
            user32_ops.append("set_fg")

        def SetActiveWindow(self, *_args):
            user32_ops.append("set_active")

        def SetFocus(self, *_args):
            user32_ops.append("set_focus")

        def SetWindowPos(self, *_args):
            user32_ops.append("set_pos")

    class DummyKernel32:
        def GetCurrentThreadId(self):
            return 20

    dummy_ctypes = SimpleNamespace(
        windll=SimpleNamespace(user32=DummyUser32(), kernel32=DummyKernel32())
    )
    monkeypatch.setitem(sys.modules, "ctypes", dummy_ctypes)

    attribute_calls: list[tuple[str, bool]] = []

    class DummyWindow:
        def attributes(self, key, value):
            attribute_calls.append((key, value))

        def after(self, _delay, cb):
            cb()

        def winfo_id(self):
            return 123

    oc.OverlayConfigApp._raise_on_windows(DummyWindow())

    assert ("-topmost", True) in attribute_calls
    assert ("-topmost", False) in attribute_calls
    assert {"get_foreground", "get_tid", "show", "set_pos"} <= set(user32_ops)


def test_focus_on_show_windows(monkeypatch):
    _set_platform(monkeypatch, "Windows")
    calls: list[str] = []

    class DummyWindow:
        def focus_force(self):
            calls.append("force")

        def after_idle(self, cb):
            cb()

    oc.OverlayConfigApp._focus_on_show(DummyWindow())

    assert calls == ["force", "force"]


def test_focus_on_show_linux(monkeypatch):
    _set_platform(monkeypatch, "Linux")
    calls: list[str] = []

    class DummyWindow:
        def focus_set(self):
            calls.append("set")

        def after_idle(self, cb):
            cb()

    oc.OverlayConfigApp._focus_on_show(DummyWindow())

    assert calls == ["set", "set"]


def test_capture_and_restore_foreground_window(monkeypatch):
    _set_platform(monkeypatch, "Windows")
    user32_ops: list[tuple[str, object] | str] = []

    class DummyUser32:
        def GetForegroundWindow(self):
            user32_ops.append("get_fg")
            return 42

        def GetWindowThreadProcessId(self, hwnd, _):
            user32_ops.append(("get_tid", hwnd))
            return 10

        def AttachThreadInput(self, _from, _to, attach):
            user32_ops.append(("attach", bool(attach)))
            return True

        def SetForegroundWindow(self, hwnd):
            user32_ops.append(("set_fg", hwnd))

        def SetActiveWindow(self, hwnd):
            user32_ops.append(("set_active", hwnd))

        def SetFocus(self, hwnd):
            user32_ops.append(("set_focus", hwnd))

    class DummyKernel32:
        def GetCurrentThreadId(self):
            return 20

    dummy_ctypes = SimpleNamespace(
        windll=SimpleNamespace(user32=DummyUser32(), kernel32=DummyKernel32())
    )
    monkeypatch.setitem(sys.modules, "ctypes", dummy_ctypes)

    class DummyWindow:
        def __init__(self):
            self._previous_foreground_hwnd = None

        def winfo_id(self):
            return 99

    window = DummyWindow()

    oc.OverlayConfigApp._capture_foreground_window(window)
    assert window._previous_foreground_hwnd == 42

    oc.OverlayConfigApp._restore_foreground_window(window)
    assert window._previous_foreground_hwnd is None
    assert ("set_fg", 42) in user32_ops
    assert ("attach", True) in user32_ops
    assert ("attach", False) in user32_ops


def test_restore_foreground_noop_on_linux(monkeypatch):
    _set_platform(monkeypatch, "Linux")
    window = SimpleNamespace(_previous_foreground_hwnd=55)

    oc.OverlayConfigApp._restore_foreground_window(window)

    assert window._previous_foreground_hwnd is None


def test_force_render_override_restores_previous(tmp_path):
    settings_path = tmp_path / "overlay_settings.json"
    settings_path.write_text('{"force_render": false, "allow_force_render_release": false}', encoding="utf-8")
    mgr = oc._ForceRenderOverrideManager(tmp_path)

    mgr.activate()
    data = settings_path.read_text(encoding="utf-8")
    assert '"force_render": true' in data
    assert '"allow_force_render_release": true' in data

    mgr.deactivate()
    data = settings_path.read_text(encoding="utf-8")
    assert '"force_render": false' in data
    assert '"allow_force_render_release": false' in data
    assert not mgr._active


def test_center_on_screen_uses_primary_bounds(monkeypatch):
    dummy = SimpleNamespace()
    geometry_calls: list[str] = []

    def update_idletasks():
        geometry_calls.append("updated")

    def geometry(arg):
        geometry_calls.append(arg)

    def winfo_width():
        return 100

    def winfo_height():
        return 50

    def winfo_reqwidth():
        return 100

    def winfo_reqheight():
        return 50

    dummy.update_idletasks = update_idletasks
    dummy.geometry = geometry
    dummy.winfo_width = winfo_width
    dummy.winfo_height = winfo_height
    dummy.winfo_reqwidth = winfo_reqwidth
    dummy.winfo_reqheight = winfo_reqheight
    dummy._get_primary_screen_bounds = lambda: (10, 10, 200, 100)

    oc.OverlayConfigApp._center_on_screen(dummy)

    assert "100x50+60+35" in geometry_calls
