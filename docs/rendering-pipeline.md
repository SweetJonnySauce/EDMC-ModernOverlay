# Rendering & Tracing Pipeline

This document explains how a payload travels from EDMC into the Modern Overlay client, which components participate, and which tracing stages you can expect in the logs.

## 1. Configuration & gating

1. `debug.json` is read by both the EDMC plugin (`load.py`) and the overlay client (`overlay-client/debug_config.py`).  
2. Dev builds (or `MODERN_OVERLAY_DEV_MODE=1`) enable the debug configuration.  
3. `tracing.enabled` gates all subsequent trace output; `tracing.payload_ids` is interpreted as `str.startswith` prefixes. When the list is empty, every payload can emit traces.  
4. Payload logging and tracing can be toggled independently.  
5. `capture_client_stderrout` mirrors the overlay client's stdout/stderr back into EDMC’s log (still gated by EDMC’s DEBUG log level).

## 2. EDMC plugin path

1. Journal/external payloads flow through `_PluginRuntime._publish_payload()` inside `load.py`.  
2. Legacy TCP payloads are normalised via `normalise_legacy_payload()` before they are published.  
3. Overrides specified in `overlay_groupings.json` and the plugin override engine are applied.  
4. The plugin broadcasts payloads to the overlay client via the watchdog-managed socket.

## 3. Overlay client intake

1. `OverlayDataClient` reads payloads off the socket and forwards them to `OverlayWindow`.  
2. Modern-overlay payloads update the live state; legacy-formatted payloads (most third-party overlays) are sent to `_handle_legacy()`.  
3. `_handle_legacy()` extracts `plugin`/`id`, applies overrides, emits `post_override` traces when tracing is enabled, and calls `process_legacy_payload()` with a trace callback.

## 4. Legacy processing & storage

1. `process_legacy_payload()` (in `overlay-client/legacy_processor.py`) normalises each payload type:
   - `message` → text payload with color/position/size metadata.
   - `shape:rect` → rectangle payload with fill/border data.
   - `shape:vect` → vector payload with ordered points, optional markers/text.
   - Other shapes/raw payloads are stored for future handling.
2. The helper emits trace events such as:
   - `legacy_processor:vector_single_point_extended`
   - `legacy_processor:vector_normalised`
3. The processed payload is written into `LegacyItemStore`. Its setter fires `legacy_store:set` traces and notifies the window that a repaint is needed.

## 5. Grouping & viewport preparation

1. `OverlayWindow.paintEvent()` drains `LegacyItemStore` and groups payloads using `PluginOverrideManager`.  
2. For Fill mode, `FillGroupingHelper.prepare()` builds per-group bounds and anchor metadata (see `docs/fill-mode-baseline.md`).  
3. Each payload is paired with a `LegacyMapper` / `FillViewport` that captures the window size, scale factor, offsets, and any proportional translations required to keep grouped payloads rigid.  
4. `_should_trace_payload()` re-checks the tracing filters for each item before any logging happens.

## 6. Paint command construction

For every legacy item, the window builds a paint command. Each builder emits input/output trace stages when tracing is enabled.

### Messages (`_build_message_command`)

1. Compute scaled font size, remap the logical `(x, y)` via `remap_point()`, and apply inverse group scale/proportional translation if Fill mode is active.  
2. Emit:
   - `paint:message_input` (raw coordinates, scale, offsets, font size)
   - `paint:message_output` (adjusted overlay coords, pixel baseline, text width)  
3. Attach a `trace_fn` that later logs `render_message:draw`.

### Rectangles (`_build_rect_command`)

1. Build pen/brush from payload colors and compute remapped rectangle corners via `remap_rect_points()`.  
2. Emit:
   - `paint:rect_input`
   - `paint:rect_output` (both overlay-space and pixel-space bounds)  
3. Resulting `_RectPaintCommand` does not emit additional traces during painting.

### Vectors (`_build_vector_command`)

1. Log `paint:scale_factors` (scale, offsets, Fill mode) and `paint:raw_points`.  
2. Remap each point through `remap_vector_points()`, apply inverse group scale and proportional translation.  
3. Build `_VectorPaintCommand` with a `trace_fn` that `render_vector()` uses to emit `render_vector:scaled_points` (the pixel-space line segments).

## 7. Final paint execution

1. `OverlayWindow` iterates paint commands per group.  
2. `_MessagePaintCommand.paint()` sets the font, draws the text, then logs `render_message:draw`.  
3. `_RectPaintCommand.paint()` draws rectangles with the configured pen/brush.  
4. `_VectorPaintCommand.paint()` calls `render_vector()`, which draws each segment/marker and emits `render_vector:scaled_points`.  
5. Each paint command can register a cycle anchor so the “cycle payload IDs” developer feature knows where to highlight focus points.

## 8. Trace stage quick reference

| Stage prefix                | Source                                                                    | Meaning |
| --------------------------- | ------------------------------------------------------------------------- | ------- |
| `post_override`             | `_handle_legacy()`                                                        | Payload after overrides, before storage |
| `legacy_processor:*`       | `legacy_processor.process_legacy_payload()`                                | Normalisation details (e.g. vector manipulation) |
| `legacy_store:set`         | `LegacyItemStore.set()`                                                    | Payload persisted in legacy store |
| `paint:message_*`          | `_build_message_command()`                                                 | Text payload remap info |
| `paint:rect_*`             | `_build_rect_command()`                                                    | Rect payload remap info |
| `paint:scale_factors`      | `_build_vector_command()`                                                  | Vector scale/offset context |
| `paint:raw_points`         | `_build_vector_command()`                                                  | Original vector coordinates |
| `paint:vector_*`           | Future vector-specific stages (currently covered by raw/scale logs)        |
| `render_message:draw`      | `_MessagePaintCommand.paint()`                                             | Final QPainter text draw |
| `render_vector:scaled_points` | `vector_renderer.render_vector()`                                       | Pixel-space line segments prior to drawing |

Use these stages to verify that every phase—from ingestion through final paint—behaves as expected for the payload IDs you are tracing.
