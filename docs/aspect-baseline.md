# Aspect Ratio Baseline (Current Client Behaviour)

This note captures the legacy scaling numbers the overlay client produces *today* so we have a reference point before changing the projection logic. The figures use the existing implementation in `overlay-client/overlay_client.py`, which:

- Treats incoming legacy coordinates as a 1280 × 720 logical canvas.
- Derives per-axis scale factors (`scale_x`, `scale_y`) by dividing the live widget dimensions by that canvas.
- Multiplies horizontal spans by an extra `aspect_factor = scale_y / scale_x` before painting vect and rect payloads.

## Sample Window Sizes

| Window size | scale_x | scale_y | aspect_factor | Notes |
|-------------|---------|---------|----------------|-------|
| 1280 × 720  | 1.0000  | 1.0000  | 1.0000         | Baseline logical canvas. |
| 1920 × 1080 (16:9) | 1.5000 | 1.5000 | 1.0000 | Both axes scale equally; geometry keeps its shape. |
| 2560 × 1080 (21:9) | 2.0000 | 1.5000 | 0.7500 | X is compressed by 25 % to match the shorter Y scale. |
| 3440 × 1440 (21:9) | 2.6875 | 2.0000 | 0.7442 | Effective horizontal scale becomes `2.6875 × 0.7442 ≈ 2.0`. |
| 3840 × 1600 (UWQHD+) | 3.0000 | 2.2222 | 0.7407 | Wide aspect ratios receive heavier horizontal compression. |

### What the numbers imply

- For any window wider than 16:9, `scale_x > scale_y`, so `aspect_factor < 1`. The overlay squashes the X coordinates around each payload’s centre (or override pivot) to re-match `scale_y`. That keeps objects roughly circular, but it also shifts radial endpoints inward, which is where the current LandingPad artefacts come from.
- There is no compensating offset today; everything is anchored to the top-left of the overlay window after applying the aspect correction.
- Because `scale_y` is never reduced, tall aspect ratios (e.g., 3:2) end up stretching X instead.

These figures (and the formulas behind them) form the baseline we will compare against once the new “Fit” and “Fill” transforms are in place. When it’s time to validate, enable the debug overlay (`show_debug_overlay = true`) and watch the `scale_x`, `scale_y`, and `aspect` entries—they should match the values above for the same window resolutions.
