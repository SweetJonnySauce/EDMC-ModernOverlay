# Fill Mode Baseline (Pre-Grouping)

This note captures what we observed before introducing grouping-aware transforms in Fill mode. Keep it around as a reference when we start validating the new approach.

## LandingPad, Fill mode (3440×1440 overlay window)

- **Scale**: `scale=2.6875`, `scaled size=3440×1935`.
- **Offsets**: proportional remap reduces Y by ~0.744 → every point in the scene gets nudged individually, which makes circles collapse into horizontal ovals.
- **Visible symptom**: the radial lines no longer meet the dodecagon; the entire spider web looks squashed vertically.

## LandingPad, Fit mode (same window)

- **Scale**: `scale=2.0`, `scaled size=2560×1440`.
- **Offsets**: ±440 px pillarbox on each side.
- **Visible symptom**: geometry stays perfectly round; no squashing.

## Debug logging

To diagnose Fill mode further we added `fill_group_debug` to `debug.json`. When set to `true` and Fill mode is active, the overlay client now logs lines similar to:

```
fill-debug scale=2.688 size=(3440.0×1935.0) offset=(0.0, 0.0): LandingPad:shell-0 vector …
```

This gives us the raw vs pixel coordinates for each payload during a paint pass, so we can compare the per-object proportional offsets before and after we introduce grouping.
