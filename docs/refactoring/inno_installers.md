## Goal: rebuild the Windows Inno installers as `win_inno_*` workflows

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
- Current `inno_*` workflows/scripts are tangled; we will replace them with clean `win_inno_*` workflows and supporting assets.
- Two installer modes are required: (1) prebuilt/embedded Python + dependencies under `overlay_client/.venv`; (2) installer-time venv creation + dependency install.
- `installer.iss` remains the single installer entry point and must accept a switch to choose embedded vs build-at-install-time behavior.
- Both `win_inno_*` workflows must emit artifacts for releases/manual runs and feed those artifacts into `.github/workflows/virustotal_scan.yml`.
- We should assume the existing payload staging, checksum verification, and user-settings preservation remain intact (no silent behavior regressions).

## Requirements to capture

### Shared between both `win_inno_*` workflows
- Start fresh files named `win_inno_*.yml` (do not reuse the old `inno_*` workflows), keeping triggers for releases on `main` and manual dispatch.
- Reuse `scripts/installer.iss` with an explicit define/argument to pick the Python strategy (`embedded` vs `install-time`), and thread that define through `iscc`.
- Keep staging logic that applies `scripts/release_excludes.json`, bundles checksum tooling, preserves user config/fonts, and writes payload + payload manifest artifacts.
- Artifact upload: persist both the installer exe and the staged payload (including `installer.iss`) with deterministic artifact names consumed by VirusTotal.
- VirusTotal integration: call `.github/workflows/virustotal_scan.yml` with the correct artifact name and `dist/inno_output/*.exe` pattern; pass through release id when available.
- Release publishing: attach the generated exe to tagged releases (same naming convention as today) and allow download when run manually.

### `win_inno_embed` (ship bundled Python)
- Build a fresh venv at `dist/inno_payload/EDMCModernOverlay/overlay_client/.venv`.
- Install dependencies into that venv (PyQt6 >= 6.5 plus current pip upgrade); ensure required Python DLLs are copied alongside `python.exe` and into `Scripts`.
- Generate plugin and payload checksum manifests with `--include-venv`, and smoke-verify them prior to running `iscc`.
- Include the venv in the payload; installer should treat bundled Python as authoritative and skip online installs when present.

### `win_inno_build` (build venv during installation)
- Payload must exclude any prebuilt `.venv` so the installer creates it on the target machine.
- Installer must:
  - Validate available Python 3.10+ (or fail with a clear message) before creating the venv under `overlay_client/.venv`.
  - Create the venv, upgrade pip, and install runtime deps (at least PyQt6 >= 6.5) during install; surface progress in the wizard status/progress controls.
  - Fall back/exit gracefully if Python is missing or dependency installation fails.
- Checksum generation/verification should omit the venv (no `--include-venv` when building manifests) but still validate the rest of the payload.

### `installer.iss` expectations
- Accept a define/flag (e.g., `/DInstallVenvMode=embedded|build`) that selects:
  - Embedded mode: verify bundled Python 3.10+ under `overlay_client/.venv`, skip online installs, and include venv files in checksum verification.
  - Build mode: require system Python 3.10+, create venv, install deps, and run checksum verification excluding the newly built venv.
- Keep existing safeguards: prompt when upgrading an existing install, rename legacy plugin folders, preserve user settings/fonts, and run checksum validation using staged manifests.
- Upgrade path requirement: if an existing `overlay_client\.venv` is detected, check Python version + required deps (expectations sourced from a manifest captured during build, e.g., python version + `pip freeze` of the bundled venv; fallback to `overlay_client/requirements/base.txt` and Py 3.10+). Run this check in both modes. If they match expectations, prompt the user to skip rebuilding; otherwise prompt to rebuild the venv (using the selected mode: reuse bundled or recreate via system Python).
- Maintain `Tasks` toggle for optional Eurocaps font install; ensure the font still comes from the staged payload.
- Continue to use temp-staged `tools/generate_checksums.py`, `release_excludes.json`, and `checksums_payload.txt` for verification.

### Decisions (confirmed)
- Define: `/DInstallVenvMode=embedded` (default) and `/DInstallVenvMode=build` for install-time venv creation.
- Workflow filenames: `win_inno_embed.yml` and `win_inno_build.yml`; VirusTotal artifact names: `win-inno-embed` and `win-inno-build`.
- Install-time venv creation may fetch from PyPI (no offline wheel requirement).
- Minimum supported Python version remains 3.10+; builds may use the latest available 3.10+ for the venv (embedded or install-time).

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Requirements and refactor plan for new `win_inno_*` installers | Completed |
| 2 | Add `installer.iss` flagging for venv mode and keep shared behavior intact | In Progress |
| 3 | Implement `win_inno_embed` workflow (prebuilt venv) | In Progress |
| 4 | Implement `win_inno_build` workflow (install-time venv) | In Progress |
| 5 | Clean-up/remove legacy `inno_*` workflows and align docs/tests | Pending |

## Execution plan expectations
- Before planning/implementation, set up your environment using `tests/configure_pytest_environment.py`.
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
- Results: requirements recorded above; decisions documented in “Decisions (confirmed)”; no tests run (docs only).

#### Stage 1.2 plan / risks / results (Completed)
- Plan: confirm `/DInstallVenvMode` values, workflow file names (`win_inno_embed.yml`, `win_inno_build.yml`), and artifact names (`win-inno-embed`, `win-inno-build`) with maintainers; update docs/tables once confirmed.
- Risks: proceeding with mismatched names/defines would break CI or installer behavior; unclear expectations would block later phases.
- Mitigations: paused before Phase 2 until confirmation; proposed defaults for quick sign-off.
- Results: Confirmed define values and naming as noted in “Decisions (confirmed)”; no open questions remain for Phase 1. No tests run (docs only).

### Phase 2: `installer.iss` supports both modes
- Introduce a single define-driven switch for venv mode while preserving current upgrade/validation behavior.
- Keep checksum verification flow intact and ensure font handling still works.
- Add manual/automated upgrade-path checks (existing venv matching vs outdated) to validate the rebuild-or-skip prompt logic.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add install-mode define and thread through venv detection/creation paths | Completed |
| 2.2 | Update checksum verification logic for embedded vs build modes | Completed |
| 2.3 | Smoke-test both modes locally (manual installer runs) | Skipped (awaiting workflow-built installers) |

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
- Plan: run manual installer smoke-tests in both modes covering fresh install and upgrade with existing venv (matching vs stale) to confirm rebuild-or-skip prompts, checksum validation, and dependency installation behavior.
- Risks: untested branches leading to runtime failures; missed upgrade prompt edge cases.
- Mitigations: explicit test matrix (embedded fresh/upgrade-ok/upgrade-stale; build fresh/upgrade-ok/upgrade-stale); capture logs/screenshots if issues arise.
- Results: Skipped for now; will execute once `win_inno_*` workflows produce installers to test.

#### Stage 3.1 plan / risks / results (Completed)
- Plan: create `win_inno_embed.yml` workflow to build embedded-venv installer on Windows; stages payload with release excludes, builds bundled venv with DLLs, generates/verifies manifests with `--include-venv`, bundles font, builds installer via `iscc` with `/DInstallVenvMode=embedded`, uploads artifacts as `win-inno-embed`, and calls VirusTotal scan workflow.
- Risks: workflow syntax errors; missing DLLs in venv; misaligned artifact naming with VirusTotal; forgetting to pass `InstallVenvMode`.
- Mitigations: mirror prior embedded workflow structure; explicitly copy DLLs into venv and Scripts; pass `InstallVenvMode=embedded`; artifact name matches spec; include manifest smoke-verification steps.
- Results: `win_inno_embed.yml` added with full build steps and VirusTotal invocation; size trimmed via `--no-cache-dir/--no-compile`, cache cleanup, and single-copy DLL placement; awaiting CI run for validation. No tests run locally.

#### Stage 3.2 plan / risks / results (Completed)
- Plan: run the new workflow in CI (release tag or manual dispatch) to confirm payload staging, bundled venv contents (including DLLs), and checksum generation/verification succeed.
- Risks: CI failures due to path/syntax errors, missing DLL copy, or checksum mismatch.
- Mitigations: inspect artifact contents and logs from first run; rerun if needed after fixes.
- Results: Manual workflow dispatch completed; artifacts/logs reviewed to confirm payload staging and checksum steps succeeded. No code changes needed; no local tests run.

#### Stage 3.3 plan / risks / results (Completed)
- Plan: confirm artifact upload names (`win-inno-embed`, `win-inno-embed-exe`), release attachment, and VirusTotal workflow invocation using the new workflow; ensure VT uses `dist/inno_output/*.exe`.
- Risks: incorrect artifact names/path pattern causing VT or release attachment to fail.
- Mitigations: validate artifact list in CI run; check VT job logs for pattern/attachment success.
- Results: Manual run confirmed artifacts (`win-inno-embed`, `win-inno-embed-exe`), release attachment wiring, and VT invocation with `dist/inno_output/*.exe`; VT failed due to size limit (413) but wiring is correct.

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
- Results: Manual run confirmed artifacts (`win-inno-build`, `win-inno-build-exe`), release attachment wiring, and VT invocation with `dist/inno_output/*.exe`; VT behavior depends on file size vs VT limits. No code changes needed.

### Phase 3: `win_inno_embed` workflow
- Build payload with bundled venv and DLLs; generate/verify manifests with venv included.
- Produce installer exe, upload artifacts, attach to releases, and trigger VirusTotal scan.
- Include upgrade-path validation: simulate installing over an existing venv (up-to-date vs stale) and ensure prompts behave as expected.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Author `win_inno_embed.yml` workflow from scratch | Completed |
| 3.2 | Verify payload staging + checksum generation in CI | Completed |
| 3.3 | Wire artifact upload/release attachment + VirusTotal call | Completed |

### Phase 4: `win_inno_build` workflow
- Build payload without venv; rely on installer to create venv during setup.
- Generate/verify manifests excluding venv; produce installer and hook VirusTotal.
- Include upgrade-path validation: run installer over existing venvs (matching vs outdated) to confirm rebuild-or-skip behavior and online dep install flow.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Author `win_inno_build.yml` workflow from scratch | Completed |
| 4.2 | Verify checksum generation/verification without venv | Completed |
| 4.3 | Wire artifact upload/release attachment + VirusTotal call | Completed |

### Phase 5: Clean-up and hardening
- Remove/rename legacy `inno_*` workflows and references; update docs/readme as needed.
- Ensure CI badges/links point to new workflows; add regression coverage if available.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Remove/retire old `inno_*` workflows and helper scripts | Pending |
| 5.2 | Update docs/release notes/test plans for the new installers | Pending |
| 5.3 | Final verification run of both workflows and installers | Pending |
