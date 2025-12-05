from __future__ import annotations

import json
from pathlib import Path

from overlay_plugin.groupings_migration import compute_hash, load_marker, should_migrate, write_marker


def test_should_migrate_when_no_user_and_no_marker(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")

    decision = should_migrate(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is True
    assert decision.reason == "no_marker"
    assert decision.shipped_hash == compute_hash(shipped)


def test_should_not_migrate_when_user_exists(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")
    user.write_text("{}", encoding="utf-8")

    decision = should_migrate(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is False
    assert decision.reason == "user_exists"


def test_marker_prevents_repeat_until_hash_changes(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")
    current_hash = compute_hash(shipped)
    assert current_hash is not None
    write_marker(marker, current_hash, version="1.0.0")

    decision = should_migrate(shipped, user, marker, current_version="1.0.0")
    assert decision.should_migrate is False
    assert decision.reason == "already_migrated"

    shipped.write_text('{"changed":true}', encoding="utf-8")
    decision2 = should_migrate(shipped, user, marker, current_version="1.0.0")
    assert decision2.should_migrate is True
    assert decision2.reason == "shipped_hash_changed"


def test_version_change_triggers_migration_even_with_same_hash(tmp_path: Path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"
    shipped.write_text("{}", encoding="utf-8")
    current_hash = compute_hash(shipped)
    assert current_hash is not None
    write_marker(marker, current_hash, version="1.0.0")

    decision = should_migrate(shipped, user, marker, current_version="1.1.0")
    assert decision.should_migrate is True
    assert decision.reason == "version_changed"


def test_shipped_unreadable_skips_migration(tmp_path: Path):
    shipped = tmp_path / "missing.json"
    user = tmp_path / "overlay_groupings.user.json"
    marker = tmp_path / ".groupings_baseline.json"

    decision = should_migrate(shipped, user, marker, current_version="1.0.0")

    assert decision.should_migrate is False
    assert decision.reason == "shipped_unreadable"


def test_load_marker_handles_malformed(tmp_path: Path):
    marker = tmp_path / ".groupings_baseline.json"
    marker.write_text("{bad", encoding="utf-8")

    shipped_hash, version = load_marker(marker)
    assert shipped_hash is None
    assert version is None

    marker.write_text(json.dumps({"shipped_hash": "abc", "version": "1.0.0"}), encoding="utf-8")
    shipped_hash2, version2 = load_marker(marker)
    assert shipped_hash2 == "abc"
    assert version2 == "1.0.0"
