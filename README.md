# EDMC Modern Overlay
EDMC Modern Overlay is a cross-platform (Windows, Linux X11 on Gnome), two-part implementation (plugin and overlay-client) for Elite Dangerous Market Connector (EDMC). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangrous game. It has been tested on Ubuntu 24.04.03 LTS (X11, and some Wayland) and Windows 10.

## Installation

### Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed
- On Windows Microsoft Visual C++ 14.0 or greater is required. Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/

### Download
- Grab the latest OS-specific archive from GitHub Releases:
  - Windows: `EDMC-ModernOverlay-windows-<version>.zip`
  - Linux: `EDMC-ModernOverlay-linux-<version>.tar.gz`
- Extract the archive to a folder of your choice. The extracted folder contains:
  - `EDMC-ModernOverlay/` (the plugin and overlay client code)
  - Platform install helpers at the archive root:
    - Windows: `install_windows.ps1`, `install-eurocaps.bat`
    - Linux: `install_linux.sh`, `install-eurocaps.sh`

### Windows
- Close EDMarketConnector.
- In the extracted folder, right-click `install_windows.ps1` and choose **Run with PowerShell**.
- Follow the on-screen prompts; the installer handles the rest (except installation of the Euroscripts font).
- The installer will:
  - Detect (or prompt for) the EDMC plugins directory (defaults to `%LOCALAPPDATA%\EDMarketConnector\plugins`).
  - Disable legacy `EDMCOverlay*` plugins if found.
  - Copy `EDMC-ModernOverlay/` into the plugins directory.
  - Create `overlay-client\.venv` and install `overlay-client\requirements.txt` into it.
- Start EDMarketConnector; the overlay client launches automatically.

### Linux
- Close EDMarketConnector before installing.
- Make sure you have Python 3 and venv support available (e.g. on Debian/Ubuntu: `sudo apt install python3 python3-venv`).
- From the extracted folder, run the installer:
  - `./install_linux.sh` (ensure it’s executable) or `bash ./install_linux.sh`
- Follow the on-screen prompts; the installer handles the rest (except installation of the Euroscripts font).
- The installer will:
  - Detect (or prompt for) the EDMC plugins directory (defaults to `~/.local/share/EDMarketConnector/plugins/`).
  - Disable legacy `EDMCOverlay*` plugins if found.
  - Copy `EDMC-ModernOverlay/` into the plugins directory.
  - Create `overlay-client/.venv` and install `overlay-client/requirements.txt` into it.
- Start EDMarketConnector; the overlay client launches automatically.

### Installing Euroscripts font
To use the Elite: Dangerous cockpit font (Eurocaps) in the overlay HUD:

You can automate the download and placement with the bundled helpers:

- Linux: `scripts/install-eurocaps.sh` *(optionally pass the plugin path if it isn't under `~/.local/share/EDMarketConnector/plugins/`)*
- Windows: `scripts\install-eurocaps.bat` *(optionally pass the plugin path if it isn't under `%LOCALAPPDATA%\EDMarketConnector\plugins\`)*

Both scripts verify the plugin directory, fetch `Eurocaps.ttf`, copy it into `overlay-client/fonts/`, and add it to `preferred_fonts.txt` when that file exists.

To perform the steps manually instead:

1. Download `EUROCAPS.TTF` from https://github.com/inorton/EDMCOverlay/blob/master/EDMCOverlay/EDMCOverlay/EUROCAPS.TTF.
2. Place the file in `overlay-client/fonts/` and rename it to `Eurocaps.ttf` (the overlay searches case-insensitively, but keeping a consistent casing is handy). Include the original licence text alongside it if you have one.
3. Add `Eurocaps.ttf` to `overlay-client/fonts/preferred_fonts.txt` to prioritise it over the bundled Source Sans 3, or leave the list untouched to let the overlay fall back automatically.
4. Restart the overlay client; the new font is picked up the next time it connects.

Need the reasoning behind the optional install? See [Why isn't the Eurocaps font installed automatically?](FAQ.md#why-isnt-the-eurocaps-font-installed-automatically).

## Update

To upgrade to a newer release:

1. Close EDMarketConnector so the plugin and overlay shut down cleanly.
2. Download the latest archive from GitHub Releases and extract it alongside the existing version.
3. Run the platform installer again (`install_windows.ps1` or `install_linux.sh`). The script automatically replaces the plugin files while keeping your existing `overlay-client/.venv`, `overlay_settings.json`, and any fonts you added under `overlay-client/fonts/`.
4. Restart EDMarketConnector and confirm the reported version matches the release notes (the overlay status line also shows the active build).

## Features

- Background `asyncio` JSON-over-TCP broadcaster that stays off EDMC’s Tk thread and degrades gracefully if the listener cannot bind.
- Watchdog-managed overlay client that restarts the PyQt process after crashes and mirrors EDMC’s logging controls (stdout/stderr capture, payload mirroring).
- JSON discovery file (`port.json`) that the overlay reads to locate the active port, removed automatically when the broadcaster is offline.
- Transparent PyQt6 HUD with legacy text/shape rendering, gridlines, window-follow offsets, force-render toggle, and live test messages.
- Custom font support with case-insensitive discovery and a `preferred_fonts.txt` priority list.
- Preferences-driven scaling, window sizing, opacity, and log-retention controls exposed through a myNotebook settings pane.
- Public helper API (`overlay_plugin.overlay_api.send_overlay_message`) that validates and forwards payloads from other plugins.
- Drop-in `edmcoverlay` compatibility module for legacy callers.
- Dedicated rotating client log written under the EDMC logs directory with user-configurable retention.

## Windows Manual Setup
If you want to set up EDMC-ModernOverlay manually on Windows, follow these steps.

The overlay client lives inside the plugin directory and expects a virtual environment at `overlay-client\.venv`. Create it locally before starting the plugin in EDMC.

1. Set up the client Python environment using PowerShell (press `Win`+`X`, choose *Windows PowerShell* or *Terminal*, then run the commands; default plugin path is `%LOCALAPPDATA%\EDMarketConnector\plugins\`):
   ```powershell
   Set-Location "$env:LOCALAPPDATA\EDMarketConnector\plugins"
   cd .\EDMC-ModernOverlay
   py -3 -m venv overlay-client\.venv
   overlay-client\.venv\Scripts\Activate.ps1
   ```
2. Install the client dependencies while the environment is active:
   ```powershell
   pip install -r overlay-client\requirements.txt
   ```
3. Copy the entire plugin (including `overlay-client\`) into the EDMC plugin directory if it's not already there:
   ```
   %LOCALAPPDATA%\EDMarketConnector\plugins\EDMCModernOverlay\
   ```
4. Launch EDMC. The plugin spins up the broadcaster, writes `port.json` when the listener is online, and supervises the overlay client. If the port is already taken the plugin stays loaded and logs that it is running in degraded mode until the port becomes free.
5. Configure the plugin via *File → Settings → EDMC-ModernOverlay* (see “Configuration” below for option details).

## Linux Manual Setup
If you want to set up EDMC-ModernOverlay manually on Windows, follow these steps.

The client expects a Python virtual environment at `overlay-client/.venv`. Create it locally before deploying into EDMC.

1. In bash (default plugin path is `~/.local/share/EDMarketConnector/plugins/`; adjust if you use a custom location):
   ```bash
   cd /path/to/EDMC-ModernOverlay
   python3 -m venv overlay-client/.venv
   source overlay-client/.venv/bin/activate
   ```
2. Install the client dependencies while the environment is active:
   ```bash
   pip install -r overlay-client/requirements.txt
   ```
3. Install Qt helper libraries (required by PyQt6 on most distros):
   ```bash
   sudo apt-get update
   sudo apt-get install libxcb-cursor0 libxkbcommon-x11-0
   ```
4. Copy the entire plugin (including `overlay-client/`) into:
   ```
   ~/.local/share/EDMarketConnector/plugins/EDMCModernOverlay/
   ```
5. Launch EDMC. The plugin starts the broadcaster, writes `port.json` when the listener is available, and supervises the overlay client. If the port is occupied, the plugin stays loaded and logs that it is running in degraded mode until the port frees up.
6. Configure the plugin via *File → Settings → EDMC-ModernOverlay* (see “Configuration” below for option details).

## Using EDMC-ModernOverlay

### Programmatic API

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

### `edmcoverlay` Compatibility Layer

Modern Overlay ships with a drop-in replacement for the legacy `edmcoverlay` module. Once this plugin is installed, other plugins can simply:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message("demo", "Hello CMDR", "yellow", 100, 150, ttl=5, size="large")
overlay.send_shape("demo-frame", "rect", "#ffffff", "#40000000", 80, 120, 420, 160, ttl=5)
```

Under the hood the compatibility layer forwards payloads through `send_overlay_message`, so no socket management or process monitoring is required. The overlay client understands the legacy message/rectangle schema, making migration from the original EDMCOverlay plugin largely turnkey.

## Thanks

Special thanks to [inorton](https://github.com/inorton) for the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) development.

## Blame

This EDMC plugin is an experiment in using AI for ground up development. It was developed on VSCode using Codex (gpt-5-codex) for 100% of the code.
