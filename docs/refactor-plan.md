# Overlay Client Refactor Plan

This document tracks the staged refactor of `overlay-client/overlay_client.py` into smaller, testable modules while preserving behavior and cross-platform support.

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| A | Audit remaining back-references in `LegacyRenderPipeline` to understand what still depends on `OverlayWindow`. | Completed |
| B | Introduce a `RenderSettings` bundle (font family, fallbacks, preset point-size helper, etc.) and pass it via `RenderContext`; update pipeline/grouping helper to use settings instead of window attributes. | Completed |
| C | Define a grouping helper interface/adapter; pass payload snapshot and grouping interface into the pipeline so it no longer reaches into the window for grouping/transform prep. | Pending |
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

- **Phase C (Pending):** Define a narrow grouping interface and use payload snapshots; remove direct window access for grouping/transform prep.

- **Phase D (Pending):** Provide logging/debug callbacks or result structures to eliminate direct mutation of window log/debug state from the pipeline.

- **Phase E (Pending):** Final cleanup, import hygiene, full test run (`PYQT_TESTS=1 pytest`), and a quick manual smoke.
