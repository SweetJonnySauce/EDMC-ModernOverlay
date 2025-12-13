# Per-monitor Clamp Overrides (Escape Hatch)

When fractional desktop scaling misplaces the overlay, you can force per-monitor scaling inside the Modern Overlay client without changing system settings. This is an opt-in escape hatch built on top of the physical clamp feature.

## When to use
- You’re on fractional desktop scaling (e.g., 1.25–1.5x) and the overlay shrinks or anchors incorrectly even with physical clamp enabled.
- You want to keep fractional scaling for the OS but force a specific monitor to behave as if it were 1.0x (or another explicit scale) for the overlay only.

## How to set overrides
1) Enable **Clamp fractional desktop scaling (physical clamp)** in the Modern Overlay preferences.
2) In the **Per-monitor clamp overrides** field, enter comma-separated `name=scale` pairs, e.g.:
   - `DisplayPort-2=1.0, HDMI-0=1.25`
3) Restart the overlay (or toggle the clamp setting) if you don’t see the change immediately.

### Finding the correct screen name
- Check the overlay client log for `Geometry normalisation: screen='...'` to see the exact screen names reported by Qt.
- If the name doesn’t match, the override is ignored; keep the casing as reported.

### Valid values
- Scales must be positive and finite; values are clamped to the safe range 0.5–3.0.
- Leave the field empty to clear overrides.

## What to expect
- Overrides apply only when physical clamp is enabled.
- Hit: matching screen name uses the override scale (logged once as `Per-monitor clamp override applied...`).
- Miss: non-matching or empty map leaves the existing clamp logic unchanged.
- Invalid: bad values are ignored and logged once (`ignored...`); defaults remain untouched.

## Troubleshooting
- If nothing changes, double-check the screen name from the client log.
- If the overlay looks worse, clear the overrides field or set a different scale (e.g., 1.0).
- Keep an eye on the log: it should only emit a single apply/ignore/clamp message per screen, not per frame.
