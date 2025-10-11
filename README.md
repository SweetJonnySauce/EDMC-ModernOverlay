# EDMC Modern Overlay

Warning: This is not your normal EDMC plugin and should be considered a prototype. It has only been tested on Ubuntu at this time. It has **not** been tested with edmcovelay2 loading at the same time, so stability gremlins may be present.

EDMC Modern Overlay is a two-part reference implementation for Elite Dangerous Market Connector (EDMC). It streams journal data from EDMC over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on your desktop.

## Project Layout

```
EDMC-ModernOverlay/
├── README.md                     # You're here
├── FAQ.md                        # Extra setup and troubleshooting notes
├── LICENSE
├── load.py                       # EDMC entry hook copied into the plugins dir
├── __init__.py                   # Package marker for EDMC imports
├── edmcoverlay.py                # Top-level legacy shim (`import edmcoverlay`)
├── EDMCOverlay/                  # Package form of the legacy shim
│   ├── __init__.py
│   └── edmcoverlay.py
├── overlay_plugin/               # Runtime that runs inside EDMC
│   ├── __init__.py
│   ├── overlay_api.py            # Helper API for other plugins
│   ├── overlay_socket_server.py  # JSON-over-TCP broadcaster
│   ├── overlay_watchdog.py       # Subprocess supervisor for the client
│   ├── preferences.py            # myNotebook-backed settings panel
│   └── requirements.txt          # Runtime dependencies (standard-library-only today)
├── overlay-client/               # Stand-alone PyQt6 overlay process
│   ├── overlay_client.py         # Main window and socket bridge
│   ├── client_config.py          # Bootstrap defaults and OverlayConfig parsing
│   ├── developer_helpers.py      # Dev utilities and logging helpers
│   ├── window_tracking.py        # Elite Dangerous window tracking helpers
│   ├── requirements.txt          # Client dependency list (PyQt6, etc.)
│   ├── fonts/
│   │   ├── README.txt
│   │   ├── preferred_fonts.txt   # Optional case-insensitive priority list
│   │   ├── SourceSans3-Regular.ttf
│   │   └── SourceSans3-OFL.txt
└── overlay_settings.json         # Sample preferences written by EDMC
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
- Long-running work stays off the Tk thread. `WebSocketBroadcaster` runs on a daemon thread with its own asyncio loop, `OverlayWatchdog` supervises the client on another daemon thread, and `plugin_stop()` always stops both and removes `port.json`.
- Plugin state lives inside the plugin directory. `Preferences` reads and writes `overlay_settings.json`, and the Tk UI built with `myNotebook` saves through `plugin_prefs_save`, including helper text when a restart of the overlay is required for stdout/stderr capture changes.
- Logging integrates with EDMC’s logger via `_EDMCLogHandler`; optional payload mirroring and stdout/stderr capture are preference-gated and emit additional detail only when EDMC logging is set to DEBUG.
- The overlay client launches with the dedicated `overlay-client/.venv` interpreter (or an override via `EDMC_OVERLAY_PYTHON`), keeping EDMC’s bundled Python environment untouched.
- Other plugins publish safely through `overlay_plugin.overlay_api.send_overlay_message`, which validates payload structure and size before handing messages to the broadcaster.
- Platform-aware paths handle Windows-specific interpreter names and window flags while keeping Linux/macOS support intact.

## Development Tips

- VS Code launch configurations are provided for both the overlay client and a standalone broadcast server harness.
- Plugin-side logs are routed through EDMC when `config.log` is available; otherwise they fall back to stdout. The overlay client writes to its own rotating log in `logs/EDMC-ModernOverlay/overlay-client.log`.
- All background work runs on daemon threads so EDMC can shut down cleanly.

## Packaging

To bundle the overlay as a single executable (optional):

```bash
pip install pyinstaller
pyinstaller --onefile overlay-client/overlay_client.py
```

Update `OverlayWatchdog`'s command to point at the generated binary if you ship it to other commanders.
