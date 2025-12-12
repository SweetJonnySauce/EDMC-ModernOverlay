## Goal: EDMC 6.0.0 Compatibility

## Refactorer Persona
- Bias toward carving out modules aggressively while guarding behavior: no feature changes, no silent regressions.
- Prefer pure/push-down seams, explicit interfaces, and fast feedback loops (tests + dev-mode toggles) before deleting code from the monolith.
- Treat risky edges (I/O, timers, sockets, UI focus) as contract-driven: write down invariants, probe with tests, and keep escape hatches to revert quickly.
- Default to “lift then prove” refactors: move code intact behind an API, add coverage, then trim/reshape once behavior is anchored.
- Resolve the “be aggressive” vs. “keep changes small” tension by staging extractions: lift intact, add tests, then slim in follow-ups so each step stays behavior-scoped and reversible.
- Track progress with per-phase tables of stages (stage #, description, status). Mark each stage as completed when done; when all stages in a phase are complete, flip the phase status to “Completed.” Number stages as `<phase>.<stage>` (e.g., 1.1, 1.2) to keep ordering clear.
- Personal rule: if asked to “Implement…”, expand/document the plan and stages (including tests to run) before touching code.
- Personal rule: keep notes ordered by phase, then by stage within that phase.

## Dev Best Practices

- Keep changes small and behavior-scoped; prefer feature flags/dev-mode toggles for risky tweaks.
- Plan before coding: note touch points, expected unchanged behavior, and tests you’ll run.
- Avoid UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.

## Per-Iteration Test Plan
- **Env setup (once per machine):** `python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -e .[dev]`
- **Headless quick pass (default for each step):** `source .venv/bin/activate && python -m pytest` (scope with `tests/…` or `-k` as needed).
- **Core project checks:** `make check` (lint/typecheck/pytest defaults) and `make test` (project test target) from repo root.
- **Full suite with GUI deps (as applicable):** ensure GUI/runtime deps are installed (e.g., PyQt for Qt projects), then set the required env flag (e.g., `PYQT_TESTS=1`) and run the full suite.
- **Targeted filters:** use `-k` to scope to touched areas; document skips (e.g., long-running/system tests) with reasons.
- **After wiring changes:** rerun headless tests plus the full GUI-enabled suite once per milestone to catch integration regressions.

## Guiding Traits for Readable, Maintainable Code
- Clarity first: simple, direct logic; avoid clever tricks; prefer small functions with clear names.
- Consistent style: stable formatting, naming conventions, and file structure; follow project style guides/linters.
- Intent made explicit: meaningful names; brief comments only where intent isn’t obvious; docstrings for public APIs.
- Single responsibility: each module/class/function does one thing; separate concerns; minimize side effects.
- Predictable control flow: limited branching depth; early returns for guard clauses; avoid deeply nested code.
- Good boundaries: clear interfaces; avoid leaking implementation details; use types or assertions to define expectations.
- DRY but pragmatic: share common logic without over-abstracting; duplicate only when it improves clarity.
- Small surfaces: limit global state; keep public APIs minimal; prefer immutability where practical.
- Testability: code structured so it’s easy to unit/integration test; deterministic behavior; clear seams for injecting dependencies.
- Error handling: explicit failure paths; helpful messages; avoid silent catches; clean resource management.
- Observability: surface guarded fallbacks/edge conditions with trace/log hooks so silent behavior changes don’t hide regressions.
- Documentation: concise README/usage notes; explain non-obvious decisions; update docs alongside code.
- Tooling: automated formatting/linting/tests in CI; commit hooks for quick checks; steady dependency management.
- Performance awareness: efficient enough without premature micro-optimizations; measure before tuning.

## EDMC 6.0.0-rc2 Release Notes

https://github.com/EDCD/EDMarketConnector/releases/tag/Release%2F6.0.0-rc2

### Features
- Full x64 builds, unified `config.toml`, `--config` and `--skip-journallock` flags.
- New core plugins (EDAstro), plugin enable/disable, relative-import support.
- ScrollableNotebook in Plugins UI, updated ttk elements, Python 3.13 baseline.
- Added carrier CAPI triggers, colonisation localization, safer EDMC:// handler.

This is a RELEASE CANDIDATE for EDMC 6.0.0, now available on the Beta update track!

This build represents one of the most significant internal updates to EDMC in recent memory. It includes a complete overhaul of the configuration system, full x64-bit build support, major plugin system enhancements (including enable/disable support), new core plugins, and additional updates across the codebase.

Because of the scale of these changes, existing workflows, plugins, and user configurations may behave differently. Plugin developers must review the removal list and update their plugins promptly, as several deprecated APIs and legacy behaviors have been removed.

This is a RELEASE CANDIDATE – This is intended to be a stable release that includes all new content for EDMC 6.0, but may still include bugs. Please report any issues on GitHub so we can stabilize the final 6.0.0 release.

Changes and Enhancements

    Enables building of x64-bit builds.
    Added a new unified config system and migrated both Linux and Windows configuration files to a new config.toml format at the program root directory.
    Added a new --config option to EDMC to allow users to specify a different config file.
    Added a new EDAstro core plugin to send specific events to EDAstro.
    Added a new plugin Enable/Disable system, in Preferences -> Plugins.
    Added a new logger to the Config module prior to the default logger.
    Added a new --skip-journallock argument to allow EDMC to start even if the journal lock was not acquired.
    Added a new ScrollableNotebook class to enable horizontal scrolling of tabs in a Notebook.
    Added a series of new events to trigger a Carrier CAPI check.
    Added localization for Colonisation ships.
    Added the ability for plugins to use relative imports between modules.
    Updated the Plugins settings window to use the new ScrollableNotebook class.
    Updated a number of GitHub workflow dependencies.
    Updated the default Python version to 3.13.
    Updated EDMC:// protocol handler to use process handles with least-privilege access for improved security and reliability.
    Updated a number of Tkinter TK elements to use the updated TTK equivalents.
    Updated some internal function calls to use non-deprecated alternatives.
    Updated the LastError class to a Python Dataclass.
    Updated a number of dependencies.
    Updated a number of Win32 calls with proper prototyping for x64-bit builds.
    Updated the Windows WinSparkle updater to be more maintainable.
    Updated the Windows DDE Request handler for the EDMC Protocol, specifically callbacks and internal stability.
    Updated a number of older internal functions to use Python 3 logic and hinting.
    Simplified some internal logic calls.
    Simplified the git shorthash function call.

Bug Fixes

    Fixes a bug where protocol handler reset popups would be generated on first runs of EDMC.
    Fixed a bug where "en" was not present in available languages.
    Fixed a bug where the EDMC System Profiler could not be run on Linux systems.
    Fixed a bug where the plugin prefs window was not resizable.
    Fixed a bug where EDDN's queue would not actually start processing on app launch.
    Fixed a long-standing bug where commodity CSV exports weren't comma-separated.
    Fixed a bug where boarding another player's ship would result in the ship being uploaded to plugins.

Key Removals

    Removed the long-deprecated config 1.0 conversion calls.
    Removed the "_" builtin translation in favor of tr.tl.
    Removed the stringFromNumber, numberFromString, and preferredLanguages functions.
    Removed the _Translations singleton in favor of the more modern classes.
    Removed the nb.Entry, nb.ColoredButton classes.
    Removed legacy queue migration functionality from EDDN.
    Removed the help_open_log_folder function in favor of open_log_folder.
    Removed the legacy config AbstractClass and most Windows/Linux specific config functions in favor of new defaults.

Plugin Developers

    Several deprecated functions have been removed. Please ensure your plugins are updated!
    The new Plugin Disable option relies on plugins respecting plugin_stop(). Ensure that your plugins respect this call!
    EDMC is now installed by default with x64-bit builds.
    EDMC will expect a minimum version of Python 3.13. While we do not currently use code incompatible with some earlier versions, we reserve the right to do so.

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Align legacy shim overlay_api import with package-registered module | Completed |
| 2 | Migrate prefs UI to EDMC 6-supported widgets/translations | Completed |

## Phase Details

### Phase 1: Align legacy shim overlay_api import with package-registered module
- Goal: ensure `EDMCOverlay/edmcoverlay.py` uses the same `overlay_plugin.overlay_api` instance that `load.py` registers, so legacy payloads no longer hit the “publisher unavailable” path after EDMC 6’s package import changes.
- Behavior to keep: no change to payload contents/format, legacy callers still import `edmcoverlay` the same way, overlay client launch/stop flow unchanged.
- Edge cases: running overlay shim standalone (no package import), multiple imports (top-level vs package), order of imports during EDMC startup, dev-mode stdout capture.
- Risks: regress legacy standalone usage, double-register publisher, regress non-overlay plugins that import `overlay_plugin.overlay_api` directly.
- Mitigations: prefer aliasing rather than moving files; guard alias to avoid re-binding; fall back cleanly when package context missing.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Inventory current imports and registration sites (`EDMCOverlay/edmcoverlay.py` vs `load.py`) and confirm runtime failure mode in logs | Completed |
| 1.2 | Decide aliasing approach: import package module (`.overlay_plugin.overlay_api`) and seed `sys.modules["overlay_plugin.overlay_api"]` to point to it when missing; keep legacy fallback for direct import | Completed |
| 1.3 | Implement guarded alias in the shim, retain existing fallback for standalone runs; add minimal sanity test (if feasible) or log hook to verify publisher is set | Completed |
| 1.4 | Validate manually: start EDMC 6, observe overlay payloads delivered without “not available” warnings; confirm no duplicate registration warnings | Completed |

#### Stage 1.1 Plan
- Read current imports and registration paths:
  - `EDMCOverlay/edmcoverlay.py`: how it imports `overlay_api` and when `_publisher` is checked.
  - `load.py`: where it registers the publisher and grouping store.
  - Any other modules that may import `overlay_api` (e.g., other plugins/tests) to spot differing module names.
- Confirm failure evidence in logs: capture the “Overlay publisher unavailable” equivalent (`EDMCModernOverlay is not available to accept messages`) and note timestamps/PIDs from `EDMarketConnector-debug.log`.
- Decide artifacts to reference: note interpreter paths, port file, and client log positions that confirm the shim used the wrong module.
- Deliverable for this stage: short note summarizing the import split and the observed failure sequence; update stage status once notes are recorded.

#### Stage 1.1 Findings
- Import split: `EDMCOverlay/edmcoverlay.py` imports `overlay_plugin.overlay_api` via the top-level module path; `load.py` (imported as the package module under EDMC 6) registers the publisher in `EDMCModernOverlay.overlay_plugin.overlay_api`. Because the module objects differ, `_publisher` stays `None` in the shim context.
- Failure evidence: `EDMarketConnector-debug.log` shows repeated `RuntimeError: EDMCModernOverlay is not available to accept messages` when BGS-Tally calls `edmcoverlay.send_shape` (e.g., 2025-12-09 00:16:42 and 00:29:08 runs). The overlay payload log stays empty after Dec 8, confirming the publisher disconnect.
- Relevant paths: publisher registration in `load.py` via `register_publisher(self._publish_external)`; shim emits via `send_overlay_message` in top-level `overlay_plugin.overlay_api`. Port file written at `~/.local/share/EDMarketConnector/plugins/EDMCModernOverlay/port.json`, interpreter `/overlay_client/.venv/bin/python`, confirming plugin runs but messages are rejected.

#### Stage 1.2 Plan
- Goal: choose a shim-side aliasing strategy so both package and top-level imports resolve to the same module instance.
- Options to weigh:
  - Import package module (`from .overlay_plugin import overlay_api as api`) and seed `sys.modules["overlay_plugin.overlay_api"] = api` when that key is missing.
  - Conversely, import top-level `overlay_plugin.overlay_api` and, if the package path exists, set `sys.modules[__package__ + ".overlay_plugin.overlay_api"] = api`.
  - Whether to guard with a sentinel to avoid reassigning on repeated imports.
- Constraints: keep backward-compatible fallback for running shim standalone (no package import), avoid side effects if EDMC already loaded both names, and ensure no duplicate publisher registration.
- Deliverable: decide the alias direction, the exact guard condition, and where to place the alias in `edmcoverlay.py` (likely immediately after import). Document the decision and update stage status when ready to implement.

#### Stage 1.2 Decision
- Alias direction: import the package module (`from ..overlay_plugin import overlay_api as api`) when available; after successful import, seed `sys.modules["overlay_plugin.overlay_api"] = api` if that key is absent. This aligns the legacy top-level import with the package module that `load.py` populates.
- Guarding: only set the alias when the top-level key is missing to avoid replacing an existing instance; keep the current fallback stub when the package import fails (standalone runs).
- Placement: immediately after the primary import in `EDMCOverlay/edmcoverlay.py`, before `_UNAVAILABLE_WARN_TS` usage, so all subsequent calls share the same `_publisher`.

#### Stage 1.3 Plan
- Implement the guarded alias in `EDMCOverlay/edmcoverlay.py`:
  - Attempt to import `..overlay_plugin.overlay_api` as `api`.
  - If successful and `sys.modules["overlay_plugin.overlay_api"]` is missing, assign it to `api`.
  - Keep the existing fallback stub for the “module unavailable” path (standalone runs).
- Add a minimal verification hook:
  - Lightweight: a debug log when the alias is set (suppressed in normal runs) or a comment noting the alias intent; avoid noisy logging in production.
  - Consider a simple sanity check to ensure `send_overlay_message` resolves to the shared module (e.g., assert presence of `register_publisher` attributes), but avoid raising in production; use defensive guard only.
- Tests/validation to note:
  - Unit-level (if feasible): import shim in package context and confirm both module keys point to the same object.
  - Manual: run EDMC 6 and verify absence of “EDMCModernOverlay is not available to accept messages” warnings; check overlay payload log receives entries.

#### Stage 1.3 Implementation
- Changes: in `EDMCOverlay/edmcoverlay.py`, import the package `overlay_api`, alias it into `sys.modules["overlay_plugin.overlay_api"]` when missing, and fall back to the legacy/top-level import or stub for standalone runs. `send_overlay_message` now binds from the shared module when available.
- Verification hook: no extra logging added (to avoid noise); alias only occurs when the top-level key is absent, keeping behavior stable when EDMC already loaded both names.
- Next validation: run EDMC 6 to confirm legacy payloads succeed and warnings disappear; consider a lightweight import check in tests if desired.

#### Stage 1.4 Plan
- Goal: validate end-to-end that legacy payloads are accepted under EDMC 6 with the alias in place.
- Steps:
  - Start EDMC 6 with the updated plugin; ensure overlay client launches (port file written).
  - Trigger a plugin that uses `edmcoverlay` (e.g., BGS-Tally) and watch for overlay output.
  - Check `EDMarketConnector-debug.log` for absence of “EDMCModernOverlay is not available to accept messages” warnings.
  - Check `~/.local/share/EDMarketConnector/logs/EDMCModernOverlay/overlay-payloads.log` for new entries after startup.
  - Confirm overlay client log shows connections and no disconnect spam.
- Exit criteria: messages flow without the previous runtime error; stage can be marked completed once evidence is captured.

#### Stage 1.4 Validation
- Outcome: Manual run on EDMC 6 with updated shim shows overlay payloads being accepted; no further `EDMCModernOverlay is not available to accept messages` warnings in `EDMarketConnector-debug.log`.
- Overlay logs: `overlay-payloads.log` updates after startup; client logs show normal connect/disconnect without error spam.
- Phase 1 status set to Completed.

### Phase 2: Migrate prefs UI to EDMC 6-supported widgets/translations
- Goal: update the prefs panel to use supported notebook/entry/button widgets and translations API now that `nb.Entry`, `nb.ColoredButton`, and `_()` are removed.
- Behavior to keep: same user-visible layout and behavior of Modern Overlay prefs; no preference storage changes.
- Risks: breaking the prefs dialog layout, missing translations, regress focus/validation handlers.
- Mitigations: map existing handlers to ttk/tk equivalents, keep callbacks intact, and check for translation availability.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Inventory prefs UI usage of deprecated APIs (`nb.Entry`, `nb.ColoredButton`, `_()`) and map each to replacements (`nb.EntryMenu`/`tk.Button`/`translations.tl`) | Completed |
| 2.2 | Update imports and widget construction to supported types; ensure callbacks/validation still wired | Completed |
| 2.3 | Adjust translations to use `translations.tl` or imported translate helper; remove `_()` usage | N/A (no `_()` usage found) |
| 2.4 | Validate prefs dialog in EDMC 6: opens without errors, controls function, translations render | Completed |

#### Stage 2.1 Plan
- Scan `load.py` and any prefs-related modules (e.g., `overlay_plugin/preferences.py`) for:
  - `nb.Entry` → replace with `nb.EntryMenu` or ttk entry equivalent per EDMC guidance.
  - `nb.ColoredButton` → replace with `tk.Button` (or ttk button if appropriate).
  - `_()` translation calls → replace with `translations.tl` or `translations.translate` after importing `translations`.
- Record each occurrence with the intended replacement widget/API and note any custom options (colors, validation, callbacks) that need mapping.
- Deliverable: a mapping list of deprecated usages and chosen replacements to feed Stage 2.2 updates.

#### Stage 2.1 Findings
- Files inspected: `overlay_plugin/preferences.py` (prefs UI); no occurrences found in `load.py`.
- Deprecated widgets:
  - `nb.Entry` at `overlay_plugin/preferences.py:750` (launch command entry). Intended replacement: `nb.EntryMenu` (width=10, same bindings).
  - `nb.Entry` at `overlay_plugin/preferences.py:858` (payload exclude entry). Intended replacement: `nb.EntryMenu` (width=28, fill/expand bindings).
- Non-deprecated widgets (keep as-is): existing `nb.EntryMenu` instances for test message and coordinates at lines ~986/988/990.
- Deprecated translations: none found; no `_()` calls in prefs files.
- Deprecated `nb.ColoredButton`: none found.
- Completion criteria met: mapping ready for Stage 2.2 implementation.

#### Stage 2.2 Plan
- Update `overlay_plugin/preferences.py`:
  - Replace `nb.Entry` at the launch command row with `nb.EntryMenu` (keep width/textvariable/bindings).
  - Replace `nb.Entry` at the payload exclude row with `nb.EntryMenu` (keep width/textvariable/bindings/fill/expand and state toggles).
- Ensure imports stay valid (nb already provides EntryMenu); no new dependencies needed.
- Quick sanity: import the module after changes to catch typos; then open prefs in EDMC 6 to confirm layout/behavior unchanged.

#### Stage 2.2 Implementation
- Changes applied in `overlay_plugin/preferences.py`: `nb.Entry` instances for launch command and payload exclude fields replaced with `nb.EntryMenu`, preserving width, textvariable, layout, and bindings.
- Imports unchanged (nb already exposes EntryMenu).
- Next validation: import check and manual prefs dialog run in EDMC 6 to ensure layout/behavior unchanged.

#### Stage 2.3 Note
- No `_()` translation calls were found in prefs code; stage marked N/A. No `translations.tl` usage observed either; prefs UI currently uses plain strings.

#### Stage 2.4 Plan
- Goal: ensure prefs dialog works in EDMC 6 after widget swaps.
- Steps:
  - Launch EDMC 6 with the updated plugin.
  - Open Preferences → Plugins → EDMCModernOverlay prefs.
  - Interact with modified fields:
    - Chat command entry (EntryMenu): edit, hit Enter/FocusOut, confirm value persists/applies.
    - Payload exclude entry (EntryMenu): edit/apply; ensure disabled state when not allowed still works.
  - Scan `EDMarketConnector-debug.log` for any prefs-related errors.
  - Visually confirm layout unchanged and buttons/checks still functional.
- Exit criteria: prefs dialog opens without errors, fields behave as before, no new warnings in logs.

#### Stage 2.4 Validation
- Status: Manually validated in EDMC 6: prefs dialog opens, launch command and payload exclude EntryMenus work with Enter/FocusOut/apply; no prefs-related errors in logs. Phase 2 readiness confirmed.
