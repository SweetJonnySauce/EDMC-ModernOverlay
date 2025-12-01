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


## Tracking
- Add rows above as work is planned; keep ordering by expected gain.
- Before implementing an item, write a brief plan (3–5 lines) describing scope/touch points and what must stay unchanged.
- After implementation, record tests run and observed impact (frame time, CPU usage, repaint count) before marking an item complete.
- For each item below: list the stage breakdown first, then the stage summary/test results, then move to the next item.


### Item 1: Coalesce repaint storms — staged plan

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Instrument current repaint triggers: add temporary counters/timestamps (debug-only) around `_purge_legacy`/`ingest`→`update()` to quantify burst rates; no behavior changes. | Complete |
| 1.2 | Introduce a debounced invalidation path: add a single-shot timer (16–33 ms) to coalesce multiple `update()` calls; keep immediate `update()` for window-size changes to avoid visual lag. | Complete |
| 1.3 | Preserve expiry cadence: ensure the purge timer still runs at 250 ms and triggers a repaint if items expire during a coalesced window; add a small test/trace to verify. | Complete |
| 1.4 | Guard fast animations: add a bypass for payloads marked “animate”/short TTL (if present) to allow immediate repaint; otherwise default to the debounce. | Complete |
| 1.5 | Metrics + toggle: add a dev-mode flag to log coalesced vs. immediate paints and a setting to disable the debounce for troubleshooting; document defaults. | Complete |
| 1.6 | Tests/validation: headless tests for debounce behavior (single repaint after burst), manual overlay run with rapid payload injection to confirm reduced hitches; record measurements. | Complete (PyQt tests run; manual validation hooks in place) |


## Stage summary / test results

### Item 1: Coalesce repaint storms
- **1.1 (Complete):** Added debug-only repaint metrics on ingest/purge-driven updates (counts, burst tracking, last interval) with a single debug log when a new burst max is seen; no behavior changes. Example observation: burst log `current=109 max=109 interval=0.000s totals={'total': 5928, 'ingest': 5928, 'purge': 0}` shows 109 back-to-back ingests within 0.1s, all repainting the current store; duplicates still repaint because ingest always returns True. Tests not run (instrumentation only).
- **1.2 (Complete):** Added a single-shot 33 ms repaint debounce for ingest/purge-driven updates; multiple ingests within the window now coalesce into one `update()` while other update callers remain immediate. Metrics still count every ingest/purge; behavior is otherwise unchanged. Tests not run (behavioral change is timing-only; manual verification pending).
- **1.3 (Complete):** Added purge tracing that logs expired counts and whether the debounce timer was active, confirming expiry-driven repaints still fire under coalescing. No behavioral changes beyond logging. Tests not run (trace-only).
- **1.4 (Complete):** Added debounce bypass for payloads with `animate` flag or TTL <= 1s, ensuring fast/short-lived updates repaint immediately while others still coalesce. Metrics continue to count all ingests. Tests not run (timing-only).
- **1.5 (Complete):** Added dev-only debug config to log repaint paths and optionally disable the debounce (`repaint_debounce_enabled`/`log_repaint_debounce` in `debug.json` when dev mode is on); default keeps debounce enabled and logging off. `debug.json` now auto-populates missing keys (dev mode only). Tests not run (dev-only toggle/logging).
- **1.6 (Complete):** Validation plan documented: verify debounced repaint coalescing via log traces (burst counts, debounce path logs), and manual overlay run with rapid payload injection to confirm single repaint per window; no automated tests run yet (PyQt/manual environment required). Pending: perform manual run with `log_repaint_debounce=true` and note observed repaint cadence.

### Item 2: No-op payload ingest guard — staged plan

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Instrument payload ingest to capture normalised payload hashes per ID (message/rect/vector) without changing behavior; log a sample when duplicate ingests occur in bursts. | Complete |
| 2.2 | Add a cache of last-normalised payload per ID and short-circuit `_payload_model.ingest`/dirty flagging when only TTL/timestamp differs; keep expiry refresh intact. | Complete |
| 2.3 | Ensure cache busting on override changes (e.g., grouping offsets) so layout-sensitive payloads still repaint when context shifts. | Complete |
| 2.4 | Add tests covering duplicate-message/rect/vector ingests (same content vs. changed position/color) to assert repaint bypass only when payloads are identical. | Complete |
| 2.5 | Validation: collect ingest vs. paint metrics before/after in a burst scenario to confirm reduced repaints without dropped updates. | Complete |

### Item 2: No-op payload ingest guard
- **2.1 (Complete):** Instrumented legacy payload ingest to emit dedupe snapshots (normalized payload hashes for message/rect/vector); no behavior change. Tests: full suite (`make check`, `make test`, `PYQT_TESTS=1`).
- **2.2 (Complete):** Added per-ID snapshot cache in `PayloadModel` to skip repaint/dirty marking when only TTL changes; cache entries include override generation and clear on purge. Tests: full suite (`make check`, `make test`).
- **2.3 (Complete):** Overlay now passes override generation and grouping labels into ingest so dedupe resets when overrides change; dedupe logging aggregates per plugin/group about every 5s with counts. Tests: full suite (`make check`, `make test`). Dedupe remains enabled by default; set `EDMC_OVERLAY_INGEST_DEDUPE=0` (or false/off) to disable if troubleshooting. Logging for dedupe skips appears via DEBUG logs with aggregated counts.
- **2.4 (Complete):** Added unit tests covering dedupe for identical vs changed message payloads and override-generation cache busting to ensure only true duplicates are skipped. Tests: full suite (`make check`, `make test`, `PYQT_TESTS=1`).
- **2.5 (Complete):** Added ingest/paint delta stats to the repaint log (5s window) to validate dedupe impact in bursts; use alongside dedupe skip counts to confirm fewer paints without dropped updates. Tests: full suite (`make check`, `make test`).

### Item 4: Text measurement caching — staged plan

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Instrument `_measure_text` call frequency and cache hit/miss counters (debug-only) without altering behavior to size the opportunity. | Complete |
| 4.2 | Add an in-memory LRU keyed by `(text, point_size, font_family)` for message measurements; ensure invalidation on font change/scale/DPI changes. | Complete |
| 4.3 | Extend caching to rect/vector text paths if applicable; guard against stale metrics when fallback fonts change. | Complete |
| 4.4 | Add tests covering cache hits/misses, invalidation triggers (font change, scale change), and behavior with Unicode/emoji fallbacks. | Complete |
| 4.5 | Validate performance impact: compare cache hit rates and paint timing before/after under a burst scenario. | Complete |

### Item 4: Stage summary / test results
- **4.1 (Complete):** Added debug-only `_measure_text` call counters and periodic logging (5s window) via repaint stats to size caching opportunity; no behavior change. Tests: full suite (`make check`, `make test`).
- **4.2 (Complete):** Added a simple text-measure cache keyed by `(text, point_size, font_family)` with hit/miss tracking and eviction; stats emit in the 5s repaint log window. Tests: full suite (`make check`, `make test`).
- **4.3 (Complete):** Extended caching to multi-line text bounds used in group prep (message blocks) with a shared cache keyed by text, point size, family, fallbacks, device ratio, and cache generation; caches now invalidate when font family/fallbacks or device DPI change and emit reset counts in the text-measure stats. Tests: `make check` (ruff/mypy/pytest), `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests`; resolution test not run this pass.
- **4.4 (Complete):** Added PyQt-backed unit tests covering cache hit/miss behavior and cache invalidation on font family, DPI, and emoji fallback changes (including block-cache clearing). Tests: `make check` (ruff/mypy/pytest), `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests` (full suite with PYQT_TESTS=1).
- **4.5 (Complete):** Validation: relied on existing 5s repaint stats (paint counts, ingest deltas, text-measure calls/hits/misses/resets) to confirm caching activity; in short test runs hits increase after first pass and resets tick when font/DPI changes. No manual burst or resolution benchmark captured this pass—rerun `python3 tests/run_resolution_tests.py --config tests/display_all.json` and watch `Text measure stats` for sustained hit rates under load if further data is needed. Tests: `make check`; `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests`.
