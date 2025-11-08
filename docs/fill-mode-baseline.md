# Fill Mode Diagnostics (Grouping-Aware Behaviour)

Fill mode now keeps related payloads rigid by translating whole groups instead of squeezing each payload independently. This file documents how the current code paths work so you know which values to inspect when validating fixes.

## Grouping pipeline

1. `FillGroupingHelper.prepare()` runs before every Fill-mode paint pass. It walks `OverlayWindow._legacy_items`, determines a grouping key (plugin by default, or plugin/prefix when `plugin_overrides.json` declares `grouping.mode = "id_prefix"`), and accumulates bounds via `payload_transform.accumulate_group_bounds()`.
2. The helper stores a `GroupTransform` per group inside `GroupTransformCache`. Each transform tracks the raw bounds (min/max overlay coordinates) plus normalised band/anchor values (`band_*`, `band_anchor_*`) expressed as percentages of the 1280 × 960 legacy canvas.
3. When a payload is painted, `overlay_client._paint_legacy_*` builds a `FillViewport` with `viewport_transform.build_viewport()` and, if Fill mode is active, computes a proportional translation via `compute_proportional_translation()`. That translation re-centres the group so the anchor remains visible even though the canvas overflowed in one axis.
4. `GroupTransform` anchors default to the group’s north‑west corner, but overrides can pin the anchor to `center`, `ne`, `sw`, or `se`. Anchors are resolved through `PluginOverrideManager.group_preserve_fill_aspect()` so prefix-specific overrides stay in sync with the renderer.

Effectively, scaling is now uniform: Fill uses the same scale factor on both axes, the inverse group-scale step reverts grouped payloads to their original logical size, and the proportional translation reintroduces controlled letterboxing/pillarboxing per group.

## Anchors via plugin overrides

`plugin_overrides.json` continues to drive grouping. For example, LandingPad keeps every payload rigid:

```jsonc
"LandingPad": {
  "grouping": { "mode": "plugin" }
}
```

Mining Analytics splits alerts from metrics:

```jsonc
"EDMC-MiningAnalytics": {
  "grouping": {
    "mode": "id_prefix",
    "prefixes": {
      "metrics": { "prefix": "edmcma.metric.", "anchor": "center" },
      "alerts": { "prefix": "edmcma.alert.", "anchor": "se" }
    }
  }
}
```

Every prefix shares the same proportional shift, so gauges and badges remain rigid even when the Fill viewport overflows.

## Debugging tools

- Set `fill_group_debug = true` in `debug.json` to log per-payload diagnostics whenever Fill mode is active. Each paint pass emits lines similar to:
  ```
  fill-debug scale=2.688 size=(3440.0×2580.0) base_offset=(0.0, 0.0): LandingPad:shell-0 vector … band=x[0.102,0.898] y[0.321,0.679] anchor=(0.500,0.500)
  ```
  The `band` block shows the normalised bounds and anchor that produced the proportional translation.
- Toggle `group_bounds_outline` (also in `debug.json`) to draw the cached bounds/anchor dots for each group directly on the overlay. This highlights which payloads are sharing a Fill translation.
- Enable `overlay_outline` to see the raw window tracked by the overlay client. Verifying that the dashed group bounds stay rigid relative to this outline is the quickest visual regression test.

When investigating a Fill regression:

1. Ensure the plugin override declares the expected grouping mode/prefixes.
2. Enable `fill_group_debug` and confirm the log shows one entry per group, not per payload (duplicates imply overrides didn’t match).
3. Use `tests/send_overlay_from_log.py --log tests/landingpad.log` to replay real payloads while watching the debug overlay. The `fill-debug` lines should report consistent band ranges even as the window size changes.
