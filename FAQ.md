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

### Wayland Support

Modern Overlay now ships with compositor-aware helpers and multiple fallbacks. The plugin publishes the detected session type/compositor in every `OverlayConfig` message, and all decisions are logged when EDMC logging is set to DEBUG. To get the most out of the Wayland path:

- **wlroots compositors (Sway, Wayfire, Hyprland):** Install `pywayland>=0.4.15` inside `overlay-client/.venv` and ensure `swaymsg`/`hyprctl` are available on `PATH`. The client requests a layer-shell surface so the HUD stays above fullscreen apps and uses compositor-side input suppression.
  ```bash
  cd /path/to/EDMC-ModernOverlay
  source overlay-client/.venv/bin/activate
  pip install pywayland
  # swaymsg/hyprctl live under /usr/bin after installing sway or hyprland.
  # Append /usr/bin to PATH (only if not already present):
  if ! echo "$PATH" | tr ':' '\n' | grep -qx '/usr/bin'; then
    echo 'export PATH="/usr/bin:$PATH"' >> ~/.bashrc   # adjust for zsh/fish as needed
  fi
  source ~/.bashrc
  ```
- **KDE Plasma (KWin):** Install `pydbus>=0.6.0` in the client venv so the overlay can talk to KWin’s DBus scripting API when toggling click-through behaviour.
  ```bash
  cd /path/to/EDMC-ModernOverlay
  source overlay-client/.venv/bin/activate
  pip install pydbus
  ```
- **XWayland mode:** On Wayland sessions the overlay forces itself to launch under XWayland for compatibility. Keep this path in mind on GNOME Shell (Wayland), where native layer-shell hooks are not yet available; the overlay behaves like it does on X11 and stays pinned above Elite.
  ```bash
  # Example for Debian/Ubuntu; xprop/xwininfo ship in x11-utils and swaymsg comes with sway.
  sudo apt install wmctrl x11-utils sway
  ```
