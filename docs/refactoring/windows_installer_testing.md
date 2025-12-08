## Goal: Break up the Monolith

## Refactorer Persona
- Bias toward carving out modules aggressively while guarding behavior: no feature changes, no silent regressions.
- Prefer pure/push-down seams, explicit interfaces, and fast feedback loops (tests + dev-mode toggles) before deleting code from the monolith.
- Treat risky edges (I/O, timers, sockets, UI focus) as contract-driven: write down invariants, probe with tests, and keep escape hatches to revert quickly.
- Default to "lift then prove" refactors: move code intact behind an API, add coverage, then trim/reshape once behavior is anchored.
- Resolve the "be aggressive" vs. "keep changes small" tension by staging extractions: lift intact, add tests, then slim in follow-ups so each step stays behavior-scoped and reversible.
- Track progress with per-phase tables of stages (stage #, description, status). Mark each stage as completed when done; when all stages in a phase are complete, flip the phase status to "Completed."
- Personal rule: if asked to "Implement.", expand/document the plan and stages (including tests to run) before touching code.
- Personal rule: keep notes ordered by phase, then by stage within that phase.

## Dev Best Practices

- Keep changes small and behavior-scoped; prefer feature flags/dev-mode toggles for risky tweaks.
- Plan before coding: note touch points, expected unchanged behavior, and tests you'll run.
- Avoid UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.

## Per-Iteration Test Plan
- **Env setup (once per machine):** `python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -e .[dev]`
- **Headless quick pass (default for each step):** `source .venv/bin/activate && python -m pytest` (scope with `tests/.` or `-k` as needed).
- **Core project checks:** `make check` (lint/typecheck/pytest defaults) and `make test` (project test target) from repo root.
- **Full suite with GUI deps (as applicable):** ensure GUI/runtime deps are installed (e.g., PyQt for Qt projects), then set the required env flag (e.g., `PYQT_TESTS=1`) and run the full suite.
- **Targeted filters:** use `-k` to scope to touched areas; document skips (e.g., long-running/system tests) with reasons.
- **After wiring changes:** rerun headless tests plus the full GUI-enabled suite once per milestone to catch integration regressions.

## Guiding Traits for Readable, Maintainable Code
- Clarity first: simple, direct logic; avoid clever tricks; prefer small functions with clear names.
- Consistent style: stable formatting, naming conventions, and file structure; follow project style guides/linters.
- Intent made explicit: meaningful names; brief comments only where intent isn't obvious; docstrings for public APIs.
- Single responsibility: each module/class/function does one thing; separate concerns; minimize side effects.
- Predictable control flow: limited branching depth; early returns for guard clauses; avoid deeply nested code.
- Good boundaries: clear interfaces; avoid leaking implementation details; use types or assertions to define expectations.
- DRY but pragmatic: share common logic without over-abstracting; duplicate only when it improves clarity.
- Small surfaces: limit global state; keep public APIs minimal; prefer immutability where practical.
- Testability: code structured so it's easy to unit/integration test; deterministic behavior; clear seams for injecting dependencies.
- Error handling: explicit failure paths; helpful messages; avoid silent catches; clean resource management.
- Observability: surface guarded fallbacks/edge conditions with trace/log hooks so silent behavior changes don't hide regressions.
- Documentation: concise README/usage notes; explain non-obvious decisions; update docs alongside code.
- Tooling: automated formatting/linting/tests in CI; commit hooks for quick checks; steady dependency management.
- Performance awareness: efficient enough without premature micro-optimizations; measure before tuning.

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |

## Phase Details

### Phase N: Title Placeholder
- Describe the extraction/decoupling goal for this phase.
- Note the APIs you intend to introduce and the behaviors that must remain unchanged.
- Call out edge cases and invariants that need tests before and after the move.
- Risks: list potential regressions unique to this phase.
- Mitigations: planned tests, flags, and rollout steps to contain those risks.

| Stage | Description | Status |
| --- | --- | --- |

## Windows Installer Testing Summary
- Goal: add repeatable CI coverage for `scripts/install_windows.ps1` via Pester on `windows-latest`.
- Approach: dot-source installer with `MODERN_OVERLAY_INSTALLER_IMPORT=1`, mock side-effectful functions, assert venv handling.
- State: tests still failing in CI due to loader issues (path resolution and missing/mocked functions).

## Errors / Problems Encountered
- Inbox Pester 3.4.0 conflicts: legacy parameter warnings and missing modern `Mock`/`Should -Invoke`.
- Null path during `BeforeAll` when resolving `scripts/install_windows.ps1` (`ParameterBindingValidationException`).
- `Prompt-YesNo` not found when installer functions were not loaded before mocks.
- Legacy Pester parameter set usage (`-CI` with `-OutputFormat`) caused incompatible invocation.
- Release EXE integrity check failed because `checksums.txt` expected `.gitignore`, which is omitted from the packaged payload.

## Actions Taken So Far
- Added `MODERN_OVERLAY_INSTALLER_SKIP_PIP` to skip pip installs during tests.
- Created Pester suite `tests/install_windows.Tests.ps1` covering venv rebuild/creation with mocks and dummy files.
- CI: added `windows-installer-tests` job to install/import Pester 5.5+, emit version, run tests with NUnit output.
- Adjusted test harness: explicit env flags, robust path resolution, loader in `BeforeAll`, explicit `-CommandName` mocks.
- Updated workflow to use Pester 5 configuration object (no legacy params) and to trust PSGallery for module install.
- Updated `scripts/generate_checksums.py` to exclude `.gitignore` from manifests so EXE integrity checks ignore git metadata files that aren't packaged.
- Tests seed the global `PythonSpec` variable before invoking installer functions to avoid null `-Python` bindings.
- Introduced single-source exclude manifest at `scripts/release_excludes.json`; release packaging, checksum generation, and EXE builds are being aligned to consume it.

## Plan to Resolve Outstanding Issues

### Phase 1: Stabilize Loader (High Priority)
- Echo resolved paths (test file, repo root, installer) in `BeforeAll`; fail fast if any are empty.
- Add fallbacks: use `git rev-parse --show-toplevel` or `$env:GITHUB_WORKSPACE` when `PSCommandPath`/`MyInvocation` are unavailable.
- Ensure dot-sourcing completes before any `Mock` calls; skip the suite with a clear message if loader fails.
- **Done:** Added verbose path resolution and fallbacks in `tests/install_windows.Tests.ps1` (logging test path and repo root, using git/GITHUB_WORKSPACE fallback).
- **Done:** Store resolved paths in script-scoped variables and reuse them in `BeforeAll` to avoid null installer paths; added additional repo-root fallbacks inside `BeforeAll` plus logging of installer path.

### Phase 2: Eliminate Pester 3 Influence
- In workflow, run under `pwsh -NoLogo -NoProfile`, `Remove-Module Pester -ErrorAction SilentlyContinue`, then import Pester 5.5+.
- Add an early version assertion in tests that aborts once with a clear error when Pester <5.5 is present.
- **Done:** Workflow now removes Pester 3 and imports 5.5+ with logging; test script prints Pester version on start.

### Phase 3: Strengthen Mocks and Fixtures
- Use `InModuleScope` or module-qualified `Mock` for installer functions (`Prompt-YesNo`, `Invoke-Python`, `Write-Info`) to guarantee visibility.
- Add a small fixture helper to create expected folders/files (overlay_client, requirements/base.txt, .venv/Scripts/python.exe) to avoid missed prerequisites.
- **In progress:** Tests now seed the global `PythonSpec` variable before invoking installer functions to avoid null `-Python` bindings.

### Phase 4: Diagnostics and Artifacts
- Log resolved paths and Pester version in CI output; keep NUnit XML artifact for debugging.
- Gate verbose diagnostics behind an env var so they can be pruned once green.

### Phase 5: Green Run and Cleanup
- Re-run Windows installer job; if green, trim extra logging and note the working versions/commands here.
- Success criteria: Windows installer tests job passes consistently without path or mock resolution errors.
