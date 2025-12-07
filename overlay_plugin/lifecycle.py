from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Set


class LifecycleTracker:
    """Tracks threads/handles and provides deterministic teardown helpers."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._lock = threading.Lock()
        self._threads: Set[threading.Thread] = set()
        self._handles: Set[Any] = set()

    @property
    def threads(self) -> Set[threading.Thread]:
        return self._threads

    @property
    def handles(self) -> Set[Any]:
        return self._handles

    def track_thread(self, thread: threading.Thread) -> None:
        if thread is None:
            return
        with self._lock:
            self._threads.add(thread)

    def untrack_thread(self, thread: Optional[threading.Thread]) -> None:
        if thread is None:
            return
        with self._lock:
            self._threads.discard(thread)

    def track_handle(self, handle: Any) -> None:
        if handle is None:
            return
        with self._lock:
            self._handles.add(handle)

    def untrack_handle(self, handle: Any) -> None:
        if handle is None:
            return
        with self._lock:
            self._handles.discard(handle)

    def join_thread(self, thread: Optional[threading.Thread], name: Optional[str], *, timeout: float = 2.0) -> None:
        if thread is None:
            return
        thread.join(timeout=timeout)
        if thread.is_alive():
            self._logger.warning("Thread %s did not exit cleanly within %.1fs", name or thread.name, timeout)
        self.untrack_thread(thread)

    def log_state(self, label: str) -> None:
        with self._lock:
            live_threads = [thr.name or repr(thr) for thr in self._threads if thr.is_alive()]
            handles = list(self._handles)
        if live_threads or handles:
            self._logger.debug("Tracked resources %s: threads=%s handles=%s", label, live_threads, handles)
