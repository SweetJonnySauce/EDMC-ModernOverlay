from __future__ import annotations

import threading
import logging
from typing import Any, Callable, Mapping, Optional, Set


def rebroadcast_last_config(
    is_running: Callable[[], bool],
    last_config_provider: Callable[[], Mapping[str, Any]],
    publish_payload: Callable[[Mapping[str, Any]], None],
) -> None:
    if not is_running():
        return
    payload = last_config_provider()
    if not payload:
        return
    publish_payload(dict(payload))


def schedule_config_rebroadcasts(
    rebroadcast_fn: Callable[[], None],
    timers: Set[threading.Timer],
    timer_lock: threading.Lock,
    count: int = 5,
    interval: float = 1.0,
    logger: Optional[logging.Logger] = None,
) -> None:
    if count <= 0 or interval <= 0:
        return

    cancel_config_timers(timers, timer_lock, logger)

    def _schedule(delay: float) -> None:
        timer_ref: Optional[threading.Timer] = None

        def _callback() -> None:
            try:
                rebroadcast_fn()
            finally:
                if timer_ref is not None:
                    with timer_lock:
                        timers.discard(timer_ref)

        timer_ref = threading.Timer(delay, _callback)
        timer_ref.daemon = True
        with timer_lock:
            timers.add(timer_ref)
        timer_ref.start()

    for index in range(count):
        delay = interval * (index + 1)
        _schedule(delay)


def cancel_config_timers(
    timers: Set[threading.Timer],
    timer_lock: threading.Lock,
    logger: Optional[logging.Logger] = None,
) -> None:
    with timer_lock:
        active = list(timers)
        timers.clear()
    for timer in active:
        try:
            timer.cancel()
        except Exception as exc:
            if logger:
                logger.warning("Failed to cancel config rebroadcast timer: %s", exc)


def schedule_version_notice_rebroadcasts(
    should_rebroadcast: Callable[[], bool],
    build_payload: Callable[[], Mapping[str, Any]],
    send_payload: Callable[[Mapping[str, Any]], bool],
    timers: Set[threading.Timer],
    timer_lock: threading.Lock,
    count: int,
    interval: float,
    logger: Optional[logging.Logger] = None,
) -> None:
    if count <= 0 or interval <= 0:
        return

    cancel_version_notice_timers(timers, timer_lock, logger)

    def _schedule(delay: float) -> None:
        timer_ref: Optional[threading.Timer] = None

        def _callback() -> None:
            try:
                if not should_rebroadcast():
                    return
                payload = build_payload()
                if send_payload(payload):
                    if logger:
                        logger.debug("Rebroadcasted version update notice to overlay")
            finally:
                if timer_ref is not None:
                    with timer_lock:
                        timers.discard(timer_ref)

        timer_ref = threading.Timer(delay, _callback)
        timer_ref.daemon = True
        with timer_lock:
            timers.add(timer_ref)
        timer_ref.start()

    for index in range(count):
        delay = interval * (index + 1)
        _schedule(delay)


def cancel_version_notice_timers(
    timers: Set[threading.Timer],
    timer_lock: threading.Lock,
    logger: Optional[logging.Logger] = None,
) -> None:
    with timer_lock:
        active = tuple(timers)
        timers.clear()
    for timer in active:
        try:
            timer.cancel()
        except Exception as exc:
            if logger:
                logger.warning("Failed to cancel version notice timer: %s", exc)
