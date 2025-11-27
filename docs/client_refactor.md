# Overlay Client Refactor Plan

> This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.


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
  | 1 | Extract `OverlayDataClient` into `overlay_client/data_client.py` with unchanged public API (`start/stop/send_cli_payload`), own logger, and narrow signal surface. Import it back into `overlay_client.py`. | Not started |
  | 2 | Move paint command types (`_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`) and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py`; keep signatures intact so `_paint_legacy` logic can stay as-is. | Not started |
  | 3 | Split platform and font helpers (`_initial_platform_context`, font resolution) into `overlay_client/platform_context.py` and `overlay_client/fonts.py`, keeping interfaces unchanged. | Not started |
  | 4 | Trim `OverlayWindow` to UI orchestration only; delegate pure calculations to extracted helpers. Update imports and ensure existing tests pass. | Not started |
  | 5 | Add/adjust unit tests in `overlay_client/tests` to cover extracted modules; run test suite and update any docs if behavior notes change. | Not started |

  Notes:
  - Perform refactor in small, behavior-preserving steps; avoid logic changes during extraction.
  - Keep entrypoint `main()` in `overlay_client.py` but reduce imports as modules move.
  - Prefer adding module-level docstrings or brief comments only where intent isn’t obvious.
- Long, branchy methods with mixed concerns: `_build_vector_command` (overlay_client/overlay_client.py:3851-4105), `_build_rect_command` (overlay_client/overlay_client.py:3623-3849), `_build_message_command` (overlay_client/overlay_client.py:3411-3621), `_apply_follow_state` (overlay_client/overlay_client.py:2199-2393); need smaller helpers and clearer data flow.
- Duplicate anchor/translation/justification workflows across the three builder methods (overlay_client/overlay_client.py:3411, :3623, :3851) risk behavioral drift; shared utilities would improve consistency.
- Heavy coupling of calculation logic to Qt state (e.g., QFont/QFontMetrics usage in `_build_message_command` at overlay_client/overlay_client.py:3469) reduces testability; pure helpers would help.
- Broad `except Exception` handlers in networking and cleanup paths (e.g., overlay_client/overlay_client.py:480, :454) silently swallow errors, hiding failures.
