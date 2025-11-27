# Overlay Client Refactor Plan

This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.

## Refactoring rules
- Before touching code for a stage, write a short (3-5 line) stage summary in this file outlining intent, expected touch points, and what should not change.
- Always summarize the plan for a stage without making changes before proceeding.
- Even if a request says “do/implement the step,” you still need to follow all rules above (plan, summary, tests, approvals).
- If you find areas that need more unit tests, add them in to the update.
- Record which tests were run (and results) before marking a stage complete; if tests are skipped, note why and what to verify later.
- If a step is not small enough to be safe, stop and ask for direction.
- After each step is complete, run through all tests, update the plan here, and summarize what was done for the commit message.
- Each stage is uniquely numbered across all risks. Sub-steps will use dots. i.e. 2.1, 2.2, 2.2.1, 2.2.2
- All substeps need to be completed or otherwise handled before the parent step can be complete or we can move on.
- If you find areas that need more unit tests, add them in to the update.

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
- `overlay_client/overlay_client.py` co-locates async TCP client, Qt window/rendering, font loading, caching, follow logic, and entrypoint in one 5k-line module/class, violating single responsibility and making changes risky. Tracking stages to break this up:

  | Stage | Description | Status |
  | --- | --- | --- |
  | 1 | Extract `OverlayDataClient` into `overlay_client/data_client.py` with unchanged public API (`start/stop/send_cli_payload`), own logger, and narrow signal surface. Import it back into `overlay_client.py`. | Complete (extracted and imported; all documented tests passing, resolution run verified with overlay running) |
  | 2 | Move paint command types (`_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`) and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py`; keep signatures intact so `_paint_legacy` logic can stay as-is. | Complete (moved into `overlay_client/paint_commands.py`; all documented tests passing with overlay running for resolution test) |
  | 3 | Split platform and font helpers (`_initial_platform_context`, font resolution) into `overlay_client/platform_context.py` and `overlay_client/fonts.py`, keeping interfaces unchanged. | Complete (extracted; all documented tests passing with overlay running) |
  | 4 | Trim `OverlayWindow` to UI orchestration only; delegate pure calculations to extracted helpers. Update imports and ensure existing tests pass. | In progress |
| 4.1 | Map non-UI helpers in `OverlayWindow` (follow/geometry math, payload builders, viewport/anchor/scale helpers) and mark target extractions. | Complete |
| 4.2 | Extract follow/geometry calculation helpers into a module (no Qt types); wire `OverlayWindow` to use them; keep behavior unchanged. | Complete |
| 4.3 | Extract payload builder helpers (`_build_message_command/_rect/_vector` calculations, anchor/justification/offset utils) into a module, leaving painter/UI hookup in `OverlayWindow`. | Not started |
| 4.4 | Extract remaining pure utils (viewport/size/line width math) if still embedded. | Not started |
| 4.5 | After each extraction chunk, run full test suite and update Stage 4 log/status. | In progress |
  | 5 | Add/adjust unit tests in `overlay_client/tests` to cover extracted modules; run test suite and update any docs if behavior notes change. | In progress |
  | 5.1 | Add tests for `overlay_client/data_client.py` (queueing behavior and signal flow). | Complete |
  | 5.2 | Add tests for `overlay_client/paint_commands.py` (command rendering paths and vector adapter hooks). | Complete |
  | 5.3 | Add tests for `overlay_client/fonts.py` (font/emoji fallback resolution and duplicate suppression). | Complete |
  | 5.4 | Add tests for `overlay_client/platform_context.py` (env overrides applied over settings). | Complete |
  | 5.5 | Run resolution test after test additions and update logs/status. | Pending (overlay process required) |

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

#### Stage 4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 102 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (71 passed).
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

  Notes:
  - Perform refactor in small, behavior-preserving steps; avoid logic changes during extraction.
  - Keep entrypoint `main()` in `overlay_client.py` but reduce imports as modules move.
  - Prefer adding module-level docstrings or brief comments only where intent isn’t obvious.
- Long, branchy methods with mixed concerns: `_build_vector_command` (overlay_client/overlay_client.py:3851-4105), `_build_rect_command` (overlay_client/overlay_client.py:3623-3849), `_build_message_command` (overlay_client/overlay_client.py:3411-3621), `_apply_follow_state` (overlay_client/overlay_client.py:2199-2393); need smaller helpers and clearer data flow.
- Duplicate anchor/translation/justification workflows across the three builder methods (overlay_client/overlay_client.py:3411, :3623, :3851) risk behavioral drift; shared utilities would improve consistency.
- Heavy coupling of calculation logic to Qt state (e.g., QFont/QFontMetrics usage in `_build_message_command` at overlay_client/overlay_client.py:3469) reduces testability; pure helpers would help.
- Broad `except Exception` handlers in networking and cleanup paths (e.g., overlay_client/overlay_client.py:480, :454) silently swallow errors, hiding failures.
