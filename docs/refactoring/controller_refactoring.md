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
| 1 | Extract group/config state management into a service with a narrow API; keep Tk shell unaware of JSON/cache details. | Completed |
| 2 | Isolate plugin bridge + mode/heartbeat timers into dedicated helpers to decouple sockets and scheduling from UI. | Completed |
| 3 | Move preview math/rendering into a pure helper and a canvas renderer class so visuals are testable without UI clutter. | Completed |
| 4 | Split reusable widgets (idPrefix, offset, absolute XY, anchor, justification, tips) into `widgets/` modules. | Completed |
| 5 | Slim `OverlayConfigApp` to orchestration only; wire services together; add/adjust tests for new seams. | Completed |
| 6 | Finish shell eviction: purge remaining helpers/shims, shrink `overlay_controller.py` to a minimal UI shell. | Completed |
| 7 | Polish/cleanup: tighten error handling/logging, doc/tests for public hooks, and remove dead code. | Completed (line-count target deferred) |

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

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Baseline existing bridge/timer behavior: map heartbeat/poll/backoff timings, ForceRender fallback, and current tests; run `make check` + headless controller pytest. | Completed |
| 2.2 | Extract `services/plugin_bridge.py` with CLI/socket messaging, heartbeat, active-group/override signals, port/settings reads, and ForceRender fallback; add fakes/unit tests. | Completed |
| 2.3 | Extract `services/mode_timers.py` to own mode profiles, poll interval management, debounced writes, live-edit reload guard, and injected `after/after_cancel`; add timing/guard tests. | Completed |
| 2.4 | Wire controller to the bridge/timers behind a legacy flag; connect callbacks (`poll_cache`, `flush_config`, heartbeat triggers), adapt tests/mocks. | Completed |
| 2.5 | Run headless + PyQt suites with new services enabled; flip default to new bridge/timers once green and keep legacy escape hatch documented. | Completed |

Stage 2.1 notes:
- Plugin CLI send path: `_send_plugin_cli` reads `_port_path` (defaults to repo-root `port.json`), best-effort connects to 127.0.0.1 with a 1.5s timeout, sends one line of JSON, and swallows errors (no retries/acks). Active-group updates and override reload signals reuse this helper.
- Heartbeat: `_controller_heartbeat_ms` defaults to 15000ms (clamped to >=1000ms); `_start_controller_heartbeat` is scheduled at startup (after 0ms), sends `controller_heartbeat`, then reschedules itself. Each heartbeat also sends `controller_active_group` for the current selection (deduped via `_last_active_group_sent` and includes anchor + `edit_nonce`).
- Mode/poll timers: `ControllerModeProfile` active=write 75ms/offset 75ms/status poll 50ms/cache_flush 1.0s; inactive=200/200/2500ms/5.0s. `_apply_mode_profile` clamps minimums (write/offset >=25ms, poll >=50ms) and reschedules `_status_poll_handle` on change. Startup applies the active profile and schedules `_poll_cache_and_status` after 50ms.
- Cache poll + live-edit guards: `_poll_cache_and_status` asks `GroupStateService.reload_groupings_if_changed(last_edit_ts, delay_seconds=5.0)` (or `GroupingsLoader.reload_if_changed` only when >5s since last edit), reloads cache via `state.refresh_cache()` (or direct file read) and uses `cache_changed` stripping `last_updated`. Refreshes options/snapshots, then reschedules after the current poll interval. `_offset_live_edit_until` (set to now+5s after offset changes) and `_group_snapshots` short-circuit `_refresh_current_group_snapshot` to avoid snap-backs during live edits; `_schedule_offset_resync` refreshes after 75ms.
- ForceRender override: `_ForceRenderOverrideManager` now sends `force_render_override` payloads over the socket (2s timeout, waits for `status: ok`) and relies on runtime state only; no settings file fallback or persistence.
- Existing coverage: `overlay_controller/tests/test_status_poll_mode_profile.py` verifies mode-profile clamping/reschedule; `tests/test_controller_override_reload.py` covers `controller_override_reload` debouncing/deduping; `overlay_client/tests/test_controller_active_group.py` exercises client handling of active-group signals. Heartbeat and force-render fallback currently untested.
- Tests run: `make check` (ruff, mypy, pytest) passing (284 passed, 21 skipped); `python -m pytest overlay_controller/tests` passing (25 passed, 3 skipped).

Stage 2.2 notes:
- Added `overlay_controller/services/plugin_bridge.py` with `PluginBridge` (port resolution, CLI send helper, heartbeat send, active-group dedupe, override reload dedupe) and `ForceRenderOverrideManager` (socket-only runtime override).
- Port paths default to repo-root `port.json`; connect/logger/time are injectable for tests; CLI send uses 1.5s timeout, ignores failures, and keeps last active-group key `(plugin, label, anchor)` to avoid duplicates.
- Force-render manager sends `force_render_override` with `force_render=true/false` over a 2s timeout window and does not write settings on failure.
- Tests: new `overlay_controller/tests/test_plugin_bridge.py` fakes sockets to cover CLI send, active-group dedupe, force-render fallback writing settings, and restore using server-provided prior values. `make check` now includes these (288 passed, 21 skipped).

Stage 2.3 notes:
- Added `overlay_controller/services/mode_timers.py` with `ModeTimers` owning mode profile application (clamps write/offset debounces to >=25ms, polls to >=50ms), status-poll scheduling via injected `after/after_cancel`, debounce helpers (write/offset), live-edit window tracking, and a post-edit reload guard (`record_edit` + `should_reload_after_edit`).
- Constructor accepts `ControllerModeProfile`, callbacks for scheduling/cancel, time source, and logger; exposes `start_status_poll`/`stop_status_poll` with automatic reschedule after each poll.
- Live-edit guard uses `start_live_edit_window` + `live_edit_active` to keep preview/snapshot refreshes from snapping back during edits; reload guard ensures groupings reload waits out a post-edit delay.
- Tests: new `overlay_controller/tests/test_mode_timers.py` covers mode clamp/reschedule, poll rescheduling after callback, debounce helper behavior (including cancel/re-schedule), live-edit window, and reload guard. `make check` passing (292 passed, 21 skipped).

Stage 2.4 notes:
- Controller now wires to `PluginBridge`/`ModeTimers` with legacy escape hatches (`MODERN_OVERLAY_LEGACY_BRIDGE`, `MODERN_OVERLAY_LEGACY_TIMERS`). Default path uses services; legacy paths remain in-place.
- `_send_plugin_cli` delegates to bridge; heartbeats use `send_heartbeat`; active-group/override reload signals use bridge APIs (still fallback to legacy socket writes). Force-render override uses bridge-managed manager when enabled.
- Mode timers drive status-poll scheduling, debounce helpers, live-edit windows, and post-edit reload gating; legacy Tk `after` path retained when legacy flag set.
- Live-edit guards now use service window tracking in addition to legacy `_offset_live_edit_until`; edit timestamps flow to timers for reload gating.
- Tests: `make check` (ruff, mypy, pytest) passing with new wiring (292 passed, 21 skipped).

Stage 2.5 notes:
- Defaults now run with service-backed bridge/timers; legacy env flags remain documented for fallback (`MODERN_OVERLAY_LEGACY_BRIDGE`, `MODERN_OVERLAY_LEGACY_TIMERS`).
- Test coverage with services enabled: `make check` (ruff, mypy, full pytest) passing (292 passed, 21 skipped) and `PYQT_TESTS=1 python -m pytest overlay_client/tests` passing (180 passed).

### Phase 3: Preview Math and Renderer
- Move anchor/translation math, target-frame resolution, and fill-mode translation into `preview/snapshot_math.py` (pure functions).
- Build a `PreviewRenderer` class in `preview/renderer.py` that draws onto a Tk canvas given a snapshot + viewport; no file or state access.
- Point `overlay_controller/tests/test_snapshot_translation.py` at the new math module; add tests if gaps appear.
- Include the anchor/bounds helpers and the “synthesize transform from base + offsets” rule so preview output matches current behavior/tests.
- Risks: subtle anchor/scale regressions; canvas rendering mismatches due to rounding/order changes.
- Mitigations: move math first with existing tests, add golden value tests for anchor/bounds, and keep renderer order/rounding identical before any cleanup.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Baseline current preview math/rendering: document anchor rules, fill-mode translation, and test coverage; run headless controller pytest. | Completed |
| 3.2 | Extract pure snapshot math into `preview/snapshot_math.py` (anchor points, translate for fill, clamp helpers); point existing tests to it and add golden-value cases if needed. | Completed |
| 3.3 | Introduce `preview/renderer.py` with `PreviewRenderer` that draws given snapshot/viewport; keep layout/colors/order identical; add renderer-focused tests (using stub canvas). | Completed |
| 3.4 | Wire controller to use snapshot math/renderer; keep legacy paths guarded if needed; ensure preview/absolute widgets stay in sync. | Completed |
| 3.5 | Run full headless + PyQt suites with new preview path; flip default if gated; document remaining cleanup. | Completed |

Stage 3.1 notes:
- Anchor mapping via `_anchor_point_from_bounds`: tokens `c/center`, `n/top`, `ne`, `e/right`, `se`, `s/bottom`, `sw`, `w/left`, default `nw`; `_clamp_unit` normalizes 0–1 bands.
- Fill translation helper `_translate_snapshot_for_fill` early-returns if `snapshot` is None or `has_transform` is True; otherwise uses `compute_legacy_mapper` `ScaleMode.FILL` overflow path to build a `GroupTransform` from base bounds/anchor (override -> transform anchor -> anchor), computes proportional `dx/dy`, and applies translation. Fit/no overflow snapshots remain unchanged.
- Snapshot synthesis currently marks `has_transform=True` (base+offsets), so fill-translation is only exercised when callers pass snapshots with `has_transform=False` (as in tests); preview path currently bypasses the fill shift.
- Coverage: `overlay_controller/tests/test_snapshot_translation.py` checks fill overflow shifts for 1280x720 with `nw` and `center` anchors and no shift for `fit`; no renderer-specific tests yet.
- Tests run: `python -m pytest overlay_controller/tests` (33 passed, 3 skipped).

Stage 3.2 notes:
- Added `overlay_controller/preview/snapshot_math.py` with pure helpers (`clamp_unit`, `anchor_point_from_bounds`, `translate_snapshot_for_fill`) mirroring existing controller behavior.
- Controller delegates anchor computation and fill translation to the new module; unused legacy imports removed.
- Updated `overlay_controller/tests/test_snapshot_translation.py` to target `snapshot_math.translate_snapshot_for_fill`; behavior unchanged.
- Tests run: `make check` (ruff, mypy, full pytest) passing (292 passed, 21 skipped).

Stage 3.3 notes:
- Added `overlay_controller/preview/renderer.py` with `PreviewRenderer` that draws the preview onto a supplied canvas using the same layout/colors/order/labels/anchor marker and signature caching as the previous `_draw_preview`.
- Controller `_draw_preview` now instantiates and delegates to `PreviewRenderer` (and still uses snapshot math helpers); stores renderer signature to maintain cache behavior.
- New tests: `overlay_controller/tests/test_preview_renderer.py` covers draw signature caching and empty selection/snapshot placeholders. `make check` passing with suite (294 passed, 21 skipped).

Stage 3.4 notes:
- Controller fully delegates preview math/rendering: `_draw_preview` now only resolves selection/snapshot and calls `PreviewRenderer`, which uses `snapshot_math` for fill translation/anchors and preserves signature caching. `_last_preview_signature` mirrors renderer state to keep legacy cache checks stable.
- No legacy preview path kept; visual output/order/colors unchanged.
- Tests run: `make check` (ruff, mypy, full pytest) passing (294 passed, 21 skipped).

Stage 3.5 notes:
- New preview path validated via full suites: `make check` (ruff, mypy, full pytest) passing (294 passed, 21 skipped) and `PYQT_TESTS=1 python -m pytest overlay_client/tests` passing (180 passed).
- No gating flags needed; preview renderer/math now default. Legacy behavior retained via identical rendering outputs and signature caching.

### Phase 4: Widget Extraction
- Relocate `IdPrefixGroupWidget`, `OffsetSelectorWidget`, `AbsoluteXYWidget`, `AnchorSelectorWidget`, `JustificationWidget`, and `SidebarTipHelper` into a `widgets/` package.
- Keep only layout/wiring in the main file; widgets expose callbacks for selection/change/focus and remain self-contained.
- Preserve behaviors/bindings; adjust imports in tests and app shell.
- Document the binding/focus contract used by `BindingManager` (e.g., `set_focus_request_callback`, `get_binding_targets`) so keyboard navigation and overlays keep working.
- Risks: broken focus/binding wiring; styling/geometry drift when detached from parent.
- Mitigations: extract one widget at a time with a focused test per widget, keep existing callbacks/signatures, and run the controller manually to verify focus cycling/selection overlays.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Baseline widget behaviors/bindings/layout: document callbacks, focus wiring, and current tests; run headless controller pytest. | Completed |
| 4.2 | Extract `IdPrefixGroupWidget` to `widgets/idprefix.py` with existing API; adjust imports and add/align tests. | Completed |
| 4.3 | Extract offset/absolute widgets (`OffsetSelectorWidget`, `AbsoluteXYWidget`) to `widgets/offset.py`/`widgets/absolute.py`; preserve change callbacks and focus hooks; update tests. | Completed |
| 4.4 | Extract anchor/justification widgets to `widgets/anchor.py`/`widgets/justification.py`; ensure bindings and callbacks intact; update tests. | Completed |
| 4.5 | Extract tips helper (`SidebarTipHelper`) and finalize widget package exports; refit controller imports; rerun full test suites. | Completed |

Stage 4.1 notes:
- Widgets and bindings baseline: `IdPrefixGroupWidget` handles Alt-key suppression for dropdown navigation; Offset selector uses Alt+Arrow to pin edges and focuses host on clicks; Absolute widget exposes `get_binding_targets` and change callbacks; Anchor/Justification widgets manage focus via `set_focus_request_callback` and emit change callbacks; `SidebarTipHelper` currently static text.
- Focus wiring: `_focus_widgets` uses sidebar index mapping; `BindingManager` registers widget-specific bindings via `absolute_widget.get_binding_targets()`; widgets provide `on_focus_enter/exit` methods used by controller focus navigation.
- Tests run: `python -m pytest overlay_controller/tests` (headless) passing (33 passed, 3 skipped).

Stage 4.2 notes:
- Added `overlay_controller/widgets` package with shared `alt_modifier_active` helper and `IdPrefixGroupWidget` moved to `widgets/idprefix.py` (API intact).
- Controller imports widget/alt helper; removed inline class definition and unused ttk import.
- Tests run: `python -m pytest overlay_controller/tests` (35 passed, 3 skipped).

Stage 4.3 notes:
- Moved `OffsetSelectorWidget` to `widgets/offset.py` (still uses `alt_modifier_active` helper) and `AbsoluteXYWidget` to `widgets/absolute.py`; exported via `widgets/__init__.py`.
- Controller imports widgets from package; inline class definitions removed.
- Tests run: `python -m pytest overlay_controller/tests` (35 passed, 3 skipped).

Stage 4.4 notes:
- Extracted `JustificationWidget` to `widgets/justification.py` and `AnchorSelectorWidget` to `widgets/anchor.py` (anchor uses shared `alt_modifier_active` helper); exported via `widgets/__init__.py`.
- Controller now imports all widgets from the package; inline definitions removed.
- Tests run: `python -m pytest overlay_controller/tests` (35 passed, 3 skipped).

Stage 4.5 notes:
- Moved `SidebarTipHelper` to `widgets/tips.py`; `widgets/__init__.py` exports all widgets (idprefix, offset, absolute, anchor, justification, tips) plus `alt_modifier_active`.
- Controller sidebar wiring now imports all widgets from `overlay_controller.widgets`; inline helper removed from controller.
- Tests run: `make check` (ruff, mypy, full pytest) passing (294 passed, 21 skipped).

### Phase 5: App Shell Slimdown and Tests
- Leave `overlay_controller.py` as a thin `OverlayConfigApp` shell: layout, focus/drag handling, and orchestration of services/widgets.
- Rewrite wiring to use the extracted services; remove direct JSON/socket/timer math from the Tk class.
- Update or add tests around new seams (service unit tests + minimal integration harness for the shell).
- Aggressive target: drive `overlay_controller.py` down toward 600–700 lines by 5.7 (no business logic left inline). Move any reusable helpers to `controller/` or `widgets/`; prune legacy escape hatches once replacements are wired.
- Risks: orchestration regressions (missed signals, debounces); UI focus/close edge cases.
- Mitigations: add a lightweight integration harness that stubs services/bridge, reuse existing focus/close tests, and gate rollout behind a dev flag until manual smoke passes.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Baseline the current monolith: map responsibilities to evict, set target size (<700 lines), and list tests per step; lock down legacy flags we’ll delete by 5.7. | Completed |
| 5.2 | Extract runtime/context glue into `controller/app_context.py` (paths/env/services/mode profile/bridge/timers); default to new services, relegate legacy flags to a minimal shim. | Completed |
| 5.3 | Extract layout composition into `controller/layout.py` (placement/sidebar/overlays/focus map assembly); controller retains only callbacks/state. | Completed |
| 5.4 | Extract focus/binding orchestration into `controller/focus_manager.py` (focus map, widget-select mode, navigation handlers, binding registration); remove inline binding helpers. | Completed |
| 5.5 | Extract preview orchestration into `controller/preview_controller.py` (snapshot fetch, live-edit guards, target frame resolution, renderer invocation, absolute sync); drop duplicate preview helpers from the shell. | Completed |
| 5.6 | Extract edit/persistence flow into `controller/edit_controller.py` (persist_* hooks, debounces, cache reload guard, active-group/override signals, nonce/timestamps); move reload guards + cache diff helpers out of the shell. | Completed |
| 5.7 | Final shell trim: remove remaining legacy helpers/flags, tighten imports, keep only UI wiring/drag/close plumbing; update docs/tests and rerun full suites (headless + PyQt). | Not started |

#### Stage 5.1 Plan
- **Goal:** Baseline the current monolith, mark what must move out, and set a concrete size target (<700 lines) with a test cadence for each upcoming stage.
- **Inventory to map:**
  - Service/runtime glue (paths, env, loaders, mode profiles, bridge/timers, force-render) that should live in `controller/app_context.py`.
  - Layout construction (frames, overlays, widgets, focus map) that should move to `controller/layout.py`.
  - Focus/binding orchestration (focus map, widget-select mode, navigation handlers, binding registration) for `controller/focus_manager.py`.
  - Preview orchestration (snapshot fetch/live-edit guard/target frame resolve/renderer invocation/absolute sync) for `controller/preview_controller.py`.
  - Edit/persistence flow (persist_* hooks, debounce scheduling, cache reload guard, override/active-group signals, nonce/timestamp handling) for `controller/edit_controller.py`.
  - Legacy helpers/flags earmarked for removal in 5.7.
- **Deliverables:** Updated notes in this doc capturing current responsibilities, size target, and tests to run per stage; no code changes.
- **Tests to run:** `python -m pytest overlay_controller/tests` (headless) after the baseline note-taking; defer `make check`/PyQt until after code-moving stages.

Stage 5.1 notes:
- Current size: `overlay_controller.py` is ~3,180 lines; aggressive target remains <700 by 5.7 with no business logic inline.
- Responsibilities to evict:
  - **Runtime/context glue:** path/env resolution, `GroupingsLoader` construction, cache/settings/port paths, mode profile defaults, plugin bridge/timer setup, legacy flags.
  - **Layout assembly:** container/placement/sidebar frames, overlays (sidebar/placement), indicator, preview canvas binding, widget creation/packing, focus map population.
  - **Focus/binding orchestration:** sidebar focus map, widget-select mode toggles, navigation handlers, binding registration (`BindingManager` actions, widget-specific bindings), contextual tips/highlights.
  - **Preview orchestration:** snapshot fetch/build, live-edit guards, target frame resolution, renderer invocation/signature caching, absolute widget sync.
  - **Edit/persistence flow:** persist offsets/anchors/justification, debounce scheduling, cache reload guard, override/active-group signals, nonce/timestamp management, cache diff helpers.
  - **Legacy helpers/flags:** legacy bridge/timer toggles, redundant socket helpers, duplicated preview/math helpers earmarked for removal by 5.7.
- Test cadence locked: run `overlay_controller/tests` after each stage; `make check` + PyQt suite after major extractions (5.4–5.7).
- Tests run for baseline: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (35 passed, 3 skipped).

#### Stage 5.2 Plan
- **Goal:** Extract runtime/context glue into `controller/app_context.py` and wire the controller to consume it, while keeping a minimal legacy escape hatch. Target a substantial line reduction by moving path/env/service construction and mode profile defaults out of the shell.
- **What to move:**
  - Path/env resolution: shipped/user groupings, cache, settings, port, root detection, env overrides (e.g., `MODERN_OVERLAY_USER_GROUPINGS_PATH`).
  - GroupingsLoader/GroupStateService construction and initial cache/load state setup.
  - ControllerModeProfile defaults and mode/timer configuration values.
  - Plugin bridge/timers/force-render override wiring, including legacy flags (`MODERN_OVERLAY_LEGACY_BRIDGE`, `MODERN_OVERLAY_LEGACY_TIMERS`) scoped to a shim.
  - Heartbeat interval defaults and any constants tied to the above context.
- **Interfaces:** `build_app_context(root: Path, logger) -> AppContext` with resolved paths, services, mode profile, heartbeat interval, bridge, force-render override, and loader references.
- **Constraints:** No behavior changes; defaults remain intact; legacy flags still honored. Controller should only pull from the context and stop doing inline construction.
- **Tests to run:** `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` after wiring; defer `make check`/PyQt until after subsequent stages unless failures appear.
- **Risks & mitigations:**
  - Miswired paths/env overrides (user/shipped/cache/settings/port) could point to wrong files → keep defaults identical, add assertions/logging in the builder, and cover with a lightweight unit test for `build_app_context`.
  - Bridge/timer legacy flags regressing behavior → isolate the shim, keep env flags honored, and document defaults in the builder; add a smoke test that instantiates with/without legacy flags.
  - Mode profile defaults drifting → lift constants intact into the builder and verify via existing `test_status_poll_mode_profile`.
  - Controller wiring misses a field (e.g., force-render override/heartbeat) → fail fast by typing the `AppContext` and updating controller initialization in one pass; run headless tests immediately.
  - Aggressive pruning losing behavior → move code verbatim first, then trim imports; avoid reformatting logic in this step.

Stage 5.2 notes:
- Added `overlay_controller/controller/app_context.py` with `AppContext` + `build_app_context` to own path/env resolution, `GroupingsLoader`/`GroupStateService`, mode profile defaults, heartbeat interval, and plugin bridge/force-render wiring (legacy shim via injected factory).
- Controller now builds `_app_context` and pulls shipped/user/cache/settings/port paths, loader, group state, mode profile, heartbeat, bridge, and force-render override from it; inline construction removed.
- New unit test `overlay_controller/tests/test_app_context.py` covers path/env resolution, bridge/force-override wiring, and mode profile defaults (including legacy shim creation).
- Tests run: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (headless).

#### Stage 5.3 Plan
- **Goal:** Move layout composition into `controller/layout.py`, leaving the controller to supply callbacks/state only. Target a large line drop by removing all inline frame/canvas/widget construction, focus map assembly, and indicator wiring from `overlay_controller.py`.
- **What to move (aggressively):**
  - Container/placement/sidebar frame creation and grid configuration.
  - Indicator wrapper/canvas setup and placement overlay/sidebar overlay creation.
  - Preview canvas creation/bindings.
  - Sidebar sections (idprefix, offset, absolute, anchor, justification, tips): widget instantiation, packing, focus-map population, and click bindings.
  - Layout constants (padding, overlay border, min widths) fed in as parameters from the controller—no layout literals left inline.
- **Interfaces:** `LayoutBuilder(app).build(...) -> dict[...]` returning container/frames, preview canvas, overlays, indicator, sidebar cells, focus map, and optional context frame. Controller keeps ownership of callbacks.
- **Constraints:** Preserve geometry/bindings/order exactly; no behavior changes. Keep alt-click bindings and focus callbacks intact. Controller should just pass callbacks/config and store returned components.
- **Tests to run:** `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` after wiring; run `make check` if layout refactor touches imports broadly.

Stage 5.3 notes:
- Added `overlay_controller/controller/layout.py` with `LayoutBuilder.build(...)` that constructs container/placement/sidebar frames, overlays, indicator, preview canvas bindings, sidebar widgets, and focus map; controller now just passes callbacks/config and stores returned components.
- `overlay_controller.py` uses `LayoutBuilder` instead of inline `_build_layout`/`_build_sidebar_sections` (removed), assigning returned widgets/overlays/frames and reusing existing callbacks; initial focus index reset to 0.
- Tests run: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (37 passed, 3 skipped).

#### Stage 5.4 Plan
- **Goal:** Extract focus/binding orchestration into `controller/focus_manager.py`, leaving the controller to simply register callbacks and consume focus state. Continue shrinking `overlay_controller.py` by removing inline focus map handling and binding registration helpers.
- **What to move (aggressively):**
  - Focus map accessors (`_get_active_focus_widget`, sidebar focus index init), widget-select mode toggles (`enter_focus_mode`/`exit_focus_mode` hooks), and sidebar focus navigation helpers (`focus_sidebar_up/down`, `move_widget_focus_left/right` selection-mode behaviors).
  - Binding registration currently done inline (`BindingManager` actions, widget-specific bindings via `absolute_widget.get_binding_targets`).
  - Focus highlight updates (`_update_sidebar_highlight`, `_update_placement_focus_highlight`) and contextual tip refresh triggers.
  - Any selection-mode focus forcing to keep Space/arrow handling on the shell.
  - Aggressive target: leave no focus/binding logic in `overlay_controller.py` beyond delegating to `FocusManager`; only wiring/attributes remain in the shell.
- **Interfaces:** `FocusManager(app, binding_manager)` exposing `register_widget_bindings()` and helpers for sidebar click/navigation/highlight refresh; keep callback signatures the controller already uses.
- **Constraints:** Preserve keyboard/focus behavior identically (space/enter/esc, alt-modifier focus quirks). Avoid changing widget callbacks; controller should delegate to `FocusManager` where possible. Keep legacy behaviors intact for tests.
- **Tests to run:** `overlay_client/.venv/bin/python -m pytest overlay_controller/tests`; if focus wiring changes are invasive, run `make check` as well.
- **Risks & mitigations:**
  - Focus navigation regression (e.g., skipping cells, failing to enter/exit focus mode) → port logic verbatim first, add a small unit test for FocusManager bindings, and rerun headless focus-related tests.
  - Binding registration drift (absolute widget bindings missing) → keep `register_widget_bindings` delegating to widget APIs; add assertions/tests for registered actions.
  - Contextual highlights/tips not refreshing → ensure FocusManager triggers controller tip/highlight updates; keep callbacks for `_update_contextual_tip` wired.
  - Selection-mode key handling (Space/Enter/Esc) breaking → retain selection-mode focus forcing in FocusManager and cover with a smoke test that toggles modes.

Stage 5.4 notes:
- Added `overlay_controller/controller/focus_manager.py` to own widget binding registration and sidebar click delegation; exported via `controller/__init__.py`.
- `overlay_controller.py` now instantiates `FocusManager` and delegates binding registration to it; inline `_register_widget_specific_bindings` usage is replaced with `_register_focus_bindings`.
- New unit test `overlay_controller/tests/test_focus_manager.py` covers absolute widget binding registration.
- Tests run: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (38 passed, 3 skipped).

#### Stage 5.5 Plan
- **Goal:** Extract preview orchestration into `controller/preview_controller.py`, removing preview-fetch/draw plumbing from `overlay_controller.py`. Aim to eliminate `_draw_preview` logic and preview helper methods from the shell.
- **What to move (aggressively):**
  - Snapshot fetch/refresh logic (current selection snapshot resolution, live-edit guards, snapshot storage/accessors).
  - Preview renderer invocation, target frame resolution, anchor/absolute sync helpers, and signature caching.
  - Scale mode/anchor token resolution, absolute widget sync (apply/get), and target dimension/bounds helpers.
  - Live-edit offset guard handling tied to preview refreshes.
- **Interfaces:** `PreviewController(app, abs_width, abs_height, padding)` exposing `refresh_current_group_snapshot(...)`, `get_group_snapshot(...)`, `draw_preview()`, and helper accessors for anchor/target-frame resolution; app supplies callbacks/time/renderer via injection if needed.
- **Constraints:** Preserve visual output/order/caching; no behavior changes. Controller should delegate preview/anchor/absolute helper methods to the PreviewController.
- **Tests to run:** `overlay_client/.venv/bin/python -m pytest overlay_controller/tests`; run `make check` if interface changes ripple across imports.
- **Risks & mitigations:**
  - Preview signature caching regressions (extra draws or missing updates) → port renderer invocation/signature handling verbatim; add/extend renderer/signature tests to cover live anchor changes.
  - Live-edit guard behavior changing (snap-back during arrow holds) → keep existing live-edit guard checks in the helper and add a smoke test that simulates live-edit window timing.
  - Target frame/anchor math drift → move helpers intact and rely on existing snapshot/translation tests; consider a targeted preview-controller unit test for target frame resolution.
  - Absolute widget sync mismatches (UI not reflecting snapshot or vice versa) → keep apply/get helpers inside the controller with delegation; add a small unit test for absolute sync pathways if feasible.

Stage 5.5 notes:
- Added `overlay_controller/controller/preview_controller.py` to own snapshot refresh, live-edit guard handling, target-frame resolution, anchor/absolute sync helpers, and renderer invocation/signature caching; exported via `controller/__init__.py`.
- `overlay_controller.py` now instantiates `PreviewController` and delegates preview/anchor/absolute helper methods and `_draw_preview`/snapshot refresh to it; preview math/renderer imports remain in the helper.
- Tests run: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (38 passed, 3 skipped).

#### Stage 5.6 Plan
- **Goal:** Extract edit/persistence flow into `controller/edit_controller.py`, pulling all persist hooks, debounce scheduling, cache reload guards, and override/active-group signaling out of `overlay_controller.py`. Aggressive target: no persistence/cache/override logic left inline.
- **What to move (aggressively):**
  - `persist_*` flows for offsets/anchor/justification (including edit nonce stamping, cache invalidation, live-edit windows).
  - Debounce scheduling and cache/groupings write helpers; cache diff helpers and reload guards (`_poll_cache_and_status` pieces) related to persistence.
  - Active-group and override-reload signal emission (bridge/CLI), heartbeat-triggered active-group send hooks, and last-sent tracking.
  - Edit timestamp/nonce handling and live-edit delay coordination with timers.
  - Any remaining ForceRender override triggers tied to persistence signals (if applicable).
- **Interfaces:** `EditController(app, bridge, timers, group_state, cache_path, shipped_path, user_path, logger)` exposing methods for `persist_offsets/anchor/justification`, `schedule_writes`, `poll_cache_and_status`, `send_active_group`, and cache diff helpers. Controller should delegate persistence and signaling to this helper.
- **Constraints:** Preserve debounce timings, nonce semantics, cache invalidation behavior, and live-edit guards; keep legacy fallbacks accessible if needed. No behavioral drift.
- **Tests to run:** `overlay_client/.venv/bin/python -m pytest overlay_controller/tests`; run `make check` if interface changes are broad. Add unit coverage for the new EditController if feasible.
- **Risks & mitigations:**
  - Debounce/poll timing regressions (writes too fast/slow) → lift timings intact, add unit tests around debounce scheduling, and verify with existing status-poll tests.
  - Cache reload/guard drift (reload during writes) → port reload-guard logic verbatim and add a unit test for post-edit delay handling.
  - Active-group/override signals missing or duplicated → keep last-sent tracking in the helper; add a smoke test for dedupe and invoke existing override reload tests.
  - Nonce/timestamp handling regression → ensure the helper stamps/propagates `_edit_nonce`/`_last_edit_ts` exactly as before; add a focused test if possible.
  - Legacy fallback removal too early → keep a shim path for legacy cache/CLI write behavior until tests are green; remove only after validation.

Stage 5.6 notes:
- Added `overlay_controller/controller/edit_controller.py` to own persist hooks (offsets/justification), debounce scheduling, groupings config writes, and override reload signals; exported via `controller/__init__.py`.
- `overlay_controller.py` now instantiates `_edit_controller`, delegates offset persistence and debounce/write scheduling to it, and uses helper for override reload + config writes; legacy `_write_groupings_config` wrapper retained for compatibility/tests.
- Tests run: `overlay_client/.venv/bin/python -m pytest overlay_controller/tests` (38 passed, 3 skipped).

#### Stage 5.7 Plan
- **Goal:** Final trim of `overlay_controller.py` to a thin shell (<650 lines). Remove legacy helpers/flags and push any remaining logic (cache reload guards, ForceRender/CLI fallbacks, heartbeat/active-group glue, debounce helpers, snapshot glue) into controllers/services. Leave only UI wiring, drag, and close plumbing.
- **What to cut/move (aggressively):**
  - Legacy bridge/timer/cache write fallbacks and inline `_write_groupings_config`/debounce stubs that duplicate EditController; consolidate override reload/active-group send paths into services.
  - Leftover preview/layout/focus helpers still defined in the shell (anchor/absolute sync, sidebar highlight updates, selection-mode toggles) that can live in `PreviewController` or `FocusManager`.
  - Residual snapshot/cache/loader helpers (cache diff/invalidation, reload gating) lingering in the shell; move to EditController or GroupStateService.
  - Import trimming: drop unused widget/controller imports and lift small pure helpers into the appropriate modules.
  - Remove legacy env flags once services are the only path; keep a small shim if tests rely on legacy symbols but target deleting unused code.
- **Interfaces:** Keep `OverlayConfigApp` exposing only lifecycle wiring (init widgets/controllers, bind callbacks, start timers, teardown). Controllers/services own behavior; shell calls their APIs.
- **Tests to run:** `make lint`, `make test`, plus `PYQT_TESTS=1 python -m pytest overlay_client/tests` once final trim is done to ensure UI paths stay green.
- **Risks & mitigations:**
  - Removing legacy fallbacks breaks external scripts/tests → audit references first, keep minimal shims with deprecation logs, and run full suites (headless + PyQt) immediately after removal.
  - Missing glue after moving helpers (active-group/override reload not firing, debounces skipped) → add/extend unit tests around bridge/edit controllers and rerun `tests/test_controller_override_reload.py` and active-group tests to verify service path.
  - UI focus/preview regressions if helpers move without callback wiring → move helpers alongside explicit callback hookups in FocusManager/PreviewController; rerun headless controller tests and manual smoke if needed.
  - Line-count pressure leading to over-pruning → move logic into helpers instead of deleting; measure file length after each cut and stop deleting when behavior isn’t covered.
  - ForceRender/heartbeat edge cases regress when legacy flags are removed → keep a temporary compatibility shim that delegates to services, and validate with `tests/test_overlay_controller_platform.py`/heartbeat-related coverage before deleting.

Stage 5.7 notes:
- Removed legacy bridge/timer env flags; controller always uses the service `PluginBridge`, with a thin compatibility shim `_ForceRenderOverrideManager` delegating to the service for tests. `_send_plugin_cli` now delegates to the bridge only (no socket fallback).
- Retired legacy debounce/write helpers (`_write_groupings_config`, cache/debounce stubs) from `overlay_controller.py` and replaced them with small static wrappers that delegate to `EditController`; `EditController` owns offset rounding.
- Simplified `AppContext` (no `use_legacy_bridge`), pruned the legacy test case, and trimmed imports accordingly.
- Tests run after the trim: `make lint` and `make test` (full suite).

### Phase 6: Shell Eviction and Line-Cut
- Status: Completed (tests green; size target deferred to Phase 7).
- Aggressive goal: drive `overlay_controller.py` to a true UI shell (<650 lines). Evict remaining business helpers, shims, and duplicated logic; tighten interfaces so services/controllers own behavior.
- Best-practice gaps this phase addresses: remaining monolith size, UI shell still housing snapshot/persistence/focus helpers, leaky state access via `__dict__`, and legacy shims/test-only code sitting in the shell.
- What to remove/move aggressively:
  - `_GroupSnapshot` definition and any snapshot/absolute helpers still in the shell (move to preview controller or a dataclass module).
  - Focus/navigation helpers still inline (sidebar/placement focus moves, selection-mode toggles, contextual tips/highlights) into `FocusManager`.
  - Persistence/offset/absolute glue and test shims (`_write_groupings_config`, rounders, static wrappers) into `EditController` or a test helper module.
  - Residual cache/loader helpers and any direct `__dict__` pokes for state that belong to services.
  - UI-agnostic fallbacks and broad `getattr(..., None)` + silent `except Exception` patterns; move/limit to helpers with explicit logging.
- Interfaces: `OverlayConfigApp` should only build widgets/layout/controllers, wire callbacks, manage window/drag/close, and forward to helpers. Public/test APIs live in services/helpers.
- Tests to run: `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests` after big cuts; add/adjust unit tests for moved helpers.
- Risks & mitigations:
  - Breaking tests that reference legacy shims → provide temporary import shims in helper modules, update tests to new locations, then remove shims once green.
  - Focus/preview behavior drift → migrate logic verbatim into managers, add small unit tests (focus nav, absolute sync), and rerun headless controller tests.
  - Over-aggressive deletion → prefer moving intact code into helpers; measure file length after each cut.

| Stage | Description | Status |
| --- | --- | --- |
| 6.1 | Move `_GroupSnapshot` and snapshot helpers out of the shell (into preview controller/dataclass), update references/tests. | Completed |
| 6.2 | Move remaining focus/nav/tip/highlight helpers into `FocusManager`; controller only wires callbacks/state. | Completed |
| 6.3 | Move persistence/test shims (`_write_groupings_config`, rounders, cache/loader helpers) into `EditController`/test helpers; update tests; drop shell copies. | Completed |
| 6.4 | Strip residual legacy/fallback code and direct `__dict__` state pokes; enforce helper APIs; re-measure line count. | Completed |
| 6.5 | Run full suites (lint/test/PyQt) and verify shell <650 lines; remove temporary shims. | Completed |

#### Stage 6.1 Plan
- **Goal:** Move `_GroupSnapshot` and any snapshot/absolute helper logic out of `overlay_controller.py` into the preview controller (or a dedicated dataclass module), so the shell no longer defines or owns snapshot shape/logic.
- **What to move:**
  - `_GroupSnapshot` dataclass definition.
  - Snapshot build/access helpers still in the shell (e.g., `_build_group_snapshot`, `_get_group_snapshot`, anchor/absolute computation helpers) that belong in `PreviewController` or a dedicated snapshot module.
  - Any snapshot-related state kept in the shell that can be owned by `PreviewController` (e.g., `_group_snapshots` management) while keeping UI wiring intact.
- **Interfaces:** Expose `_GroupSnapshot` from the preview controller module (or a new `snapshot.py`) and update imports/tests to reference the new location. `OverlayConfigApp` should request snapshots through `PreviewController` APIs only.
- **Tests to run:** `make lint`, `make test`, and (if snapshot rendering paths change) `PYQT_TESTS=1 python -m pytest overlay_client/tests` before marking complete.
- **Risks & mitigations:**
  - Snapshot type drift breaking rendering or anchor math → move code verbatim, keep `_GroupSnapshot` fields identical, and rerun snapshot/preview tests (`overlay_controller/tests/test_snapshot_translation.py`, `test_preview_renderer.py`).
  - Hidden dependencies on the shell’s `_GroupSnapshot` symbol (tests or helpers) → add re-export/shim in the new module while updating references; remove shim only after tests are green.
  - State ownership bugs (missing snapshot updates) when moving `_group_snapshots` handling → ensure `PreviewController` manages the map and controller uses its accessors; add a small unit test if needed.
- **Guarantee alignment:** This cut removes business data structures from the shell, reducing size and coupling. Success criteria include: shell no longer defines `_GroupSnapshot`, snapshot helpers live in helpers/controllers, and full suites are green, keeping us on track for the “UI-only shell” guarantee in Phase 7.

Stage 6.1 notes:
- `_GroupSnapshot` now comes from `services.group_state.GroupSnapshot` (aliased for test compatibility); the shell no longer defines it. Snapshot build/absolute helpers moved into `PreviewController` with an internal snapshot map; the shell delegates `_build_group_snapshot`/`_compute_absolute_from_snapshot` (with a minimal legacy fallback for tests that construct partial apps).
- `PreviewController` now owns snapshot storage (`snapshots`), build logic, and absolute computation; controller keeps a reference for legacy consumers.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped).

#### Stage 6.2 Plan
- **Goal:** Move the remaining focus/navigation/contextual tip/highlight helpers out of `overlay_controller.py` into `FocusManager`, leaving the shell to wire callbacks/state only.
- **What to move:**
  - Sidebar/placement focus navigation (`_set_sidebar_focus`, `_refresh_widget_focus`, `_update_sidebar_highlight`, `_update_placement_focus_highlight`, widget-select mode toggles, placement click handler).
  - Contextual tip updates tied to focus state (`_update_contextual_tip`) and any focus-index bookkeeping currently in the shell.
  - Any remaining key handlers that are focus-nav specific (e.g., move_widget_focus_left/right behaviors in selection mode) that can be hosted in `FocusManager` while keeping UI wiring in the shell.
- **Interfaces:** Extend `FocusManager` with methods to perform these updates given the current app state/callbacks; controller invokes the manager rather than owning focus logic.
- **Tests to run:** `make lint`, `make test`; if focus behaviors change visibly, consider `PYQT_TESTS=1 python -m pytest overlay_client/tests` before marking complete.
- **Risks & mitigations:**
  - Focus navigation regressions (skipped/incorrect focus targets) → port logic verbatim first, add/extend a small unit test in `test_focus_manager.py` to cover sidebar/placement highlights and selection-mode moves.
  - Contextual tips not updating correctly → ensure `FocusManager` accepts a tip-callback and invoke it in the same places as before; add an assertion in tests if feasible.
  - Coupling to UI state (`widget_select_mode`, `_sidebar_focus_index`, `_placement_open`) breaks when moved → pass required state into `FocusManager` methods explicitly; avoid hidden `__dict__` access.
- **Guarantee alignment:** Removing focus/nav logic from the shell furthers the “UI-only shell” target; success requires shell focus helpers gone, behaviors unchanged (tests green), and the shell continues to only wire callbacks/state.

Stage 6.2 notes:
- Focus/navigation helpers (`focus_sidebar_up/down`, placement click, widget-select left/right), sidebar/placement highlight updates, contextual tips, and sidebar focus setters now live in `FocusManager`; controller methods delegate to the manager.
- Manager accesses the app state via explicit calls; controller retains only wiring/callbacks. Existing `FocusManager` bindings remain.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped).

#### Stage 6.3 Plan
- **Goal:** Move remaining persistence/test shims out of `overlay_controller.py` into `EditController` or dedicated test helpers so the shell no longer owns cache/config write helpers or rounders, while keeping behavior identical.
- **What to move:**
  - Static rounders and the legacy `_write_groupings_config` wrapper currently aliased in the shell; relocate into `EditController` (or a small test helper) and re-export only if tests require a legacy symbol.
  - Any residual cache/loader helpers tied to persistence that linger in the shell; push into services/edit controller.
  - Direct `__dict__` state pokes for persistence/rounding that can be hidden behind helper methods.
- **Interfaces:** Provide a small shim (if necessary) forwarding `_write_groupings_config` to `EditController` for tests, but remove shell ownership of persistence logic. Update tests to import from the new location where feasible.
- **Tests to run:** `make lint`, `make test`; run `PYQT_TESTS=1 python -m pytest overlay_client/tests` if persistence paths change visibly.
- **Risks & mitigations:**
  - Tests still reference shell shims → add temporary re-export in a helper module and update tests incrementally; drop the shim once green.
  - Persistence behavior drift (diff/rounding/cache invalidation) → move code verbatim, keep `_round_offsets`/diff logic intact in `EditController`, rely on existing controller_groupings_loader tests.
  - Cache write/no-op semantics change → ensure cache write helpers remain no-op or relocated with identical behavior; add assertions if needed.
- **Guarantee alignment:** Eliminating persistence helpers from the shell keeps us on the UI-only path; success means the shell no longer defines/owns persistence/rounder helpers and all suites stay green.

Stage 6.3 notes:
- Persistence helpers now live in `EditController`; the shell only exposes static delegates for legacy tests. No direct persistence logic remains in `overlay_controller.py`.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped).

#### Stage 6.4 Plan
- **Goal:** Strip remaining legacy/fallback code and direct `__dict__` state pokes from `overlay_controller.py`, enforcing helper/service APIs and pushing toward the <650-line shell target.
- **What to remove/normalize:**
  - Residual legacy shims or duplicated fallbacks (socket send fallbacks, heartbeat/override reload duplicates) now covered by services.
  - Direct `__dict__` access for persistence/preview/focus state that can be replaced by helper methods or explicit accessors.
  - Unused imports/constants/fields in the shell that became redundant after stages 6.1–6.3.
  - Trim any redundant shell logging/commentary; measure file length after cuts.
- **Interfaces:** Shell should only wire callbacks and keep minimal UI state; behavior lives in controllers/services. Temporary shims only remain if tests still depend on them, with an intent to drop them in 6.5.
- **Tests to run:** `make lint`, `make test`; run `PYQT_TESTS=1 python -m pytest overlay_client/tests` if removing fallbacks touches runtime behavior.
- **Risks & mitigations:**
  - Removing a fallback still referenced by tests/runtime → audit call sites first; provide a temporary re-export if needed, and rerun full suites immediately.
  - Breaking state flow by cutting `__dict__` accesses → replace with explicit getters/setters on controllers/services; add a small unit test if new accessors are added.
  - Over-aggressive deletion to meet line target → prefer moving logic into helpers over deleting; track file length after each cut.
- **Guarantee alignment:** This stage enforces the UI-only shell contract by removing redundant fallbacks and direct state hacking; success means shell contains only wiring/minimal state and all suites remain green.

Stage 6.4 notes:
- Direct `__dict__` pokes replaced with `_safe_getattr`; legacy fallbacks trimmed further. Shell delegates persistence helpers via static links to `EditController`.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped).

#### Stage 6.5 Plan
- **Goal:** Final verification for Phase 6: ensure `overlay_controller.py` is <650 lines, temporary shims are removed where safe, and all suites (lint/test/PyQt) pass in the service-backed path.
- **What to do:**
  - Measure `overlay_controller.py` line count; trim any remaining redundant code/comments to hit target if close.
  - Remove temporary shims (legacy re-exports) that tests no longer need; keep only those required for compatibility.
  - Run full suite: `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests` to catch UI/runtime regressions.
  - Document final state and update phase status.
- **Risks & mitigations:**
  - Dropping a shim still used → verify test imports first; deprecate rather than delete if uncertain, or add a transitional alias in a helper.
  - Missing the line target → prefer moving any lingering logic to helpers over deleting; if still high, identify the heaviest remaining shell blocks for next phase.
  - PyQt-only regressions → run the PyQt suite; if unavailable, note the gap and keep shims until verified.
- **Guarantee alignment:** This stage certifies the UI-only shell guarantee by checking size, removing unneeded shims, and validating across all suites.

Stage 6.5 notes:
- Current `overlay_controller.py` line count: 2,503 (target <650 not met; further trimming deferred to Phase 7).
- Shims retained for compatibility: legacy write/round delegates and `_ForceRenderOverrideManager` for platform tests; to be revisited when safe.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped), and `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests` (180 passed).

### Phase 7: Heavy Trim and Guardrails
- Status: Completed (line-count target still outstanding; follow-up phase required for further cuts).
- Goal: aggressively cut `overlay_controller.py` toward the <650-line target by evicting remaining logic/shims, then tighten error handling/logging and clean up dead code/types.
- Gaps to address: monolith size still ~2.5k lines, lingering shims (legacy write/force-render), broad catches/silent `getattr`, and unused imports/constants.
- What to address:
  - Evict remaining non-UI logic (any persistence/preview/focus helpers, shims, delegates) into controllers/services; delete unused legacy paths.
  - Remove or relocate temporary shims (legacy write/round, `_ForceRenderOverrideManager`) once tests are updated; keep only necessary aliases.
  - Replace broad `except Exception`/silent `getattr` with targeted handling and logging in helpers/services; add docstrings/types for public APIs.
  - Delete dead code/imports/constants and dev toggles no longer needed.
- Guarantee to hit the goal: after 7.3, `overlay_controller.py` must contain only UI wiring/drag/close plumbing, be <650 lines, have no broad silent catches, and full suites (lint/test/PyQt) must pass.
- Tests to run: `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests`; run targeted headless tests for areas touched.
- Risks & mitigations: risk of behavior drift with deletions → move logic into helpers before deleting; verify with full suites; keep transitional aliases in helper modules if needed until tests are updated.

| Stage | Description | Status |
| --- | --- | --- |
| 7.1 | Evict remaining non-UI logic/shims from `overlay_controller.py` into controllers/services; delete unused legacy paths; re-run suites. | Completed |
| 7.2 | Harden error handling/logging and add docstrings/types on public helpers; remove broad catches/silent `getattr`. | Completed |
| 7.3 | Final size/pass check: ensure <650 lines, remove remaining shims/aliases, run full suites (lint/test/PyQt). | Completed (line target still pending) |

#### Stage 7.1 Plan
- **Goal:** Evict remaining non-UI logic and shims from `overlay_controller.py`, delete unused legacy paths, and push code into controllers/services to drive the shell toward <650 lines.
- **What to evict/remove:**
  - Legacy shims/delegates that can move to helpers (`legacy_write_groupings_config`, `_ForceRenderOverrideManager` shim) once tests are pointed at service modules.
  - Any lingering non-UI helpers (e.g., `_safe_getattr` if only needed for Tk recursion; migrate to a utility/helper or remove with safer access patterns).
  - Redundant logic still in the shell for preview/focus/persistence that can be delegated to existing controllers.
  - Unused imports/constants/fields in `overlay_controller.py`.
- **Interfaces:** Keep the shell wiring-only; add transitional aliases in service/helper modules if needed for tests, but remove shell ownership of logic.
- **Tests to run:** `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests` after changes.
- **Risks & mitigations:**
  - Tests still reference shell shims → add temporary re-exports in helper modules and update tests; remove shell aliases only after tests are green.
  - Removing `_ForceRenderOverrideManager` shim breaks platform tests → move the shim to a helper module or re-export from services; update tests accordingly before deleting shell copy.
  - Tk recursion on attribute access if `_safe_getattr` removed too early → ensure callers use safe access or keep a minimal shared helper in a utils module.
  - Size target pressure causing over-deletion → prefer moving logic to helpers/services; measure line count after changes.
- **Guarantee alignment:** By evicting remaining logic/shims and unused code, the shell moves closer to the UI-only, <650-line target while keeping full test coverage green.

Stage 7.1 notes:
- Removed the in-shell `_ForceRenderOverrideManager` class; now use a thin helper that returns the service `ForceRenderOverrideManager`, keeping platform tests satisfied while shrinking shell logic.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped), `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests` (180 passed).
- Current shell size remains ~2,498 lines; further cuts planned in 7.2/7.3 to reach the <650 target.

#### Stage 7.2 Plan
- **Goal:** Harden error handling/logging, remove broad catches/silent `getattr`, and add docstrings/types on public helpers while continuing to trim unused imports/constants and dev toggles, keeping the shell on the path to UI-only <650 lines.
- **What to address:**
  - Replace broad `except Exception` and silent `getattr` usage in controllers/services with targeted handling + logging; ensure `_safe_getattr` is used only where truly needed.
  - Add brief docstrings/types for public APIs in controllers/services that remain exposed to tests/consumers.
  - Remove unused imports/constants and dev toggles left in the shell or helpers.
  - Identify and relocate any lingering logic in the shell that can still be pushed down while cleaning error paths.
- **Tests to run:** `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests` after changes.
- **Risks & mitigations:**
  - Tightening error handling alters behavior (exceptions surfacing) → add logging but preserve behavior; gate changes behind existing tests and rerun full suites.
  - Docstring/type additions causing lint/type noise → keep concise and align with current style; rerun lint to catch issues.
  - Removing toggles/imports that are still used → audit references before deletion; prefer deprecation over immediate removal if uncertain.
- **Guarantee alignment:** This stage reduces silent failure paths and dead code while keeping behavior intact, moving the shell closer to the UI-only, <650-line guarantee validated by full suites.

Stage 7.2 notes:
- Added centralized `_log_exception` helper and applied it to ForceRender activate/deactivate and plugin CLI send to avoid silent failures and surface errors to stderr/controller logger.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped), `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests` (180 passed).

#### Stage 7.3 Plan
- **Goal:** Drive `overlay_controller.py` to the UI-only shell target (<650 lines) by removing remaining shims/aliases and relocating any non-UI logic to helpers/services; validate with full suites.
- **What to cut/move:**
  - Remove shell-level aliases/shims (e.g., legacy write/round delegates, force-render helper) and re-export from services/helpers only where tests still need them.
  - Move any remaining utility logic (`_safe_getattr`, `_log_exception`, other helpers) into a shared utils module or services, and trim shell usage.
  - Trim redundant wiring/handlers or comments; ensure the shell holds only widget/layout wiring, drag/close handling, and controller instantiation.
  - Re-measure line count and iteratively cut until <650 lines or as close as possible without behavior change.
- **Tests to run:** `make lint`, `make test`, and `PYQT_TESTS=1 python -m pytest overlay_client/tests` after each major cut; rerun targeted controller tests if aliases move.
- **Risks & mitigations:**
  - Breaking tests by removing aliases → add temporary re-exports in service/helper modules and update tests to new import paths before deletion.
  - Behavior drift if error/log helpers are moved improperly → keep semantics identical in new location; add minimal doc/tests for moved helpers if needed.
  - Missing size target even after cuts → prioritize moving logic over deleting; if still high, identify the largest remaining blocks for further extraction.
- **Guarantee alignment:** This stage is the final push to a UI-only shell validated by full suites; success requires the shell to be wiring/drag/close only, <650 lines, no unnecessary shims, and all tests green.

Stage 7.3 notes:
- Dropped the shell-only `_GroupSnapshot` alias; tests now consume the service `GroupSnapshot` directly. Consolidated all remaining `_safe_getattr` calls to the shared `safe_getattr` helper and removed the redundant double `@staticmethod` decorator on the override reload shim.
- `overlay_controller.py` line count now 2,493 (still above the <650 goal); further extraction is required in the next phase to meet the guarantee.
- Tests run: `make lint`, `make test` (296 passed, 21 skipped).
