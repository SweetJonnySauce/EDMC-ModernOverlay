# Development Tips

- VS Code launch configurations are provided for both the overlay client and a standalone broadcast server harness.
- Plugin-side logs are routed through EDMC when `config.log` is available; otherwise they fall back to stdout. The overlay client writes to its own rotating log in `logs/EDMC-ModernOverlay/overlay-client.log`.
- All background work runs on daemon threads so EDMC can shut down cleanly.

## Versioning

- The release number lives in `version.py` as `__version__`. Bump it before tagging a GitHub release so EDMC, the overlay client, and any API consumers stay in sync.
- `load.py` exposes that version via the EDMC metadata fields and writes it to `port.json` alongside the broadcast port.
- The overlay client displays the currently running version in its “Connected to …” status message, making it easy to confirm which build is active.
