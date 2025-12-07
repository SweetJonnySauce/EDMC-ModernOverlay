from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional, Protocol


class _ControllerRuntime(Protocol):  # type: ignore[name-defined]
    _controller_launch_lock: object
    _controller_launch_thread: Optional[object]
    _controller_process: Optional[subprocess.Popen]
    _controller_status_id: str
    _controller_pid_path: Path
    _last_override_reload_nonce: Optional[str]
    _lifecycle: object

    def _overlay_controller_launch_sequence(self) -> None: ...
    def _controller_python_command(self, overlay_env: dict[str, str]) -> list[str]: ...
    def _build_overlay_environment(self) -> dict[str, str]: ...
    def _controller_countdown(self) -> None: ...
    def _spawn_overlay_controller_process(
        self, python_command: list[str], launch_env: dict[str, str], capture_output: bool
    ) -> subprocess.Popen: ...
    def _emit_controller_active_notice(self) -> None: ...
    def _emit_controller_message(self, text: str, ttl: Optional[float] = None, persistent: bool = False) -> None: ...
    def _clear_controller_message(self) -> None: ...
    def _format_controller_output(self, stdout: str, stderr: str) -> str: ...
    def _read_controller_pid_file(self) -> Optional[int]: ...
    def _cleanup_controller_pid_file(self) -> None: ...
    def _overlay_controller_active(self) -> bool: ...
    def _capture_enabled(self) -> bool: ...


def launch_controller(runtime: _ControllerRuntime, logger: logging.Logger) -> None:
    with runtime._controller_launch_lock:
        if runtime._controller_launch_thread and runtime._controller_launch_thread.is_alive():
            raise RuntimeError("Overlay Controller launch already in progress.")
        if runtime._controller_process and runtime._controller_process.poll() is None:
            raise RuntimeError("Overlay Controller is already running.")
        logger.debug("Overlay Controller launch requested; preparing launch thread.")
        thread = threading.Thread(
            target=runtime._overlay_controller_launch_sequence,
            name="OverlayControllerLaunch",
            daemon=True,
        )
        runtime._controller_launch_thread = thread
    thread.start()


def controller_launch_sequence(runtime: _ControllerRuntime, logger: logging.Logger) -> None:
    try:
        launch_env = runtime._build_overlay_environment()
        python_command = runtime._controller_python_command(launch_env)
        logger.debug("Overlay Controller launch sequence starting with interpreter=%s", python_command[0])
        for key in ("TCL_LIBRARY", "TK_LIBRARY"):
            if key in launch_env:
                logger.debug("Removing %s from controller environment to avoid Tcl/Tk conflicts", key)
                launch_env.pop(key, None)
        capture_output = runtime._capture_enabled()
        runtime._controller_countdown()
        process = runtime._spawn_overlay_controller_process(python_command, launch_env, capture_output=capture_output)
    except Exception as exc:
        logger.error("Overlay Controller launch failed: %s", exc, exc_info=exc)
        runtime._emit_controller_message(f"Overlay Controller launch failed: {exc}", ttl=6.0)
        with runtime._controller_launch_lock:
            runtime._controller_launch_thread = None
        return

    with runtime._controller_launch_lock:
        runtime._controller_process = process
        runtime._controller_launch_thread = None
    logger.debug("Overlay Controller process handle stored (pid=%s)", getattr(process, "pid", "?"))
    if hasattr(runtime, "_lifecycle"):
        try:
            runtime._lifecycle.track_handle(process)  # type: ignore[attr-defined]
        except Exception:
            pass

    runtime._emit_controller_active_notice()

    try:
        exit_code: Optional[int] = None
        stdout: str = ""
        stderr: str = ""
        try:
            if runtime._capture_enabled():
                stdout, stderr = process.communicate()
                exit_code = process.returncode
            else:
                exit_code = process.wait()
        except Exception as exc:
            logger.debug("Overlay Controller process wait failed: %s", exc)
            try:
                exit_code = process.poll()
            except Exception:
                exit_code = None
        logger.debug("Overlay Controller process exited with code %s", exit_code)
        if exit_code not in (0, None) and runtime._capture_enabled():
            formatted_output = runtime._format_controller_output(stdout, stderr)
            logger.warning(
                "Overlay Controller exited abnormally (code=%s).\n%s",
                exit_code,
                formatted_output,
            )
    finally:
        with runtime._controller_launch_lock:
            runtime._controller_process = None
        runtime._clear_controller_message()


def terminate_controller_process(runtime: _ControllerRuntime, logger: logging.Logger) -> None:
    handle: Optional[subprocess.Popen] = None
    with runtime._controller_launch_lock:
        handle = runtime._controller_process
    pid_from_file = runtime._read_controller_pid_file()
    target_pid = None
    if handle and handle.poll() is None:
        target_pid = handle.pid
    elif pid_from_file and (handle is None or pid_from_file != getattr(handle, "pid", None)):
        target_pid = pid_from_file
    if target_pid is None:
        runtime._cleanup_controller_pid_file()
        return
    logger.debug("Attempting to stop Overlay Controller (pid=%s)", target_pid)
    terminated = False
    try:
        try:
            import psutil  # type: ignore
        except Exception:
            psutil = None  # type: ignore
        if psutil is not None:
            try:
                proc = psutil.Process(target_pid)
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
                terminated = True
            except psutil.NoSuchProcess:
                terminated = True
            except Exception as exc:
                logger.warning("Failed to terminate controller process via psutil: %s", exc)
        if not terminated:
            try:
                os.kill(target_pid, signal.SIGTERM)
                terminated = True
            except Exception as exc:
                logger.warning("Failed to signal controller process pid=%s: %s", target_pid, exc)
    finally:
        runtime._cleanup_controller_pid_file()
        with runtime._controller_launch_lock:
            if runtime._controller_process and getattr(runtime._controller_process, "pid", None) == target_pid:
                runtime._controller_process = None
    if hasattr(runtime, "_lifecycle"):
        try:
            runtime._lifecycle.untrack_handle(handle)  # type: ignore[attr-defined]
        except Exception:
            pass
