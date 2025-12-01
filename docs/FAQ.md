# Frequently Asked Questions

## How is the Project Laid Out?

```
EDMCModernOverlay/
├── README.md                       # Install & usage guide
├── docs/
│   ├── FAQ.md                      # Expanded setup and troubleshooting notes
│   ├── build.md                    # Build helpers and packaging notes
│   ├── developer.md                # Development tips and versioning details
│   └── (more renderer/layout docs)
├── DEV.md                          # Historical root copy (kept for compatibility)
├── LICENSE                         # Project licensing
├── .gitignore                      # Ignore rules (see note on respecting them)
├── EDMC-ModernOverlay.code-workspace  # Optional VS Code workspace definition
├── .codex/
│   └── agents.md                   # Codex CLI agent metadata
├── .github/
│   └── workflows/
│       └── release.yml             # GitHub Actions release pipeline
├── .vscode/
│   ├── launch.json                 # Recommended debug configuration
│   └── settings.json               # Workspace settings
├── __init__.py                     # Package marker for EDMC imports
├── edmcoverlay.py                  # Legacy shim module (`import edmcoverlay`)
├── EDMCOverlay/                    # Package form of the legacy shim
│   ├── __init__.py
│   └── edmcoverlay.py
├── load.py                         # EDMC entry hook copied into the plugins dir
├── overlay_plugin/                 # Runtime that runs inside EDMC
│   ├── __init__.py
│   ├── overlay_api.py              # Helper API for other plugins
│   ├── overlay_socket_server.py    # JSON-over-TCP broadcaster
│   ├── overlay_watchdog.py         # Subprocess supervisor for the client
│   ├── preferences.py              # myNotebook-backed settings panel
│   └── requirements.txt            # Runtime dependency stub (stdlib today)
├── overlay_client/                 # Stand-alone PyQt6 overlay process
│   ├── overlay_client.py           # Main window and socket bridge
│   ├── client_config.py            # Bootstrap defaults and OverlayConfig parsing
│   ├── platform_integration.py     # Window stacking/input helpers per platform
│   ├── developer_helpers.py        # Dev utilities and logging helpers
│   ├── window_tracking.py          # Elite Dangerous window tracking helpers
│   ├── requirements.txt            # Client dependency list (PyQt6, etc.)
│   └── fonts/
│       ├── README.txt
│       ├── preferred_fonts.txt     # Optional case-insensitive priority list
│       ├── SourceSans3-Regular.ttf
│       └── SourceSans3-OFL.txt
├── overlay_settings.json           # Sample preferences persisted by the plugin
├── scripts/                        # Helper scripts for common setup tasks
│   ├── install-eurocaps.bat        # Windows font installer helper
│   └── install_linux.sh            # Linux installer & font wrapper
└── version.py                      # Central version metadata for releases
```

## Does the plug in follow EDMC guidelines for good plugin development?

- Implements the documented EDMC hooks (`plugin_start3`, `plugin_stop`, `plugin_prefs`, `prefs_changed`, `journal_entry`); `plugin_app` explicitly returns `None`, so the Tk main thread stays idle.
- Long-running work stays off the Tk thread. `WebSocketBroadcaster` runs on a daemon thread with its own asyncio loop, `OverlayWatchdog` supervises the client on another daemon thread, and `plugin_stop()` stops both and removes `port.json`.
- Plugin-owned timers are guarded by `_config_timer_lock`, keeping rebroadcast scheduling thread-safe across shutdowns and restarts.
- Plugin state lives inside this directory. `Preferences` reads and writes `overlay_settings.json`, while developer-only toggles (payload mirroring, tracing, stdout/stderr capture) live in `debug.json` and are only honoured in dev builds.
- Logging integrates with EDMC’s logger via `_EDMCLogHandler`; optional payload mirroring and stdout/stderr capture are controlled via `debug.json` and still emit additional detail only when EDMC logging is set to DEBUG.
- The overlay client launches with the dedicated `overlay_client/.venv` interpreter (or an override via `EDMC_OVERLAY_PYTHON`), keeping EDMC’s bundled Python environment untouched.
- Other plugins publish safely through `overlay_plugin.overlay_api.send_overlay_message`, which validates payload structure and size before handing messages to the broadcaster.
- Platform-aware paths handle Windows-specific interpreter names and window flags while keeping Linux/macOS support intact.

**Why are JSON preferences handled outside of EDMC?** The PyQt overlay process runs outside EDMC’s Python interpreter and reads `overlay_settings.json` directly so it can pick up the latest settings without importing EDMC modules. Storing the preferences here keeps a single source of truth that both the plugin and the external client can access.

## Why do I need a license for EUROCAPS.ttf

Eurocaps ships with Elite: Dangerous, but its redistribution rights are tied to Typodermic’s “Font Software for Desktop End User License Agreement (v230123)” (https://typodermicfonts.com/end-user-license-agreement). Because we can’t grant you that license, the installer now asks **you** to confirm that you already have the rights to use Eurocaps before it downloads the font. If you say no, the install continues with the bundled open-source fonts instead. Windows users can still run `scripts\install-eurocaps.bat`; Linux users just re-run `install_linux.sh` and accept the Eurocaps prompt when they’re ready.

## Emoji characters show up as squares. How do I fix it?

Source Sans 3 (the default HUD font) does not include emoji glyphs, so 📝 and friends render as tofu unless a fallback font is configured. Drop an emoji-capable font such as [Noto Color Emoji](https://github.com/googlefonts/noto-emoji) into `overlay_client/fonts/` and list it in `overlay_client/fonts/emoji_fallbacks.txt`. Each line can reference either a font file in that directory (`NotoColorEmoji.ttf`) or an installed family name (`Segoe UI Emoji`, `Twemoji Mozilla`, etc.). The overlay loads the fonts at startup and automatically falls back to the first family that contains the requested glyph, so messages published by plugins can freely include emoji once the font is available.

## PowerShell says scripts are disabled. How do I run `install_windows.ps1`?

If Windows blocks the installer, unblock the file or relax your execution policy for the current session:

- Right-click the ZIP before extracting and choose **Properties → Unblock**, or run `Unblock-File .\install_windows.ps1` inside the extracted folder.
- Run one of the following commands from PowerShell and then launch the script:
  - `powershell -ExecutionPolicy Bypass -File .\install_windows.ps1`
  - `Set-ExecutionPolicy -Scope Process Bypass -Force; .\install_windows.ps1`

These options avoid permanently lowering your global execution-policy settings.

## How do I confirm the Windows installation worked?

Run these checks after the installer finishes (replace paths if you customised the plugin directory):

- `Test-Path "$env:LOCALAPPDATA\EDMarketConnector\plugins\EDMCModernOverlay\overlay_client\.venv\Scripts\python.exe"`
- `Get-Content "$env:LOCALAPPDATA\EDMarketConnector\plugins\EDMCModernOverlay\port.json"` while EDMC is running the plugin.

## How does the overlay client pick up changes to preferences set in EDMC?

1. The EDMC preferences UI writes changes to `overlay_settings.json` and immediately calls back into the plugin runtime (`overlay_plugin/preferences.py`).
2. Each setter in `_PluginRuntime` updates the in-memory preferences object and pushes an `OverlayConfig` payload through `_send_overlay_config` (`load.py`).
3. The payload is broadcast to every connected socket client by the JSON-over-TCP server (`overlay_plugin/overlay_socket_server.py`).
4. The PyQt overlay keeps a live connection, receiving each JSON line via `OverlayDataClient` (`overlay_client/data_client.py`).
5. When the overlay window gets an `OverlayConfig` event in `_on_message`, it applies the updated opacity, scaling, grid, window size, log retention, and status flags immediately (`overlay_client/overlay_client.py`).
6. On startup, the plugin rebroadcasts the current configuration a few times so newly launched clients always get the latest settings, and the client seeds its defaults from `overlay_settings.json` if no update has arrived yet (`load.py`, `overlay_client/overlay_client.py`).

## Why does the overlay stay visible when I alt‑tab out of Elite Dangerous on Windows?

The overlay hides itself when the game window is not foreground. This behavior is controlled by the `force_render` setting.

- `force_render = false` (default): overlay hides when Elite is not the active/foreground window.
- `force_render = true`: overlay remains visible even if Elite loses focus.

You can toggle this via the EDMC preferences panel checkbox labeled "Keep overlay visible when Elite Dangerous is not the foreground window". The overlay client and plugin exchange this value through the regular `OverlayConfig` updates, so changes take effect immediately without restarting.

## Why does the overlay recommend borderless mode on Linux?

When running under X11/Wayland the overlay lets the compositor manage its window so it can stay synced to Elite without tearing. Most compositors only vsync tool windows reliably when the game runs in borderless/fullscreen-windowed mode. If you launch Elite in exclusive fullscreen, the overlay still tracks the game window but the compositor may not present it smoothly. Switch Elite to borderless or enable compositor vsync (e.g. Picom `--vsync`) for the best experience.

### Wayland Support

Modern Overlay now ships with compositor-aware helpers and multiple fallbacks. The plugin publishes the detected session type/compositor in every `OverlayConfig` message, and all decisions are logged when EDMC logging is set to DEBUG. To get the most out of the Wayland path:

- **wlroots compositors (Sway, Wayfire, Hyprland):** Install `pywayland>=0.4.15` inside `overlay_client/.venv` and ensure `swaymsg`/`hyprctl` are available on `PATH`. The client requests a layer-shell surface so the HUD stays above fullscreen apps and uses compositor-side input suppression.
  ```bash
  cd /path/to/EDMCModernOverlay
  source overlay_client/.venv/bin/activate
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
  cd /path/to/EDMCModernOverlay
  source overlay_client/.venv/bin/activate
  pip install pydbus
  ```
- **XWayland mode:** On Wayland sessions the overlay forces itself to launch under XWayland for compatibility. Keep this path in mind on GNOME Shell (Wayland), where native layer-shell hooks are not yet available; the overlay behaves like it does on X11 and stays pinned above Elite.
  ```bash
  # Example for Debian/Ubuntu; xprop/xwininfo ship in x11-utils and swaymsg comes with sway.
  sudo apt install wmctrl x11-utils sway
  ```
