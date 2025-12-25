# Debug/Logging Refactor

Modern Overlay’s diagnostics depend on two independent gates: the plugin respects EDMC’s log level, while the overlay client/controller only unlock most debug behaviour when “dev mode” is on. This split makes it hard for users to gather logs without wrestling with version suffixes or environment variables. The goal of this refactor is to let EDMC’s log level drive all logging/capture knobs and reserve dev mode for high-risk UI/geometry features.

## Requirements
- When EDMC’s log level is set to DEBUG, every Modern Overlay component must emit DEBUG messages:
  - Plugin logs (forwarded to the EDMC log via `_EDMCLogHandler`) already follow EDMC’s level; ensure the overlay client and overlay controller raise their logger levels to DEBUG as well and stop filtering debug statements (i.e., don’t demote them to INFO).
  - This behaviour should not require dev mode; the EDMC log-level gate alone must be enough to make `overlay_client.log`, `overlay_controller.log`, and the EDMC log capture the same DEBUG verbosity.
- Propagate the resolved EDMC log level to child processes (overlay client + controller) via `port.json` and/or environment variables so they can deterministically raise their logger level without guessing. The propagated level must update whenever EDMC’s config changes.
- While EDMC logging is DEBUG, auto-create `debug.json` from `DEFAULT_DEBUG_CONFIG` if it is missing so payload logging/capture/log-retention toggles immediately work. (Release builds currently skip this; extend `_ensure_default_debug_config()` to run when EDMC log level == DEBUG even if `DEV_BUILD` is false.)
- When dev mode is active but EDMC logging is not DEBUG, bypass the EDMC gate for every Modern Overlay logger (plugin, overlay client, overlay controller, payload logger, stdout capture): treat them all as DEBUG so developers get full diagnostics even if EDMC stays at INFO/WARN.
- Split the current mixed `debug.json` semantics into two files:
  - Keep `debug.json` for operator-facing troubleshooting flags (payload logging, stdout capture, log retention tweaks). Do not expose payload tracing from this file.
  - Introduce `dev_settings.json` for developer-only toggles including payload tracing, overlay/group outlines, payload vertex markers, repaint overrides, cache flush overrides, etc. When dev mode is active, ensure this file exists (writing defaults if needed) and load its contents in addition to `debug.json`. Outside dev mode, never auto-create or load this file so regular users aren’t exposed to dev-only options.
- Update documentation (troubleshooting guide, developer guide, release notes) to reflect the new logging workflow and config-split once the refactor ships, and add/extend unit tests covering the new log-level propagation, config creation, and dev-mode override logic.
- Update `release.yml` (and any build pipelines) to enforce that release artifacts are built with dev mode disabled (e.g., fail if `__version__` ends with `-dev` or `MODERN_OVERLAY_DEV_MODE` is set), ensuring packaged builds don’t accidentally ship dev behaviour.


## Dev Best Practices

- Keep changes small and behavior-scoped; prefer feature flags/dev-mode toggles for risky tweaks.
- Plan before coding: note touch points, expected unchanged behavior, and tests you’ll run.
- Avoid Qt/UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.

## Guiding traits for readable, maintainable code:
- Clarity first: simple, direct logic; avoid clever tricks; prefer small functions with clear names.
- Consistent style: stable formatting, naming conventions, and file structure; follow project style guides/linters.
- Intent made explicit: meaningful names; brief comments only where intent isn’t obvious; docstrings for public APIs.
- Single responsibility: each module/class/function does one thing; separate concerns; minimize side effects.
- Predictable control flow: limited branching depth; early returns for guard clauses; avoid deeply nested code.
- Good boundaries: clear interfaces; avoid leaking implementation details; use types or assertions to define expectations.
- DRY but pragmatic: share common logic without over-abstracting; duplicate only when it improves clarity.
- Small surfaces: limit global state; keep public APIs minimal; prefer immutability where practical.
- Testability: code structured so it's easy to unit/integration test; deterministic behavior; clear seams for injecting dependencies.
- Error handling: explicit failure paths; helpful messages; avoid silent catches; clean resource management.
- Observability: surface guarded fallbacks/edge conditions with trace/log hooks so silent behavior changes don’t hide regressions.
- Documentation: concise README/usage notes; explain non-obvious decisions; update docs alongside code.
- Tooling: automated formatting/linting/tests in CI; commit hooks for quick checks; steady dependency management.
- Performance awareness: efficient enough without premature micro-optimizations; measure before tuning.



## Current Behaviour

### Dev mode gates
- `load.py:76-290` sets `DEV_BUILD` (via `MODERN_OVERLAY_DEV_MODE=1` or a `-dev` version suffix). Dev builds default the plugin logger to DEBUG and log the “Running Modern Overlay dev build…” banner.
- `load.py:838-906` only writes `debug.json` defaults when `DEV_BUILD` is true, so release users have to craft the file manually.
- `overlay_plugin/preferences.py:775-923` hides the “Developer Settings” group unless `dev_mode=True`. That block holds the overlay restart button, opacity slider, gridlines, payload-ID cycling controls, payload sender, and legacy overlay testers. The force-render toggle now lives in the main preferences section.
- The overlay client/controller treat dev mode as an all-or-nothing flag:
  - `overlay_client/debug_config.py:30-120` ignores `debug.json` unless `DEBUG_CONFIG_ENABLED` (derived from dev mode) is true. Group outlines, axis tags, payload vertex markers, tracing, repaint logging, and custom log retention all hinge on that flag.
  - `overlay_client/overlay_client.py:76-101` and `overlay_client/data_client.py:34-42` keep their loggers at INFO in release builds; `_ReleaseLogLevelFilter` downgrades any DEBUG message to INFO when dev mode is off.
  - `overlay_client/setup_surface.py:70-224` guards faster cache flushes, repaint metrics, geometry logging, and other helper overlays on `DEBUG_CONFIG_ENABLED`.
  - `overlay_controller/overlay_controller.py:4318-4340` only writes richer controller logs (and stack traces) when dev mode is active.

### EDMC log-level gates
- `load.py:147-213` continuously sets the plugin logger to EDMC’s configured log level. Users already get INFO/DEBUG control by toggling EDMC’s UI setting.
- Overlay stdout/stderr capture is tied to EDMC logging: `_capture_enabled()` only returns true when the user both enables capture in `debug.json` and sets EDMC to DEBUG (`load.py:1043-1089`). The overlay controller launch uses the same check (`load.py:1491-1523`).
- The payload logger (`overlay-payloads.log`) itself is always active once preferences enable logging, but the decision to mirror payloads is wired through `debug.json` which currently requires dev mode.

## Pain Points
- Users who simply want richer logs must either rename the build to `-dev` or export `MODERN_OVERLAY_DEV_MODE=1`, which is especially confusing in Flatpak environments.
- Even when EDMC is set to DEBUG, the overlay/client/controller logs remain at INFO because `DEBUG_CONFIG_ENABLED` stays false; monitor/geometry traces and controller stack traces never appear.
- Debug UI affordances (grid, payload IDs, legacy test payloads) are bundled with the same gate that controls logging, preventing us from selectively granting high-risk toggles while keeping diagnostics easy.

## Refactor Goals
1. **Logging parity:** if EDMC’s log level is DEBUG, surface the same verbosity end-to-end (plugin, overlay client, overlay controller) without touching dev mode. This likely means piping the resolved level through `port.json` so the client/controller can honour it.
2. **`debug.json` availability:** allow the overlay client to load `debug.json` (at least for logging-related switches such as tracing, payload mirroring, repaint logging, log retention, and stdout capture) whenever EDMC is DEBUG. Keep purely visual developer helpers (group outlines, payload vertex markers) behind dev mode.
3. **Dev-mode scope:** reserve dev mode for disruptive toggles (force-render override, legacy payload injectors, experimental overlays, group editing shims). Users shouldn’t need it for basic diagnostics; the new `dev_settings.json` added in Phase 2 must therefore only be created/loaded when dev mode is explicitly active.
4. **Documentation update:** simplify docs/troubleshooting to say “set EDMC log level to DEBUG” for diagnostics, and describe dev mode only for the remaining developer-only controls.

## Suggested Work Items
1. Extend `port.json` (or another IPC channel) with the resolved EDMC log level so the overlay client/controller can bump their loggers to DEBUG when EDMC is DEBUG.
2. Update `overlay_client/debug_config.py` to load `debug.json` when either dev mode is active **or** EDMC logging is DEBUG; gate each flag individually so only troubleshooting helpers honour the EDMC switch. Introduce `dev_settings.json`, but only create/read it while dev mode is active so release users never see the file.
3. Split the developer UI block in `overlay_plugin/preferences.py`: move safe diagnostics (gridlines, payload cycling) out of the dev-only section, but leave force-render/test-payload buttons gated.
4. Ensure controller log capture honours EDMC’s log level regardless of dev mode by removing the `DEBUG_CONFIG_ENABLED` guard around `_ensure_controller_logger`.
5. Revisit docs (`docs/troubleshooting.md`, `docs/developer.md`) to reflect the new flow once implemented.

Tracking these steps in this document keeps the debugging workflow aligned with user expectations while still protecting experimental features behind the existing dev-mode flag.

## Implementation Phases

| Phase # | Description | Status |
| --- | --- | --- |
| 1a | Surface EDMC’s resolved log level via `port.json`/env vars and teach overlay client/controller launchers to read it. | Completed |
| 1b | Update overlay client/controller logging setup to honor the propagated level (raise to DEBUG when requested) and remove the release-mode debug demotion. | Completed |
| 1c | Extend `_ensure_default_debug_config()` so `debug.json` is auto-created whenever EDMC logging is DEBUG, and wire stdout capture/watchdog toggles to the new gate. | Completed |
| 1d | Implement the dev-mode override that forces all Modern Overlay loggers/capture to DEBUG even if EDMC logging is INFO/WARN. | Completed |
| 2 | Split troubleshooting vs. dev toggles: keep payload logging/capture in `debug.json`, create `dev_settings.json` for tracing/visual dev flags, and load it only in dev mode (without auto-creating it when EDMC is merely DEBUG). Update preferences/UI/docs accordingly. | Completed |
| 3 | Release-validation and polish: after the config split, update docs/tests accordingly and add the `release.yml` guard that fails when dev mode is enabled (`__version__` ends with `-dev` or `MODERN_OVERLAY_DEV_MODE` is set) so tagged builds never ship dev behaviour. | Completed |

### Phase 1a Plan (Log-level propagation)
1. **Expose EDMC log level in plugin runtime**  
   - Extend `port.json` with a `log_level` field (numeric + string label) and refresh it whenever EDMC’s log preference changes.  
   - Export an `EDMC_OVERLAY_LOG_LEVEL` env var during client/controller spawns to cover cases where the port file is inaccessible.
2. **Update overlay client launcher**  
   - Read the propagated level (prefer `port.json`, fall back to env) in `overlay_client/launcher.py` and pass it into the client settings/logging bootstrap.  
   - Maintain backward compatibility when the field is missing by defaulting to INFO.
3. **Update overlay controller launcher**  
   - Ensure the controller process reads the same env variable at startup and configures its logger before emitting output.
4. **Telemetry + tests**  
   - Log a single startup line in both processes summarizing the resolved level (“EDMC log level=DEBUG (source=port.json)”).  
   - Add unit tests covering `port.json` serialization/deserialization of the new field and the env fallback logic.
5. **Docs**  
- Document the new `log_level` field in developer docs/port.json schemas so downstream tools know to expect it.

### Phase 1b Plan (Client/controller logging updates)
1. **Overlay client logger**  
   - Read the `InitialClientSettings.edmc_log_level` hint early in `overlay_client.py` and set `_CLIENT_LOGGER` to that level (fallback to existing behaviour when unavailable).  
   - Remove the release-mode `_ReleaseLogLevelFilter` downgrading DEBUG to INFO so hints take effect.
2. **Overlay controller logger**  
   - Use the env hint captured in `_ENV_LOG_LEVEL_VALUE/_ENV_LOG_LEVEL_NAME` to set `resolve_log_level` defaults during `_ensure_controller_logger`.  
   - Ensure controller stdout/stderr logging honours the propagated level even before Tk initializes.
3. **Fallback rules**  
   - If the hint is missing/invalid, continue using the previous logic (INFO for releases) to avoid regressions.
4. **Validation**  
   - Add unit tests verifying that supplying the hint bumps client/controller loggers to DEBUG and that the fallback path still works.  
   - Add telemetry logs confirming the logger level set (“Overlay client logger level set to DEBUG via hint”).

### Phase 1c Plan (Auto-create debug.json + capture gating)
1. **Centralize EDMC DEBUG detection**  
   - Expose a helper (e.g., `_edmc_logging_is_debug()`) that memoizes `_resolve_edmc_log_level()` and signals whether DEBUG or lower is active.  
   - Ensure it updates when EDMC preferences change (hook into `prefs_changed` or log-level poller).
2. **Auto-create `debug.json` in DEBUG**  
   - In `_load_payload_debug_config()`, call `_ensure_default_debug_config()` when the helper reports DEBUG, even in release builds.  
   - Log once per session when the file is created to aid troubleshooting.
3. **Gate stdout/stderr capture**  
   - Update `_capture_enabled()` to use the helper so capture flips on automatically whenever EDMC logging is DEBUG (or dev mode override is active).  
   - Apply the same check to the controller launch path so both overlay and controller obey the same gate.
4. **Telemetry + docs**  
   - Emit info-level logs when capture transitions on/off because of the EDMC gate.  
   - Document the new behaviour in `docs/developer.md`/release notes so users know dev mode is no longer required just to collect `debug.json`.
5. **Tests**  
   - Add unit tests that simulate EDMC log level changes and assert `_capture_enabled()` responds correctly.  
   - Add tests confirming `_load_payload_debug_config()` creates `debug.json` when the helper returns True and skips it otherwise.

### Phase 1d Plan (Dev-mode logging override)
1. **Define override semantics**  
   - When dev mode is active (either via `DEV_BUILD` or `MODERN_OVERLAY_DEV_MODE=1`), treat every logging surface (plugin, overlay client, overlay controller, payload logger, stdout capture) as if EDMC’s log level were DEBUG, even if EDMC is currently INFO/WARN.  
   - Ensure the override stays opt-in (only when dev mode is explicitly enabled).
2. **Plugin logger**  
   - Update `_configure_logger()` so dev builds force the plugin logger to DEBUG regardless of EDMC’s current level, but still respect EDMC’s level when dev mode is off.  
   - Emit a clear banner (“Dev mode forcing Modern Overlay logger to DEBUG”) to aid troubleshooting.
3. **Overlay client/controller**  
   - Teach the client launcher and controller startup to detect dev mode (via the hint propagated in port.json/env) and force their loggers to DEBUG without needing a log-level hint.  
   - Update telemetry to indicate whether DEBUG came from EDMC, dev override, or both.
4. **Stdout capture**  
   - Allow `_capture_enabled()` to return True when dev mode is active even if EDMC logging isn’t DEBUG, so dev testers can always see stdout/stderr.  
   - Surface a warning when capture is active solely because of dev mode.
5. **Tests + docs**  
   - Add tests covering the dev override path (e.g., monkeypatch `load.DEV_BUILD = True` and confirm loggers flip to DEBUG).  
   - Update docs (developer/troubleshooting) to explain that dev mode now automatically forces DEBUG logging/capture across components.

### Phase 1d Implementation Notes
- `_effective_log_level()` now clamps the plugin logger (and `_EDMCLogHandler`) to DEBUG whenever `DEV_BUILD` is active; we log a single banner identifying when that override fires so EDMC logs always explain their provenance.
- `port.json` still advertises EDMC’s true log level, but `apply_log_level_hint()` in the PyQt client and `_ensure_controller_logger()` now clamp hints to DEBUG whenever dev mode is active, logging whether DEBUG came from EDMC or the dev override.
- `_capture_enabled()` relies on the new `_diagnostic_logging_enabled()` helper so stdout/stderr capture follows the EDMC gate but remains active in dev mode; `_update_capture_state()` surfaces whether capture is running because of EDMC DEBUG or the override.
- Added unit coverage for the new behaviour (`tests/test_logging_and_version_helper.py`, `overlay_client/tests/test_log_level_hint.py`, `overlay_controller/tests/test_controller_log_level_hint.py`) so future refactors can lean on deterministic helpers rather than module reloads.
- `docs/developer.md` and `docs/troubleshooting.md` now explain the EDMC vs. dev-mode log gates so users know that EDMC DEBUG alone unlocks diagnostics, while dev mode forces the same behaviour when experimenting at INFO/WARN.

### Phase 2 Plan (Split troubleshooting vs. dev toggles)

| Step | Description | Owner/Notes | Status |
| --- | --- | --- | --- |
| 2a | **Define config boundaries.** Enumerate which flags stay in `debug.json` (capture, payload logging, log retention, other user-facing diagnostics) versus which move to `dev_settings.json` (payload tracing, outlines, vertex markers, repaint overrides, controller shims). Update `DEFAULT_DEBUG_CONFIG` and introduce `DEFAULT_DEV_SETTINGS` so both files have clear schemas. | Runtime/Docs | Completed |
| 2b | **Loader implementation.** Teach `load.py` (and any helper modules) to load `debug.json` whenever `_diagnostic_logging_enabled()` is true, but only create/read `dev_settings.json` when dev mode is active. Ensure `dev_settings.json` shares the same fallback path (defaults + JSON schema validation) but never auto-seeds during release diagnostics. | Runtime | Completed |
| 2c | **Overlay client/controller consumers.** Update modules such as `overlay_client/debug_config.py`, `overlay_client/setup_surface.py`, and controller helpers to consume the split configs: troubleshooting toggles should look at the `debug.json` payload (honouring `_diagnostic_logging_enabled()`), while dev-only visuals read from `dev_settings.json` and stay inactive otherwise. | Client/Controller | Completed |
| 2d | **Preferences/UI updates.** Adjust the EDMC preferences panel so user-safe toggles (gridlines, payload cycling, log retention) appear regardless of dev mode, while the dev-only controls (force render, payload injector, overlays) reference the new `dev_settings` backing store. | Preferences | Completed |
| 2e | **Docs + schema.** Add/update documentation describing both files, show example JSON, and update any schema or troubleshooting references. Reflect the new workflow in `docs/troubleshooting.md`, `docs/developer.md`, and `docs/refactoring/debug_refactor.md`. | Docs | Completed |
| 2f | **Testing.** Add/extend unit coverage for the new loaders and consumers: verify that `debug.json` still auto-creates under EDMC DEBUG, `dev_settings.json` only appears in dev mode, and each flag path toggles the right behaviour. Ensure new tests for the overlay client/controller cover the config split. | Tests | Completed |

#### Phase 2a Mini-Plan (Define config boundaries)

| Task | Description | Notes |
| --- | --- | --- |
| 2a.1 | Inventory every flag currently stored in `debug.json` (see `DEFAULT_DEBUG_CONFIG` and client consumers) and classify each as **troubleshooting** (safe for users) or **developer** (requires dev mode). | Produce a table listing the destination file for each flag. |
| 2a.2 | Define the JSON schema/defaults for the new `dev_settings.json` (e.g., payload tracing, outlines, vertex markers, repaint overrides, controller helpers). | Introduce a `DEFAULT_DEV_SETTINGS` structure mirroring what we expect per key. |
| 2a.3 | Update docs/reference (this file + developer/troubleshooting guides) with a short rationale of the split and examples of both files so downstream steps know the target shape. | Keep this scoped to documentation only; loader changes are in later steps. |

#### Phase 2a Results

**Flag Split**

| Flags | Description | Destination |
| --- | --- | --- |
| `capture_client_stderrout` | Enables stdout/stderr capture for the overlay client/controller. | `debug.json` (Always available when `_diagnostic_logging_enabled()` is true.) |
| `overlay_logs_to_keep` | Retention count for rotating overlay client logs. | `debug.json` |
| `payload_logging.overlay_payload_log_enabled` | Master switch for writing `overlay-payloads.log`. | `debug.json` |
| `payload_logging.exclude_plugins` | Optional list of plugin IDs to skip when mirroring payloads. | `debug.json` |
| `trace_enabled`, `payload_ids` (legacy aliases) and `tracing.*` | Controls payload tracing/filters. Tracing remains a developer-only feature. | `dev_settings.json` |
| `overlay_outline` | Renders the dashed overlay window outline in dev mode. | `dev_settings.json` |
| `group_bounds_outline` | Draws per-group bounds/anchors for Fill-mode tuning. | `dev_settings.json` |
| `payload_vertex_markers` | Shows vertex dots on vector payloads. | `dev_settings.json` |
| `repaint_debounce_enabled` | Opt-in override for the repaint debounce helper. | `dev_settings.json` |
| `log_repaint_debounce` | Emits repaint-debug logs/metrics. | `dev_settings.json` |

`load.py` now exposes `DEFAULT_DEV_SETTINGS` so later phases can write the new file without guessing at the structure. `DEFAULT_DEBUG_CONFIG` remains unchanged for now so existing releases continue to parse the combined file until the loader split lands in Phase 2b.

#### Phase 2b Plan (Loader implementation)

| Task | Description | Notes |
| --- | --- | --- |
| 2b.1 | **Persist troubleshooting config.** Update `_load_payload_debug_config()` (and related helpers) to treat `debug.json` as the troubleshooting store: auto-create/populate it whenever `_diagnostic_logging_enabled()` is true, but only keep troubleshooting keys (capture, payload logging, log retention). Introduce migration logic that copies legacy dev flags into `dev_settings.json` when dev mode is active so we don’t lose user tweaks. |
| 2b.2 | **Add dev-settings loader.** Create `_load_dev_settings()` (or similar) that only runs when dev mode is active. It should load `dev_settings.json`, seed defaults from `DEFAULT_DEV_SETTINGS` if the file is missing, and expose the parsed data to the rest of the runtime without touching troubleshooting flags. |
| 2b.3 | **Expose combined config to consumers.** Extend `_PluginRuntime` to stash both troubleshooting config (`self._debug_config`) and dev settings (`self._dev_settings`), with helper accessors that the overlay client/controller can read when broadcasting config payloads. Ensure release builds skip reading `dev_settings.json` entirely. |
| 2b.4 | **Telemetry and fallbacks.** Emit clear logs when either file is created, migrated, or skipped (e.g., “Created default dev_settings.json because dev mode is active”) and handle JSON parse errors gracefully by reverting to defaults. |

#### Phase 2b Results
- `DEFAULT_DEBUG_CONFIG` now holds only troubleshooting toggles (stdout capture, payload logging, log retention), while `DEFAULT_DEV_SETTINGS` captures tracing/outline overrides. `_load_payload_debug_config()` auto-seeds `debug.json` whenever `_diagnostic_logging_enabled()` is true, and migrates any legacy dev flags into `dev_settings.json` whenever dev mode is active so user tweaks persist.
- New helpers (`_ensure_default_dev_settings()`, `_normalise_dev_settings()`, `_load_dev_settings()`) gate `dev_settings.json` creation strictly on dev-mode builds. When dev mode is off, dev settings reset to defaults and `_trace_enabled` stays false; when on, the logger reports when the file is created/migrated.
- Tests in `tests/test_logging_and_version_helper.py` now cover the split: we verify `dev_settings.json` isn’t created for release diagnostics and that legacy tracing fields migrate into the new file in dev mode.

#### Phase 2c Plan (Overlay client/controller consumers)

| Task | Description | Notes |
| --- | --- | --- |
| 2c.1 | **Client config loader.** Update `overlay_client/debug_config.py` so it reads troubleshooting settings from `debug.json` only when `_diagnostic_logging_enabled()` is true (EDMC DEBUG or dev override), but loads dev visuals/tracing from the new `dev_settings.json` whenever dev mode is active. Ensure the dataclass cleanly separates the two sources. |
| 2c.2 | **Runtime wiring.** Extend the plugin’s `_send_overlay_config()` payload (and any auxiliary API data) with the dev settings so the PyQt client/controller can access them without reopening the files themselves. Alternatively, teach the client launcher/controller to read `dev_settings.json` from disk when dev mode is active (mirroring the plugin’s loader). Choose whichever path keeps Flatpak/message flows simple. |
| 2c.3 | **Client consumers.** Adjust `overlay_client/setup_surface.py`, `render_surface.py`, and other helpers so troubleshooting behaviours (e.g., log retention, capture toggles, payload mirroring) respect the always-on config, while dev-only visuals (outlines, vertex markers, repaint overrides, tracing) require dev settings. Remove references to the old combined structure. |
| 2c.4 | **Controller consumers.** Update controller utilities (e.g., `overlay_controller/overlay_controller.py`, tracing/logging helpers) to read dev settings via the same mechanism, ensuring controller-only toggles (payload tracing, repaint overrides) look at the dev file and never depend on `debug.json`. |
| 2c.5 | **Telemetry/tests.** Log when the client/controller detect each config source, and add unit tests verifying that dev settings remain inactive in release mode even if `dev_settings.json` exists. Update existing tests for `overlay_client/debug_config.py` and controller log-level helpers to cover the new schema.

#### Phase 2c Results
- `overlay_client/debug_config.py` now exposes `load_troubleshooting_config()` for the EDMC-DEBUG gate and `load_dev_settings()` for dev-only helpers. Release builds always receive default dev settings even if `dev_settings.json` is present, and new unit tests (`overlay_client/tests/test_debug_config_split.py`) cover both paths.
- The launcher derives a `diagnostics_enabled` flag from the propagated EDMC log level, applies troubleshooting overrides (log retention) regardless of dev mode, and keeps the PyQt client/controller loggers in sync. Dev settings continue to gate outlines/tracing, but troubleshooting toggles no longer require dev mode.
- `OverlayWindow`, grouping helpers, and plugin overrides continue to consume the `DebugConfig` dev-settings dataclass, while the client log-controller now reads retention from the troubleshooting config so release users can tune logs whenever EDMC logging is DEBUG.

#### Phase 2d Results
- The EDMC preferences panel now includes a Diagnostics section that appears whenever `_diagnostic_logging_enabled()` is true (EDMC log level = DEBUG or dev mode). From there users can toggle stdout/stderr capture, set/clear the `overlay_logs_to_keep` override, and manage the payload-logging exclusion list without touching `debug.json`.
- Gridlines, grid spacing, and payload ID cycling were moved out of the dev-only block so they remain available in release builds; the legacy dev frame now focuses on force-render, restart, and other high-risk helpers.
- `_PluginRuntime` exposes `get_troubleshooting_panel_state()` plus setters for capture, log retention overrides, and exclusion lists. Updates flow back into `debug.json` through a new `_edit_debug_config()` helper that enforces the diagnostics gate and reloads the runtime state on success.
- `tests/test_logging_and_version_helper.py` now covers the new setter helpers so a regression in the debug-config mutator logic is caught quickly. `docs/troubleshooting.md` points users to the new Diagnostics controls so gathering logs no longer requires manual JSON edits.

#### Phase 2d Plan (Preferences/UI updates)

| Task | Description | Notes |
| --- | --- | --- |
| 2d.1 | **Expose troubleshooting toggles outside dev mode.** Update `overlay_plugin/preferences.py` so user-safe controls (log retention, payload capture toggle, payload logging exclusions) are visible whenever diagnostics are enabled, even if dev mode is off. Persist the values into `debug.json` so the new troubleshooting loader can read them. |
| 2d.2 | **Dev-only panel refresh.** Keep dev-only controls (force render, payload injector, overlay outlines, tracing toggles, repaint overrides) gated behind dev mode, but update their persistence to write into `dev_settings.json` instead of `debug.json`. Consider adding UI hints that these settings only apply when dev mode is active. |
| 2d.3 | **Controller hooks.** Ensure the overlay controller UI (Tk side) surfaces any dev-only toggles it needs (e.g., tracing) based on `dev_settings.json`, and does not reference `debug.json` directly anymore. |
| 2d.4 | **Documentation/tooltips.** Update the preference tooltips or inline docs so users know which settings require EDMC log level = DEBUG versus dev mode. |

#### Phase 2e Results
- Updated `docs/troubleshooting.md` with a dedicated diagnostics workflow, explicit EDMC log-level instructions, and example `debug.json`/`dev_settings.json` payloads so support can point users to the exact knobs that ship in each file.
- Expanded `docs/developer.md` with the same JSON examples plus guidance on how to add new troubleshooting vs. dev flags, ensuring future refactors touch the right defaults, loaders, and documentation at the same time.
- `RELEASE_NOTES.md` now calls out the diagnostics overhaul so release consumers understand that EDMC’s DEBUG level replaces the previous dev-mode requirement for log capture.

#### Phase 2f Results
- Added regression tests covering the troubleshooting panel state, payload logging preference plumbing, and the overlay client’s diagnostics gate so EDMC DEBUG (or the dev override) remains a single-switch entry point.
- Launcher tests now assert that `_diagnostics_enabled()` honours both the propagated EDMC log level and the dev-mode override, preventing regressive UI states where diagnostics silently disappear.
- Runtime tests validate that `get_troubleshooting_panel_state()` mirrors capture/log-retention/exclusion state and exposes the `_diagnostic_logging_enabled()` flag for the UI layer, ensuring the Diagnostics section knows when it can appear.

#### Phase 2e Plan (Docs & schema updates)

| Task | Description | Notes |
| --- | --- | --- |
| 2e.1 | **Schema/source-of-truth update.** Revise any JSON schema snippets (port.json, debug/dev settings) in `docs/troubleshooting.md`, `docs/developer.md`, and `docs/refactoring/debug_refactor.md` so they reflect the split between `debug.json` and `dev_settings.json`, including field descriptions and sample payloads. |
| 2e.2 | **Workflow documentation.** Update troubleshooting steps to say “set EDMC log level to DEBUG to enable diagnostics” and explain how the diagnostics UI now maps to `debug.json`. Provide explicit guidance on when to edit each file manually (if ever) and how dev mode changes behaviour. |
| 2e.3 | **Developer guidance.** Extend the developer/refactoring docs with a migration guide for maintainers: how to add new troubleshooting flags (update `DEFAULT_DEBUG_CONFIG`, docs, tests) versus dev-only toggles (update `DEFAULT_DEV_SETTINGS`, dev UI). Include reminders to update both the config loader and docs whenever new keys are introduced. |
| 2e.4 | **Release artifacts.** Ensure `RELEASE_NOTES.md` (or the relevant changelog) calls out the new diagnostics flow so users know to rely on EDMC’s log level rather than dev builds for logging. |

#### Phase 2f Plan (Test coverage)

| Task | Description | Notes |
| --- | --- | --- |
| 2f.1 | **Runtime tests.** Add/extend tests in `tests/test_logging_and_version_helper.py` (and related suites) that cover the final config split: auto-creation of `debug.json`, dev-only creation of `dev_settings.json`, migration paths, and the new preference setters that mutate each file. |
| 2f.2 | **Client/controller tests.** Expand `overlay_client/tests/test_debug_config_split.py`, `overlay_client/tests/test_logging_propagation.py`, and controller log-level tests to verify that diagnostics toggles remain active when EDMC logging is DEBUG, even without dev mode, while dev-only toggles stay inert. |
| 2f.3 | **UI tests.** Add Tk/panel unit tests (where practical) to ensure the Diagnostics section appears when `_diagnostic_logging_enabled()` is true, the dev frame hides when dev mode is off, and toggles invoke the correct callbacks (troubleshooting vs. dev settings). |
| 2f.4 | **Integration smoke.** Wire a smoke test (CLI script or pytest case) that simulates EDMC DEBUG mode end-to-end: launch the overlay client with the propagated log level, verify payload logging writes DEBUG lines, and confirm disabling diagnostics (EDMC=INFO) suppresses them. |

### Phase 3 Plan (Release validation & polish)

| Step | Description | Owner/Notes | Status |
| --- | --- | --- | --- |
| 3a | **CI guard.** Add a reusable verification script and wire it into `.github/workflows/release.yml` so every packaging job fails immediately if the version string carries a dev suffix or `MODERN_OVERLAY_DEV_MODE` is exported. | CI | Completed |
| 3b | **Documentation updates.** Capture the release-guard rationale/results in this refactoring doc and ensure future release instructions call out the CI check. | Docs | Completed |

#### Phase 3 Results
- Introduced `scripts/verify_release_not_dev.py`, which inspects both the current `__version__` and the `MODERN_OVERLAY_DEV_MODE` override to ensure tagged builds never run with developer behaviour enabled.
- Both release jobs now execute the guard right after checkout so the workflow fails fast if someone tags a `-dev` build or leaves a dev-mode env var set in the workflow dispatch.
- This document records the guard so future maintainers know where the check lives and what it enforces.
