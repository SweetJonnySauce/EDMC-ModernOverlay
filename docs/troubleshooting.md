# Troubleshooting Modern Overlay

Use these steps to gather diagnostics when the overlay misbehaves. EDMC’s own DEBUG log level now drives every Modern Overlay logger (plugin, client, controller, payload mirror) so a single toggle unlocks full verbosity. Dev mode remains the gate for risky UI helpers, but it now forces the same DEBUG behaviour even if EDMC stays at INFO/WARN.

## Enable overlay dev mode (optional)
- Run the overlay in DEV mode by updating `version.py` and making sure `__version__` ends with `-dev` (e.g., `0.7.4-dev`), or export `MODERN_OVERLAY_DEV_MODE=1` before launching EDMC. Set `MODERN_OVERLAY_DEV_MODE=0` to force release behaviour.
- Verify startup: the EDMC log will include `Running Modern Overlay dev build (...)`.
- Dev mode now forces every Modern Overlay logger (plugin, overlay client, overlay controller, payload mirror) to DEBUG even if EDMC stays at INFO/WARN, and stdout/stderr capture follows suit whenever `capture_client_stderrout` is true. Use this to debug locally without touching EDMC’s setting.
- Dev mode still unlocks `debug.json` visual helpers (tracing, payload mirroring, repaint logging, group outlines, title-bar tweaks, etc.), so keep it disabled for normal gameplay builds.

## Set EDMC log level to DEBUG
- In EDMC, set the application log level to DEBUG (UI option if available in your build), then restart EDMC. This sets `loglevel=DEBUG` in EDMC’s config.
- DEBUG automatically raises the plugin, overlay client, and overlay controller loggers to DEBUG and creates `debug.json` on first run so payload mirroring/capture toggles are available even in release builds.
- When `capture_client_stderrout` is true, DEBUG mode (or the dev override) pipes overlay stdout/stderr back to EDMC so controller launch failures and PyQt stack traces appear in a single log.

## Configure diagnostics from the preferences panel
- Open EDMC’s settings and select the Modern Overlay tab. When DEBUG logging (or dev mode) is active a new **Diagnostics** group appears.
- Use the **Capture overlay stdout/stderr** checkbox to mirror the client/controller output back into the EDMC log without editing `debug.json`.
- Enable the **Override overlay log retention** switch to clamp the rotating client logs (1–20 files), or clear it to fall back to the normal preference.
- Enter a comma-separated list of plugin IDs in the exclusion field to keep noisy payload sources out of `overlay-payloads.log`.
- Gridlines, grid spacing, and payload ID cycling are now regular user controls instead of dev-only toggles, so release builds can use them while troubleshooting layout problems.
- Per-monitor clamp overrides: when physical clamp is enabled, you can set `DisplayPort-2=1.0, HDMI-0=1.25` in the per-monitor field to force a scale on specific screens. Screen names match the ones printed in the overlay client log (`Geometry normalisation: screen='...'`). Leave blank to clear overrides.

## Where to find logs
- EDMC log (core):  
  - Windows: `%LOCALAPPDATA%\\EDMarketConnector\\EDMarketConnector.log`   
  - Linux: `~/.local/share/EDMarketConnector/EDMarketConnector.log`
  - Flatpak: `~/.var/app/io.edcd.EDMarketConnector/data/EDMarketConnector/EDMarketConnector.log`
- Overlay logs (client): `logs/EDMCModernOverlay/overlay_client.log` under the Modern Overlay plugin directory (or `logs/EDMCModernOverlay/overlay-payloads.log` when payload mirroring is on).
- Overlay Controller log: `logs/EDMCModernOverlay/overlay_controller.log` (same directory as the client log). The controller writes a startup banner every time `!ovr` launches it and captures any uncaught exceptions or stack traces before it exits. Set EDMC to DEBUG (or use dev mode) so geometry/routing DEBUG logs are flushed to the file even before Tk initialises.
- Debug flags live in `debug.json` in the plugin directory; Modern Overlay now auto-creates this file whenever EDMC logging is DEBUG (or dev mode is active) so users don’t need to craft it manually before capturing payloads. Developer-only overlay helpers (tracing, outlines, vertex markers) live in `dev_settings.json`, which is created/read only when dev mode is enabled so normal troubleshooting stays focused on capture/logging knobs.

## Manual config reference

Most users never need to edit JSON by hand because the Diagnostics section writes these values for you, but support workflows sometimes require double-checking what is on disk. `debug.json` is the troubleshooting store; only edit it when you want to seed capture/log-retention defaults before EDMC launches:

```json
{
  "capture_client_stderrout": true,
  "overlay_logs_to_keep": 5,
  "payload_logging": {
    "overlay_payload_log_enabled": true,
    "exclude_plugins": []
  }
}
```

`dev_settings.json` is only honoured in dev mode and holds purely developer-facing toggles:

```json
{
  "tracing": {
    "enabled": false,
    "payload_ids": []
  },
  "overlay_outline": true,
  "group_bounds_outline": true,
  "payload_vertex_markers": false,
  "repaint_debounce_enabled": true,
  "log_repaint_debounce": false
}
```

If you do edit these files manually, restart EDMC afterwards so the plugin reloads them, and make sure EDMC log level is still set to DEBUG so diagnostics remain active.
