from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from overlay_client.data_client import OverlayDataClient


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_send_cli_payload_queues_when_loop_absent(qt_app):
    client = OverlayDataClient(Path("dummy_port.json"))
    assert client.send_cli_payload({"foo": "bar"}) is True
    assert client._pending.qsize() == 1  # type: ignore[attr-defined]


def test_send_cli_payload_overflow_returns_false(qt_app):
    client = OverlayDataClient(Path("dummy_port.json"))
    # Fill pending queue
    for _ in range(client._pending.maxsize):  # type: ignore[attr-defined]
        assert client.send_cli_payload({"x": 1})
    assert client.send_cli_payload({"overflow": True}) is False


def test_send_cli_payload_uses_running_loop(qt_app):
    class EagerLoop:
        def __init__(self) -> None:
            self.calls = []

        def call_soon_threadsafe(self, fn, *args, **kwargs):
            self.calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

    class RecordingQueue:
        def __init__(self) -> None:
            self.items = []

        def put_nowait(self, payload):
            self.items.append(payload)

    client = OverlayDataClient(Path("dummy_port.json"))
    loop = EagerLoop()
    outgoing = RecordingQueue()
    client._loop = loop  # type: ignore[attr-defined]
    client._outgoing = outgoing  # type: ignore[attr-defined]

    assert client.send_cli_payload({"hello": "world"}) is True
    assert outgoing.items == [{"hello": "world"}]
    # Pending queue should remain empty when loop/outgoing are available.
    assert client._pending.qsize() == 0  # type: ignore[attr-defined]
