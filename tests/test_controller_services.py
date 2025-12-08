from __future__ import annotations

import logging
import threading

from overlay_plugin import controller_services


class _DummyProcess:
    def __init__(self, pid: int = 1234, exit_code: int = 0, capture: bool = False):
        self.pid = pid
        self._exit_code = exit_code
        self.wait_called = False
        self.communicated = False
        self._capture = capture

    def wait(self) -> int:
        self.wait_called = True
        return self._exit_code

    def communicate(self):
        self.communicated = True
        return ("", "")

    def poll(self):
        return None


class _DummyLifecycle:
    def __init__(self):
        self.tracked = []
        self.untracked = []

    def track_handle(self, handle):
        self.tracked.append(handle)

    def untrack_handle(self, handle):
        self.untracked.append(handle)


class _DummyControllerRuntime:
    def __init__(self):
        self._controller_launch_lock = threading.Lock()
        self._controller_launch_thread = None
        self._controller_process = None
        self._controller_status_id = "overlay-controller-status"
        self._controller_pid_path = None
        self._last_override_reload_nonce = None
        self._active_notice = False
        self._cleared = False
        self._emit_fail = False
        self._capture = False
        self._lifecycle = _DummyLifecycle()

    def _controller_python_command(self, env):
        return ["python"]

    def _build_overlay_environment(self):
        return {}

    def _controller_countdown(self):
        return

    def _spawn_overlay_controller_process(self, python_command, launch_env, capture_output: bool):
        return _DummyProcess(capture=self._capture)

    def _emit_controller_active_notice(self):
        self._active_notice = True

    def _emit_controller_message(self, text: str, ttl=None, persistent: bool = False):
        self._emit_fail = True

    def _clear_controller_message(self):
        self._cleared = True

    def _format_controller_output(self, stdout: str, stderr: str) -> str:
        return f"stdout={stdout} stderr={stderr}"

    def _read_controller_pid_file(self):
        return None

    def _cleanup_controller_pid_file(self):
        self._cleanup_called = True

    def _overlay_controller_active(self) -> bool:
        return False

    def _capture_enabled(self) -> bool:
        return self._capture


def test_controller_launch_sequence_success():
    runtime = _DummyControllerRuntime()
    logger = logging.getLogger("test")

    controller_services.controller_launch_sequence(runtime, logger)

    assert runtime._controller_process is None
    assert runtime._active_notice is True
    assert runtime._cleared is True
    assert runtime._lifecycle.tracked  # process was tracked


def test_controller_launch_sequence_failure_sets_thread_none(monkeypatch):
    runtime = _DummyControllerRuntime()
    runtime._controller_launch_thread = object()
    logger = logging.getLogger("test")

    def _raise(_env):
        raise RuntimeError("boom")

    runtime._controller_python_command = _raise  # type: ignore[assignment]

    controller_services.controller_launch_sequence(runtime, logger)

    assert runtime._controller_launch_thread is None
    assert runtime._emit_fail is True


def test_terminate_controller_process_uses_os_kill(monkeypatch):
    runtime = _DummyControllerRuntime()
    process = _DummyProcess()
    runtime._controller_process = process
    runtime._controller_pid_path = None
    logger = logging.getLogger("test")
    called = {}

    def fake_cleanup():
        called["cleanup"] = True

    runtime._cleanup_controller_pid_file = fake_cleanup  # type: ignore[assignment]

    controller_services.terminate_controller_process(runtime, logger)

    assert called.get("cleanup") is True
    assert runtime._controller_process is None
    assert runtime._lifecycle.untracked == [process]
