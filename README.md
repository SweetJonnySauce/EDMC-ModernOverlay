# EDMC Modern Overlay
EDMC Modern Overlay is a two-part implementation (plugin and overlay-client) for Elite Dangerous Market Connector (EDMC). It streams data from EDMC plugins over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on the Elite Dangrous game.

## Installation

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
- Close EDMarketConnector before installing.
- Open PowerShell in the extracted folder and run one of:
  - `powershell -ExecutionPolicy Bypass -File .\install_windows.ps1` (one-off, does not change your policy)
  - `Set-ExecutionPolicy -Scope Process Bypass -Force; .\install_windows.ps1`
  - If you prefer no bypass, right‑click the ZIP before extracting and Unblock it, or run `Unblock-File .\install_windows.ps1`, then `./install_windows.ps1`.
- The installer will:
  - Detect (or prompt for) the EDMC plugins directory (defaults to `%LOCALAPPDATA%\EDMarketConnector\plugins`).
  - Disable legacy `EDMCOverlay*` plugins if found.
  - Copy `EDMC-ModernOverlay/` into the plugins directory.
  - Create `overlay-client\.venv` and install `overlay-client\requirements.txt` into it.
- Optional font: `./install-eurocaps.bat` to install the Eurocaps font.
- Start EDMarketConnector; the overlay client launches automatically. If prompted to update settings, use the EDMC preferences panel.

Quick checks:
- `Test-Path "$env:LOCALAPPDATA\EDMarketConnector\plugins\EDMC-ModernOverlay\overlay-client\.venv\Scripts\python.exe"`
- `Get-Content "$env:LOCALAPPDATA\EDMarketConnector\plugins\EDMC-ModernOverlay\port.json"` (when the plugin is running)

### Linux
- Close EDMarketConnector before installing.
- Make sure you have Python 3 and venv support available (e.g. on Debian/Ubuntu: `sudo apt install python3 python3-venv`).
- From the extracted folder, run the installer:
  - `./install_linux.sh` (ensure it’s executable) or `bash ./install_linux.sh`
- The installer will:
  - Detect (or prompt for) the EDMC plugins directory.
  - Copy `EDMC-ModernOverlay/` into the plugins directory.
  - Create `overlay-client/.venv` and install `overlay-client/requirements.txt` into it.
- Optional font: `./install-eurocaps.sh` installs the Eurocaps font system-wide (may require sudo depending on distro setup).
- Start EDMarketConnector; the overlay client launches automatically.

## Project Layout

```
EDMC-ModernOverlay/
├── README.md                       # You're here
├── FAQ.md                          # Extra setup and troubleshooting notes
├── LICENSE
├── EDMC-ModernOverlay.code-workspace  # Optional VS Code workspace settings
├── load.py                         # EDMC entry hook copied into the plugins dir
├── __init__.py                     # Package marker for EDMC imports
├── edmcoverlay.py                  # Top-level legacy shim (`import edmcoverlay`)
├── EDMCOverlay/                    # Package form of the legacy shim
│   ├── __init__.py
│   └── edmcoverlay.py
├── overlay_plugin/                 # Runtime that runs inside EDMC
│   ├── __init__.py
│   ├── overlay_api.py              # Helper API for other plugins
│   ├── overlay_socket_server.py    # JSON-over-TCP broadcaster
│   ├── overlay_watchdog.py         # Subprocess supervisor for the client
│   ├── preferences.py              # myNotebook-backed settings panel
│   └── requirements.txt            # Runtime dependency stub (stdlib today)
├── overlay-client/                 # Stand-alone PyQt6 overlay process
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
├── scripts/                        # Helper scripts for common setup tasks
│   ├── install-eurocaps.sh         # Linux font installer helper
│   └── install-eurocaps.bat        # Windows font installer helper
├── overlay_settings.json           # Sample preferences persisted by EDMC
└── port.json                       # Last known port (written while the plugin runs)
```

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

## Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed
- On Windows Microsoft Visual C++ 14.0 or greater is required. Get it with "Microsoft C++ Build Tools": https://visualstudio.microsoft.com/visual-cpp-build-tools/

## Windows Setup

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

## Linux Setup

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


## Optional Fonts

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

### `edmcoverlay` Compatibility Layer

Modern Overlay ships with a drop-in replacement for the legacy `edmcoverlay` module. Once this plugin is installed, other plugins can simply:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message("demo", "Hello CMDR", "yellow", 100, 150, ttl=5, size="large")
overlay.send_shape("demo-frame", "rect", "#ffffff", "#40000000", 80, 120, 420, 160, ttl=5)
```

Under the hood the compatibility layer forwards payloads through `send_overlay_message`, so no socket management or process monitoring is required. The overlay client understands the legacy message/rectangle schema, making migration from the original EDMCOverlay plugin largely turnkey.

## EDMC Compliance Checklist

- Implements the documented EDMC hooks (`plugin_start3`, `plugin_stop`, `plugin_prefs`, `plugin_prefs_save`, `journal_entry`); `plugin_app` explicitly returns `None`, so the Tk main thread stays idle.
- Long-running work stays off the Tk thread. `WebSocketBroadcaster` runs on a daemon thread with its own asyncio loop, `OverlayWatchdog` supervises the client on another daemon thread, and `plugin_stop()` stops both and removes `port.json`.
- Plugin-owned timers are guarded by `_config_timer_lock`, keeping rebroadcast scheduling thread-safe across shutdowns and restarts.
- Plugin state lives inside this directory. `Preferences` reads and writes `overlay_settings.json`; the Tk UI uses `myNotebook` widgets and writes through `plugin_prefs_save`, including helper text when a restart of the overlay is required for stdout/stderr capture changes.
- Logging integrates with EDMC’s logger via `_EDMCLogHandler`; optional payload mirroring and stdout/stderr capture are preference-gated and emit additional detail only when EDMC logging is set to DEBUG.
- The overlay client launches with the dedicated `overlay-client/.venv` interpreter (or an override via `EDMC_OVERLAY_PYTHON`), keeping EDMC’s bundled Python environment untouched.
- Other plugins publish safely through `overlay_plugin.overlay_api.send_overlay_message`, which validates payload structure and size before handing messages to the broadcaster.
- Platform-aware paths handle Windows-specific interpreter names and window flags while keeping Linux/macOS support intact.

**Why JSON preferences?** The PyQt overlay process runs outside EDMC’s Python interpreter and reads `overlay_settings.json` directly so it can pick up the latest settings without importing EDMC modules. Storing the preferences here keeps a single source of truth that both the plugin and the external client can access.

## Development Tips

- VS Code launch configurations are provided for both the overlay client and a standalone broadcast server harness.
- Plugin-side logs are routed through EDMC when `config.log` is available; otherwise they fall back to stdout. The overlay client writes to its own rotating log in `logs/EDMC-ModernOverlay/overlay-client.log`.
- All background work runs on daemon threads so EDMC can shut down cleanly.

## Versioning

- The release number lives in `version.py` as `__version__`. Bump it before tagging a GitHub release so EDMC, the overlay client, and any API consumers stay in sync.
- `load.py` exposes that version via the EDMC metadata fields and writes it to `port.json` alongside the broadcast port.
- The overlay client displays the currently running version in its “Connected to …” status message, making it easy to confirm which build is active.

## Packaging

To bundle the overlay as a single executable (optional):

```bash
pip install pyinstaller
pyinstaller --onefile overlay-client/overlay_client.py
```

Update `OverlayWatchdog`'s command to point at the generated binary if you ship it to other commanders.
