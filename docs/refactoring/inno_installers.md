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

### Open questions / decisions to confirm
- Exact define name/value to pass into `installer.iss` (proposal: `/DInstallVenvMode=embedded` default, `/DInstallVenvMode=build` for install-time). Confirmed.
- Naming: workflow files will be `win_inno_embed.yml` and `win_inno_build.yml`; VirusTotal artifact names remain `win-inno-embed` and `win-inno-build`.
- Whether install-time venv creation must be offline-capable (e.g., ship wheels) or is allowed to fetch from PyPI. Install-time can fetch from PyPI.
- Minimum supported Python version (assumed 3.10+ based on current scripts). This is the min supported version but we can use latest for the .venv (install-time or embed).

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Requirements and refactor plan for new `win_inno_*` installers | In Progress |
| 2 | Add `installer.iss` flagging for venv mode and keep shared behavior intact | Pending |
| 3 | Implement `win_inno_embed` workflow (prebuilt venv) | Pending |
| 4 | Implement `win_inno_build` workflow (install-time venv) | Pending |
| 5 | Clean-up/remove legacy `inno_*` assets and align docs/tests | Pending |

## Execution plan expectations
- Before planning/implementation, set up your environment using `tests/configure_pytest_environment.py`.
- For each phase/stage, create and document a concrete plan before making code changes.
- Identify risks inherent in the plan (behavioral regressions, installer failures, CI flakiness, dependency drift, user upgrade prompts) and list the mitigations/tests you will run to address those risks.
- Track the plan and risk mitigations alongside the phase notes so they are visible during execution and review.
- After implementing each phase/stage, document the results and outcomes for that stage (tests run, issues found, follow-ups).
- After implementation, mark the stage as completed in the tracking tables.
- Do not continue if you have open questions, need clarification, or prior stages are not completed.

## Phase Details

### Phase 1: Requirements and plan
- Lock in scope, non-goals, and naming for the new `win_inno_*` workflows.
- Decide on installer argument surface so both workflows can call `installer.iss` without divergence.
- Capture VirusTotal/artifact expectations so CI wiring is straightforward.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Document requirements, shared constraints, and open questions | Completed |
| 1.2 | Confirm naming/define choices with maintainers | Pending |

### Phase 2: `installer.iss` supports both modes
- Introduce a single define-driven switch for venv mode while preserving current upgrade/validation behavior.
- Keep checksum verification flow intact and ensure font handling still works.
- Add manual/automated upgrade-path checks (existing venv matching vs outdated) to validate the rebuild-or-skip prompt logic.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add install-mode define and thread through venv detection/creation paths | Pending |
| 2.2 | Update checksum verification logic for embedded vs build modes | Pending |
| 2.3 | Smoke-test both modes locally (manual installer runs) | Pending |

### Phase 3: `win_inno_embed` workflow
- Build payload with bundled venv and DLLs; generate/verify manifests with venv included.
- Produce installer exe, upload artifacts, attach to releases, and trigger VirusTotal scan.
- Include upgrade-path validation: simulate installing over an existing venv (up-to-date vs stale) and ensure prompts behave as expected.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Author `win_inno_embed.yml` workflow from scratch | Pending |
| 3.2 | Verify payload staging + checksum generation in CI | Pending |
| 3.3 | Wire artifact upload/release attachment + VirusTotal call | Pending |

### Phase 4: `win_inno_build` workflow
- Build payload without venv; rely on installer to create venv during setup.
- Generate/verify manifests excluding venv; produce installer and hook VirusTotal.
- Include upgrade-path validation: run installer over existing venvs (matching vs outdated) to confirm rebuild-or-skip behavior and online dep install flow.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Author `win_inno_build.yml` workflow from scratch | Pending |
| 4.2 | Verify checksum generation/verification without venv | Pending |
| 4.3 | Wire artifact upload/release attachment + VirusTotal call | Pending |

### Phase 5: Clean-up and hardening
- Remove/rename legacy `inno_*` workflows and references; update docs/readme as needed.
- Ensure CI badges/links point to new workflows; add regression coverage if available.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Remove/retire old `inno_*` workflows and helper scripts | Pending |
| 5.2 | Update docs/release notes/test plans for the new installers | Pending |
| 5.3 | Final verification run of both workflows and installers | Pending |
