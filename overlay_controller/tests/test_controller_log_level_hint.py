from __future__ import annotations

import logging

import pytest

from overlay_controller import overlay_controller as controller


@pytest.fixture(autouse=True)
def reset_controller_logger():
    controller.set_log_level_hint(None, None)
    controller._CONTROLLER_LOGGER = None
    yield
    controller.set_log_level_hint(None, None)
    controller._CONTROLLER_LOGGER = None


def test_controller_logger_uses_env_hint(monkeypatch, tmp_path):
    controller.set_log_level_hint(10, "DEBUG")
    logger = controller._ensure_controller_logger(tmp_path)
    assert logger is not None
    assert logger.level == 10


def test_controller_logger_defaults_without_env(monkeypatch, tmp_path):
    logger = controller._ensure_controller_logger(tmp_path)
    assert logger.level == logging.DEBUG if controller.DEBUG_CONFIG_ENABLED else logging.INFO


def test_controller_logger_dev_override_clamps_env(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "DEBUG_CONFIG_ENABLED", True, raising=False)
    monkeypatch.setattr(controller, "_ENV_LOG_LEVEL_VALUE", logging.INFO, raising=False)
    monkeypatch.setattr(controller, "_ENV_LOG_LEVEL_NAME", "INFO", raising=False)
    controller.set_log_level_hint(None, None)
    logger = controller._ensure_controller_logger(tmp_path)
    assert logger.level == logging.DEBUG
