from __future__ import annotations

from typing import Mapping

from overlay_client.payload_model import PayloadModel


def _trace_logger(plugin: str, item_id: str, stage: str, details: Mapping[str, object]) -> None:
    return


def test_message_dedupe_skips_identical_payload() -> None:
    model = PayloadModel(_trace_logger)
    payload = {
        "id": "msg-1",
        "type": "message",
        "text": "hello",
        "color": "white",
        "x": 10,
        "y": 20,
        "size": "normal",
    }
    first = model.ingest(payload.copy(), override_generation=1, group_label="group-a")
    second = model.ingest(payload.copy(), override_generation=1, group_label="group-a")
    assert first is True
    assert second is False


def test_message_dedupe_detects_changed_position() -> None:
    model = PayloadModel(_trace_logger)
    payload = {
        "id": "msg-2",
        "type": "message",
        "text": "hello",
        "color": "white",
        "x": 10,
        "y": 20,
        "size": "normal",
    }
    assert model.ingest(payload.copy(), override_generation=1, group_label="group-a") is True
    moved = payload.copy()
    moved["x"] = 11
    assert model.ingest(moved, override_generation=1, group_label="group-a") is True


def test_message_dedupe_detects_changed_text() -> None:
    model = PayloadModel(_trace_logger)
    payload = {
        "id": "msg-3",
        "type": "message",
        "text": "hello",
        "color": "white",
        "x": 10,
        "y": 20,
        "size": "normal",
    }
    assert model.ingest(payload.copy(), override_generation=1, group_label="group-a") is True
    changed = payload.copy()
    changed["text"] = "hello world"
    assert model.ingest(changed, override_generation=1, group_label="group-a") is True


def test_override_generation_busts_dedupe() -> None:
    model = PayloadModel(_trace_logger)
    payload = {
        "id": "msg-4",
        "type": "message",
        "text": "same",
        "color": "white",
        "x": 1,
        "y": 2,
        "size": "normal",
    }
    assert model.ingest(payload.copy(), override_generation=1, group_label="group-a") is True
    # Same payload but new override generation should not dedupe.
    assert model.ingest(payload.copy(), override_generation=2, group_label="group-a") is True
