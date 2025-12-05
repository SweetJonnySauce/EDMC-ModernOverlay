Target Jumping Fix
==================
## Dev Best Practices

- Keep changes small and behavior-scoped; prefer feature flags/dev-mode toggles for risky tweaks.
- Plan before coding: note touch points, expected unchanged behavior, and tests you’ll run.
- Avoid Qt/UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.

## Guiding traits for readable, maintainable code:
- Clarity first: simple, direct logic; avoid clever tricks; prefer small functions with clear names.
- Consistent style: stable formatting, naming conventions, and file structure; follow project style guides/linters.
- Intent made explicit: meaningful names; brief comments only where intent isn’t obvious; docstrings for public APIs.
- Single responsibility: each module/class/function does one thing; separate concerns; minimize side effects.
- Predictable control flow: limited branching depth; early returns for guard clauses; avoid deeply nested code.
- Good boundaries: clear interfaces; avoid leaking implementation details; use types or assertions to define expectations.
- DRY but pragmatic: share common logic without over-abstracting; duplicate only when it improves clarity.
- Small surfaces: limit global state; keep public APIs minimal; prefer immutability where practical.
- Testability: code structured so it's easy to unit/integration test; deterministic behavior; clear seams for injecting dependencies.
- Error handling: explicit failure paths; helpful messages; avoid silent catches; clean resource management.
- Observability: surface guarded fallbacks/edge conditions with trace/log hooks so silent behavior changes don’t hide regressions.
- Documentation: concise README/usage notes; explain non-obvious decisions; update docs alongside code.
- Tooling: automated formatting/linting/tests in CI; commit hooks for quick checks; steady dependency management.
- Performance awareness: efficient enough without premature micro-optimizations; measure before tuning.



Context
-------
- HUD payloads and controller preview jump to stale locations after offset edits because cached `transformed` blocks (with `has_transformed = true`) in `overlay_group_cache.json` are reused (e.g., `offset_dx/dy = 100/100` for `BGS-Tally Colonisation`).
- Controller shows the new target (current X/Y), but the client renders using the cached transformed geometry, so HUD and preview diverge and the controller thinks the payload has not caught up.
- Core rule: the controller sets the target; the client must work to match the controller’s target (not the other way around).

Chosen Approach
---------------
Use a combined strategy to keep HUD and preview aligned:
- Invalidate or rewrite the cached `transformed` entry on every edit (offset/anchor/justification) and bump `last_updated`.
- Gate adoption of any `transformed` entry by timestamp/generation so stale cache cannot override a newer edit.
- Optionally synthesize a fresh transformed block from base + new offsets + anchor to bridge the gap until the client rewrites.
- Avoid double-applying offsets: when a transformed block exists, use it as-is; when absent, synthesize once from base + overrides (including fill translation) and persist it.
- Push overrides immediately: after controller writes merged overrides, send them to the client with the edit nonce so the client applies without waiting on file reload timing.

Controller Actions
------------------
- On offset/anchor/justification change:
  - Clear or overwrite the `transformed` block for the active group.
  - Set `has_transformed = false` (or update to the synthesized transform) and bump `last_updated`.
  - Debounce/atomic write of `overlay_group_cache.json` and emit reload signal to the client.
  - Use synthesized transform in preview until a fresh client write arrives.

Client Actions
--------------
- Treat controller target as source of truth; HUD must converge to it.
- When reading cache, only apply `transformed` if `last_updated >= last_edit_generation` (or matching generation nonce); otherwise recompute from base + offsets.
- After rendering with new offsets, write back a fresh `transformed` block with updated `last_updated` so controller/HUD remain in sync.
- Fallback: if cache is missing/invalid, recompute from base + offsets and continue.
- Fallback specifics: do not reapply offsets on top of a `transformed` block; if no transform exists, synthesize transformed from base+overrides (including fill overflow translation) and write it back.
- Override handling: accept pushed merged overrides (with `_edit_nonce`) from controller and apply immediately when nonce matches; preserve metadata through `GroupingsLoader` merge so nonce gating works.

Safeguards / Risk Mitigation
----------------------------
- Single writer / locking: designate one writer for the cache or use a simple lock/generation to avoid clobbering concurrent writes.
- Atomic writes: write to temp then rename; validate JSON before swap.
- Timestamp discipline: use monotonic timestamps or an edit generation counter to avoid skew issues.
- Overrides: write user overrides atomically, carry `_edit_nonce` metadata through merge, and ignore mismatched nonce payloads.
- Backward compatibility: feature-flag gating/invalidation so older clients/controllers continue to work with default behavior.
- Logging and retries: log cache write/read failures and fall back to base+offset computation when cache is untrusted.
- Throttle edits: debounce invalidation+reload to avoid flip-flops during rapid changes.

Testing Notes
-------------
- Controller tests: verify cache invalidation/rewrite on edits, timestamp bumps, and synthesized preview transforms.
- Client/coordinator tests: ensure stale `transformed` entries are ignored when older than last edit/generation; fresh entries are applied; fallback does not double-apply offsets and applies fill translation only once.
- End-to-end: edit offsets and confirm HUD and controller preview move together without snapping back; absolute widget color updates when the client write lands; fallback rendering matches controller target when HUD payload is absent.

Phased Plan
-----------
| Phase # | Description | Status |
| --- | --- | --- |
| 0 (POC) | Prove “controller target drives HUD”: on edit, clear `transformed`/set `has_transformed=false`/bump `last_updated`; controller ignores cached `transformed` entirely (uses base+overrides); extend live-edit window to keep snapshot in-memory; atomic writes for user overrides with post-edit reload pause; client fallback recomputes target from base+overrides and ignores cached `transformed`; overrides are pushed directly to client with `_edit_nonce` and applied immediately when matching. Validate via manual tweaks. Disposable shim acceptable. | Complete |
| 1 | Harden controller invalidation + preview synthesis + nonce: keep cache invalidation, add generation/nonce to cache entries and snapshot gating; include nonce in override pushes; ensure atomic writes; add controller unit tests. | Complete (unit tests to add) |
| 2 | Client stale-gating + single-application: ignore stale/mismatched cache transforms; recompute from base+overrides; fallback/draw apply offsets once and fill translation once; accept pushed overrides with nonce. Add client/unit tests for gating + no double-offset. | Complete |
| 3 | Write-back discipline: after render with new offsets/anchor, write fresh `transformed` with updated `last_updated`/nonce; verify debounce/flush timing and convergence tests. | Complete |
| 4 | Integration/regression: end-to-end edits without jumps; fallback matches controller target when HUD absent; clean up POC shims/flags, keep minimal logging. | Pending |
| 5 | UI cleanup: simplify preview to draw target=actual only; remove/redesign absolute text red warning logic now that target and actual stay aligned in preview. | Pending |

Phase 1 Plan (Controller hardening + nonce)
-------------------------------------------
- Goals: make controller-side invalidation/synthesis robust with generation/nonce; keep preview in sync without POC shims.
- Steps:
  1) Cache/gen nonce: add edit generation/nonce to cache entries (`overlay_group_cache.json`) when invalidating/rewriting; include nonce in controller state and active-group signal.
  2) Snapshot gating: use nonce+timestamp to accept `transformed` only when matching current edit; otherwise synthesize from base+offsets.
  3) Override pushes: include nonce in pushed overrides; ensure atomic writes; remove duplicated POC guards once nonce is enforced.
  4) Tests: controller unit tests for cache invalidation with nonce, snapshot gating, and preview synthesis; manual check that preview/HUD stay aligned during edits.
  5) Cleanup: remove temporary POC-only skips/guards, keep minimal logging.

Phase 2 Plan (Client stale-gating + single-application)
-------------------------------------------------------
- Goals: guarantee the client always converges to the controller target by trusting controller overrides over cache, ignoring stale transforms, and ensuring offsets/fill translation are applied once per render.
- Steps:
  1) Snapshot inputs: plumb `_edit_nonce` and `last_updated` through the client override loader and active group coordinator so cache lookups know the latest valid generation for each group.
  2) Cache gating: update `GroupPlacementCache` (and any helpers in `render_surface.py`/`group_cache.py`) to accept cached `transformed` data only when the nonce/timestamp matches the active override snapshot; otherwise treat it as invalid and synthesize transformed bounds from base + overrides.
  3) Single-application math: audit `_fallback_bounds_from_cache`, `_apply_fill_translation`, and payload builders to ensure offsets and fill spillover translation are applied exactly once regardless of cache path; add guardrails so synthesized transforms aren’t offset again when cached later.
  4) Override adoption: wire the direct override payload (sent from the controller with nonce) into the client so edits apply immediately even if the periodic reload is paused; ensure nonce mismatches are ignored with clear logging.
  5) Tests: extend/author unit tests covering (a) stale cache ignored when nonce mismatch or timestamp older, (b) valid cache adopted without double offset, (c) fill translation applied once, (d) override payload application updates active nonce and triggers repaint. Include regression tests in `overlay_client/tests/test_override_reload.py` or new files as needed.
  6) Manual verification: using the controller, perform rapid offset adjustments and confirm HUD payloads track the target without snap-backs, even when cache writes are delayed; inspect `overlay_group_cache.json` to ensure newly written transforms match controller positions.
  7) Cleanup/document: remove POC-specific comments/flags in the client path, ensure logs clearly describe when cache is ignored due to nonce/timestamp, and document the new gating behavior in this file for future reference.

### Phase 2 summary / test results
- `GroupPlacementCache` entries now carry `edit_nonce`/timestamp metadata, and `GroupCoordinator`/render pipeline propagate controller nonce + override timestamps so cache writes reflect the active generation.
- Render fallback synthesizes bounds from base + overrides unless cached transforms match offsets, nonce, and edit timestamp; fill translation now runs only for synthesized bounds to prevent double-shifts.
- Plugin override manager/control surface track active nonce timestamps, override payloads apply immediately, and new tests cover cache gating, metadata persistence, and nonce/timestamp guard rails.
- Tests: `make check` (ruff + mypy + full pytest suite, including new controller target box + group cache cases).

### Phase 3 summary / test results
- Controller-active mode now drives cache flush cadence: the payload log delay clamps to the active profile, pending log entries skip delays, and group cache debounce tightens while the controller heartbeat is fresh. Background/inactive mode retains the longer debounce.
- `GroupPlacementCache` gained forced flush + metadata reporting; render surface tracks per-group generations, clears stale log state when `_edit_nonce` changes, records last-write diagnostics, and triggers an immediate flush (respecting a minimum interval) whenever controller-active renders produce cache updates.
- Tests: `make check` (ruff, mypy, full pytest suite) plus new cases for cache debounce/flush, coordinator normalization metadata, controller mode payload delay adjustments, and forced flush behavior.

Phase 3 Plan (Write-back discipline)
------------------------------------
- Goals: ensure every edit that reaches the client results in a timely cache write with the same transform geometry the HUD is rendering, so the controller preview/HUD fallback never stalls on stale data.
- Steps:
  1) **Snapshot plumbing:** expose the controller’s active nonce/timestamp (from the override manager/control surface) to the payload logging/caching path so `_apply_group_logging_payloads` and `_update_group_cache_from_payloads` know which generation they are persisting. Capture per-group last-write metadata in-memory for diagnostics.
  2) **Flush cadence:** audit the debounce/timer pipeline (logging throttles → coordinator → `GroupPlacementCache`) and ensure rapid edits in controller-active mode shorten the flush window (e.g., bump cache debounce to sub-second while controller is active). Verify background mode still uses longer intervals to avoid disk churn.
  3) **Write-after-edit guarantee:** when the controller is active and offsets change, force a cache flush (or direct write) after the first rendered frame so `overlay_group_cache.json` reflects the new transform even if additional edits are still in-flight. Provide guardrails to avoid unbounded writes (e.g., min interval, coalescing identical payloads).
  4) **Stale-entry cleanup:** when a new generation/nonce arrives for a group, ensure any previous cached transformed data is immediately replaced/cleared in memory before the write to avoid HUD fallback seeing mismatched data.
  5) **Logging/telemetry:** add debug logs (guarded by dev mode) that record when cache writes are forced, skipped, or delayed; include generation/nonce info so we can debug stuck writes. Consider wiring this into the controller preview overlay.
  6) **Tests:** extend unit tests to assert (a) cache writes record the latest nonce/timestamp for every active group, (b) forced flushes happen when controller-active debounce is lowered, (c) stale cache entries are replaced promptly, and (d) background mode still batches writes. Introduce an integration-style test that simulates rapid offset changes and asserts the cache ends up with the expected transformed block after the final edit.
  7) **Manual verification:** with the overlay + controller running, perform rapid alt-click and offset drags, then inspect `overlay_group_cache.json` to confirm each edit writes within the shortened window and reflects the on-screen placement. Verify that returning to inactive mode reverts to the longer debounce.
  
Quick breadcrumbs for future sessions
-------------------------------------
- Key touchpoints:
  - Controller: `overlay_controller/overlay_controller.py` — `_build_group_snapshot`, `_draw_preview`, `_persist_offsets`, `_send_active_group_selection`.
  - Client: `overlay_client/render_surface.py` — `_fallback_bounds_from_cache`, `_apply_fill_translation_from_cache`, write-back via `_apply_group_logging_payloads` → `GroupPlacementCache`.
  - Cache plumbing: `group_cache.py`; overrides: `overlay_client/plugin_overrides.py`.
- Fallback/offset rule: if `transformed` exists, do not reapply offsets; if absent or stale, synthesize once from base+overrides (plus fill translation when fill+overflow) and persist it.
- POC flag idea: gate the shim with a dev toggle (e.g., `DEV_TARGET_CACHE_INVALIDATION`) to make removal easy.
- Tests to run on resume:
  - Unit: controller invalidation/synthesis; client stale-gating; fallback no double-offset; fill translation only once.
  - Manual: edit offsets/anchor in controller; verify preview + HUD target stay aligned with no snap-back; confirm cache `transformed` updates/nulls after edit; fallback path still aligns when HUD payload is absent.
