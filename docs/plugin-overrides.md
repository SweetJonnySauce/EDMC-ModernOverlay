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

Pattern blocks are still evaluated in declaration order, but Modern Overlay no longer supports user-specified `transform` / scale / offset directives. Only grouping metadata is honoured today; any historical transform fields should be removed from the JSON (they are ignored if left in place). Pattern objects can still carry future custom metadata, and grouping-related options focus on how payloads are bucketed; Fill mode now always preserves aspect across the group, so historical `preserve_fill_aspect` settings are silently ignored.
- The plugin-level `notes` array is just documentation for humans; Modern Overlay ignores it, but it keeps the rationale beside the configuration.
- You can add a `grouping` block to keep Fill-mode transforms rigid. `"mode": "plugin"` keeps every payload in one group; `"mode": "id_prefix"` lets you list the exact prefixes (see “Grouping vector payloads”).
- Each group can declare an `anchor` (`"nw"`, `"ne"`, `"sw"`, `"se"`, `"center"`), which picks the point inside the group bounds that Fill mode preserves. When omitted, the north-west corner (`"nw"`) is used.

This pattern keeps the adjustment in the adapter layer while leaving the plugin’s source intact. If a future plugin
applies a similar workaround (for example, only providing a single anchor point instead of polygons), you can set
`source_bounds` to the rectangle the plugin was targeting and reuse the same transform logic.

### Grouping vector payloads

Fill mode zooms the overlay uniformly, which means we sometimes have to translate payloads back into the window to keep them visible. By default the overlay groups payloads by plugin, but you can override that behaviour:

```jsonc
"LandingPad": {
  "__match__": { "id_prefixes": ["shell-", "line-"] },
  "grouping": {
    "mode": "plugin"
  }
}
```

```jsonc
"EDMC-MiningAnalytics": {
  "__match__": { "id_prefixes": ["edmcma.metric.", "edmcma.alert."] },
  "grouping": {
    "mode": "id_prefix",
    "prefixes": {
      "metrics": {
        "prefix": "edmcma.metric.",
        "anchor": "center"
      },
      "alerts": {
        "prefix": "edmcma.alert.",
        "anchor": "se"
      }
    }
  }
}
```

- `"plugin"` keeps every payload from the plugin in one rigid group (useful for single-widget overlays such as LandingPad).
- `"id_prefix"` splits the plugin into named groups so unrelated widgets can move independently; each entry can define an anchor.
- If a prefix isn’t listed, the renderer falls back to per-item grouping for that payload.

## Testing Your Overrides

1. Run `python3 -m compileall overlay-client` to ensure the Python modules still compile.
2. With `payload_logging.overlay_payload_log_enabled` set to `true` in `debug.json`,
   the plugin writes payload mirrors into `logs/EDMC-ModernOverlay/overlay-payloads.log`.
   Inspect that file to verify overrides are active—look for DEBUG lines mentioning “Loaded … plugin override”.
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
