# EDMC Modern Overlay (beta)
[![Github All Releases](https://img.shields.io/github/downloads/SweetJonnySauce/EDMCModernOverlay/total.svg)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![GitHub Latest Version](https://img.shields.io/github/v/release/SweetJonnySauce/EDMCModernOverlay)](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/latest)
[![Build Status][build-badge]][build-url]

[build-badge]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml/badge.svg?branch=main
[build-url]: https://github.com/SweetJonnySauce/EDMCModernOverlay/actions/workflows/ci.yml


EDMC Modern Overlay (packaged as `EDMCModernOverlay`) is a drop-in replacement for [EDMCOverlay](https://github.com/inorton/EDMCOverlay) and [edmcoverlay2](https://github.com/pan-mroku/edmcoverlay2). It is a cross-platform (Windows and Linux), two-part implementation (plugin and overlay client) for Elite Dangerous Market Connector ([EDMC](https://github.com/EDCD/EDMarketConnector)). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangerous game. It runs in both fullscreen borderless and windowed mode on any display size. The [plugin releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) ship with both Windows and Linux installers.

Plugin authors can leverage EDMC Modern Overlay's flexible payload grouping system to precisely control where their overlays appear. By specifying properties like `anchor`, `justify`, and explicit `x`/`y` coordinates in their group definitions, authors can define the placement, alignment, and justification of HUD elements relative to any corner, side, or the center of the screen. The overlay interprets these fields to allow left, right, and center justification, vertical/horizontal anchoring, as well as pixel or percentage-based coordinates for fine-grained positioning—enabling complex, fully-customized HUD layouts for different use cases.

> ⚠️ **Breaking upgrade notice:** Modern Overlay as of 0.7.4 now installs into the `EDMCModernOverlay/` directory. Running the installer will disable any existing `EDMC-ModernOverlay/` folder by renaming it to `EDMC-ModernOverlay.disabled`, `EDMC-ModernOverlay.1.disabled`, etc. Settings are **not** migrated automatically; keep the disabled folder if you need to roll back.

<img width="1957" height="1260" alt="image" src="https://github.com/user-attachments/assets/f17a2a83-1e5c-4556-af65-1053dba38cff" />

# Key Features
- Backwards compatibility with [EDMCOverlay](https://github.com/inorton/EDMCOverlay)
- Custom placement of Plugin overlays using the Overlay Controller (see below)
- Works in borderless or windowed mode on any display size
- Cross platform for Windows and Linux
- Support 4 distributions for Linux (Debian, Fedora, OpenSUSE, Arch)
- Supports host and Flatpak installs of EDMC on Linux
- Code is 100% Python
- Numerous development features for EDMC Plugin Developers

## Overlay Controller
- Type `!ovr` in the in-game Comms panel on any channel to launch
- Change X/Y position via selectors on the screen with "pinning" capabilities (i.e. hug an edge of the screen)
- Change absolute X/Y values using px or % values
- Change the anchor point on the group to define where and how it's placed. Anchor points include nw, top, ne, right, se, bottom, sw, left, center.
- Change justification within the payload (doesn't work on vector based images)
- A preview window can be expanded with the right arrow (when a widget is not in focus) to see original placement, actual placement, and target.

<img width="1147" height="677" alt="image" src="https://github.com/user-attachments/assets/618f06c2-18da-4bdc-b148-035921f7dcdb" />

# Installation

## Prerequisites

- Python 3.10+
- Elite Dangerous Market Connector installed
- On Windows, Powershell 3 or greater is required for the installation (both exe or ps1 installations)

## Installation
- Grab the latest OS-specific release asset from [GitHub Releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest):
  - Windows (PowerShell script bundle): `EDMCModernOverlay-windows_powershell-<version>.zip` – includes `EDMCModernOverlay/` plus `install_windows.ps1` so you can inspect and run the script directly. Extract the files and run `install_windows.ps1` in PowerShell.
  - Windows (standalone EXE): `EDMCModernOverlay-windows-<version>.exe`. Download the EXE and run it. You will need to accept the "Microsoft Defender SmartScreen prevented an unrecognized app from starting." warning when installing by clicking on "More info..."
  - Linux (distro aware): `EDMCModernOverlay-linux-<version>.tar.gz` – includes `EDMCModernOverlay/`, `install_linux.sh`, and the distro manifest `install_matrix.json`. Extract the archive and run `install_linux.sh` from the terminal.

## Upgrades
- Grab the latest OS-specific release asset from [GitHub Releases](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/releases/latest) and re-run the install script (or double click on the EXE file). The installer disables the old `EDMC-ModernOverlay` directory and deploys a fresh `EDMCModernOverlay` folder with no automatic settings migration.

## Installation Notes
- **Python Environment:** All installations require the overlay client to have its own python environment. This is required for PyQt support. The installations will automatically build the environment for you. In the case of upgrades, you can chose rebuild the python environment or skip it.

- **EUROCAPS.ttf:** The install asks you to confirm you have a license to install EUROCAPS.ttf. [Why do I need a license for EUROCAPS.ttf?](docs/FAQ.md#why-do-i-need-a-license-for-eurocapsttf)

- **Integrity checks:** Releases ship a `checksums.txt` manifest. Both installers (`install_linux.sh` and `install_windows.ps1`) verify the extracted bundle and the installed plugin files against that manifest; if verification fails, re-download the release and re-run the installer.

- **Linux Dependency Packages:** `install_linux.sh` reads `install_matrix.json` and installs the distro-specific prerequisites for the overlay client. The manifest currently checks for and pulls in if necessary:
  - Debian / Ubuntu: `python3`, `python3-venv`, `python3-pip`, `rsync`, `curl`, `wmctrl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0` and Wayland helpers `x11-utils`
  - Fedora / RHEL / CentOS Stream: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, `wmctrl`, `libxkbcommon`, `libxkbcommon-x11`, `xcb-util-cursor`, and Wayland helpers `xwininfo`, `xprop`
  - openSUSE / SLE: `python3`, `python3-pip`, `python3-virtualenv`, `rsync`, `curl`, `wmctrl`, plus Qt helpers `libxcb-cursor0`, `libxkbcommon-x11-0`, and Wayland helpers `xprop`, `xwininfo`
  - Arch / Manjaro / SteamOS: `python`, `python-pip`, `rsync`, `curl`, `wmctrl`, plus Qt helpers `libxcb`, `xcb-util-cursor`, `libxkbcommon`, and Wayland helpers `xorg-xprop`, `xorg-xwininfo`
  - Wayland-only Python dependency `pydbus` is installed inside `overlay_client/.venv` from `overlay_client/requirements/wayland.txt` when a Wayland session is detected; no system package is required.
  
- **Compositor-aware overrides (Linux):** `install_linux.sh` detects your compositor (via `install_matrix.json`) and can offer compositor-specific env overrides (e.g., Qt scaling tweaks on KDE/Wayland). Use `--compositor auto|<id>|none` to control this and `--yes` to auto-apply. Accepted overrides are stored in `overlay_client/env_overrides.json` with provenance; user-set env vars always win at runtime. Force Xwayland is only set when the manifest entry requests it.

- **Installation dependency for x11 tools isn't found** If you do a Linux install and you get an error that the x11 dependency can't be found or installed, you may be hitting this [bug](https://github.com/SweetJonnySauce/EDMC-ModernOverlay/issues/15). There isn't a fix for this yet but you may be able to work around this. You specifically need `xwininfo` and `xprop`. If you have those installed, or can install them manually, then you should be able to install without the needed dependency.

- **Flatpack Sandboxing:** The Flatpak version of EDMC runs in a sandboxed environment. The sandboxed environment does not include the packages needed to run the overlay client. Because of this, the client will be launched outside of the sandboxed environment. You should only run this plugin if you trust the plugin code and the system where it runs.

  > **Caution:** Enabling the host launch runs the overlay client outside the Flatpak sandbox, so it inherits the host user’s privileges. Only do this if you trust the plugin code and the system where it runs.

- **Flatpak D-Bus access:** Running the plugin via Flatpak EDMC requires a user permission to be added to enable D-Bus access to `org.freedesktop.Flatpak`. The Linux installer now detects for this and prompts you to grant permission. It does not automatically grant that permission. This is needed because the plugin client uses the following override when launching the client:
  ```bash
  flatpak override --env=EDMC_OVERLAY_HOST_PYTHON=/path/to/python io.edcd.EDMarketConnector
  ```

  The Flatpak host launch requires D-Bus access to `org.freedesktop.Flatpak`. Grant it once (per-user if the Flatpak was installed with `--user`):
  ```bash
  flatpak override --user io.edcd.EDMarketConnector --talk-name=org.freedesktop.Flatpak
  ```
  The auto-detection prioritises `EDMC_OVERLAY_HOST_PYTHON`; otherwise it falls back to `overlay_client/.venv/bin/python`.

# Using EDMC Modern Overlay

## Everyday workflow
1. **Enable the plugin in EDMC.** Install the plugin and restart EDMC. In EDMC, open `File → Settings → Plugins`, and navigate to `EDMCModernOverlay` for user settings.
2. **Configure the HUD from EDMC.** Go to `File → Settings → EDMCModernOverlay` and adjust:
   - Whether to show the connection status banner in lower left hand corner plus its gutter/margin in pixels.
   - Font scaling bounds for payload text. This sets the min/max size of the normal font on different display sizes. 
   - Elite title-bar compensation toggle + height. Turn this true if running in windowed mode with a title bar.
   - Nudge overflowing payloads back into view” + gutter. Useful if you find text extending beyond the edges of the screen.
   
## Programmatic API

> ⚠️ **Caution: Here Be Dragons!**
> The `send_overlay_message` API will most likely be changed or made private for the compatibility shim layer. It has not been fully developed or tested in order to priotitize work on backwards compatibility with the very capable `edmcoverlay` legacy API (described below). Use this at your own risk.

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

Modern Overlay ships with a drop-in replacement for the legacy `edmcoverlay` module. Even though it says "legacy" this is still the preferred method of sending payloads to the Modern Overlay since it helps ensure your plugin will work with `edmcoverlay` as well. Once this plugin is installed, other plugins can simply:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message("demo", "Hello CMDR", "yellow", 100, 150, ttl=5, size="large")
overlay.send_shape("demo-frame", "rect", "#ffffff", "#40000000", 80, 120, 420, 160, ttl=5)
```

Under the hood the compatibility layer forwards payloads through `send_overlay_message`, so no socket management or process monitoring is required. The overlay client understands the legacy message/rectangle schema, making migration from the original EDMCOverlay plugin largely turnkey.

# Support

Best way to get support for this plugin is to create a github issue in this repo. This is a side project for me. As such, support is best effort only and there is no guarantee I'll be able to fix or fully address your issue/request. You can occassionally find me on [EDCD Discord](https://edcd.github.io/) in the `#edmc-plugins` channel.

# Thanks

Special thanks to [inorton](https://github.com/inorton) for the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) development.

# Blame

First and foremost, this EDMC plugin is a learning experiment in using AI for ground up development. The intent was never to get it to this point, but here we are. My goal was to avoid touching code and only use AI, and I've been very successful in reaching that goal. It was developed on VSCode using Codex (gpt-5-codex) for 99.999% of the code.
