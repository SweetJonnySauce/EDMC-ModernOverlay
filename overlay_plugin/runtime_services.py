from __future__ import annotations

import logging
from typing import Protocol


class _RuntimeLike(Protocol):
    broadcaster: object
    watchdog: object

    def _legacy_overlay_active(self) -> bool: ...
    def _delete_port_file(self) -> None: ...
    def _write_port_file(self) -> None: ...
    def _start_watchdog(self) -> bool: ...


def start_runtime_services(runtime: _RuntimeLike, logger: logging.Logger, log_fn) -> bool:
    """Start broadcaster + watchdog stack with original sequencing."""
    if runtime._legacy_overlay_active():
        runtime._delete_port_file()
        logger.error("Legacy edmcoverlay overlay detected; Modern Overlay will remain inactive.")
        return False

    if not runtime.broadcaster.start():
        log_fn("Overlay broadcast server failed to start; running in degraded mode.")
        runtime._delete_port_file()
        return False

    runtime._write_port_file()
    if not runtime._start_watchdog():
        runtime.broadcaster.stop()
        runtime._delete_port_file()
        log_fn("Overlay client launch aborted; Modern Overlay plugin remains inactive.")
        return False

    return True


def stop_runtime_services(runtime: _RuntimeLike, logger: logging.Logger, untrack_handle=None) -> None:
    """Stop watchdog + broadcaster stack with original ordering."""
    track_untracker = untrack_handle or (lambda handle: None)
    if runtime.watchdog:
        handle = runtime.watchdog
        try:
            stopped = runtime.watchdog.stop()
            if stopped:
                logger.debug("Overlay watchdog stopped and client terminated cleanly")
            else:
                logger.warning("Overlay watchdog stop reported incomplete shutdown")
        finally:
            track_untracker(handle)
            runtime.watchdog = None

    if getattr(runtime, "broadcaster", None):
        handle = runtime.broadcaster
        runtime.broadcaster.stop()
        track_untracker(handle)
    runtime._delete_port_file()
