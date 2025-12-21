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

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Align vect rendering semantics with legacy (default behavior change) | Not started |

## Phase Details

### Phase 1: Align vect rendering with legacy (no gating flag)
- Goal: make Modern Overlay render `vect` exactly like legacy without a feature flag (default behavior change).
- Behavior targets:
  - Use the payload’s top-level `color` for all line segments (ignore per-point `color` when setting the pen).
  - Keep per-point colors for markers/text (matches legacy); OK to drop per-point line color support.
  - Require 2+ points; remove auto-duplication of a single point (legacy didn’t auto-duplicate). Consider graceful drop/log if <2 points.
- Tests to add:
  - 2-point payload with mixed per-point colors → line uses base color, markers/text use per-point color.
  - 1-point payload → rejected/dropped/ignored (no line drawn).
  - 3+ points → confirm consecutive segments all use base color, markers/text still per-point.
- Risks: breaking consumers relying on per-point line colors or single-point duplication; regressions in grouping/transform paths.
- Mitigations: targeted tests above; document the behavioral change; keep code paths small to ease revert.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Adjust legacy shim normalization to drop single-point duplication and log/drop insufficient points | Not started |
| 1.2 | Change vector renderer to use base color for segments, preserve per-point colors for markers/text | Not started |
| 1.3 | Add/update tests covering 1-point, 2-point mixed colors, 3+ points | Not started |
| 1.4 | Document behavioral change and test steps in the refactor notes | Not started |

### Phase 2: Align label placement with legacy
- Goal: match legacy text placement relative to markers/lines (vertical offset).
- Current difference:
  - Legacy: `DrawTextEx(..., marker_x + 2, marker_y + 7)` uses `(x,y)` as text top-left; `+7` pushes text below the line/marker.
  - Modern: `draw_text(x + 8, y - 8, ...)` then adds font ascent internally, effectively treating `y` as text-top and pulling text up to the line.
- Target behavior: replicate legacy placement (text below the line/marker) unless a design call is made to keep the modern placement.
- Tests/checks:
  - Visual regression for vect labels vs. markers/lines (ensure text sits at legacy position).
  - Verify bioscan radar overlay to ensure label offsets don’t regress other overlays.
  - Check navroute and other vect consumers still render labels correctly.
- Risks: changing text offsets could affect other overlays that rely on current positioning.
- Mitigations: scoped visual checks, note deltas, add targeted assertions in renderer tests if possible.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Adjust vector text offsets to match legacy `(x+2, y+7)` or equivalent after font ascent handling | Not started |
| 2.2 | Validate bioscan radar overlay text placement | Not started |
| 2.3 | Run visual/regression checks on navroute and other vect overlays | Not started |
| 2.4 | Document placement change and any observed side effects | Not started |

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
| 3.1 | Change border color handling to skip pen when color is invalid/None | Not started |
| 3.2 | Add regression tests for invalid vs valid border colors | Not started |
| 3.3 | Visual check: navroute panel and bioscan radar panel outlines | Not started |
| 3.4 | Document behavior change and any affected overlays | Not started |

### Notes: Legacy vs Modern vect behavior
- **EDMCOverlay (legacy, inorton)**: draws line segments using the graphic’s top-level `Color` only; per-point colors apply to markers/text; requires caller to supply at least 2 points. Rendering in `EDMCOverlay/EDMCOverlay/OverlayRenderer.cs:404-448`.
- **EDMCModernOverlay (shim + client)**: currently normalizes a single-point vect by duplicating the point (`EDMCOverlay/edmcoverlay.py:97-116`), then draws segments with the pen color chosen from the next point’s `color` (fallback to current/base) in `overlay_client/vector_renderer.py:47-52`; markers/text use each point’s color. Behavior differs from legacy when per-point colors are set or only one point is provided. The refactor above will change Modern to match legacy defaults.
- **Legacy repo reference**: https://github.com/inorton/EDMCOverlay
