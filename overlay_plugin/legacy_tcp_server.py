"""Compatibility TCP listener for legacy edmcoverlay payloads."""
from __future__ import annotations

import json
import socketserver
import threading
from typing import Any, Callable, Mapping, Optional

LogFunc = Callable[[str], None]
LegacyPayloadHandler = Callable[[Mapping[str, Any]], bool]


class _LegacyTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass) -> None:  # type: ignore[override]
        super().__init__(server_address, RequestHandlerClass)
        self.log: LogFunc = lambda _msg: None
        self.payload_handler: Optional[LegacyPayloadHandler] = None


class _LegacyTCPHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:  # type: ignore[override]
        server = self.server  # type: ignore[assignment]
        log = getattr(server, "log", lambda _msg: None)
        handler = getattr(server, "payload_handler", None)
        if handler is None:
            return

        buffer = b""
        while True:
            try:
                chunk = self.rfile.readline()
            except Exception:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    payload_obj = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    log(f"Legacy overlay payload rejected (parse error): {exc}")
                    continue
                if not isinstance(payload_obj, Mapping):
                    log("Legacy overlay payload rejected (not a mapping)")
                    continue
                try:
                    handler(dict(payload_obj))
                except Exception as exc:
                    log(f"Legacy overlay payload handler raised error: {exc}")


class LegacyOverlayTCPServer:
    """TCP server that ingests legacy edmcoverlay payloads."""

    def __init__(
        self,
        host: str,
        port: int,
        log: LogFunc,
        handler: LegacyPayloadHandler,
    ) -> None:
        self._host = host
        self._port = port
        self._log = log
        self._handler = handler
        self._server: Optional[_LegacyTCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            server = _LegacyTCPServer((self._host, self._port), _LegacyTCPHandler)
        except OSError as exc:
            self._log(
                f"Legacy overlay compatibility server unavailable on {self._host}:{self._port} ({exc})"
            )
            return False
        server.log = self._log
        server.payload_handler = self._handler
        thread = threading.Thread(target=server.serve_forever, name="EDMCOverlay-LegacyTCP", daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        self._log(f"Legacy overlay compatibility server listening on {self._host}:{self._port}")
        return True

    def stop(self) -> None:
        server = self._server
        if not server:
            return
        server.shutdown()
        server.server_close()
        thread = self._thread
        if thread:
            thread.join(timeout=2.0)
        self._server = None
        self._thread = None
        self._log("Legacy overlay compatibility server stopped")
