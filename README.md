# EDMC Modern Overlay

Warning: This is not your normal EDMC plugin and should be considered a prototype. It has only been tested on Ubuntu at this time. It has **not** been tested with edmcovelay2 loading at the same time, so stability gremlins may be present.

EDMC Modern Overlay is a two-part reference implementation for Elite Dangerous Market Connector (EDMC). It streams journal data from EDMC over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on your desktop.

## Project Layout

```
EDMC-ModernOverlay/
├── load.py                # EDMC entry hook file (copy into EDMC plugins dir)
├── edmcoverlay.py         # Legacy compatibility shim for `edmcoverlay` callers
├── EDMCOverlay/           # Importable package form of the legacy shim
│   ├── __init__.py
│   └── edmcoverlay.py
├── overlay_plugin/        # Supporting plugin package
│   ├── overlay_watchdog.py
│   ├── overlay_socket_server.py
│   ├── preferences.py
│   └── requirements.txt
├── overlay-client/        # Stand-alone PyQt6 overlay
│   ├── fonts/             # HUD font assets (drop in optional alternates)
│   ├── client_config.py   # Typed bootstrap defaults and OverlayConfig parsing
│   ├── developer_helpers.py  # Developer-helper controller & logging utilities
│   ├── overlay_client.py  # Core PyQt window and socket bridge
│   ├── requirements.txt
│   └── .venv/             # Local virtual environment (create locally; not tracked)
├── overlay_settings.json  # Sample overlay configuration bundle for the client
├── __init__.py            # Allows EDMC to import the plugin as a package
├── .vscode/               # VS Code settings & launch configs
│   ├── launch.json
│   └── settings.json
└── README.md
```

## Features

- Background `asyncio` JSON-over-TCP server that never blocks EDMC's Tkinter thread
- Safe watchdog that supervises the overlay executable and restarts it when needed
- JSON discovery file (`port.json`) so the overlay can find the active port
- Transparent, click-through PyQt6 HUD with test messages, and legacy rectangle/text rendering for `edmcoverlay` callers
- Automatic reconnection logic in both plugin and overlay client
- Full EDMC logging integration with optional stdout/stderr capture and payload mirroring toggled from the preferences pane
- Configurable legacy overlay scaling on both axes so text spacing and legacy rectangles can be adjusted without breaking layout
- Adjustable overlay window size with optional background gridlines for alignment and layout authoring
- Plugin runtime uses only the Python standard library (no EDMC-side installs required)
- Drop-in Python compatibility layer (`EDMCOverlay/edmcoverlay.py`) that emulates the classic EDMCOverlay API so existing plugins can migrate without code changes
- Dedicated client log with rotation controls that writes alongside EDMC’s own logs

## Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed

## Setup

The client lives in the plugin folder and expects a dedicated Python environment under `overlay-client/.venv`. That directory is *not* distributed, so create it yourself before copying the plugin into EDMC.

1. **From the plugin folder, create a virtual environment for the overlay client** inside `overlay-client/`:
   ```bash
   python3 -m venv overlay-client/.venv
   # Windows PowerShell
   overlay-client\.venv\Scripts\activate
   # macOS/Linux
   source overlay-client/.venv/bin/activate
   ```
2. **Install overlay dependencies** into that environment:
   ```bash
   pip install -r overlay-client/requirements.txt
   ```
   On Linux you also need Qt's XCB helpers:
   ```bash
   sudo apt-get update
   sudo apt-get install libxcb-cursor0 libxkbcommon-x11-0
   ```
   Source Sans 3 (SIL Open Font License 1.1) ships in `overlay-client/fonts/`
   as `SourceSans3-Regular.ttf` and is used by default. To override the HUD
   typeface drop another font (for example `Eurocaps.ttf`) into the same
   directory along with its license.
3. **Copy the entire plugin (including client) into EDMC's plugin directory**:
   ```
   %LOCALAPPDATA%\EDMarketConnector\plugins\EDMCModernOverlay\
   ```

4. **Launch EDMC.** The plugin starts automatically, spins up the background broadcast server, writes `port.json`, and begins supervising the overlay client.
5. **Configure via EDMC** under *File → Settings → Modern Overlay*:
   - Toggle *Enable overlay stdout/stderr capture* when you need detailed diagnostics; leave it off for normal play.
   - Enable *Send overlay payloads to the EDMC log* to mirror every payload into EDMC's own log for troubleshooting.
   - Adjust *Legacy overlay vertical scale* if legacy payload text needs extra spacing (1.00× keeps the original layout) and *Legacy overlay horizontal scale* if legacy rectangles need additional width.
   - Change *Overlay window width/height* to set the baseline canvas size before scaling is applied.
   - Toggle *Show light gridlines* and set *Grid spacing* to visualise layout columns or HUD zones; grid opacity follows the background opacity setting.
   - Adjust *Overlay background opacity* to reintroduce a translucent backdrop (0.0 = fully transparent, 1.0 = opaque). Alt+drag to reposition is enabled only when opacity > 0.5, and changes preview in real time.
   - Set *Overlay client log files to keep* if you need longer log history from the client’s rotating logfile.
   - Use *Send test message to overlay* for a quick health check of the native API.
   - Use the legacy compatibility buttons to send `edmcoverlay`-style messages and rectangles without writing any code.


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
