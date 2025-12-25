## Goal: Stabilize Timer/Thread Lifecycle Management

## Context from Compliance Review
- Thread/timer lifecycle clarity flagged as **At risk**: timers/threads are spawned in the constructor (`load.py:378-455`) and cleanup relies on manual flags with exceptions swallowed (e.g., `_cancel_config_timers` at `load.py:2884-2891`). Centralize lifecycle management, avoid silent `except`, and add idempotent start/stop tests to catch leaks.

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
| Phase 1 | Centralize lifecycle ownership for timers/threads and add leak-focused tests | Completed |

## Phase Details

### Phase 1: Centralize Timer/Thread Lifecycle and Add Safeguards
- Requirement: preserve existing functionality; lifecycle changes must be behavior-neutral while improving clarity and observability.
- Move thread/timer spins out of `__init__` into explicit start hooks; register all background workers (force-render monitor, prefs worker, version check, rebroadcast timers) in a lifecycle registry.
- Replace silent cleanup paths (e.g., `_cancel_config_timers` swallows exceptions) with logged warnings and test-visible outcomes.
- Add idempotent start/stop coverage to assert no threads/timers remain alive after stop and rebroadcast timers are fully drained.
- Risks: regressions in startup order, missed rebroadcasts while refactoring timer wiring, flakiness in new lifecycle tests.
- Mitigations: stage behind registry with guards on `_running`, add timeouts when joining/canceling, and scope tests to deterministic timers using dependency injection or shorter intervals.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Audit current spawn/cancel sites (`load.py:378-455`, `_cancel_config_timers` and similar) and list owned resources | Completed |
| 1.2 | Introduce lifecycle registry and move thread/timer creation into `start()` with tracked handles | Completed |
| 1.3 | Harden teardown: replace silent catches with logged warnings; add join/cancel timeouts | Completed |
| 1.4 | Add idempotent start/stop tests covering force-render monitor, version check, config/version rebroadcast timers | Completed |
| 1.5 | Validate behavior parity (no missed rebroadcasts, no background leaks) and document rollout steps | Completed |
| 1.6 | Extract lifecycle management out of `load.py` into a dedicated module to shrink the monolith | Completed |

#### Stage 1.1 Plan: Audit current spawn/cancel sites
- **Goal:** produce a complete inventory of background workers and timers with their creation/teardown paths so lifecycle ownership gaps are explicit before moving code.
- **Scope to scan:** `load.py` constructor (`__init__` around 378-455), lifecycle methods (`start`, `stop`), timer helpers (`_schedule_config_rebroadcasts`, `_cancel_config_timers`, `_schedule_version_notice_rebroadcasts`, `_cancel_version_notice_timers`), force-render monitor thread, prefs worker thread, version check thread, controller launch thread/process, watchdog, broadcaster, and legacy TCP server.
- **Deliverables:** table of resources with:
  - creation point (function/line range, gating conditions)
  - shutdown path (function/line, whether join/cancel/terminate is called)
  - current guards (locks/flags) and gaps (silent excepts, untracked handles).
- **Acceptance criteria:** no background resource left unlisted; clear notes on any silent failure paths; identifies where `__init__` currently starts work that should move to `start()`.

#### Stage 1.1 Findings: Background resource inventory

| Resource | Creation (gates) | Shutdown | Guards / Gaps |
| --- | --- | --- | --- |
| Prefs worker thread (`ModernOverlayPrefs`) | `_start_prefs_worker` `load.py:750-756`, invoked unconditionally from `__init__` `load.py:428-429` | `_stop_prefs_worker` `load.py:758-767`, called in `stop` even when `_running` is `False` `load.py:495-524` | Starts before `start()`; join timeout unlogged; queue-full during sentinel enqueue is silently swallowed. |
| Force-render monitor thread (`ModernOverlayForceMonitor`) | `_start_force_render_monitor_if_needed` `load.py:805-835`, invoked from `start` and when the controller runtime override activates | Only `Event` set in `stop` (`_force_monitor_stop.set()` `load.py:522`); no join/handle clear | Starts when controller override is active; relies on override flag flip or event to exit; handle remains. |
| Version status check thread (`ModernOverlayVersionCheck`) | Spawned directly in `__init__` `load.py:444-448`, no handle kept | None (one-shot thread) | Runs even if `start()` bails; untracked/unjoinable. |
| WebSocket broadcaster server | `self.broadcaster.start()` in `start` `load.py:471-484` | `self.broadcaster.stop()` in `stop` `load.py:513` | Lifecycle tied to `_running`; no join/timeout surfaced. |
| Overlay watchdog (spawns overlay client/process) | `_start_watchdog` `load.py:1220-1267` called from `start` `load.py:471-484` after broadcaster starts | `watchdog.stop()` in `stop` `load.py:506-512` with warning on incomplete shutdown | Not started in `__init__`; stop depends on watchdog reporting success; no forced kill/join fallback. |
| Legacy overlay TCP server | `_start_legacy_tcp_server` `load.py:2052-2071` in `start` `load.py:488` | `_stop_legacy_tcp_server` `load.py:2073-2080` in `stop` `load.py:506` | Shutdown exceptions logged at debug and otherwise ignored; thread ownership hidden inside server. |
| Config rebroadcast timers (`_config_timers`) | `_schedule_config_rebroadcasts` `load.py:2849-2874` invoked via `_send_overlay_config` with `rebroadcast=True` (first call in `start` `load.py:490`) | `_cancel_config_timers` `load.py:2883-2891` in `stop` `load.py:504` | Uses set + lock; cancellation exceptions swallowed; timers can be queued even if `start()` later aborts. |
| Version notice rebroadcast timers (`_version_notice_timers`) | `_schedule_version_notice_rebroadcasts` `load.py:642-675` when update notice sent `_maybe_emit_version_update_notice` | `_cancel_version_notice_timers` `load.py:677-682` in `stop` `load.py:504` | Guarded by `_running` and `_version_update_notice_sent`; timers removed under lock; no silent catches. |
| Overlay Controller launch thread | `launch_overlay_controller` spawns `OverlayControllerLaunch` thread `load.py:1731-1740` on user request | No explicit stop; clears handle on completion inside `_overlay_controller_launch_sequence` `load.py:1763-1794`; process stopped separately | Not tied to plugin lifecycle; stop does not join if a launch is mid-flight. |
| Overlay Controller subprocess | Spawned in `_overlay_controller_launch_sequence` `load.py:1741-1905` | `_terminate_controller_process` `load.py:1935-1994` invoked in `stop` `load.py:523-524` | Uses pid file + psutil/os.kill; silent fallbacks if kill fails; no wait for launch thread before termination. |

#### Stage 1.2 Plan: Lifecycle registry and start-only spawns
- **Goal:** move background worker/timer creation out of `__init__` into explicit startup, and register all lifecycle-managed resources in a single registry that stop() can drain deterministically without changing runtime behavior.
- **Design sketch:**
  - Introduce a lightweight registry (e.g., dict/sets) to track threads, timers, and external handles (watchdog, broadcaster, legacy TCP server, controller process).
  - Add helpers to register/unregister and to iterate for teardown with consistent logging/guards.
  - Refactor `__init__` → `start()` to delay starting: prefs worker, force-render monitor, version check thread; ensure registry wiring covers existing start-created resources (broadcaster, watchdog, timers).
  - Keep controller launch thread/process out of start/stop registry for now (user-initiated), but document the seam for later tightening.
- **Sequencing:** first add registry scaffolding and no-op wiring, then move constructor-spawned workers into `start()` behind existing gates, keeping guards on `_running` and preferences identical.
- **Acceptance criteria:** after refactor, `__init__` no longer starts threads/timers; all always-on background resources started in `start()` are registered; stop paths can iterate registry entries without behavior change; logging level unchanged unless silent failures become explicit in Stage 1.3. 

#### Stage 1.2 Notes: Lifecycle registry and start-only spawns
- Added lightweight lifecycle tracking (`_tracked_threads`, `_tracked_handles` with a shared lock) to register background threads/handles as they are created.
- Moved constructor-started workers into `start()`: prefs worker, force-render monitor, and version status check thread now spin up only after the plugin successfully starts.
- Version check now has a tracked thread handle (`_version_check_thread`) to reuse or inspect later; broadcaster/watchdog/legacy TCP server handles are registered when created, and watchdog/legacy server are untracked on stop.
- Behavior remains the same for running instances while preventing background spawns when `start()` exits early (e.g., legacy overlay detected). 

#### Stage 1.3 Plan: Harden teardown (joins/timeouts/logging)
- **Goal:** make shutdown deterministic and observable: every tracked thread/timer/handle is canceled/terminated with bounded waits and any failure is logged (not swallowed) without changing runtime behavior.
- **Targets:** prefs worker, force-render monitor, version notice timers, config rebroadcast timers, broadcaster, watchdog, legacy TCP server, controller process termination; ensure registry can be iterated to assert emptiness after stop.
- **Actions:**
  - Add helpers to join tracked threads with timeouts; cancel timers with warning-level logging on failure; remove silent `except` in `_cancel_config_timers`.
  - Ensure force-render monitor and version check threads are cleared and untracked after completion/stop; consider optional debug metrics on remaining tracked entries post-stop.
  - Keep controller launch thread behavior unchanged but document if not joined; ensure `_terminate_controller_process` logs failures instead of silent `pass`.
  - Wire stop() to walk the registry (without changing order) and emit debug/warn logs when resources remain after attempted shutdown.
- **Acceptance criteria:** stop path leaves no tracked threads/timers/handles behind in the registry under normal conditions; cancellation/join failures are surfaced via logs; runtime behavior (what starts/stops) remains unchanged aside from observability and bounded waits. 

#### Stage 1.3 Notes: Hardened teardown and visibility
- Added join helper and tracked-resource logging so `stop()` now joins the force-render monitor and version-check threads with bounded waits, logging if they linger; prefs worker join now warns on timeout and uses tracking.
- Timers now log failures instead of swallowing exceptions (`_cancel_config_timers`, `_cancel_version_notice_timers`), and controller termination logs failures when signals/psutil termination fall back.
- Handles/threads are untracked on shutdown (watchdog, legacy TCP server, broadcaster, controller process) with a debug snapshot of any stragglers after stop, improving observability without changing normal runtime behavior. 

#### Stage 1.4 Plan: Idempotent start/stop leak tests
- **Goal:** add automated coverage that start→stop (and stop when already stopped) leaves no tracked threads/timers/handles and does not spawn new work on repeated start/stop cycles.
- **Test scope:** `load._PluginRuntime` lifecycle using tracking helpers: prefs worker, force-render monitor, version check thread, config/version timers, watchdog/server/broadcaster handles.
- **Approach:**
  - Fixture to instantiate `_PluginRuntime` with mocked preferences/paths; stub out external side effects (watchdog start, broadcaster start/stop, TCP server) to avoid real I/O.
  - Tests:
    1. `stop()` without `start()` drains workers/timers and leaves registries empty, no exceptions.
    2. `start()` followed by `stop()` leaves `_tracked_threads`/`_tracked_handles` empty and timers cleared.
    3. Repeated `start()` (idempotent when already running) does not double-spawn tracked resources; repeated `stop()` is safe.
    4. Timers scheduled via `_send_overlay_config(rebroadcast=True)` and version notice path are canceled after stop.
  - Use shorter intervals or patched timers to avoid sleeps; assert tracked sets and thread liveness directly.
- **Acceptance criteria:** tests reliably pass without sleeping long; failures point to leaked tracked resources or unintended spawns on repeated start/stop; no reliance on network/UI. 

#### Stage 1.4 Notes: Idempotent lifecycle coverage
- Added `tests/test_lifecycle_tracking.py` with dummy resources and prefs to isolate `_PluginRuntime` start/stop without real I/O or network calls.
- Coverage includes: start→stop drains tracked threads/handles/timers; repeated start/stop cycles remain leak-free; `stop()` without `start()` is safe and leaves only the constructor-created broadcaster handle.
- Timers and threads are patched to non-blocking stubs, giving fast feedback on registry leaks aligned with the new tracking helpers. 

#### Stage 1.5 Plan: Validate behavior parity and rollout steps
- **Goal:** prove lifecycle changes are behavior-neutral: configs/rebroadcasts, version notices, watchdog/broadcaster flows, and controller paths behave as before with no new leaks.
- **Checks to run:**
  - Functional smoke: start plugin in normal mode and confirm overlay config is sent, rebroadcast timers fire once, and stop cancels them; simulate version-update path to ensure notice rebroadcast still occurs.
  - Controller flow: launch controller, then stop plugin to ensure process termination still works and tracking stays empty.
  - Idempotency: repeated start/stop cycles in a live-ish context (not fully mocked) leave no background threads/timers; verify tracked-resource debug logs are empty after stop.
  - Regressions: compare logs to pre-refactor runs (no new warnings aside from intentional teardown visibility).
- **Test commands:** `python -m pytest tests/test_lifecycle_tracking.py` plus targeted integration tests covering controller/override paths (`tests/test_controller_launcher.py`, `tests/test_controller_override_reload.py`) and existing journal/config emission tests if available.
- **Acceptance criteria:** functional parity observed (no missed messages/rebroadcasts), tracked resources empty after stop in real start/stop flow, and only expected teardown warnings appear; document observed logs and any deviations for rollout. 

#### Stage 1.5 Notes: Behavior parity validation
- Setup: created local venv (`python3 -m venv .venv`) and installed pytest 8.3.3 locally to run checks.
- Tests run: `.venv/bin/python -m pytest tests/test_lifecycle_tracking.py tests/test_controller_launcher.py tests/test_controller_override_reload.py` (all passed). Lifecycle tracking asserts no leaked threads/handles/timers after start→stop cycles; controller launcher/override paths still behave as expected.
- Observations: teardown warnings remain limited to intentional visibility; tracked resources empty after stop in the exercised flows. Broader journal/config emission smoke still advised during next manual run. 

#### Stage 1.6 Plan: Extract lifecycle management from `load.py`
- **Goal:** move lifecycle tracking/helpers (registry, join/cancel helpers, start/stop wiring) into a dedicated module to reduce `load.py` size and improve reuse/testability, without changing behavior.
- **Target shape:** new module (e.g., `overlay_plugin/lifecycle.py`) housing tracking primitives and lifecycle helper class; `load.py` imports and composes it; public surface kept narrow.
- **Approach:**
  - Identify the lifecycle-specific methods/fields in `load.py` (tracking sets/locks, _track/_untrack, _join_thread, timer cancel helpers) and lift them intact into the new module with minimal signature changes.
  - Keep `_PluginRuntime` API stable; refactor to delegate to the lifecycle helper while preserving ordering/guards; update tests to import from new module only if needed.
  - Ensure new module has its own unit tests for tracking/join/cancel helpers; adjust existing lifecycle tests to run against the refactored wiring.
- **Acceptance criteria:** no behavior change; `load.py` shrinks its lifecycle concerns to delegation; all lifecycle tests pass; start/stop still empty the tracked resources; controller and rebroadcast flows unaffected. 

#### Stage 1.6 Notes: Lifecycle extraction
- Added `overlay_plugin/lifecycle.py` with `LifecycleTracker` to own tracking sets, joins, and logging helpers; `_PluginRuntime` now delegates to it while keeping wrapper methods for compatibility.
- `load.py` shrinks lifecycle state to the tracker (threads/handles sets still exposed for tests); start/stop wiring unchanged in behavior.
- Tests run in venv: `.venv/bin/python -m pytest tests/test_lifecycle_tracking.py tests/test_controller_launcher.py tests/test_controller_override_reload.py` (pass), confirming lifecycle logic still leak-free and controller paths intact after extraction. 
