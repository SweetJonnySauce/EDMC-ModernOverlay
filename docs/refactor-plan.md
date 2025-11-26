> This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.

# Overlay Client Refactor Plan

This document tracks the staged refactor of `overlay-client/overlay_client.py` into smaller, testable modules while preserving behavior and cross-platform support.

## Testing
After every change, do the following manual tests:
Restart EDMC then... 
```
source overlay-client/.venv/bin/activate
make check
make test
PYQT_TESTS=1 python -m pytest overlay-client/tests
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
| C2.2 | Decouple group logging/state updates (see substeps) | In progress |
| C2.2.1 | Have pipeline return base/transform payloads and active keys instead of mutating `_group_log_pending_*` and cache directly; window applies existing logging/cache functions. | Completed |
| C2.2.2 | Move cache updates out: window calls `_update_group_cache_from_payloads` based on pipeline results. | Completed |
| C2.2.3 | Move log buffer mutations/trace helper calls to window: pipeline only reports what changed. | Completed |
| C2.3 | Decouple debug state/offscreen logging: pipeline reports debug data; window handles `_debug_group_*` and logging helpers. | Completed |
| C2.3.1 | Move debug-state construction/offscreen logging triggers to window; pipeline only returns data (commands/bounds/transforms/translations). | Completed |
| C2.3.2 | Verify dev/debug behaviors (outlines, anchor labels, vertex markers) in dev mode; run lint and `PYQT_TESTS=1 pytest overlay-client/tests`. | Completed |
| D | Decouple logging/trace and debug state: pass logging callbacks or result objects so pipeline stops mutating `_group_log_*` and debug caches directly. | Pending |
| E | Cleanup: remove remaining back-references, drop `sys.path` hacks in favor of package imports, and run full test suite + manual smoke. | Pending |

## Details

- **Phase A (Completed):** Cataloged the remaining pipeline dependencies on `OverlayWindow`:
  - Grouping: `_grouping_helper`, `_build_legacy_commands_for_pass`.
  - Payload/state: `_payload_model` store, `_group_offsets`, `_has_user_group_transform`.
  - Logging/state buffers: `_group_log_pending_*`, `_payload_log_delay`, `_update_group_cache_from_payloads`, `_flush_group_log_entries`, `_group_trace_helper`.
  - Debug/render state: `_dev_mode_enabled`, `_debug_config`, `_debug_group_bounds_final/_state`, `_cycle_anchor_points`.
  - Geometry/helpers: `width/height`, `_compute_group_nudges`, `_apply_anchor_translations_to_overlay_bounds`, `_apply_payload_justification`, `_clone_overlay_bounds_map`, `_build_group_debug_state`, `_log_offscreen_payload`, `_draw_group_debug_helpers`, `_draw_payload_vertex_markers`, `_legacy_preset_point_size`.
  - Time helper: `_monotonic_now` fallback.

- **Phase B (Pending):** Add `RenderSettings` to `RenderContext` and thread it through pipeline/grouping helper; stop reading font/preset data from the window.
- **Phase B (Completed):** Added `RenderSettings` to `RenderContext`, passed font/fallbacks/preset callback through to the pipeline, and updated grouping helper to consume settings instead of window attributes.

- **Phase C (Completed):** Defined a narrow grouping interface, moved grouping prep into an adapter, pulled logging/cache/debug/offscreen effects back into the window, and ensured commands/bounds are built from context + snapshot + adapter only.
  - Substep C1: Introduce a grouping adapter interface that wraps `FillGroupingHelper` and the payload snapshot; adjust the pipeline to call the adapter instead of reaching into `OverlayWindow` for grouping/transform prep.
  - Substep C2: Remove remaining direct payload/grouping accesses from the pipeline; ensure commands/bounds are built purely from context + snapshot + grouping adapter.

- **Phase D (Pending):** Provide logging/debug callbacks or result structures to eliminate direct mutation of window log/debug state from the pipeline.

- **Phase E (Pending):** Final cleanup, import hygiene, full test run (`PYQT_TESTS=1 pytest`), and a quick manual smoke.
