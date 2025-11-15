# EDMC Modern Overlay (beta)
[![Github All Releases](https://img.shields.io/github/downloads/SweetJonnySauce/EDMC-ModernOverlay/total.svg)](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest)

EDMC Modern Overlay is a cross-platform (Windows and Linux), two-part implementation (plugin and overlay-client) for Elite Dangerous Market Connector ([EDMC](https://github.com/EDCD/EDMarketConnector)). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangrous game. It runs in both borderless and windowed mode.

# Key Features
- Backwards compatibility with [EDMCOverlay](https://github.com/inorton/EDMCOverlay)
- Works in borderless or windowed mode on any display size
- Cross platform for Windows and Linux
- Support 4 distributions for Linux (Debian, Fedora, OpenSUSE, Arch) and can be extended
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
  - Linux (distro aware): `EDMC-ModernOverlay-linux-<version>.tar.gz` – includes `EDMC-ModernOverlay/`, `install_linux.sh`, and the distro manifest `install_matrix.json`. Extract the archive and run `install_linux.sh` from the terminal

## Upgrades
- Grab the latest OS-speific release asset from [GitHub Releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) and re-run the install script (or double click on the exe file). The install file will walk you through the upgrade options.

## Installation Notes
- **Python Environment:** All installations require the overlay-client to have its own python environment. This is required for PyQt support. The installations will automatically build the environment for you. In the case of upgrades, you can chose rebuild the python environment or skip it.

- **EUROCAPS.ttf:** The install asks you to confirm you have a license to install EUROCAPS.ttf. [Why do I need a license for EUROCAPS.ttf?](docs/FAQ.md#why-do-i-need-a-license-for-eurocapsttf)

- **Linux Dependency Packages:** `install_linux.sh` reads `install_matrix.json` and installs the distro-specific prerequisites for the overlay client. The manifest currently checks for and pulls in if necessary:
  - Debian / Ubuntu: `python3`, `python3-venv`, `python3-pip`, `rsync`, `curl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0`, and Wayland helpers `wmctrl`, `x11-utils`
  - Fedora / RHEL / CentOS Stream: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, `libxkbcommon`, `libxkbcommon-x11`, `xcb-util-cursor`, and Wayland helpers `wmctrl`, `xorg-x11-utils`
  - openSUSE / SLE: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0`, and Wayland helpers `wmctrl`, `xprop`
  - Arch / Manjaro / SteamOS: `python`, `python-pip`, `rsync`, `curl`, plus Qt helpers `libxcb`, `xcb-util-cursor`, `libxkbcommon`, and Wayland helpers `wmctrl`, `xorg-xprop`

- **Installation dependency for x11 tools isn't found** If you do a Linux install and you get an error that the x11 dependency can't be found or installed, you may be hitting this [bug](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/issues/15). There isn't a fix for this yet but you may be able to work around this. You specifically need `xwininfo` and `xprop`. If you have those installed, or can install them manually, then you should be able to install without the needed dependency.

- **Flatpack Sandboxing:** The Flatpak version of EDMC runs in a sandboxed environment. The sandboxed environment does not include the packages needed to run the overlay-client. Because of this, the client will be launched outide of the sandboxed environment. You should only run this plugin if you trust the plugin code and the system where it runs.

  > **Caution:** Enabling the host launch runs the overlay client outside the Flatpak sandbox, so it inherits the host user’s privileges. Only do this if you trust the plugin code and the system where it runs.

  Flatpak uses the following override when launching the client:
  ```bash
  flatpak override --env=EDMC_OVERLAY_HOST_PYTHON=/path/to/python io.edcd.EDMarketConnector
  ```

  The Flatpak host launch requires D-Bus access to `org.freedesktop.Flatpak`. Grant it once (per-user if the Flatpak was installed with `--user`):
  ```bash
  flatpak override --user io.edcd.EDMarketConnector --talk-name=org.freedesktop.Flatpak
  ```
  The auto-detection prioritises `EDMC_OVERLAY_HOST_PYTHON`; otherwise it falls back to `overlay-client/.venv/bin/python`.

# More Features

- Background `asyncio` JSON-over-TCP broadcaster that stays off EDMC’s Tk thread and degrades gracefully if the listener cannot bind.
- Watchdog-managed overlay client that restarts the PyQt process after crashes and mirrors EDMC’s logging controls (stdout/stderr capture).
- JSON discovery file (`port.json`) that the overlay reads to locate the active port, removed automatically when the broadcaster is offline.
- Transparent PyQt6 HUD with legacy text, shape, and emoji rendering.
- Custom font support with case-insensitive discovery and a `preferred_fonts.txt` priority list.
- Custom emoji font support with fallback options.
- Public helper API (`overlay_plugin.overlay_api.send_overlay_message`) that validates and forwards payloads from other plugins.
- Drop-in `edmcoverlay` compatibility module for legacy callers.

# Using EDMC-ModernOverlay

## Everyday workflow
1. **Enable the plugin in EDMC.** Install the plugin and resstart EDMC. In EDMC, open `File → Settings → Plugins`, and navigate to `EDMC-ModernOverlay` for user settings
2. **Configure the HUD from EDMC.** Go to `File → Settings → EDMC-ModernOverlay` and adjust:
   - Scaling (`Fit` keeps the original aspect ratio, `Fill` stretches groups proportionally).
   - Whether to show the connection status banner in lower left hand corner plus its gutter/margin in pixels.
   - Debug overlay metrics and the corner they appear in.
   - Font scaling bounds for payload text. This sets the min/max size of the normal font on different display sizes. 
   - Elite title-bar compensation toggle + height. Turn this true if running in windowed mode with a title bar.
   - Nudge overflowing payloads back into view” + gutter. Useful in `Fill` if you find text extending beyond the right or bottom edges of the screen.

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
