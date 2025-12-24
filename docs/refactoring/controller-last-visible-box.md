## Goal: Controller Target Box Persistence (Last vs Max)

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
| 1 | Add per-group controller box mode (`last` vs `max`) with persistent cache, plus user-visible cache reset. | Completed |
| 2 | Switch last/max tracking to use base bounds (not transformed). | Completed |

## Phase Details

### Phase 1: Controller Target Box Persistence
- Goal: expose a per-group `controllerPreviewBoxMode` with `last` (default) and `max` options, and persist both across restarts.
- `max` uses the maximum base bounds ever recorded for the group.
- `last` uses the most recent base bounds for a visible payload group.
- Both `last` and `max` persist in `overlay_group_cache.json`.
- Provide a "Reset cached values" button in preferences (no debug/dev gating) to clear `overlay_group_cache.json`.

Definition: "Last Visible"
- "Last visible" means the most recent base bounds for a group where the payload is considered visible.
- Visibility rules:
  - Bounds width and height are strictly > 0.
  - Messages with `ttl=0` and empty `text` are not visible.
  - Zero-size rects are not visible.
  - Vector payloads must have at least one point.

Propagation Path (Config -> Runtime)
1) Plugin API entry point
   - `overlay_plugin/overlay_api.py:define_plugin_group` accepts `controller_preview_box_mode`.
   - Store as `controllerPreviewBoxMode` under the idPrefix group in `overlay_groupings.json`.

2) Overrides parsing
   - `overlay_client/plugin_overrides.py` parses the new field from group entries.
   - Normalize to `last` or `max`, default `last`.

3) Runtime access
   - Either:
     - Add a new property to `GroupTransform` (e.g., `controller_preview_box_mode`),
       and set it in `overlay_client/grouping_helper.py`, or
     - Expose a direct lookup on the override manager (e.g.,
       `group_controller_box_mode(plugin, suffix)`) and use it from
       `render_surface.py`.
   - Render path needs this setting at draw time.

4) Render usage (in-game orange box)
   - `overlay_client/render_surface.py:_paint_controller_target_box` uses the
     mode to decide which bounds to display.
   - `last` uses the persisted last-visible transformed bounds.
   - `max` uses the persisted max transformed bounds, with fallback to last.

Max/Last Tracking and Cache Persistence
- Storage location: `overlay_group_cache.json` per group entry.
- Add optional fields for last-visible and max base bounds (stored under the existing cache keys):
  - `last_visible_transformed`: `{base_min_x, base_min_y, base_max_x, base_max_y, base_width, base_height}`
  - `max_transformed`: `{base_min_x, base_min_y, base_max_x, base_max_y, base_width, base_height}`
- Update policy:
  - When a group is visible, update last-visible base bounds.
  - Update max base bounds if the new visible bounds exceed previous max.
  - Only use base bounds (no transformed bounds).

Reset Cached Values
- Add a "Reset cached values" button to the preferences pane UI.
- Reset should delete or truncate `overlay_group_cache.json` to default state.
- Ensure any in-memory cache mirrors the reset (force reload or clear).
- Reset also clears any in-memory last/max maps immediately.

Risks
- Cache schema drift or stale values after mode toggles.
- Oversized max bounds lingering after layout changes.

Mitigations
- Reset button to clear cached values.
- Define a deterministic update policy tied to visibility and transformed bounds.
- Add tests for cache read/write semantics and mode-specific selection.

Decisions
- Max only resets via the reset button (not on edit nonce changes).
- Max comparison uses width and height only (no area-based metric).

Implementation Plan
- Define controller box mode in API/config: add `controller_preview_box_mode` to `define_plugin_group`, validate/normalize it, store `controllerPreviewBoxMode` in groupings, and expose it via overrides/runtime.
- Persist last/max transformed bounds in cache: extend cache schema (`last_visible_transformed`/`max_transformed`), update render/cache write path to maintain them for visible groups, and update cache read helpers.
- Select bounds by mode in the in-game target box: use last vs max from cache (with fallbacks) and wire mode lookup in render surface.
- Add preferences "Reset cached values" button and wiring to clear the cache file and in-memory last/max maps immediately.
- Tests and docs: add/adjust tests for mode parsing, cache persistence, target box selection, and reset behavior; update release notes if needed.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Add new grouping field, parsing, and runtime access for `controllerPreviewBoxMode`. | Completed |
| 1.2 | Persist last/max transformed bounds in cache; update render logic to select by mode. | Completed |
| 1.3 | Add preferences reset button to clear cache; add tests. | Completed |

#### Stage 1.1 Plan
- Touch points: `overlay_plugin/overlay_api.py` (new argument + validation + storage),
  `overlay_client/plugin_overrides.py` (parse + default), runtime access method
  on the override manager.
- Add a normalizer for `controller_preview_box_mode` (`last`/`max`) with a safe
  default of `last`.
- Tests: extend overlay API tests to cover validation + storage; add/adjust
  override parsing tests to confirm the mode is read.
- Risks: name mismatch between API arg and JSON field; mis-typed values ignored.
- Mitigations: explicit normalization, tests for both accepted values and
  invalid inputs.

#### Stage 1.1 Results
- Changes: added `controller_preview_box_mode` to `define_plugin_group`, stored
  `controllerPreviewBoxMode` in groupings, parsed in overrides, and exposed via
  override manager lookup.
- Tests: `source .venv/bin/activate && python -m pytest tests/test_overlay_api.py overlay_client/tests/test_override_grouping.py -k controller_preview_box_mode`
- Issues: none observed.
- Follow-ups: none.

#### Stage 1.2 Plan
- Touch points: `group_cache.py` (persist `last_visible_transformed` +
  `max_transformed`), `overlay_client/render_surface.py` (cache read/write
  selection + controller target box mode), tests for cache persistence and
  target-box selection.
- Update cache writes to set `last_visible_transformed` whenever a visible group
  has transformed bounds; update `max_transformed` when width/height exceed the
  stored max.
- Update target-box selection to resolve `controller_preview_box_mode` and pick
  `last_visible_transformed` vs `max_transformed` (with `max` falling back to
  `last`), then fall back to base cache behavior when needed.
- Tests: add cache update coverage for `last_visible_transformed`/`max_transformed`,
  and target-box selection coverage for `last` vs `max` modes.
- Risks: stale cache data after override edits or offset changes; mitigate by
  reusing existing offset/nonce gating and falling back to base cache logic,
  plus targeted tests for the new selection path.

#### Stage 1.2 Results
- Changes: cached `last_visible_transformed` and `max_transformed` in
  `overlay_group_cache.json`, and updated controller target box rendering to
  choose bounds by `controller_preview_box_mode` with max->last fallback.
- Tests: `source .venv/bin/activate && python -m pytest tests/test_group_cache_debounce.py overlay_client/tests/test_controller_target_box.py`
- Issues: none observed.
- Follow-ups: none.

#### Stage 1.3 Plan
- Touch points: `group_cache.py` (add cache reset helper), `overlay_client`
  (handle reset event + clear in-memory maps), `overlay_plugin/preferences.py`
  (preferences button + callback), `load.py` (wire callback + publish reset
  event), and `overlay_client/launcher.py` (new event handling).
- Implement a `GroupPlacementCache.reset()` that clears state and writes an
  empty cache file, then add a `reset_group_cache` handler on the overlay client
  to clear in-memory maps and force a repaint.
- Add a "Reset cached values" button in the preferences panel that clears the
  cache file and notifies the overlay client via a new
  `OverlayGroupCacheReset` event.
- Tests: add unit coverage for the cache reset path and in-memory map clearing.
- Risks: reset button may leave overlay client maps stale if event delivery
  fails; mitigate by clearing the file first and ensuring the event handler
  clears in-memory state with a repaint.

#### Stage 1.3 Results
- Changes: added a preferences button to reset the group cache, wired through
  plugin runtime to emit an `OverlayGroupCacheReset` event, and added client-side
  cache reset handling that clears in-memory maps immediately.
- Tests: `source .venv/bin/activate && python -m pytest tests/test_group_cache_debounce.py overlay_client/tests/test_render_surface_mixin.py`
- Issues: none observed.
- Follow-ups: none.

### Phase 2: Base Bounds Tracking for Last/Max
- Goal: ensure last/max cache entries are derived from base bounds so groups without transforms (e.g., default anchors/justification) still persist usable target boxes.
- Backward compatibility: tolerate existing `last_visible_transformed`/`max_transformed` entries that still use transformed keys, but prefer base-keyed entries going forward.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Update cache writes/reads to use base bounds for last/max; refresh tests/docs. | Completed |

#### Stage 2.1 Plan
- Touch points: `group_cache.py` (last/max updates from base bounds),
  `overlay_client/render_surface.py` (cache fallback parsing for last/max),
  `tests/test_group_cache_debounce.py`, `overlay_client/tests/test_controller_target_box.py`,
  and this refactoring doc.
- Update cache writes to persist base-keyed bounds in `last_visible_transformed` and `max_transformed`.
- Update cache read helpers to treat last/max payloads as base bounds (apply offsets/anchors at draw time).
- Tests: update cache persistence/selection tests; run targeted pytest for cache + controller target box behavior.
- Risks: target box shifts for anchored/justified groups; mitigate by retaining transformed fallbacks and testing representative cases.

#### Stage 2.1 Results
- Changes: last/max cache entries now persist base bounds from group snapshots, and cache fallback treats last/max payloads as base bounds (with transformed fallbacks); controller target box no longer requires transformed payloads for last/max.
- Tests: `source .venv/bin/activate && python -m pytest tests/test_group_cache_debounce.py overlay_client/tests/test_controller_target_box.py`
- Issues: none observed.
- Follow-ups: none.
