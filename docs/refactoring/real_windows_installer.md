## Goal: Select a real Windows installer approach and wire it into CI

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

## Installer Options (Windows)

| Option | Pros | Cons | GitHub Actions fit | VT (PowerShell DLL) impact |
| --- | --- | --- | --- | --- |
| WiX (MSI/Burn) | Native Windows installer UX; upgrade/repair/uninstall; enterprise-friendly; strong logging; signing-friendly; Burn can chain prereqs. | Verbose XML; steeper learning curve; custom actions often require C#/DLLs. | `windows-latest`; install via `choco install wixtoolset` or `dotnet tool install --global wix`; run `candle`/`light` or `dotnet wix build`; artifacts/signing/upload steps are straightforward. | No embedded PowerShell; should avoid the PowerShell DLL Sigma hit. |
| MSIX | Modern packaging; clean install/uninstall; good isolation; store/enterprise manageability. | Sandboxing can break broad filesystem needs; requires signing; no Windows 7/8; awkward for PowerShell-first installers. | `windows-latest`; use `MakeAppx.exe`/`SignTool.exe` from Windows SDK or msix-packaging tool; inject cert secret for signing. | No PowerShell SDK embedding; unlikely to trigger the specific VT rule. |
| Inno Setup | Simple authoring; nice default UI; solid compression; AV-familiar EXE; easy to sign. | No native repair/rollback; full reinstall for upgrades; Pascal scripting only; less enterprise-native than MSI. | `windows-latest`; install via `choco install innosetup` or download portable; run `iscc.exe script.iss`; actions like `Minionguyjpro/InnoSetup-Action` available. | If implemented without embedding PowerShell, avoids the Sigma hit; reimplement installer logic in Pascal. |
| NSIS | Very flexible; tiny stubs; good compression; plugin ecosystem; common AV profile. | Low-level scripting, readability suffers; fewer built-in enterprise features; debugging harder. | `windows-latest`; install via `choco install nsis` or portable; run `makensis.exe script.nsi`; actions like `joncloud/makensis-action`. | Same as Inno: keep logic in NSIS, don’t embed PowerShell, so Sigma rule should not fire. |
| Squirrel.Windows | Built-in auto-update/deltas; familiar in Electron world; simple UX. | Prefers per-user installs; weaker enterprise story; project relatively quiet; less suited to script-heavy installers. | `windows-latest`; install `Squirrel` via `dotnet tool install --global Squirrel` or NuGet; run `Squirrel.exe --releasify`; script steps directly. | No PowerShell embedding by default; safe from the PowerShell DLL detection. |
| Script + zip/cmd | Minimal moving parts; transparent; avoids PowerShell DLL-in-EXE AV hits; already close to current flow. | No installer UI; no add/remove entry; manual updates/uninstall; depends on PowerShell host availability. | Already works in current workflows; ship `install_windows.ps1` plus `install.cmd` that shells to `powershell.exe`, package in zip, upload artifact/release. | Best near-term fix: process is `powershell.exe`, so the current VT Sigma hit should clear. |

## Requirements (initial)

1. Installer must avoid the VirusTotal detection seen in hash `914ae23eb5d294caf8f60ad1df74f622959bd2dbfef60e6df9011e18ba714476` (PowerShell DLL loaded by non-PowerShell process). Replace or rework packaging to eliminate that signature.
2. Build the new installer in its own GitHub Action workflow so it can be tested independently of `.github/workflows/release.yml`; wire it into the release flow only after it’s validated.
3. The installer EXE must be built via GitHub Actions (unsigned for now); no local-only build steps.

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Define Inno Setup design and inputs | Completed |
| 2 | Prototype unsigned Inno installer in standalone GH Action | Pending |
| 3 | Validate, then wire installer into release flow | Pending |

## Phase Details

### Phase 1: Define Inno Setup design and inputs
- Goal: lock installer behavior and author an initial `.iss` script covering current PowerShell installer steps.
- Keep parity with existing install_windows.ps1 flow: copy payload, handle plugin directory, optional font, venv creation (via bundled Python or powershell), checksum verify.
- Risks: missing edge cases from PowerShell script; unclear prereqs (Python availability, permissions).
- Mitigations: map each PowerShell step to Inno tasks; decide runtime strategy (system PowerShell vs bundled Python/embedded runtime).

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Inventory current installer behaviors/inputs/outputs and decide dependency strategy (system Python+PowerShell vs bundled runtime) | Completed |
| 1.2 | Draft Inno `.iss` script structure (directories, files, run steps, logging, uninstall story) | Completed |
| 1.3 | Review against requirements (VT avoidance, unsigned build, GH Actions-only) and adjust | Completed |

#### Plan for Stage 1.1 (Inventory + dependency strategy)
- Catalog current installer behavior from `scripts/install_windows.ps1`:
  - Detect EDMC plugins directory; prompt override.
  - Ensure EDMC not running; disable legacy plugin dirs; disable existing Modern Overlay by renaming.
  - Copy payload and checksum manifest; validate checksums.
  - Create/refresh `overlay_client\.venv` and install requirements.
  - Optional Eurocaps font download.
  - Logging toggle and dry-run handling.
- Decide runtime dependencies:
  - Option A (prefer): bundle embeddable Python + wheels; run `python.exe -m venv` and `pip install --no-index --find-links <bundled>` from Inno `Exec`.
  - Option B: shell to `powershell.exe` and reuse existing script; acceptable if VT rule stays clear (process is `powershell.exe`).
  - Choose based on VT risk, size, and effort; record decision and required payload layout.
- Outputs:
  - Decision doc (in this file) on dependency strategy and payload structure.
  - Checklist mapping each PowerShell action to an Inno equivalent.

Risks and mitigations for 1.1
- Risk: Missing installer behaviors or edge cases in the inventory. Mitigation: cross-check against `install_windows.ps1` comments and control flow; list all user prompts/flags; verify checksum and font paths.
- Risk: Underestimating Python/runtime needs (e.g., `pip` network). Mitigation: plan to bundle wheels or prebuilt venv to allow offline install; document network assumptions if any remain.
- Risk: VT rule still triggered if relying on PowerShell. Mitigation: prefer bundled Python path; if using PowerShell, ensure process is `powershell.exe` and re-scan a prototype.
- Risk: Inno unable to perform some steps (e.g., process checks). Mitigation: map to Inno `Run`/`Check` and, if needed, small helper EXE or retained PowerShell snippet executed by `powershell.exe`.

Testing hooks
- Add focused unit tests (Python) for checksum generator and payload layout rules (e.g., ensure excludes applied) that the installer relies on; run in CI.
- If retaining parts of `install_windows.ps1`, add PowerShell Pester tests for functions like checksum verification and directory resolution; run in CI (Windows job).
- For dependency strategy choice, add a simple integration script in CI to create the bundled venv from the staged payload to prove offline viability.

#### Stage 1.1 results
- Dependency strategy decision: bundle embeddable Python (3.12) plus required wheels; Inno will `Exec` the bundled `python.exe -m venv overlay_client\.venv` and `pip install --no-index --find-links <bundled-wheels> -r requirements.txt`. No embedded PowerShell runtime; avoids the VT rule tied to PowerShell DLL in non-PowerShell processes. PowerShell use limited to optional helper (e.g., font download) executed via `powershell.exe` only if strictly needed.
- Payload layout for Inno staging: `payload\EDMCModernOverlay\` (plugin files + checksums.txt), `payload\python\` (embeddable runtime), `payload\wheels\` (deps), optional `payload\extras\font\Eurocaps.ttf`.
- Behavior mapping checklist (Inno equivalents):
  - Detect/prompt plugins directory → Inno dir page + custom check to ensure EDMC not running; fail with message if running.
  - Disable legacy/previous installs → Inno `Run` helper (compiled into a small exe or Pascal code) to rename legacy dirs before install.
  - Copy payload + checksums → Inno file sections copy; post-copy `Exec` to run bundled Python checksum validator (reuse `scripts/generate_checksums.py` or small verifier).
  - Create/refresh venv + pip install → Inno `Exec` bundled `python.exe` as above; log output.
  - Font optional → add checkbox task; if selected, install bundled font file (no network).
  - Logging/dry run → keep Inno log enabled; no dry-run mode in Inno, but can add a “simulate” flag later if needed.
- Artifacts for next phase: dependency decision recorded; mapping ready to translate into `.iss` sections; confirm need to bundle embeddable Python and wheels in the prototype workflow.

#### Plan for Stage 1.2 (Draft Inno `.iss` structure)
- Draft initial `installer.iss` scaffold:
  - `Setup`: AppName/Version, default dir (EDMC plugins path placeholder), output base name, compression, logging enabled.
  - `Files`: copy `payload\EDMCModernOverlay\*` to target plugins dir; copy `payload\python\*`, `payload\wheels\*`, optional font assets to temp/staging under `{tmp}` or `{app}` as needed.
  - `Dirs`/`Tasks`: optional font install checkbox; ensure staging folders exist.
  - `Run`: sequence to check EDMC not running (custom Pascal check), rename legacy dirs, run checksum validation with bundled Python, create venv, pip install wheels, install font if selected.
  - `Code`: Pascal helpers for plugin dir detection (fallbacks matching PowerShell script), EDMC process check, legacy directory rename, simple wrapper to run bundled Python with args and capture exit codes.
  - Logging: ensure `/LOG` default enabled; consider extra log file in target directory for postmortem.
- Inputs/constants to define:
  - Payload root variable (e.g., `#define PayloadRoot "payload"`), venv path `overlay_client\venv`, wheels dir, checksum file name.
  - Version injection from CI (e.g., pre-process with `#define AppVersion "{{VERSION}}"` from GH Action).
- Outputs:
  - Skeleton `installer.iss` ready for CI; document any required helper scripts/exes.

Risks and mitigations for 1.2
- Risk: Plugin directory detection diverges from PowerShell logic. Mitigation: mirror detection order from `install_windows.ps1`; add unit test (PowerShell/Pester or Python mimic) to validate detection rules against sample inputs.
- Risk: EDMC process check unreliable. Mitigation: implement explicit process name check in Pascal; add a small integration test in CI that spawns a dummy process name to verify check/halt behavior.
- Risk: Bundled Python invocation paths wrong on some systems. Mitigation: keep paths relative to `{tmp}`/`{app}` and add CI smoke script to run `python.exe -V` and `-m venv` from staged tree.
- Risk: Legacy dir rename or checksum validation fails mid-install. Mitigation: order steps with clear failure messages; ensure rollback semantics (stop before copying payload) and log all commands.
- Risk: Font install permissions. Mitigation: install font only if checkbox selected; catch failures and continue with warning.

Testing hooks for 1.2
- Add a lightweight Python test that stages a mock payload layout and verifies the path assumptions (payload root, wheels dir, checksum path).
- Add a Windows CI step (can be a helper script) to exercise the Pascal helper functions compiled via `iscc` with `/SUPPRESSMSGBOXES` and inspect log for expected sequence (process check, venv creation dry run).
- Add unit tests for checksum validator (reuse existing Python) invoked with bundled Python to ensure it works from the planned locations.

#### Stage 1.2 results
- Draft `installer.iss` structure defined (no file added yet):
  - Setup: `AppName=EDMC Modern Overlay`, `AppVersion` injected from CI define; `DefaultDirName` resolved via custom code to EDMC plugins path; `OutputBaseFilename=EDMCModernOverlay-setup`; compression `lzma2`; logging on by default.
  - Files: copy `payload\EDMCModernOverlay\*` into `{code:GetPluginsDir}\EDMCModernOverlay`; copy `payload\python\*` and `payload\wheels\*` into `{tmp}\payload_python` and `{tmp}\payload_wheels`; optional font under `{tmp}\font\Eurocaps.ttf`.
  - Tasks: optional “Install Eurocaps font” checkbox.
  - Run order (deferred until after files copied):
    1) `CheckEdmcNotRunning` (Pascal; looks for `EDMarketConnector.exe`).
    2) `RenameLegacyDirs` to disable `EDMC-ModernOverlay*` and existing `EDMCModernOverlay` variants.
    3) `ValidateChecksums` by running bundled `python.exe` with `scripts/generate_checksums.py --verify --root "{app}" --manifest checksums.txt`.
    4) `CreateVenv` using bundled `python.exe -m venv overlay_client\.venv`.
    5) `PipInstall` using bundled `python.exe -m pip install --no-index --find-links "{tmp}\payload_wheels" -r "{app}\EDMCModernOverlay\overlay_client\requirements.txt"`.
    6) Optional font install if task selected.
  - Code section helpers:
    - `GetPluginsDir`: mirrors PowerShell detection order (uses known EDMC plugins paths, allows user override via dir page).
    - `CheckEdmcNotRunning`: scans process list; prompts to close if found.
    - `RenameLegacyDirs`: renames legacy folders with `.disabled` suffix before install.
    - `RunPython`: helper to call bundled python with arguments and capture exit code/log.
    - `ValidateChecksums`: wrapper calling existing checksum script.
- Constants/defines set for payload roots: `#define PayloadRoot "payload"`, `#define WheelsDir "payload\\wheels"`, `#define PythonDir "payload\\python"`, `#define FontFile "payload\\extras\\font\\Eurocaps.ttf"`.
- Logging: rely on Inno built-in log; plan to copy log to `{app}\EDMCModernOverlay\install.log` post-run for user support.
- Ready for Phase 1.3: review against VT requirement (no embedded PowerShell), GH Actions build, and unsigned output; then transcribe scaffold into actual `.iss`.

#### Plan for Stage 1.3 (Requirements review and adjustments)
- Goal: verify the drafted Inno plan meets stated requirements: avoids the VT PowerShell DLL hit, builds unsigned via GitHub Actions in a separate workflow, and stays independent of `release.yml` until validated.
- Actions:
  - Cross-check scaffold against requirements list:
    - VT avoidance: confirm no embedded PowerShell; bundled Python path only; any optional PowerShell helper must run as `powershell.exe` and be removable.
    - GH Actions-only build: ensure all steps (payload staging, embeddable Python, wheels) can be produced in CI without local steps.
    - Separate workflow: outline `.github/workflows/inno_prototype.yml` triggers (manual/branch) and artifacts; no hooks into `release.yml` yet.
    - Unsigned output: confirm `iscc` config leaves binary unsigned and notes that in release notes.
  - Adjust `.iss` assumptions if any requirement is unmet (e.g., add fallback when bundled Python missing, or move font to bundled asset to avoid network).
  - Define acceptance checks for 1.3 completion: a checklist mapping each requirement to a planned control in the prototype workflow.
- Outputs:
  - Documented requirement-to-plan mapping in this file.
  - Identified gaps and the adjustments needed in the upcoming `.iss` implementation or CI workflow.

Risks and mitigations for 1.3
- Risk: Hidden PowerShell usage slips back in (e.g., for process checks). Mitigation: enforce a rule in `.iss`/code section to avoid PowerShell unless behind a deliberate task; add a CI grep/lint step to flag `powershell.exe` usage.
- Risk: CI cannot fetch or stage embeddable Python/wheels reliably. Mitigation: pin URLs/checksums; cache artifacts; add a preflight download script with retries and hash validation.
- Risk: Prototype workflow accidentally couples to `release.yml` outputs. Mitigation: keep separate artifact names and triggers; no `needs:` on release jobs.
- Risk: Unsigned binary triggers AV heuristics anyway. Mitigation: note expectation; plan a VT scan in prototype (Phase 2) and document results; consider signing later as a follow-up.

Testing hooks for 1.3
- Add a CI step to assert no PowerShell embedding: scan `.iss` and helper sources for `System.Management.Automation` or unexpected PowerShell invocations.
- Add a download integrity test: script to fetch embeddable Python and wheels and validate checksums in CI before packaging.
- Add a dry-run CI job (Windows) that builds the installer with `/SIGNTOOL=` unset (ensuring unsigned) and uploads the log to confirm separation from `release.yml`.

#### Stage 1.3 results
- Requirement mapping:
  - VT avoidance: design keeps all install logic in Inno + bundled Python; no embedded PowerShell runtime. Any optional PowerShell helper would run via `powershell.exe` and is considered removable; plan CI grep to ensure no `System.Management.Automation` usage.
  - GH Actions-only build: prototype workflow will stage payload, download embeddable Python (pinned URL + checksum), and build wheels in CI (`pip wheel` against requirements) to populate `payload\wheels`; no local-only steps.
  - Separate workflow: plan for `.github/workflows/inno_prototype.yml` triggered manually or on a branch; uploads installer artifact; no `needs:` linkage to `release.yml`.
  - Unsigned output: `iscc` invoked without signing; release notes will state “unsigned” until a certificate is available.
- Adjustments identified:
  - Bundle Eurocaps font as a file (no network fetch) to keep offline/VT-friendly.
  - Add hash validation for embeddable Python download in the prototype workflow.
  - Ensure installer log is copied to the app directory for support without needing signing trust.
- Acceptance checks for this stage:
  - Checklist exists tying each requirement to a planned control.
  - Prototype workflow inputs/outputs defined to operate entirely in CI and stay separate from `release.yml`.
  - Signing explicitly disabled/omitted in the planned `iscc` invocation.

### Phase 2: Prototype unsigned Inno installer in standalone GH Action
- Goal: build an unsigned Inno installer EXE in its own workflow (not release.yml), publish as artifact for testing.
- Risks: CI tool install flakiness; missing payload assets; runtime prerequisites unresolved.
- Mitigations: cache/download Inno via Chocolatey; ensure payload staging matches existing release layout; document manual test steps.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add `.github/workflows/inno_prototype.yml` that stages payload, installs Inno, runs `iscc`, uploads EXE | Completed |
| 2.2 | Add `installer.iss`, wire defines, and ensure prototype workflow emits an unsigned EXE | Completed |
| 2.3 | Smoke-test artifact locally/VM (install/uninstall) and rerun VirusTotal to confirm PowerShell DLL rule is clear | Blocked (needs Windows VM + VT) |
| 2.4 | Iterate on `.iss` as needed to pass VT and functional checks | Pending |

#### Plan for Stage 2.1 (Prototype GH Action workflow)
- Goal: create `.github/workflows/inno_prototype.yml` to build an unsigned Inno installer independently of `release.yml`, stage the payload with bundled Python/wheels/font, and upload the EXE and logs as artifacts.
- Workflow outline:
  - Triggers: `workflow_dispatch` and/or branch push (e.g., `inno/*`), no ties to releases/tags.
  - Jobs: single `windows-latest`.
  - Steps:
    1) Checkout repo.
    2) Stage payload: run existing `scripts/verify_release_not_dev.py`; reuse `scripts/release_excludes.json`; rsync/robocopy equivalent on Windows to assemble `payload\EDMCModernOverlay`.
    3) Download embeddable Python (pinned URL + checksum) into `payload\python`; verify hash.
    4) Build wheels: install Python (`actions/setup-python`), `pip wheel -r scripts/install_requirements.txt` (or equivalent) into `payload\wheels` using `--no-binary=:all:` as feasible; cache if useful.
    5) Copy Eurocaps font into `payload\extras\font`.
    6) Place `installer.iss` (to be authored) in repo; run Inno via `choco install innosetup` or portable; invoke `iscc installer.iss` with defines for version/output dir.
    7) Upload artifacts: installer EXE, Inno logs, staged payload manifest if helpful.
- Inputs/defines for `iscc`:
  - `AppVersion` from `github.run_number`/tag fallback.
  - Paths for payload root, python dir, wheels dir set via `#define` or environment.
- Outputs:
  - CI workflow file ready to run.
  - Artifact naming scheme for later VT submission.

Risks and mitigations for 2.1
- Risk: Embeddable Python download fails or hash mismatch. Mitigation: pin URL + SHA256; retry logic; fail the build on mismatch.
- Risk: Wheel build pulls from network during install. Mitigation: pre-wheel all deps in CI and use `--no-index --find-links` at install time; cache wheels; consider pinning versions.
- Risk: Inno not available or installation flakes. Mitigation: install via Chocolatey with retry; or download portable Inno and call `iscc.exe` directly.
- Risk: Payload staging diverges from release packaging. Mitigation: reuse the same exclude manifest and checksum generator; add a small Python check to verify staged tree contains expected files.
- Risk: Workflow accidentally triggers on releases. Mitigation: limit triggers to manual/branch patterns; no `if` on tags.

Testing hooks for 2.1
- Add a CI step that runs a Python script to validate staged payload layout (presence of payload root, python dir, wheels, font, checksums).
- Add a checksum validation step using bundled checksum script against the staged payload.
- After `iscc`, parse the Inno log to assert expected Run entries present; upload log as artifact.

#### Stage 2.1 results
- Added `.github/workflows/inno_prototype.yml`:
  - Triggers: `workflow_dispatch` and `push` to `inno/*` branches; no release/tag linkage.
  - Jobs: `windows-latest`; sets `VERSION` env from tag/ref/run number.
  - Steps: checkout; Python 3.12 setup; `verify_release_not_dev.py`; payload staging via Python honoring `scripts/release_excludes.json`; checksum generation; download + hash-validate Python 3.12.3 embeddable zip (SHA256 `38b265fc0612027a126ae54d2485101f041b61893e41ef4f421dee6ac618a99e`) and expand to `dist/inno_payload/python`; build wheels from `overlay_client/requirements/base.txt` into `dist/inno_payload/wheels`; bundle Eurocaps font from upstream URL; install Inno via Chocolatey; call `iscc installer.iss` when present with defines for `AppVersion`, `OutputDir`, and `PayloadRoot`; upload artifacts (`dist/inno_output/*.exe`, `dist/inno_payload/**`).
  - Includes bundled `scripts/generate_checksums.py` under `dist/inno_payload/tools` for installer use.
- Notes/next steps:
  - `installer.iss` build step is gated on file presence (`hashFiles('installer.iss')`), so workflow runs staging even before the script lands; add the `.iss` implementation next so EXE emits.
  - Font is fetched in CI to keep installer offline at runtime; consider pinning hash in a follow-up.
  - Wheels built from pinned requirements; offline install via `--find-links` in installer remains planned.

#### Stage 2.2 results
- Added `installer.iss` implementing the Inno installer scaffold:
  - Setup: defaults to EDMC plugins dir via `GetDefaultPluginDir`, allows directory override, unsigned output (`EDMCModernOverlay-setup.exe`) to `{#OutputDir}`; `AppVersion` injected via define.
  - Files: copies payload from `{#PayloadRoot}\EDMCModernOverlay` to `{app}\EDMCModernOverlay`; stages bundled Python, wheels, checksum script, and Eurocaps font into `{tmp}` for runtime use (font behind optional task).
  - Code: `PrepareToInstall` blocks if `EDMarketConnector.exe` is running; `CurStepChanged(ssInstall)` renames legacy plugin dirs (`EDMC-ModernOverlay*` and `EDMCModernOverlay*`) to `.disabled*`; `CurStepChanged(ssPostInstall)` runs post-install tasks using bundled Python: checksum verify, venv creation, pip install from wheels, optional font install. Signing is not invoked.
  - Defines: defaults for `PayloadRoot`, `OutputDir`, and `AppVersion` align with the prototype workflow (`/DPayloadRoot=dist\inno_payload` etc.).
- Workflow alignment: the prototype job already passes these defines; with `installer.iss` present the workflow will build and upload an unsigned EXE plus the staged payload and logs.
- Caveats noted for follow-up testing: embeddable Python suitability for `venv`/`pip` needs validation in 2.3; font hash pinning still pending.

#### Plan for Stage 2.2 (Add `installer.iss` and emit EXE)
- Goal: author `installer.iss` per Phase 1 scaffold, wire defines to the prototype workflow, and confirm the workflow produces an unsigned installer EXE artifact.
- Actions:
  - Create `installer.iss` implementing: Setup metadata, file copy from `PayloadRoot`, tasks (font), Code helpers (plugin dir detect, process check, rename legacy dirs, checksum verify, venv + pip via bundled Python, font install), logging.
  - Ensure defines align with workflow: `/DPayloadRoot=dist\inno_payload`, `/DOutputDir=dist\inno_output`, `/DAppVersion=${{ env.VERSION }}`; guard for missing defines with sensible defaults.
  - Add log copy step in Code section to place installer log under `{app}\EDMCModernOverlay\install.log`.
  - Keep signing disabled (no `/S` or sign tool).
  - Update workflow if needed to include `installer.iss` in artifacts and parse the Inno log for success.
- Outputs:
  - `installer.iss` checked in.
  - Verified prototype workflow run that emits `dist/inno_output/*.exe`.
  - Captured Inno log artifact for later review.

Risks and mitigations for 2.2
- Risk: Path mismatches between workflow staging and `.iss` assumptions. Mitigation: use the same defines/paths as staged (`dist/inno_payload/...`); add CI step to assert expected directories before `iscc`.
- Risk: Code section errors prevent EXE build. Mitigation: start with minimal helpers and expand; use `/O+` logs to diagnose; keep Pascal code simple.
- Risk: Missing files (font, wheels, python) cause build/runtime failures. Mitigation: add pre-build checks in `.iss` (`FileExists`) and/or workflow assertions before calling `iscc`.
- Risk: Installer silently signed or blocked. Mitigation: ensure no signing parameters; confirm log shows unsigned build; mark artifact as unsigned.

Testing hooks for 2.2
- Add a workflow step to verify staged payload structure before `iscc` (Python script).
- After build, inspect Inno log to ensure all sections executed and no signing step occurred; upload log artifact.
- Optional local/CI quick run: invoke `iscc` with `/Qp` to validate script syntax without full build.

#### Plan for Stage 2.3 (Smoke test + VT scan)
- Goal: validate the unsigned Inno installer artifact from `inno_prototype` with a manual/VM smoke test and submit to VirusTotal to confirm the PowerShell DLL rule is clear.
- Actions:
  - Trigger `inno_prototype` workflow to produce a fresh EXE.
  - Smoke test on a clean Windows VM:
    - Install: run installer, choose default plugin dir, select font task, confirm payload copied, venv created, pip install succeeds, font installed if selected.
    - Uninstall behavior (none) and rerun install to ensure idempotence with legacy dirs already renamed.
    - Validate checksum step passes; inspect `{app}\EDMCModernOverlay\install.log` if copied.
  - Run VirusTotal scan on the produced EXE; capture report ID and note any hits (expecting Sigma rule cleared).
  - Note embeddable Python behavior: ensure `-m venv` and `pip install --no-index --find-links` work from bundled runtime; adjust wheels if needed.
- Outputs:
  - VT report link/ID and summary of detections (ideally zero for the PowerShell DLL rule).
  - Smoke test notes (pass/fail, issues found).

Risks and mitigations for 2.3
- Risk: Installer fails on clean VM (venv/pip issues with embeddable Python). Mitigation: if embeddable Python cannot `venv`, switch to full embeddable + `python312._pth` tweak or bundle a minimal CPython; expand wheels to include `pip` if missing.
- Risk: VT still flags the EXE. Mitigation: confirm no PowerShell embedding; if flagged, inspect which engine/rule and adjust (e.g., change stub metadata, further reduce runtime footprint).
- Risk: Font install permissions or antivirus interference. Mitigation: keep font optional; log warning on failure; ensure installer continues.
- Risk: Payload integrity mismatch. Mitigation: rerun checksum generation and ensure manifest packaged; verify during smoke test.

Testing hooks for 2.3
- Use the Inno installer log plus `{app}\EDMCModernOverlay\install.log` to verify step ordering.
- Add a temporary CI step (optional) to run `iscc /Qp` and maybe a minimal PowerShell to exercise `python.exe -m venv` on the embeddable payload in the workflow environment.

#### Stage 2.3 results
- Current status: blocked pending access to a Windows VM and VirusTotal submission (requires VT API key or manual upload).
- What remains to run:
  - Trigger `inno_prototype` workflow to produce the unsigned EXE.
  - On a clean Windows VM: install (with font task), verify payload copy, checksum validation, venv creation, pip install from bundled wheels, optional font install; rerun installer to confirm idempotence/legacy rename handling; inspect `{app}\EDMCModernOverlay\install.log`.
  - Submit produced EXE to VirusTotal; capture report ID and confirm the PowerShell DLL Sigma rule is absent.
- Known risk discovered ahead of testing: Windows embeddable Python often lacks `venv`/`pip` by default. If smoke test fails at venv/pip, plan to bundle full embeddable with `python312._pth` tweaks or a minimal CPython+ensurepip, and regenerate wheels accordingly.

### Phase 3: Validate, then wire installer into release flow
- Goal: integrate the vetted Inno build into `release.yml` once prototype passes.
- Risks: regression during integration; signing still absent (expected).
- Mitigations: gate with conditional, keep unsigned note in release assets, retain old path as fallback until confident.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Add release job to build/upload Inno installer alongside existing artifacts | Pending |
| 3.2 | Document release notes and README update for new installer (unsigned) | Pending |
| 3.3 | Remove/disable ps2exe-based EXE path after rollout decision | Pending |
