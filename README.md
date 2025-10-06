# EDMC Modern Overlay

EDMC Modern Overlay is a two-part reference implementation for Elite Dangerous Market Connector (EDMC). It streams journal data from EDMC over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on your desktop.

## Project Layout

```
EDMC-ModernOverlay/
├── load.py                # EDMC entry hook file (copy into EDMC plugins dir)
├── overlay_plugin/        # Supporting plugin package
│   ├── overlay_watchdog.py
│   ├── overlay_socket_server.py
│   ├── preferences.py
│   └── requirements.txt
├── overlay-client/        # Stand-alone PyQt6 overlay
│   ├── overlay_client.py
│   └── requirements.txt
├── .vscode/               # VS Code settings & launch configs
│   ├── launch.json
│   └── settings.json
└── README.md
```

## Features

- Background `asyncio` JSON-over-TCP server that never blocks EDMC's Tkinter thread
- Safe watchdog that supervises the overlay executable and restarts it when needed
- JSON discovery file (`port.json`) so the overlay can find the active port
- Transparent, click-through PyQt6 HUD with live CMDR/system/station info and ad-hoc test messages
- Automatic reconnection logic in both plugin and overlay client
- Full EDMC logging integration with optional stdout/stderr capture toggled from the preferences pane
- Plugin runtime uses only the Python standard library (no EDMC-side installs required)

## Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed

## Setup

The plugin expects a dedicated Python environment for the overlay client. The `.venv/` folder is *not* distributed, so create it yourself before copying the plugin into EDMC.

1. **Create a virtual environment for the overlay client** inside the repository root:
   ```bash
   python3 -m venv .venv
   # Windows PowerShell
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
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
3. **Copy the plugin into EDMC's plugin directory**:
   ```
   %LOCALAPPDATA%\EDMarketConnector\plugins\EDMCModernOverlay\
   ```
   Include `load.py`, the entire `overlay_plugin/` folder, and (optionally) `overlay-client/` if you want EDMC to supervise the overlay. The watchdog will automatically use `<plugin_root>/.venv/bin/python` (or `Scripts\python.exe` on Windows). To use a different interpreter set `EDMC_OVERLAY_PYTHON` before launching EDMC.
4. **Launch EDMC.** The plugin starts automatically, spins up the background broadcast server, writes `port.json`, and begins supervising the overlay client.
5. **Configure via EDMC** under *File → Settings → Modern Overlay*:
   - Toggle *Enable overlay stdout/stderr capture* when you need detailed diagnostics; leave it off for normal play.
   - Use *Send test message to overlay* to push a one-off message to the HUD and verify connectivity.
6. **Run the overlay client manually (optional)** for development:
   ```bash
   .venv/bin/python overlay-client/overlay_client.py
   ```
   When packaging or relocating the client, update the preferences or environment to point the watchdog at the correct interpreter.

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

## Development Tips

- VS Code launch configurations are provided for both the overlay client and a standalone broadcast server harness.
- Logs are routed through EDMC when `config.log` is available; otherwise they fall back to stdout.
- All background work runs on daemon threads so EDMC can shut down cleanly.

## Packaging

To bundle the overlay as a single executable (optional):

```bash
pip install pyinstaller
pyinstaller --onefile overlay-client/overlay_client.py
```

Update `OverlayWatchdog`'s command to point at the generated binary if you ship it to other commanders.

## License

MIT — remix, extend, and deploy freely for your wing or squadron.
