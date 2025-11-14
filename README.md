# EDMC Modern Overlay (beta)
[![Github All Releases](https://img.shields.io/github/downloads/SweetJonnySauce/EDMC-ModernOverlay/total.svg)](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest)

EDMC Modern Overlay is a cross-platform (Windows and Linux), two-part implementation (plugin and overlay-client) for Elite Dangerous Market Connector ([EDMC](https://github.com/EDCD/EDMarketConnector)). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangrous game. It runs in both borderless and windowed mode.

# Key Features
- Backwards compatibility with [EDMCOverlay](https://github.com/inorton/EDMCOverlay)
- Works in borderless or windowed mode on any display size
- Cross platform for Windows and Linux
- Support 4 distributions for Linux (Debian, Fedora, OpenSuse, Arch) and can be extended
- Supports host and Flatpak installs of EDMC on Linux
- Code is 100% Python
- Numerous development features for EDMC Plugin Developers

# Installation

## Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed
- On Windows, Powershell 3 or greater is required for the installation (both exe or ps1 installations)
- On Windows, Microsoft Visual C++ 14.0 or greater is required. Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/

## Installation
- Grab the latest OS-specific release asset from [GitHub Releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest):
  - Windows (PowerShell script bundle): `EDMC-ModernOverlay-windows_powershell-<version>.zip` – includes `EDMC-ModernOverlay/` plus `install_windows.ps1` so you can inspect and run the script directly. Extract the files and run `install_windows.ps1` in Powershell
  - Windows (standalone EXE): `EDMC-ModernOverlay-windows-<version>.exe`. Download the exe and run it. You will need to accept the "Microsoft Defender SmartScreen prevented an unrecognized app from starting." warning when installing by clicking on "More info..."
  - Linux (Supports Debian, Fedora, OpenSuse, and Arch for both EDMC Base and Flatpak installions): `EDMC-ModernOverlay-linux-<version>.tar.gz` – includes `EDMC-ModernOverlay/`, `install_linux.sh`, and the distro manifest `install_matrix.json`. Extract the archive and run `install_linux.sh` from the terminal.

## Upgrades
- Grab the latest OS-speific release asset from [GitHub Releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) and re-run the install script (or double click on the exe file). The install file will walk you through the upgrade options.

## Installation Notes
- **Python Environment:** All installations require the overlay-client to have its own python environment. This is required for PyQt support. The installations will automatically build the environment for you. In the case of upgrades, you can chose rebuild the python environment or skip it.

- **EUROCAPS.ttf:** The install asks you to confirm you have a license to install EUROCAPS.ttf. [Why do I need a license for EUROCAPS.ttf?](FAQ.md#why-do-i-need-a-license-for-eurocapsttf)

- **Linux Dependency Packages:** `install_linux.sh` reads `scripts/install_matrix.json` and installs the distro-specific prerequisites for the overlay client. The manifest currently for and pulls in if necessary:
  - Debian / Ubuntu: `python3`, `python3-venv`, `python3-pip`, `rsync`, `curl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0`, and Wayland helpers `wmctrl`, `x11-utils`
  - Fedora / RHEL / CentOS Stream: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, `libxkbcommon`, `libxkbcommon-x11`, `xcb-util-cursor`, and Wayland helpers `wmctrl`, `xorg-x11-utils`
  - openSUSE / SLE: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0`, and Wayland helpers `wmctrl`, `xprop`
  - Arch / Manjaro / SteamOS: `python`, `python-pip`, `rsync`, `curl`, plus Qt helpers `libxcb`, `xcb-util-cursor`, `libxkbcommon`, and Wayland helpers `wmctrl`, `xorg-xprop`

- **Flatpack Sandboxing:** The Flatpak version of EDMC runs in a sandboxed environment. The sandboxed environment does not include the packages needed to run the overlay-client. Because of this, the client will be launched using the command `flatpak-spawn --host …/.venv/bin/python overlay_client.py` with `-env` arguements. You should only run this plugin if you trust the plugin code and the system where it runs.

  > **Caution:** Enabling the host launch runs the overlay client outside the Flatpak sandbox, so it inherits the host user’s privileges. Only do this if you trust the plugin code and the system where it runs.

  Flatpak includes th following override when launching the client:
  ```bash
  flatpak override --env=EDMC_OVERLAY_HOST_PYTHON=/path/to/python io.edcd.EDMarketConnector
  ```

  The optional host launch requires D-Bus access to `org.freedesktop.Flatpak`. Grant it once (per-user if the Flatpak was installed with `--user`):
  ```bash
  flatpak override --user io.edcd.EDMarketConnector --talk-name=org.freedesktop.Flatpak
  ```
  The auto-detection prioritises `EDMC_OVERLAY_HOST_PYTHON`; otherwise it falls back to `overlay-client/.venv/bin/python`.

# More Features

- Background `asyncio` JSON-over-TCP broadcaster that stays off EDMC’s Tk thread and degrades gracefully if the listener cannot bind.
- Watchdog-managed overlay client that restarts the PyQt process after crashes and mirrors EDMC’s logging controls (stdout/stderr capture, payload mirroring).
- JSON discovery file (`port.json`) that the overlay reads to locate the active port, removed automatically when the broadcaster is offline.
- Transparent PyQt6 HUD with legacy text/shape rendering, gridlines, window-follow offsets, force-render toggle, and live test messages.
- Custom font support with case-insensitive discovery and a `preferred_fonts.txt` priority list.
- Preferences-driven scaling, window sizing, opacity, and log-retention controls exposed through a myNotebook settings pane.
- Public helper API (`overlay_plugin.overlay_api.send_overlay_message`) that validates and forwards payloads from other plugins.
- Drop-in `edmcoverlay` compatibility module for legacy callers.
- Dedicated rotating client log written under the EDMC logs directory with user-configurable retention.

# Using EDMC-ModernOverlay

## Everyday workflow
1. **Enable the plugin in EDMC.** Open `File → Settings → Plugins`, tick `EDMC-ModernOverlay`, and restart EDMC so it can register the plugin.
2. **Let EDMC manage the overlay process.** On startup the plugin writes `port.json` next to `EDMC-ModernOverlay/` with the TCP port (and `flatpak` metadata when applicable), then `OverlayWatchdog` launches `overlay-client/overlay_client.py` using the bundled virtual environment. The watchdog keeps the PyQt6 overlay alive and automatically restarts it if it crashes, so you never need to run the client manually.
3. **Configure the HUD from EDMC.** Go to `File → Settings → EDMC-ModernOverlay` and adjust:
   - Scaling (`Fit` keeps the original aspect ratio, `Fill` stretches groups proportionally).
   - Whether to show the connection status banner plus its gutter/margin in pixels.
   - Debug overlay metrics and the corner they appear in.
   - Font scaling bounds for payload text, the Elite title-bar compensation toggle + height, and the overflow “nudge back into view” gutter.
   - These preferences are saved to `EDMC-ModernOverlay/overlay_settings.json`, so you can back up or copy that file between machines.
   - Developer builds (versions suffixed with `-dev` or when `MODERN_OVERLAY_DEV_MODE=1`) also reveal a **Developer Settings** block that adds overlay restart/testing buttons, background opacity controls, temporary gridlines, payload cycling, and legacy test payload senders.
4. **Verify connectivity and gather diagnostics.** Toggle the “Show connection status message” setting to display the live status banner in the overlay. Payload activity is logged to `logs/EDMC-ModernOverlay/overlay-payloads.log` (created under `%LOCALAPPDATA%\EDMarketConnector\logs` on Windows or `~/.local/share/EDMarketConnector/logs` on Linux) and rotates according to the `client_log_retention` value sent to the overlay. Advanced users can edit `debug.json` in the plugin directory to enable payload tracing or pipe the overlay client’s stdout/stderr into the EDMC log for troubleshooting.
5. **Keep the virtual environment healthy.** Both installers detect an existing `overlay-client/.venv`, prompt before rebuilding it, and reinstall `overlay-client/requirements.txt`. If the overlay stops launching, re-run the installer (or delete `.venv` and rerun it) so a fresh environment is created with the right dependencies and the watchdog can start the client again.

## Programmatic API

Other plugins within EDMC can publish overlay updates without depending on socket details by using the bundled helper:

```python
from overlay_plugin.overlay_api import send_overlay_message

payload = {
    "event": "TestMessage",
    "message": "Fly safe, CMDR!",
    "timestamp": "2025-10-06T15:42:00Z",
}

if not send_overlay_message(payload):
    # Handle delivery failure (overlay offline, port missing, etc.)
    pass
```

`send_overlay_message()` validates payloads, ensures a timestamp, and routes the message through the running plugin’s broadcaster. It returns `False` if the plugin is inactive or the payload cannot be serialised. Keep payloads small (<16 KB) and include an `event` string so future overlay features can route them.

## `edmcoverlay` Compatibility Layer

Modern Overlay ships with a drop-in replacement for the legacy `edmcoverlay` module. Once this plugin is installed, other plugins can simply:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message("demo", "Hello CMDR", "yellow", 100, 150, ttl=5, size="large")
overlay.send_shape("demo-frame", "rect", "#ffffff", "#40000000", 80, 120, 420, 160, ttl=5)
```

Under the hood the compatibility layer forwards payloads through `send_overlay_message`, so no socket management or process monitoring is required. The overlay client understands the legacy message/rectangle schema, making migration from the original EDMCOverlay plugin largely turnkey.

# Thanks

Special thanks to [inorton](https://github.com/inorton) for the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) development.

# Blame

This EDMC plugin is a learning experiment in using AI for ground up development. My goal was to avoid touching code and only use AI. It was developed on VSCode using Codex (gpt-5-codex) for 99.999% of the code.
