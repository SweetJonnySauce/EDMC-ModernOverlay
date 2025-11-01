# Developer Notes

## Payload ID Finder Overlay

Modern Overlay includes a developer-facing “payload ID finder” that helps trace which legacy payload is currently targeted. When you enable **Cycle through Payload IDs** in the preferences, the overlay shows a floating badge containing:

- The active `payload_id`
- The originating plugin name (if known)
- The computed center coordinates of the payload on screen

This is particularly useful when capturing coordinates or validating plugin overrides.

> **Important:** If “Compensate for Elite Dangerous title bar” is enabled, the center coordinates displayed in the payload ID finder will be inaccurate. Title bar compensation translates the overlay to align with the game window, but the badge still uses the original, uncompensated coordinates. Disable the compensation setting when you need precise center values from the finder.

### Tips

- Toggle payload cycling with the controls in the preferences.
- The connector line from the badge points toward the payload’s anchor point, helping locate overlapping elements quickly.
- Plugin names and coordinates rely on the metadata provided by each payload; if a plugin does not populate `plugin` fields, the finder falls back to `unknown`.
- Message overrides (e.g. `bgstally-msg-*`) are now tracked, so scale/offset adjustments applied via overrides show up in the badge.
