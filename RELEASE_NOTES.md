# Release Notes

## 0.7.5
- Features:
  - Controller⇄client targeting rewrite: controller now pushes merged overrides with an edit nonce, cache entries carry nonce/timestamp metadata, and the client refuses stale transformed blocks so payloads never “jump” when editing offsets.
  - Diagnostics overhaul: EDMC’s DEBUG log level now drives every Modern Overlay logger, auto-creates `debug.json`, and exposes payload logging/stdout capture controls directly in the preferences panel while dev-only helpers live in the new `dev_settings.json`.
  - Cache + fallback hardening: while the controller is active we shorten cache flush debounces, immediately rewrite transformed bounds from the rendered geometry, and keep HUD fallback aligned even if the HUD momentarily drops payload frames.
  - Controller UI cleanup: preview now renders a single authoritative target box (no more dual “actual vs. target”), the absolute widget always mirrors controller coordinates without warning colors, and group pinning/anchor edits stay responsive.
  - Controller performance & usability: merged-group loader now feeds the controller UI, writes are isolated to the user config file, and reloads poll both shipped/user files with last-good fallback to keep editing responsive.
  - Layered configs: shipped defaults remain in `overlay_groupings.json`; per-user overrides live in `overlay_groupings.user.json` (or an override path) and are preserved across upgrades. No automatic migration runs in this release.

- Maintenance:
  - Runtime floor: client/controller now require Python 3.10+; packaging, docs, and both installers enforce/announce the new minimum with a continue-anyway prompt if an older interpreter is detected.
  - Integrity: installers now ship a per-file `checksums.txt` manifest. Both Linux and Windows installers validate the extracted bundle and installed plugin files against it; `generate_checksums.py` builds the manifest during release packaging.
  - Workflow + testing aids: added controller workflow helper/tests to validate cache geometry, expanded fallback regression tests, and folded the new behavior into the refactoring plan documentation.
  - Linux install: added Arch/pacman support alongside existing installers.
  - Fix #26. Give focus back to game after closing the controller on Windows
  - Center justification now uses origin-aware baselines (ignoring non-justified frames) to keep centered text inside its containing box; right justification is unchanged.

## 0.7.4-dev
- Controller startup no longer crashes when Tk rejects a binding; unsupported or empty sequences are skipped with a warning instead.
- Default keyboard bindings drop the X11-only `<ISO_Left_Tab>` entry (Shift+Tab remains) to stay cross-platform.

## 0.7.2.4.1
- Fixed public API: `overlay_plugin.define_plugin_group` now accepts and persists `payload_justification`, matching the documented schema and UI tools. Third-party plugins can set justification without runtime errors.
