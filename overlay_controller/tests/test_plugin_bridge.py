import json
from pathlib import Path

import overlay_controller.services.plugin_bridge as pb


class FakeWriter:
    def __init__(self, log: list[object]) -> None:
        self.log = log

    def write(self, data: str) -> int:
        self.log.append(("write", data))
        return len(data)

    def flush(self) -> None:
        self.log.append("flush")


class FakeReader:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def readline(self) -> str:
        if self._responses:
            return self._responses.pop(0)
        return ""


class FakeSocket:
    def __init__(self, log: list[object], responses: list[str] | None = None) -> None:
        self.log = log
        self._responses = responses or []

    def makefile(self, mode: str, **_kwargs):
        if "w" in mode:
            return FakeWriter(self.log)
        return FakeReader(list(self._responses))

    def settimeout(self, timeout: float) -> None:
        self.log.append(("timeout", timeout))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.log.append("closed")


def test_plugin_bridge_sends_cli_payload(tmp_path: Path) -> None:
    log: list[object] = []
    (tmp_path / "port.json").write_text('{"port": 2345}', encoding="utf-8")

    def fake_connect(addr, timeout=0.0):
        log.append(("connect", addr, timeout))
        return FakeSocket(log)

    bridge = pb.PluginBridge(root=tmp_path, connect=fake_connect)

    assert bridge.send_cli({"cli": "ping", "value": 1}) is True
    json_writes = [entry for entry in log if isinstance(entry, tuple) and entry[0] == "write"]
    assert json_writes
    payload = json.loads(json_writes[0][1])
    assert payload == {"cli": "ping", "value": 1}
    assert ("connect", ("127.0.0.1", 2345), 1.5) in log
    assert "flush" in log
    assert "closed" in log


def test_active_group_dedupes_same_payload(tmp_path: Path) -> None:
    log: list[object] = []
    (tmp_path / "port.json").write_text('{"port": 3456}', encoding="utf-8")

    def fake_connect(addr, timeout=0.0):
        return FakeSocket(log)

    bridge = pb.PluginBridge(root=tmp_path, connect=fake_connect)
    sent_first = bridge.send_active_group("Plugin", "Group", anchor="NW", edit_nonce="n1")
    sent_second = bridge.send_active_group("Plugin", "Group", anchor="nw", edit_nonce="n2")

    json_writes = [
        entry[1] for entry in log if isinstance(entry, tuple) and entry[0] == "write" and entry[1].startswith("{")
    ]
    assert sent_first is True
    assert sent_second is False
    assert len(json_writes) == 1
    payload = json.loads(json_writes[0])
    assert payload["anchor"] == "nw"
    assert payload["edit_nonce"] == "n1"


def test_force_render_override_logs_on_failure(tmp_path: Path) -> None:
    log: list[object] = []
    (tmp_path / "port.json").write_text('{"port": 2345}', encoding="utf-8")

    def failing_connect(*_args, **_kwargs):
        raise OSError("socket unavailable")

    manager = pb.ForceRenderOverrideManager(
        port_path=tmp_path / "port.json",
        connect=failing_connect,
        logger=lambda msg: log.append(("log", msg)),
    )

    manager.activate()
    manager.deactivate()
    assert any("enabling force-render override" in entry[1] for entry in log if entry[0] == "log")
    assert any("disabling force-render override" in entry[1] for entry in log if entry[0] == "log")


def test_force_render_override_sends_payloads(tmp_path: Path) -> None:
    log: list[object] = []
    responses = ['{"status": "ok"}\n']
    (tmp_path / "port.json").write_text('{"port": 4567}', encoding="utf-8")
    call_count = {"value": 0}

    def fake_connect(addr, timeout=0.0):
        call_count["value"] += 1
        resp = responses if call_count["value"] == 1 else []
        log.append(("connect", addr, timeout))
        return FakeSocket(log, responses=resp)

    manager = pb.ForceRenderOverrideManager(
        port_path=tmp_path / "port.json",
        connect=fake_connect,
        logger=lambda msg: log.append(("log", msg)),
        time_source=lambda: 0.0,
    )

    manager.activate()
    manager.deactivate()

    json_writes = [entry[1] for entry in log if isinstance(entry, tuple) and entry[0] == "write" and entry[1].startswith("{")]
    assert json_writes, "expected force-render override payloads to be written"
    first_payload = json.loads(json_writes[0])
    assert first_payload["force_render"] is True
    second_payload = json.loads(json_writes[-1])
    assert second_payload["force_render"] is False
