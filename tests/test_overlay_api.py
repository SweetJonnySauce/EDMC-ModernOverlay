from __future__ import annotations

import json

import pytest

from overlay_plugin import overlay_api
from overlay_plugin.overlay_api import PluginGroupingError


@pytest.fixture(autouse=True)
def grouping_store(tmp_path):
    path = tmp_path / "overlay_groupings.json"
    overlay_api.register_grouping_store(path)
    try:
        yield path
    finally:
        overlay_api.unregister_grouping_store()


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_register_grouping_store_rejects_user_file(tmp_path):
    user_path = tmp_path / "overlay_groupings.user.json"
    with pytest.raises(PluginGroupingError):
        overlay_api.register_grouping_store(user_path)


def test_define_plugin_group_creates_sections(grouping_store):
    updated = overlay_api.define_plugin_group(
        plugin_group="Example",
        matching_prefixes=["example-"],
        id_prefix_group="alerts",
        id_prefixes=["example-alert-", "example-warning-"],
        id_prefix_group_anchor="se",
    )
    assert updated is True

    payload = _load(grouping_store)
    assert payload["Example"]["matchingPrefixes"] == [
        "example-",
    ]
    group = payload["Example"]["idPrefixGroups"]["alerts"]
    assert group["idPrefixes"] == ["example-alert-", "example-warning-"]
    assert group["idPrefixGroupAnchor"] == "se"


def test_define_plugin_group_extends_matching_without_removal(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        matching_prefixes=["example-", "legacy-"],
    )
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="metrics",
        id_prefixes=["example-metric-", "legacy-"],
    )

    payload = _load(grouping_store)
    assert payload["Example"]["matchingPrefixes"] == [
        "example-",
        "legacy-",
    ]
    group = payload["Example"]["idPrefixGroups"]["metrics"]
    assert group["idPrefixes"] == ["example-metric-", "legacy-"]


def test_define_plugin_group_creates_matching_from_id_prefixes(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Solo",
        id_prefix_group="alerts",
        id_prefixes=["solo-alert-"],
    )

    payload = _load(grouping_store)
    assert payload["Solo"]["matchingPrefixes"] == ["solo-alert-"]


def test_define_plugin_group_only_adds_unmatched_prefixes(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Scoped",
        matching_prefixes=["example-"],
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
    )

    overlay_api.define_plugin_group(
        plugin_group="Scoped",
        id_prefix_group="status",
        id_prefixes=["example-status-", "other-scope-"],
    )

    payload = _load(grouping_store)
    matches = payload["Scoped"]["matchingPrefixes"]
    assert matches == ["example-", "other-scope-"]


def test_define_plugin_group_lowercases_prefixes(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="MixedCase",
        matching_prefixes=["Alpha-", "BETA-"],
        id_prefix_group="Alerts",
        id_prefixes=["Gamma-", "DELTA-"],
    )

    payload = _load(grouping_store)
    assert payload["MixedCase"]["matchingPrefixes"] == ["alpha-", "beta-", "gamma-", "delta-"]
    assert payload["MixedCase"]["idPrefixGroups"]["Alerts"]["idPrefixes"] == ["gamma-", "delta-"]


def test_define_plugin_group_supports_exact_match_mode(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="tick",
        id_prefixes=[{"value": "bgstally-frame-tick", "matchMode": "exact"}],
    )

    payload = _load(grouping_store)
    group = payload["Example"]["idPrefixGroups"]["tick"]
    assert group["idPrefixes"] == [{"value": "bgstally-frame-tick", "matchMode": "exact"}]
    # matchingPrefixes still holds strings so plugin detection continues to work
    assert payload["Example"]["matchingPrefixes"] == ["bgstally-frame-tick"]


def test_define_plugin_group_moves_prefix_between_groups(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-a-", "example-b-"],
    )
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="metrics",
        id_prefixes=["example-c-"],
    )

    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="metrics",
        id_prefixes=["example-b-", "example-x-"],
    )

    payload = _load(grouping_store)
    alerts = payload["Example"]["idPrefixGroups"]["alerts"]["idPrefixes"]
    metrics = payload["Example"]["idPrefixGroups"]["metrics"]["idPrefixes"]

    assert alerts == ["example-a-"]
    assert metrics == ["example-b-", "example-x-"]


def test_define_plugin_group_anchor_updates_existing_group(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
    )

    updated = overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefix_group_anchor="ne",
    )
    assert updated is True

    payload = _load(grouping_store)
    assert payload["Example"]["idPrefixGroups"]["alerts"]["idPrefixGroupAnchor"] == "ne"


def test_define_plugin_group_anchor_requires_existing_group(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefix_group="missing",
            id_prefix_group_anchor="nw",
        )


def test_define_plugin_group_sets_payload_justification(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        payload_justification="center",
    )

    payload = _load(grouping_store)
    group = payload["Example"]["idPrefixGroups"]["alerts"]
    assert group["payloadJustification"] == "center"


def test_define_plugin_group_updates_payload_justification(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
    )

    updated = overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        payload_justification="right",
    )
    assert updated is True

    payload = _load(grouping_store)
    assert payload["Example"]["idPrefixGroups"]["alerts"]["payloadJustification"] == "right"


def test_define_plugin_group_sets_marker_label_position(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        marker_label_position="below",
    )

    payload = _load(grouping_store)
    group = payload["Example"]["idPrefixGroups"]["alerts"]
    assert group["markerLabelPosition"] == "below"


def test_define_plugin_group_updates_marker_label_position(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        marker_label_position="below",
    )

    updated = overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        marker_label_position="centered",
    )
    assert updated is True

    payload = _load(grouping_store)
    assert payload["Example"]["idPrefixGroups"]["alerts"]["markerLabelPosition"] == "centered"

def test_define_plugin_group_sets_controller_preview_box_mode(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        controller_preview_box_mode="max",
    )

    payload = _load(grouping_store)
    group = payload["Example"]["idPrefixGroups"]["alerts"]
    assert group["controllerPreviewBoxMode"] == "max"


def test_define_plugin_group_updates_controller_preview_box_mode(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        controller_preview_box_mode="last",
    )

    updated = overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        controller_preview_box_mode="max",
    )
    assert updated is True

    payload = _load(grouping_store)
    assert payload["Example"]["idPrefixGroups"]["alerts"]["controllerPreviewBoxMode"] == "max"


def test_define_plugin_group_requires_id_group_for_payload_justification(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            payload_justification="center",
        )


def test_define_plugin_group_validates_payload_justification_token(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefix_group="alerts",
            id_prefixes=["example-"],
            payload_justification="middle",
        )


def test_define_plugin_group_requires_id_group_for_marker_label_position(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            marker_label_position="below",
        )

def test_define_plugin_group_requires_id_group_for_controller_preview_box_mode(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            controller_preview_box_mode="max",
        )


def test_define_plugin_group_validates_marker_label_position_token(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefix_group="alerts",
            id_prefixes=["example-"],
            marker_label_position="low",
        )

def test_define_plugin_group_validates_controller_preview_box_mode_token(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefix_group="alerts",
            id_prefixes=["example-"],
            controller_preview_box_mode="largest",
        )


def test_define_plugin_group_requires_store(grouping_store):
    overlay_api.unregister_grouping_store()
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(plugin_group="Example", matching_prefixes=["example-"])
    # Re-register so teardown remains a no-op and future tests get a store.
    overlay_api.register_grouping_store(grouping_store)


def test_define_plugin_group_requires_fields(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(plugin_group="Example")


def test_define_plugin_group_requires_id_group_for_prefixes(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefixes=["example-"],
        )


def test_define_plugin_group_requires_id_prefixes_when_group_absent(grouping_store):
    with pytest.raises(PluginGroupingError):
        overlay_api.define_plugin_group(
            plugin_group="Example",
            id_prefix_group="alerts",
        )


def test_define_plugin_group_supports_background_fields(grouping_store):
    overlay_api.define_plugin_group(
        plugin_group="Example",
        id_prefix_group="alerts",
        id_prefixes=["example-alert-"],
        background_color="#ab12cd",
        background_border_color="red",
        background_border_width=4,
    )

    payload = _load(grouping_store)
    group = payload["Example"]["idPrefixGroups"]["alerts"]
    assert group["backgroundColor"] == "#AB12CD"
    assert group["backgroundBorderColor"] == "red"
    assert group["backgroundBorderWidth"] == 4
