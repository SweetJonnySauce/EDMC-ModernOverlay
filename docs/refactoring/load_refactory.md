## Goal: Break up the Monolith (load.py extraction)

## Context: EDMC load.py contract (must not break)
- EDMC discovers plugins via the top-level `load.py` and calls `plugin_start3(plugin_dir) -> str`, `plugin_stop() -> None`, and `plugin_app(parent) -> Optional[Any]`. These hooks and their signatures/return types must remain unchanged.
- `plugin_start3` must return the plugin name string and must be safe to call once; repeated calls should remain idempotent.
- `plugin_stop` must be safe to call even if start failed or the plugin isn’t running; it must not raise in normal shutdown.
- `plugin_app` is a Tk hook; behavior/signature must stay intact (even if it returns `None`).
- EDMC imports `load.py` at plugin load: side effects must remain minimal and compatible with EDMC’s expectations (no blocking I/O, no GUI/timers at import time).

## Refactorer Persona
- Bias toward carving out modules aggressively while guarding behavior: no feature changes, no silent regressions.
- Prefer pure/push-down seams, explicit interfaces, and fast feedback loops (tests + dev-mode toggles) before deleting code from the monolith.
- Treat risky edges (I/O, timers, sockets, UI focus) as contract-driven: write down invariants, probe with tests, and keep escape hatches to revert quickly.
- Default to “lift then prove” refactors: move code intact behind an API, add coverage, then trim/reshape once behavior is anchored.
- Resolve the “be aggressive” vs. “keep changes small” tension by staging extractions: lift intact, add tests, then slim in follow-ups so each step stays behavior-scoped and reversible.
- Track progress with per-phase tables of stages (stage #, description, status). Mark each stage as completed when done; when all stages in a phase are complete, flip the phase status to “Completed.”
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

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| Phase 1 | Identify seams and extract lifecycle/logging helpers already stabilized | Completed |
| Phase 2 | Extract watcher/broadcaster/controller concerns into dedicated modules | Completed |
| Phase 3 | Simplify EDMC hook surface and finalize contracts/tests | Completed |
| Phase 4 | Extract config/version broadcast helpers and remaining runtime seams | Planned |
| Phase 5 | (Optional) Split prefs/state/journal responsibilities into focused modules | Planned |

## Phase Details

### Phase 1: Identify seams and extract lifecycle/logging helpers (contract intact)
- Goal: carve out already-stabilized lifecycle/logging helpers from `load.py` to reduce surface area without changing behavior or EDMC hook contracts.
- Scope: lifecycle tracker/logging helpers, start/stop orchestration seams; no change to EDMC hook signatures/semantics.
- Risks: import-order regressions, missing hook wiring, accidental start/stop behavior drift.
- Mitigations: keep EDMC hook contract front and center (signatures unchanged), rely on existing lifecycle tests and `make check`, and perform small, reversible moves.
- EDMC contract guardrails: preserve `plugin_start3`/`plugin_stop`/`plugin_app` signatures and return types; keep import-time side effects minimal; maintain idempotent start/stop semantics.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Map current lifecycle/logging seams in `load.py` and note dependencies on EDMC hooks | Completed |
| 1.2 | Extract lifecycle/logging helpers into dedicated modules with delegated calls | Completed |
| 1.3 | Update/extend tests to cover delegated helpers and hook wiring; run `make check` | Completed |

### Phase 2: Extract watcher/broadcaster/controller concerns
- Goal: move overlay watchdog, broadcaster plumbing, and controller launch/termination orchestration out of `load.py` into focused modules/services, keeping EDMC hooks and runtime behavior intact.
- Risks: startup ordering changes, controller lifecycle regressions, port/log file handling drift.
- Mitigations: stage extractions with intact behavior, reuse lifecycle tracking, and run full test suite after each step.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Map watcher/broadcaster/controller seams and their interactions with EDMC hooks | Completed |
| 2.2 | Extract broadcaster/watchdog orchestration into dedicated module(s) with delegated calls | Completed |
| 2.3 | Extract controller launch/termination orchestration into a dedicated module/service | Completed |
| 2.4 | Update tests (and add new ones if needed) to cover delegated flows; run `make check` | Completed |

#### Stage 2.1 Plan: Map watcher/broadcaster/controller seams
- Goal: inventory how watchdog, broadcaster, and controller launch/termination flow through `load.py`, including EDMC hook touch points, to guide extraction.
- Scope to scan:
  - Broadcaster lifecycle: construction, `start()`/`stop()`, port file write/delete, publisher registration, and any error handling.
  - Watchdog: `_start_watchdog`, stop path in `stop`/restart, environment setup, capture handling.
  - Controller orchestration: launch thread/process, pid file handling, termination (`_terminate_controller_process`), status messaging.
  - EDMC hook integration: where `plugin_start3`/`plugin_stop` call these seams.
- Deliverables:
  - Table/bullets noting creation/teardown sites (line ranges), gating flags, side effects (files, env), and dependencies between components.
  - Notes on import-time vs runtime side effects to keep import light.
- Acceptance criteria: complete map of watcher/broadcaster/controller seams with EDMC hook dependencies, ready to drive Stage 2.2/2.3 extraction. 

#### Stage 2.1 Findings: watcher/broadcaster/controller seams
- **Broadcaster:**
  - Constructed in `_PluginRuntime.__init__` (load.py:379-381), tracked via lifecycle; started in `start()` (load.py:471-484) before watchdog; writes `port.json` (`_write_port_file`) and registers publisher; stopped in `stop()` (load.py:521-523) with port file deletion and handle untracking. No threads started at import.
  - Dependencies: EDMC hook `plugin_start3`→`start()` wires publisher; `_publish_payload` used by journal/external handlers.
- **Watchdog (overlay client process manager):**
  - Started in `start()` after broadcaster (load.py:471-484) via `_start_watchdog` (load.py:1264-1305). Builds env, locates overlay client Python, logs context, creates `OverlayWatchdog`, tracks handle, starts process.
  - Stopped in `stop()` (load.py:515-520) with warning if incomplete; untracked; restart path via `restart_overlay_client` (load.py:2045-2060).
  - Dependencies: capture settings, platform context, preferences; uses `_build_overlay_environment` and capture toggles.
- **Legacy TCP server:**
  - Started in `start()` (load.py:496-498) via `_start_legacy_tcp_server` (load.py:2113-2124); tracked handle; stopped in `stop()` (load.py:514-515) via `_stop_legacy_tcp_server` (load.py:2126-2135) with debug-only error logging.
- **Controller launch/termination:**
  - Launch: `launch_overlay_controller` spawns thread (load.py:1816-1829) running `_overlay_controller_launch_sequence` (load.py:1849-1903) which resolves env, counts down, spawns subprocess, stores handle, tracks process. Emits active notice and waits for process completion; cleans handle on exit.
  - Termination: `_terminate_controller_process` (load.py:1985-2030) invoked in `stop()` (load.py:533) and restart path; reads PID file fallback; uses psutil/os.kill; cleans PID file and untracks handle.
  - Dependencies: controller pid file paths, capture settings, `_controller_launch_lock` for thread/process coordination.
- **Hook integration:**
  - `plugin_start3` constructs runtime, calls `start()`, triggering broadcaster→watchdog→legacy server→controller helper setup.
  - `plugin_stop` calls `stop()`, which tears down broadcaster/watchdog/legacy server/controller process and cancels timers.
- **Side effects:**
  - Files: `port.json` write/delete; controller pid file cleanup; log handler for controller handled in overlay_controller module (already hardened).
  - Import-time side effects: none from these seams beyond construction; runtime only after `start()`.

#### Stage 2.2 Plan: Extract broadcaster/watchdog orchestration
- Goal: move broadcaster startup/teardown and watchdog management (including port file write/delete) into a dedicated module/service while keeping `start()`/`stop()` behavior and EDMC hooks unchanged.
- Targets:
  - Broadcaster lifecycle: construction, start/stop, publisher registration, port file write/delete.
  - Watchdog lifecycle: `_start_watchdog`, restart flow, stop handling, capture/env wiring.
- Approach:
  - Introduce a helper (e.g., `overlay_plugin/runtime_services.py`) to own broadcaster+watchdog orchestration behind a clear API used by `_PluginRuntime`.
  - Keep sequencing identical (broadcaster before watchdog; teardown order preserved).
  - Maintain lifecycle tracking and port file semantics; avoid import-time side effects.
- Tests:
  - Existing lifecycle tests plus targeted start/stop smoke; ensure `make check` stays green.
  - Optional new unit tests for helper if behavior can be validated without real processes.
- Acceptance criteria: broadcaster/watchdog orchestration delegated with no behavior change; EDMC hooks intact; full test suite passes. 

#### Stage 2.2 Notes: Broadcaster/watchdog delegation
- Added `overlay_plugin/runtime_services.py` with `start_runtime_services`/`stop_runtime_services` to encapsulate broadcaster + watchdog start/stop and port file handling; `load.py` now delegates while keeping sequencing and hook behavior intact.
- Lifecycle tracking preserved via untrack callbacks; port file write/delete unchanged.
- Tests: targeted lifecycle/controller tests and full `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` all pass after delegation. 

#### Stage 2.3 Plan: Extract controller launch/termination orchestration
- Goal: move controller launch thread/process handling (env resolution, countdown, spawn, pid file, termination) out of `load.py` into a focused module/service, preserving behavior and EDMC hook semantics.
- Scope/targets:
  - `launch_overlay_controller`, `_overlay_controller_launch_sequence`, `_terminate_controller_process`, pid file helpers, controller status messaging.
  - Keep `_controller_launch_lock`, process handle tracking, and capture/environment wiring intact.
- Approach:
  - Introduce a controller orchestration helper module that `_PluginRuntime` delegates to; keep public/runtime-facing methods and locks stable.
  - Preserve sequencing and logging; avoid import-time side effects.
- Tests:
  - Existing controller launcher/override tests; rerun `make check` with PYQT_TESTS=1 after delegation.
  - Optional new unit tests for helper if feasible without spawning real processes.
- Acceptance criteria: controller orchestration delegated with no behavior change; EDMC hooks intact; full test suite passes. 

#### Stage 2.3 Notes: Controller orchestration delegation
- Added `overlay_plugin/controller_services.py` with helpers for controller launch and termination; `load.py` delegates `launch_overlay_controller`, launch sequence, and termination while retaining locks, messaging, and lifecycle tracking.
- Behavior preserved (pid file handling, capture/env wiring, logging); EDMC hooks unchanged.
- Tests: targeted lifecycle/controller tests and full `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` all pass post-delegation. 

#### Stage 2.4 Plan: Test updates and regression guardrails
- Goal: ensure delegated broadcaster/watchdog/controller flows stay covered and EDMC hooks remain intact after extractions.
- Actions:
  - Review existing tests (lifecycle tracking, controller launcher/override, make check) and add focused unit tests for `runtime_services` and `controller_services` if gaps exist (e.g., sequencing/port file behavior, pid file handling).
  - Add a minimal smoke for `plugin_start3`/`plugin_stop` with a stubbed runtime to assert hook contract stability post-delegation.
  - Run full `make check` (ruff/mypy/pytest with PYQT_TESTS=1) after any new tests to confirm parity.
- Acceptance criteria: delegation-specific tests exist or are deemed unnecessary with rationale; EDMC hook contract confirmed; full check passes. 

#### Stage 2.4 Notes: Delegation test coverage
- Added targeted unit tests for new helpers: `tests/test_runtime_services.py` (broadcaster/watchdog sequencing, port file handling) and `tests/test_controller_services.py` (controller launch/termination flow and tracking).
- Existing lifecycle/controller tests still pass; full `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` (ruff, mypy, full pytest) passes, confirming hook contract and delegated flows are covered. 

### Phase 3: Simplify EDMC hook surface and finalize contracts/tests
- Goal: keep `load.py` as a thin EDMC adapter by further reducing in-file logic, validating contracts, and documenting the final structure.
- Risks: hook signature/behavior drift, import-time side effects introduced, gaps in end-to-end coverage.
- Mitigations: preserve hook signatures, keep import-time work minimal, rely on existing/lifecycle tests and add a lightweight hook smoke test.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Audit EDMC hook surfaces and remaining `load.py` responsibilities post-extraction | Completed |
| 3.2 | Refine/annotate hook adapters (plugin_start3/stop/app) and ensure import-time minimalism | Completed |
| 3.3 | Add/adjust hook-level tests or smokes; run `make check` and document final contracts | Completed |

#### Stage 3.1 Plan: Audit EDMC hook surfaces and remaining load.py responsibilities
- Goal: catalog what remains in `load.py` after extractions, focusing on EDMC hook adapters and any logic still embedded there.
- Scope:
  - Hook functions: `plugin_start3`, `plugin_stop`, `plugin_app` (signatures, side effects, idempotency).
  - Remaining in-file responsibilities: state/init logic, payload config emissions, journal handlers, any lingering orchestration not yet delegated.
  - Import-time work: confirm minimal side effects (no threads/timers/UI at import).
- Deliverables:
  - Bulleted inventory of remaining responsibilities with file/line references and notes on whether they should stay or be candidates for future delegation.
  - Explicit confirmation of hook contracts and guards (idempotency, error handling).
- Acceptance criteria: complete map of remaining `load.py` duties aligned to EDMC hooks, ready to inform Stage 3.2 refinements. 

#### Stage 3.1 Findings: Remaining load.py responsibilities and EDMC hooks
- **EDMC hooks (unchanged signatures):**
  - `plugin_start3(plugin_dir) -> str` (load.py:2927-2932): constructs `Preferences`, `_PluginRuntime`, calls `start()`, returns plugin name; idempotent via `_running` guard.
  - `plugin_stop() -> None` (load.py:2934-2941): calls `_plugin.stop()` if present; safe when not running.
  - `plugin_app(parent)` (load.py:2944-2950): Tk hook returning prefs panel; untouched.
- **Import-time side effects:** module imports/constants, logger setup, payload logger init if missing, force-render reset; no threads/timers/UI started at import.
- **Remaining in-file responsibilities (post delegation):**
  - `_PluginRuntime` state/init: preferences/state tracking, payload dev config load, trace flags, platform context detection.
  - Payload logging config (delegated handler creation), log retention overrides.
  - Lifecycle tracking integration (delegated to `LifecycleTracker` but wiring lives here).
  - Payload config send/rebroadcast helpers (`_send_overlay_config`, `_schedule_config_rebroadcasts`, `_cancel_config_timers`).
  - Journal handling/state updates and external publish path (`handle_journal`, `_publish_external`).
  - Version status handling and notice rebroadcast timers.
  - Force-render monitor logic, prefs worker queue/worker.
  - Legacy overlay detection guard on start.
  - Delegated services wiring: broadcaster/watchdog (`runtime_services`), controller launch/termination (`controller_services`); hooks remain here.
  - Legacy TCP server start/stop.
  - Misc helpers: overlay metrics update, payload filtering, preference setters, controller command helper setup.
- **Candidates to keep vs. future delegation:**
  - Keep: EDMC hook adapters, preference/stateful helpers closely tied to runtime, journal handling (EDMC-specific).
  - Potential future delegation (if shrinking further): payload config broadcast/rebroadcast helpers, version notice scheduler, journal command helper wiring.
- **Contract checks:** hooks still minimal and idempotent; start/stop sequencing now delegated but invoked from hooks; import remains light. 

#### Stage 3.2 Plan: Refine hook adapters and import-time minimalism
- Goal: keep `load.py`’s EDMC hook surface thin and explicit, and confirm import-time work is minimal and documented.
- Actions:
  - Review `plugin_start3`/`plugin_stop`/`plugin_app` and ensure they are thin adapters with clear docstrings/comments about contracts.
  - Trim any residual non-hook logic from the hook section (move helpers below or into modules if needed); ensure no timers/threads/UI start at import.
  - Add brief inline notes on import-time expectations if helpful for maintainers.
- Acceptance criteria: hooks remain minimal and documented; import-time side effects confirmed minimal; no behavior change; ready for Stage 3.3 tests/smokes. 

#### Stage 3.2 Notes: Hook refinement
- Added docstrings to EDMC hook adapters (`plugin_start3`, `plugin_stop`, `plugin_app`) clarifying contracts and intent; hooks remain thin and unchanged in behavior.
- Import-time work remains minimal (no threads/timers/UI); no additional logic moved into hooks. 

#### Stage 3.3 Plan: Hook-level smokes and contract documentation
- Goal: validate hook contracts end-to-end and document the finalized `load.py` surface.
- Actions:
  - Add a lightweight smoke test that imports `load`, invokes `plugin_start3`/`plugin_stop` with a temp plugin_dir (stubbed prefs/runtime as needed), and asserts idempotency/no exceptions.
  - Ensure existing lifecycle/controller tests remain green; rerun `make check` with PYQT_TESTS=1.
  - Summarize the final hook contract and module layout in the refactor doc for maintainer reference.
- Acceptance criteria: hook smoke in place (or rationale if skipped), full check passes, and contract documentation updated. 

#### Stage 3.3 Notes: Hook smokes and contracts
- Added `tests/test_plugin_hooks.py` to smoke `plugin_start3`/`plugin_stop` with stubbed `Preferences`/`_PluginRuntime`, asserting idempotent start/stop behavior without side effects.
- Full `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` passes after adding the smoke, confirming hooks remain intact. Hook contracts documented via docstrings and this refactor plan. 

### Phase 4: Extract config/version broadcast helpers and remaining runtime seams
- Goal: move config rebroadcast/version notice scheduling and related payload helpers out of `load.py` to continue shrinking the monolith.
- Risks: changing timing/order of rebroadcasts/version notices; accidental behavior drift in payload publishing.
- Mitigations: lift helpers intact first, preserve sequencing/guards, and cover with targeted tests around rebroadcast/version notice behavior.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Identify config/version helper seams and their guards/timers | Planned |
| 4.2 | Extract config rebroadcast/version notice helpers into dedicated module(s) | Planned |
| 4.3 | Add/adjust tests for rebroadcast/version notice behavior; run `make check` | Planned |

### Phase 5: (Optional) Split prefs/state/journal responsibilities into focused modules
- Goal: further reduce `load.py` by splitting preference/state/journal handling into focused modules while keeping EDMC hooks stable.
- Risks: regression in journal handling, state updates, or preference persistence.
- Mitigations: stage extractions with existing tests, add smokes for journal/state updates if needed.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Map prefs/state/journal responsibilities and dependencies | Planned |
| 5.2 | Extract targeted subsets (e.g., journal handlers/state updates) into modules | Planned |
| 5.3 | Validate with existing tests and added smokes; run `make check` | Planned |

#### Stage 1.1 Plan: Map lifecycle/logging seams and EDMC hook dependencies
- Goal: produce a clear inventory of lifecycle and logging helpers in `load.py`, how they interact with `plugin_start3`/`plugin_stop`/`plugin_app`, and what dependencies/gates they have.
- Inventory targets:
  - EDMC hooks: `plugin_start3`, `plugin_stop`, `plugin_app` and how they call into `_PluginRuntime`.
  - Lifecycle/logging helpers: lifecycle tracker delegation, start/stop orchestration, payload logger configuration, version notice/config rebroadcast timers.
  - Remaining start/stop side effects: broadcaster/watchdog/legacy TCP server registration, controller process termination.
- Deliverables:
  - Table or bullet list noting function locations (line ranges), creation/teardown points, and hook dependencies.
  - Notes on import-time side effects that must remain (e.g., logger init) vs. what can be moved.
- Acceptance criteria: every lifecycle/logging seam in `load.py` is listed with its hook touch points and gating conditions; EDMC hook contract dependencies are explicit for use in Stage 1.2 extraction. 

#### Stage 1.1 Findings: lifecycle/logging seam inventory
- **EDMC hooks & contract:**
  - `plugin_start3(plugin_dir) -> str` (load.py:2901-2906): constructs `_PluginRuntime` and calls `start()`. Idempotent on repeated calls (returns name if already running).
  - `plugin_stop() -> None` (load.py:2909-2914): calls `_plugin.stop()` if present; safe when not running.
  - `plugin_app(parent)` (below 2914): Tk hook, returns panel; unchanged.
  - Import-time side effects: logger setup/constants/imports; no threads/timers started at import post-refactor.
- **Lifecycle tracker & logging helpers:**
  - Lifecycle tracking via `LifecycleTracker` (init: load.py:401-408) with wrapper methods `_track_thread/_track_handle/_join_thread/_log_state` (load.py:766-801 delegates). Tracked sets exposed for tests.
  - Payload logger config `_configure_payload_logger` (load.py:730-764) runs during init if handler missing; import-safe.
- **Start orchestration (load.py:462-500):**
  - Guards: `_running` flag, `_legacy_overlay_active` early abort.
  - Starts broadcaster, writes port file, starts watchdog; sets `_running=True`.
  - After running: starts prefs worker, force-render monitor, version status check; registers publisher; starts legacy TCP server; sends overlay config (rebroadcast timers); maybe emit version notice.
- **Stop orchestration (load.py:503-539):**
  - Guards `_running`; stops prefs worker even if not running.
  - Cancels config/version notice timers; stops legacy TCP server; stops watchdog; stops broadcaster; deletes port file; tears down payload log handler; signals force monitor stop; terminates controller process; joins monitor/version check threads; logs tracked state.
- **Timers:**
  - Config rebroadcast timers (`_schedule_config_rebroadcasts`, `_cancel_config_timers` load.py:2902-2921/2923-2929) with logging on cancel failures.
  - Version notice timers (`_schedule_version_notice_rebroadcasts`, `_cancel_version_notice_timers` load.py:642-682) keyed off `_running`/notice sent.
- **Logging-related helpers:**
  - Payload logging setup (`_configure_payload_logger`), log retention, payload logging enablement via debug config.
  - Controller logger handled in overlay_controller module; not part of `load.py` seams.
- **Start/stop side effects & dependencies:**
  - Watchdog start/stop (`_start_watchdog` load.py:1213-1265, stop in `stop`).
  - Legacy TCP server start/stop (`_start_legacy_tcp_server` load.py:2097-2113, `_stop_legacy_tcp_server` load.py:2115-2125).
  - Controller process termination `_terminate_controller_process` (load.py:2007-2049) invoked during stop.
  - Payload config broadcast/rebroadcast from `_send_overlay_config` (load.py:2389-2426) invoked in start and on pref changes.
- **Import-time vs runtime side effects:**
  - Import: definitions, logger setup, payload logger config if handler missing, force-render reset; no timers/threads started.
  - Runtime (start/stop): all background threads/timers spawned via `start()`, torn down via `stop()`.

#### Stage 1.2 Plan: Extract lifecycle/logging helpers with delegation
- Goal: move lifecycle tracking and logging helpers out of `load.py` into focused modules while keeping EDMC hook behavior identical.
- Targets to lift:
  - Lifecycle tracking wrappers (`_track_*`, `_join_thread`, `_log_state`), timer cancel helpers, and payload logger configuration utilities.
  - Any pure/logging helpers that can live alongside `LifecycleTracker` (e.g., payload logger builder) without touching EDMC hooks.
- Approach:
  - Introduce/extend dedicated modules (e.g., `overlay_plugin/lifecycle.py`, `overlay_plugin/logging_utils.py`) to house extracted helpers.
  - Keep `_PluginRuntime` delegating to extracted helpers; preserve signatures/ordering in `start`/`stop`.
  - Avoid moving EDMC hooks; imports stay lightweight (no new side effects at import).
- Tests to run: existing lifecycle/idempotency tests, controller/tests already in `make check`; add/adjust unit tests if new helper surfaces appear.
- Acceptance criteria: `load.py` shrinks (helpers delegated), EDMC hook contract intact, and `make check` still passes. 

#### Stage 1.2 Notes: Delegated lifecycle/logging helpers
- Added `overlay_plugin/logging_utils.py` with a shared rotating handler builder and delegated `_configure_payload_logger` to it; lifecycle tracking already delegated to `LifecycleTracker`.
- `load.py` keeps behavior/ordering intact while offloading handler creation; EDMC hook surface unchanged.
- Tests: `.venv/bin/python -m pytest tests/test_lifecycle_tracking.py tests/test_controller_launcher.py tests/test_controller_override_reload.py` and full `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` (ruff, mypy, full pytest) all pass. 

#### Stage 1.3 Plan: Tests and hook wiring validation
- Goal: ensure all delegation still satisfies EDMC hook contract and lifecycle/logging behaviors via targeted tests and doc updates.
- Actions:
  - Add/adjust tests to cover delegated helpers in `overlay_plugin/logging_utils` and lifecycle tracker wiring from `_PluginRuntime` start/stop.
  - Verify EDMC hook signatures/behavior (plugin_start3/stop/app) remain intact via smoke tests or harness.
  - Run `make check` (ruff/mypy/full pytest with PYQT_TESTS=1) to confirm no regressions.
- Acceptance criteria: new/updated tests in place where needed; EDMC hook contract documented as unchanged; full check passes. 

#### Stage 1.3 Notes: Hook validation and tests
- Delegated payload handler creation to `overlay_plugin/logging_utils` while keeping `_configure_payload_logger` behavior; lifecycle tracker delegation already covered by existing tests.
- EDMC hooks unchanged; runtime start/stop semantics verified via lifecycle tracking tests.
- Validation: `PYQT_TESTS=1 PATH=.venv/bin:$PATH make check` (ruff, mypy, full pytest) completed successfully. 
