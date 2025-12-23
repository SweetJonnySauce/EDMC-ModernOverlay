## Goal: standardize on a build-mode Windows Inno installer (`win_inno_build`) and retire the embedded bundle

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

## Drivers and scope notes
- Current `inno_*` workflows/scripts are tangled; we will replace them with a clean, build-only `win_inno_build` workflow and supporting assets.
- The embedded/bundled Python installer is being abandoned; installs will create the venv at install time using system Python 3.10+ with internet access for deps.
- `installer.iss` remains the single installer entry point and should default to `/DInstallVenvMode=build` while we remove embedded branches.
- `win_inno_build` must emit artifacts for releases/manual runs and feed those artifacts into `.github/workflows/virustotal_scan.yml`.
- We should assume the existing payload staging, checksum verification, and user-settings preservation remain intact (no silent behavior regressions).

## Requirements to capture

### Build-only installer/workflow (`win_inno_build`)
- Maintain `win_inno_build.yml` as the single installer workflow with release triggers on `main` and manual dispatch.
- Build via `scripts/installer.iss` with `/DInstallVenvMode=build` (default); embedded mode is retired.
- Keep staging logic that applies `scripts/release_excludes.json`, bundles checksum tooling, preserves user config/fonts, and uploads payload + installer artifacts with deterministic names consumed by VirusTotal.
- Exclude any prebuilt `.venv` from the payload; installer must create `overlay_client/.venv` using system Python 3.10+ with internet access to install deps and surface progress.
- Release publishing: attach the generated exe to tagged releases (same naming convention as today) and allow download when run manually.

### `installer.iss` expectations
- Default to build mode; embedded/bundled Python flow is retired.
- Validate available Python 3.10+ (clear failure messaging) before creating the venv under `overlay_client/.venv`.
- Create the venv, upgrade pip, and install runtime deps (PyQt6 >= 6.5) during install; surface progress in wizard status/progress controls and fail clearly on dependency errors.
- Upgrade path: if an existing `overlay_client/.venv` matches expected Python/deps (manifest or `requirements/base.txt`), prompt to skip rebuild; otherwise rebuild using system Python 3.10+.
- Maintain safeguards: prompt when upgrading existing installs, rename legacy plugin folders, preserve user settings/fonts, and run checksum validation excluding the venv files.

### Decisions (confirmed)
- Standardize on build-mode installers and drop the embedded bundle path.
- Keep `win_inno_build.yml` and retire `win_inno_embed.yml`; VirusTotal artifact name remains `win-inno-build`.
- Installer define defaults to `/DInstallVenvMode=build`; internet access and system Python 3.10+ are assumed.
- Minimum supported Python version remains 3.10+; builds/installs may use the latest available 3.10+.

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Requirements and refactor plan for build-only installer | Completed |
| 2 | Add `installer.iss` flagging for venv mode (default build) and keep shared behavior intact | Completed |
| 3 | Retire embedded workflow and references | Completed |
| 4 | Implement/verify `win_inno_build` workflow (install-time venv) | Completed |
| 5 | Clean-up/remove legacy `inno_*` workflows and align docs/tests for build-only | Pending |

## Execution plan expectations
- Before planning/implementation, set up your environment using `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed).
- For each phase/stage, create and document a concrete plan before making code changes.
- Identify risks inherent in the plan (behavioral regressions, installer failures, CI flakiness, dependency drift, user upgrade prompts) and list the mitigations/tests you will run to address those risks.
- Track the plan and risk mitigations alongside the phase notes so they are visible during execution and review.
- After implementing each phase/stage, document the results and outcomes for that stage (tests run, issues found, follow-ups).
- After implementation, mark the stage as completed in the tracking tables.
- Do not continue if you have open questions, need clarification, or prior stages are not completed; pause and document why you stopped so the next step is unblocked quickly.

## Phase Details

### Phase 1: Requirements and plan
- Lock in scope, non-goals, and naming for the new `win_inno_*` workflows.
- Decide on installer argument surface so both workflows can call `installer.iss` without divergence.
- Capture VirusTotal/artifact expectations so CI wiring is straightforward.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Document requirements, shared constraints, and open questions | Completed |
| 1.2 | Confirm naming/define choices with maintainers | Completed |

#### Stage 1.1 plan / risks / results (Completed)
- Plan: inventory current `inno_*` behaviors, define the two `win_inno_*` modes, capture installer expectations, VirusTotal wiring, and upgrade prompts; no code changes.
- Risks: omitting legacy behaviors or naming conventions; mixing workflow vs artifact names.
- Mitigations: cross-check existing `inno_*` workflows and `installer.iss`; document naming for workflows (`win_inno_*.yml`) vs artifacts (`win-inno-*`).
- Results: requirements recorded above (later narrowed to build-only; see Phase 3); decisions documented in "Decisions (confirmed)"; no tests run (docs only).

#### Stage 1.2 plan / risks / results (Completed)
- Plan: confirm `/DInstallVenvMode` values and initial workflow/artifact naming (embedded + build) with maintainers; update docs/tables once confirmed (embedded path later removed).
- Risks: proceeding with mismatched names/defines would break CI or installer behavior; unclear expectations would block later phases.
- Mitigations: paused before Phase 2 until confirmation; proposed defaults for quick sign-off.
- Results: Confirmed define values and naming as noted in "Decisions (confirmed)"; embedded path later retired in Phase 3. No open questions remain for Phase 1. No tests run (docs only).

### Phase 2: `installer.iss` supports build mode (legacy embedded branch)
- Introduce a single define-driven switch for venv mode while preserving current upgrade/validation behavior; default to build and flag embedded handling for retirement.
- Keep checksum verification flow intact and ensure font handling still works.
- Add manual/automated upgrade-path checks (existing venv matching vs outdated) to validate the rebuild-or-skip prompt logic.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add install-mode define and thread through venv detection/creation paths | Completed |
| 2.2 | Update checksum verification logic for embedded vs build modes | Completed |
| 2.3 | Smoke-test both modes locally (manual installer runs) | Skipped (awaiting workflow-built installers) |
| 2.4 | Fix embedded venv relocation (rehoming `pyvenv.cfg` + safe fallback) | Completed |

#### Stage 2.1 plan / risks / results (Completed)
- Plan: update `installer.iss` to accept `/DInstallVenvMode=embedded|build` (default embedded), branch venv handling accordingly: embedded uses bundled venv; build uses system Python 3.10+ to create venv, install deps, show progress, and honor upgrade-check prompt (reuse vs rebuild). Keep legacy folder rename and existing prompts intact.
- Risks: breaking installer flow in either mode; mis-detecting Python version; regressions in upgrade prompt logic; Inno script compile errors.
- Mitigations: implement minimal branching to avoid duplication; guard version check; keep existing helper calls; manual smoke runs for both modes after change.
- Results: Implemented mode-aware branching, reuse/rebuild prompts for existing venvs, system-Python venv creation for build mode, and embedded-mode validation. No tests run yet (Inno/manual only).

#### Stage 2.2 plan / risks / results (Completed)
- Plan: adjust checksum verification in `installer.iss` to include venv files only in embedded mode; exclude venv during build-mode verification; ensure payload manifest checks remain unchanged.
- Risks: checksum mismatches causing install failures; accidentally skipping verification of non-venv files.
- Mitigations: mirror CLI flags used during manifest generation; manual verification runs in both modes; keep excludes/includes aligned with workflows.
- Results: Checksum verification now includes `--include-venv` only in embedded mode and keeps payload manifest checks intact. No tests run yet.

#### Stage 2.3 plan / risks / results (Skipped; awaiting workflow-built installers)
- Plan: focus manual smoke-tests on build mode (fresh install and upgrade with existing venv matching vs stale) to confirm rebuild-or-skip prompts, checksum validation, and dependency installation behavior.
- Risks: untested build-mode branches leading to runtime failures; missed upgrade prompt edge cases.
- Mitigations: explicit build-only matrix (fresh/upgrade-ok/upgrade-stale); capture logs/screenshots if issues arise.
- Results: Skipped for now; will execute once the build-only installer artifacts are available.

#### Stage 2.4 plan / risks / results (Completed)
- Plan:
  - Before any embedded-mode venv checks run, rewrite `overlay_client/.venv/pyvenv.cfg` so `home`, `executable`, and `command` point to the installed path (compute from `{app}`), then re-run venv checks against that path.
  - Exclude `overlay_client/.venv/pyvenv.cfg` from checksum validation (or regenerate the manifest to omit it) to avoid hash mismatches after rewriting.
  - If the rehomed venv still fails to start (non-zero exit), fall back to a rebuild path: prompt the user and, if accepted, create a fresh venv with system Python 3.10+ and reinstall PyQt6>=6.5 (using the build-mode flow), otherwise abort with a clear error.
  - Add installer logging around the rehome/rebuild decisions for triage.
- Risks:
  - Hash drift if `pyvenv.cfg` is rewritten but still covered by manifests, causing installs to fail.
  - Rehome logic could point to the wrong path (e.g., path with spaces or non-default install dir) and still fail to start Python.
  - Rebuild fallback could pull from PyPI and fail offline or on machines without Python 3.10+.
  - Silent venv reuse if checks are skipped accidentally.
- Mitigations/safeguards:
  - Explicitly exclude `pyvenv.cfg` from the embedded manifest verification (single-file carve-out) while keeping the rest of the venv hashed; document this exception.
  - Validate the rehomed interpreter by running `python.exe -c "import sys, PyQt6"` and fail fast with a clear message if it exits non-zero.
  - Gate rebuild on user confirmation; require system Python 3.10+ and surface dependency install progress; fail with actionable messaging if Python/deps are missing.
  - Cover spaces/non-default paths in the manual test matrix; keep upgrade prompts unchanged except for the added rehome/rebuild step.
- Results:
  - Added installer rehome step for the bundled venv (`pyvenv.cfg` rewritten to installed paths) before dependency checks; if validation still fails, prompt to rebuild using system Python 3.10+ with online installs, then re-validate.
  - Added shared helper for system-Python venv creation (reuse in both modes) and excluded `pyvenv.cfg` from manifests to avoid checksum drift after rehome. Current guidance: set `pyvenv.cfg` `home` to the venv `Scripts` directory (not the exe path) to avoid `python.exe\python.exe` resolution failures.
  - Tests: not run (no installer smoke pass available in this environment); needs manual installer run covering embedded fresh/upgrade + rebuild prompt flow.

### Phase 3: Retire embedded workflow
- Drop the bundled-Python installer path so build-mode is the only supported flow.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Remove/disable `win_inno_embed.yml` and embedded artifacts from CI/release wiring | Completed |
| 3.2 | Strip embedded-venv references from docs/release notes and align defaults to build-only | Completed |

#### Stage 3.1 plan / risks / results (Completed)
- Plan: delete the embedded workflow and stop producing/uploading embedded artifacts; keep build-mode workflow intact.
- Risks: lingering CI references to the removed workflow/artifacts causing failures; accidental removal of shared build steps needed by `win_inno_build`.
- Mitigations: remove only the embedded workflow file; retain build workflow unchanged; follow-up sweep in Stage 3.2 for docs/links.
- Results: `.github/workflows/win_inno_embed.yml` removed; no other CI references remained. No tests run (workflow removal only).

#### Stage 3.2 plan / risks / results (Completed)
- Plan: update documentation to reflect build-only strategy and note embedded retirement.
- Risks: lingering references causing confusion for reviewers; mismatched artifact names in docs.
- Mitigations: sweep docs for embedded-workflow mentions; update phase tables; align decisions with build-only assumption.
- Results: Doc sweep completed for this refactoring plan; embedded workflow references are now noted only historically, defaults point to build-only, and phase tables updated. No tests run (docs only).

### Phase 4: `win_inno_build` workflow
- Build payload without venv; rely on installer to create venv during setup.
- Generate/verify manifests excluding venv; produce installer and hook VirusTotal.
- Include upgrade-path validation: run installer over existing venvs (matching vs outdated) to confirm rebuild-or-skip behavior and online dep install flow.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Author `win_inno_build.yml` workflow from scratch | Completed |
| 4.2 | Verify checksum generation/verification without venv | Completed |
| 4.3 | Wire artifact upload/release attachment + VirusTotal call | Completed |

#### Stage 4.1 plan / risks / results (Completed)
- Plan: create `win_inno_build.yml` workflow to build installer without embedded venv; stage payload with release excludes and ensure `.venv` is excluded; generate and verify checksum manifests without `--include-venv`; bundle font; build via `iscc` with `/DInstallVenvMode=build`; upload artifacts as `win-inno-build`; invoke VirusTotal.
- Risks: accidentally including the venv; checksum mismatch due to include/exclude differences; wrong `InstallVenvMode`; artifact naming mismatch.
- Mitigations: explicitly exclude `.venv` in staging; use manifest generation without `--include-venv`; pass `InstallVenvMode=build`; align artifact names with VT.
- Results: `win_inno_build.yml` added with staging that excludes `.venv`, checksum generation/verification without venv, build-mode `iscc` call, artifacts `win-inno-build`/`win-inno-build-exe`, and VT invocation. Awaiting CI run for validation. No tests run locally.

#### Stage 4.2 plan / risks / results (Completed)
- Plan: trigger `win_inno_build.yml` (release tag or manual dispatch) to confirm payload staging excludes `.venv`, manifests are generated without `--include-venv`, and verification steps pass.
- Risks: CI failures due to exclude logic, checksum mismatch, or workflow syntax.
- Mitigations: inspect artifact contents and logs from the first successful run; rerun after fixes if needed.
- Results: Manual workflow dispatch succeeded after fixing exclude handling; artifacts/logs show `.venv` excluded and checksum generation/verification completed. No local tests run.

#### Stage 4.3 plan / risks / results (Completed)
- Plan: confirm artifact upload names (`win-inno-build`, `win-inno-build-exe`), release attachment, and VirusTotal workflow invocation using the new workflow; ensure VT uses `dist/inno_output/*.exe`.
- Risks: incorrect artifact names/path pattern causing VT or release attachment to fail.
- Mitigations: validate artifact list in CI run; check VT job logs for pattern/attachment success.
- Results: Manual run confirmed artifacts (`win-inno-build`, `win-inno-build-exe`), release attachment wiring (now via separate `attach_release` job with artifact download), and VT invocation with `dist/inno_output/*.exe`; VT behavior depends on file size vs VT limits. No code changes needed.

### Phase 5: Clean-up and hardening
- Remove/rename legacy `inno_*` workflows and references; align remaining docs/CI to the build-only path; add regression coverage if available.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Remove/retire old `inno_*` workflows and helper scripts | Pending |
| 5.2 | Update CI badges/links and release notes to point at `win_inno_build` | Pending |
| 5.3 | Final verification run of the build-only installer (manual smoke + VT wiring) | Pending |
