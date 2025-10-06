"""Watchdog responsible for launching and supervising the overlay client process."""
from __future__ import annotations

import shlex
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Optional, Sequence, Tuple

LogFunc = Callable[[str], None]


class OverlayWatchdog:
    """Launches the overlay as a subprocess and restarts it if it crashes."""

    def __init__(
        self,
        command: Sequence[str],
        working_dir: Path,
        log: LogFunc,
        debug_log: Optional[LogFunc] = None,
        capture_output: bool = False,
        max_restarts: int = 3,
        restart_window: float = 60.0,
    ) -> None:
        self._command = list(command)
        self._working_dir = working_dir
        self._log = log
        self._log_debug = debug_log or log
        self._capture_output = capture_output
        self._max_restarts = max_restarts
        self._restart_window = restart_window

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen[str]] = None
        self._restart_times: Deque[float] = deque(maxlen=max_restarts)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._debug(
            "Overlay watchdog starting; command=%s cwd=%s"
            % (self._format_command(), self._working_dir)
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="EDMCOverlay-Watchdog", daemon=True)
        self._thread.start()
        self._debug("Overlay watchdog started")

    def stop(self) -> bool:
        self._stop_event.set()
        process_terminated = self._terminate_process()
        thread_joined = True
        if self._thread:
            self._thread.join(timeout=5.0)
            thread_joined = not self._thread.is_alive()
        self._thread = None
        success = process_terminated and thread_joined
        if success:
            self._log("Overlay watchdog stopped")
        else:
            self._log("Overlay watchdog stop incomplete")
        return success

    # Internal helpers -----------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._process or self._process.poll() is not None:
                if not self._can_restart():
                    self._debug("Overlay restart limit reached; watchdog giving up")
                    return
                self._spawn_overlay()
            self._wait_for_exit(interval=1.0)

    def _can_restart(self) -> bool:
        now = time.monotonic()
        self._restart_times.append(now)
        if len(self._restart_times) < self._max_restarts:
            return True
        window = now - self._restart_times[0]
        if window <= self._restart_window:
            self._debug(
                "Overlay restart throttled: %d attempts within %.1fs"
                % (len(self._restart_times), window)
            )
        return window > self._restart_window

    def _spawn_overlay(self) -> None:
        self._debug("Launching overlay client: %s" % self._format_command())
        popen_kwargs = {
            "cwd": str(self._working_dir),
            "stdout": subprocess.PIPE if self._capture_output else subprocess.DEVNULL,
            "stderr": subprocess.PIPE if self._capture_output else subprocess.DEVNULL,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        }
        if self._capture_output:
            popen_kwargs.update(
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        try:
            proc = subprocess.Popen(
                self._command,
                **popen_kwargs,
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
        self._debug(f"Overlay process started (pid={proc.pid})")

    def _wait_for_exit(self, interval: float) -> None:
        proc = self._process
        if not proc:
            time.sleep(interval)
            return
        try:
            proc.wait(timeout=interval)
        except subprocess.TimeoutExpired:
            return
        pid = proc.pid if proc else "?"
        returncode = proc.returncode if proc else "?"
        stdout_data, stderr_data = self._collect_process_output(proc)
        self._debug(f"Overlay process exited (pid={pid}, returncode={returncode})")
        if self._capture_output and isinstance(returncode, int) and returncode != 0:
            self._log_failure_details(pid, returncode, stdout_data, stderr_data)
        self._process = None

    def _terminate_process(self) -> bool:
        if not self._process:
            return True
        proc = self._process
        terminated = True
        try:
            if proc.poll() is None:
                self._debug(f"Terminating overlay process (pid={proc.pid})")
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._debug(f"Killing unresponsive overlay process (pid={proc.pid})")
                    proc.kill()
                    proc.wait(timeout=5.0)
            else:
                self._debug(f"Overlay process already stopped (pid={proc.pid}, returncode={proc.returncode})")
            terminated = proc.poll() is not None
        except Exception:
            terminated = False
        finally:
            self._process = None
        return terminated

    def _format_command(self) -> str:
        try:
            return shlex.join(self._command)
        except Exception:
            return " ".join(self._command)

    def _debug(self, message: str) -> None:
        try:
            self._log_debug(message)
        except Exception:
            pass

    def _collect_process_output(self, proc: Optional[subprocess.Popen[str]]) -> Tuple[str, str]:
        if proc is None or not self._capture_output:
            return "", ""
        stdout_data = ""
        stderr_data = ""
        try:
            if proc.stdout is None and proc.stderr is None:
                return "", ""
            stdout_data, stderr_data = proc.communicate()
        except subprocess.TimeoutExpired:
            stdout_data, stderr_data = "", ""
        except Exception:
            stdout_data, stderr_data = "", ""
        return stdout_data or "", stderr_data or ""

    def _log_failure_details(self, pid: int, returncode: int, stdout_data: str, stderr_data: str) -> None:
        segments = [
            f"Command: {self._format_command()}",
            f"Working directory: {self._working_dir}",
            f"Return code: {returncode}",
        ]
        stdout_tail = self._tail_output(stdout_data)
        stderr_tail = self._tail_output(stderr_data)
        if stdout_tail:
            segments.append("stdout tail:\n" + stdout_tail)
        if stderr_tail:
            segments.append("stderr tail:\n" + stderr_tail)
        if len(segments) == 3:
            segments.append("No stdout/stderr output captured.")
        detail = "\n".join(segments)
        self._debug(f"Overlay process failure diagnostics (pid={pid}):\n{detail}")

    def _tail_output(self, text: str, limit: int = 1000) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        if len(stripped) <= limit:
            return stripped
        return stripped[-limit:]

    def set_capture_output(self, capture_output: bool) -> None:
        self._capture_output = capture_output
        self._debug(f"Capture output setting updated to {capture_output}")
