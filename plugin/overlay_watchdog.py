"""Watchdog responsible for launching and supervising the overlay client process."""
from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Optional, Sequence

LogFunc = Callable[[str], None]


class OverlayWatchdog:
    """Launches the overlay as a subprocess and restarts it if it crashes."""

    def __init__(
        self,
        command: Sequence[str],
        working_dir: Path,
        log: LogFunc,
        max_restarts: int = 3,
        restart_window: float = 60.0,
    ) -> None:
        self._command = list(command)
        self._working_dir = working_dir
        self._log = log
        self._max_restarts = max_restarts
        self._restart_window = restart_window

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._restart_times: Deque[float] = deque(maxlen=max_restarts)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="EDMCOverlay-Watchdog", daemon=True)
        self._thread.start()
        self._log("Overlay watchdog started")

    def stop(self) -> None:
        self._stop_event.set()
        self._terminate_process()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._log("Overlay watchdog stopped")

    # Internal helpers -----------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._process or self._process.poll() is not None:
                if not self._can_restart():
                    self._log("Overlay restart limit reached; watchdog giving up")
                    return
                self._spawn_overlay()
            self._wait_for_exit(interval=1.0)

    def _can_restart(self) -> bool:
        now = time.monotonic()
        self._restart_times.append(now)
        if len(self._restart_times) < self._max_restarts:
            return True
        window = now - self._restart_times[0]
        return window > self._restart_window

    def _spawn_overlay(self) -> None:
        try:
            proc = subprocess.Popen(
                self._command,
                cwd=str(self._working_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            self._log("Overlay executable not found; watchdog disabled")
            self._stop_event.set()
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"Failed to launch overlay: {exc}")
            time.sleep(5.0)
            return
        self._process = proc
        self._log("Overlay process started")

    def _wait_for_exit(self, interval: float) -> None:
        if not self._process:
            time.sleep(interval)
            return
        try:
            self._process.wait(timeout=interval)
        except subprocess.TimeoutExpired:
            return
        self._log("Overlay process exited")
        self._process = None

    def _terminate_process(self) -> None:
        if not self._process:
            return
        try:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5.0)
        except Exception:
            pass
        finally:
            self._process = None
