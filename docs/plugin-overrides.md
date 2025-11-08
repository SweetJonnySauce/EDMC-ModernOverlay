# Plugin Override Developer Guide

Modern Overlay keeps plugin-specific quirks in `overlay_groupings.json` at the repository root. The override engine runs exclusively inside the overlay client (`overlay-client/plugin_overrides.py`) so third-party plugins do not need to ship different payload formats. Today the engine focuses on two things:

- Identifying payloads even when the plugin name is missing.
- Declaring grouping/anchor metadata so Fill mode can keep related payloads rigid.

The historical “transform this payload in-place” directives were removed. Pattern entries still parse but `_apply_override()` intentionally does not mutate payload geometry. Use grouping metadata to control Fill behaviour and keep notes in the JSON to explain why a plugin needs special handling.

## File layout

The JSON root is a dictionary keyed by display name:

```jsonc
{
  "LandingPad": {
    "notes": ["Keep pad geometry rigid in Fill mode."],
    "__match__": {
      "id_prefixes": ["shell-", "pad-", "line-"]
    },
    "grouping": {
      "mode": "plugin"
    },
    "shell-*": {
      "anchor": "center"
    }
  }
}
```

Key blocks:

- `notes` (optional) – for humans only; Modern Overlay ignores the contents.
- `__match__` (optional) – hints used when the payload does not state its plugin.
- `grouping` (optional but strongly recommended) – controls how Fill mode buckets payloads.
- Everything else is a glob pattern (`fnmatchcase`). The engine currently keeps these entries for forward compatibility but does not read their contents.

## Matching plugins

`PluginOverrideManager` tries multiple locations in order: `payload["plugin"]`, `payload["meta"]["plugin"]`, then `payload["raw"]["plugin"]`. When those are missing it:

1. Canonicalises the payload ID (`id.casefold()`).
2. Looks for an override whose `__match__.id_prefixes` contains that prefix.

Prefix comparisons are case-insensitive, so normalise every prefix to the form you expect to receive from EDMC/your plugin.

## Grouping configuration

Grouping metadata is the only part of the JSON that affects runtime behaviour today.

```jsonc
"SomePlugin": {
  "grouping": {
    "mode": "id_prefix",
    "groups": {
      "metrics": {
        "id_prefixes": ["sp.metric.", "sp.sparkline."],
        "anchor": "center"
      }
    },
    "prefixes": {
      "alerts": {
        "prefix": "sp.alert.",
        "anchor": "se"
      }
    }
  }
}
```

- `"mode": "plugin"` keeps every payload in one group. Use this for single-overlay UIs like LandingPad that must scale as a unit.
- `"mode": "id_prefix"` lets you split a plugin into named buckets. Two helper syntaxes are available:
  - `groups`: declare rich entries with an explicit label and `id_prefixes` array. Useful when multiple prefixes should share the same transform/anchor.
  - `prefixes`: shorthand for simple `label → prefix` mappings.
- `anchor` picks the point that must remain stationary when Fill mode nudges a group back on-screen. Supported values: `nw`, `ne`, `sw`, `se`, `center`. Legacy `preserve_fill_aspect.anchor` blocks are still parsed and converted automatically.

If a payload does not match any configured prefix the renderer falls back to “per-item” grouping, so it will still render but it will not benefit from rigid Fill translations.

## Testing overrides

1. **Validate JSON** – `python3 -m compileall overlay-client overlay_plugin` is a quick syntax sanity-check before launching the overlay.
2. **Replay real payloads** – the CLI helpers in `tests/` talk to the running overlay client:
   - `python3 tests/send_overlay_from_log.py --log tests/landingpad.log` replays a recorded session.
   - `python3 tests/send_overlay_shape.py` and `python3 tests/send_overlay_text.py` craft quick vector/text payloads.
3. **Watch the debug overlay** – enable `Show debug overlay` and confirm `scale.mode = fill`, then toggle `group_bounds_outline` to ensure all relevant payloads share the same dashed rectangle.

The CLI scripts warn if `debug.json` does not have payload mirroring enabled. Flip `payload_logging.overlay_payload_log_enabled` to `true` when you need to capture the transformed payloads in `logs/EDMC-ModernOverlay/overlay-payloads.log`.

## Tracing specific payloads

`debug.json` lets you focus on particular payload IDs during override work:

```json
{
  "trace_enabled": true,
  "plugin": "LandingPad",
  "payload_ids": [
    "shell-",
    "pad-"
  ]
}
```

- `trace_enabled` turns on tracing.
- `plugin` narrows logs to a single plugin (optional).
- `payload_ids` accepts a list of prefixes; the engine matches `str.startswith`.

With tracing enabled the overlay client logs `trace plugin=… stage=…` entries for each paint stage (raw points, adjusted rects, etc.), making it easier to confirm that grouping metadata is being honoured.

## Extending the override engine

If you reintroduce payload mutation in the future:

1. Extend the JSON schema (for example, add a `"font"` block to a pattern).
2. Implement the behaviour inside `PluginOverrideManager._apply_override()`.
3. Add targeted tests under `overlay-client/tests` and update this guide accordingly.

Until then, keep overrides declarative and prefer adding more precise grouping metadata rather than baking per-payload offsets.
