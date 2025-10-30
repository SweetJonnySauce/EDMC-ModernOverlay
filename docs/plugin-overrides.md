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

| Key       | Type                | Description                                                                                                     |
| --------- | ------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `x_scale` | number or string    | Scales the payload along X. Numbers are absolute factors (1.0 keeps original width). Special modes are described below. |

`x_scale` supports a few computed modes in addition to numeric constants:

| Mode name                   | Purpose                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------- |
| `"derive_ratio_from_height"`| Inspect the first matching shape, compute √(span<sub>y</sub> / span<sub>x</sub>), and cache that ratio for the plugin. |
| `"use_cached_ratio"`        | Reuse the most recent cached ratio for the plugin (typically following a `"derive_ratio_from_height"` rule). |

The cache is per plugin. You usually define a single “derive” rule (for a representative shape) and
point all related shapes at `"use_cached_ratio"`.

Example block:

```jsonc
"shell-*": {
  "x_scale": "derive_ratio_from_height"
},
"toaster-*": {
  "x_scale": "use_cached_ratio"
}
```

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
