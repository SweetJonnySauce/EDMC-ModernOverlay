from __future__ import annotations

import logging

from overlay_plugin import runtime_services


class _DummyBroadcaster:
    def __init__(self, should_start: bool = True):
        self.should_start = should_start
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return self.should_start

    def stop(self) -> None:
        self.stopped = True


class _DummyWatchdog:
    def __init__(self, stop_result: bool = True):
        self.stop_result = stop_result
        self.stopped = False

    def stop(self) -> bool:
        self.stopped = True
        return self.stop_result


class _DummyRuntime:
    def __init__(self, *, legacy_active: bool = False, broadcaster_ok: bool = True, watchdog_ok: bool = True):
        self._legacy_active = legacy_active
        self.deleted_port = False
        self.wrote_port = False
        self.broadcaster = _DummyBroadcaster(should_start=broadcaster_ok)
        self.watchdog = _DummyWatchdog(stop_result=True) if watchdog_ok else None
        self.watchdog_started = False
        self.untracked = []

    def _legacy_overlay_active(self) -> bool:
        return self._legacy_active

    def _delete_port_file(self) -> None:
        self.deleted_port = True

    def _write_port_file(self) -> None:
        self.wrote_port = True

    def _start_watchdog(self) -> bool:
        if self.watchdog is None:
            return False
        self.watchdog_started = True
        return True


def test_start_runtime_services_handles_legacy_and_stop(monkeypatch):
    runtime = _DummyRuntime(legacy_active=True)
    logger = logging.getLogger("test")

    result = runtime_services.start_runtime_services(runtime, logger, lambda msg: None)

    assert result is False
    assert runtime.deleted_port is True
    assert runtime.broadcaster.started is False


def test_start_runtime_services_handles_broadcaster_failure():
    runtime = _DummyRuntime(broadcaster_ok=False)
    logger = logging.getLogger("test")

    result = runtime_services.start_runtime_services(runtime, logger, lambda msg: None)

    assert result is False
    assert runtime.deleted_port is True
    assert runtime.broadcaster.started is True
    assert runtime.watchdog_started is False


def test_start_runtime_services_handles_watchdog_failure():
    runtime = _DummyRuntime(watchdog_ok=False)
    logger = logging.getLogger("test")

    result = runtime_services.start_runtime_services(runtime, logger, lambda msg: None)

    assert result is False
    assert runtime.deleted_port is True
    assert runtime.broadcaster.started is True
    assert runtime.broadcaster.stopped is True


def test_start_runtime_services_success_path():
    runtime = _DummyRuntime()
    logger = logging.getLogger("test")

    result = runtime_services.start_runtime_services(runtime, logger, lambda msg: None)

    assert result is True
    assert runtime.broadcaster.started is True
    assert runtime.watchdog_started is True
    assert runtime.wrote_port is True


def test_stop_runtime_services_orders_teardown():
    runtime = _DummyRuntime()
    logger = logging.getLogger("test")
    watchdog = _DummyWatchdog()
    runtime.watchdog = watchdog
    runtime.deleted_port = False

    runtime_services.stop_runtime_services(runtime, logger, runtime.untracked.append)

    assert watchdog.stopped is True
    assert runtime.broadcaster.stopped is True
    assert runtime.deleted_port is True
    assert runtime.untracked == [watchdog, runtime.broadcaster]
