# Troubleshooting Modern Overlay

Use these steps to gather diagnostics when the overlay misbehaves. Dev mode gates most debug helpers, and EDMC’s own DEBUG log level is required for the most verbose output.

## Enable overlay dev mode
- Export `MODERN_OVERLAY_DEV_MODE=1` before launching EDMC (e.g., `export MODERN_OVERLAY_DEV_MODE=1` on Linux; set the env var in a terminal/PowerShell on Windows).
- Alternatively, run a build whose `__version__` ends with `-dev` (e.g., `0.7.4-dev`); dev mode is auto-enabled.
- Verify startup: the EDMC log will include `Running Modern Overlay dev build (...)`. To force release behavior while using a `-dev` build, set `MODERN_OVERLAY_DEV_MODE=0`.
- In dev mode, `debug.json` flags take effect (tracing, payload mirroring, repaint logging, etc.).

## Set EDMC log level to DEBUG
- In EDMC, set the application log level to DEBUG (UI option if available in your build), then restart EDMC. This sets `loglevel=DEBUG` in EDMC’s config.
- DEBUG is required for verbose overlay logs piped back to EDMC (stdout/stderr capture, payload mirroring notices).

## Where to find logs
- EDMC log (core):  
  - Windows: `%LOCALAPPDATA%\\EDMarketConnector\\EDMarketConnector.log`   
  - Linux: `~/.local/share/EDMarketConnector/EDMarketConnector.log`
- Overlay logs (client): `logs/EDMCModernOverlay/overlay_client.log` under the Modern Overlay plugin directory (or `logs/EDMCModernOverlay/overlay-payloads.log` when payload mirroring is on).
- Debug flags live in `debug.json` in the plugin directory; missing keys are auto-filled in dev mode.
