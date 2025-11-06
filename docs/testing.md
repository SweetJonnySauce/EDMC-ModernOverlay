# Testing Strategies

This document records the test coverage added (or required) for the aspect-ratio work, plus the manual spot checks that caught previous regressions. The goal is to make it obvious which commands to run and which screens to capture when you suspect a regression in overlay scaling.

## Automated Tests

| Scope | Command | Purpose |
|-------|---------|---------|
| Viewport helper | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_viewport_helper.py` | Confirms the Fit and Fill strategies report expected scale factors and overflow flags for representative window sizes (16:9, 21:9, 4:3, tall portrait). |
| Vector renderer | `overlay-client/.venv/bin/python -m pytest tests/test_vector_renderer.py` | Verifies that vect payloads honour the new `offset_x` / `offset_y` parameters so points, markers, and labels land in the correct pixels. |
| Group transform cache | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_group_transform.py` | Checks that per-group bounding boxes accumulate correctly and cache lookups are consistent. |
| Override grouping parser | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_override_grouping.py` | Ensures the override manager honours `grouping.mode` and explicit prefix maps when deriving Fill-mode groups. |
| Import sanity | `python3 -m compileall overlay_plugin overlay-client` | Catches syntax/indent errors in the plugin, preferences UI, and client modules without requiring PyQt at runtime. |

### Environment setup

Before running the suites:

1. **Create/activate the client virtualenv** (if not already present):
   ```bash
   python3 -m venv overlay-client/.venv
   source overlay-client/.venv/bin/activate
   pip install -U pip
   ```

2. **Install development dependencies and the plugin in editable mode**:
   ```bash
   pip install -e .[dev]
   ```
   The `pyproject.toml` defines a minimal editable package; installing it ensures `from EDMCOverlay import edmcoverlay` succeeds during tests.

3. **Run pytest via the venv interpreter**:
   ```bash
   overlay-client/.venv/bin/python -m pytest
   ```

> **Note:** The existing `overlay-client/tests/test_geometry_override.py` suite needs PyQt6 present on the system; run it in environments where Qt is available to catch regressions in window sizing and guard code.

If you run tests from scratch (e.g. CI or fresh clone), steps 1–2 ensure the environment mirrors what pytest expects. For ad-hoc runs, `source overlay-client/.venv/bin/activate` followed by the relevant `pytest` command is sufficient.

## Manual Verification

Because geometry rendering is visual, you should still smoke-test on real overlay windows after changes:

1. **4:3 baseline (Fit mode)**  
   - Launch the overlay in a 1920×1440 window.  
   - Enable the LandingPad CLI (`python3 tests/send_overlay_landingpad.py`).  
   - Confirm the radial lines meet the dodecagon vertices without pillarboxing and the debug metrics report `scale.mode = fit`.

2. **21:9 ultrawide (Fit mode vs Fill mode)**  
   - Resize the overlay to 3440×1440 (or 2560×1080).  
   - Toggle the new “Overlay scaling mode” setting in preferences between **Fit** and **Fill**:
     * Fit should pillarbox the canvas—no clipping, equal padding on both sides.
     * Fill should expand the overlay and proportionally compress coordinates so radials still touch the dodecagon while utilising the full width; `scale.mode` should report `fill`.
   - With `fill_group_debug` set to `true` (see `debug.json`), confirm the log shows a single Δ for every LandingPad payload—evidence that grouping keeps the pad rigid.

3. **Alternative aspect (e.g., 4:3 or 3:2)**  
   - Check that both modes keep payloads visible; Fill will crop the shorter edge but never push geometry off-screen due to the proportional remap.

4. **Prefix-based grouping (e.g., Mining Analytics)**  
   - Ensure the plugin override declares `grouping.mode = "id_prefix"` with at least two prefixes (metrics vs. alerts).  
   - Send sample payloads (Mining Analytics’ overlay refresh is sufficient) and, in Fill mode, verify that each prefix logs its own Δ while geometry inside each prefix stays aligned.

Capture screenshots or debug overlay dumps for these steps whenever you introduce a change that affects scaling. That way we keep a rolling visual baseline to compare against regressions.
