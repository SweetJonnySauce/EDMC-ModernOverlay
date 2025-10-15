# Frequently Asked Questions

## How does the overlay client pick up changes to preferences set in EDMC?

1. The EDMC preferences UI writes changes to `overlay_settings.json` and immediately calls back into the plugin runtime (`overlay_plugin/preferences.py`).
2. Each setter in `_PluginRuntime` updates the in-memory preferences object and pushes an `OverlayConfig` payload through `_send_overlay_config` (`load.py`).
3. The payload is broadcast to every connected socket client by the JSON-over-TCP server (`overlay_plugin/overlay_socket_server.py`).
4. The PyQt overlay keeps a live connection, receiving each JSON line via `OverlayDataClient` (`overlay-client/overlay_client.py`).
5. When the overlay window gets an `OverlayConfig` event in `_on_message`, it applies the updated opacity, scaling, grid, window size, log retention, and status flags immediately (`overlay-client/overlay_client.py`).
6. On startup, the plugin rebroadcasts the current configuration a few times so newly launched clients always get the latest settings, and the client seeds its defaults from `overlay_settings.json` if no update has arrived yet (`load.py`, `overlay-client/overlay_client.py`).

## Why does the overlay stay visible when I alt‑tab out of Elite Dangerous on Windows?

The overlay hides itself when the game window is not foreground. This behavior is controlled by the `force_render` setting:

- `force_render = false` (default): overlay hides when Elite is not the active/foreground window.
- `force_render = true`: overlay remains visible even if Elite loses focus.

You can toggle this via the EDMC preferences panel checkbox labeled "Keep overlay visible when Elite Dangerous is not the foreground window". The overlay client and plugin exchange this value through the regular `OverlayConfig` updates, so changes take effect immediately without restarting.

## Why does the overlay recommend borderless mode on Linux?

When running under X11/Wayland the overlay lets the compositor manage its window so it can stay synced to Elite without tearing. Most compositors only vsync tool windows reliably when the game runs in borderless/fullscreen-windowed mode. If you launch Elite in exclusive fullscreen, the overlay still tracks the game window but the compositor may not present it smoothly. Switch Elite to borderless or enable compositor vsync (e.g. Picom `--vsync`) for the best experience.
