from __future__ import annotations

import logging
import threading
from overlay_plugin.prefs_services import PrefsWorker


class DummyLifecycle:
    def __init__(self) -> None:
        self.tracked = []
        self.untracked = []

    def track_thread(self, thread: threading.Thread) -> None:
        self.tracked.append(thread)

    def untrack_thread(self, thread: threading.Thread) -> None:
        self.untracked.append(thread)


def test_prefs_worker_start_stop_tracks_threads():
    lifecycle = DummyLifecycle()
    worker = PrefsWorker(lifecycle, logging.getLogger("test-prefs-worker"))

    worker.start()
    assert lifecycle.tracked
    assert lifecycle.tracked[0].is_alive()

    worker.stop()
    assert lifecycle.untracked


def test_submit_wait_runs_task():
    lifecycle = DummyLifecycle()
    worker = PrefsWorker(lifecycle, logging.getLogger("test-prefs-submit"))
    worker.start()

    result = worker.submit(lambda: "ok", wait=True, timeout=1.0)
    assert result == "ok"

    worker.stop()


def test_submit_timeout_runs_inline_without_worker():
    lifecycle = DummyLifecycle()
    worker = PrefsWorker(lifecycle, logging.getLogger("test-prefs-timeout"))

    result = worker.submit(lambda: "inline", wait=True, timeout=0.0)
    assert result == "inline"
    # No worker started; stop should be a no-op
    worker.stop()


def test_task_executes_in_background():
    lifecycle = DummyLifecycle()
    worker = PrefsWorker(lifecycle, logging.getLogger("test-prefs-bg"))
    worker.start()

    evt = threading.Event()
    worker.submit(lambda: evt.set(), wait=False)

    assert evt.wait(timeout=1.0)
    worker.stop()
