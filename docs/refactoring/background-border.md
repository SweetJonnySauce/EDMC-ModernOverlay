## Goal: Allow for the option to have a differently colored border around a background

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
| 1 | Define requirements + compatibility contract | Completed |
| 2 | Schema + persistence contracts | Completed |
| 3 | Controller UI + preview wiring | Completed |
| 4 | Runtime rendering behavior | Completed |
| 5 | Docs + tests | Completed |

## Phase Details

### Phase 1: Legacy compatibility contract + requirements

#### Understanding (legacy vs. modern)
- Legacy EDMCOverlay (C#): rects support both fill and border colors; `Graphic.Fill` is the fill and `Graphic.Color` is the border stroke. Both accept legacy named colors or hex `#RRGGBB`/`#AARRGGBB`.
- Modern overlay: group backgrounds currently support a single color (`backgroundColor`) and a border width (`backgroundBorderWidth`), with the border using the same color as the fill and expanding the fill rectangle equally on all sides.
- Compatibility goal: add an optional border color that maps to legacy `Color` while preserving current defaults when unset.
- Confirmed: border stroke width is fixed at 1px to match legacy EDMCOverlay.
- Confirmed: named colors are accepted for both fill and border; store named tokens as-is in groupings files.

#### Requirements
1) **Schema**
   - Add `backgroundBorderColor` to `schemas/overlay_groupings.schema.json` alongside existing background fields.
   - Validation: accept CSS/Qt named colors (must include legacy names) plus hex `#RRGGBB` or `#AARRGGBB`, or `null` to clear (transparent). Keep validation rules consistent with `backgroundColor`.

2) **Overlay API**
   - Extend `overlay_plugin/overlay_api.py` `define_plugin_group(...)` to accept `background_border_color`.
   - Validate using the same normalization as `background_color` (including named colors); persist to `overlay_groupings.json` under `idPrefixGroups.<name>.backgroundBorderColor`.
   - Require `idPrefixGroup` when specifying `background_border_color` (same as existing background fields).

3) **Groupings persistence/merge**
   - Update groupings loader/diff to carry the new field end-to-end (shipped -> user overrides).
   - Precedence: user override value wins; invalid user values fall back to shipped; explicit `null` clears to transparent.

4) **Controller UI**
   - Add a border color input to `overlay_controller/widgets/background.py` (hex entry + picker, same validation as fill; allow named colors by text entry).
   - Update controller tips to mention named colors are accepted for both background and border.
   - Wire `overlay_controller/overlay_controller.py` to persist border color via the same flow as fill/border width.
   - Update `overlay_controller/preview/renderer.py` to render the border stroke using border color and border width; render rule must match runtime behavior.

5) **Runtime rendering**
   - Propagate `backgroundBorderColor` through overrides -> grouping helper -> group transform.
   - Render background fill as before with `backgroundColor`.
   - Render border when `backgroundBorderColor` is set, even if `backgroundColor` is unset; border stroke thickness is fixed (1px), and `backgroundBorderWidth` does not change stroke width.
   - `backgroundBorderWidth` only expands the fill bounds; the border stroke is drawn outside the fill with its inner edge aligned to the fill bounds, so the outer bounds expand by that width.
   - If border color is unset/invalid, no border is drawn (fill remains).

6) **Documentation**
   - Update `docs/define_plugin_group-API.md` and `docs/developer.md` to include `backgroundBorderColor`, including validation rules and transparent override semantics.

#### Implementation Plan
1) Update schema + normalization helpers to accept named colors and add `backgroundBorderColor`; store named tokens unchanged.
2) Extend overlay API + groupings persistence so `define_plugin_group` accepts `background_border_color` and groupings loader/diff/state carry the new field with override precedence.
3) Controller UI + preview: add border color input/picker + tip text; thread new value through callbacks, snapshots, and preview rendering.
4) Runtime rendering: parse `backgroundBorderColor` in overrides, add it to `GroupTransform`, and draw a 1px border stroke outside the expanded fill bounds even without fill.
5) Docs + tests: update API/developer docs and extend tests for validation, merging, and rendering expectations.

#### Tests
- Extend groupings loader/diff tests to cover `backgroundBorderColor` merge/override behavior.
- Add/extend controller widget tests to validate border color input + preview rendering.
- Add/extend render surface tests to ensure border stroke uses border color and width; fill remains unchanged.

#### Open questions
- None. Compatibility rules for named colors and border expansion/stroke are confirmed.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Capture legacy behavior + modern baseline | Completed |
| 1.2 | Define schema/API/UI/runtime requirements | Completed |
| 1.3 | Confirm open questions + finalize contract | Completed |

### Phase 2: Schema + persistence contracts
- Goal: lock schema + normalization rules and ensure persistence/merge flows carry `backgroundBorderColor`.
- Invariants: named color tokens stored unchanged; `null` clears to transparent; user overrides win; invalid user values fall back to shipped.
- Risks: schema validation gaps or loader fallback regressions.
- Mitigations: extend schema tests and loader/merge tests for named colors + null overrides.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Update schema + normalization helpers for named colors and `backgroundBorderColor` | Completed |
| 2.2 | Extend overlay API + groupings loader/diff/state to persist/merge the new field | Completed |

### Phase 3: Controller UI + preview wiring
- Goal: expose border color in the controller and match preview behavior to runtime.
- Invariants: validation mirrors runtime; tips mention named colors; previews reflect 1px stroke outside fill.
- Risks: UI validation accepting values runtime rejects; preview mismatch.
- Mitigations: reuse shared normalization helpers; add targeted widget/preview tests.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Add border color input + picker + tips for named colors | Completed |
| 3.2 | Wire controller persistence + preview rendering for border color | Completed |

### Phase 4: Runtime rendering behavior
- Goal: render 1px border strokes using `backgroundBorderColor` with fill expansion rules.
- Invariants: border draws even without fill; border stroke width fixed at 1px; stroke sits outside expanded fill bounds.
- Risks: bounds expansion changes layout or overdraw; alpha handling regressions.
- Mitigations: add render surface tests for bounds + color/alpha handling.

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Parse `backgroundBorderColor` in overrides + add to group transform | Completed |
| 4.2 | Render 1px border stroke outside expanded fill bounds | Completed |

### Phase 5: Docs + tests
- Goal: document new API field and verify behavior with tests.
- Invariants: docs reflect named color support and border/fill rules.
- Risks: docs drifting from implementation; test gaps.
- Mitigations: update docs and add tests alongside code changes.

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Update API/developer docs for `backgroundBorderColor` + named colors | Completed |
| 5.2 | Add/extend tests for validation, merging, and rendering | Completed |
