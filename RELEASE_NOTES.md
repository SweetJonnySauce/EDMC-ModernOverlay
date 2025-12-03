# Release Notes

## 0.7.4-dev
- Controller startup no longer crashes when Tk rejects a binding; unsupported or empty sequences are skipped with a warning instead.
- Default keyboard bindings drop the X11-only `<ISO_Left_Tab>` entry (Shift+Tab remains) to stay cross-platform.

## 0.7.2.4.1
- Fixed public API: `overlay_plugin.define_plugin_group` now accepts and persists `payload_justification`, matching the documented schema and UI tools. Third-party plugins can set justification without runtime errors.
