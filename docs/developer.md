# Developer Notes

## Payload ID Finder Overlay

Modern Overlay includes a developer-facing “payload ID finder” that helps trace which legacy payload is currently targeted. When you enable **Cycle through Payload IDs** in the preferences, the overlay shows a floating badge containing:

- The active `payload_id`
- The originating plugin name (if known)
- The computed center coordinates of the payload on screen
- Runtime diagnostics: remaining TTL (or `∞` when persistent), how long ago the payload last updated, the payload kind (message/rect/vector with relevant size info), and any override adjustments (scaled/offset coordinates, sizes, and matched pattern)

This is particularly useful when capturing coordinates or validating plugin overrides.

> **Important:** If “Compensate for Elite Dangerous title bar” is enabled, the center coordinates displayed in the payload ID finder will be inaccurate. Title bar compensation translates the overlay to align with the game window, but the badge still uses the original, uncompensated coordinates. Disable the compensation setting when you need precise center values from the finder.

### Tips

- Toggle payload cycling with the controls in the preferences.
- Enable “Copy current payload ID to clipboard” if you want each ID handed to the clipboard automatically while stepping through items. The checkbox is automatically disabled (but keeps its state) whenever cycling itself is turned off, then becomes active again when cycling is re-enabled.
- The connector line from the badge points toward the payload’s anchor point, helping locate overlapping elements quickly.
- Plugin names and coordinates rely on the metadata provided by each payload; if a plugin does not populate `plugin` fields, the finder falls back to `unknown`.
- Message overrides (e.g. `bgstally-msg-*`) are now tracked, so scale/offset adjustments applied via overrides show up in the badge.

## Debug Overlay Reference

Enable **Show debug overlay** to surface a live diagnostics panel in the corner of the overlay. It mirrors most of the geometry/scale state the client is using:

- **Monitor block** lists the active display (with the computed aspect ratio) and the tracker window the overlay is following. The tracker entry shows the Elite window’s top-left coordinate and the captured width/height in game pixels. If the overlay is offset (e.g., due to title bar compensation) you’ll see a second `wm_rect` line describing the size the window manager believes the overlay occupies.
- **Overlay block** lists:
  - `widget`: the actual QWidget size in logical pixels, with aspect ratio.
  - `frame`: the Qt frame geometry (includes window frame and drop shadows when present).
  - `phys`: the size after multiplying by the device pixel ratio, i.e., the true number of physical screen pixels the overlay occupies.
  - `raw`: the Elite window geometry that legacy payloads are targeting; this is the reference rectangle used for coordinate normalisation.
  These values are useful when diagnosing mismatched HUD scaling or when confirming that overrides line up with the monitored window.
- **Fonts block** records:
  - Legacy scale factors (`scale_x`, `scale_y`, `diag`) derived from window size.
  - `ui_scale`: the user’s current font scaling multiplier.
  - `bounds`: the min/max font point clamping that payloads are restricted to.
  - Live font sizes (`message`, `status`, `legacy`) after clamping and scaling.
  - `legacy presets`: the resolved point sizes for the classic `small`, `normal`, `large`, and `huge` presets so you can see exactly what each payload’s `size` value maps to.
- **Settings block** highlights the title-bar compensation flag and height, along with the actual pixel offset applied. If compensation is enabled but the offset seems wrong, this is the first place to verify the numbers.

These details are helpful when debugging sizing issues (e.g., 21:9 vs. 16:9 monitors) or verifying that override transforms are behaving as expected.
