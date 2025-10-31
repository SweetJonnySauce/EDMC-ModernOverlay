# Plugin Override Developer Guide

This document explains how Modern Overlay’s plugin override system works and how to extend it
when you need to massage payloads coming from a specific plugin.

The override engine lives entirely on the overlay client side. It inspects each incoming
`LegacyOverlay` payload, figures out which plugin produced it, and (when a matching rule exists)
mutates the payload before it gets stored/rendered. The configuration is stored in
`plugin_overrides.json` at the repository root.

## File Layout

The JSON file is a dictionary keyed by plugin name. Each plugin entry contains two kinds of keys:

```jsonc
{
  "LandingPad": {
    "__match__": { ... },     // optional helper metadata
    "pattern": { ... },       // payload overrides
    "pattern2": { ... }
  }
}
```

- `__match__` (optional) provides hints for discovering the plugin when a payload does not
  explicitly state its origin.
- `notes` (optional) is freeform documentation (string or array of strings) explaining why the plugin needs overrides. Modern Overlay ignores this field entirely; it exists purely for humans reviewing the JSON.
- `transform`, `x_scale`, `x_shift` placed directly under the plugin act as plugin-wide defaults that run before any pattern-specific overrides.
- Every other key is a glob pattern (`fnmatch` rules) that will be compared against the payload’s
  `id`. The corresponding object lists the overrides to apply.

### Match Helpers

Modern Overlay tries to read the plugin name from the payload (`payload["plugin"]`,
`payload["meta"]["plugin"]`, or `payload["raw"]["plugin"]`). When the plugin field is missing,
`__match__` helps narrow down the source.

Supported helper fields:

| Field         | Type           | Description                                                   |
| ------------- | -------------- | ------------------------------------------------------------- |
| `id_prefixes` | array of string| Treat payloads whose `id` starts with any prefix as this plugin. |

Example:

```jsonc
"__match__": {
  "id_prefixes": ["shell-", "line-", "toaster-"]
}
```

### Pattern Blocks

Each pattern block contains the override settings. Patterns are evaluated in declaration order;
the first match wins.

Current override keys:

| Key         | Type              | Description                                                                                                     |
| ----------- | ----------------- | ----------------------------------------------------------------------------------------------------------------- |
| `x_scale`   | number or string  | Scales the payload along X. Numbers are absolute factors (1.0 keeps original width). Special modes are described below. |
| `x_shift`   | number or object  | Translates X after scaling. A numeric value shifts by that many logical units; object forms can align to a target centre. |
| `transform` | object            | Applies 2-D scaling and translation with an explicit pivot. Ideal when a plugin pre-warps its coordinates and needs symmetric correction. |

`x_scale` supports a few computed modes in addition to numeric constants:

| Mode name                   | Purpose                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| `"derive_ratio_from_height"`| Inspect the first matching shape, compute √(span<sub>y</sub> / span<sub>x</sub>), and cache that ratio for the plugin. |
| `"use_cached_ratio"`        | Reuse the most recent cached ratio for the plugin (typically following a `"derive_ratio_from_height"` rule). |

`x_shift` accepts either a numeric literal (for a fixed post-scale translation) or an object such as
`{"mode": "align_center", "target": 75.5}` which moves the payload so its centre aligns with the
specified X coordinate after scaling.

The cache is per plugin. You usually define a single “derive” rule (for a representative shape) and
point all related shapes at `"use_cached_ratio"`.

The `transform` directive mirrors the prototype harness in `tests/scale-prototype`. It accepts two optional sub-blocks:

```jsonc
"transform": {
  "scale": {
    "x": 2.0,
    "y": 1.0,
    "point": "sw",               // Anchor used to compute the pivot; defaults to "NW"
    "pivot": {"x": 50, "y": 60}, // Optional explicit pivot override
    "source_bounds": {           // Optional fallback bounds when the payload lacks points
      "min": {"x": 0, "y": 0},
      "max": {"x": 128, "y": 128}
    }
  },
  "offset": {
    "x": 0.0,
    "y": 150.0
  }
}
```

If `pivot` is omitted, the pivot is derived by combining the selected anchor (`point`) with either the payload’s
current bounding box or the optional `source_bounds`. Offsets are applied after scaling, so a zero scale with a non-zero
offset still performs a pure translation. Leaving the block empty is a no-op. You can also set `point` to an object
containing `x` and `y`; ModernOverlay will use that explicit coordinate as the pivot (equivalent to `pivot`, but more
convenient when you just need to override the anchor).

Modern Overlay applies overrides in this order: `transform` → `x_scale` → `x_shift`. That makes the transform block the
place to normalise a plugin’s coordinate system before any legacy tweaks run. You can still follow up with an
`x_shift` alignment if the incoming data is missing its expected centre.

Example block:

```jsonc
"shell-*": {
  "x_scale": "derive_ratio_from_height"
},
"toaster-*": {
  "x_scale": "use_cached_ratio"
}
```

A transform-driven equivalent:

```jsonc
"shell-*": {
  "transform": {
    "scale": {"x": 2.0, "y": 1.0, "point": "sw"},
    "offset": {"y": 150.0}
  }
}
```

Plugin-wide defaults can live alongside `__match__`; they run before any pattern-specific overrides and save you from
repeating the same transform for every ID.

## Worked Example

To add overrides for a hypothetical plugin “FooHUD” that emits squashed rectangles (`foo-*`) and
messages (`foo-msg-*`):

1. Update `plugin_overrides.json`:

   ```jsonc
   {
     "FooHUD": {
       "__match__": {
         "id_prefixes": ["foo-"]
       },
       "foo-shell": {
         "x_scale": "derive_ratio_from_height"
       },
       "foo-*": {
         "x_scale": "use_cached_ratio"
       },
       "foo-msg-*": {
         "font_size": "small"
       }
     }
   }
   ```

   (The `font_size` key above is illustrative; you can introduce new keys as the client gains support.)

2. Restart or reload the overlay client. The override manager watches the config file timestamp and
   auto-reloads, so editing the JSON is usually enough—no code changes required unless you add a new
   override type.

### LandingPad field notes

The legacy LandingPad plugin still emits coordinates pre-scaled by an `aspect_x` that halved every X value. ModernOverlay
already stretches legacy coordinates to the actual overlay window, so those payloads needed to be un-squashed and nudged
into place. The `transform` directive lets us replicate the prototype math captured in `tests/scale-prototype`—the same
math that `draw_shapes.py` uses for local inspection.

```jsonc
"LandingPad": {
  "notes": [
    "LandingPad added aspect_x years ago to compensate for the original Windows-only EDMCOverlay.exe.",
    "That binary rendered into a fixed 1280x1024 virtual canvas, and the plugin's coordinates assumed it was being stretched to fit arbitrary screen sizes.",
    "",
    "By multiplying X by an extra factor derived from the monitor dimensions (calc_aspect_x), LandingPad tried to undo the horizontal stretch so the dodecagon stayed round.",
    "ModernOverlay already handles that scaling, so leaving aspect_x active doubles the correction and flattens the pad."
  ],
  "__match__": {
    "id_prefixes": ["shell-", "line-", "toaster-left-", "toaster-right-", "pad-"]
  },
  "transform": {
    "scale": { "x": 2.0, "y": 1.0, "point": "sw" },
    "offset": { "y": 150.0 }
  }
}
```

- Scaling around the south-western corner (`point: "sw"`) doubles every X span—undoing the plugin’s extra compression.
- The shared `offset.y` mimics the legacy `landingpad.json` translation so the pad sits at the expected vertical origin.
- No explicit `pivot` is required because the payload coordinates include all of the vertices the transform needs to
  deduce its bounds.
- The plugin-level `notes` array is just documentation for humans; Modern Overlay ignores it, but it keeps the rationale beside the configuration.

This pattern keeps the adjustment in the adapter layer while leaving the plugin’s source intact. If a future plugin
applies a similar workaround (for example, only providing a single anchor point instead of polygons), you can set
`source_bounds` to the rectangle the plugin was targeting and reuse the same transform logic.

## Testing Your Overrides

1. Run `python3 -m compileall overlay-client` to ensure the Python modules still compile.
2. With `log_payloads` enabled, observe the overlay client log (`overlay-client/logs/.../overlay-client.log`)
   to verify that the overrides are being applied—look for DEBUG lines mentioning “Loaded … plugin override”.
3. Use the CLI helper in `tests/send_overlay_landingpad.py` or your plugin’s test harness to emit a payload
   and check that the rendered output matches expectations.

## Extending the Override Engine

When you need a new override type (e.g., gutters or font tweaks):

1. Add the key to the JSON.
2. Update `PluginOverrideManager._apply_override` to interpret the new directive.
3. Implement the helper (likely alongside `_scale_vector` / `_scale_rect`).
4. Document the new option in this guide.

Because the JSON is declarative, most adjustments can be achieved without touching plugin code—ideal
for keeping third-party plugins compatible with Modern Overlay going forward.

## Debugging Overrides

To trace how a specific payload is transformed, create `debug.json` alongside
`plugin_overrides.json` with the following structure:

```json
{
  "trace_enabled": true,
  "plugin": "LandingPad",
  "payload_id": "line-0"
}
```

When tracing is enabled the overlay client logs each transformation stage (scale/shift) for the
matching payload ID, making it easier to reconcile expected vs. actual coordinates. Set
`trace_enabled` back to `false` when you are done to avoid noisy logs.
