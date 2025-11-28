# Overlay Client Refactor Plan

This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.

## Refactoring rules
- Before touching code for a stage, write a short (3-5 line) stage summary in this file outlining intent, expected touch points, and what should not change.
- Always summarize the plan for a stage without making changes before proceeding.
- Even if a request says “do/implement the step,” you still need to follow all rules above (plan, summary, tests, approvals).
- If you find areas that need more unit tests, add them in to the update.
- When breaking down a key risk, add a table of numbered stages under that risk (or a top-level stage table) that starts after the last completed stage number, and keep each row small, behavior-preserving, and testable. Always log status and test results per stage as you complete them.
- Don't delete key risks once recorded; append new risks instead of removing existing entries.
- Put stage summaries and test results in the Stage summary/test results section in numerical order (by stage number).
- Record which tests were run (and results) before marking a stage complete; if tests are skipped, note why and what to verify later.
- Before running full-suite/refactor tests, ensure `overlay_client/.venv` is set up with GUI deps (e.g., PyQt6) and run commands using that venv’s Python.
- If a step is not small enough to be safe, stop and ask for direction.
- After each step is complete, run through all tests, update the plan here, and summarize what was done for the commit message.
- Each stage is uniquely numbered across all risks. Sub-steps will use dots. i.e. 2.1, 2.2, 2.2.1, 2.2.2
- All substeps need to be completed or otherwise handled before the parent step can be complete or we can move on.
- If you find areas that need more unit tests, add them in to the update.
- If a stage is bookkeeping-only (no code changes), call that out explicitly in the status/summary.

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
- Documentation: concise README/usage notes; explain non-obvious decisions; update docs alongside code.
- Tooling: automated formatting/linting/tests in CI; commit hooks for quick checks; steady dependency management.
- Performance awareness: efficient enough without premature micro-optimizations; measure before tuning.

## Testing (run after each refactor step):
- Restart EDMC, activate the venv, then:
```
source overlay_client/.venv/bin/activate
make check
make test
PYQT_TESTS=1 python -m pytest overlay_client/tests
python3 tests/run_resolution_tests.py --config tests/display_all.json
```

## Key readability/maintainability risks (ordered by importance):
- **A.** `overlay_client/overlay_client.py` co-locates async TCP client, Qt window/rendering, font loading, caching, follow logic, and entrypoint in one 5k-line module/class, violating single responsibility and making changes risky. Tracking stages to break this up:

  | Stage | Description | Status |
  | --- | --- | --- |
  | 1 | Extract `OverlayDataClient` into `overlay_client/data_client.py` with unchanged public API (`start/stop/send_cli_payload`), own logger, and narrow signal surface. Import it back into `overlay_client.py`. | Complete (extracted and imported; all documented tests passing, resolution run verified with overlay running) |
  | 2 | Move paint command types (`_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`) and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py`; keep signatures intact so `_paint_legacy` logic can stay as-is. | Complete (moved into `overlay_client/paint_commands.py`; all documented tests passing with overlay running for resolution test) |
  | 3 | Split platform and font helpers (`_initial_platform_context`, font resolution) into `overlay_client/platform_context.py` and `overlay_client/fonts.py`, keeping interfaces unchanged. | Complete (extracted; all documented tests passing with overlay running) |
  | 4 | Trim `OverlayWindow` to UI orchestration only; delegate pure calculations to extracted helpers. Update imports and ensure existing tests pass. | Complete |
  | 4.1 | Map non-UI helpers in `OverlayWindow` (follow/geometry math, payload builders, viewport/anchor/scale helpers) and mark target extractions. | Complete |
  | 4.2 | Extract follow/geometry calculation helpers into a module (no Qt types); wire `OverlayWindow` to use them; keep behavior unchanged. | Complete |
  | 4.3 | Extract payload builder helpers (`_build_message_command/_rect/_vector` calculations, anchor/justification/offset utils) into a module, leaving painter/UI hookup in `OverlayWindow`. | Complete |
  | 4.4 | Extract remaining pure utils (viewport/size/line width math) if still embedded. | Complete |
  | 4.5 | After each extraction chunk, run full test suite and update Stage 4 log/status. | Complete |
  | 5 | Add/adjust unit tests in `overlay_client/tests` to cover extracted modules; run test suite and update any docs if behavior notes change. | Complete |
  | 5.1 | Add tests for `overlay_client/data_client.py` (queueing behavior and signal flow). | Complete |
  | 5.2 | Add tests for `overlay_client/paint_commands.py` (command rendering paths and vector adapter hooks). | Complete |
  | 5.3 | Add tests for `overlay_client/fonts.py` (font/emoji fallback resolution and duplicate suppression). | Complete |
  | 5.4 | Add tests for `overlay_client/platform_context.py` (env overrides applied over settings). | Complete |
  | 5.5 | Run resolution test after test additions and update logs/status. | Complete |
  | 10 | Move `_compute_*_transform` helpers and related math into a pure module (no Qt types), leaving painter wiring in `OverlayWindow`; preserve behavior and logging. | Complete |
  | 10.1 | Map Qt vs. pure seams for `_compute_message/_rect/_vector_transform` and define the target pure module interface (inputs/outputs). | Complete (mapping documented; no code changes) |
  | 10.2 | Extract message transform calc to the pure module; leave font metrics/painter wiring in `OverlayWindow`; keep logging intact. | Complete |
  | 10.3 | Extract rect transform calc to the pure module; leave pen/brush/painter wiring in `OverlayWindow`; keep logging intact. | Complete |
  | 10.4 | Extract vector transform calc to the pure module; keep screen-point conversion and command assembly local; preserve logging/guards. | Complete |
  | 10.5 | Wire `OverlayWindow` to use the pure module for all three transforms; update imports and run staging tests. | Complete (bookkeeping/tests only; wiring already done) |
  | 10.6 | Add focused unit tests for the transform module to lock remap/anchor/translation behavior and guardrails (e.g., insufficient points). | Complete |
  | 11 | Extract follow/window orchestration (geometry application, WM overrides, transient parent/visibility) into a window-controller module to shrink `OverlayWindow`; keep Qt boundary localized. | Complete |
  | 11.1 | Map follow/window orchestration seams (what stays Qt-bound vs. pure) and define target controller interface/state handoff. | Complete (mapping only; no code changes) |
  | 11.2 | Create window-controller module scaffold with pure methods/structs; leave `OverlayWindow` behavior unchanged. | Complete (scaffold only; no wiring) |
  | 11.3 | Move geometry application/WM override resolution (setGeometry/move-to-screen/classification) into the controller; keep Qt calls contained. | Complete |
  | 11.4 | Move visibility/transient-parent/fullscreen-hint handling into the controller; keep Qt calls contained. | Complete |
  | 11.5 | Wire `OverlayWindow` to the controller for follow orchestration; update imports; preserve logging. | Complete (bookkeeping; already wired) |
  | 11.6 | Add focused tests around controller logic (override adoption, visibility decisions, transient parent) to lock behavior. | Complete |
  | 12 | Split payload/group coordination (grouping, cache/nudge plumbing) into a coordinator module so `overlay_client.py` keeps only minimal glue and entrypoint. | Complete (full-suite rerun pending PyQt6 availability) |
  | 12.1 | Map grouping/cache/nudge seams and inputs/outputs across `overlay_client.py`, `group_cache`, and settings/CLI hooks; document current logging and Qt boundaries. | Complete (mapping only; no code changes) |
  | 12.2 | Define coordinator interface (pure, no Qt) owning group selection, cache updates, nudge/backoff decisions, and outbound payload batching; decide injected callbacks for logging/send/settings. | Complete (interface defined; doc-only) |
  | 12.3 | Scaffold coordinator module and initial focused tests to lock current behaviors (group adoption, cache read/write, nudge gating) without wiring changes. | Complete (scaffold + tests; no wiring) |
  | 12.4 | Move non-Qt grouping/cache logic from `overlay_client.py` into the coordinator; preserve behavior/logging; adjust imports only. | Complete (delegated cache/nudge helpers; no UI wiring) |
  | 12.5 | Wire overlay client/window to use the coordinator via injected callbacks, keeping signal/slot behavior, logging, and threading assumptions unchanged. | Complete (group key usage delegated; behavior preserved) |
  | 12.6 | Expand coordinator tests for edge cases (missing groups, stale cache, retry/nudge cadence); rerun full suite and resolution test; log results. | Complete (tests added; full suite pending PyQt6) |

- **B.** Long, branchy methods with mixed concerns: `_build_vector_command` (overlay_client/overlay_client.py:3851-4105), `_build_rect_command` (overlay_client/overlay_client.py:3623-3849), `_build_message_command` (overlay_client/overlay_client.py:3411-3621), `_apply_follow_state` (overlay_client/overlay_client.py:2199-2393); need smaller helpers and clearer data flow.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 6 | Map logic segments and log/trace points in each long method; set refactor boundaries and identify Qt vs. pure sections. | Complete |
  | 7 | Refactor `_apply_follow_state` into smaller helpers (geometry classification, WM override handling, visibility) while preserving logging and Qt calls. | Complete |
  | 7.1 | Extract geometry normalization and logging: raw/native→Qt conversion, device ratio logs, title bar offset, aspect guard; keep Qt calls local. | Complete |
  | 7.2 | Extract WM override resolution and geometry application: setGeometry/move-to-screen, override classification/logging, and target adoption. | Complete |
  | 7.3 | Extract follow-state post-processing: follow-state persistence, transient parent handling, fullscreen hint, visibility/show/hide decisions. | Complete |
  | 8 | Split builder methods (`_build_message_command`, `_build_rect_command`, `_build_vector_command`) into calculation/render sub-helpers; keep font metrics/painter setup intact. | In progress |
  | 8.1 | Refactor `_build_message_command`: extract calculation helpers (transforms, offsets, anchors, bounds) while keeping font metrics/painter setup in place; preserve logging/tracing. | Complete |
  | 8.2 | Refactor `_build_rect_command`: extract geometry/anchor/translation helpers, leaving pen/brush setup and painter interactions in place; preserve logging/tracing. | Complete |
  | 8.3 | Refactor `_build_vector_command`: extract point remap/anchor/bounds helpers, leaving payload assembly and painter interactions in place; preserve logging/tracing. | Complete |
  | 8.4 | After each builder refactor, run full test suite and update logs/status. | Complete |
  | 9 | After each refactor chunk, run full test suite and update logs/status. | Complete |
  | 13 | Add unit tests for transform helpers (message/rect/vector) covering anchor/remap/translation paths and guardrails (e.g., insufficient points return `None`). | Planned |
  | 13.1 | Inventory existing transform helper coverage and define scenarios for anchors/remap/translation and guardrails (vector-point insufficiency, non-finite values). | Complete (mapping only; no code/tests) |
  | 13.2 | Add message transform helper tests (anchors, offsets, inverse scaling, translation) with trace callbacks asserting payload fields. | Complete |
  | 13.3 | Add rect transform helper tests for offsets/anchors/translation and base/reference bounds propagation. | Complete |
  | 13.4 | Add vector transform helper tests covering point remap, anchor translation, bounds accumulation, and insufficient-point guard returning `None`. | Complete |
  | 13.5 | Run full test suite (including PYQT_TESTS and resolution) and log results after additions. | Complete |
  | 14 | Add unit tests for follow-state helpers (`_normalise_tracker_geometry`, `_resolve_and_apply_geometry`, `_post_process_follow_state`) to lock behavior before further extractions. | Planned |
- **C.** Duplicate anchor/translation/justification workflows across the three builder methods (overlay_client/overlay_client.py:3411, :3623, :3851) risk behavioral drift; shared utilities would improve consistency.
 
  | Stage | Description | Status |
  | --- | --- | --- |
  | 15 | Consolidate anchor/translation/justification utilities into a shared helper used by all builders to keep payload alignment consistent. | Planned |
- **D.** Heavy coupling of calculation logic to Qt state (e.g., QFont/QFontMetrics usage in `_build_message_command` at overlay_client/overlay_client.py:3469) reduces testability; pure helpers would help.
 
  | Stage | Description | Status |
  | --- | --- | --- |
  | 16 | Re-audit builder/follow helpers to ensure calc paths operate on primitives only, with Qt boundaries wrapped at call sites; add headless coverage to enforce separation. | Planned |
- **E.** Broad `except Exception` handlers in networking and cleanup paths (e.g., overlay_client/overlay_client.py:480, :454) silently swallow errors, hiding failures.
 
  | Stage | Description | Status |
  | --- | --- | --- |
  | 17 | Replace broad exception catches with scoped handling/logging in networking/cleanup paths; surface actionable errors while keeping UI stable. | Planned |

----
# Stage Summary and Test results

### Stage 1 quick summary (intent)
- Goal: move `OverlayDataClient` into `overlay_client/data_client.py` with no behavior change.
- Keep public API identical (`start/stop/send_cli_payload`) and the same signals (`message_received`, `status_changed`); preserve backoff/queue behavior and release-mode log filtering.
- `overlay_client.py` should only switch to importing the extracted class; no UI or pipeline changes.
- Run the full test set listed below and record results before marking this stage complete.

#### Stage 1 test log (latest)
- Created venv at `overlay_client/.venv` and installed `requirements/dev.txt`.
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running; verified).

### Stage 2 quick summary (intent)
- Goal: move `_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`, and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py` with no behavior change.
- Keep signatures and call sites identical so `_paint_legacy` and related rendering paths remain unchanged.
- `overlay_client.py` should only adjust imports/references; avoid touching rendering logic beyond the move.
- Run full test set and record results after the extraction.

#### Stage 2 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 3 quick summary (intent)
- Goal: move `_initial_platform_context` and font resolution helpers (`_resolve_font_family`, `_resolve_emoji_font_families`, `_apply_font_fallbacks`) into `overlay_client/platform_context.py` and `overlay_client/fonts.py` without behavior changes.
- Keep function signatures and usage points the same; only adjust imports/wiring in `overlay_client.py`.
- Preserve logging behavior and font lookup/fallback logic exactly as before.
- Run the full test set and log results once the move is complete (including resolution test with overlay running).

#### Stage 3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 4 quick summary (intent)
- Goal: trim `OverlayWindow` to UI orchestration only by extracting pure calculations.
- Keep function signatures and usage points the same; only adjust imports/wiring in `overlay_client.py`.
- Preserve logging behavior and math/geometry logic exactly as before.
- Run the full test set and log results once the move is complete (including resolution test with overlay running).

Substeps:
- 4.1 Map non-UI helpers in `OverlayWindow` (follow/geometry math, payload builders, viewport/anchor/scale helpers) and mark target extractions.
- 4.2 Extract follow/geometry calculation helpers into a module (no Qt types); wire `OverlayWindow` to use them; keep behavior unchanged.
- 4.3 Extract payload builder helpers (`_build_message_command/_rect/_vector` calculations, anchor/justification/offset utils) into a module, leaving painter/UI hookup in `OverlayWindow`.
- 4.4 Extract remaining pure utils (viewport/size/line width math) if still embedded.
- 4.5 After each extraction chunk, run full test suite and update Stage 4 log/status.

#### Stage 4.2 quick summary (intent)
- Goal: move follow/geometry math (`_apply_title_bar_offset`, `_apply_aspect_guard`, `_convert_native_rect_to_qt`, and follow state calculations) into a helper module with only primitive types.
- Keep `OverlayWindow` responsible for Qt handles and window manager interactions; only swap in helpers for pure calculations and logging.
- Preserve log messages, override handling, and geometry normalization behavior exactly; no UI changes.
- Touch points: new helper module under `overlay_client`, updated imports/call sites in `overlay_client.py`, and Stage 4 status/test log updates here.

#### Stage 4.1 mapping (complete)
- Follow/geometry targets: `_apply_follow_state`, `_convert_native_rect_to_qt`, `_apply_title_bar_offset`, `_apply_aspect_guard`, related logging/override handling.
- Payload builder targets: `_build_message_command`, `_build_rect_command`, `_build_vector_command`, anchor/justification/offset and size/scale calculations within them.
- Other pure helpers still in `OverlayWindow`: `_line_width`, `_legacy_preset_point_size`, `_current_physical_size`, `_aspect_ratio_label`, `_compute_legacy_mapper`, viewport state helpers.

#### Stage 4.2 status (complete)
- Added `overlay_client/follow_geometry.py` with screen info dataclass and helpers for native-to-Qt rect conversion, title-bar offsets, aspect guard, and WM override resolution (primitive types only).
- `OverlayWindow` now calls those helpers via thin wrappers to preserve logging/state while keeping Qt/window operations local.
- Introduced `_screen_info_for_native_rect` to build conversion context without leaking Qt types into the helper module.

#### Stage 4.3 quick summary (intent)
- Goal: move payload builder calculations for messages/rects/vectors into a helper module (anchors, offsets, translations, bounds math) while leaving Qt painter wiring in `OverlayWindow`.
- Keep method signatures and observable behavior identical; preserve logging, tracing, and grouping/viewport interactions.
- Limit helpers to pure calculations and data assembly; keep QPainter/QPen/QBrush construction and font metric retrieval inside `OverlayWindow`.
- Touch points: new helper module under `overlay_client`, updated imports/wiring in `overlay_client.py`, docs/test log updates here.

#### Stage 4.3 status (complete)
- Added `overlay_client/payload_builders.py` with `build_group_context` to centralize group anchor/translation math for message/rect/vector builders.
- `OverlayWindow` now calls the helper for shared calculations, keeping Qt object creation and command construction local; behavior/logging preserved.

#### Stage 4.4 quick summary (intent)
- Goal: move remaining pure helpers (`_line_width`, `_legacy_preset_point_size`, `_current_physical_size`, `_aspect_ratio_label`, `_compute_legacy_mapper`, `_viewport_state` helpers) into a module, leaving Qt/UI wiring in `OverlayWindow`.
- Keep signatures and behavior identical; only delegate calculations and defaults to helpers using primitive inputs.
- Preserve logging and debug formatting; no changes to painter or widget interactions.
- Touch points: new helper module under `overlay_client`, updated imports/wiring in `overlay_client.py`, docs/test log updates here.

#### Stage 4.4 status (complete)
- Added `overlay_client/window_utils.py` with helpers for physical size, aspect labels, mapper/state construction, legacy preset sizing, and line widths (primitive-only).
- `OverlayWindow` now delegates to these helpers while keeping Qt/window handles local; method signatures unchanged.

#### Stage 5 status (complete)
- Added tests for `window_utils` covering physical size guards, aspect labels, mapper/state construction, preset font sizing, and line widths.
- Re-ran the full test suite (including resolution test) after additions.

#### Stage 4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 102 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (71 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

#### Stage 5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 5 quick summary (intent)
- Goal: add targeted unit tests for newly extracted modules:
  - `overlay_client/data_client.py`: payload queueing behavior and basic signal flow (with mocked connections).
  - `overlay_client/paint_commands.py`: paint commands and `_QtVectorPainterAdapter` call through to window hooks and painter methods.
  - `overlay_client/fonts.py`: font/emoji fallback resolution paths and duplicate suppression.
  - `overlay_client/platform_context.py`: env overrides applied over settings.
- No production logic changes; only tests and supporting stubs/mocks as needed.
- Run the full test set and log results once added.

#### Stage 5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 102 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → included above (PYQT_TESTS set during full run).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

#### Stage 6 mapping (complete)
- `_apply_follow_state`: raw geometry logging; native→Qt conversion + device ratio logs; title bar offset and aspect guard (helpers); WM override resolution; QRect/setGeometry/move-to-screen with logging; WM override classification/logging; follow-state update; transient parent handling; fullscreen hint; visibility/show/hide updates. Qt boundary: windowHandle/devicePixelRatio, QRect/frameGeometry/setGeometry/move/show/hide/raise_.
- `_build_message_command`: size/color parsing; group context (viewport + offsets); inverse group scale for anchors; remap + offsets; translation; font setup + metrics (Qt boundary: QFont/QFontMetrics); pixel/bounds and overlay bounds; tracing (`paint:message_input/translation/output`); command assembly.
- `_build_rect_command`: color parsing; QPen/QBrush setup (Qt boundary); group context; rect remap + offsets; inverse group scale + translation; anchor transform; overlay/base bounds; pixel bounds; tracing (`paint:rect_input/translation/output`); command assembly.
- `_build_vector_command`: trace flags; group context offsets/anchors/translation; raw points min lookup; remap_vector_points + offsets; inverse group scale + translation; overlay/base bounds accumulation; anchor transform; screen point conversion; tracing (`paint:scale_factors/raw_points/vector_translation`); command assembly.

#### Stage 7.1 status (complete)
- Introduced `_normalise_tracker_geometry` to handle raw geometry logging, native→Qt conversion + device ratio diagnostics, title bar offset, and aspect guard application while keeping Qt calls local.
- `_apply_follow_state` now delegates the normalization block; behavior and logging unchanged.

#### Stage 7.2 status (complete)
- Added `_resolve_and_apply_geometry` to handle WM override resolution, geometry application/setGeometry/move-to-screen, override classification/logging, and target adoption; `_apply_follow_state` now delegates this block.
- Behavior and logging preserved; `_last_geometry_log` and override handling remain unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, `python3 tests/run_resolution_tests.py --config tests/display_all.json`.

#### Stage 7.3 status (complete)
- Added `_post_process_follow_state` to handle follow-state persistence, transient parent handling, fullscreen hint emission, and visibility/show/hide decisions; `_apply_follow_state` delegates to it.
- Behavior and logging preserved; follow visibility and transient parent flows unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, `python3 tests/run_resolution_tests.py --config tests/display_all.json`.

### Stage 8 quick summary (intent)
- Goal: split builder methods into calculation/render sub-helpers while keeping font metrics/painter setup in place; preserve logging/tracing and behavior.
- Work through message, rect, and vector builders in small, testable steps; run full tests after each chunk.

#### Stage 8.1 status (complete)
- Added `_compute_message_transform` to handle message payload remap/offset/anchor/translation calculations and tracing; `_build_message_command` now delegates pre-metrics math to the helper (Qt font metrics remain local).
- Behavior and logging unchanged.

#### Stage 8.2 status (complete)
- Added `_compute_rect_transform` to handle rect remap/offset/anchor/translation calculations, base/reference bounds, and tracing; `_build_rect_command` now delegates geometry math while keeping pen/brush setup local.
- Behavior and logging unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`; resolution test not rerun in this stage.

#### Stage 8.3 status (complete)
- Added `_compute_vector_transform` to handle vector remap/offset/anchor/translation, bounds accumulation, and tracing; `_build_vector_command` now delegates calculation while keeping payload assembly/painter interactions local.
- Behavior and logging unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`; resolution test not rerun in this stage.

#### Stage 8 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 9 quick summary (intent)
- Goal: run the full test suite after the Stage 8 refactors and update logs/status.
- Includes resolution test with overlay running.

#### Stage 9 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 10.1 quick summary (intent and mapping)
- Mapped `_compute_message_transform`, `_compute_rect_transform`, `_compute_vector_transform` seams: all current math is pure (no Qt types); Qt stays where painter/font/pen/brush and command assembly occur.
- Target pure module API: three functions mirroring current helpers, operating on primitives/group contexts and accepting injected trace/log callbacks; return transformed logical points/bounds, effective anchors, translations, and (for vectors) screen-point tuples and optional trace fn; guard that insufficient vector points returns `None`.
- Qt boundaries to keep in `OverlayWindow`: QFont/QFontMetrics usage, QPen/QBrush creation, QPainter interactions, and command object construction.
- No code changes; this is a mapping/documentation step only.

#### Stage 10.1 test log (latest)
- Not run (documentation-only mapping).

### Stage 10.2 quick summary (status)
- Created `overlay_client/transform_helpers.py` with pure helpers `apply_inverse_group_scale` and `compute_message_transform` (no Qt types); preserved logging via injected trace callback.
- `_compute_message_transform` in `OverlayWindow` now delegates to the pure helper; painter/font handling and command assembly remain local.
- Behavior and logging preserved; inverse group scaling reused via the new helper.

#### Stage 10.2 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.3 quick summary (status)
- Added `compute_rect_transform` to `overlay_client/transform_helpers.py` (pure math, optional trace callback); reused shared inverse group scaling.
- `_compute_rect_transform` in `OverlayWindow` now delegates to the pure helper; pen/brush/painter work and command assembly stay local; logging preserved.

#### Stage 10.3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.4 quick summary (status)
- Added `compute_vector_transform` to `overlay_client/transform_helpers.py` (pure math/remap/bounds/anchor with optional trace callback); preserves insufficient-point guard.
- `_compute_vector_transform` now delegates to the pure helper; screen-point conversion and command assembly remain in `OverlayWindow`; logging preserved.

#### Stage 10.4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.5 quick summary (status)
- All three transform helpers now come from `overlay_client/transform_helpers.py`; `OverlayWindow` uses them via injected trace callbacks, keeping Qt/painter wiring local.
- Imports cleaned; util helpers now the single path for message/rect/vector calculations.

#### Stage 10.5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.6 quick summary (status)
- Added `overlay_client/tests/test_transform_helpers.py` covering `apply_inverse_group_scale`, and message/rect/vector transform helpers (offsets, inverse scaling/translation, bounds, insufficient-point guard, trace callbacks).
- Ensures pure helpers behave consistently before further refactors.

#### Stage 10.6 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.1 quick summary (intent and mapping)
- Goal: define Qt vs. pure seams for follow/window orchestration and the target controller interface.
- Qt-bound: `windowHandle()` interactions (setScreen, devicePixelRatio), `QRect`/`QScreen` usage, `frameGeometry`, `setGeometry`, `move/show/hide/raise_`, transient parent creation (`QWindow.fromWinId`), and platform controller hooks.
- Pure/controller-friendly: WM override resolution, geometry classification/adoption, follow-state persistence, visibility decision (`should_show`), title bar offset/aspect guard inputs/outputs, last-state caching/logging keys.
- Target controller API: methods for `normalize_tracker_geometry(state) -> (tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple)`, `resolve_and_apply_geometry(tracker_qt_tuple, desired_tuple) -> target_tuple`, `post_process_follow_state(state, target_tuple) -> visibility decision + follow state updates`, plus callbacks/injections for logging, WM override getters/setters, and Qt geometry application delegated via thin lambdas.
- No code changes; mapping-only step.

#### Stage 11.1 test log (latest)
- Not run (documentation-only mapping).

### Stage 11.2 quick summary (status)
- Added scaffold `overlay_client/window_controller.py` with pure types (`Geometry`, `NormalisationInfo`, `FollowContext`) and a `WindowController` shell that will host follow/window orchestration; includes logging/state placeholders only.
- No wiring yet; behavior unchanged in `OverlayWindow`.

#### Stage 11.2 test log (latest)
- Not run (scaffold only; no behavior change).

### Stage 11.3 quick summary (status)
- Implemented geometry/WM override orchestration in `WindowController.resolve_and_apply_geometry` (pure; uses injected callbacks for Qt operations and logging); preserved override resolution flow.
- `_resolve_and_apply_geometry` now delegates to the controller with callbacks for move/set geometry, classification logging, and WM override bookkeeping; behavior/logging preserved.
- Fixed regression risk: `_last_set_geometry` is now updated before `setGeometry` via the controller callback to prevent resizeEvent from reverting to stale sizes during follow updates.

#### Stage 11.3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.4 quick summary (status)
- Moved follow post-processing into `WindowController.post_process_follow_state` with callbacks for visibility updates, auto-scale, transient parent, and fullscreen hint; preserves Linux fullscreen hint logging.
- `_post_process_follow_state` now delegates to the controller; logging/behavior unchanged.

#### Stage 11.4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.5 quick summary (status)
- Controller now handles geometry and post-processing; `OverlayWindow` delegates follow orchestration to it. No further code changes; bookkeeping only.

#### Stage 11.5 test log (latest)
- Not rerun (no code changes).

### Stage 11.6 quick summary (status)
- Added `overlay_client/tests/test_window_controller.py` covering geometry override adoption, WM override bookkeeping, visibility decisions, transient parent callbacks, and fullscreen hint logging via controller APIs.
- Locks controller behavior before further refactors.

#### Stage 11.6 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 117 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 12.1 quick summary (mapping)
- Grouping inputs live in `overlay_client/overlay_client.py` via `GroupingAdapter`/`FillGroupingHelper` and `GroupTransform` (per-item `group_key`, transform lookup, override patterns, and viewport build helpers), plus dev/debug group tracing and bounds state (`_group_log_pending_*`, `_group_log_next_allowed`, `_logged_group_*`).
- Cache plumbing: `GroupPlacementCache` (init via `resolve_cache_path` → `overlay_group_cache.json`) updated through `_update_group_cache_from_payloads` driven by render results (`cache_base_payloads`, `cache_transform_payloads`), populated after throttled logging in `_apply_group_logging_payloads`.
- Nudge gating: settings/CLI feed `set_payload_nudge` (flags + gutter); `_compute_group_nudges` and `_apply_group_nudges_to_overlay_bounds` compute/apply translations per group when enabled; payloads carry `nudge_dx/dy` and `nudged` into cache/logs and debug overlays.
- Qt boundaries are minimal here: grouping/cache/nudge logic is pure (no Qt types), consumed by builders/render paths that attach to QPainter/QWindow elsewhere; logging uses standard logger with throttling keys.

#### Stage 12.1 test log (latest)
- Not run (mapping-only documentation update).

### Stage 12.2 quick summary (interface definition)
- Coordinator will be pure (no Qt) and manage: per-item group resolution (`group_key` lookup + override pattern), active group tracking, cache updates (base + transform payloads), nudge/backoff decisions, and outbound payload batching/context assembly for renderers.
- Inputs: grouping helper/adapter callbacks (`group_key_for`, `transform_for_item`, override pattern resolver), settings/CLI flags (nudge enabled/gutter, dev/debug toggles), cache path and IO hooks, and current payload/render outputs (bounds by group, anchor translations, overlay bounds, cache payloads).
- Outputs: per-group context/results (transforms, anchor translations, nudge deltas, cache payloads) and logging/throttle events to be consumed by render/builders; should expose methods to apply throttled group logging and cache writes and to compute nudge translations.
- Injected callbacks: logging (info/debug), time source (for throttling), cache read/write (via `GroupPlacementCache`), grouping helper/adapter hooks, and a hook to emit payloads to the sender when batching is needed. Threading assumptions stay the same (called from existing overlay client paths).
- No code changes yet; this defines the contract to implement in Stage 12.3 scaffolding.

#### Stage 12.2 test log (latest)
- Not run (interface/mapping only).

### Stage 12.3 quick summary (status)
- Added `overlay_client/group_coordinator.py` with pure helpers for group key resolution, cache payload normalization/write-through, and nudge translation calculations; no Qt or wiring changes.
- Added `overlay_client/tests/test_group_coordinator.py` covering override/fallback key resolution, cache normalization/write shape, and nudge gating.
- Behavior unchanged; overlay client still uses legacy paths for now.

#### Stage 12.3 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.

### Stage 12.4 quick summary (status)
- Delegated cache updates and group nudge calculations in `overlay_client.py` to `GroupCoordinator`; instantiated coordinator with existing group cache/logger.
- Removed duplicate cache/nudge helpers from `OverlayWindow`; kept behavior/logging intact and no Qt wiring changes yet.

#### Stage 12.4 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.
- `python3 -m pytest overlay_client/tests` → failed at collection (PyQt6 missing in environment); rerun full suite once PyQt6 is available.

### Stage 12.5 quick summary (status)
- `OverlayWindow` now uses `GroupCoordinator.resolve_group_key` for per-item grouping while retaining `FillGroupingHelper` for transform lookup; coordinator already handles cache updates and nudge calculations.
- Behavior/logging preserved; no Qt wiring changes introduced.

#### Stage 12.5 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.
- Full suite not rerun here (PyQt6 absent in environment); rerun once available.

### Stage 12.6 quick summary (status)
- Added edge-case coverage to `overlay_client/tests/test_group_coordinator.py` for missing transform payloads, override errors (fallback), invalid/overflow bounds, and cache-less no-op; coordinator behavior unchanged.
- Full wiring unchanged; this locks coordinator semantics before further moves.

#### Stage 12.6 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/acknowledgements and resolution sweep completed).

### Stage 12 overall status
- All substeps (12.1–12.6) completed: coordinator scaffolded, cache/nudge logic delegated, group key resolution wired, and coordinator edge cases covered by tests.
- Full project test suite and resolution test rerun with PyQt6 available in the venv; all passing.

### Stage 13 quick summary (intent)
- Goal: lock down `transform_helpers` (message/rect/vector) with focused unit tests covering anchors, remap, offsets/translation, inverse group scaling, and guardrails (e.g., insufficient vector points returns `None`).
- Approach: map current coverage gaps, add per-helper tests with trace callbacks asserting payload fields and bounds propagation, and rerun full suite (PYQT_TESTS + resolution).
- No production code changes expected; tests-only with current helper behavior as oracle.

### Stage 13.1 quick summary (mapping)
- Current transform helper tests cover: inverse group scale basic; message transform offsets/translation without anchors/remap; rect transform inverse scale + translation in fill mode; vector insufficient points guard; vector basic offsets/bounds with trace.
- Gaps to cover: message/rect/vector anchor translation paths with `group_transform`/anchor tokens; remap via `transform_context` (scale/offset) including non-default base offsets; collect_only path and trace callbacks for all helpers; guardrails for non-finite inputs; vector translation/bounds when anchor selected and base/reference bounds differ.
- Target scenarios for 13.2–13.4: message with anchor_for_transform/base anchors, offsets, and inverse scaling; rect with anchor translation and reference bounds propagation; vector with remap + anchor translation + base/reference bounds and insufficient points returning `None`.

#### Stage 13.1 test log (latest)
- Not run (mapping/documentation only).

### Stage 13.2 quick summary (status)
- Added message transform test covering anchor usage and transform_meta remap (scale/offset) with trace callback assertions; uses base/anchor inputs and confirms translations remain zero when expected.
- No production code changes; tests only.

#### Stage 13.2 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (7 tests).

### Stage 13.3 quick summary (status)
- Added rect transform test covering anchor-aware inputs with transform_meta remap, asserting base/reference bounds and translation logging remain consistent (no production changes).

#### Stage 13.3 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (8 tests).

### Stage 13.4 quick summary (status)
- Added vector transform test covering remap + anchor translation, bounds accumulation, and trace callback path; guardrails for insufficient points already covered earlier.
- Tests only; no production changes.

#### Stage 13.4 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (9 tests).

### Stage 13.5 quick summary (status)
- Full suite rerun after transform helper test additions with venv PyQt6: lint/typecheck/pytest, PYQT_TESTS, and resolution tests all passing.

#### Stage 13.5 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

  Notes:
  - Perform refactor in small, behavior-preserving steps; avoid logic changes during extraction.
  - Keep entrypoint `main()` in `overlay_client.py` but reduce imports as modules move.
  - Prefer adding module-level docstrings or brief comments only where intent isn’t obvious.
