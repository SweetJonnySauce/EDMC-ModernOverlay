from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from overlay_client.controller_mode import ControllerModeProfile, ModeProfile
from overlay_controller.services import GroupStateService, PluginBridge
from overlay_plugin.groupings_loader import GroupingsLoader


@dataclass
class AppContext:
    root: Path
    shipped_path: Path
    user_groupings_path: Path
    cache_path: Path
    settings_path: Path
    port_path: Path
    groupings_loader: GroupingsLoader
    group_state: GroupStateService
    mode_profile: ControllerModeProfile
    controller_heartbeat_ms: int
    plugin_bridge: PluginBridge | None
    force_render_override: object | None
    use_legacy_bridge: bool


def build_app_context(
    *,
    root: Path,
    use_legacy_bridge: bool,
    legacy_force_override_factory: Optional[Callable[[Path], object]] = None,
    logger: Optional[Callable[..., None]] = None,
) -> AppContext:
    shipped_path = root / "overlay_groupings.json"
    user_groupings_raw = os.environ.get("MODERN_OVERLAY_USER_GROUPINGS_PATH", root / "overlay_groupings.user.json")
    user_groupings_path = Path(user_groupings_raw)
    cache_path = root / "overlay_group_cache.json"
    settings_path = root / "overlay_settings.json"
    port_path = root / "port.json"

    groupings_loader = GroupingsLoader(shipped_path, user_groupings_path)
    group_state = GroupStateService(
        root=root,
        shipped_path=shipped_path,
        user_groupings_path=user_groupings_path,
        cache_path=cache_path,
        loader=groupings_loader,
    )
    mode_profile = ControllerModeProfile(
        active=ModeProfile(
            write_debounce_ms=75,
            offset_write_debounce_ms=75,
            status_poll_ms=50,
            cache_flush_seconds=1.0,
        ),
        inactive=ModeProfile(
            write_debounce_ms=200,
            offset_write_debounce_ms=200,
            status_poll_ms=2500,
            cache_flush_seconds=5.0,
        ),
        logger=logger,
    )

    plugin_bridge: PluginBridge | None = None
    force_render_override: object | None = None
    if use_legacy_bridge:
        if legacy_force_override_factory is not None:
            try:
                force_render_override = legacy_force_override_factory(root)
            except Exception:
                force_render_override = None
    else:
        plugin_bridge = PluginBridge(root=root, logger=logger)
        force_render_override = plugin_bridge.force_render_override

    return AppContext(
        root=root,
        shipped_path=shipped_path,
        user_groupings_path=user_groupings_path,
        cache_path=cache_path,
        settings_path=settings_path,
        port_path=port_path,
        groupings_loader=groupings_loader,
        group_state=group_state,
        mode_profile=mode_profile,
        controller_heartbeat_ms=15000,
        plugin_bridge=plugin_bridge,
        force_render_override=force_render_override,
        use_legacy_bridge=use_legacy_bridge,
    )
