## Goal: Allow the CMDR to define interval for named font sizes

## Requirements
- Add a configurable "font size step" option in the preferences pane; default value is 2.
- The font size step is stored as `legacy_font_step` and clamped to an integer 0–10.
- The step applies only to legacy named sizes so: small = normal - step, large = normal + step, huge = normal + (2 * step).
- Changing the step updates the overlay immediately (no restart).
- Add a "Preview" button that shows huge, large, normal, and small fonts on the overlay.
- Preview text auto-clears after a TTL (default 5 seconds).
- Conserve space in the preferences pane by placing the step input and Preview button inline after the font bounds controls.

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
| 1 | Add configurable font size step + preview UX | Completed |

## Phase Details

### Phase 1: Add configurable font size step + preview UX
- Keep existing font scaling behavior; only replace the hardcoded +/-2 with the configurable step.
- Update preferences persistence and the live overlay update path so changes apply immediately.
- Add a preview trigger that displays all four named sizes on the overlay.
- Risks: UI wiring regressions (preference not persisted or not applied live); preview text not cleared or conflicting with existing overlays.
- Mitigations: update a small unit test or add a targeted integration check around preset sizing, and verify in dev mode with preview on/off.
- Tests to run:
  - `source .venv/bin/activate && python -m pytest overlay_client/tests/test_window_utils.py`
  - `source .venv/bin/activate && python -m pytest tests/test_overlay_config_payload.py`
  - (if time) `source .venv/bin/activate && python -m pytest`

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Add the font size step preference (default 2) with persistence + validation | Completed |
| 1.2 | Replace legacy preset offsets to use the configured step | Completed |
| 1.3 | Apply step changes immediately in the overlay rendering path | Completed |
| 1.4 | Add Preview button to show huge/large/normal/small text on overlay | Completed |
