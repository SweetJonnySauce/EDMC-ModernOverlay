## Goal: Add flatpak-spawn detection in linux install for Fedora distro since it is packaged separately from flatpak.

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

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Add Flatpak-specific dependency detection for Fedora install flow. | In Progress |

## Phase Details

### Phase 1: Fedora Flatpak Dependency Detection
- Goal: Ensure `flatpak-spawn` is prompted for installation on Fedora when the EDMC target is a Flatpak install, while leaving non-Flatpak installs unchanged.
- Touch points: `scripts/install_matrix.json` for new package group, `scripts/install_linux.sh` for parsing and dependency selection logic.
- Invariants: Existing package prompts remain unchanged for non-Flatpak targets; Flatpak permission checks still rely on `flatpak` CLI presence; no behavior changes to plugin detection or install flows.
- Risks: Missing/incorrect package names for Fedora or accidentally adding Flatpak-only deps to all installs.
- Mitigations: Limit `packages.flatpak` to Fedora; gate inclusion on `PLUGIN_DIR_KIND=flatpak`; validate with dry-run on Fedora profile.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Add `packages.flatpak` group in `scripts/install_matrix.json` with `flatpak-spawn` for Fedora. | Completed |
| 1.2 | Extend `matrix_helper` parsing in `scripts/install_linux.sh` to emit `PROFILE_PACKAGES_FLATPAK`. | Completed |
| 1.3 | Append Flatpak package group in `ensure_system_packages` when `PLUGIN_DIR_KIND=flatpak`; update fallback notice to mention `flatpak-spawn` for Flatpak installs. | Completed |
| 1.4 | Validate via `install_linux.sh --dry-run --profile fedora` with Flatpak plugin dir selection; confirm `flatpak-spawn` appears only for Flatpak installs. | Blocked |
| 1.5 | Add Fedora (dnf/rpm) package status checks comparable to Debian apt checks. | Completed |

#### Stage 1.1 Plan
- Update `scripts/install_matrix.json` to add a new `packages.flatpak` array alongside `core`, `qt`, and `wayland` for each distro profile.
- Set Fedora's `packages.flatpak` to include `flatpak-spawn`; keep other distros empty for now to avoid unintended prompts.
- Verify JSON structure and trailing commas to keep the manifest valid.

#### Stage 1.1 Results
- Added `packages.flatpak` arrays for all distro profiles, with Fedora including `flatpak-spawn` and others empty.

#### Stage 1.2 Plan
- Update `matrix_helper` in `scripts/install_linux.sh` to emit `PROFILE_PACKAGES_FLATPAK` from the new `packages.flatpak` array.
- Declare `PROFILE_PACKAGES_FLATPAK` near the other package group arrays to keep state consistent.
- Keep the change data-only: no behavior changes yet in package selection or prompts (that is Stage 1.3).

#### Stage 1.2 Results
- Added `PROFILE_PACKAGES_FLATPAK` state and emitted it from `matrix_helper`, including reset in the custom profile path.

#### Stage 1.3 Plan
- Update `ensure_system_packages` in `scripts/install_linux.sh` to append `PROFILE_PACKAGES_FLATPAK` when `PLUGIN_DIR_KIND=flatpak`.
- Add a brief log/console note explaining the extra Flatpak dependency inclusion when applicable.
- Extend the fallback dependency notice string to mention `flatpak-spawn` when the plugin target is Flatpak.

#### Stage 1.3 Results
- Appended `PROFILE_PACKAGES_FLATPAK` and `flatpak-spawn` fallback notice for Flatpak installs, with an informational note in the installer output.

#### Stage 1.4 Plan
- Run `scripts/install_linux.sh --dry-run --profile fedora` and select a Flatpak EDMC plugin directory when prompted.
- Confirm the package list includes `flatpak-spawn` and the Flatpak helper note appears in the output.
- Repeat with a non-Flatpak plugin directory (or override path) to confirm `flatpak-spawn` is not included.
- Record the validation outcome or any blockers (e.g., missing prompt choices) in the results section.

#### Stage 1.4 Results
- Blocked: running `scripts/install_linux.sh --dry-run --yes --profile fedora <path>` from the repo fails with `Could not find EDMCModernOverlay directory alongside install script.` The script expects a release bundle layout (EDMCModernOverlay directory adjacent to `scripts/`), which is not present in this repo checkout.

#### Stage 1.5 Plan
- Extend `detect_package_manager_kind` handling in `scripts/install_linux.sh` to treat `dnf` as a supported manager kind for status checks.
- Implement `classify_packages_for_dnf` that:
  - Uses `rpm -q <pkg>` (or `dnf list installed <pkg>`) to detect installed packages.
  - Uses `dnf repoquery --latest-limit 1 --qf '%{evr}' <pkg>` to retrieve candidate versions (if available).
  - Compares installed vs. candidate versions using `rpmdev-vercmp` when present; otherwise, treat as “installed” without upgrade checks.
- Wire `classify_packages_for_dnf` into `classify_package_statuses` and set `PACKAGE_STATUS_CHECK_SUPPORTED=1` for dnf.
- Add fallback behavior and messages when `dnf repoquery` or version-compare tooling is missing (avoid hard failure; mark upgrade check unavailable).
- Document any new tool dependencies (e.g., `dnf-plugins-core` for `repoquery`, `rpmdevtools` for `rpmdev-vercmp`) and decide whether to prompt-install them or skip upgrade checks when absent.

#### Stage 1.5 Plan (Detailed)
- Define the exact command flow for dnf:
  - Use `rpm -q --qf '%{EVR}' <pkg>` to capture installed EVR and detect not-installed exit codes.
  - Use `dnf repoquery --latest-limit 1 --qf '%{EVR}' <pkg>` to capture candidate EVR when available.
  - Use `rpmdev-vercmp <installed> <candidate>` for comparisons when installed; interpret `0` (equal), `11` (first newer), `12` (second newer).
- Decide fallback behavior when tools are missing:
  - If `dnf repoquery` is unavailable, mark status as "installed" (if present) without upgrade checks and log that candidate lookup was skipped.
  - If `rpmdev-vercmp` is unavailable, skip upgrade checks and mark as "installed" when both versions are known.
- Add log detail strings to `PACKAGE_STATUS_DETAILS` for each package that explain which checks were used and which were skipped.
- Update the Stage 1.5 results section after implementation to note any tool dependency assumptions and any deviations from apt behavior.

#### Stage 1.5 Results
- Implemented `classify_packages_for_dnf` and wired it into `classify_package_statuses` with `PACKAGE_STATUS_CHECK_SUPPORTED=1` for dnf.
- Uses `rpm -q --qf '%{EVR}'` for install detection, `dnf repoquery` for candidate EVR when available, and `rpmdev-vercmp` for upgrade comparison when present.
- Falls back to "candidate check skipped" or "version compare skipped" status details when tools are missing, without failing installation.
