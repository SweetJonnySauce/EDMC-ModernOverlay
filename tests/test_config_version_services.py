from __future__ import annotations

import logging
import threading

import overlay_plugin.config_version_services as services


class DummyTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.cancelled = False

    def start(self):
        self.callback()

    def cancel(self):
        self.cancelled = True


def test_schedule_config_rebroadcasts_runs_and_clears(monkeypatch):
    monkeypatch.setattr(services.threading, "Timer", DummyTimer)

    calls = []
    timers: set = set()
    lock = threading.Lock()

    services.schedule_config_rebroadcasts(
        rebroadcast_fn=lambda: calls.append("rebroadcast"),
        timers=timers,
        timer_lock=lock,
        count=2,
        interval=1.0,
        logger=logging.getLogger("test-config"),
    )

    assert calls == ["rebroadcast", "rebroadcast"]
    assert timers == set()


def test_cancel_config_timers_cancels_all():
    timers = {DummyTimer(0, lambda: None), DummyTimer(0, lambda: None)}
    original = list(timers)
    lock = threading.Lock()

    services.cancel_config_timers(timers, lock, logging.getLogger("test-config-cancel"))

    assert timers == set()
    assert all(timer.cancelled for timer in original)


def test_schedule_config_rebroadcasts_ignores_invalid_params():
    timers = {DummyTimer(0, lambda: None)}
    lock = threading.Lock()

    services.schedule_config_rebroadcasts(
        rebroadcast_fn=lambda: None,
        timers=timers,
        timer_lock=lock,
        count=0,
        interval=1.0,
        logger=logging.getLogger("test-config-invalid"),
    )
    assert len(timers) == 1

    services.schedule_config_rebroadcasts(
        rebroadcast_fn=lambda: None,
        timers=timers,
        timer_lock=lock,
        count=1,
        interval=0,
        logger=logging.getLogger("test-config-invalid"),
    )
    assert len(timers) == 1


def test_rebroadcast_last_config_respects_guards():
    published = []
    services.rebroadcast_last_config(
        is_running=lambda: False,
        last_config_provider=lambda: {"event": "OverlayConfig"},
        publish_payload=lambda payload: published.append(payload),
    )
    assert published == []

    services.rebroadcast_last_config(
        is_running=lambda: True,
        last_config_provider=lambda: {},
        publish_payload=lambda payload: published.append(payload),
    )
    assert published == []

    services.rebroadcast_last_config(
        is_running=lambda: True,
        last_config_provider=lambda: {"event": "OverlayConfig", "nonce": "abc"},
        publish_payload=lambda payload: published.append(payload),
    )
    assert published == [{"event": "OverlayConfig", "nonce": "abc"}]


def test_schedule_version_notice_rebroadcasts_respects_guard(monkeypatch):
    monkeypatch.setattr(services.threading, "Timer", DummyTimer)

    payloads = []
    timers: set = set()
    lock = threading.Lock()

    services.schedule_version_notice_rebroadcasts(
        should_rebroadcast=lambda: True,
        build_payload=lambda: {"id": "notice"},
        send_payload=lambda payload: payloads.append(payload) or True,
        timers=timers,
        timer_lock=lock,
        count=3,
        interval=0.5,
        logger=logging.getLogger("test-version"),
    )

    assert payloads == [{"id": "notice"}, {"id": "notice"}, {"id": "notice"}]
    assert timers == set()


def test_schedule_version_notice_rebroadcasts_skips_when_guard_false(monkeypatch):
    monkeypatch.setattr(services.threading, "Timer", DummyTimer)

    payloads = []
    timers: set = set()
    lock = threading.Lock()

    services.schedule_version_notice_rebroadcasts(
        should_rebroadcast=lambda: False,
        build_payload=lambda: {"id": "notice"},
        send_payload=lambda payload: payloads.append(payload) or True,
        timers=timers,
        timer_lock=lock,
        count=2,
        interval=0.5,
        logger=logging.getLogger("test-version-guard"),
    )

    assert payloads == []
    assert timers == set()


def test_cancel_version_notice_timers_cancels_all():
    timers = {DummyTimer(0, lambda: None), DummyTimer(0, lambda: None)}
    original = list(timers)
    lock = threading.Lock()

    services.cancel_version_notice_timers(timers, lock, logging.getLogger("test-version-cancel"))

    assert timers == set()
    assert all(timer.cancelled for timer in original)


def test_schedule_version_notice_rebroadcasts_ignores_invalid(monkeypatch):
    monkeypatch.setattr(services.threading, "Timer", DummyTimer)

    timers = {DummyTimer(0, lambda: None)}
    lock = threading.Lock()
    sent = []

    services.schedule_version_notice_rebroadcasts(
        should_rebroadcast=lambda: True,
        build_payload=lambda: {"id": "notice"},
        send_payload=lambda payload: sent.append(payload) or True,
        timers=timers,
        timer_lock=lock,
        count=0,
        interval=1.0,
        logger=logging.getLogger("test-version-invalid"),
    )
    assert len(timers) == 1
    assert sent == []
