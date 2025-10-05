"""Overlay watchdog that launches and supervises the PyQt overlay client."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional

try:
    import psutil
except ImportError:  # pragma: no cover - dependency handled at runtime
    psutil = None  # type: ignore[assignment]


MAX_RESTARTS = 5
RESTART_BACKOFF_SECONDS = 5


def _log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    try:
        from config import config  # type: ignore

        config.log(f"[{timestamp}] [ModernOverlay] {message}")
    except Exception:
        print(f"[{timestamp}] [ModernOverlay] {message}")


class OverlayWatchdog:
    """Monitor a subprocess and restart it if it exits unexpectedly."""

    def __init__(self, command: Iterable[str], working_dir: Path) -> None:
        self.command: List[str] = list(command)
        self.working_dir = working_dir
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._restart_attempts = 0

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not psutil:
            _log("psutil not available; watchdog disabled")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ModernOverlay-Watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._terminate_process()
        self._thread = None

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if self._process is None or self._process.poll() is not None:
                if self._restart_attempts >= MAX_RESTARTS:
                    _log("Watchdog reached max restarts; giving up")
                    break
                self._launch_process()
            self._check_process_health()
            time.sleep(1.0)
        self._terminate_process()

    def _launch_process(self) -> None:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        try:
            self._process = subprocess.Popen(
                self.command,
                cwd=str(self.working_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._restart_attempts += 1
            _log(f"Started overlay client (attempt {self._restart_attempts}/{MAX_RESTARTS})")
        except Exception as exc:
            _log(f"Failed to start overlay client: {exc}")
            time.sleep(RESTART_BACKOFF_SECONDS)

    def _check_process_health(self) -> None:
        if not self._process or psutil is None:
            return
        try:
            proc = psutil.Process(self._process.pid)
            if not proc.is_running():
                _log("Overlay process not running; scheduling restart")
                self._terminate_process()
                time.sleep(RESTART_BACKOFF_SECONDS)
        except psutil.NoSuchProcess:
            self._terminate_process()
        except Exception as exc:
            _log(f"Watchdog health check failed: {exc}")

    def _terminate_process(self) -> None:
        if not self._process:
            return
        try:
            if self._process.poll() is None:
                _log("Terminating overlay client")
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    _log("Overlay unresponsive; killing")
                    self._process.kill()
            if self._process.stdout:
                self._process.stdout.close()
            if self._process.stderr:
                self._process.stderr.close()
        finally:
            self._process = None
