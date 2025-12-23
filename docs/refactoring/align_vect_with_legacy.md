## Goal: Refactor vect to be fully backwards compatible with EDMCOverlay (Legacy)

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
| 1 | Align vect rendering semantics with legacy (default behavior change) | Completed |
| 2 | Align label placement with legacy | Completed |
| 3 | Align rectangle border fallback with legacy | Completed |
| 4 | Honor newline (`\n`) in text like legacy | Completed |

## Phase Details

### Phase 1: Align vect rendering with legacy (no gating flag)
- Goal: make Modern Overlay render `vect` exactly like legacy without a feature flag (default behavior change).
- Behavior targets:
  - Use the payload’s top-level `color` for all line segments (ignore per-point `color` when setting the pen).
  - Keep per-point colors for markers/text (matches legacy); OK to drop per-point line color support.
  - Draw line segments only when 2+ points are present; do not auto-duplicate a single point.
  - Preserve single-point vectors when they include marker/text (legacy callers rely on this for label/marker-only payloads).
- Behavior changes (implemented):
  - Line segments always use the payload `base_color` (per-point line colors ignored).
  - Single-point vectors are only kept if they contain marker/text; otherwise they are dropped.
- Tests to add:
  - 2-point payload with mixed per-point colors → line uses base color, markers/text use per-point color.
  - 1-point payload with marker/text → marker/text drawn, no line drawn.
  - 1-point payload without marker/text → rejected/dropped/ignored.
  - 3+ points → confirm consecutive segments all use base color, markers/text still per-point.
- Risks: breaking consumers relying on per-point line colors or single-point line rendering; regressions in grouping/transform paths.
- Mitigations: targeted tests above; document the behavioral change; keep code paths small to ease revert.
- Compatibility note: EDMC-BioScan sends single-point vect payloads for markers/text; preserving marker/text-only single points maintains parity with legacy overlay behavior.

#### Phase 1 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py -h` to confirm the venv + PyQt6 setup before any changes.
- Sequence:
  1) Stage 1.1: adjust normalization in `EDMCOverlay/edmcoverlay.py` and `overlay_client/legacy_processor.py` to stop duplicating single points while keeping marker/text-only single points.
  2) Stage 1.2: update `overlay_client/vector_renderer.py` to use base color for all line segments.
  3) Stage 1.3: add tests for single-point marker/text, single-point drop, mixed colors, and 3+ points.
  4) Stage 1.4: document behavior change + tests run in this file.
- Risks + mitigations/tests:
  - Behavioral regression for callers relying on per-point line colors or 1-point lines. Mitigation: targeted vector renderer/legacy processor tests; log drops for visibility.
  - Bioscan radar label/marker loss if single-point marker/text is dropped. Mitigation: explicitly preserve marker/text-only single points; validate with bioscan payload log and tests.
  - CI flakiness: low; run scoped tests (`-k legacy_processor`/`-k vector`) plus broader pytest if needed.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Adjust legacy shim normalization to stop duplicating single points; allow marker/text-only single points to pass through; log/drop otherwise | Completed |
| 1.2 | Change vector renderer to use base color for segments, preserve per-point colors for markers/text | Completed |
| 1.3 | Add/update tests covering 1-point marker/text, 1-point without marker/text, 2-point mixed colors, 3+ points | Completed |
| 1.4 | Document behavioral change and test steps in the refactor notes | Completed |

#### Stage 1.1 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py -h` to confirm environment readiness.
- Implementation steps:
  1) Update `EDMCOverlay/edmcoverlay.py` to keep a single point only when it has `marker` or `text`; otherwise return `None` and avoid duplication.
  2) Update `overlay_client/legacy_processor.py` to stop duplicating single points; keep marker/text-only single points, otherwise drop/log as insufficient.
  3) Keep logging minimal and consistent (reuse existing shim warning; add a legacy processor warning/trace only if needed for visibility).
- Risks + mitigations/tests:
  - Drop of line-only single-point payloads: expected; mitigated by preserving marker/text-only cases and adding tests in Stage 1.3.
  - Compatibility regressions for other vect consumers: mitigated by logging and focused tests.
- Tests to run after Stage 1.1:
  - `.venv/bin/python tests/configure_pytest_environment.py -k legacy_processor`
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector`

#### Stage 1.1 Results
- Outcome: single-point duplication removed in the shim and legacy processor; marker/text-only single points preserved; insufficient single-point vectors now drop with a warning and trace hook.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k legacy_processor`; `.venv/bin/python tests/configure_pytest_environment.py -k vector`.
- Issues/Follow-ups: none.

#### Stage 1.2 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py -h` to confirm environment readiness.
- Implementation steps:
  1) Update `overlay_client/vector_renderer.py` to set the pen color from `base_color` for all line segments (stop using per-point colors for lines).
  2) Leave marker/text color selection unchanged (per-point color or base color fallback).
  3) Keep tracing output intact; avoid new behavior flags.
- Risks + mitigations/tests:
  - Behavioral regression: per-point line color no longer renders. Mitigation: document in Phase 1 notes; add coverage in Stage 1.3 for mixed-color payloads.
  - Unexpected line color fallback behavior: mitigate with renderer tests and payload samples.
  - CI flakiness: low; run focused tests.
- Tests to run after Stage 1.2:
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector`

#### Stage 1.2 Results
- Outcome: line segments now always use the payload `base_color`; marker/text colors still use per-point color or base color fallback.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`; `.venv/bin/python tests/configure_pytest_environment.py -k vector`.
- Issues/Follow-ups: none.

#### Stage 1.3 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py -h` to confirm environment readiness.
- Implementation steps:
  1) Add a vector renderer test that asserts line segments always use `base_color` even when per-point colors differ, while markers/text keep per-point colors.
  2) Add legacy processor tests for 1-point marker/text vectors (kept) and 1-point without marker/text (dropped).
  3) If needed, add shim-level tests for `normalise_legacy_payload` single-point handling (drop vs keep marker/text).
- Risks + mitigations/tests:
  - Behavioral regression not captured by tests: mitigate by covering 1-point keep/drop and mixed color lines.
  - Flaky test expectations due to ordering: mitigate by asserting on captured operations explicitly (no ordering assumptions beyond the line list).
  - CI flakiness: low; run focused tests.
- Tests to run after Stage 1.3:
  - `.venv/bin/python tests/configure_pytest_environment.py -k legacy_processor`
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector`

#### Stage 1.3 Results
- Outcome: added coverage for single-point marker/text retention vs drop, plus line segment base color behavior with mixed per-point colors.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k legacy_processor`; `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`; `.venv/bin/python tests/configure_pytest_environment.py -k vector`.
- Issues/Follow-ups: none.

#### Stage 1.4 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py -h` to confirm environment readiness.
- Implementation steps:
  1) Update Phase 1 notes to explicitly document the behavior changes (single-point marker/text preserved, single-point line-only dropped, base color for segments).
  2) Record the tests run across Stages 1.1–1.3 in the notes for quick audit.
  3) Mark Stage 1.4 as completed once documentation is updated.
- Risks + mitigations/tests:
  - Documentation drift: mitigate by referencing the exact behaviors and test commands already executed.
  - Missed test traceability: mitigate by listing all executed test commands in the Stage 1.4 results.
- Tests to run after Stage 1.4:
  - None (documentation-only stage).

#### Stage 1.4 Results
- Outcome: documented Phase 1 behavior changes and captured tests run for auditability.
- Tests: none (documentation-only).
- Issues/Follow-ups: none.

### Phase 2: Make marker label placement configurable (default legacy offset)
- Goal: keep Modern Overlay's default label placement aligned with legacy (Y+7 to top-left of the text box), while allowing per-plugin vertical positioning for other layouts.
- Current difference:
  - Legacy: `DrawTextEx(..., marker_x + 2, marker_y + 7)` uses `(x,y)` as text top-left; `+7` pushes text below the line/marker.
  - Modern: `draw_text(x + 8, y - 8, ...)` then adds font ascent internally, effectively keeping text in-line with the marker.
- Target behavior:
  - Default position is `below`: Y+7 applies to the **top of the text box** (top-left anchor), matching legacy.
  - Introduce optional `markerLabelPosition` in `define_plugin_group` schema/API with values `below`, `above`, `centered`.
  - `below`: top of text box at Y+7 (legacy default).
  - `above`: bottom of text box at Y-7 (requires font height to compute top).
  - `centered`: middle of text box at Y+0 (requires font height to compute top).
- Tests/checks:
  - Ensure default `below` matches legacy placement (top-left anchor at Y+7).
  - Add config-driven coverage for `markerLabelPosition` values `below`, `above`, `centered` to verify placement relative to text box.
  - Visual regression for bioscan radar and navroute to confirm per-plugin offsets behave as expected.
- Risks: introducing a new plugin-group setting could drift across schema/controller/client or cause unexpected offsets for existing configs.
- Mitigations: schema validation for allowed values; default `below` in loader; targeted tests for API/schema + renderer offsets; document the new option.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add `markerLabelPosition` (`below`/`above`/`centered`) to `define_plugin_group` schema/API with default `below`; update loader/config plumbing | Completed |
| 2.2 | Apply the configurable position in vector label rendering (default legacy `below`) | Completed |
| 2.3 | Validate bioscan radar + navroute overlays with offset adjustments | Completed |
| 2.4 | Document the new offset option and any observed side effects | Completed |

#### Stage 2.1 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed) to set up the environment before changes.
- Implementation steps:
  1) Extend `schemas/overlay_groupings.schema.json` to allow optional `markerLabelPosition` with enum values `below`, `above`, `centered` and default `below` (top-of-text-box anchor).
  2) Update `overlay_plugin/overlay_api.py` to accept `marker_label_position` (and `markerLabelPosition` if appropriate), validate tokens, and write canonical `markerLabelPosition` into `overlay_groupings.json` when provided.
  3) Plumb the new field through config loaders/overrides with a default of `below` when missing (e.g., `overlay_plugin/groupings_loader.py`, `overlay_client/plugin_overrides.py`, `overlay_client/group_transform.py`).
  4) Keep serialization/normalization consistent with existing plugin group fields (camelCase in JSON; snake_case in Python APIs).
- Risks + mitigations/tests:
  - Schema/API drift or invalid values accepted. Mitigation: strict enum validation in schema and API; add loader tests for invalid values.
  - Default mismatch across layers (schema vs loader vs overrides). Mitigation: set default `below` consistently in schema, loader, and override manager; assert in tests.
  - Inconsistent key naming (camelCase vs snake_case) leading to silent ignores. Mitigation: accept both in API/loader; canonicalize on write; add tests.
- Tests to run after Stage 2.1:
  - `.venv/bin/python tests/configure_pytest_environment.py -k define_plugin_group`
  - `.venv/bin/python tests/configure_pytest_environment.py -k groupings_loader`
  - `.venv/bin/python tests/configure_pytest_environment.py -k plugin_override_loader`

#### Stage 2.1 Results
- Outcome: added `markerLabelPosition` to the schema, API, loader/overrides parsing, and group transforms with default handling (`below`).
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k define_plugin_group`; `.venv/bin/python tests/configure_pytest_environment.py -k groupings_loader`; `.venv/bin/python tests/configure_pytest_environment.py -k plugin_override_loader`.
- Issues/Follow-ups: none.

#### Stage 2.2 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` to confirm the environment before changes.
- Implementation steps:
  1) Plumb `markerLabelPosition` from `GroupTransform` into the vector rendering path (e.g., `_VectorPaintCommand` → `render_vector`), keeping the default `below`.
  2) Update `overlay_client/vector_renderer.py` and the Qt adapter to position text using the **top of the text box**: `below` uses Y+7, `above` uses Y-7 to the **bottom** of the box, `centered` uses Y=0 to the **middle**. This requires measuring the text block height via font metrics (line spacing × line count) to compute the top Y.
  3) Keep X offset logic intact (x+8) and ensure the computed top Y is rounded consistently to avoid jitter.
  4) Add/adjust unit tests to verify `below`/`above`/`centered` placement math without relying on Qt font metrics (fake adapter height), and update any Qt adapter tests as needed.
- Risks + mitigations/tests:
  - Behavioral regression: default `below` shifts existing inline label placement. Mitigation: document the default change, rely on per-plugin overrides, and add targeted tests for the three positions.
  - Cross-platform font metric differences could cause flaky pixel tests. Mitigation: keep unit tests off Qt by faking text heights; avoid hardcoded font metrics in assertions.
  - CI flakiness: low. Mitigation: run focused tests and keep the changes isolated to vector rendering.
  - Installer failures/dependency drift/user upgrade prompts: none (no new deps).
- Tests to run after Stage 2.2:
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`
  - `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector`

#### Stage 2.2 Results
- Outcome: `markerLabelPosition` now drives vector label placement (`below`/`above`/`centered`) using text box height from font metrics; default `below` maps to Y+7 top-of-text placement.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`; `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`; `.venv/bin/python tests/configure_pytest_environment.py -k vector`.
- Issues/Follow-ups: none.

#### Stage 2.3 Results
- Outcome: visual checks on bioscan radar and navroute overlays passed with default `below` placement; `above`/`centered` positions respond as expected.
- Tests: none (visual verification).
- Issues/Follow-ups: none.

#### Stage 2.4 Results
- Outcome: documented `markerLabelPosition` and confirmed no side effects observed during Phase 2 visual checks.
- Tests: none (documentation-only).
- Issues/Follow-ups: none.

### Phase 3: Align rectangle border fallback with legacy
- Goal: match legacy’s behavior when an invalid/empty border color is supplied (e.g., trailing comma `dd5500,` in `igm_config.v9.ini`).
- Current difference:
  - Legacy: `GetBrush` returns null on invalid color, so no border is drawn (only fill).
  - Modern: falls back to white (`QColor("white")`) and draws a border.
- Target behavior: suppress border when the border color is invalid/None to mirror legacy, unless a valid color is provided.
- Tests/checks:
  - Panel payload with invalid color string → no border, fill only.
  - Valid color still draws border at configured width.
  - Visual check on navroute panel and bioscan radar panels to confirm no unintended outlines.
- Risks: other overlays that rely on the fallback border may lose their outline; document any consumers.
- Mitigations: targeted visual checks, note deltas; consider allowing explicit “none” to force no border and valid color to force border.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Change border color handling to skip pen when color is invalid/None | Completed |
| 3.2 | Add regression tests for invalid vs valid border colors | Completed |
| 3.3 | Visual check: navroute panel and bioscan radar panel outlines | Completed |
| 3.4 | Document behavior change and any affected overlays | Completed |

#### Stage 3.1 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed) before code changes.
- Implementation steps:
  1) Review `_build_rect_command` in `overlay_client/render_surface.py` to confirm current invalid-color handling and how legacy rects map to `item["color"]`.
  2) Change invalid border color handling to use `Qt.NoPen` instead of falling back to white; keep `legacy_rect` line width for valid colors.
  3) Leave fill/brush handling unchanged and avoid adding new behavior flags.
  4) Keep logging minimal; add a trace hook only if needed for visibility of invalid colors.
- Risks + mitigations/tests:
  - Some overlays may have relied on the white fallback: mitigated by Stage 3.2 tests and Stage 3.3 visual checks on navroute/bioscan panels.
  - Valid colors misclassified as invalid could drop borders: mitigated by retaining `QColor.isValid()` checks and adding regression tests in Stage 3.2.
  - Silent behavior change: mitigated by documenting in Stage 3.4 and optionally tracing invalid colors.
- Tests to run after Stage 3.1:
  - `.venv/bin/python tests/configure_pytest_environment.py -k rect`
  - `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`

#### Stage 3.1 Results
- Outcome: invalid border colors now skip drawing a border (`Qt.NoPen`) instead of falling back to white; valid border colors still render with `legacy_rect` width.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k rect`; `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`.
- Issues/Follow-ups: none.

#### Stage 3.2 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed) before code changes.
- Implementation steps:
  1) Add unit coverage for legacy rect border handling in the most appropriate test module (likely `overlay_client/tests/test_paint_commands.py` or an existing legacy rect test) to avoid Qt font metric dependencies.
  2) For invalid border color payloads (e.g., empty string, trailing comma `dd5500,`, or `none`), assert that the rect paint command uses `Qt.NoPen` and still applies the fill color.
  3) For valid border colors, assert that the pen is set to the parsed color with the `legacy_rect` width.
  4) Keep assertions focused on paint command state/calls to avoid brittle pixel or font metric checks.
- Risks + mitigations/tests:
  - Qt class construction in tests could make assertions brittle; mitigate by using existing recording painter helpers and asserting on pen/brush types rather than pixel output.
  - Coverage might miss the invalid-color parsing branch; mitigate by explicitly including a malformed color case (e.g., trailing comma) plus empty/none variants.
  - CI flakiness: low; keep tests isolated to paint commands and avoid GUI dependencies.
- Tests to run after Stage 3.2:
  - `.venv/bin/python tests/configure_pytest_environment.py -k rect`
  - `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`

#### Stage 3.2 Results
- Outcome: added regression coverage for invalid border colors (empty/none/malformed) and valid border colors, asserting `Qt.NoPen` vs solid pen with `legacy_rect` width while preserving fill.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k rect`; `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`.
- Issues/Follow-ups: none.

#### Stage 3.3 Results
- Outcome: visual checks on navroute and bioscan radar panels passed; no unintended outlines observed when invalid border colors are supplied.
- Tests: none (visual verification).
- Issues/Follow-ups: none.

#### Stage 3.4 Plan (pre-implementation)
- Preflight: none (documentation-only stage).
- Implementation steps:
  1) Document the behavior change: invalid/empty border colors now suppress the border instead of falling back to white (legacy parity).
  2) Note potential affected overlays/configs that previously relied on the fallback (e.g., malformed color strings like trailing commas).
  3) Record the visual check outcome from Stage 3.3.
- Risks + mitigations/tests:
  - Documentation drift or missed consumers: mitigated by capturing the legacy parity note and pointing to potential invalid-color configs.
  - Confusion about expected border behavior: mitigated by explicitly stating the invalid color handling and recommended fix (use a valid color or `none`).
- Tests to run after Stage 3.4:
  - None (documentation-only stage).

#### Stage 3.4 Results
- Outcome: documented invalid-border handling change, noted legacy parity and potential invalid-color configs, and captured Stage 3.3 visual verification.
- Tests: none (documentation-only).
- Issues/Follow-ups: none.

### Phase 4: Honor newline (`\n`) in text like legacy
- Goal: mirror legacy handling of `\n` as a hard line break for overlay text.
- Approach (minimal risk): in the Qt text painters, split incoming text on `\r\n`/`\n` and render each line with `lineSpacing()` vertical offsets; keep first line anchored at the original baseline. No payload format changes.
- Targets: `_QtVectorPainterAdapter.draw_text` (vector labels) and message painter.
- Tests/checks: add a “Foo\nBar” case for vector labels and messages to ensure two lines render; quick visual on navroute/bioscan overlays.
- Risks: slight shift in vertical sizing if fonts differ; mitigated by localized change and targeted tests.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Implement line splitting/lineSpacing rendering in Qt text painters | Completed |
| 4.2 | Add regression tests for multiline text in vectors/messages | Completed |
| 4.3 | Visual check on navroute and bioscan overlays for multiline labels | Completed |
| 4.4 | Document behavior change and confirm parity with legacy newline handling | Completed |

#### Stage 4.1 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed) before code changes.
- Implementation steps:
  1) Update `_QtVectorPainterAdapter.draw_text` in `overlay_client/paint_commands.py` to split incoming text on `\r\n`/`\n` and draw each line using `lineSpacing()` offsets, keeping the first line anchored at the existing baseline.
  2) Update the message painter path (e.g., `_MessagePaintCommand.paint` in `overlay_client/paint_commands.py`) to apply the same line-splitting logic so multi-line messages render with consistent spacing.
  3) Verify message/vector text measurement helpers still reflect multi-line height (e.g., `measure_text_block` vs single-line measurements) and adjust if needed so bounds/cycle anchors remain correct.
  4) Keep X-offset behavior and font selection unchanged; avoid adding behavior flags.
- Risks + mitigations/tests:
  - Baseline shifts for multi-line text could alter anchor placement: mitigated by keeping the first line anchored and adding Stage 4.2 tests.
  - Cross-platform font metric differences could cause subtle spacing changes: mitigated by using `lineSpacing()` consistently and focusing tests on logical layout, not pixels.
  - Message bounds/anchor mismatches if measurement stays single-line: mitigated by reviewing measurement helpers and adding explicit multi-line coverage in Stage 4.2.
- Tests to run after Stage 4.1:
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`
  - `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`

#### Stage 4.1 Results
- Outcome: Qt text painters now split on newlines and draw multi-line text using line spacing, with the first line anchored to the existing baseline for both vector labels and message text.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`; `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`.
- Issues/Follow-ups: none.

#### Stage 4.2 Plan (pre-implementation)
- Preflight: run `.venv/bin/python tests/configure_pytest_environment.py` (create `.venv` if needed) before code changes.
- Implementation steps:
  1) Add vector label tests in `tests/test_vector_renderer.py` to assert multi-line text is split and drawn with per-line offsets (use a fake adapter to capture draw_text calls).
  2) Add message paint command tests in `overlay_client/tests/test_paint_commands.py` to verify `\n` and `\r\n` inputs result in multiple drawText calls with line spacing offsets.
  3) Add message bounds/measurement coverage (likely `overlay_client/tests/test_render_surface_mixin.py` or a new focused test) to ensure `_measure_text` returns multi-line width/height consistent with line spacing.
  4) Keep assertions logical (call counts, ordered offsets) rather than pixel-perfect font metrics to avoid cross-platform flakiness.
- Risks + mitigations/tests:
  - Qt metrics differences causing flaky tests: mitigate by using fake adapters/recording painters and explicit line spacing values where possible.
  - Missing a newline normalization path (`\r\n` vs `\n`): mitigate by covering both line ending types.
  - Tests overreach into internal behavior: mitigate by asserting only on stable public outputs (draw calls/bounds).
- Tests to run after Stage 4.2:
  - `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`
  - `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`
  - `.venv/bin/python tests/configure_pytest_environment.py -k text_measurer`

#### Stage 4.2 Results
- Outcome: added multiline regression coverage for vector label placement, Qt adapter line splitting, message painter line splitting, and `_measure_text` multi-line sizing via a fake measurer.
- Tests: `.venv/bin/python tests/configure_pytest_environment.py -k vector_renderer`; `.venv/bin/python tests/configure_pytest_environment.py -k paint_commands`; `.venv/bin/python tests/configure_pytest_environment.py -k text_measurer`.
- Issues/Follow-ups: none.

#### Stage 4.3 Results
- Outcome: visual checks on navroute and bioscan overlays passed with multi-line labels rendering as expected (line breaks honored, spacing consistent).
- Tests: none (visual verification).
- Issues/Follow-ups: none.

#### Stage 4.4 Plan (pre-implementation)
- Preflight: none (documentation-only stage).
- Implementation steps:
  1) Document the newline handling change for vector labels and message text (split on `\n`/`\r\n`, draw with line spacing, first line anchored to the existing baseline).
  2) Note that this behavior matches legacy overlay newline handling and applies to all overlay text drawn via Qt painters.
  3) Record the visual verification from Stage 4.3 and reference the regression tests from Stage 4.2.
- Risks + mitigations/tests:
  - Documentation drift: mitigated by explicitly stating the behavior, scope, and validation steps already run.
  - Confusion about anchor/baseline behavior: mitigated by stating that the first line keeps the original baseline.
- Tests to run after Stage 4.4:
  - None (documentation-only).

#### Stage 4.4 Results
- Outcome: documented newline handling scope and legacy parity, plus recorded Stage 4.2 tests and Stage 4.3 visual verification.
- Tests: none (documentation-only).
- Issues/Follow-ups: none.

### Notes: Legacy vs Modern vect behavior
- **EDMCOverlay (legacy, inorton)**: draws line segments using the graphic’s top-level `Color` only; per-point colors apply to markers/text; requires caller to supply at least 2 points. Rendering in `EDMCOverlay/EDMCOverlay/OverlayRenderer.cs:404-448`.
- **EDMCModernOverlay (shim + client)**: currently normalizes a single-point vect by duplicating the point (`EDMCOverlay/edmcoverlay.py:97-116`), then draws segments with the pen color chosen from the next point’s `color` (fallback to current/base) in `overlay_client/vector_renderer.py:47-52`; markers/text use each point’s color. Behavior differs from legacy when per-point colors are set or only one point is provided. The refactor above will change Modern to match legacy defaults while preserving marker/text-only single points.
- **Legacy repo reference**: https://github.com/inorton/EDMCOverlay
