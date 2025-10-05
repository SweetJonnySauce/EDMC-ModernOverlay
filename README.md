# EDMC Modern Overlay

A two-part reference implementation that adds a modern overlay/HUD to Elite Dangerous Market Connector (EDMC).

- `plugin/` – a safe EDMC plugin that streams journal events over WebSockets and supervises the overlay process.
- `overlay-client/` – a stand-alone PyQt6 window that renders the data on a transparent, click-through HUD.

## Features

- Background asyncio WebSocket server (no Tk mainloop blocking)
- Threaded watchdog with bounded restart attempts
- JSON-based client discovery via `port.json`
- PyQt6 overlay with transparent background and opaque text
- Auto-reconnect support if EDMC restarts

## Getting Started

1. **Clone or copy** the repository into your EDMC plugins workspace (see below for default paths).
2. Create a virtual environment at the repository root:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r plugin/requirements.txt -r overlay-client/requirements.txt
   ```
3. Symlink or copy the `plugin/` folder into your EDMC plugins directory (e.g. `%LOCALAPPDATA%\EDMarketConnector\plugins\EDMCModernOverlay`).
4. Launch EDMC – the plugin will start the WebSocket server and watchdog automatically.
5. The watchdog launches `overlay-client/overlay_client.py` using EDMC's interpreter. When packaging, replace the command with your built executable.

## Development

- VS Code launch configurations are provided under `.vscode/` for running the overlay and a simple plugin harness.
- Logging is routed through `config.log()` when available; otherwise it falls back to `print()`.
- All background work runs on daemon threads to avoid blocking EDMC shutdown.

## Packaging the Overlay

Build a one-file executable with:
```bash
pyinstaller --onefile overlay-client/overlay_client.py
```
Update the watchdog command to point to the generated binary.

## EDMC Plugins Workspace

ED Market Connector scans a platform-specific `plugins` directory at startup:

- Windows: `%LOCALAPPDATA%\EDMarketConnector\plugins`
- macOS: `~/Library/Application Support/EDMarketConnector/plugins`
- Linux (Wine default): `~/.local/share/EDMarketConnector/plugins`

Place this repository (or a symlink to it) inside that directory so EDMC can load the plugin and launch the overlay.

## License

MIT – adapt freely for your squadron or project.
