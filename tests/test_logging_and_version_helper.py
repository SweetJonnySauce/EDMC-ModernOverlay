from __future__ import annotations

import logging
import sys
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
