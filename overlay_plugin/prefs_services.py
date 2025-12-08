from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional


class PrefsWorker:
    """Background preference worker that mirrors load.py behavior without import-time side effects."""

    def __init__(self, lifecycle, logger) -> None:
        self._queue: "queue.Queue[Optional[Callable[[], Any]]]" = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._lifecycle = lifecycle
        self._logger = logger

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        worker = threading.Thread(target=self._loop, name="ModernOverlayPrefs", daemon=True)
        self._worker = worker
        self._lifecycle.track_thread(worker)
        worker.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        worker = self._worker
        if worker:
            worker.join(timeout=2.0)
            if worker.is_alive():
                self._logger.warning("Thread %s did not exit cleanly within %.1fs", worker.name, 2.0)
        self._lifecycle.untrack_thread(worker)
        self._worker = None

    def submit(self, func: Callable[[], Any], *, wait: bool = False, timeout: Optional[float] = 2.0) -> Any:
        if not wait:
            self._queue.put(func)
            return None
        done = threading.Event()
        outcome: dict[str, Any] = {}

        def _wrapper() -> None:
            try:
                outcome["value"] = func()
            except Exception as exc:
                outcome["error"] = exc
            finally:
                done.set()

        self._queue.put(_wrapper)
        if not done.wait(timeout):
            self._logger.debug("Preference worker timeout; running task inline")
            return func()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                break
            try:
                task()
            except Exception as exc:
                self._logger.debug("Preference task failed: %s", exc, exc_info=exc)
