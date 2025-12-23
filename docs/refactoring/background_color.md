## Goal: Paint the background of the payload group based on plugin author or user defined preferences

## Background Color Feature Requirements
- Plugin authors can set a default background color on their plugin group via `define_plugin_group`.
- Background color and border width apply only to plugin groups (`idPrefixGroup`); per-payload background values are not supported.
- `define_plugin_group` may also include an optional background border width (pixels, 0–10 inclusive); the background extends beyond the group boundary by that width equally on all sides, using the same color as the background.
- Persist plugin defaults per group in `overlay_groupings.json` (inside each group definition) so the renderer can resolve that group’s color without user input.
- CMDRs can override the background color in the overlay controller via a new widget that shows a text box for color code entry plus a button that opens a color picker.
- Resolved color precedence: user override (from `overlay_groupings.user.json`) → plugin group default (from `overlay_groupings.json` via `define_plugin_group`) → plugin-provided payload color (if any) → transparent. The widget shows the resolved value.
- Accept color codes in hex `#RRGGBB` or `#AARRGGBB` (alpha optional, case-insensitive); invalid codes are rejected and the widget should surface validation.
- Store user overrides in `overlay_groupings.user.json`; group-level user values take precedence over plugin defaults when rendering.
- If no user override is set, fall back to the plugin’s default background color from `overlay_groupings.json`.
- Clearing the color value (user override empty) means transparent; when no user override, no plugin default, and no plugin-provided payload color are present, treat background as transparent and show no value in the widget/picker.
- Rendering: background and border are drawn behind all payloads; in the controller preview, the border expansion is reflected visually.
- The background frame (border width = 0) must be exactly the same size and position as the plugin group boundary after all transforms (anchor translations, justifications, nudges) are applied.


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
| 1 | Contracts and schema for background color/border | Completed |
| 2 | Plugin API + loader/diff persistence plumbing | Completed |
| 3 | Controller UI, validation, and user override writes | Completed |
| 4 | Client rendering + preview visuals | Completed |
| 5 | plugin_group_manager defaults | Completed |

## Phase Details

### Phase 1: Contracts and schema for background color/border
- Goal: lock in field names, formats, validation rules, and JSON schema for group background color and border width; keep existing grouping behavior unchanged otherwise.
- Edge cases: invalid hex, alpha support, border range (0–10), transparent when unset, ensure diff/merge treats unknown fields safely.
- Risks: schema drift causing plugin/controller/client mismatches; rejects valid user data.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Document field names, precedence, validation (hex + alpha, border 0–10) in schema and docs | Completed |
| 1.2 | Update `schemas/overlay_groupings.schema.json` to allow background color + border width per group | Completed |
| 1.3 | Add/adjust tests for schema/loader contract coverage (e.g., loader tests consuming the schema) | Completed |

**Stage 1.1 notes**
- Plan: clarify the background fields, precedence (user → plugin group default → plugin payload → transparent), validation (`#RRGGBB`/`#AARRGGBB`, border width 0–10), and rendering rule for the frame aligning to the transformed group bounds.
- Risks: misaligned terminology or missing precedence step; mitigation: restated precedence and alignment requirement in the requirements list.
- Result: requirements updated; no code changes; tests not applicable.

**Stage 1.2 notes**
- Plan: extend the JSON schema to permit optional `backgroundColor` and `backgroundBorderWidth` on group definitions, keeping validation strict (hex with optional alpha, border 0–10).
- Risks: loosening schema too far or rejecting valid values; mitigation: pattern-match hex with alpha, clamp border width via min/max.
- Result: schema updated with the two fields; tests not yet run (schema-only change).

**Stage 1.3 notes**
- Plan: cover schema/loader normalization with unit tests so hex validation and precedence stay anchored.
- Risks: regression in merge precedence or schema drift; mitigation: new loader/diff/API tests asserting color/border normalization and clear-to-transparent semantics.
- Result: Tests added (`tests/test_overlay_api.py`, `tests/test_groupings_loader.py`, `tests/test_groupings_diff.py`, `tests/test_plugin_override_loader.py`) and passing.

### Phase 2: Plugin API + loader/diff persistence plumbing
- Goal: extend `define_plugin_group` and storage to accept/write defaults; ensure merge/diff honor precedence (user → plugin → payload → transparent).
- Edge cases: write guards stay on shipped file; diff doesn’t emit redundant defaults; loader tolerates missing/invalid user values gracefully.
- Risks: breaking third-party plugins, bad writes to user file, merge inconsistencies.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Extend `overlay_api.define_plugin_group` validation/serialization for background color + border width | Completed |
| 2.2 | Update `groupings_loader` and `groupings_diff` to merge/diff new fields correctly | Completed |
| 2.3 | Refresh docs (`overlay-groupings.md`, `developer.md`) and add unit tests for API/loader/diff behaviors | Completed |

**Stage 2.x notes**
- Implemented `background_color`/`background_border_width` support in `overlay_plugin.overlay_api`, loader, and diff helpers with validation + fallback to shipped defaults when user entries are invalid, and `None` respected as a transparent override.
- Updated schema docs (`docs/overlay-groupings.md`) and added unit tests across API/loader/diff/override loader.
- Tests: `tests/test_overlay_api.py`, `tests/test_groupings_loader.py`, `tests/test_groupings_diff.py`, `tests/test_plugin_override_loader.py`.

### Phase 3: Controller UI, validation, and user override writes
- Goal: add the background color widget (text + picker) and border width control; persist user overrides to `overlay_groupings.user.json` with validation feedback.
- Edge cases: clearing value = transparent; invalid input surfaces errors; debounce/write paths remain stable; preview reflects overrides.
- Risks: UI regressions in controller, broken cache invalidation, noisy writes.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Build background color widget with validation (hex + optional alpha) and border width input (0–10) | Completed |
| 3.2 | Wire reads/writes through controller state/edit controller to user file; ensure cache invalidation | Completed |
| 3.3 | Update preview to display background + border expansion; add controller tests for override precedence | Completed |

**Stage 3.x notes**
- Added Tk background widget (hex entry + picker + border spinbox), wired through edit/group state persistence, and updated preview rendering to include background/border with live anchor/offset transforms.
- Clearing the field records a transparent override; invalid input is highlighted.
- Tests: `overlay_controller/tests/test_group_state_service.py`, `overlay_controller/tests/test_preview_renderer.py`.


### Phase 4: Client rendering + preview visuals
- Goal: render group background + border behind all payloads using resolved precedence; keep existing rendering stable.
- Edge cases: alpha handling, transparent fallback, payload-provided colors interaction, performance of extra draw calls.
- Risks: rendering regressions, incorrect hit/selection visuals, off-by-one border sizing.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Plumb resolved background color/border through override manager/grouping helper into render pipeline | Completed |
| 4.2 | Draw background + border behind payloads; ensure preview/render match (border expansion visible) | Completed |
| 4.3 | Add/extend client tests (override loader, render pipeline) and manual sanity checklist | Completed |

**Stage 4.x notes**
- Propagated background fields through plugin override manager → grouping helper → group transform; render surface now paints backgrounds behind payloads using transformed bounds + nudges so border=0 matches final group geometry.
- Tests: `overlay_client/tests/test_render_surface_mixin.py` plus shared loader/diff/override tests above.



## Phase 5: plugin_group_manager defaults
- Goal: allow `utils/plugin_group_manager` to set per-group `backgroundColor`/`backgroundBorderWidth` defaults when writing `overlay_groupings.json`.
- Touch points: `utils/plugin_group_manager.py` (CLI/data handling), help/usage docs/snippets.
- Behavior: accept optional background color (hex `#RRGGBB`/`#AARRGGBB`) and border width (0–10); validate using the same rules as `define_plugin_group`; write fields only when provided; omit to keep transparent/default 0. Preserve existing prefix/anchor/offset/justification handling.
- Tests: add/adjust utility tests to cover valid writes, invalid inputs (bad hex, out-of-range border), and unchanged behavior when fields are omitted.
- Risks: validation drift vs. `define_plugin_group`, unintended overwrites/noisy diffs, CLI UX regressions.
- Mitigations: reuse normalization logic, write only when provided, targeted tests for the utility path.
- Status: Completed — normalization/persistence accepts the new fields and the add/edit grouping dialogs now include background color (hex) and border width (0–10) with validation; clearing color sets transparent.
