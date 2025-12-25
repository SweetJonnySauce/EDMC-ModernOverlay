# Release Notes

## 0.7.6
- Features
  - Added functionality to set plugin group background color via define_plugin_group for Plugin Authors or via Overlay Controller for CMDRs.
  - Added Font Step to preference pane and a Font preview button. This allows the CMDR to define the interval increase/decrease between the canonical font sizes "Small", "Normal", "Large", and "Huge". Addresses [#41](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/41)
  - Added a global payload opacity setting for CMDRs on the plugin preference pane. Reducing opacity makes all payloads semi-transparent on the game screen. Payloads that are already semi-transparent have their settings further reduced linearly with this setting. Adrsses [#33](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/33)
  - Moved a Dev only setting to "Keep overlay visible" to be always available on the preferences pane. Helpful when trying out other settings. (Fixes [#40](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/40))
- Plugin Developer Features
  - Added `markerLabelPosition` (`below`/`above`/`centered`) to `define_plugin_group` schema/API with default `below`.
  - Added `\n` and `\r\n` functionality to text payloads to support multiline text.
  - Provide a new option in `define_plugin_group` called `controller_preview_box_mode` (enum: `last` (default),`max`). This is used to determine how to size the orange border that shows up when the overlay controller is open. Some plugins send clear messages or slowly decay their on-screen HUDs so the border will shrink. By setting this property to `last` (default), it will use the last visible payload to determine the size of the orange border. By setting this property to `max`, it will use the largest visible payload seen to determine the size of the orange border. This now also includes a "Reset cached values" button on the pref pane to clear `overlay_group_cache.json` should it go astray.
- Bug Fixes
  - Fixes [#42](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/42) and [#43](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/43). Address nuanced backwards compatibility issues for vector images and marker labels that mainly affected EDR Navigation.
  - Fixed [#21](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/21). EDR Help and Docking payloads were not clearing when EDR sent the clear message. Modified the shim layer to allow positional arguments (see [#13](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/13))
  - Fixed [#46](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/46). Fedora install now checks to see if the `flatpak-spawn` package is installed. (Fedora packages it separately.)
  - Tweaked some preference settings for a more consistent UI/UX.
  - Fixed [#48](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/48). A "pinned" group in the overlay controller is when it's nudged up next to the edge. The arrow in the controller stays orange when pinned. This fix was to address a problem where pinning did not reset when the plugin group changed in the controller.
  - Fixed [#27](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/27). When a plugin sends a clear payload it's typically just ttl=0 , text="". This gets cached and the hud target in controller mode is misrepresented. Add capability to show the last visible (or max) payload size while in controller mode.
  - Cleaned up some inconsistencies with pref pane, internal messages being sent, and plugged `define_plugin_group` api into `utils/plugin_group_manager.py` for add/update operations.
  - Cleaned up a noisy log message (client connected)
  - Addresses [#56](https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/56) by creating a vt_transparency.html asset you can download and view.

  
## 0.7.5
- Features & Improvements:
  - EDMC 6.0.0 compatibility!
  - CMDR payload placements are now stored in `overlay_groupings.user.json` and are perserved across upgrades.
  - Diagnostics overhaul: EDMC’s DEBUG log level now drives every Modern Overlay logger, auto-creates `debug.json`, and exposes payload logging/stdout capture controls directly in the preferences panel while dev-only helpers live in the new `dev_settings.json`.
  - Overlay debug metrics now surface environment override inputs (applied, skipped, and values) to make override issues visible from the HUD.
  - Controller UI cleanup: preview now renders a single authoritative target box (no more dual “actual vs. target”), the absolute widget always mirrors controller coordinates without warning colors, and group pinning/anchor edits stay responsive.
- Bug Fixes
  - Fix #26. Give focus back to game after closing the controller on Windows
  - Fix #29 where fractional scaling caused overlay to span two monitors. See [Physical Clamping](https://github.com/SweetJonnySauce/EDMCModernOverlay/wiki/Physical_Clamping)
  - Center justification now uses origin-aware baselines (ignoring non-justified frames) to keep centered text inside its containing box; right justification is unchanged.
- Installer updates
  - A brand new EXE installer is now shipped with the release using Inno Setup.
  - Linux installer is compositor-aware: detects your compositor, can apply manifest-driven overrides (Qt scaling, force Xwayland when requested) via `--compositor auto|<id>|none`, and records accepted overrides in `overlay_client/env_overrides.json` without clobbering existing env vars.
  - Installers now ship a per-file `checksums.txt` manifest to validate the integrity of them before installation/upgrade.
  - Linux install: added Arch/pacman support alongside existing installers.
- Maintenance:
  - Overlay Controller⇄client targeting rewrite to address "jumping" of on-screen assets.
  - Cache + fallback hardening: while the controller is active we shorten cache flush debounces, immediately rewrite transformed bounds from the rendered geometry, and keep HUD fallback aligned even if the HUD momentarily drops payload frames.
  - Controller performance & usability: merged-group loader now feeds the controller UI, writes are isolated to the user config file, and reloads poll both shipped/user files with last-good fallback to keep editing responsive.
  - Made min-version of Python required 3.10 for Plugin, Client, and Controller.
  - Lifecycle hardening: centralized thread/timer management via a new lifecycle helper
  - Runtime delegation: moved broadcaster/watchdog orchestration and controller launch/termination into dedicated helpers, added hook-level smoke tests
- Known Issues
  - VirusTotal flags the EXE installer due to it being unsigned and/or because it builds its own Python environment. Build logs and scan details are provided on the link below.

## 0.7.4-dev
- Controller startup no longer crashes when Tk rejects a binding; unsupported or empty sequences are skipped with a warning instead.
- Default keyboard bindings drop the X11-only `<ISO_Left_Tab>` entry (Shift+Tab remains) to stay cross-platform.

## 0.7.2.4.1
- Fixed public API: `overlay_plugin.define_plugin_group` now accepts and persists `payload_justification`, matching the documented schema and UI tools. Third-party plugins can set justification without runtime errors.
