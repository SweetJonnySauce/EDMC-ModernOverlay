from __future__ import annotations

import json
from pathlib import Path

from overlay_plugin.groupings_migration import migrate_shipped_to_user, compute_hash, write_marker


def test_migrate_copies_shipped_and_writes_marker(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    payload = {"PluginA": {"idPrefixGroups": {"Main": {"idPrefixes": ["Foo-"]}}}}
    shipped.write_text(json.dumps(payload), encoding="utf-8")

    decision = migrate_shipped_to_user(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is True
    assert decision.reason == "migrated"
    assert json.loads(user.read_text(encoding="utf-8")) == payload
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_data["shipped_hash"] == compute_hash(shipped)
    assert marker_data["version"] == "1.0.0"


def test_migrate_is_idempotent_when_user_exists(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")
    user.write_text("{}", encoding="utf-8")

    decision = migrate_shipped_to_user(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is False
    assert decision.reason == "user_exists"
    assert not marker.exists()


def test_migrate_skips_on_malformed_shipped(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{bad", encoding="utf-8")

    decision = migrate_shipped_to_user(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is False
    assert decision.reason == "shipped_invalid_json"
    assert not user.exists()
    assert not marker.exists()


def test_migrate_respects_marker_to_prevent_repeat(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")
    write_marker(marker, compute_hash(shipped) or "", "1.0.0")

    decision = migrate_shipped_to_user(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is False
    assert decision.reason == "already_migrated"
