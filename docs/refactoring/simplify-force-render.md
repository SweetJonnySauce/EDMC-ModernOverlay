## Goal: Simplify how we force rendering

## Requirements (Behavior)
- "Keep overlay visible" remains a dev-only preference for now (do not expose in release UI).
- When "Keep overlay visible" is checked, the overlays must render even when the game is not focused (no release gating).
- When the controller is active (controller mode), the overlays must render even when the game is not focused, even if the user has disabled "Keep overlay visible."
- Controller force-render is runtime-only (no persistence across restarts).
- Drop `allow_force_render_release` entirely (no config key, no persistence).

## Current Behavior (Force Render + Release Gate)

### Definitions
- `force_render`: keeps the overlay visible even when Elite is not the foreground window.
- `allow_force_render_release`: release-build gate/override flag that decides whether `force_render` is honored or cleared.

### Key Enforcement Points
- Effective force-render is computed by `_is_force_render_enabled()` in `load.py`. In dev builds it returns `force_render`; in release builds it returns `force_render && allow_force_render_release`.
- Release builds refuse to persist `force_render` unless `allow_force_render_release` is set. This is enforced in `Preferences.disable_force_render_for_release()` (`overlay_plugin/preferences.py`) and `load.py::_update_force_render_locked()`.
- `allow_force_render_release` is cleared on plugin startup (`load.py::_reset_force_render_override_on_startup`) and can be re-enabled temporarily by the controller via the `force_render_override` CLI command.
- The overlay client bootstraps its initial state from `overlay_settings.json` in `overlay_client/client_config.py::load_initial_settings()`, which forces `force_render = False` if `allow_force_render_release` is false.

### Client Visibility Behavior
- The client decides visibility with `force_render or (state.is_visible and state.is_foreground)` in `overlay_client/window_controller.py::post_process_follow_state()`.
- When `force_render` flips, `overlay_client/control_surface.py::set_force_render()` updates visibility immediately and re-applies follow state (including drag/interaction behavior on Linux).

## Runtime Flow: Dev Build

1) Preferences load
- `Preferences.__post_init__()` (`overlay_plugin/preferences.py`) loads config or `overlay_settings.json`, then calls `disable_force_render_for_release()`, which is a no-op when `dev_mode` is true.
- `allow_force_render_release` defaults to `dev_mode` when missing, but may be cleared later by the startup override reset.

2) Startup override reset
- `_PluginRuntime.__init__()` calls `_reset_force_render_override_on_startup()` (`load.py`), which clears `allow_force_render_release` if it is true and saves preferences.
- This does not change effective force-render in dev builds because `_is_force_render_enabled()` ignores the allow flag when `DEV_BUILD` is true.

3) Initial client bootstrap
- The client reads `overlay_settings.json` via `load_initial_settings()` (`overlay_client/client_config.py`).
- If `allow_force_render_release` is false in the file (common after step 2), the initial client setting forces `force_render` to false until the first config payload arrives.

4) Overlay config broadcast
- The plugin sends the overlay config using `_is_force_render_enabled()` (`load.py`) so the client eventually receives the dev-mode `force_render` value regardless of the allow flag.
- The client calls `set_force_render()` and `post_process_follow_state()` to apply visibility behavior.

5) Controller override path (optional)
- Opening the controller calls `ForceRenderOverrideManager.activate()` (`overlay_controller/services/plugin_bridge.py`), which sends a `force_render_override` CLI payload (`allow=true`, `force_render=true`).
- The plugin handles this in `_handle_cli_payload()` (`load.py`) and sets `allow_force_render_release=true` plus `force_render=true`, then starts `_start_force_render_monitor_if_needed()` to auto-clear the allow flag when the controller exits.
- Because dev builds ignore the allow flag for effectiveness, this path mainly exists to support the release policy and controller-driven restore logic.

## Runtime Flow: Release Build

1) Preferences load
- `Preferences.__post_init__()` loads settings and calls `disable_force_render_for_release()` (`overlay_plugin/preferences.py`).
- If `allow_force_render_release` is false and `force_render` is true, it clears `force_render` and saves immediately.

2) Startup override reset
- `_reset_force_render_override_on_startup()` (`load.py`) clears `allow_force_render_release` and saves.
- This guarantees the default policy on each restart, even if a controller override was active in the previous session.

3) Initial client bootstrap
- `load_initial_settings()` (`overlay_client/client_config.py`) reads `overlay_settings.json` and forces `force_render = False` when `allow_force_render_release` is false.
- This prevents force-render visibility before the config payload arrives.

4) Config updates and preference changes
- `_is_force_render_enabled()` (`load.py`) returns `force_render && allow_force_render_release`.
- `_update_force_render_locked()` rejects a `force_render=true` update when `allow_force_render_release` is false, logging a warning and keeping `force_render` false.
- `set_force_render_preference()` only takes effect if the allow flag is true.

5) Controller override path (temporary allow)
- When the controller opens, `ForceRenderOverrideManager.activate()` sends `force_render_override` with `allow=true` and `force_render=true`.
- The plugin applies both flags, broadcasts config, and starts `_start_force_render_monitor_if_needed()` (`load.py`).
- The monitor clears `allow_force_render_release` (and saves + broadcasts) once the controller is no longer detected, reverting the policy and disabling force-render if it was only active via the override.

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

## Execution Rules
- Before planning/implementation, set up your environment using `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed).
- For each phase/stage, create and document a concrete plan before making code changes.
- Identify risks inherent in the plan (behavioral regressions, installer failures, CI flakiness, dependency drift, user upgrade prompts) and list the mitigations/tests you will run to address those risks.
- Track the plan and risk mitigations alongside the phase notes so they are visible during execution and review.
- After implementing each phase/stage, document the results and outcomes for that stage (tests run, issues found, follow-ups).
- After implementation, mark the stage as completed in the tracking tables.
- Do not continue if you have open questions, need clarification, or prior stages are not completed; pause and document why you stopped so the next step is unblocked quickly.

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Define single force-render policy, remove release gating, and introduce runtime-only controller override | Planned |
| 2 | Clean up persistence/schema/tests/docs for removed `allow_force_render_release` | Planned |

## Phase Details

### Phase 1: Single Force-Render Policy + Controller Runtime Override
- Goal: enforce one source of truth for force-render (the preference) plus a runtime-only controller override; remove release gating logic.
- APIs/Behavior: effective force-render = `force_render_preference || controller_override_active`.
- Invariants: "Keep overlay visible" remains dev-only UI; controller mode always forces render; controller override does not persist.
- Risks: regressions in visibility when Elite is unfocused; loss of controller override restoration; stale settings in `overlay_settings.json`.
- Mitigations: add targeted tests for controller override lifecycle and client visibility; keep settings migration and backward-compatible read (ignore old key).

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Identify all references to `allow_force_render_release` and release gating; document the new effective-force-render rule | Planned |
| 1.2 | Update plugin runtime to compute effective force-render without release gating; wire controller override as runtime-only | Planned |
| 1.3 | Update controller override manager to avoid writing persistence flags; ensure activation/deactivation only affects runtime state | Planned |
| 1.4 | Update client bootstrap/config application to accept `force_render` only; remove allow gating in `load_initial_settings` | Planned |
| 1.5 | Add/adjust tests for preference-driven force-render and controller override lifecycle | Planned |

### Phase 2: Persistence, Schema, and Documentation Cleanup
- Goal: remove `allow_force_render_release` from preferences, settings files, payloads, and docs.
- APIs/Behavior: `overlay_settings.json` and config payloads no longer include allow flag; ignored if present.
- Invariants: existing user settings continue to load safely; no new release-specific gates.
- Risks: older clients/controllers expect the allow flag; user settings retained with stale keys.
- Mitigations: tolerate unknown keys, update docs/FAQ, add migration to drop key on save.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Remove `allow_force_render_release` from preferences model and persistence (config + shadow JSON) | Planned |
| 2.2 | Update overlay config payload schema and any test fixtures referencing allow flag | Planned |
| 2.3 | Update docs and troubleshooting references to reflect single setting and controller override behavior | Planned |
