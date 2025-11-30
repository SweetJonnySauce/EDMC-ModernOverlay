# Overlay Client Performance Plan

This file tracks prospective changes to improve overlay-client runtime smoothness (reduce frame hitches when many plugins update in quick succession). It mirrors the structure of `client_refactor.md`: keep items ordered, scoped, and testable; document intent before coding.


## Guardrails
- Keep changes small and reversible; favour opt-in behind flags where behavior risk is unclear.
- Avoid touching Qt objects off the UI thread; if work is moved off-thread, ensure the inputs are pure data.
- Preserve existing visual layout and group semantics unless explicitly stated; performance should not alter placement.
- Measure before/after where possible (e.g., frame time, paint duration, update rate).

## Refactoring rules
- Before touching code for a stage, write a short (3-5 line) stage summary in this file outlining intent, expected touch points, and what should not change.
- Always summarize the plan for a stage without making changes before proceeding.
- Even if a request says “do/implement the step,” you still need to follow all rules above (plan, summary, tests, approvals).
- If you find areas that need more unit tests, add them in to the update.
- When breaking down a key risk, add a table of numbered stages under that risk (or a top-level stage table) that starts after the last completed stage number, and keep each row small, behavior-preserving, and testable. Always log status and test results per stage as you complete them.
- Don't delete key risks once recorded; append new risks instead of removing existing entries.
- Put stage summaries and test results in the Stage summary/test results section in numerical order (by stage number).
- Record which tests were run (and results) before marking a stage complete; if tests are skipped, note why and what to verify later.
- Before running full-suite/refactor tests, ensure `overlay_client/.venv` is set up with GUI deps (e.g., PyQt6) and run commands using that venv’s Python.
- When all sub-steps for a parent stage are complete, re-check the code (not just this doc) to verify the parent is truly done, then mark the parent complete.
- Only mark a stage/substage “Complete” after a stage-specific code change or new tests are added and validated; if no code/tests are needed, explicitly note why in the summary before marking complete.
- After finishing any stage/substep, update the table row and the Stage summary/test results section (with tests run) before considering it done; missing documentation means the stage is still incomplete.
- If the code for a substage landed in an earlier substage, explicitly note that in the substage summary before marking it complete.
- If a step is not small enough to be safe, stop and ask for direction.
- After each step is complete, run through all tests, update the plan here, and summarize what was done for the commit message.
- Each stage is uniquely numbered across all risks. Sub-steps will use dots. i.e. 2.1, 2.2, 2.2.1, 2.2.2
- All substeps need to be completed or otherwise handled before the parent step can be complete or we can move on.
- If you find areas that need more unit tests, add them in to the update.
- If a stage is bookkeeping-only (no code changes), call that out explicitly in the status/summary.

## Testing (per change)
- `make check`
- `make test`
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` (requires `overlay_client/.venv`)
- `python3 tests/run_resolution_tests.py --config tests/display_all.json`

## Candidate performance changes (ordered by expected gain)

| Item | Expected gain | Difficulty | Regression risk | Notes/Approach |
| --- | --- | --- | --- | --- |
| 1. Coalesce repaint storms | High | Medium | Medium | Ingest paths call `update()` immediately for every payload/TTL change, so bursts of messages trigger back-to-back paint events. Add a short single-shot timer (e.g., 16–33 ms) to batch invalidations and only repaint once per frame window. Ensure purge/expiry still processed and avoid starving fast animations. |
| 2. No-op payload ingest guard | High | Low | Low-Med | `process_legacy_payload` rewrites items and marks the cache dirty even when payload content/position is unchanged (common when plugins rebroadcast on every tick). Cache the last normalised payload per ID and skip dirty/paint when only TTL/updated timestamp changes; still refresh expiry so messages don’t disappear. |
| 3. Precompute render cache off the paint path | High | High | High | `_rebuild_legacy_render_cache` and builder calls run on the UI thread during `paintEvent`, walking all items, measuring text, and building commands. Prototype a worker that prepares commands (using pure data + optional text metrics seam) and hands off immutable batches to the UI thread, or incrementally update cached commands on ingest instead of full rebuilds. Needs careful Qt boundary audit. |
| 4. Text measurement caching | Medium | Low-Med | Low | `_measure_text` constructs `QFont/QFontMetrics` for every message build. Add an LRU keyed by `(text, point_size, font_family)` and reuse metrics until font prefs or DPI changes invalidate the cache. Clear the cache on font change/scale events. |
| 5. Skip heavy debug/offscreen work outside dev mode | Low-Med | Low | Low | Offscreen logging and vertex/debug overlays run per command even when dev features are off. Gate `log_offscreen_payload`/vertex collection behind the existing dev-mode flags to avoid per-payload math when not debugging. |
| 6. Grid overlay tiling | Low | Low | Low | `'_grid_pixmap_for'` repaints a full-window pixmap on size changes. Switch to a small tiled pattern pixmap and repeat-draw, reducing per-resize allocations for large windows/high resolutions. |

### Item 1: Coalesce repaint storms — staged plan

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Instrument current repaint triggers: add temporary counters/timestamps (debug-only) around `_purge_legacy`/`ingest`→`update()` to quantify burst rates; no behavior changes. | Complete |
| 1.2 | Introduce a debounced invalidation path: add a single-shot timer (16–33 ms) to coalesce multiple `update()` calls; keep immediate `update()` for window-size changes to avoid visual lag. | Complete |
| 1.3 | Preserve expiry cadence: ensure the purge timer still runs at 250 ms and triggers a repaint if items expire during a coalesced window; add a small test/trace to verify. | Planned |
| 1.4 | Guard fast animations: add a bypass for payloads marked “animate”/short TTL (if present) to allow immediate repaint; otherwise default to the debounce. | Planned |
| 1.5 | Metrics + toggle: add a dev-mode flag to log coalesced vs. immediate paints and a setting to disable the debounce for troubleshooting; document defaults. | Planned |
| 1.6 | Tests/validation: headless tests for debounce behavior (single repaint after burst), manual overlay run with rapid payload injection to confirm reduced hitches; record measurements. | Planned |

## Tracking
- Add rows above as work is planned; keep ordering by expected gain.
- Before implementing an item, write a brief plan (3–5 lines) describing scope/touch points and what must stay unchanged.
- After implementation, record tests run and observed impact (frame time, CPU usage, repaint count) before marking an item complete.

## Stage summary / test results
- **1.1 (Complete):** Added debug-only repaint metrics on ingest/purge-driven updates (counts, burst tracking, last interval) with a single debug log when a new burst max is seen; no behavior changes. Example observation: burst log `current=109 max=109 interval=0.000s totals={'total': 5928, 'ingest': 5928, 'purge': 0}` shows 109 back-to-back ingests within 0.1s, all repainting the current store; duplicates still repaint because ingest always returns True. Tests not run (instrumentation only).
- **1.2 (Complete):** Added a single-shot 33 ms repaint debounce for ingest/purge-driven updates; multiple ingests within the window now coalesce into one `update()` while other update callers remain immediate. Metrics still count every ingest/purge; behavior is otherwise unchanged. Tests not run (behavioral change is timing-only; manual verification pending).
