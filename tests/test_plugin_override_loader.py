import logging

from overlay_client.plugin_overrides import PluginOverrideManager
from overlay_plugin.groupings_loader import GroupingsLoader


def test_override_manager_uses_loader_merged_view(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped.write_text(
        """
{
  "PluginA": {
    "matchingPrefixes": ["foo-"],
    "idPrefixGroups": {
      "Main": { "idPrefixes": ["foo-"] }
    }
  }
}
""",
        encoding="utf-8",
    )
    user.write_text(
        """
{
  "PluginA": {
    "matchingPrefixes": ["bar-"]
  },
  "PluginB": {
    "matchingPrefixes": ["baz-"]
  }
}
""",
        encoding="utf-8",
    )

    loader = GroupingsLoader(shipped, user)
    manager = PluginOverrideManager(shipped, logging.getLogger("test"), groupings_loader=loader)

    # Trigger reload via loader
    manager._reload_if_needed()

    # User override should win for PluginA
    plugina = manager._plugins.get("plugina")
    assert plugina is not None
    assert plugina.match_id_prefixes[0] == "bar-"
    assert "foo-" in plugina.match_id_prefixes

    # User-only plugin should be present
    pluginb = manager._plugins.get("pluginb")
    assert pluginb is not None
    assert pluginb.match_id_prefixes == ("baz-",)


def test_override_manager_background_from_loader(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped.write_text(
        """
{
  "PluginA": {
    "idPrefixGroups": {
      "Main": {
        "idPrefixes": ["foo-"],
        "backgroundColor": "#112233",
        "backgroundBorderColor": "red",
        "backgroundBorderWidth": 1
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    user.write_text(
        """
{
  "PluginA": {
    "idPrefixGroups": {
      "Main": {
        "backgroundColor": "#AABBCC",
        "backgroundBorderColor": "blue",
        "backgroundBorderWidth": 4
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    loader = GroupingsLoader(shipped, user)
    manager = PluginOverrideManager(shipped, logging.getLogger("test"), groupings_loader=loader)
    manager._reload_if_needed()

    color, border_color, border = manager.group_background("PluginA", "Main")
    assert color == "#AABBCC"
    assert border_color == "blue"
    assert border == 4


def test_override_manager_marker_label_position_from_loader(tmp_path):
    shipped = tmp_path / "overlay_groupings.json"
    user = tmp_path / "overlay_groupings.user.json"

    shipped.write_text(
        """
{
  "PluginA": {
    "idPrefixGroups": {
      "Main": {
        "idPrefixes": ["foo-"],
        "markerLabelPosition": "below"
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    user.write_text(
        """
{
  "PluginA": {
    "idPrefixGroups": {
      "Main": {
        "markerLabelPosition": "above"
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    loader = GroupingsLoader(shipped, user)
    manager = PluginOverrideManager(shipped, logging.getLogger("test"), groupings_loader=loader)
    manager._reload_if_needed()

    assert manager.group_marker_label_position("PluginA", "Main") == "above"
