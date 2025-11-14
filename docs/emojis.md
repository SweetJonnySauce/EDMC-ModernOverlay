# Emoji Support

Modern Overlay understands Unicode payloads end‑to‑end, so plugins can render emoji
in overlay text without extra escape sequences. This document outlines how the feature
is wired up and how to exercise it with both the Modern API and the legacy
`edmcoverlay` shim.

## Bundled Fonts

- `overlay-client/fonts/NotoColorEmoji.ttf` and `NotoColorEmoji-OFL.txt` ship with the repo
  under the SIL Open Font License. The client registers the font on startup and uses it
  as the first emoji fallback, so 📝 and other glyphs render even on systems that don’t
  have an emoji font installed globally.
- `overlay-client/fonts/emoji_fallbacks.txt` lists additional fallback fonts. Each entry
  can be either a font file name living in `overlay-client/fonts/` or an installed family
  name such as `Segoe UI Emoji`. The overlay tries each entry in order and appends any
  successful registrations to the fallback chain. To add another font, drop the `.ttf`
  into the directory, list it in `emoji_fallbacks.txt`, and restart the client.
- Regular HUD fonts are still controlled via `overlay-client/fonts/preferred_fonts.txt`.
  The first font that loads becomes the primary face; emoji fallbacks kick in only
  when the primary font lacks the requested glyph.

## Sending Emoji With the Modern API

```python
from overlay_plugin import overlay_api

overlay_api.send_overlay_message(
    {
        "event": "OverlayMessage",
        "text": "Mission logged \N{memo}",  # becomes 📝 after Python parses the literal
        "x": 60,
        "y": 120,
        "color": "#80d0ff",
        "size": "normal",
        "ttl": 8,
    }
)
```

- `overlay_plugin/overlay_api.py` serializes payloads with `ensure_ascii=False`, so the UTF‑8
  emoji stays intact over the socket.
- Python string literals resolve `\N{memo}` to the actual character before the call. If a plugin
  needs to convert shorthand at runtime, call `unicodedata.lookup("memo")` or similar before
  sending the payload. The overlay does **not** expand `\N{...}` at runtime; it expects the
  real code point.
- Emoji work in any text field (`OverlayMessage`, vector labels, debug overlays, etc.) because
  every `QFont` instance now receives the fallback families automatically.

## Sending Emoji Via Legacy `edmcoverlay`

```python
from EDMCOverlay import edmcoverlay

overlay = edmcoverlay.Overlay()
overlay.send_message(
    "memo-demo",
    "Mission logged \N{memo}",  # or "Mission logged 📝"
    "#80d0ff",
    60,
    120,
    ttl=8,
    size="large",
)
```

- Modern Overlay bundles the `EDMCOverlay.edmcoverlay` shim so plugins that still rely on
  the original API can keep working. The shim publishes to the same JSON socket the PyQt
  client reads, so emoji reach the renderer identically.
- Coordinates and sizes remain in the classic 1280 × 960 space. Modern Overlay handles scaling
  and grouping internally, so the only change needed for emoji support is to send strings
  with Unicode characters already resolved.

## Troubleshooting

- **Squares instead of emoji:** confirm `overlay-client/fonts/NotoColorEmoji.ttf` exists and
  isn’t corrupted. If you replaced `emoji_fallbacks.txt`, make sure at least one entry resolves
  to a font on the current machine. The client logs its discovered fallback list at startup.
- **Literal `\N{memo}` shows up on screen:** this means the plugin never converted the escape
  sequence. Ensure you’re using a Python string literal with `r` omitted (plain `"..."`) or
  call `unicodedata.lookup` to insert the character before sending the payload.
- **Missing glyph in legacy mode:** same root cause; the legacy TCP path is Unicode-aware, but
  only if the payload already contains the emoji character.
