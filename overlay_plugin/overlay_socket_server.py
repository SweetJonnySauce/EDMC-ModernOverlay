"""Threaded JSON-over-TCP broadcaster used by the EDMC Modern Overlay plugin."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set, Tuple


LogFunc = Callable[[str], None]


@dataclass
class SocketBroadcaster:
    """Runs a background TCP server that streams JSON lines to clients."""

    host: str = "127.0.0.1"
    port: int = 0
    log: LogFunc = lambda _msg: None  # noqa: E731 - simple default noop logger
    _loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _ready_event: threading.Event = field(default_factory=threading.Event, init=False)
    _queue: "queue.Queue[Optional[str]]" = field(default_factory=queue.Queue, init=False)
    _clients: Set[Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = field(default_factory=set, init=False)

    def start(self) -> None:
        """Start the broadcast server on a background thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run, name="EDMCOverlay-Server", daemon=True)
        self._thread.start()
        if not self._ready_event.wait(timeout=5.0):
            raise RuntimeError("Broadcast server failed to start in time")

    def stop(self) -> None:
        """Stop the server and release resources."""
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._clients.clear()

    def publish(self, payload: Dict[str, Any]) -> None:
        """Queue a payload to broadcast to all connected clients."""
        if self._stop_event.is_set():
            return
        try:
            message = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            self.log(f"Failed to encode payload to JSON: {exc}")
            return
        self._queue.put_nowait(message)

    # Internal helpers -----------------------------------------------------

    def _run(self) -> None:
        if self._loop is not None:
            return

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._server_main())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _server_main(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        sockets = server.sockets or []
        if sockets:
            sock = sockets[0]
            self.port = sock.getsockname()[1]
        self.log(f"Broadcast server listening on {self.host}:{self.port}")
        self._ready_event.set()

        async with server:
            while not self._stop_event.is_set():
                try:
                    message = await self._loop.run_in_executor(None, self._queue.get)
                except Exception:  # pragma: no cover - defensive
                    await asyncio.sleep(0.1)
                    continue
                if message is None:
                    continue
                await self._broadcast(message)

        for _reader, writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self._clients.add((reader, writer))
        self.log(f"Client connected ({len(self._clients)} active) {peer}")
        try:
            await reader.read()  # Drain until client disconnects; we are write-only.
        except Exception:
            pass
        finally:
            self._clients.discard((reader, writer))
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.log(f"Client disconnected ({len(self._clients)} active) {peer}")

    async def _broadcast(self, message: str) -> None:
        if not self._clients:
            return
        stale = []
        payload = (message + "\n").encode("utf-8")
        for reader_writer in list(self._clients):
            _reader, writer = reader_writer
            try:
                writer.write(payload)
                await writer.drain()
            except Exception:
                stale.append(reader_writer)
        for reader_writer in stale:
            self._clients.discard(reader_writer)
            _reader, writer = reader_writer
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# Backwards compatibility: existing code imports WebSocketBroadcaster
WebSocketBroadcaster = SocketBroadcaster
