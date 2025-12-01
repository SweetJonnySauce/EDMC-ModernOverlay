from overlay_client.platform_context import _initial_platform_context


class _Initial:
    def __init__(self, force_xwayland: bool) -> None:
        self.force_xwayland = force_xwayland


def test_initial_platform_context_prefers_env(monkeypatch):
    monkeypatch.setenv("EDMC_OVERLAY_FORCE_XWAYLAND", "0")
    monkeypatch.setenv("EDMC_OVERLAY_SESSION_TYPE", "wayland")
    monkeypatch.setenv("EDMC_OVERLAY_COMPOSITOR", "kwin")
    monkeypatch.setenv("EDMC_OVERLAY_IS_FLATPAK", "1")
    monkeypatch.setenv("EDMC_OVERLAY_FLATPAK_ID", "app.id")

    ctx = _initial_platform_context(_Initial(force_xwayland=False))
    assert ctx.session_type == "wayland"
    assert ctx.compositor == "kwin"
    assert ctx.flatpak is True
    assert ctx.flatpak_app == "app.id"
    assert ctx.force_xwayland is False


def test_initial_platform_context_respects_force(monkeypatch):
    monkeypatch.delenv("EDMC_OVERLAY_FORCE_XWAYLAND", raising=False)
    ctx = _initial_platform_context(_Initial(force_xwayland=True))
    assert ctx.force_xwayland is True
