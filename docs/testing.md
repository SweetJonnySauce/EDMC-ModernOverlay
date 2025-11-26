# Testing Strategies

This guide documents the automated suites and manual spot checks that keep the Fit/Fill work honest. Use it as a checklist whenever you change viewport math, grouping, or CLI tooling.

## Automated tests

| Scope | Command | Purpose |
|-------|---------|---------|
| Viewport helper | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_viewport_helper.py` | Verifies that `compute_viewport_transform()` reports the correct scales, offsets, and overflow flags for 4:3, 16:9, 21:9, and portrait windows. |
| Viewport transform | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_viewport_transform_module.py` | Exercises `build_viewport()`, proportional translations, and scaled font helpers to ensure Fill remapping math stays consistent. |
| Group transform cache | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_group_transform.py` | Confirms `GroupTransformCache` tracks bounds per plugin/prefix and resets cleanly between frames. |
| Override grouping parser | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_override_grouping.py` | Guards the JSON parser that turns `overlay_groupings.json` into grouping metadata (prefix matching, anchors, plugin-level group detection). |
| Plugin group API | `overlay-client/.venv/bin/python -m pytest tests/test_overlay_api.py` | Ensures the public API enforces schema rules (required prefixes, anchors) while updating `overlay_groupings.json`. |
| Overlay render cache (PyQt) | `PYQT_TESTS=1 overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_overlay_client_cache.py` | Verifies grid pixmap reuse and legacy render caching aren’t rebuilt every paint; requires PyQt6. |
| Payload bounds (PyQt) | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_payload_bounds.py` | Uses PyQt’s font metrics to prove that message/rect bounds scale correctly before grouping. Skipped automatically if PyQt6 is missing. |
| Payload text metrics (PyQt) | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_payload_text_metrics.py` | Tests `_measure_text_block` so multi-line labels produce consistent bounds. Requires PyQt6. |
| Renderer transform order (PyQt) | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_renderer_transform_order.py` | Ensures Fill translations are applied before scaling when `__mo_transform__` metadata is present. Requires PyQt6. |
| Geometry override (PyQt) | `overlay-client/.venv/bin/python -m pytest overlay-client/tests/test_geometry_override.py` | Catch regressions in window-manager override classification (min-size clamps, forced resize). Requires PyQt6. |
| Vector renderer | `overlay-client/.venv/bin/python -m pytest tests/test_vector_renderer.py` | Validates the Qt-independent renderer honours per-point offsets and markers. |
| Legacy processor | `overlay-client/.venv/bin/python -m pytest tests/test_legacy_processor.py` | Exercises payload ingestion, TTL handling, and store eviction logic. |
| Import sanity | `python3 -m compileall overlay_plugin overlay-client` | Fast guard against syntax errors in both halves of the project without touching Qt. |

### Environment setup

All of the above assume a local venv:

1. Create/activate the environment (once per machine):
   ```bash
   python3 -m venv overlay-client/.venv
   source overlay-client/.venv/bin/activate
   pip install -U pip
   ```
2. Install Modern Overlay in editable mode with dev extras:
   ```bash
   pip install -e .[dev]
   ```
3. Run whichever test target you need. `overlay-client/.venv/bin/python -m pytest` without arguments executes everything that does not require PyQt, while adding `-k` filters narrows the run.

For PyQt-dependent suites, ensure PyQt6 is installed and set `PYQT_TESTS=1`:
```bash
source overlay-client/.venv/bin/activate
PYQT_TESTS=1 overlay-client/.venv/bin/python -m pytest overlay-client/tests  # runs PyQt-required tests too
```

> PyQt-dependent suites (`test_geometry_override`, `test_payload_bounds`, `test_payload_text_metrics`, `test_renderer_transform_order`) will skip automatically when Qt is missing, but you should run them on a workstation that has PyQt6 installed before releasing.

## Manual verification

Automated tests cannot replace eyeballing the overlay, especially when dealing with Fill translations. Rely on the CLI drivers in `tests/` to reproduce common payloads.

1. **4:3 Fit baseline**  
   - Resize the overlay window to 1920×1440 and select **Fit** in preferences.  
   - Replay the LandingPad log: `python3 tests/send_overlay_from_log.py --log payload_store/landingpad.log`.  
   - Use the developer overlay to confirm `scale.mode = fit`, `scale_x = scale_y`, and radial lines meet the dodecagon.

2. **21:9 Fit vs Fill**  
   - Switch the window to 3440×1440 (or 2560×1080).  
   - Toggle between **Fit** and **Fill**. Fit should pillarbox with equal padding; Fill should report `overflow_y = true` and keep LandingPad rigid.  
   - Enable `group_bounds_outline` in `debug.json` to highlight each group’s anchor box while verifying that every payload within a group moves in lockstep.

3. **Tall portrait sanity**  
   - Use `python3 tests/run_resolution_tests.py --config tests/test_resolution.json --wait-to-finish 3` to drive a mock Elite window through the portrait sizes configured in `tests/test_resolution.json`.  
   - Verify Fill mode now translates horizontally (overflow_x) while Fit applies letterboxing above/below.

4. **Prefix-based grouping**  
   - Ensure `overlay_groupings.json` declares `grouping.mode = "id_prefix"` for Mining Analytics (or another multi-widget plugin).  
   - Replay `payload_store/edr_docking.log` or your plugin’s log via `tests/send_overlay_from_log.py`.  
   - With `group_bounds_outline` enabled, Fill mode should render distinct dashed rectangles (and anchor dots) for each configured prefix while keeping them rigid relative to one another.

5. **Ad-hoc payloads**  
   - `python3 tests/send_overlay_shape.py --length 220 --angle 45` draws a synthetic vector arrow so you can confirm scaling remains isotropic.  
   - `python3 tests/send_overlay_text.py --text "Lorem ipsum"` is useful for checking font metrics after tinkering with viewport math.

Capture screenshots or copy the debug overlay text whenever a regression is suspected; keeping before/after evidence in the issue tracker has been invaluable when verifying ultrawide fixes.
