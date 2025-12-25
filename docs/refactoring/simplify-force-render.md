## Goal: Simplify how we force rendering

## Requirements (Behavior)
- When "Keep overlay visible" is checked, the overlays must render even when the game is not focused (no release gating).
- When the controller is active (controller mode), the overlays must render even when the game is not focused, even if the user has disabled "Keep overlay visible."
- Controller force-render is runtime-only (no persistence across restarts).
- Drop `allow_force_render_release` entirely (no config key, no persistence).

## Current Behavior (Single Preference + Controller Override)

### Definitions
- `force_render`: keeps the overlay visible even when Elite is not the foreground window.
- controller override: runtime-only force-render flag set while the controller is active.

### Key Enforcement Points
- Effective force-render is computed in `_PluginRuntime._resolve_force_render()` as `force_render || controller_override_active`.
- Controller mode toggles the override via `force_render_override` CLI payloads (`force_render: true/false`); no persistence is written.
- The force-render monitor thread clears the runtime override when the controller is no longer detected and rebroadcasts config.
- The overlay client bootstraps its initial state from `overlay_settings.json` in `overlay_client/client_config.py::load_initial_settings()`, using only `force_render`.
- "Keep overlay visible" lives in the main preferences section and is honored in all builds when the preference is set.

### Client Visibility Behavior
- The client decides visibility with `force_render or (state.is_visible and state.is_foreground)` in `overlay_client/window_controller.py::post_process_follow_state()`.
- When `force_render` flips, `overlay_client/control_surface.py::set_force_render()` updates visibility immediately and re-applies follow state (including drag/interaction behavior on Linux).

## Runtime Flow: Dev Build

1) Preferences load
- `Preferences.__post_init__()` (`overlay_plugin/preferences.py`) loads config or `overlay_settings.json`; there is no release gating.
- The "Keep overlay visible" checkbox is available in the main preferences UI and honored regardless of build.

2) Initial client bootstrap
- The client reads `overlay_settings.json` via `load_initial_settings()` (`overlay_client/client_config.py`) and applies `force_render` directly.

3) Overlay config broadcast
- The plugin sends the overlay config using `_resolve_force_render()` (`load.py`), so the client receives `force_render` OR controller override state.
- The client calls `set_force_render()` and `post_process_follow_state()` to apply visibility behavior.

4) Controller override path (optional)
- Opening the controller calls `ForceRenderOverrideManager.activate()` (`overlay_controller/services/plugin_bridge.py`), which sends `force_render_override` with `force_render=true`.
- The plugin sets the runtime override, starts `_start_force_render_monitor_if_needed()`, and rebroadcasts config.
- When the controller exits or is no longer detected, the monitor clears the override and rebroadcasts.

## Runtime Flow: Release Build

1) Preferences load
- `Preferences.__post_init__()` loads settings; there is no release-specific gating.
- The "Keep overlay visible" control is shown in the main preferences UI and the stored preference is honored.

2) Initial client bootstrap
- `load_initial_settings()` reads `overlay_settings.json` and applies `force_render` directly.

3) Config updates and preference changes
- `_resolve_force_render()` returns `force_render || controller_override_active`.
- `set_force_render_preference()` updates `force_render` without gating and triggers an overlay config broadcast.

4) Controller override path (runtime-only)
- When the controller opens, it sends `force_render_override` with `force_render=true`; when it closes, it sends `force_render=false`.
- The plugin applies the runtime override without persisting any settings and clears the override when the controller is no longer detected.

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
| 1 | Define single force-render policy, remove release gating, and introduce runtime-only controller override | Completed |
| 2 | Clean up persistence/schema/tests/docs for removed `allow_force_render_release` | Completed |

## Phase Details

### Phase 1: Single Force-Render Policy + Controller Runtime Override
- Goal: enforce one source of truth for force-render (the preference) plus a runtime-only controller override; remove release gating logic.
- APIs/Behavior: effective force-render = `force_render_preference || controller_override_active`.
- Invariants: "Keep overlay visible" is available in the main UI; controller mode always forces render; controller override does not persist.
- Risks: regressions in visibility when Elite is unfocused; loss of controller override restoration; stale settings in `overlay_settings.json`.
- Mitigations: add targeted tests for controller override lifecycle and client visibility; keep settings migration and backward-compatible read (ignore old key).

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Identify all references to `allow_force_render_release` and release gating; document the new effective-force-render rule | Completed |
| 1.2 | Update plugin runtime to compute effective force-render without release gating; wire controller override as runtime-only | Completed |
| 1.3 | Update controller override manager to avoid writing persistence flags; ensure activation/deactivation only affects runtime state | Completed |
| 1.4 | Update client bootstrap/config application to accept `force_render` only; remove allow gating in `load_initial_settings` | Completed |
| 1.5 | Add/adjust tests for preference-driven force-render and controller override lifecycle | Completed |

### Phase 1 Results
- Stage 1.1: Completed; removed release gating references and documented the new effective-force-render rule.
- Stage 1.2: Completed; runtime now computes force-render via `_resolve_force_render()` with a controller override flag.
- Stage 1.3: Completed; controller override now uses socket-only runtime toggles with no persistence fallback.
- Stage 1.4: Completed; client bootstrap applies `force_render` directly without allow gating.
- Stage 1.5: Completed; tests updated for new override behavior and runtime flag.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py`, `.venv/bin/python -m pytest overlay_controller/tests/test_plugin_bridge.py tests/test_overlay_controller_platform.py tests/test_lifecycle_tracking.py tests/test_overlay_config_payload.py`, `.venv/bin/python -m pytest tests/test_overlay_config_payload.py`.
- Issues: overlay config tests initially failed due to missing `_controller_force_render_override` on stub runtimes; fixed by defaulting in `_resolve_force_render()`.
- Follow-ups: none.

### Phase 2: Persistence, Schema, and Documentation Cleanup
- Goal: remove `allow_force_render_release` from preferences, settings files, payloads, and docs.
- APIs/Behavior: `overlay_settings.json` and config payloads no longer include allow flag; ignored if present.
- Invariants: existing user settings continue to load safely; no new release-specific gates.
- Risks: older clients/controllers expect the allow flag; user settings retained with stale keys.
- Mitigations: tolerate unknown keys, update docs/FAQ, add migration to drop key on save.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Remove `allow_force_render_release` from preferences model and persistence (config + shadow JSON) | Completed |
| 2.2 | Update overlay config payload schema and any test fixtures referencing allow flag | Completed |
| 2.3 | Update docs and troubleshooting references to reflect single setting and controller override behavior | Completed |

### Phase 2 Results
- Stage 2.1: Completed; dropped `allow_force_render_release` from preferences, config persistence, and `overlay_settings.json`.
- Stage 2.2: Completed; updated override payloads and test fixtures to remove allow gating.
- Stage 2.3: Completed; updated refactor and troubleshooting docs to reflect single-setting + runtime override behavior.
- Tests: see Phase 1 results (no additional runs specific to Phase 2).
