from __future__ import annotations

from overlay_controller.controller import build_app_context


def test_build_app_context_paths_and_bridge(tmp_path, monkeypatch):
    shipped = tmp_path / "overlay_groupings.json"
    shipped.write_text("{}", encoding="utf-8")
    user = tmp_path / "custom.user.json"
    monkeypatch.setenv("MODERN_OVERLAY_USER_GROUPINGS_PATH", str(user))

    ctx = build_app_context(root=tmp_path, logger=lambda *_args, **_kwargs: None)

    assert ctx.shipped_path == shipped
    assert ctx.user_groupings_path == user
    assert ctx.cache_path == tmp_path / "overlay_group_cache.json"
    assert ctx.settings_path == tmp_path / "overlay_settings.json"
    assert ctx.port_path == tmp_path / "port.json"
    assert ctx.plugin_bridge is not None
    assert ctx.force_render_override is ctx.plugin_bridge.force_render_override
    active = ctx.mode_profile.resolve("active")
    inactive = ctx.mode_profile.resolve("inactive")
    assert active.write_debounce_ms == 75
    assert inactive.status_poll_ms == 2500
