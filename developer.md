# Developer Notes

## Development Tips

- VS Code launch configurations exist for the overlay client and the standalone broadcast server harness.
- Plugin-side logs route through EDMC when `config.log` is present; otherwise they fall back to stdout. The overlay client writes to `logs/EDMC-ModernOverlay/overlay-client.log`.
- Background tasks run on daemon threads so EDMC can exit cleanly even if the overlay client is still doing work.
- When testing the window-follow path, toggle the developer debug overlay (Shift+F10 by default) to inspect monitor, overlay, and font metrics. The status label now only reports the connection banner and window position so it never changes the overlay geometry.
- Other plugins can detect Modern Overlay (and the version they are talking to) via `MODERN_OVERLAY_IDENTITY`, which is exported from `EDMCOverlay.edmcoverlay`. Because `edmcoverlay.py` re-exports that module, consumers can simply `import edmcoverlay` and inspect `edmcoverlay.MODERN_OVERLAY_IDENTITY` for `{"plugin": "EDMC-ModernOverlay", "version": "<semver>"}`. Gate Modern Overlay-specific behaviour behind that check instead of probing files on disk.
- Example detection helper:
  ```python
  import edmcoverlay

  identity = getattr(edmcoverlay, "MODERN_OVERLAY_IDENTITY", None)
  if identity and identity.get("plugin") == "EDMC-ModernOverlay":
      version = identity.get("version", "unknown")
      print(f"Modern Overlay v{version} detected")
  ```
- Clearing a legacy payload now mirrors every legacy path: sending `text=""`, `ttl=0`, **or** calling `send_raw({"id": "payload-id"})` all normalise to a `legacy_clear` event. The shim logs the event, the plugin mirrors it to `overlay-payloads.log`, and the overlay client removes the matching `id` even if the request originated from the WebSocket CLI.

## Versioning

- The release number lives in `version.py` (`__version__`). Bump it before tagging so EDMC, the overlay client, and API consumers remain in sync.
- `load.py` exposes that version via EDMC metadata fields and records it in `port.json` next to the broadcast port.
- The overlay client shows the running version in the “Connected to …” banner, making it easy to confirm which build is active.
- Developer builds inherit BGSTally-style semantics: append `-dev` (or any `.dev*` suffix) to `__version__` **or** export `MODERN_OVERLAY_DEV_MODE=1` before launching EDMC to force dev mode. Dev builds default the plugin logger to DEBUG and log a startup banner; set `MODERN_OVERLAY_DEV_MODE=0` to suppress dev behaviour while keeping the `-dev` version string.
- `debug.json` is only read when dev mode is active. Release builds ignore every flag in that file, so set `MODERN_OVERLAY_DEV_MODE=1` (or bump the version suffix to `-dev`) before relying on payload mirroring, group outlines, or trace helpers.

## Tests

- Lightweight regression scenarios live in `overlay-client/tests`. `test_geometry_override.py` covers window-manager override classification, including fractional window sizes that previously caused geometry thrash.
- Install `pytest` in the client virtualenv and run `python -m pytest overlay-client/tests` to execute the suite.

## Payload ID Finder Overlay

Modern Overlay includes a developer-facing “payload ID finder” that helps trace which legacy payload is currently targeted. When you enable **Cycle through Payload IDs** in the preferences, the overlay shows a floating badge containing:

- The active `payload_id`
- The originating plugin name (if known)
- The computed center coordinates of the payload on screen
- Runtime diagnostics: remaining TTL (or `∞` when persistent), how long ago the payload last updated, the payload kind (message/rect/vector with relevant size info), and a breakdown of the active Fill transforms (remap, preservation shift, translation)

This is particularly useful when capturing coordinates or validating grouping behaviour.

> **Important:** If “Compensate for Elite Dangerous title bar” is enabled, the center coordinates displayed in the payload ID finder will be inaccurate. Title bar compensation translates the overlay to align with the game window, but the badge still uses the original, uncompensated coordinates. Disable the compensation setting when you need precise center values from the finder.

### Tips

- Toggle payload cycling with the controls in the preferences.
- Enable “Copy current payload ID to clipboard” if you want each ID handed to the clipboard automatically while stepping through items. The checkbox is automatically disabled (but keeps its state) whenever cycling itself is turned off, then becomes active again when cycling is re-enabled.
- The connector line from the badge points toward the payload’s anchor point, helping locate overlapping elements quickly.
- Plugin names and coordinates rely on the metadata provided by each payload; if a plugin does not populate `plugin` fields, the finder falls back to `unknown`.
- The transform breakdown is listed in the order the renderer applies it:
  1. **Fill scale** shows the raw X/Y proportions computed for Fill mode along with the effective values after aspect preservation (`raw → applied`). Fill mode scales by the larger of the window’s horizontal/vertical ratios so the 1280×960 legacy canvas covers the window completely; one axis therefore overflows and requires proportional remapping. (Fit mode, by contrast, uses the smaller ratio so the entire canvas remains inside the window.)
  2. **Fill preserve shift** appears when a group is preserving aspect; it reports the group-wide translation we inject to avoid squashing.
  3. **Fill translation** is the per-group dx/dy derived from bounds that keeps the payload inside the window (assertion #7).
  All values are in overlay coordinates to make it easy to compare against raw payload dumps (e.g. `tests/edr-docking.log`) when tuning Fill behaviour.
- The payload finder’s callout line is configurable. See **Line width overrides** below if you need a thicker/thinner connector.

### Line width overrides

Modern Overlay centralises common pen widths in `overlay-client/render_config.json`. Adjust the values to tune debug visuals without touching code:

- `grid`: spacing grid rendered by the developer background toggle (debug only).
- `group_outline`: dashed bounding box drawn when `group_bounds_outline` is enabled (debug only).
- `viewport_indicator`: the oversized orange guideline arrows that show Fill overflow (debug only).
- `legacy_rect`: outline for legacy `shape="rect"` payloads.
- `vector_line`: the main stroke used for vector payloads (sparklines, trend lines, guidance beams).
- `vector_marker`: the filled circle marker drawn when a vector point specifies `"marker": "circle"`.
- `vector_cross`: the X-shaped marker used for `"marker": "cross"` points.
- `cycle_connector`: the payload finder’s connector from the center badge to the active overlay (debug only).

Values are in pixels. Restart the overlay client after editing the JSON file.

## Debug Overlay Reference

Enable **Show debug overlay** to surface a live diagnostics panel in the corner of the overlay. It mirrors most of the geometry/scale state the client is using:

- **Monitor block** lists the active display (with the computed aspect ratio) and the tracker window the overlay is following. The tracker entry shows the Elite window’s top-left coordinate and the captured width/height in game pixels. If the overlay is offset (e.g., due to title bar compensation) you’ll see a second `wm_rect` line describing the size the window manager believes the overlay occupies.
- **Overlay block** lists:
  - `widget`: the actual QWidget size in logical pixels, with aspect ratio.
  - `frame`: the Qt frame geometry (includes window frame and drop shadows when present).
  - `phys`: the size after multiplying by the device pixel ratio, i.e., the true number of physical screen pixels the overlay occupies.
  - `raw`: the Elite window geometry that legacy payloads are targeting; this is the reference rectangle used for coordinate normalisation.
  - `scale`: the resolved legacy scale factors (`legacy_x`, `legacy_y`) plus the active scaling `mode` (`fit` or `fill`).
  These values are useful when diagnosing mismatched HUD scaling or when confirming that group offsets line up with the monitored window.
- **Fonts block** records:
  - Legacy scale factors (`scale_x`, `scale_y`, `diag`) derived from window size.
  - `ui_scale`: the user’s current font scaling multiplier.
  - `bounds`: the min/max font point clamping that payloads are restricted to.
  - Live font sizes (`message`, `status`, `legacy`) after clamping and scaling.
  - `legacy presets`: the resolved point sizes for the classic `small`, `normal`, `large`, and `huge` presets so you can see exactly what each payload’s `size` value maps to.
- **Settings block** highlights the title-bar compensation flag and height, along with the actual pixel offset applied. If compensation is enabled but the offset seems wrong, this is the first place to verify the numbers.

These details are helpful when debugging sizing issues (e.g., 21:9 vs. 4:3 monitors) or verifying that Fill-mode remaps are behaving as expected.

### Fill-mode diagnostics

Enable `group_bounds_outline` in `debug.json` to render dashed rectangles (plus anchor dots) for each cached group while tuning Fill mode behaviour. Because Fill scales the legacy canvas until one axis overflows, these outlines make it easy to confirm that related payloads are translating together and remaining rigid even when they extend beyond the visible window.

## Transform Pipeline Overview

The current scaling flow is intentionally broken into Qt-aware and Qt-free layers so we can reason about transforms everywhere (Fit, Fill, grouping) without leaking widget details:

1. **Window → ViewportTransform**  
   `OverlayWindow` samples the widget width/height and devicePixelRatioF, then calls `viewport_helper.compute_viewport_transform()`. That helper decides the Fit/Fill scale about logical `(0,0)` and returns the canvas offsets that center or pin the 1280×960 surface inside the window, along with `overflow_x/overflow_y`.
   - In **Fill** mode the helper keeps the legacy origin anchored at the window’s `(0,0)` corner; overflow simply extends past the right/bottom edges so coordinate systems remain aligned with the physical window.

2. **ViewportTransform → LegacyMapper**  
   We wrap just the uniform `scale_x/scale_y` and base `offset_x/offset_y` into a `LegacyMapper`. This struct carries the Qt-derived values to code that otherwise never touches Qt.

3. **LegacyMapper → FillViewport**  
   `viewport_transform.build_viewport()` receives the mapper, a plain `ViewportState` (width, height, device ratio), and any cached `GroupTransform`. It produces a `FillViewport` object that painters use to map logical coordinates to screen pixels, while preserving group anchors/metadata. This is the first place payload coordinates are evaluated after the base Fit/Fill scale.
   - When the mapper is in Fill mode we cache each group’s anchor so the renderer can “undo” the Fill scale around that pivot, keeping grouped payloads at their original logical size even though the viewport itself was scaled up.

4. **FillViewport → payload remappers**  
   `payload_transform.py` (messages/rectangles/vectors) consumes `FillViewport` to remap payload points, apply plugin overrides, and hand back overlay coordinates. `grouping_helper.py` iterates live payloads, accumulates `GroupTransform` bounds/anchors, and caches them for subsequent paint calls.

When adding new behaviour, update `payload_transform` first so grouping and rendering stay in sync, then layer viewport-specific adjustments in `viewport_transform`. `OverlayWindow` should remain the only place that touches PyQt6 APIs.
