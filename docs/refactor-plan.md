> This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.

# Overlay Client Refactor Plan

This document tracks the staged refactor of `overlay_client/overlay_client.py` into smaller, testable modules while preserving behavior and cross-platform support.

## Testing
After every change, do the following manual tests:
Restart EDMC then... 
```
source overlay_client/.venv/bin/activate
make check
make test
PYQT_TESTS=1 python -m pytest overlay_client/tests
python3 tests/run_resolution_tests.py --config tests/display_all.json
```

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| A | Audit remaining back-references in `LegacyRenderPipeline` to understand what still depends on `OverlayWindow`. | Completed |
| B | Introduce a `RenderSettings` bundle (font family, fallbacks, preset point-size helper, etc.) and pass it via `RenderContext`; update pipeline/grouping helper to use settings instead of window attributes. | Completed |
| C | Grouping refactor (see substeps) | Completed |
| C1 | Introduce grouping adapter that wraps `FillGroupingHelper` + payload snapshot; pipeline calls adapter instead of `OverlayWindow` for grouping prep. | Completed |
| C2 | Remove remaining direct payload/grouping accesses from pipeline; build commands/bounds from context + snapshot + adapter only. | Completed |
| C2.1 | Move grouping prep/command building into the adapter: pipeline calls adapter to build commands/bounds instead of `_build_legacy_commands_for_pass`/`_grouping_helper`. | Completed |
| C2.2 | Decouple group logging/state updates (see substeps) | Completed |
| C2.2.1 | Have pipeline return base/transform payloads and active keys instead of mutating `_group_log_pending_*` and cache directly; window applies existing logging/cache functions. | Completed |
| C2.2.2 | Move cache updates out: window calls `_update_group_cache_from_payloads` based on pipeline results. | Completed |
| C2.2.3 | Move log buffer mutations/trace helper calls to window: pipeline only reports what changed. | Completed |
| C2.3 | Decouple debug state/offscreen logging: pipeline reports debug data; window handles `_debug_group_*` and logging helpers. | Completed |
| C2.3.1 | Move debug-state construction/offscreen logging triggers to window; pipeline only returns data (commands/bounds/transforms/translations). | Completed |
| C2.3.2 | Verify dev/debug behaviors (outlines, anchor labels, vertex markers) in dev mode; run lint and `PYQT_TESTS=1 pytest overlay_client/tests`. | Completed |
| D | Decouple logging/trace and debug state: pass logging callbacks or result objects so pipeline stops mutating `_group_log_*` and debug caches directly. | Completed (mostly achieved during C2.2/C2.3) |
| D1 | Move group logging buffers fully out of pipeline: introduce callbacks/result structs for group base/transform logging, invoked by window. | Completed (implemented during C2.2.x) |
| D2 | Extract trace helper wiring: pipeline emits trace data via callback; window handles `_group_trace_helper` and related logging. | Completed (implemented during C2.2.3) |
| D3 | Move remaining debug state hooks (if any) to window via callbacks/result structs; ensure no pipeline mutation of debug caches. | Completed |
| E | Cleanup: remove remaining back-references, drop `sys.path` hacks in favor of package imports, and run full test suite + manual smoke. | Completed |
| E1.1 | Import/unused cleanup: fix imports, drop unused helpers/constants; run `ruff`/`mypy`. | Completed (lint/mypy clean; no unused imports/helpers found) |
| E1.2 | Remove `sys.path` hacks by formalizing package imports (or adjusting PYTHONPATH); fix fallout and rerun lint/tests. | Completed (renamed to `overlay_client`, package imports in place, launcher uses `-m`) |
| E2 | Residual back-reference check: confirm pipeline has no window mutations; tidy TODOs/comments; run `make check`. | Completed |
| E3 | Validation: `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, `python3 tests/run_resolution_tests.py --config tests/display_all.json`, plus brief manual smoke (dev mode outlines/anchors, follow, drag/click-through). | Completed (tests run; manual smoke still recommended) |

## Details

- **Phase A (Completed):** Cataloged the remaining pipeline dependencies on `OverlayWindow`:
  - Grouping: `_grouping_helper`, `_build_legacy_commands_for_pass`.
  - Payload/state: `_payload_model` store, `_group_offsets`, `_has_user_group_transform`.
  - Logging/state buffers: `_group_log_pending_*`, `_payload_log_delay`, `_update_group_cache_from_payloads`, `_flush_group_log_entries`, `_group_trace_helper`.
  - Debug/render state: `_dev_mode_enabled`, `_debug_config`, `_debug_group_bounds_final/_state`, `_cycle_anchor_points`.
  - Geometry/helpers: `width/height`, `_compute_group_nudges`, `_apply_anchor_translations_to_overlay_bounds`, `_apply_payload_justification`, `_clone_overlay_bounds_map`, `_build_group_debug_state`, `_log_offscreen_payload`, `_draw_group_debug_helpers`, `_draw_payload_vertex_markers`, `_legacy_preset_point_size`.
  - Time helper: `_monotonic_now` fallback.

- **Phase B (Completed):** Added `RenderSettings` to `RenderContext`, passed font/fallbacks/preset callback through to the pipeline, and updated grouping helper to consume settings instead of window attributes (no remaining window font/preset reads).

- **Phase C (Completed):** Defined a narrow grouping interface, moved grouping prep into an adapter, pulled logging/cache/debug/offscreen effects back into the window, and ensured commands/bounds are built from context + snapshot + adapter only.
  - Substep C1: Introduce a grouping adapter interface that wraps `FillGroupingHelper` and the payload snapshot; adjust the pipeline to call the adapter instead of reaching into `OverlayWindow` for grouping/transform prep.
  - Substep C2: Remove remaining direct payload/grouping accesses from the pipeline; ensure commands/bounds are built purely from context + snapshot + grouping adapter.

- **Phase D (Completed):** Logging/trace/debug mutations were already moved out of the pipeline during C2.2/C2.3. The pipeline now only returns data; the window handles logging buffers, trace helper, and debug state. Nothing further to do here.

- **Phase E (Completed):** Final cleanup, import hygiene, full test run (`PYQT_TESTS=1 pytest`), and a quick manual smoke.

## sys.path Removal Plan (Completed)

These steps make the client a normal package and remove the inline `sys.path` hacks. Keep work small and test after each chunk.

- Step 1: Rename `overlay-client/` to `overlay_client/`; ensure `__init__.py` is present in the package root. (Done)
  - 1.1: Physically rename the directory to `overlay_client/` (keep `__init__.py`). (Done)
  - 1.2: Update any references to the directory path in scripts/Makefile/CI/docs. (Done)
  - 1.3: Verify the launcher paths (EDMC loader/scripts) are updated to the new directory name. (Done; launcher now uses `-m overlay_client.overlay_client`)
- Step 2: Fix imports inside the client and tests to use package-qualified paths (e.g., `from overlay_client.payload_model import PayloadModel`). (Done)
- Step 3: Update entrypoints/scripts to launch as a module (`python -m overlay_client.overlay_client`) or adjust `PYTHONPATH`; update any tooling references (Makefile/CI/scripts) that point to the old path. (Done)
- Step 4: Remove `sys.path` manipulations from `overlay_client.py` (and any other files) once imports resolve normally. (Done)
- Step 5: Retest: `ruff`, `mypy`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, and a quick manual launch to confirm the overlay starts. If the plugin loader caches paths, update it to the new package path. (Tests run)
