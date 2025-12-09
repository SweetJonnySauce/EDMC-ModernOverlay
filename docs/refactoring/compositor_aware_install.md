## Goal: Make the Linux install compositor aware.

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
| 1 | Extend install manifest and helper to carry compositor guidance | Planned |
| 2 | Wire installer and overlay env to apply compositor-specific overrides | Planned |
| 3 | Tests, docs, and validation | Planned |

**Cross-phase testing note:** add/extend unit tests alongside each phase’s code changes (don’t defer all tests to Phase 3); land guardrails as behavior shifts.

## Phase Details

### Phase 1: Manifest and helper wiring
- Goal: encode compositor-aware guidance (match hints + env overrides + user-facing instructions) in `scripts/install_matrix.json` and expose it via the Python matrix helper without changing current distro/package behavior.
- Behaviors to keep: existing distro profile detection, package lists, and plugin path templates remain untouched; installer continues to function without compositor data when absent.
- Edge cases: missing `XDG_CURRENT_DESKTOP` / `XDG_SESSION_TYPE`; users forcing `--profile`; manifests without `compositors` must be ignored safely.
- Risks: breaking the manifest loader or match logic; shell eval injection if fields are not quoted.
- Mitigations: keep helper output quoted, add a no-op path when compositor data is absent, and document the schema.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Define `compositors` schema (match hints, env overrides, instructions) in `scripts/install_matrix.json` | Completed |
| 1.2 | Extend matrix helper to emit compositor entries (list/by-id/match modes) alongside existing distro data | Completed |
| 1.3 | Add compositor detection/match in the installer (using session + desktop hints) gated behind safe defaults | Completed |

**Stage 1.1 working plan**
- Capture current manifest shape (plugin paths, distro entries) and decide where to add `compositors` without breaking existing consumers.
- Define fields for each compositor entry: `id`, `label`, `match` (session types, desktops, optional requires_force_xwayland), `env_overrides` (key/val map for `QT_*`, `EDMC_OVERLAY_FORCE_XWAYLAND`), `notes` (user-facing guidance), and optional `provenance` hint for logging.
- Keep schema backwards compatible: existing installers must ignore unknown top-level keys; do not rename current keys.
- Add example entries for `kwin-wayland`, `gnome-shell`, and `wlroots` to clarify usage (values can be placeholders until implementation).
- Update docstring/comments near `scripts/install_matrix.json` and note any future unit tests to validate schema shape once helper is wired (ties into Phase 3/Stage 3.1).

**Stage 1.2 working plan**
- Extend the Python `matrix_helper` to load `compositors` and support `list`, `by-id`, and `match` modes for compositor entries (parallel to distro profiles).
- Decide on shell-friendly output: emit `COMPOSITOR_ID`, `COMPOSITOR_LABEL`, `COMPOSITOR_MATCH_JSON`, `COMPOSITOR_ENV_OVERRIDES_JSON`, `COMPOSITOR_NOTES` (array), `COMPOSITOR_PROVENANCE`; JSON strings allow safe parsing in bash without eval injection.
- Keep backward compatibility: existing modes (`paths`, distro `list`, `match`, `by-id`) remain unchanged; unknown keys ignored by older installers.
- Add defensive defaults when compositor data is absent; helper should emit nothing and exit cleanly so installers without compositor support still work.
- Note unit test hooks to add in Stage 3.1 for helper output (fixture manifest -> expected fields) once wiring is done.

**Stage 1.3 working plan**
- Detection inputs: use `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP` (tokenised), and optional CLI override to select a compositor via `matrix_helper compositor-match`.
- Installer flow: after distro profile detection, invoke compositor match; if found, show label/provenance/overrides/`requires_force_xwayland` and prompt to apply (honour `--yes` for noninteractive).
- Application rules: apply overrides only when env vars aren’t already set; include `EDMC_OVERLAY_FORCE_XWAYLAND=1` when `requires_force_xwayland` is true; otherwise leave it unchanged. Write to `overlay_client/env_overrides.json` (create if missing, never clobber existing keys), dry-run aware.
- Safeguards: no-op when no compositor match; keep legacy behaviour untouched if manifest lacks compositors; log why overrides were applied or skipped (already set, declined, no match).
- CLI flag to consider: `--compositor <id|auto|none>` for forcing/skip debugging; default is auto.
- Tests to add later (Stage 3.1): bash-level helper integration to assert match output is wired into shell vars, and installer flow unit to ensure overrides are conditionally applied.

### Phase 2: Installer flow + overlay env consumption
- Goal: let the installer offer compositor-specific overrides (e.g., disable Qt auto-scaling on KDE+Xwayland, force Xwayland when recommended) and persist them in an overlay env overrides file; have the runtime consume this via a dedicated helper (not bolting more into `load.py`) that merges overrides without clobbering user-set env.
- Behaviors to keep: user-supplied env vars take precedence; non-Wayland/X11 paths remain unchanged; forced Xwayland preference respected.
- Edge cases: already-set `QT_*` vars; flatpak vs host paths; installer noninteractive `--yes` mode; absence of write permission to override file; upgrades must not overwrite an existing `env_overrides.json`; user must be told when compositor detection triggered overrides and exactly which vars/values will be set; legacy `force_xwayland` pref still present in `overlay_settings.json`; need to record in `env_overrides.json` what was detected/why the overrides were set.
- Risks: clobbering user env, applying overrides on unsupported compositors, leaving partial config on failure, wiping user overrides during upgrades, silently changing behavior without informing the user, or diverging between legacy pref and override file; missing provenance in `env_overrides.json` makes support harder.
- Mitigations: only set when absent; prompt/opt-in; write to a dedicated `overlay_client/env_overrides.json` (or similar) with atomic write; log when applied and when skipped; preserve existing `env_overrides.json` on upgrade (create only if missing); emit a clear installer message that compositor detection recommends overrides and list the vars/values before applying; keep reading legacy `force_xwayland` for backward compatibility but prefer the override file when present; include detection context/provenance fields in `env_overrides.json` (e.g., compositor/session matched); implement an `env_overrides` helper module that merges overrides into the runtime env and logs applied/skipped keys.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add installer prompt/flag to apply compositor override block and write to the override file (with `--yes` auto-apply) | Completed |
| 2.2 | Add an `env_overrides` helper module and wire `load.py::_build_overlay_environment` (and controller) to consume it without clobbering set env vars | Completed |
| 2.3 | Emit logging/notes when compositor overrides are applied or skipped to aid support/debug | Completed |

**Stage 2.1 working plan**
- Installer flags/flow: use existing compositor detection output to present label/provenance/overrides and prompt to apply; honour `--yes` for noninteractive installs and `--compositor none|<id>|auto`.
- File write: persist overrides into `overlay_client/env_overrides.json` (create if missing, never overwrite existing keys), adding detection provenance and `requires_force_xwayland` when applicable; skip keys already set in the environment.
- Safety: dry-run support; preserve existing override file on upgrade; short-circuit when no compositor match or overrides empty.
- User messaging: clearly list the vars/values that will be set (and any forced Xwayland) before applying.
- Tests to add in Stage 3.1: bash-level tests asserting compositor match triggers prompt/output and that env_overrides.json write is skipped/applied as expected.

**Stage 2.2 working plan**
- Helper module: add `overlay_client/env_overrides.py` (or similar) to load/validate `env_overrides.json` and merge into a provided env dict without overwriting keys already set in `os.environ`.
- API shape: pure helpers like `load_overrides(path: Path) -> dict` and `apply_overrides(env: dict, overrides: dict, logger=None) -> MergeResult(applied, applied_values, skipped_env, skipped_existing, provenance)`.
- Consumption: call helper from `load.py::_build_overlay_environment` and controller env builder so both respect installer overrides; keep user env highest precedence; fall back to legacy `force_xwayland` pref only when no override exists.
- Logging: emit a concise summary of applied/skipped keys and provenance (guard to DEBUG or a single INFO line).
- Edge cases: missing/invalid JSON (graceful skip), empty overrides, already-present keys, cross-platform path resolution (guard non-Linux).
- Tests: unit tests for helper load/merge; adjust existing env-build tests to assert overrides are honored without clobbering user env.

**Stage 2.3 working plan**
- Logging scope: add concise INFO/DEBUG lines when compositor overrides are applied or skipped, including which keys and why (env-set, already present, user declined).
- Surfaces: installer summary (already in place), runtime logs when overrides are merged, and mention in `collect_overlay_debug_linux.sh` output to aid support (list applied keys and provenance).
- Noise control: keep detailed lists at DEBUG; INFO gets a single summary line; avoid duplicating logs on every launch if nothing applied.
- Tests: small unit/assertion updates to ensure logging calls don’t break when overrides are empty or malformed; bash helper test can remain minimal.

### Phase 3: Tests, docs, validation
- Goal: cover the new data paths and document how/when compositor overrides are used.
- Behaviors to keep: existing tests remain green; docs match shipped behavior.
- Edge cases: parser tolerates missing/new fields; override file readability issues.
- Risks: silent regressions in env construction; unclear user guidance; debug tooling missing override visibility.
- Mitigations: targeted unit tests, README updates, manual smoke for KDE Wayland + forced Xwayland, and extend `collect_overlay_debug_linux.sh` to capture `env_overrides.json` provenance/values.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Add unit tests for matrix helper compositor output and `_build_overlay_environment` override application | Completed |
| 3.2 | Update README/Linux install docs to describe compositor-aware behavior and opt-in | Completed |
| 3.3 | Manual validation notes (KDE/Wayland with forced Xwayland and a normal X11 case) | In progress |
| 3.4 | Update `collect_overlay_debug_linux.sh` to gather `env_overrides.json` details (values + detection context) | Completed |

**Stage 3.1 working plan**
- Extend tests for compositor data flow: verify `matrix_helper` compositor modes still behave, installer override writes/skips in dry-run and real modes, and `env_overrides` helper merges without clobbering existing env.
- Runtime assertions: add tests around `_build_overlay_environment` to ensure overrides are applied, user env wins, and legacy `force_xwayland` only fills in when no override exists.
- CLI coverage: bash-level tests for `--compositor none|<id>|auto` and empty override cases (no file write).
- Keep tests fast/headless with temp dirs/fixtures; avoid touching global env outside scoped mocks.

**Stage 3.2 working plan**
- README updates: document compositor-aware install flow, `--compositor` flag, opt-in overrides (`--yes` auto-apply), and provenance in `overlay_client/env_overrides.json`.
- Call out current recommended overrides (e.g., KDE/Wayland Qt scaling disable) and that force_xwayland is only applied when the compositor entry requests it.
- Add brief troubleshooting note pointing to the debug script’s env overrides section.
- Keep messaging concise and clear about defaults (no global scaling change unless opted in).

**Stage 3.3 working plan**
- Manual validation matrix: run installs/launches on (a) KDE/Wayland with Qt scaling overrides applied, (b) Wayland compositor that does not request force_xwayland, and (c) a plain X11 session to confirm no unintended overrides.
- Verify outcomes: compositor prompt appears with correct label/notes, `env_overrides.json` populated when accepted, runtime logs show applied/skipped keys, and overlay scales/positions correctly.
- Edge checks: ensure `--compositor none` suppresses prompts, `--compositor <id>` forces the intended overrides, and upgrades preserve existing `env_overrides.json`.
- Record results and any manual tweaks needed for README/troubleshooting.

**Stage 3.3 validation checklist**
- [ ] KDE/Wayland (KWin): installer prompts with KDE label/provenance; overrides written (Qt scaling only), runtime log shows applied keys; overlay scales/positions correctly.
- [ ] Wayland compositor without force_xwayland (e.g., GNOME Shell): installer either skips overrides or writes none; runtime unchanged; `--compositor none` suppresses prompt/writes.
- [ ] X11 session: no compositor prompt; no env_overrides.json written/touched.
- [ ] Upgrades: rerun installer with existing env_overrides.json; file preserved, no clobber; prompts respect existing values.
- Capture pass/fail notes and update troubleshooting/README if issues found.

**Stage 3.4 working plan**
- Confirm `collect_overlay_debug_linux.sh` always prints the env overrides section (already added) and handles missing/invalid files gracefully.
- Add a short explanatory note in the debug output that overrides are opt-in and list the keys/provenance shown.
- Keep output concise and low-noise; no redaction needed (no secrets stored).
- Validate manually: run the debug script with and without `overlay_client/env_overrides.json` to ensure the section appears and is readable; adjust if needed.
