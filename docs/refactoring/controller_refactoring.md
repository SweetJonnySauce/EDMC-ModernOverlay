## Goal: Break up the Overlay Controller Monolith

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
- Avoid Qt/UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.

## Per-Iteration Test Plan
- **Env setup (once per machine):** `python3 -m venv overlay_client/.venv && source overlay_client/.venv/bin/activate && pip install -U pip && pip install -e .[dev]`
- **Headless quick pass (default for each step):** `source overlay_client/.venv/bin/activate && python -m pytest overlay_controller/tests` (or `python tests/configure_pytest_environment.py overlay_controller/tests`).
- **Core project checks:** `make check` (lint/typecheck/pytest defaults) and `make test` (project test target) from repo root.
- **Full suite with PyQt (run before risky merges):** ensure PyQt6 is installed, then `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` (PyQt-only tests auto-skip without the env var).
- **Targeted filters:** use `-k` to scope to touched areas; document skips (e.g., resolution tests) with reasons.
- **After wiring changes:** rerun headless controller tests plus the full PyQt suite once per milestone to catch viewport/render regressions.

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

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Extract group/config state management into a service with a narrow API; keep Tk shell unaware of JSON/cache details. | Not started |
| 2 | Isolate plugin bridge + mode/heartbeat timers into dedicated helpers to decouple sockets and scheduling from UI. | Not started |
| 3 | Move preview math/rendering into a pure helper and a canvas renderer class so visuals are testable without UI clutter. | Not started |
| 4 | Split reusable widgets (idPrefix, offset, absolute XY, anchor, justification, tips) into `widgets/` modules. | Not started |
| 5 | Slim `OverlayConfigApp` to orchestration only; wire services together; add/adjust tests for new seams. | Not started |

## Phase Details

### Phase 1: Group/Config State Service
- Extract `_GroupSnapshot` build logic, cache loading/diffing, merged groupings access, and config writes into `services/group_state.py`.
- Expose methods like `load_options()`, `select_group()`, `snapshot(selection)`, `persist_offsets/anchor/justification()`, and `refresh_from_disk()`.
- Keep debounce/write strategy and user/shipped diffing inside the service; UI calls it instead of touching JSON files directly.
- Preserve option filtering and reload behavior: idPrefix options only include groups present in the cache, and groupings reloads are delayed briefly after edits to avoid half-written files.
- Keep optimistic edit flow: offsets/anchors update snapshots immediately, stamp an edit nonce, and invalidate cache entries to avoid HUD snap-back while the client rewrites transforms.
- Snapshot math still synthesizes transforms from base + offsets (ignoring cached transforms) so previews and HUD stay aligned during edits.
- Risks: cache/user file churn; hidden behavior drift in snapshot synthesis.
- Mitigations: lift code intact first, add unit tests around load/filter/snapshot/write/invalidate, and keep a toggle to fall back to in-file logic until coverage is green.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Baseline current behavior: note cache/filter invariants, edit nonce handling, debounce timings, and which tests cover them; run `make check` + headless controller pytest. | Completed |
| 1.2 | Scaffold `services/group_state.py` with loader/config/cache paths and pure snapshot builder (lifted intact); add unit tests for option filtering and snapshot synthesis. | Completed |
| 1.3 | Move persistence hooks (`persist_offsets/anchor/justification`, diff/nonce write, cache invalidation) into the service with tests for edit nonce + invalidation. | Completed |
| 1.4 | Port reload/debounce strategy into the service (post-edit reload delay, cache-diff guard); cover with tests for skip-while-writing behavior. | Completed |
| 1.5 | Wire controller to call the service API for options/snapshots/writes (feature-flagged if needed); rerun headless + PyQt suites (`make check`, `make test`, `PYQT_TESTS=1 ...`). | Completed |

Stage 1.1 notes:
- Options filter: `_load_idprefix_options` only surfaces groups present in `overlay_group_cache.json`; uses merged groupings loader and skips reloads if `_last_edit_ts` was <5s ago.
- Snapshot behavior: `_build_group_snapshot` synthesizes transforms from base+offsets (ignores cached transformed payload) and anchors default to configured or transformed anchor tokens; absolute values clamp to 1280x960 bounds.
- Edit flow: `_persist_offsets` stamps `_edit_nonce`, updates in-memory snapshots, clears cache transforms (`_invalidate_group_cache_entry`), and debounces writes with mode-profile timers; anchors/justification follow similar diff write/invalidations.
- Debounce/poll timers: active profile defaults to write 75ms, offset 75ms, status poll 50ms; inactive to 200/200/2500ms; cache reloads are diff-based with timestamp stripping.
- Tests run: `make check` (ruff, mypy, pytest) and full headless pytest suite; all passing (278 passed, 21 skipped expected for optional/GUI cases).

Stage 1.2 notes:
- Added `overlay_controller/services/group_state.py` with `GroupStateService` and `GroupSnapshot`; defaults to shipped/user/cache paths under repo root (user path honors `MODERN_OVERLAY_USER_GROUPINGS_PATH`).
- `load_options()` mirrors controller filtering: merged groupings via `GroupingsLoader`, options only for groups present in cache, plugin prefix shown when labels share a first token.
- `snapshot()` synthesizes transforms from base + offsets (ignores cached transformed bounds) while retaining cached transform anchor tokens; anchors computed via existing anchor-side helpers.
- Tests: new `overlay_controller/tests/test_group_state_service.py` covers cache-filtered options and synthesized snapshots (ignoring cached transforms). `make check` (ruff/mypy/pytest) now includes these; all passing (280 passed, 21 skipped).

Stage 1.3 notes:
- Added persistence hooks to `GroupStateService`: `persist_offsets`, `persist_anchor`, and `persist_justification` update in-memory config, write user diffs via `diff_groupings`, stamp `_edit_nonce`, and invalidate cache entries.
- `_invalidate_group_cache_entry` now mirrors controller behavior (clears transformed payload, sets `has_transformed` false, stamps `edit_nonce`/`last_updated`, rewrites cache file and in-memory cache).
- `_write_groupings_config` rounds offsets and writes user overrides (with `_edit_nonce`) when diffs exist; clears user file when merged view matches shipped.
- Tests: extended `overlay_controller/tests/test_group_state_service.py` to cover persist offsets writing user diff and cache invalidation. `make check` (ruff/mypy/pytest) passing with new test (281 passed, 21 skipped).

Stage 1.4 notes:
- Added reload/debounce helpers to `GroupStateService`: `reload_groupings_if_changed` respects a post-edit delay before calling the loader; `cache_changed` compares caches while stripping `last_updated` churn.
- Tests: `test_group_state_service.py` now covers skipping reloads within the delay, performing reloads after the delay, and cache-diff comparisons ignoring timestamps. `make check` (ruff/mypy/pytest) passing (283 passed, 21 skipped).

Stage 1.5 notes:
- Controller now instantiates `GroupStateService` and uses it for options (cache-filtered), cache reloads, cache-diff checks, snapshots (converted to `_GroupSnapshot`), and persistence hooks. Reload guard uses the service delay helper.
- Persistence paths call service `persist_*` with `write=False` to keep debounced writes; `_write_groupings_config` delegates to service and still sends merged overrides to the plugin.
- Fallback legacy paths remain for test harnesses without `_group_state` (retain diff-based writes and cache invalidation).
- Tests: `make check` (ruff, mypy, pytest) passing post-wireup (284 passed, 21 skipped).

### Phase 2: Plugin Bridge and Mode Timers
- Create `services/plugin_bridge.py` for CLI/socket messaging, heartbeat, active-group, and override-reload signals (including `ForceRenderOverrideManager`).
- Create `services/mode_timers.py` to own `ControllerModeProfile` application, poll interval management, debounced writes, and heartbeat scheduling via callbacks.
- UI supplies callbacks (e.g., `poll_cache`, `flush_config`) and receives events; timers and sockets stop living on the Tk class.
- Mode timers must retain the “skip reload right after edits” guard and respect live-edit windows so cache polls do not override in-flight changes; inject `after/after_cancel` rather than using Tk directly.
- Plugin bridge should own port/settings reads and ForceRender override lifecycle, including the fallback that writes `overlay_settings.json` if the CLI is unreachable.
- Risks: socket/heartbeat regressions; ForceRender fallback divergence; timer drift.
- Mitigations: wrap send/heartbeat in thin adapter with fakes in tests; keep port/settings reads behind a single API; add tests for live-edit guard timing; ship a temporary “legacy bridge” flag to flip back if needed.

### Phase 3: Preview Math and Renderer
- Move anchor/translation math, target-frame resolution, and fill-mode translation into `preview/snapshot_math.py` (pure functions).
- Build a `PreviewRenderer` class in `preview/renderer.py` that draws onto a Tk canvas given a snapshot + viewport; no file or state access.
- Point `overlay_controller/tests/test_snapshot_translation.py` at the new math module; add tests if gaps appear.
- Include the anchor/bounds helpers and the “synthesize transform from base + offsets” rule so preview output matches current behavior/tests.
- Risks: subtle anchor/scale regressions; canvas rendering mismatches due to rounding/order changes.
- Mitigations: move math first with existing tests, add golden value tests for anchor/bounds, and keep renderer order/rounding identical before any cleanup.

### Phase 4: Widget Extraction
- Relocate `IdPrefixGroupWidget`, `OffsetSelectorWidget`, `AbsoluteXYWidget`, `AnchorSelectorWidget`, `JustificationWidget`, and `SidebarTipHelper` into a `widgets/` package.
- Keep only layout/wiring in the main file; widgets expose callbacks for selection/change/focus and remain self-contained.
- Preserve behaviors/bindings; adjust imports in tests and app shell.
- Document the binding/focus contract used by `BindingManager` (e.g., `set_focus_request_callback`, `get_binding_targets`) so keyboard navigation and overlays keep working.
- Risks: broken focus/binding wiring; styling/geometry drift when detached from parent.
- Mitigations: extract one widget at a time with a focused test per widget, keep existing callbacks/signatures, and run the controller manually to verify focus cycling/selection overlays.

### Phase 5: App Shell Slimdown and Tests
- Leave `overlay_controller.py` as a thin `OverlayConfigApp` shell: layout, focus/drag handling, and orchestration of services/widgets.
- Rewrite wiring to use the extracted services; remove direct JSON/socket/timer math from the Tk class.
- Update or add tests around new seams (service unit tests + minimal integration harness for the shell).
- Risks: orchestration regressions (missed signals, debounces); UI focus/close edge cases.
- Mitigations: add a lightweight integration harness that stubs services/bridge, reuse existing focus/close tests, and gate rollout behind a dev flag until manual smoke passes.
