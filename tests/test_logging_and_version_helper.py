from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
import sys
import threading
import json
from types import SimpleNamespace

import pytest

import load
from overlay_plugin import version_helper


def test_logger_uses_plugin_folder_name():
    logger = logging.getLogger(load.PLUGIN_NAME)
    assert logger.name == load.PLUGIN_NAME
    assert hasattr(load, "plugin_name")
    assert load.plugin_name == load.PLUGIN_NAME


@pytest.mark.parametrize(
    "appversion, expected",
    [
        ("", ()),
        ("5.0", (5, 0)),
        ("5.10.1", (5, 10, 1)),
        ("4.x", (4,)),
    ],
)
def test_appversion_tuple_parsing(monkeypatch, appversion, expected):
    dummy_config = SimpleNamespace(appversion=appversion)
    monkeypatch.setitem(sys.modules, "config", dummy_config)
    assert version_helper._appversion_tuple() == expected
    sys.modules.pop("config", None)


def test_has_min_appversion_defaults_true_when_unknown():
    sys.modules.pop("config", None)
    assert version_helper._has_min_appversion(99, 0) is True


def test_has_min_appversion_respects_floor(monkeypatch):
    dummy_config = SimpleNamespace(appversion="4.9.1")
    monkeypatch.setitem(sys.modules, "config", dummy_config)
    assert version_helper._has_min_appversion(5, 0) is False
    assert version_helper._has_min_appversion(4, 9) is True
    sys.modules.pop("config", None)


def test_create_http_session_prefers_edmc_when_supported(monkeypatch):
    def fake_new_session(timeout: int):
        class _Session(dict):
            def __init__(self):
                super().__init__()
                self.headers = {}

            def close(self):
                pass

        return _Session()

    applied = {}

    def fake_apply(session):
        applied["seen"] = session

    monkeypatch.setattr(version_helper, "_has_min_appversion", lambda major, minor=0: True)
    monkeypatch.setattr(version_helper, "_edmc_new_session", fake_new_session, raising=False)
    monkeypatch.setattr(version_helper, "_apply_debug_sender", fake_apply, raising=False)
    monkeypatch.setattr(version_helper, "requests", None, raising=False)

    session = version_helper._create_http_session(timeout=3)
    assert session is not None
    assert applied.get("seen") is session


def test_create_http_session_uses_requests_when_appversion_too_low(monkeypatch):
    class DummySession(dict):
        def __init__(self):
            super().__init__()
            self.headers = {}

        def close(self):
            pass

    class DummyRequests:
        def Session(self):
            return DummySession()

    applied = {}

    def fake_apply(session):
        applied["seen"] = session

    monkeypatch.setattr(version_helper, "_has_min_appversion", lambda major, minor=0: False)
    monkeypatch.setattr(version_helper, "_edmc_new_session", lambda timeout: (_ for _ in ()).throw(RuntimeError()), raising=False)
    monkeypatch.setattr(version_helper, "_apply_debug_sender", fake_apply, raising=False)
    monkeypatch.setattr(version_helper, "requests", DummyRequests(), raising=False)

    session = version_helper._create_http_session(timeout=3)
    assert isinstance(session, DummySession)
    assert applied.get("seen") is session


def test_edmc_debug_helper_true(monkeypatch):
    monkeypatch.setattr(load, "_resolve_edmc_log_level", lambda: logging.DEBUG)
    assert load._edmc_debug_logging_active() is True


def test_edmc_debug_helper_false(monkeypatch):
    monkeypatch.setattr(load, "_resolve_edmc_log_level", lambda: logging.INFO)
    assert load._edmc_debug_logging_active() is False


def test_capture_enabled_respects_helper(monkeypatch):
    runtime = object.__new__(load._PluginRuntime)
    runtime._capture_client_stderrout = True
    monkeypatch.setattr(load, "DEV_BUILD", False)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: True)
    assert runtime._capture_enabled() is True


def test_capture_disabled_when_not_debug(monkeypatch):
    runtime = object.__new__(load._PluginRuntime)
    runtime._capture_client_stderrout = True
    monkeypatch.setattr(load, "DEV_BUILD", False)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: False)
    assert runtime._capture_enabled() is False


def test_capture_disabled_when_override_off(monkeypatch):
    runtime = object.__new__(load._PluginRuntime)
    runtime._capture_client_stderrout = False
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: True)
    assert runtime._capture_enabled() is False


def _runtime_for_debug_json(tmp_path: Path):
    runtime = object.__new__(load._PluginRuntime)
    runtime._preferences = None
    runtime._payload_filter_path = tmp_path / "debug.json"
    runtime._payload_filter_excludes = set()
    runtime._payload_logging_enabled = False
    runtime._payload_filter_mtime = None
    runtime._trace_enabled = False
    runtime._trace_payload_prefixes = ()
    runtime._capture_client_stderrout = False
    runtime._capture_active = False
    runtime.watchdog = None
    runtime._log_retention_override = None
    runtime.plugin_dir = tmp_path
    runtime._payload_log_handler = None
    runtime._payload_logger = logging.getLogger("EDMCModernOverlay.payloads.test")
    runtime._payload_logger.propagate = False
    runtime._last_config = {}
    runtime._config_timers = set()
    runtime._config_timer_lock = threading.Lock()
    runtime._dev_settings_path = tmp_path / "dev_settings.json"
    runtime._dev_settings_mtime = None
    runtime._dev_settings = deepcopy(load.DEFAULT_DEV_SETTINGS)
    runtime._prefs_lock = threading.Lock()
    return runtime


def test_capture_enabled_with_dev_override(monkeypatch):
    runtime = object.__new__(load._PluginRuntime)
    runtime._capture_client_stderrout = True
    monkeypatch.setattr(load, "DEV_BUILD", True)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: False)
    assert runtime._capture_enabled() is True


def test_plugin_logger_forced_to_debug_in_dev_mode(monkeypatch):
    logger = logging.getLogger(load.LOGGER_NAME)
    previous_level = logger.level
    monkeypatch.setattr(load, "DEV_BUILD", True)
    monkeypatch.setattr(load, "_resolve_edmc_log_level", lambda: logging.INFO)
    monkeypatch.setattr(load, "_DEV_LOG_LEVEL_OVERRIDE_EMITTED", False, raising=False)
    try:
        level = load._ensure_plugin_logger_level()
    finally:
        logger.setLevel(previous_level)
    assert level == logging.DEBUG


def test_debug_json_created_when_edmc_debug(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "DEV_BUILD", False)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: True)
    runtime._load_payload_debug_config(force=True)
    assert runtime._payload_filter_path.exists()


def test_debug_json_skipped_when_not_debug(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "DEV_BUILD", False)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: False)
    runtime._load_payload_debug_config(force=True)
    assert runtime._payload_filter_path.exists() is False


def test_dev_settings_not_created_without_dev_mode(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "DEV_BUILD", False)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: True)
    runtime._load_payload_debug_config(force=True)
    runtime._load_dev_settings(force=True)
    assert runtime._dev_settings_path.exists() is False


def test_dev_settings_migrated_from_debug(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "DEV_BUILD", True)
    monkeypatch.setattr(load, "_edmc_debug_logging_active", lambda: True)
    # Seed legacy debug.json with dev-only fields.
    legacy = {
        "capture_client_stderrout": True,
        "overlay_logs_to_keep": 5,
        "payload_logging": {"overlay_payload_log_enabled": True},
        "tracing": {"enabled": True, "payload_ids": ["foo", "bar"]},
        "overlay_outline": True,
    }
    runtime._payload_filter_path.write_text(json.dumps(legacy), encoding="utf-8")
    runtime._load_payload_debug_config(force=True)
    assert runtime._dev_settings_path.exists()
    dev_payload = json.loads(runtime._dev_settings_path.read_text(encoding="utf-8"))
    assert dev_payload["tracing"]["enabled"] is True
    assert dev_payload["overlay_outline"] is True


def test_set_capture_override_updates_debug_json(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: True)
    runtime.set_capture_override_preference(False)
    data = json.loads(runtime._payload_filter_path.read_text(encoding="utf-8"))
    assert data["capture_client_stderrout"] is False
    assert runtime._capture_client_stderrout is False


def test_set_log_retention_override_preference(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: True)
    runtime.set_log_retention_override_preference(9)
    data = json.loads(runtime._payload_filter_path.read_text(encoding="utf-8"))
    assert data["overlay_logs_to_keep"] == 9
    assert runtime._log_retention_override == 9
    runtime.set_log_retention_override_preference(None)
    data = json.loads(runtime._payload_filter_path.read_text(encoding="utf-8"))
    assert data["overlay_logs_to_keep"] is None
    assert runtime._log_retention_override is None


def test_set_payload_logging_exclusions(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: True)
    runtime.set_payload_logging_exclusions(["Alpha", "beta", "alpha"])
    data = json.loads(runtime._payload_filter_path.read_text(encoding="utf-8"))
    assert data["payload_logging"]["exclude_plugins"] == ["alpha", "beta"]
    assert runtime._payload_filter_excludes == {"alpha", "beta"}


def test_set_payload_logging_preference_updates_debug_override(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    runtime._preferences = _PrefStub(value=False)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: True)
    runtime.set_payload_logging_preference(False)
    data = json.loads(runtime._payload_filter_path.read_text(encoding="utf-8"))
    assert data["payload_logging"]["overlay_payload_log_enabled"] is False
    assert runtime._payload_logging_enabled is False
    assert runtime._preferences.log_payloads is False


def test_set_payload_logging_preference_without_diagnostics(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    runtime._preferences = _PrefStub(value=False)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: False)
    runtime.set_payload_logging_preference(True)
    assert runtime._payload_logging_enabled is True
    assert runtime._payload_filter_path.exists() is False


def test_debug_config_edit_requires_diagnostics(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: False)
    with pytest.raises(RuntimeError):
        runtime.set_capture_override_preference(True)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple capture helper
        self.records.append(record)


class _PrefStub:
    def __init__(self, value: bool = False):
        self.log_payloads = value
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


def test_log_payload_skips_when_not_diagnostic(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    runtime._preferences = SimpleNamespace(log_payloads=True)
    test_logger = logging.getLogger("EDMCModernOverlay.payloads.test.gated")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.DEBUG)
    handler = _ListHandler()
    test_logger.addHandler(handler)
    runtime._payload_log_handler = handler
    runtime._payload_logger = test_logger
    monkeypatch.setattr(load._PluginRuntime, "_configure_payload_logger", lambda self: None)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: False)
    runtime._payload_logging_enabled = True
    runtime._log_payload({"event": "TestEvent"})
    assert handler.records == []
    test_logger.removeHandler(handler)


def test_log_payload_uses_debug_level(monkeypatch, tmp_path):
    runtime = _runtime_for_debug_json(tmp_path)
    runtime._preferences = SimpleNamespace(log_payloads=True)
    test_logger = logging.getLogger("EDMCModernOverlay.payloads.test.debug")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.DEBUG)
    handler = _ListHandler()
    test_logger.addHandler(handler)
    runtime._payload_log_handler = handler
    runtime._payload_logger = test_logger
    monkeypatch.setattr(load._PluginRuntime, "_configure_payload_logger", lambda self: None)
    monkeypatch.setattr(load, "_diagnostic_logging_enabled", lambda: True)
    runtime._payload_logging_enabled = True
    runtime._log_payload({"event": "TestEvent"})
    assert any("Overlay payload" in rec.getMessage() and rec.levelno == logging.DEBUG for rec in handler.records)
    test_logger.removeHandler(handler)
