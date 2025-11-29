from __future__ import annotations

from overlay_client.overlay_client import OverlayWindow


class _StubFrame:
    def __init__(self, w: int, h: int) -> None:
        self._w = w
        self._h = h

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


def test_current_physical_size_defaults_ratio_and_logs(monkeypatch):
    logs = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    window = type(
        "Stub",
        (),
        {
            "frameGeometry": lambda self: _StubFrame(100, 50),
            "windowHandle": lambda self: type("WH", (), {"devicePixelRatio": lambda self: (_ for _ in ()).throw(RuntimeError("fail"))})(),
            "_current_physical_size": OverlayWindow._current_physical_size,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)

    width, height = window._current_physical_size()  # type: ignore[attr-defined]

    assert (width, height) == (100.0, 50.0)
    assert any("devicePixelRatio" in msg for msg in logs)


def test_viewport_state_defaults_ratio_and_logs(monkeypatch):
    logs = []

    def _debug(msg: str, *args) -> None:
        logs.append(msg % args if args else msg)

    window = type(
        "Stub",
        (),
        {
            "width": lambda self: 200,
            "height": lambda self: 100,
            "devicePixelRatioF": lambda self: (_ for _ in ()).throw(AttributeError("no dpr")),
            "_viewport_state": OverlayWindow._viewport_state,
        },
    )()
    monkeypatch.setattr("overlay_client.overlay_client._CLIENT_LOGGER.debug", _debug)

    state = window._viewport_state()  # type: ignore[attr-defined]

    assert state.device_ratio == 1.0
    assert any("devicePixelRatioF unavailable" in msg for msg in logs)
