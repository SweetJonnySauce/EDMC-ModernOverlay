from __future__ import annotations

import importlib
import json
import logging
import sys

import pytest

from overlay_client import launcher


def test_resolve_log_level_prefers_port(tmp_path, monkeypatch):
    port_path = tmp_path / "port.json"
    port_path.write_text(json.dumps({"log_level": {"value": 10, "name": "DEBUG"}}), encoding="utf-8")
    monkeypatch.setenv("EDMC_OVERLAY_LOG_LEVEL", "30")
    monkeypatch.setenv("EDMC_OVERLAY_LOG_LEVEL_NAME", "ERROR")

    value, name, source = launcher.resolve_log_level_hint(port_path)
    assert value == 10
    assert name == "DEBUG"
    assert source == "port.json"


def test_resolve_log_level_uses_env_when_port_missing(tmp_path, monkeypatch):
    port_path = tmp_path / "missing.json"
    monkeypatch.setenv("EDMC_OVERLAY_LOG_LEVEL", "30")
    monkeypatch.delenv("EDMC_OVERLAY_LOG_LEVEL_NAME", raising=False)

    value, name, source = launcher.resolve_log_level_hint(port_path)
    assert value == 30
    assert name == "WARNING"  # logging resolves default name
    assert source == "env"


def test_resolve_log_level_defaults_when_unavailable(tmp_path, monkeypatch):
    port_path = tmp_path / "port.json"
    port_path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("EDMC_OVERLAY_LOG_LEVEL", raising=False)
    monkeypatch.delenv("EDMC_OVERLAY_LOG_LEVEL_NAME", raising=False)

    value, name, source = launcher.resolve_log_level_hint(port_path)
    assert value is None
    assert name is None
    assert source == "default"


def test_resolve_log_level_accepts_name_only(tmp_path, monkeypatch):
    port_path = tmp_path / "missing.json"
    monkeypatch.delenv("EDMC_OVERLAY_LOG_LEVEL", raising=False)
    monkeypatch.setenv("EDMC_OVERLAY_LOG_LEVEL_NAME", "ERROR")

    value, name, source = launcher.resolve_log_level_hint(port_path)
    assert value == logging.ERROR
    assert name == "ERROR"
    assert source == "env"


def _reload_client_module():
    if "overlay_client.overlay_client" in sys.modules:
        return importlib.reload(sys.modules["overlay_client.overlay_client"])
    return importlib.import_module("overlay_client.overlay_client")


@pytest.fixture
def client_module():
    mod = _reload_client_module()
    yield mod
    _reload_client_module()


def test_apply_log_level_hint_sets_level(client_module):
    client_module.apply_log_level_hint(logging.DEBUG, source="test")
    assert client_module._CLIENT_LOGGER.level == logging.DEBUG


def test_apply_log_level_hint_ignores_invalid(client_module):
    initial = client_module._CLIENT_LOGGER.level
    client_module.apply_log_level_hint("invalid")  # type: ignore[arg-type]
    assert client_module._CLIENT_LOGGER.level == initial


def test_apply_log_level_hint_clamps_in_dev_mode(client_module, monkeypatch):
    monkeypatch.setattr(client_module, "DEBUG_CONFIG_ENABLED", True, raising=False)
    client_module._CLIENT_LOGGER.setLevel(logging.INFO)
    client_module.apply_log_level_hint(logging.INFO, source="port")
    assert client_module._CLIENT_LOGGER.level == logging.DEBUG
