# Readable and Maintainable code compliance

## Guiding traits for EDMC plugins
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


## Current compliance assessment

| Item | Status | Notes/Actions |
| --- | --- | --- |
| Module boundaries & size (`load.py`) | Partial | `load.py` is slimmer with lifecycle/broadcaster/watchdog delegated (`overlay_plugin/runtime_services.py`) and controller orchestration split (`overlay_plugin/controller_services.py`); EDMC hooks are thin with docstrings and hook smokes added. Still large with mixed responsibilities (prefs/state/journal/config emission), so continue extracting config rebroadcast/version notice helpers and consider further runtime splitting. |
| Preferences UI complexity | Needs attention | `PreferencesPanel.__init__` builds the entire UI inline over ~500+ lines with many callbacks (overlay_plugin/preferences.py:449-1023) and handlers spread below (1028-1110+); readability and testability suffer. Move to data-driven field definitions or subcomponents, push Tk setup into helpers, and add unit tests for validation/wiring. |
| Thread/timer lifecycle clarity | Good | Lifecycle is now centralized via `LifecycleTracker` (overlay_plugin/lifecycle.py) with tracking/joins; constructor no longer spawns timers/threads—startup happens in `start()` and teardown logs failures instead of swallowing them. Added leak-focused tests (`tests/test_lifecycle_tracking.py`) and full suite (`make check` with PYQT_TESTS=1) passes. |
| Config schema readability | Partial | Preferences blend EDMC config and shadow JSON with manual key names/coercers scattered (overlay_plugin/preferences.py:42-146) and magic defaults. Define a single schema (defaults, bounds, config keys) and reuse it for load/save/UI binding to reduce drift and improve clarity. |
| Logging/observability | Good | Consistent logger usage (`LOGGER`, `_log`, payload logger) and detailed debug messages around geometry/watchdog/payload flows; version/update notices are surfaced (load.py, overlay_client/follow_geometry.py). Preserve these signals during refactors. |
| Tests & coverage for readability | Partial | Strong unit/integration coverage for controller/workflow/grouping/prefs persistence (`tests/test_controller_workflow.py`, `tests/test_preferences_persistence.py`, etc.), but no automated checks for Tk UI wiring or thread/timer lifecycles. Add focused tests/mocks around `_PluginRuntime.start/stop`, timer cleanup, and UI value validation to lock in behavior. |
