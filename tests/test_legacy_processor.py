from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
OVERLAY_DIR = ROOT_DIR / "overlay-client"
if str(OVERLAY_DIR) not in sys.path:
    sys.path.insert(0, str(OVERLAY_DIR))

if "-h" in sys.argv or "--help" in sys.argv:
    print("Usage: PYTHONPATH=. python3 -m pytest tests/test_legacy_processor.py")
    raise SystemExit(0)

from legacy_store import LegacyItemStore
from legacy_processor import process_legacy_payload


def test_process_message_payload():
    store = LegacyItemStore()
    changed = process_legacy_payload(
        store,
        {
            "type": "message",
            "id": "msg1",
            "text": "Hello",
            "color": "green",
            "x": 10,
            "y": 20,
            "ttl": 5,
        },
    )
    assert changed is True
    item = store.get("msg1")
    assert item is not None
    assert item.kind == "message"
    assert item.data["text"] == "Hello"
    assert item.data["color"] == "green"
    assert item.data["x"] == 10
    assert item.data["y"] == 20


def test_process_rect_payload():
    store = LegacyItemStore()
    changed = process_legacy_payload(
        store,
        {
            "type": "shape",
            "shape": "rect",
            "id": "rect1",
            "color": "#abcdef",
            "fill": "#112233",
            "x": 5,
            "y": 6,
            "w": 40,
            "h": 20,
            "ttl": 3,
        },
    )
    assert changed is True
    item = store.get("rect1")
    assert item is not None
    assert item.kind == "rect"
    assert item.data["fill"] == "#112233"
    assert item.data["w"] == 40
    assert item.data["h"] == 20


def test_ttl_purge(monkeypatch: pytest.MonkeyPatch):
    store = LegacyItemStore()

    base_time = 1000.0
    monkeypatch.setattr("legacy_processor.time.monotonic", lambda: base_time)

    process_legacy_payload(
        store,
        {
            "type": "message",
            "id": "msg-ttl",
            "text": "Timed",
            "ttl": 1,
        },
    )
    item = store.get("msg-ttl")
    assert item is not None
    assert item.expiry is not None

    # Advance beyond expiry and purge
    assert store.purge_expired(base_time + 2.0) is True
    assert store.get("msg-ttl") is None
