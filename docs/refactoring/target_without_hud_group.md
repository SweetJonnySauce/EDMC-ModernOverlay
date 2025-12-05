Target box mismatch when no HUD group is drawn
===============================================

Context
-------
- Scenario: Controller target box + anchor are drawn when the controller is active, even if the payload group is off-screen or expired.
- Example: `EDR Docking` cache entry shows correct base_min_x/base_min_y from the plugin, but the target renders too low vertically when the payload is not visible.
- Goal: Explain why the fallback target rendering does not apply the proportional remap used during live rendering.

What happens today
------------------
- Live paint path (payload on-screen):
  - Fill mode builds a `FillViewport` and computes proportional translation via `compute_proportional_translation` (overlay_client/payload_builders.py) using the group’s band/anchor data.
  - The translated overlay bounds for each group are stored in `_last_overlay_bounds_for_target` during `_paint_legacy` (overlay_client/render_surface.py) and are used to draw the target box/anchor. This renders correctly.
- Fallback path (payload off-screen/expired):
  - `_paint_controller_target_box` falls back to `_fallback_bounds_from_cache` when `_last_overlay_bounds_for_target` has no entry.
  - `_fallback_bounds_from_cache` simply reads the cached `base_*` values from `overlay_group_cache.json` and converts them to a rect with `_overlay_bounds_to_rect`. No proportional remap or overflow handling is applied.
  - The cache “base” values come from `_rebuild_legacy_render_cache` (overlay_client/render_pipeline.py): they are the pre-translation logical bounds. A `transformed` block is only persisted when user transforms/offsets exist; the Fill proportional shift is never saved.
  - Result: In Fill mode with an overflowing axis, the target box/anchor are drawn using unshifted base coords, so they appear offset (e.g., too low vertically).

Implications
------------
- Any group that relies on Fill-mode proportional translation will draw its target incorrectly whenever the HUD group is absent. Base_min_x/base_min_y from the plugin remain correct; the missing remap on the overflow axis causes the visual mismatch.

Potential fixes
---------------
- Persist translated bounds: write the Fill-translated overlay bounds into the cache `transformed` block even when no user transform/offsets exist.
- Recompute on fallback: in `_fallback_bounds_from_cache`, rebuild a temporary `GroupTransform` from cached base/anchor + current viewport and apply `compute_proportional_translation` before drawing.

Forcing a “transformed” cache entry (even with dx=dy=0)
-------------------------------------------------------
- `_has_user_group_transform` only returns true when anchor != `nw` or payload justification != `left`; it ignores offsets and Fill-mode overflow.
- `has_transformed` in `render_pipeline._rebuild_legacy_render_cache` is set when offsets are non-zero or `_has_user_group_transform` is true. A Fill-only proportional shift will not trigger it.
- Ways to force the target to be treated as transformed (so a `transformed` block is cached):
  - Code change: treat Fill-mode groups as transformed whenever the viewport overflows (e.g., set `has_transformed = True` when `transform` exists and `mapper.transform.mode is ScaleMode.FILL`), or teach `_has_user_group_transform` to consider Fill-overflow as “transformed”.
  - Override trick: set a non-default anchor or justification in overrides for the group. This flips `_has_user_group_transform` to true even with `dx=0, dy=0`, so the `transformed` block is written. (Zero offsets alone won’t do it.)

Plan: robust fallback translation
---------------------------------
1) Update fallback logic: `_fallback_bounds_from_cache` should reconstruct a minimal `GroupTransform` from cached base bounds + anchor token, build a Fill viewport with the current mapper/device state, and apply `compute_proportional_translation` before drawing the target box/anchor. This mirrors the live paint path without requiring a visible payload.
2) Tests: add controller-target tests that simulate Fill overflow on the Y axis and assert the fallback rect is translated (e.g., base_min_y → shifted min_y) and anchor follows suit. Keep FIT mode unchanged.
3) Risk mitigation:
   - Miscomputed anchor_norms could over-shift groups: clamp normalized coords to [0,1] and use constants `BASE_WIDTH/BASE_HEIGHT`.
   - Double-applying offsets: ensure fallback uses cache bounds as-is (already includes offsets) and only applies the proportional shift.
   - Unexpected side effects in non-Fill modes: guard translation to Fill + overflow only; FIT should remain untouched.

Plan: controller snapshot translation (anchor/payload alignment)
---------------------------------------------------------------
Goal: When the controller builds a snapshot from cache-only data, apply the same Fill proportional translation used in the client fallback so anchor/payload preview aligns with the translated target box.

Steps
1) Snapshot path: In `overlay_controller._get_group_snapshot` (or a helper it calls), detect when only base cache data exists and the current scale mode is Fill with overflow. Rebuild a minimal `GroupTransform` from the base bounds + anchor token and apply `compute_proportional_translation` to derive translated bounds/anchor for the snapshot.
2) Keep FIT untouched: Only translate when Fill + overflow are active; FIT keeps the raw base.
3) Tests: Add controller snapshot/unit tests covering:
   - FIT mode: snapshot uses base bounds/anchor unchanged.
   - Fill overflow Y: translated bounds/anchor shift proportionally; cached base is unchanged.
   - Anchor tokens: verify anchor mapping respects token while translating.

Risks & mitigations
- Anchor drift due to bad normalisation: clamp band/anchor normals to [0,1] and use `BASE_WIDTH/BASE_HEIGHT`.
- Double-translation: ensure controller snapshot uses base bounds once and applies only the proportional delta; do not re-apply offsets or nudges.
- Behaviour divergence from client: reuse the same helper (`compute_proportional_translation` + `build_viewport`) to keep parity with the render-side fix.

Plan: feed live anchor into controller fallback translation
----------------------------------------------------------
Goal: Allow anchor changes in the controller UI/overrides to influence the fallback translation and anchor dot when no transformed cache block exists.

Steps
1) Snapshot translation: extend `_translate_snapshot_for_fill` to accept an explicit anchor token/point. When we have live anchor from the widget/overrides, use it; otherwise fall back to the cached token.
2) Wire-in live anchor: in `_draw_preview`, resolve the live anchor token first, and pass it into `_translate_snapshot_for_fill` before computing target/anchor visuals.
3) Tests: add unit tests that:
   - Change anchor token to `ne`/`center` and confirm translated bounds shift in X/Y accordingly under Fill overflow.
   - Keep FIT mode unchanged.
4) Guardrails: clamp anchor normals as before, and ensure we only apply translation once (no double offsets).

Risks & mitigations
- Using stale anchor: always prefer live widget anchor when available; otherwise use cache token.
- Over-shift/under-shift: reuse `compute_proportional_translation` and clamp inputs to [0,1].
- FIT-mode regression: gate translation to Fill + overflow only.

Plan: feed live anchor into client fallback translation (HUD target box)
-----------------------------------------------------------------------
Goal: When the overlay client draws the controller target from cache fallback, use the live/controller anchor token so the box shifts in X/Y instead of sticking to the cached `nw`.

Steps
1) Propagate anchor: surface the current controller anchor to the overlay client (e.g., store on the client when controller updates selection).
2) Fallback path: update `_fallback_bounds_from_cache` (overlay_client/render_surface.py) to accept an anchor override and use it in `_apply_fill_translation_from_cache` and anchor drawing; default to cached token if no override.
3) Wire call: when `_paint_controller_target_box` invokes `_fallback_bounds_from_cache`, pass the live anchor override.
4) Tests: add unit tests for fallback translation with anchor override:
   - Fill overflow + anchor override (`ne`/`center`) shifts X/Y relative to cached `nw`.
   - FIT mode unchanged.
5) Guardrails: gate translation to Fill + overflow; clamp normals; safe fallback if override missing.

Risks & mitigations
- Missing propagation: ensure controller-to-client path sets the override; fallback keeps cached token if absent.
- Double translation: apply proportional shift once; avoid reapplying offsets.
- Non-Fill regression: guard to Fill + overflow only.

Plan: propagate live anchor to client fallback (HUD target)
-----------------------------------------------------------
Goal: Make the HUD target box honor the controller’s current anchor even when rendering from cache fallback.

Steps
1) Carry anchor over IPC: when the controller sends the active group selection, include the current anchor token. In the client, store this as `_controller_active_anchor` keyed by active group.
2) Fallback hook: update `_paint_controller_target_box`/`_fallback_bounds_from_cache` (overlay_client/render_surface.py) to accept an anchor override and use it for fill translation and anchor dot placement.
3) Source selection: choose the override anchor in this order: live controller anchor (if matches active group), then cache/transformed anchor, then default.
4) Tests: add unit tests that:
   - With fill overflow and anchor override `center`/`e`, X shifts versus cached `nw`.
   - FIT mode remains unchanged.
5) Guardrails: keep translation gated to Fill + overflow; clamp normals; no double offsets.

Risks & mitigations
- Missing anchor payload from controller: fallback to cached token; log once in debug.
- Divergence if group changes: tie anchor override to the active group key so stale anchors don’t leak.
- Non-Fill impact: guard to Fill + overflow only.
