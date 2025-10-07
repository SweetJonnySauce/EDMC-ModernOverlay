# Frequently Asked Questions

## How does the overlay client pick up changes to preferences set in EDMC?

1. The EDMC preferences UI writes changes to `overlay_settings.json` and immediately calls back into the plugin runtime (`overlay_plugin/preferences.py`).
2. Each setter in `_PluginRuntime` updates the in-memory preferences object and pushes an `OverlayConfig` payload through `_send_overlay_config` (`load.py`).
3. The payload is broadcast to every connected socket client by the JSON-over-TCP server (`overlay_plugin/overlay_socket_server.py`).
4. The PyQt overlay keeps a live connection, receiving each JSON line via `OverlayDataClient` (`overlay-client/overlay_client.py`).
5. When the overlay window gets an `OverlayConfig` event in `_on_message`, it applies the updated opacity, scaling, grid, window size, log retention, and status flags immediately (`overlay-client/overlay_client.py`).
6. On startup, the plugin rebroadcasts the current configuration a few times so newly launched clients always get the latest settings, and the client seeds its defaults from `overlay_settings.json` if no update has arrived yet (`load.py`, `overlay-client/overlay_client.py`).

