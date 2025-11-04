# Aspect Ratio Baseline (Current Client Behaviour)

This note captures the legacy scaling numbers the overlay client produces *today* so we have a reference point before changing the projection logic. The figures use the existing implementation in `overlay-client/overlay_client.py`, which:

- Treats incoming legacy coordinates as a 1280 × 960 logical canvas.
- Derives per-axis scale factors (`scale_x`, `scale_y`) by dividing the live widget dimensions by that canvas.
- Multiplies horizontal spans by an extra `aspect_factor = scale_y / scale_x` before painting vect and rect payloads.

## Sample Window Sizes

| Window size | scale_x | scale_y | aspect_factor | Notes |
|-------------|---------|---------|----------------|-------|
| 1280 × 960  | 1.0000  | 1.0000  | 1.0000         | Baseline logical canvas (4:3). |
| 1920 × 1080 (16:9) | 1.5000 | 1.1250 | 0.7500 | Horizontal letterboxing; X is compressed by 25 %. |
| 2560 × 1080 (21:9) | 2.0000 | 1.1250 | 0.5625 | Wider view adds heavier X compression. |
| 3440 × 1440 (21:9) | 2.6875 | 1.5000 | 0.5581 | Effective horizontal scale becomes `2.6875 × 0.5581 ≈ 1.5`. |
| 3840 × 1600 (UWQHD+) | 3.0000 | 1.6667 | 0.5556 | Ultra-wide layouts retain the same compression trend. |

### What the numbers imply

- For any window wider than 4:3, `scale_x > scale_y`, so `aspect_factor < 1`. The overlay squashes the X coordinates around each payload’s centre (or override pivot) to re-match `scale_y`. That keeps objects roughly circular, but it also shifts radial endpoints inward, which is where the current LandingPad artefacts come from.
- There is no compensating offset today; everything is anchored to the top-left of the overlay window after applying the aspect correction.
- Because `scale_y` is never reduced, tall portrait ratios (e.g., 1080 × 1920) end up stretching X instead.

These figures (and the formulas behind them) form the baseline we will compare against once the new “Fit” and “Fill” transforms are in place. When it’s time to validate, enable the debug overlay (`show_debug_overlay = true`) and watch the `scale_x`, `scale_y`, and `aspect` entries—they should match the values above for the same window resolutions.
