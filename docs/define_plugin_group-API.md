`overlay_groupings.json` is the source for Modern Overlay’s plugin-specific behaviour as defined by Plugin Authors. These values can be overridden by CMDRs using the Overlay Controller (stored in `overlay_groupings.user.json`). It powers six things:

1. **Plugin detection** – payloads without a `plugin` field are mapped to the correct owner via `matchingPrefixes`.
2. **Grouping** – related payloads stay rigid when they share a named `idPrefixGroup`.
3. **Anchoring** – each group can declare the anchor point Modern Overlay applies transformatios to.
4. **Justification** - Payloads within a group can now be centered or right justified (does not work for vector images).
5. **Backgrounds** – groups can define a background fill plus an optional border color and fill expansion.
6. **Controller target boxes** – group defaults can choose whether the controller box shows the last visible or max transformed bounds.

This document explains the current schema, the helper tooling, and the workflows we now support.

## Schema overview

The JSON root is an object keyed by the display name you want shown in the overlay UI. Each entry follows this schema (draft 2020‑12):

```jsonc
{
  "Example Plugin": {
    "matchingPrefixes": ["example-"],
    "idPrefixGroups": {
      "alerts": {
        "idPrefixes": ["example-alert-"],
        "idPrefixGroupAnchor": "ne",
        "controllerPreviewBoxMode": "last",
        "backgroundColor": "#cc1a1a1a",
        "backgroundBorderColor": "red",
        "backgroundBorderWidth": 2
      }
    }
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `matchingPrefixes` | array of non-empty strings | Optional. Used for plugin inference. Whenever an `idPrefixes` array is provided, missing entries are appended automatically (add-only). Entries are lowercased and deduplicated. In general, the `idPrefixes` provided should be top level and broadly scoped to capture as many of the payloads. Think `bioscan-` more than `bioscan-details-`. |
| `idPrefixGroups` | object | Optional, but any entry here must contain at least one group. Each property name is the label shown in tooling (e.g., “Bioscan Details”). |
| `idPrefixGroups.<name>.idPrefixes` | array of non-empty strings **or** `{ "value": "...", "matchMode": "startswith \| exact" }` objects | Required whenever a group is created. Each entry defaults to `startswith` matching; set `matchMode` to `exact` when the payload ID must match in full (useful when another prefix shares the same leading characters). Prefixes are lowercased, deduplicated, and unique per plugin group—if you reassign a prefix, it is removed from all other groups automatically. In general, the `idPrefixes` provided should be lower level and more narrow scoped (but still a prefix). Think `bgstally-msg-info-` more than `bgstally-msg-info-0`.|
| `idPrefixGroups.<name>.idPrefixGroupAnchor` | enum | Optional. One of `nw`, `ne`, `sw`, `se`, `center`, `top`, `bottom`, `left`, or `right`. Defaults to `nw` when omitted. `top`/`bottom` keep the midpoint of the vertical edges anchored, while `left`/`right` do the same for the horizontal edges—useful when plugins want edges to stay aligned against the overlay boundary. |
| `idPrefixGroups.<name>.offsetX` / `offsetY` | number | Optional. Translates the whole group in the legacy 1280 × 960 canvas before Fill-mode scaling applies. Positive values move right/down; negative values move left/up. |
| `idPrefixGroups.<name>.payloadJustification` | enum | Optional. One of `left` (default), `center`, or `right`. Applies only to idPrefix groups. After anchor adjustments (but before overflow nudging) Modern Overlay shifts narrower payloads so that their right edge or midpoint lines up with the widest payload in the group. The widest entry defines the alignment width and stays put. **Caution** Using justification with vect type payloads isn't supported and probably never will be. |
| `idPrefixGroups.<name>.markerLabelPosition` | enum | Optional. One of `below` (default), `above`, or `centered`. Controls where vector marker labels are placed relative to the marker: `below` anchors the top of the text box at Y+7 (legacy default), `above` anchors the bottom of the text box at Y-7, and `centered` anchors the middle of the text box at Y+0. |
| `idPrefixGroups.<name>.controllerPreviewBoxMode` | enum | Optional. One of `last` (default) or `max`. Controls which cached bounds the overlay controller uses when drawing controller target boxes: `last` uses the last visible transformed bounds, `max` uses the maximum transformed bounds recorded for the group. |
| `idPrefixGroups.<name>.backgroundColor` | hex string, named color, or null | Optional. Default background fill for this group. Accepts named colors or `#RRGGBB`/`#AARRGGBB` (alpha optional, case-insensitive). `null` forces a transparent override. |
| `idPrefixGroups.<name>.backgroundBorderColor` | hex string, named color, or null | Optional. Border color for the group background. Uses the same formats as `backgroundColor`. `null` clears the border. |
| `idPrefixGroups.<name>.backgroundBorderWidth` | integer | Optional. Fill expansion in pixels (0–10). The background fill expands by this width on every side; the border is a fixed 1px stroke drawn outside the expanded fill. |

Additional metadata (`notes`, legacy `grouping.*`, etc.) is ignored by the current engine but preserved so you can document intent for reviewers.

Offsets run right after the overlay client collects a group’s payloads, so they are independent of the current window size. Scaling, proportional Fill translations, and overflow nudging all build on top of the translated group, keeping the shift consistent everywhere.

Payload justification is resolved immediately after anchor translations. The overlay measures every payload in an idPrefix group, finds the widest entry, and shifts the remaining payloads to align against that width. This keeps multi-line payloads visually balanced without affecting anchor placement or the later nudging pass.

## Layered configuration (user overrides)

- Defaults ship in `overlay_groupings.json`. User overrides live beside it in `overlay_groupings.user.json` and are never overwritten on upgrade.
- Merge rules: shipped defaults are the base; user values replace shipped values at the same plugin or `idPrefixGroups.<name>` when present, while any missing keys fall back to shipped defaults; user-only plugins/groups are allowed. You can hide a shipped entry by setting `disabled: true` on the plugin entry (removes the whole plugin from the merged view) or on a specific `idPrefixGroups.<name>` entry (removes just that group).
- Writes: the controller writes **only** to the user file (diffed against shipped defaults). The public API (`define_plugin_group`) still targets the shipped file so plugin authors can register defaults.
- Paths: `MODERN_OVERLAY_USER_GROUPINGS_PATH` can point the user file elsewhere (tests/tools). If omitted, the plugin root path above is used. CLI tools still default to the shipped file for writes unless you override via `--groupings-path`.
- Reload/error handling: the loader watches both shipped/user files; missing user file means “no overrides.” Malformed user JSON is warned and ignored while keeping the last-good merged view.
- Reset: remove/rename `overlay_groupings.user.json` to fall back to shipped defaults. User-only entries disappear; shipped-only entries return. 

### Reference schema

The repository ships with `schemas/overlay_groupings.schema.json` (Draft 2020‑12). `overlay_groupings.json` already points to it via `$schema`, so editors such as VS Code will fetch it automatically. For reference, the schema contents are below:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EDMC Modern Overlay Payload Group Definition",
  "type": "object",
  "additionalProperties": { "$ref": "#/$defs/pluginGroup" },
  "$defs": {
    "pluginGroup": {
      "type": "object",
      "properties": {
        "matchingPrefixes": {
          "type": "array",
          "minItems": 1,
          "items": { "type": "string", "minLength": 1 }
        },
        "idPrefixGroups": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": { "$ref": "#/$defs/idPrefixGroup" }
        }
      },
      "anyOf": [
        { "required": ["matchingPrefixes"] },
        { "required": ["idPrefixGroups"] }
      ],
      "additionalProperties": false
    },
    "idPrefixGroup": {
      "type": "object",
      "properties": {
        "idPrefixes": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/idPrefixValue" }
        },
        "idPrefixGroupAnchor": {
          "type": "string",
          "enum": ["nw", "ne", "sw", "se", "center", "top", "bottom", "left", "right"]
        },
        "offsetX": {
          "type": "number"
        },
        "offsetY": {
          "type": "number"
        },
        "payloadJustification": {
          "type": "string",
          "enum": ["left", "center", "right"],
          "default": "left"
        },
        "markerLabelPosition": {
          "type": "string",
          "enum": ["below", "above", "centered"],
          "default": "below",
          "description": "Marker label placement relative to the marker."
        },
        "controllerPreviewBoxMode": {
          "type": "string",
          "enum": ["last", "max"],
          "default": "last",
          "description": "Controls controller target box selection: last visible or max transformed bounds."
        },
        "backgroundColor": {
          "oneOf": [
            {
              "type": "string",
              "pattern": "^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$|^[A-Za-z][A-Za-z0-9_]*$"
            },
            { "type": "null" }
          ],
          "description": "Hex color in #RRGGBB/#AARRGGBB or a named color. Null clears to transparent."
        },
        "backgroundBorderColor": {
          "oneOf": [
            {
              "type": "string",
              "pattern": "^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$|^[A-Za-z][A-Za-z0-9_]*$"
            },
            { "type": "null" }
          ],
          "description": "Border color in #RRGGBB/#AARRGGBB or named form. Null clears the border."
        },
        "backgroundBorderWidth": {
          "type": "integer",
          "minimum": 0,
          "maximum": 10,
          "description": "Fill expansion in pixels; extends background equally on all sides."
        }
      },
      "required": ["idPrefixes"],
      "additionalProperties": false
    },
    "idPrefixValue": {
      "oneOf": [
        { "type": "string", "minLength": 1 },
        {
          "type": "object",
          "properties": {
            "value": { "type": "string", "minLength": 1 },
            "matchMode": {
              "type": "string",
              "enum": ["startswith", "exact"],
              "default": "startswith"
            }
          },
          "required": ["value"],
          "additionalProperties": false
        }
      ]
    }
  }
}
```

## Authoring options

### Manual edits

While it is advised to use the `define_plugin_group` API, you can edit `overlay_groupings.json` directly; the schema above is self-contained and stored alongside the repository. Keep the file in version control, run `python3 -m json.tool overlay_groupings.json` (or a formatter of your choice) for quick validation, and cover behavioural changes with tests/logs when possible.

### Public API (`define_plugin_group`)

Third-party plugins should call the bundled helper to create or replace their entries at runtime:

```python
from overlay_plugin.overlay_api import define_plugin_group, PluginGroupingError

try:
    define_plugin_group(
        plugin_group="MyPlugin",
        matching_prefixes=["myplugin-"],
        id_prefix_group="alerts",
        id_prefixes=["myplugin-alert-"],
        id_prefix_group_anchor="ne",
        marker_label_position="below",
        controller_preview_box_mode="last",
        background_color="#1A1A1ACC",
        background_border_color="red",
        background_border_width=2,
    )
except PluginGroupingError as exc:
    # Modern Overlay is offline or the payload was invalid
    print(f"Could not register grouping: {exc}")
```

The helper enforces the schema, lowercases prefixes, ensures per-plugin uniqueness, and writes the JSON back to disk so the overlay client reloads it instantly. Use `controller_preview_box_mode` to choose `last` or `max` when you need to control which bounds the controller target boxes use (stored as `controllerPreviewBoxMode` in JSON).

## Example 1: Center a text string at the top center of the screen

<img width="1919" height="112" alt="image" src="https://github.com/user-attachments/assets/e57a15cf-2026-4cc6-b2a8-6ed5d57fc936" />

Call the grouping helper **once at plugin startup** to keep your group anchored to the top edge while horizontally aligning every payload around its midpoint:

```python
from overlay_plugin.overlay_api import define_plugin_group, PluginGroupingError

def plugin_startup():
    try:
        define_plugin_group(
            plugin_group="Centered Banner",
            id_prefix_group="status-line",
            id_prefixes=["centered-banner-"],
            id_prefix_group_anchor="top",
            payload_justification="center",
        )
    except PluginGroupingError as exc:
        print(f"Could not register grouping: {exc}")
```

Once registration succeeds (you do not need to call it again unless you change the prefixes or anchor), any payload whose ID starts with `centered-banner-` will remain pinned to the top-center anchor.

To draw a string in that group, send a legacy message to the `1280×960` coordinate space that Modern Overlay expects and let the Fill transforms scale it for the current window. The midpoint of that width is `x=640`, so `640, 0` produces a top-centered payload on every monitor:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message(
    "centered-banner-welcome",
    "Safe travels, CMDR o7",
    "#ffd27f",
    640,  # 1280px canvas midpoint for centered placements
    0,    # 0 keeps the anchor flush with the top edge
    ttl=6,
    size="large",
)
```

Legacy calls always speak the 1280×960 virtual canvas and Modern Overlay scales from there, so centering a payload is as simple as targeting `x=640`—even on ultrawide monitors.

## Example 2: Right-justify a banner against the top-right edge

<img width="358" height="321" alt="image" src="https://github.com/user-attachments/assets/62d3e903-7396-4b07-be38-6a2a58954d3f" />
(screenshot not the same as the example)

Register the grouping **once at startup** so Modern Overlay anchors the block to the north-east corner while right-justifying the payload text:

```python
from overlay_plugin.overlay_api import define_plugin_group, PluginGroupingError

def plugin_startup():
    try:
        define_plugin_group(
            plugin_group="Right Banner",
            id_prefix_group="alerts",
            id_prefixes=["right-banner-"],
            id_prefix_group_anchor="ne",
            payload_justification="right",
        )
    except PluginGroupingError as exc:
        print(f"Could not register grouping: {exc}")
```

With that single registration in place, any payload whose ID begins with `right-banner-` is pinned to the top-right corner and its text hugs the right edge of the widest payload in the group.

To render a message there, send legacy coordinates that reference the canonical 1280×960 canvas. The rightmost column is `x=1280`, so targeting that coordinate keeps the banner flush with the edge no matter how large the real overlay window becomes:

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message(
    "right-banner-alert",
    "Reactor at 95%",
    "#ff9c6b",
    1280,  # far right of the legacy 1280px canvas
    40,    # drop the banner slightly below the corner
    ttl=6,
    size="normal",
)
```

Because legacy clients always address the 1280×960 virtual surface, you only need to aim at `x=1280` once—Modern Overlay handles the scaling and offsets for every other resolution.

## Utilities

### Payload inspector (`utils/payload_inspector.py`)

Run `python3 utils/payload_inspector.py` to tail `overlay-payloads.log` and see live payload IDs alongside the resolved plugin/group labels from the current overrides. It mirrors runtime log discovery (including rotations), lets you pick a log file, and is a quick way to verify that a prefix maps to the group you expect.

### Interactive manager (`utils/plugin_group_manager.py`)

The full Plugin Group Manager remains available for exploratory work:

- Watches live payload logs, suggests prefixes/groups, and lets you edit everything through dialogs.
- The ID-prefix editor now treats each entry as its own row. Pick a row to toggle the match mode (starts-with or exact) via a dropdown, or add/remove entries at the bottom. The “Add to ID Prefix group” dialog also offers a match-mode selector and automatically inserts the full payload ID when you switch to `exact`.
- Automatically reloads if it notices that `overlay_groupings.json` changed on disk (including API- or CLI-driven updates) and purges payloads that now match a group.
- Great for vetting Fill-mode anchors with real payloads before copying the values into commits.

## Runtime behaviour

- **Prefix casing/uniqueness:** every prefix is stored lowercased. When you assign an `idPrefixes` list to a group, the API removes those prefixes from every other group under the same plugin to avoid ambiguous matches.
- **Matching inference:** the overlay client uses `matchingPrefixes` first, falling back to `idPrefixes` inside each group and legacy hints. Supplying at least one matching prefix keeps plugin detection deterministic.
- **Anchor enforcement:** the renderer validates anchors against the nine allowed tokens. Invalid entries fall back to `nw` so the overlay never crashes; fix the source JSON when this happens.
- **Hot reload:** both the overlay client and the Plugin Group Manager poll file mtimes so changes take effect without restarts. Treat the JSON like a shared resource—always make edits atomically (write to a temp file, then replace) or use the provided helpers.

## Testing & validation

| Scope | Command | Purpose |
|-------|---------|---------|
| API contract | `pytest tests/test_overlay_api.py` | Validates schema enforcement, prefix lowercasing, per-plugin uniqueness, and error cases for the public API. |
| Override parser | `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_override_grouping.py` | Ensures `overlay_groupings.json` is parsed into runtime grouping metadata correctly (matching, anchors, grouping keys). |
| Manual sanity | `python3 utils/plugin_group_manager.py` | Exercise the UI, verify anchors/bounds, and ensure new groups behave correctly with live payloads. |

Before shipping new prefixes, capture representative payloads (in EDMC DEBUG mode from the EDMC Logs directory `cat ./EDMCModernOverlay/overlay-payloads.log | grep 'mypluginspec' > mypluginspec.log` and test with `tests/send_overlay_from_log.py`) to verify that Fill mode keeps the new groups rigid. 
