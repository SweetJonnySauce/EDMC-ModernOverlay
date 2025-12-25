from __future__ import annotations

import load


class _DummyTimer:
    def __init__(self):
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _DummyThread:
    def __init__(self, name: str):
        self.name = name
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self._alive = False


class _DummyHandle:
    def stop(self) -> bool:
        return True


class _DummyBroadcaster:
    def __init__(self, *args, **kwargs):
        self.port = 1234
        self.started = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.started = False

    def publish(self, payload) -> None:  # pragma: no cover - stub
        return


class _FakePrefs:
    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.overlay_opacity = 0.5
        self.show_connection_status = False
        self.debug_overlay_corner = "NW"
        self.status_message_gutter = 0
        self.client_log_retention = load.DEFAULT_CLIENT_LOG_RETENTION
        self.gridlines_enabled = False
        self.gridline_spacing = 120
        self.force_render = False
        self.force_xwayland = False
        self.show_debug_overlay = False
        self.min_font_point = 6.0
        self.max_font_point = 24.0
        self.title_bar_enabled = False
        self.title_bar_height = 0
        self.cycle_payload_ids = False
        self.copy_payload_id_on_cycle = False
        self.scale_mode = "fit"
        self.nudge_overflow_payloads = False
        self.payload_nudge_gutter = 30
        self.payload_log_delay_seconds = 0.0
        self.log_payloads = False
        self.controller_launch_command = "!ovr"

    def status_bottom_margin(self) -> int:
        return 0

    def save(self) -> None:
        return


def _make_runtime(monkeypatch, tmp_path):
    # NOP out external side effects and wire dummy resources.
    monkeypatch.setattr(load, "WebSocketBroadcaster", _DummyBroadcaster)
    monkeypatch.setattr(load, "OverlayWatchdog", _DummyHandle)
    monkeypatch.setattr(load, "LegacyOverlayTCPServer", _DummyHandle)
    monkeypatch.setattr(load, "register_grouping_store", lambda *args, **kwargs: None)
    monkeypatch.setattr(load, "unregister_grouping_store", lambda *args, **kwargs: None)
    monkeypatch.setattr(load, "register_publisher", lambda *args, **kwargs: None)
    monkeypatch.setattr(load, "unregister_publisher", lambda *args, **kwargs: None)
    monkeypatch.setattr(load._PluginRuntime, "_configure_payload_logger", lambda self: None)
    monkeypatch.setattr(load._PluginRuntime, "_load_payload_debug_config", lambda self, force=False: None)
    monkeypatch.setattr(load._PluginRuntime, "_load_dev_settings", lambda self, force=False: None)
    monkeypatch.setattr(load._PluginRuntime, "_enforce_force_xwayland", lambda self, **kwargs: False)
    monkeypatch.setattr(load._PluginRuntime, "_publish_payload", lambda self, payload: None)
    monkeypatch.setattr(load._PluginRuntime, "_maybe_emit_version_update_notice", lambda self: None)
    monkeypatch.setattr(load._PluginRuntime, "_platform_context_payload", lambda self: {})
    monkeypatch.setattr(load._PluginRuntime, "_legacy_overlay_active", lambda self: False)

    def _fake_start_watchdog(self) -> bool:
        self.watchdog = _DummyHandle()
        self._track_handle(self.watchdog)
        return True

    def _fake_start_legacy_tcp_server(self) -> None:
        server = _DummyHandle()
        self._legacy_tcp_server = server
        self._track_handle(server)

    def _fake_start_force_monitor(self) -> None:
        thread = _DummyThread("ModernOverlayForceMonitor")
        self._force_monitor_thread = thread
        self._track_thread(thread)

    def _fake_start_version_check(self) -> None:
        thread = _DummyThread("ModernOverlayVersionCheck")
        self._version_check_thread = thread
        self._track_thread(thread)

    def _fake_start_prefs_worker(self) -> None:
        thread = _DummyThread("ModernOverlayPrefs")
        self._prefs_worker = thread
        self._track_thread(thread)

    def _fake_schedule_config(self, count: int = 1, interval: float = 0.1) -> None:
        timers = [_DummyTimer() for _ in range(max(0, count))]
        with self._config_timer_lock:
            self._config_timers.update(timers)

    monkeypatch.setattr(load._PluginRuntime, "_start_watchdog", _fake_start_watchdog)
    monkeypatch.setattr(load._PluginRuntime, "_start_legacy_tcp_server", _fake_start_legacy_tcp_server)
    monkeypatch.setattr(load._PluginRuntime, "_start_force_render_monitor_if_needed", _fake_start_force_monitor)
    monkeypatch.setattr(load._PluginRuntime, "_start_version_status_check", _fake_start_version_check)
    monkeypatch.setattr(load._PluginRuntime, "_start_prefs_worker", _fake_start_prefs_worker)
    monkeypatch.setattr(load._PluginRuntime, "_schedule_config_rebroadcasts", _fake_schedule_config)

    prefs = _FakePrefs(tmp_path)
    runtime = load._PluginRuntime(str(tmp_path), prefs)
    return runtime


def test_start_stop_drains_tracked_resources(monkeypatch, tmp_path):
    runtime = _make_runtime(monkeypatch, tmp_path)

    runtime.start()
    runtime.stop()

    assert not runtime._tracked_threads
    assert not runtime._tracked_handles
    assert not runtime._config_timers
    assert not runtime._version_notice_timers


def test_repeated_start_stop_is_idempotent(monkeypatch, tmp_path):
    runtime = _make_runtime(monkeypatch, tmp_path)

    runtime.start()
    runtime.stop()
    runtime.start()
    runtime.stop()

    assert not runtime._tracked_threads
    assert not runtime._tracked_handles
    assert not runtime._config_timers
    assert not runtime._version_notice_timers


def test_stop_without_start_is_safe(monkeypatch, tmp_path):
    runtime = _make_runtime(monkeypatch, tmp_path)

    runtime.stop()

    assert runtime._prefs_worker is None
    assert not runtime._tracked_threads
    # Broadcaster is created during __init__; when not started, handles remain limited to it.
    assert runtime._tracked_handles == [runtime.broadcaster]
