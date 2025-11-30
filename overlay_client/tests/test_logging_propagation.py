from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture(autouse=True)
def _reset_logger(monkeypatch):
    yield
    monkeypatch.delenv("EDMC_OVERLAY_PROPAGATE_LOGS", raising=False)
    if "overlay_client.overlay_client" in sys.modules:
        del sys.modules["overlay_client.overlay_client"]
    importlib.import_module("overlay_client.overlay_client")


def _reload_with_env(monkeypatch, value: str | None):
    if value is None:
        monkeypatch.delenv("EDMC_OVERLAY_PROPAGATE_LOGS", raising=False)
    else:
        monkeypatch.setenv("EDMC_OVERLAY_PROPAGATE_LOGS", value)
    if "overlay_client.overlay_client" in sys.modules:
        del sys.modules["overlay_client.overlay_client"]
    return importlib.import_module("overlay_client.overlay_client")


def test_default_propagation_disabled(monkeypatch):
    mod = _reload_with_env(monkeypatch, None)
    assert mod._CLIENT_LOGGER.propagate is False


def test_env_enables_propagation(monkeypatch):
    mod = _reload_with_env(monkeypatch, "1")
    assert mod._CLIENT_LOGGER.propagate is True
