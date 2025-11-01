# Testing Strategies

This document records the test coverage added (or required) for the aspect-ratio work, plus the manual spot checks that caught previous regressions. The goal is to make it obvious which commands to run and which screens to capture when you suspect a regression in overlay scaling.

## Automated Tests

| Scope | Command | Purpose |
|-------|---------|---------|
| Viewport helper | `pytest overlay-client/tests/test_viewport_helper.py` | Confirms the Fit and Fill strategies report expected scale factors and overflow flags for representative window sizes (16:9, 21:9, 4:3, tall portrait). |
| Vector renderer | `pytest tests/test_vector_renderer.py` | Verifies that vect payloads honour the new `offset_x` / `offset_y` parameters so points, markers, and labels land in the correct pixels. |
| Import sanity | `python3 -m compileall overlay_plugin overlay-client` | Catches syntax/indent errors in the plugin, preferences UI, and client modules without requiring PyQt at runtime. |

> **Note:** The existing `overlay-client/tests/test_geometry_override.py` suite needs PyQt6 present on the system; run it in environments where Qt is available to catch regressions in window sizing and guard code.

## Manual Verification

Because geometry rendering is visual, you should still smoke-test on real overlay windows after changes:

1. **16:9 baseline (Fit mode)**  
   - Launch the overlay in a 1920×1080 window.  
   - Enable the LandingPad CLI (`python3 tests/send_overlay_landingpad.py`).  
   - Confirm the radial lines meet the dodecagon vertices and width/height debug metrics report `scale.mode = fit`.

2. **21:9 ultrawide (Fit mode vs Fill mode)**  
   - Resize the overlay to 3440×1440 (or 2560×1080).  
   - Toggle the new “Overlay scaling mode” setting in preferences between **Fit** and **Fill**:
     * Fit should pillarbox the canvas—no clipping, equal padding on both sides.
     * Fill should expand the overlay and proportionally compress coordinates so radials still touch the dodecagon while utilising the full width; `scale.mode` should report `fill`.

3. **Alternative aspect (e.g., 4:3 or 3:2)**  
   - Check that both modes keep payloads visible; Fill will crop the shorter edge but never push geometry off-screen due to the proportional remap.

Capture screenshots or debug overlay dumps for these steps whenever you introduce a change that affects scaling. That way we keep a rolling visual baseline to compare against regressions.
