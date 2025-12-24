import json

from utils.plugin_group_manager import GroupConfigStore


def test_add_grouping_enforces_unique_prefixes(tmp_path):
    path = tmp_path / "overlay_groupings.json"
    path.write_text("{}", encoding="utf-8")
    store = GroupConfigStore(path)

    store.add_group(name="PluginX", notes=None, match_prefixes=["pluginx-"])
    store.add_grouping(
        group_name="PluginX",
        label="GroupA",
        prefixes=["shared-"],
        anchor="nw",
        notes=None,
    )
    store.add_grouping(
        group_name="PluginX",
        label="GroupB",
        prefixes=["shared-"],
        anchor="ne",
        notes=None,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data["PluginX"]["idPrefixGroups"]
    group_a_prefixes = groups["GroupA"].get("idPrefixes", [])

    assert "shared-" not in group_a_prefixes
    assert groups["GroupB"]["idPrefixes"] == ["shared-"]


def test_update_group_lowercases_matching_prefixes(tmp_path):
    path = tmp_path / "overlay_groupings.json"
    path.write_text("{}", encoding="utf-8")
    store = GroupConfigStore(path)

    store.add_group(name="MyPlugin", notes=None, match_prefixes=["Foo-"])
    store.update_group("MyPlugin", match_prefixes=["Bar-"])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["MyPlugin"]["matchingPrefixes"] == ["bar-"]
