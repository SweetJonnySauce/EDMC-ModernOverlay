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
- ForceRender fallback: `_ForceRenderOverrideManager` reads `overlay_settings.json` + `port.json`; `activate()` stores previous allow/force values, tries `force_render_override` over the socket (2s timeouts, waits for `status: ok`), and on failure defaults to False/False and writes settings directly with allow+force True. `deactivate()` restores the cached values, sends the CLI request, and always writes settings (logs to stderr when CLI unreachable).
- Existing coverage: `overlay_controller/tests/test_status_poll_mode_profile.py` verifies mode-profile clamping/reschedule; `tests/test_controller_override_reload.py` covers `controller_override_reload` debouncing/deduping; `overlay_client/tests/test_controller_active_group.py` exercises client handling of active-group signals. Heartbeat and force-render fallback currently untested.
- Tests run: `make check` (ruff, mypy, pytest) passing (284 passed, 21 skipped); `python -m pytest overlay_controller/tests` passing (25 passed, 3 skipped).

Stage 2.2 notes:
- Added `overlay_controller/services/plugin_bridge.py` with `PluginBridge` (port/settings resolution, CLI send helper, heartbeat send, active-group dedupe, override reload dedupe) and `ForceRenderOverrideManager` (socket-first override, fallback settings write when CLI unreachable).
- Port/settings paths default to repo-root `port.json`/`overlay_settings.json`; connect/logger/time are injectable for tests; CLI send uses 1.5s timeout, ignores failures, and keeps last active-group key `(plugin, label, anchor)` to avoid duplicates.
- Force-render manager preserves previous allow/force values (overridden by CLI response when present), attempts socket send with 2s timeout window, and writes settings on failure and after restore.
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
| 5.3 | Extract layout composition into `controller/layout.py` (placement/sidebar/overlays/focus map assembly); controller retains only callbacks/state. | Not started |
| 5.4 | Extract focus/binding orchestration into `controller/focus_manager.py` (focus map, widget-select mode, navigation handlers, binding registration); remove inline binding helpers. | Not started |
| 5.5 | Extract preview orchestration into `controller/preview_controller.py` (snapshot fetch, live-edit guards, target frame resolution, renderer invocation, absolute sync); drop duplicate preview helpers from the shell. | Not started |
| 5.6 | Extract edit/persistence flow into `controller/edit_controller.py` (persist_* hooks, debounces, cache reload guard, active-group/override signals, nonce/timestamps); move reload guards + cache diff helpers out of the shell. | Not started |
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
- **Interfaces:** `build_app_context(root: Path, use_legacy_bridge: bool, logger) -> AppContext` with resolved paths, services, mode profile, heartbeat interval, bridge, force-render override, and loader references.
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
