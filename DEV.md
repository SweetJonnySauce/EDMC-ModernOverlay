# Development Tips

- VS Code launch configurations are provided for both the overlay client and a standalone broadcast server harness.
- Plugin-side logs are routed through EDMC when `config.log` is available; otherwise they fall back to stdout. The overlay client writes to its own rotating log in `logs/EDMC-ModernOverlay/overlay-client.log`.
- All background work runs on daemon threads so EDMC can shut down cleanly.
- When testing window-follow behaviour, toggle the developer debug overlay (Shift+F10 by default) to inspect monitor, overlay, and font metrics. The status label now only reports the connection banner and window position so it never changes the overlay geometry.

## Versioning

- The release number lives in `version.py` as `__version__`. Bump it before tagging a GitHub release so EDMC, the overlay client, and any API consumers stay in sync.
- `load.py` exposes that version via the EDMC metadata fields and writes it to `port.json` alongside the broadcast port.
- The overlay client displays the currently running version in its “Connected to …” status message, making it easy to confirm which build is active.

## Tests

- Lightweight regression scenarios live under `overlay-client/tests`. `test_geometry_override.py` covers window-manager override classification, including fractional window sizes that previously caused geometry thrash.
- Install `pytest` in the client virtualenv and run `python -m pytest overlay-client/tests` to execute the suite.
