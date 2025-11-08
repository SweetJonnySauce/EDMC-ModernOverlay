# Aspect Ratio Baseline (Viewport Helper Reference)

Modern Overlay’s renderer now routes every geometry decision through `viewport_helper.compute_viewport_transform()`. Legacy payloads still target a 1280 × 960 canvas, but the helper exposes two explicit scale modes (`ScaleMode.FIT` and `ScaleMode.FILL`) plus the offsets/overflow flags that downstream code (`viewport_transform.build_viewport`) consumes.

## Viewport helper overview

- **Fit** scales the legacy canvas uniformly until it *fits* inside the current window. The helper recentres the canvas and records how much pillar/letterboxing padding was introduced via `offset=(x,y)`. No overflow flags are set because the scaled canvas always stays inside the window bounds.
- **Fill** scales the canvas until *at least* one axis matches the window. The origin stays pinned to the window’s top-left corner (offsets remain zero) and the helper tells us which axis overflowed. Grouping logic later remaps payloads back into view by translating around the group anchor.
- `ViewportTransform.scaled_size` exposes the effective canvas size in window pixels; `overflow_x/overflow_y` drive Fill-mode proportional remaps; the `LegacyMapper` built in `overlay_client.OverlayWindow._compute_legacy_mapper()` keeps these values available to the rest of the pipeline.

## Sample window sizes

The table below shows what the helper reports for representative window sizes. Fit padding uses pixels on each edge. Fill overflow columns read as `x / y`.

| Window size | Fit scale | Fit padding (x / y px) | Fill scale | Fill canvas (px) | Fill overflow (x / y) |
|-------------|-----------|------------------------|------------|------------------|-----------------------|
| 1280 × 960 (4:3) | 1.0000 | 0 / 0 | 1.0000 | 1280 × 960 | no / no |
| 1920 × 1080 (16:9) | 1.1250 | 240 / 0 | 1.5000 | 1920 × 1440 | no / **yes** |
| 2560 × 1080 (21:9) | 1.1250 | 560 / 0 | 2.0000 | 2560 × 1920 | no / **yes** |
| 3440 × 1440 (21:9) | 1.5000 | 760 / 0 | 2.6875 | 3440 × 2580 | no / **yes** |
| 3840 × 1600 (UWQHD+) | 1.6667 | 853.3 / 0 | 3.0000 | 3840 × 2880 | no / **yes** |
| 1080 × 1920 (portrait) | 0.8438 | 0 / 555 | 2.0000 | 2560 × 1920 | **yes** / no |

Portrait layouts flip the situation: Fit introduces letterboxing above/below while Fill overflows the wide axis, so the grouping helper translates payloads horizontally instead of vertically to keep them in view.

## Where to read these numbers

- The developer debug overlay (`Show debug overlay`) mirrors `scale.mode`, `legacy_x`, `legacy_y`, `raw`, and `offset` so you can verify runtime values without scanning logs.
- `OverlayWindow._update_auto_legacy_scale()` logs a concise snapshot whenever the resolved scale changes:
  ```
  Overlay scaling updated: window=3440x1440 px mode=fill base_scale=2.6875 …
  ```
- `tests/test_viewport_helper.py` and `overlay-client/tests/test_viewport_transform_module.py` encode the Fit/Fill expectations above. If you change the helper math, update both the tests and this reference table together.
