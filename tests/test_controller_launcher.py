from __future__ import annotations

import os
from types import SimpleNamespace
from pathlib import Path
import subprocess

import pytest

import load


def _dummy_runtime(located: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        _flatpak_context={},
        _locate_overlay_python=lambda _env: located,
    )


def test_controller_python_prefers_override(monkeypatch, tmp_path):
    override = tmp_path / "py.exe"
    override.write_text("", encoding="utf-8")
    monkeypatch.setenv("EDMC_OVERLAY_CONTROLLER_PYTHON", str(override))
    runtime = _dummy_runtime(located=["should-not-be-used"])

    cmd = load._PluginRuntime._controller_python_command(runtime, {})

    assert cmd == [str(override)]
    monkeypatch.delenv("EDMC_OVERLAY_CONTROLLER_PYTHON", raising=False)


def test_controller_python_falls_back_to_overlay_python(monkeypatch):
    monkeypatch.delenv("EDMC_OVERLAY_CONTROLLER_PYTHON", raising=False)
    runtime = _dummy_runtime(located=["/tmp/venv/python"])

    cmd = load._PluginRuntime._controller_python_command(runtime, {})

    assert cmd == ["/tmp/venv/python"]


def test_controller_python_raises_when_missing(monkeypatch):
    monkeypatch.delenv("EDMC_OVERLAY_CONTROLLER_PYTHON", raising=False)
    runtime = _dummy_runtime(located=None)

    with pytest.raises(RuntimeError):
        load._PluginRuntime._controller_python_command(runtime, {})


def test_verify_tk_available_invokes_subprocess(monkeypatch):
    runtime = _dummy_runtime(located=["/tmp/venv/python"])
    called = {}

    def fake_call(cmd, stdout=None, stderr=None, env=None, timeout=None):
        called["cmd"] = cmd
        called["env"] = env
        called["timeout"] = timeout
        return 0

    monkeypatch.setattr(subprocess, "check_call", fake_call)
    load._PluginRuntime._verify_tk_available(runtime, ["python"], {"ENV": "1"})

    assert called["cmd"] == ["python", "-c", "import tkinter"]
    assert called["env"] == {"ENV": "1"}
    assert called["timeout"] == 5


def test_verify_tk_available_raises_on_failure(monkeypatch):
    runtime = _dummy_runtime(located=["/tmp/venv/python"])

    def fake_call(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "python")

    monkeypatch.setattr(subprocess, "check_call", fake_call)
    with pytest.raises(RuntimeError, match="missing Tk"):
        load._PluginRuntime._verify_tk_available(runtime, ["python"], {})
