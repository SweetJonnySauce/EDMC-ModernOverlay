from pathlib import Path

from overlay_client import env_overrides


def test_load_overrides_missing_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "env_overrides.json"
    loaded = env_overrides.load_overrides(path)
    assert loaded == {}


def test_apply_overrides_skips_existing_env(monkeypatch) -> None:
    overrides = {
        "env": {
            "EXISTING": "keep",
            "NEW_VAR": "apply",
            "SET_IN_OS": "skip",
        },
        "provenance": {"compositor_id": "kwin"},
    }
    env = {"EXISTING": "present"}
    monkeypatch.setenv("SET_IN_OS", "1")
    result = env_overrides.apply_overrides(env, overrides, logger=None)
    assert "NEW_VAR" in env and env["NEW_VAR"] == "apply"
    assert env["EXISTING"] == "present"
    assert "SET_IN_OS" not in env  # should not add when OS env already set
    assert result.applied == ["NEW_VAR"]
    assert result.skipped_existing == ["EXISTING"]
    assert result.skipped_env == ["SET_IN_OS"]


def test_load_overrides_reads_env_block(tmp_path: Path) -> None:
    payload = {"env": {"A": "1"}, "provenance": {"source": "test"}}
    path = tmp_path / "env_overrides.json"
    path.write_text('{"env":{"A":"1"},"provenance":{"source":"test"}}', encoding="utf-8")
    loaded = env_overrides.load_overrides(path)
    assert loaded.get("env") == payload["env"]
    assert loaded.get("provenance") == payload["provenance"]
