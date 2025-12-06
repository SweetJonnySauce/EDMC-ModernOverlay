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
- `overlay_plugin/preferences.py:775-923` hides the “Developer Settings” group unless `dev_mode=True`. That block holds the overlay restart button, force-render toggle, opacity slider, gridlines, payload-ID cycling controls, payload sender, and legacy overlay testers. Release builds also refuse to persist `force_render` unless `allow_force_render_release` is set (`load.py:1349-1385`, `preferences.py:293-318, 413-432`).
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
3. **Dev-mode scope:** reserve dev mode for disruptive toggles (force-render override, legacy payload injectors, experimental overlays, group editing shims). Users shouldn’t need it for basic diagnostics.
4. **Documentation update:** simplify docs/troubleshooting to say “set EDMC log level to DEBUG” for diagnostics, and describe dev mode only for the remaining developer-only controls.

## Suggested Work Items
1. Extend `port.json` (or another IPC channel) with the resolved EDMC log level so the overlay client/controller can bump their loggers to DEBUG when EDMC is DEBUG.
2. Update `overlay_client/debug_config.py` to load `debug.json` when either dev mode is active **or** EDMC logging is DEBUG; gate each flag individually so only logging/tracing helpers honour the EDMC switch.
3. Split the developer UI block in `overlay_plugin/preferences.py`: move safe diagnostics (gridlines, payload cycling) out of the dev-only section, but leave force-render/test-payload buttons gated.
4. Ensure controller log capture honours EDMC’s log level regardless of dev mode by removing the `DEBUG_CONFIG_ENABLED` guard around `_ensure_controller_logger`.
5. Revisit docs (`docs/troubleshooting.md`, `docs/developer.md`) to reflect the new flow once implemented.

Tracking these steps in this document keeps the debugging workflow aligned with user expectations while still protecting experimental features behind the existing dev-mode flag.

## Implementation Phases

| Phase # | Description | Status |
| --- | --- | --- |
| 1a | Surface EDMC’s resolved log level via `port.json`/env vars and teach overlay client/controller launchers to read it. | Not started |
| 1b | Update overlay client/controller logging setup to honor the propagated level (raise to DEBUG when requested) and remove the release-mode debug demotion. | Not started |
| 1c | Extend `_ensure_default_debug_config()` so `debug.json` is auto-created whenever EDMC logging is DEBUG, and wire stdout capture/watchdog toggles to the new gate. | Not started |
| 1d | Implement the dev-mode override that forces all Modern Overlay loggers/capture to DEBUG even if EDMC logging is INFO/WARN. | Not started |
| 2 | Split troubleshooting vs. dev toggles: keep payload logging/capture in `debug.json`, create `dev_settings.json` for tracing/visual dev flags, and load it only in dev mode. Update preferences/UI/docs accordingly. | Not started |
| 3 | Clean-up and validation: adjust overlay client/controller logging filters, ensure stdout capture obeys the new gating, and update documentation/tests to reflect the new workflow. | Not started |
