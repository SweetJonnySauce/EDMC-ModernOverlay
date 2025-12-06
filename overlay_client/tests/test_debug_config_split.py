from __future__ import annotations

import json

from overlay_client import debug_config as module


def test_troubleshooting_disabled_returns_defaults(tmp_path):
    cfg = module.load_troubleshooting_config(tmp_path / "debug.json", enabled=False)
    assert cfg.overlay_logs_to_keep is None


def test_troubleshooting_reads_overlay_logs(tmp_path):
    path = tmp_path / "debug.json"
    path.write_text(json.dumps({"overlay_logs_to_keep": 7}), encoding="utf-8")
    cfg = module.load_troubleshooting_config(path, enabled=True)
    assert cfg.overlay_logs_to_keep == 7


def test_dev_settings_release_ignores_file(monkeypatch, tmp_path):
    path = tmp_path / "dev_settings.json"
    path.write_text(json.dumps({"tracing": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setattr(module, "DEBUG_CONFIG_ENABLED", False, raising=False)
    cfg = module.load_dev_settings(path)
    assert cfg.trace_enabled is False


def test_dev_settings_enabled_reads_file(monkeypatch, tmp_path):
    path = tmp_path / "dev_settings.json"
    payload = {
        "tracing": {"enabled": True, "payload_ids": ["core"]},
        "overlay_outline": True,
        "group_bounds_outline": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(module, "DEBUG_CONFIG_ENABLED", True, raising=False)
    cfg = module.load_dev_settings(path)
    assert cfg.trace_enabled is True
    assert cfg.trace_payload_ids == ("core",)
    assert cfg.overlay_outline is True
