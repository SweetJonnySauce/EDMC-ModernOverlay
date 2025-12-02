import logging
from types import SimpleNamespace

import load
import overlay_controller.overlay_controller as oc


def test_plugin_cli_override_reload_dedupes_and_broadcasts():
    published = []
    plugin = SimpleNamespace(
        _last_override_reload_nonce=None,
        _publish_payload=lambda payload: published.append(payload),
    )

    result = load._PluginRuntime._handle_cli_payload(plugin, {"cli": "controller_override_reload", "nonce": "n1"})
    assert result == {"status": "ok"}
    assert published and published[-1]["event"] == "OverlayOverrideReload"
    assert published[-1]["nonce"] == "n1"

    # Duplicate nonce should be ignored, no extra broadcast.
    result_dup = load._PluginRuntime._handle_cli_payload(plugin, {"cli": "controller_override_reload", "nonce": "n1"})
    assert result_dup == {"status": "ok", "duplicate": True}
    assert len(published) == 1


def test_controller_emits_override_reload_with_nonce_and_debounce():
    # Ensure controller logger doesn't install file handlers or disable propagation during test.
    oc._CONTROLLER_LOGGER = logging.getLogger("EDMCModernOverlay.Controller")
    oc._CONTROLLER_LOGGER.propagate = True
    oc._CONTROLLER_LOGGER.handlers.clear()

    sent = []
    fake = SimpleNamespace(
        _last_override_reload_ts=0.0,
        _last_override_reload_nonce=None,
        _send_plugin_cli=lambda payload: sent.append(payload),
    )

    oc.OverlayConfigApp._emit_override_reload_signal(fake)
    assert sent, "Expected reload signal to be sent"
    first = sent[-1]
    assert first.get("cli") == "controller_override_reload"
    nonce = first.get("nonce")
    assert nonce and isinstance(nonce, str)
    assert fake._last_override_reload_nonce == nonce

    # Immediate repeat should be debounced (no additional send)
    oc.OverlayConfigApp._emit_override_reload_signal(fake)
    assert len(sent) == 1
