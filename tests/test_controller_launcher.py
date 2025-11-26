from __future__ import annotations

from types import SimpleNamespace

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
