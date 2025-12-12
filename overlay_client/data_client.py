"""Async TCP client that forwards messages to the Qt thread."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from overlay_client.debug_config import DEBUG_CONFIG_ENABLED

try:  # pragma: no cover - defensive fallback when running standalone
    from version import __version__ as MODERN_OVERLAY_VERSION
except Exception:  # pragma: no cover - fallback when module unavailable
    MODERN_OVERLAY_VERSION = "unknown"


class _ReleaseLogLevelFilter(logging.Filter):
    """Promote debug logs to INFO in release builds so diagnostics stay visible."""

    def __init__(self, release_mode: bool) -> None:
        super().__init__()
        self._release_mode = release_mode

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - logging shim
        if self._release_mode and record.levelno == logging.DEBUG:
            record.levelno = logging.INFO
            record.levelname = "INFO"
        return True


_LOGGER_NAME = "EDMC.ModernOverlay.Client.DataClient"
_LOGGER = logging.getLogger(_LOGGER_NAME)
_LOGGER.setLevel(logging.DEBUG if DEBUG_CONFIG_ENABLED else logging.INFO)
_LOGGER.propagate = True
_LOGGER.addFilter(_ReleaseLogLevelFilter(release_mode=not DEBUG_CONFIG_ENABLED))


class OverlayDataClient(QObject):
    """Async TCP client that forwards messages to the Qt thread."""

    message_received = pyqtSignal(dict)
    status_changed = pyqtSignal(str)

    def __init__(self, port_file: Path, loop_sleep: float = 1.0) -> None:
        super().__init__()
        self._port_file = port_file
        self._loop_sleep = loop_sleep
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self._last_metadata: Dict[str, Any] = {}
        self._outgoing: Optional[asyncio.Queue[Optional[Dict[str, Any]]]] = None
        self._pending: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=32)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, name="EDMCOverlay-Client", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._outgoing = None

    def send_cli_payload(self, payload: Mapping[str, Any]) -> bool:
        message = dict(payload)
        loop = self._loop
        queue_ref = self._outgoing
        if loop is not None and queue_ref is not None:
            try:
                loop.call_soon_threadsafe(queue_ref.put_nowait, message)
                return True
            except (RuntimeError, asyncio.QueueFull) as exc:
                _LOGGER.warning("Failed to enqueue CLI payload on running loop; falling back to pending queue: %s", exc)
        try:
            self._pending.put_nowait(message)
        except queue.Full:
            return False
        return True

    # Background thread ----------------------------------------------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            metadata = self._read_port()
            if metadata is None:
                self.status_changed.emit("Waiting for port.json…")
                await asyncio.sleep(self._loop_sleep)
                continue
            port = metadata["port"]
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except (OSError, asyncio.TimeoutError) as exc:
                self.status_changed.emit(f"Connect failed: {exc}")
                _LOGGER.warning("Connect failed to 127.0.0.1:%s: %s", port, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)
                continue

            script_label = MODERN_OVERLAY_VERSION if MODERN_OVERLAY_VERSION and MODERN_OVERLAY_VERSION != "unknown" else "unknown"
            if script_label != "unknown" and not script_label.lower().startswith("v"):
                script_label = f"v{script_label}"
            connection_prefix = script_label if script_label != "unknown" else "unknown"
            flatpak_suffix = ""
            if metadata.get("flatpak"):
                app_label = metadata.get("flatpak_app")
                flatpak_suffix = f" (Flatpak: {app_label})" if app_label else " (Flatpak)"
            connection_message = f"{connection_prefix} - Connected to 127.0.0.1:{port}{flatpak_suffix}"
            _LOGGER.debug("Status banner updated: %s", connection_message)
            self.status_changed.emit(connection_message)
            backoff = 1.0
            outgoing_queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
            self._outgoing = outgoing_queue
            while not self._pending.empty():
                try:
                    pending_payload = self._pending.get_nowait()
                except queue.Empty:
                    break
                try:
                    outgoing_queue.put_nowait(pending_payload)
                except asyncio.QueueFull:
                    break
            sender_task = asyncio.create_task(self._flush_outgoing(writer, outgoing_queue))
            try:
                while not self._stop_event.is_set():
                    line = await reader.readline()
                    if not line:
                        raise ConnectionError("Server closed the connection")
                    try:
                        payload = json.loads(line.decode("utf-8"))
                    except UnicodeDecodeError as exc:
                        _LOGGER.warning("Failed to decode payload bytes from server: %s", exc)
                        continue
                    except json.JSONDecodeError as exc:
                        _LOGGER.debug("Dropped invalid JSON payload from server: %s", exc)
                        continue
                    self.message_received.emit(payload)
            except asyncio.CancelledError:
                raise
            except (ConnectionError, asyncio.IncompleteReadError, OSError) as exc:
                self.status_changed.emit(f"Disconnected: {exc}")
                _LOGGER.warning("Disconnected from overlay server: %s", exc)
            finally:
                self._outgoing = None
                try:
                    outgoing_queue.put_nowait(None)
                except (RuntimeError, asyncio.QueueFull) as exc:
                    _LOGGER.debug("Failed to signal sender task shutdown: %s", exc)
                    pass
                try:
                    await sender_task
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - unexpected sender failures
                    _LOGGER.warning("Sender task terminated with error: %s", exc)
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except OSError as exc:
                        _LOGGER.debug("Error closing writer: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 10.0)

    async def _flush_outgoing(
        self,
        writer: asyncio.StreamWriter,
        queue_ref: "asyncio.Queue[Optional[Dict[str, Any]]]",
    ) -> None:
        while not self._stop_event.is_set():
            try:
                payload = await queue_ref.get()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive guard
                _LOGGER.warning("Failed to retrieve outgoing payload: %s", exc)
                break
            if payload is None:
                break
            try:
                serialised = json.dumps(payload, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                _LOGGER.warning("Failed to serialise outgoing payload %s: %s", payload, exc)
                continue
            try:
                writer.write(serialised.encode("utf-8") + b"\n")
                await writer.drain()
            except (ConnectionError, OSError) as exc:
                _LOGGER.warning("Failed to write outgoing payload: %s", exc)
                break

    def _read_port(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._port_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        port = data.get("port")
        if isinstance(port, int) and port > 0:
            data["port"] = port
            self._last_metadata = data
            return data
        return None
