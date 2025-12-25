## Goal: Address regression introduced in RC1 release.

## Overview
A User on Windows reports they are not getting any messages on [RC 1](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/tag/0.7.5-rc-1) but [Beta 1](https://github.com/SweetJonnySauce/EDMCModernOverlay/releases/tag/0.7.5-beta-release-1) did work. They may be getting some stuff but it's getting scaled off the screen they think.
The 'nudge' setting doesn't seem to work either and they think it's not scaling properly. I asked them to set the physical clamp to true and they reported: Doesn't seem to have changed anything.
- overlay_client/follow_geometry.py changed the core _convert_native_rect_to_qt logic between beta‑1 and RC1. Even when physical_clamp_enabled=False, the new path now computes geometries_match, may force scale_x/scale_y to 1.0 with native origins set to the logical origin, and only drops into the old “logical/native ratio” math when geoms don’t match. In beta‑1 the code always derived scale from logical/native sizes and fell back to 1/dpr when ~1.0, so the math is different regardless of the flag.
- The new clamp flag and per-monitor overrides are guarded by physical_clamp_enabled, but the shared geometry code was still modified. That means RC1 can behave differently (e.g., scaling/position) even with the clamp preference off.
- Checked the tags: overlay_client/follow_geometry.py did not change at all between 0.7.5-alpha-release-9 and 0.7.5-beta-release-1 (git diff 0.7.5-alpha-release-9..0.7.5-beta-release-1 -- overlay_client/follow_geometry.py is empty, and no commits touch that file in that range). The big follow_geometry rewrite only appears between beta1 and RC1.

## Priorities
- Restore beta1 core geometry behavior as the default path.
- Keep physical clamp strictly opt-in and isolated from the legacy path.
- Add comprehensive regression tests to lock both paths before shipping.

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


### Key differences between 0.7.5-beta-release-1 (works) and 0.7.5-rc-1 (user reports broken):

- Physical clamp feature was added end-to-end: new prefs/UI plus per-monitor overrides (overlay_plugin/preferences.py), new config fields emitted (load.py), new client setters and follow plumbing (overlay_client/control_surface.py, follow_surface.py, follow_geometry.py). Scaling math in follow_geometry.py was rewritten to handle fractional DPI/clamp/overrides and now decides differently even when clamp is off.
- Defaults changed in overlay_settings.json: force_render flipped to false, show_debug_overlay false, max_font_point dropped to 12, and new physical_clamp_* entries were added (allow_force_render_release was later removed).
- Debug overlay is now gated by diagnostics (load.py), so it won’t show unless diagnostics logging is enabled.
- Additional tests/docs/scripts were added around clamp/geometry and Windows install, but functional deltas are mainly the new clamp/scaling logic and default changes.
- Given the user’s “scaled off screen / clamp toggle has no effect” report, the only substantive behavioural change between those builds is the new clamp/scaling logic and related defaults in RC1.

### Options to Contain the RC1 Regression
- Default to legacy geometry when clamp is off: restore the beta1 `_convert_native_rect_to_qt` math as the fallback path and only execute the new clamp/override branches when `physical_clamp_enabled` is true.
- Add an explicit runtime switch: e.g., a `scale_mode` or feature flag that picks legacy vs clamp-aware geometry; ship with legacy as the default and let users opt into clamp.
- Hotfix RC2 path: revert `follow_geometry.py`/`follow_surface.py` to beta1 behavior, reapply clamp branches behind the flag, keep new prefs/UI/config wiring intact, and release.
- Add regression coverage: tests that assert the clamp-disabled path matches beta1 outputs for fractional DPI/geometry cases, plus tests that cover clamp-enabled and per-monitor override paths separately.

### High level plan
Restoring the beta‑1 geometry path as the default (or reverting follow_geometry/follow_surface to beta‑1 and only running the new clamp logic when the flag is on) has the highest chance of success. It preserves the proven behaviour for everyone by default and keeps the clamp feature gated, minimizing risk versus adding new switches or partial tweaks.


## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Restore beta1 geometry path as default | Completed |
| 2 | Gate physical clamp as opt-in | Completed |
| 3 | Regression coverage (legacy vs clamp) | Completed |
| 4 | Packaging/verification | In Progress |

## Phase Details

### Phase 1: Restore beta1 geometry path
| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Snapshot beta1 `_convert_native_rect_to_qt` behavior (scales/origins for fractional vs whole DPR; WM override handling) as expected outputs | Completed |
| 1.2 | Reintroduce beta1 geometry as the default path when `physical_clamp_enabled` is false (no clamp branches executed) | Completed |
| 1.3 | Keep logging parity and verify callers (follow_surface) remain unchanged | Completed |

**Stage 1.1 results**
- Added regression tests capturing beta1 outputs for clamp-off paths: fractional DPR, integer DPR, mismatched logical/native geometries, and WM override resolution (see `overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (16 passed).
- These baselines will be used to validate that restoring the legacy path preserves beta1 behavior while clamp remains gated.

**Stage 1.2 plan (for traceability)**
- Goal: Make clamp-disabled executions use the untouched beta1 geometry math; clamp/overrides run only when explicitly enabled.
- Steps: add a standard (beta1) helper with the original math; dispatch in `_convert_native_rect_to_qt` based on `physical_clamp_enabled`; keep clamp logging/overrides in the gated path; avoid shared state in the standard path.
- Risks: standard math accidentally altered; clamp globals leaking into standard; mis-threaded flag. Mitigations: isolate helpers, reuse baselines, add dispatch tests.

**Stage 1.2 results**
- Implemented dispatcher: `_convert_native_rect_to_qt` now calls `_convert_native_rect_to_qt_standard` (beta1 math) when clamp is off, and `_convert_native_rect_to_qt_clamp` when clamp is on; clamp globals/logging are confined to the clamp path.
- Added dispatch unit tests plus adjusted expectations to beta1 behavior (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (18 passed).

**Stage 1.3 plan (for traceability)**
- Goal: Ensure follow_surface/control_surface callers are unchanged by the dispatch refactor and that logging behavior for the standard path matches beta1 (no new noise when clamp is off).
- Steps: verify call sites, ensure clamp logs stay gated, and add log-capture/integration tests for standard vs clamp paths.
- Risks: log spam/missing logs, mis-threaded flags, globals cross-talk. Mitigations: log-capture tests, monkeypatch dispatch integration, reset globals in tests.

**Stage 1.3 results**
- Added log-capture tests to assert the standard path emits no clamp-specific logs and the clamp path logs once when enabled; added a follow_surface integration test to confirm the flag routes to standard vs clamp helpers.
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (21 passed).

#### Stage 2.1 Plan (Gate clamp/override branches strictly on flag)
- Goal: Ensure clamp/override logic runs only when `physical_clamp_enabled` is true and the standard path stays untouched otherwise.
- Steps:
  1) Audit follow_surface/control_surface state flows to confirm `_physical_clamp_enabled` defaults false and is only flipped via prefs/config payloads; ensure overrides aren’t applied implicitly.
  2) Verify `_convert_native_rect_to_qt_clamp` is only reachable via the dispatcher; add guards/early-returns so overrides are ignored when the flag is false.
  3) Ensure standard helper never inspects overrides; keep clamp-specific globals/logging confined to the clamp helper.
  4) Add tests covering overrides-present-but-flag-false (no effect) and overrides-applied-when-flag-true after a runtime toggle.
- Risks:
  - Risk: Hidden code path applies clamp math without the flag (e.g., cached state/resume). Mitigation: runtime toggle tests exercising successive calls with flag false then true, asserting path selection and outputs.
  - Risk: Overrides leak into the standard path via shared attributes. Mitigation: guard standard helper from reading overrides; test overrides with flag false against beta1 baselines.
  - Risk: UI/config sets overrides while flag false, causing surprises later. Mitigation: tests that set overrides while off and verify no effect until flag is enabled.
- Tests to add:
  - Follow/control integration: set overrides with clamp off → standard output unchanged; enable clamp → overrides applied.
  - Geometry unit: overrides provided but flag false → outputs match beta1 baselines.
  - Runtime toggle: call once with clamp off, then on with overrides, asserting correct path and override application.

**Stage 2.1 results**
- Follow_surface now drops overrides when the clamp flag is false before dispatching geometry conversion, preventing override use in the standard path.
- Added integration/runtime toggle tests to ensure overrides are ignored when clamp is off and applied after enabling; dispatcher tests updated accordingly (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (23 passed).

#### Stage 2.2 Plan (Clamp logging/overrides strictly gated)
- Goal: Ensure per-monitor overrides and clamp-specific logging only occur when `physical_clamp_enabled` is true, and that both are no-ops when the flag is false.
- Steps:
  1) Audit clamp logging in `_convert_native_rect_to_qt_clamp` and ensure it is never reached when the standard path is used; keep `_last_normalisation_log` usage confined to the clamp path.
  2) Verify no other modules emit clamp/override logs or apply overrides when the flag is false (e.g., developer helpers, setup/control surfaces).
  3) Add log-capture tests to assert: (a) flag off → no clamp/override log lines even if overrides are provided; (b) flag on → clamp logs appear once with overrides applied.
  4) Add tests that pass overrides while flag is false and assert no changes to geometry or logged override messages; then enable flag and assert override application + logging.
- Risks:
  - Risk: Clamp logs leak on the standard path due to shared globals. Mitigation: confine logging to clamp helper and reset `_last_normalisation_log` per log-capture test.
  - Risk: Overrides applied silently via another code path when flag is false. Mitigation: integration tests with follow_surface/control_surface using overrides and log capture to assert no application/logging until flag is true.
  - Risk: Double-logging when toggling flag. Mitigation: assert single log emission across successive clamp-on calls with the same inputs.
- Tests to add:
  - Log-capture: overrides present, flag false → no clamp/override logs.
  - Log-capture: flag true with overrides → clamp/override logs emitted once across repeated calls.
  - Integration: follow_surface/control_surface with overrides, flag false → standard outputs/logs; flag true → overrides applied/logged.

**Stage 2.2 results**
- Logging and overrides remain gated: clamp helper logging is confined there, and follow_surface drops overrides when clamp is off.
- Added log-capture tests to assert no clamp/override logs with flag false and single emission when true; added integration tests to confirm overrides are ignored until clamp is enabled (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (25 passed).

#### Stage 3.1 Plan (Clamp-off regression coverage vs beta1)
- Goal: Ensure clamp-disabled outputs remain identical to beta1 across key scenarios (fractional DPI, integer DPI, matching/non-matching geometries, WM overrides).
- Steps:
  1) Reuse beta1 baselines from Stage 1.1 (fractional/integer DPR, mismatched geoms) and extend to include WM override scenarios under clamp-off.
  2) Add explicit tests that compare `_convert_native_rect_to_qt_standard` outputs to known beta1 values, and that the dispatcher with `physical_clamp_enabled=False` matches the same outputs.
  3) Include WM override resolution cases (active, expired, tracker realigned) to assert clamp-off behavior is unchanged.
  4) Document expected outputs in test names/assertions to serve as regression anchors for future refactors.
- Risks:
  - Risk: Floating point drift causing flaky tests. Mitigation: use consistent tolerances (`pytest.approx` with sensible abs tolerances) and integer rounding that mirrors beta1 behavior.
  - Risk: Missing edge cases (e.g., near-unity DPR, negative/zero sizes). Mitigation: include near-unity DPR and invalid-rect guards; ensure zero/negative dimensions return early as in beta1.
  - Risk: Dispatcher changes affecting baselines. Mitigation: test both direct standard helper and dispatcher with `physical_clamp_enabled=False`.
- Tests to add:
  - Clamp-off fractional DPR baseline (existing) plus near-unity DPR case referencing beta1 expectation.
  - Clamp-off integer DPR baseline (existing) kept as regression.
  - Clamp-off mismatched geometry baseline (existing) plus WM override active/expired/realigned cases under clamp-off.
  - Dispatcher with clamp-off matches `_convert_native_rect_to_qt_standard` outputs for the above scenarios.

**Stage 3.1 results**
- Added clamp-off regression tests covering fractional/integer/near-unity DPR, mismatched geometries, WM override scenarios (active/expired/realigned), and dispatcher vs `_convert_native_rect_to_qt_standard` parity (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (28 passed).

#### Stage 3.2 Plan (Clamp-on regression coverage)
- Goal: Lock clamp-on behavior: fractional DPR is preserved, overrides are clamped to 0.5–3.0, and clamp-specific logging occurs once.
- Steps:
  1) Add tests for fractional DPR with clamp on to assert scale stays 1:1 (no shrink) unless an override is applied.
  2) Add override clamp tests: values below 0.5 or above 3.0 are clamped; invalid values ignored; resulting geometry and scale reflect the clamped override.
  3) Add log-capture tests for clamp-on with overrides to assert single emission of clamp and override logs across repeated calls.
  4) Add dispatcher parity: `physical_clamp_enabled=True` uses the clamp helper and applies overrides.
- Risks:
  - Risk: Flaky logs if logger propagation changes. Mitigation: set propagate in tests and reset logger state; reuse existing log-capture pattern.
  - Risk: Over-clamping bounds drifting. Mitigation: assert explicit 0.5/3.0 boundaries in tests.
  - Risk: Overrides with bad values causing unexpected behavior. Mitigation: test NaN/zero/negative/None paths to ensure they’re ignored.
- Tests to add:
  - Clamp-on fractional DPR, no overrides → scale 1.0, logs once.
  - Clamp-on with overrides below/above bounds → applied at 0.5/3.0 with expected geometry.
  - Clamp-on override invalid values ignored.
  - Dispatcher with clamp-on + overrides uses clamp helper (parity check).

**Stage 3.2 results**
- Added clamp-on regression tests covering fractional DPR (no shrink), override clamping to 0.5/3.0, invalid overrides ignored, single-emission log checks, and dispatcher parity with overrides (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (33 passed).

#### Stage 3.3 Plan (Integration: routing clamp flag through follow/control surfaces)
- Goal: Verify end-to-end that follow_surface/control_surface route the clamp flag and overrides correctly: clamp off uses the standard path; clamp on uses the clamp path and applies overrides.
- Steps:
  1) Add integration-style tests that create a stub window (FollowSurfaceMixin/ControlSurfaceMixin), toggle `_physical_clamp_enabled`, set `_physical_clamp_overrides`, and assert the appropriate helper is invoked and outputs match expectations.
  2) Cover runtime toggles: call once with clamp off (standard path), then enable clamp and ensure clamp helper is used with overrides; also verify disabling clamp reverts to standard path.
  3) Ensure overrides set while clamp is off do not affect geometry until clamp is on.
  4) Optionally include a control_surface test to ensure setter pathways don’t apply overrides when clamp is disabled.
- Risks:
  - Risk: State leakage between calls (e.g., overrides applied when flag off). Mitigation: reset state per test; assert override usage only when flag on.
  - Risk: Tests become too brittle around logging or internal attributes. Mitigation: focus on helper invocation and output, not log strings, for integration checks.
  - Risk: Follow/controller interactions not fully simulated. Mitigation: use stub mixins and direct method calls to isolate geometry routing.
- Tests to add:
  - Follow surface integration: clamp off → standard helper called; clamp on with overrides → clamp helper called with overrides; subsequent clamp off → standard again.
  - Control surface setter test: overrides set while clamp false do not apply geometry; enabling clamp then uses overrides.

**Stage 3.3 results**
- Added integration tests to verify routing through follow_surface/control_surface: clamp off uses the standard helper; clamp on applies overrides via the clamp helper; disabling clamp returns to standard; control surface overrides do not apply when clamp is off (`overlay_client/tests/test_follow_geometry.py`).
- Tests executed: `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (35 passed).

#### Stage 4.1 Plan (Verification run and documentation)
- Goal: Run the targeted geometry/clamp test suite plus a quick sanity pass, and record results as release readiness evidence.
- Steps:
  1) Run `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` to confirm geometry/clamp regressions stay green.
  2) Optionally run a broader fast subset (e.g., `pytest -k clamp` or `pytest tests/overlay_client`) if available, noting scope and any skips.
  3) Capture command(s) and outcomes in this doc for traceability.
- Risks:
  - Risk: Missing broader regressions outside the geometry suite. Mitigation: at least one wider quick pass (`pytest` scoped to overlay_client) if time allows; note any unrun suites.
  - Risk: Env drift causing flaky tests. Mitigation: use the existing venv; rerun failing tests once to confirm reproducibility before triaging.
- Tests to run:
  - `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py`
  - (Optional) `./.venv/bin/python -m pytest tests/overlay_client` or `pytest -k clamp` for a broader sweep.

**Stage 4.1 results**
- Ran `./.venv/bin/python -m pytest overlay_client/tests/test_follow_geometry.py` (35 passed) as the targeted geometry/clamp suite.
- No broader sweep run yet; Phase 4.2 will handle packaging/Windows sanity checks.
#### Stage 1.3 Plan (Logging parity and caller verification)
- Goal: Ensure follow_surface/control_surface callers are unchanged by the dispatch refactor and that logging behavior for the standard path matches beta1 (no new noise when clamp is off).
- Steps:
  1) Review `_screen_info_for_native_rect` usages and call sites in follow_surface/control_surface to confirm no state changes are needed and the flag threading remains correct.
  2) Adjust logging guards so the standard path does not emit clamp-specific logs; confirm `_last_normalisation_log`/`_last_wm_override_log` only affect the clamp path or are reset appropriately.
  3) Add tests that simulate follow_surface calling `_convert_native_rect_to_qt` with clamp off/on and assert no unexpected debug logs for the standard path while clamp logs still appear when enabled.
  4) Confirm WM override logging still follows beta1 expectations in the standard path.
- Risks:
  - Risk: Logging spam or missing logs in clamp-on path. Mitigation: Targeted log-capture tests for both paths.
  - Risk: follow_surface inadvertently holding clamp state or mis-routing after refactor. Mitigation: Integration test that toggles clamp and inspects which helper was invoked (stub/monkeypatch).
  - Risk: Shared globals causing cross-talk between successive calls. Mitigation: Reset globals in tests and ensure standard path leaves clamp globals untouched.
- Tests to add:
  - Log capture test for standard path to assert no clamp-specific messages when clamp is off.
  - Log capture test for clamp path to assert clamp/debug logs still appear once.
  - Integration test in follow_surface/control_surface to ensure the flag routes to the correct helper and WM override logging remains stable.

#### Stage 1.2 Plan (Restore beta1 geometry as default when clamp is off)
- Goal: Make clamp-disabled executions use the untouched beta1 geometry math; clamp/overrides run only when explicitly enabled.
- Steps:
  1) Refactor `_convert_native_rect_to_qt` to dispatch: if `physical_clamp_enabled` is false, use a pure beta1 path (use the baseline code or a faithful copy); if true, run the clamp/override path.
  2) Ensure follow_surface callers pass the flag but do not alter behavior when false; no shared state carries clamp changes into the legacy path.
  3) Keep logging parity for the legacy path (minimal/no extra noise) and retain clamp logs only in the gated path.
- Risks:
  - Risk: Mixing code paths and accidentally altering the legacy math (e.g., changed origins or DPR handling). Mitigation: isolate the beta1 logic into a helper and reuse the existing baselines to assert outputs are identical for clamp-off.
  - Risk: Hidden side effects from new globals/state (e.g., `_last_normalisation_log`) affecting legacy path. Mitigation: keep those guards only in the clamp path or reset per call; ensure legacy path does not mutate clamp-specific globals.
  - Risk: Follow_surface/control_surface may cache clamp flags; regressions if the flag is mis-threaded. Mitigation: add an integration test asserting clamp=false routes to the legacy helper, and clamp=true routes to the clamp helper.
- Tests to add:
  - Clamp-off regression: reuse/add tests to confirm outputs exactly match Stage 1.1 baselines when `physical_clamp_enabled=False`.
  - Clamp-on regression: existing clamp-on tests should still pass; add a targeted test to assert the dispatcher calls the clamp path when enabled.
  - Integration: a follow_surface/control_surface test that toggles the flag and asserts the correct helper is invoked (using a stub or monkeypatch to capture calls).

#### Stage 1.1 Plan (Snapshot beta1 behavior)
- Goal: Capture the exact beta1 geometry outputs to use as ground truth for regression tests (clamp off).
- Steps:
  1) Pull the beta1 version of `_convert_native_rect_to_qt` and identify representative cases: matching logical/native geometry with fractional DPR (1.25/1.5), matching geometry with integer DPR (1.0/2.0), non-matching geometry (logical/native differ), and WM override scenarios.
  2) Encode those cases into deterministic unit tests that assert the returned Qt rect, scale_x/scale_y, and device_ratio mirror beta1 results when `physical_clamp_enabled` is false.
  3) Add fixtures/helpers in `overlay_client/tests/test_follow_geometry.py` to reuse across clamp-off and clamp-on paths.
- Risks:
  - Risk: Misremembering beta1 outputs and baking in wrong expectations. Mitigation: Diff directly against tag `0.7.5-beta-release-1` and, if needed, run the old function via inline fixture to capture numeric outputs.
  - Risk: Floating point flakiness in assertions. Mitigation: Use `math.isclose` tolerances consistent with existing tests; avoid over-tight tolerances.
  - Risk: WM override behavior subtly changed; missing a case. Mitigation: Include at least one override-active and one override-expired scenario in tests to assert target rect resolution.
- Tests to add (unit):
  - `test_convert_native_rect_to_qt_clamp_off_fractional_dpr_matches_beta1`
  - `test_convert_native_rect_to_qt_clamp_off_integer_dpr_matches_beta1`
  - `test_convert_native_rect_to_qt_clamp_off_mismatched_geometry_scales_like_beta1`
  - `test_resolve_wm_override_matches_beta1_behavior`

### Phase 2: Gate physical clamp as opt-in
| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Ensure clamp/override branches only run when `physical_clamp_enabled` is true; baseline math untouched otherwise | Completed |
| 2.2 | Keep per-monitor overrides and clamp logging within the gated path; no-op when flag is false | Completed |
| 2.3 | Optional: add escape-hatch flag to force legacy geometry independent of prefs | Skipped (decided not to implement) |

### Phase 3: Regression coverage
| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Add tests asserting clamp-off outputs match beta1 baselines (fractional DPI, matching/non-matching geoms, WM override scenarios) | Completed |
| 3.2 | Add tests for clamp-on path (fractional DPR retained, per-monitor overrides clamped 0.5–3.0, logging expectations) | Completed |
| 3.3 | Add integration test to ensure follow_surface/control_surface routes clamp flag to the right geometry path | Completed |

### Phase 4: Packaging/verification
| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Run targeted test filters and quick suite; document results | Not Started |
| 4.2 | Build RC2 artifact; sanity-check Windows behavior (legacy path + clamp-on opt-in) | Not Started |
