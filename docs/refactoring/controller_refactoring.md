## Goal: Break up the Overlay Controller Monolith

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

### Phase 2: Plugin Bridge and Mode Timers
- Create `services/plugin_bridge.py` for CLI/socket messaging, heartbeat, active-group, and override-reload signals (including `ForceRenderOverrideManager`).
- Create `services/mode_timers.py` to own `ControllerModeProfile` application, poll interval management, debounced writes, and heartbeat scheduling via callbacks.
- UI supplies callbacks (e.g., `poll_cache`, `flush_config`) and receives events; timers and sockets stop living on the Tk class.

### Phase 3: Preview Math and Renderer
- Move anchor/translation math, target-frame resolution, and fill-mode translation into `preview/snapshot_math.py` (pure functions).
- Build a `PreviewRenderer` class in `preview/renderer.py` that draws onto a Tk canvas given a snapshot + viewport; no file or state access.
- Point `overlay_controller/tests/test_snapshot_translation.py` at the new math module; add tests if gaps appear.

### Phase 4: Widget Extraction
- Relocate `IdPrefixGroupWidget`, `OffsetSelectorWidget`, `AbsoluteXYWidget`, `AnchorSelectorWidget`, `JustificationWidget`, and `SidebarTipHelper` into a `widgets/` package.
- Keep only layout/wiring in the main file; widgets expose callbacks for selection/change/focus and remain self-contained.
- Preserve behaviors/bindings; adjust imports in tests and app shell.

### Phase 5: App Shell Slimdown and Tests
- Leave `overlay_controller.py` as a thin `OverlayConfigApp` shell: layout, focus/drag handling, and orchestration of services/widgets.
- Rewrite wiring to use the extracted services; remove direct JSON/socket/timer math from the Tk class.
- Update or add tests around new seams (service unit tests + minimal integration harness for the shell).
