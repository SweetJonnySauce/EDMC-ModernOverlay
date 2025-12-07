# Center justification offset issue

## Problem
- Center-justified payloads (e.g., text) shift too far right and can overflow the containing rect.
- Current behavior uses a per-group baseline width for justification; wider items in the same group (like the rect) can inflate that baseline, so the text is pushed right.

## Observations
- Baseline source: `_apply_payload_justification` builds baseline bounds from `base_overlay_bounds` (preferred) or current overlay bounds, then `compute_justification_offsets` applies `(baseline - width) / 2` for center.
- All commands in a group contribute to the baseline today, even if only some are justified, and large rects can dominate the baseline.
- Right-just deltas are separate; the center issue is driven purely by the baseline width being larger than the text width.

## Attempted fix (reverted)
- Change attempted: in `overlay_client/render_surface.py::_apply_payload_justification`, we merged `base_overlay_bounds`/`overlay_bounds` only for commands with `justification in {"center", "right"}` to keep rect bounds out of the baseline map. We also merged per-command bounds into the maps before calling `compute_justification_offsets`, rather than using the pre-aggregated group maps.
- Outcome: visually still over-shifted right; user reverted the patch.
- Tests: not run (pytest not available in this environment at the time), so no automated signal on regressions—only visual feedback.

## Next steps to fix
- Re-apply a scoped baseline filter, then verify visually and with unit tests:
  - Add a test: center-justified text + non-justified rect in same group should center based on text width, not rect width.
  - Ensure scale handling isn’t double-counting (baseline already logical vs. multiplied by `base_scale`).
- If filtering per-command bounds isn’t enough, consider:
  - Separate suffix/group for non-justified rects, or
  - Fallback to max width among justify-participating commands when baseline comes from mixed geometry.

## Notes
- No repo state changes remain; only this note documents the session and findings.

## Repro context (document)
- Layout: rect plus text payload in same group/suffix; rect likely not justified, text set to `center`.
- Observed: centered text shifts right and overflows the rect boundary.
- Cause hypothesis: baseline width pulled from rect’s base bounds (wider than text) → `(baseline - text_width)/2` pushes right.

## Next experiment snapshot
- Files to touch: `overlay_client/render_surface.py::_apply_payload_justification` and related tests in `overlay_client/tests/test_anchor_helpers.py` (add case: center text + wide rect, baseline should be text width).
- Plan: filter baseline candidates to justify-participating commands and/or cap baseline to max width among justify requests; verify no double-scaling of baseline (logical vs. base_scale).
- Validation: run targeted pytest (anchor_helpers/payload_justifier/vector_justification) and manual visual check with the rect+centered text scenario above.
