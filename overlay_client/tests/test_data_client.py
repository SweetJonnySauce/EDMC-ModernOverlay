import asyncio
import logging
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from overlay_client.data_client import OverlayDataClient


@pytest.fixture(scope="module")
def qt_app():
    # Force Qt to run headless for CI/CLI test runs.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


def test_send_cli_payload_logs_loop_failure(monkeypatch, qt_app):
    class FailingLoop:
        def call_soon_threadsafe(self, fn, *args, **kwargs):
            raise RuntimeError("loop closed")

    class DummyQueue:
        def put_nowait(self, payload):
            return None

    client = OverlayDataClient(Path("dummy_port.json"))
    client._loop = FailingLoop()  # type: ignore[attr-defined]
    client._outgoing = DummyQueue()  # type: ignore[attr-defined]

    logger = logging.getLogger("EDMC.ModernOverlay.Client.DataClient")
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    logger.addHandler(handler)
    try:
        assert client.send_cli_payload({"hello": "world"}) is True
    finally:
        logger.removeHandler(handler)

    assert client._pending.qsize() == 1  # type: ignore[attr-defined]
    assert any("Failed to enqueue CLI payload" in record.getMessage() for record in records)


def test_flush_outgoing_logs_write_failure(qt_app):
    class BrokenWriter:
        def write(self, data):
            raise ConnectionError("boom")

        async def drain(self):
            return None

    async def _run():
        queue_ref: asyncio.Queue = asyncio.Queue()
        await queue_ref.put({"foo": "bar"})
        await queue_ref.put(None)

        client = OverlayDataClient(Path("dummy_port.json"))

        logger = logging.getLogger("EDMC.ModernOverlay.Client.DataClient")
        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger.addHandler(handler)
        try:
            await client._flush_outgoing(BrokenWriter(), queue_ref)
        finally:
            logger.removeHandler(handler)
        return records

    log_records = asyncio.run(_run())

    assert any("Failed to write outgoing payload" in record.getMessage() for record in log_records)
