# EDMC Modern Overlay

EDMC Modern Overlay is a two-part reference implementation for Elite Dangerous Market Connector (EDMC). It streams journal data from EDMC over a lightweight TCP socket and displays a transparent, click-through PyQt6 heads-up display on your desktop.

## Project Layout

```
EDMC-ModernOverlay/
├── plugin/                # EDMC plugin package
│   ├── load.py            # EDMC hook implementation
│   ├── overlay_watchdog.py
│   ├── websocket_server.py
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
- Transparent, click-through PyQt6 HUD with live CMDR/system/station info
- Automatic reconnection logic in both plugin and overlay client
- Plugin runtime uses only the Python standard library (no EDMC-side installs required)

## Prerequisites

- Python 3.12+
- Elite Dangerous Market Connector installed

## Setup

1. **Create and activate a virtual environment** inside the repository root:
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```
2. **Install dependencies** required for the overlay client:**
   ```bash
   pip install PyQt6
   ```
   On Linux you also need Qt's XCB helpers:
   ```bash
   sudo apt-get update
   sudo apt-get install libxcb-cursor0 libxkbcommon-x11-0
   ```
3. **Install the EDMC plugin** by copying (or symlinking) the contents of the `plugin/` directory into your EDMC plugin workspace:
   ```
   %LOCALAPPDATA%\EDMarketConnector\plugins\EDMCModernOverlay\
   ```
   - Windows default: `%LOCALAPPDATA%\EDMarketConnector\plugins`
   - macOS: `~/Library/Application Support/EDMarketConnector/plugins`
   - Linux (Wine default): `~/.local/share/EDMarketConnector/plugins`
4. **Launch EDMC.** The plugin starts automatically, spins up the background broadcast server, writes `port.json`, and begins supervising the overlay.
5. **Run the overlay client** manually for development:
   ```bash
   python overlay-client/overlay_client.py
   ```
   In production you can package the overlay and update the watchdog command accordingly.

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
