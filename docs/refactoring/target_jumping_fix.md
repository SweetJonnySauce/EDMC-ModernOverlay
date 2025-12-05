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

Safeguards / Risk Mitigation
----------------------------
- Single writer / locking: designate one writer for the cache or use a simple lock/generation to avoid clobbering concurrent writes.
- Atomic writes: write to temp then rename; validate JSON before swap.
- Timestamp discipline: use monotonic timestamps or an edit generation counter to avoid skew issues.
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
| 0 (POC) | Prove “controller target drives HUD”: on edit, clear `transformed`/set `has_transformed=false`/bump `last_updated`; controller ignores cached `transformed` entirely (uses base+overrides); extend live-edit window to keep snapshot in-memory; atomic writes for user overrides with post-edit reload pause; client fallback recomputes target from base+overrides and ignores cached `transformed`; overrides are pushed directly to client and applied regardless of previous nonce. Validate via manual tweaks. Disposable shim acceptable. | In progress |
| 1 | Harden controller invalidation + preview synthesis: debounce + atomic cache writes, reload signal; snapshot uses synthesized transform until client rewrites. Add controller unit tests. | Not started |
| 2 | Client stale-gating + single-application: ignore stale `transformed`; recompute from base+overrides; fallback/draw apply offsets once and fill translation once. Add client/unit tests for gating + no double-offset. | Not started |
| 3 | Write-back discipline: after render with new offsets/anchor, write fresh `transformed` with updated `last_updated`; verify debounce/flush timing and convergence tests. | Not started |
| 4 | Integration/regression: end-to-end edits without jumps; fallback matches controller target when HUD absent; clean up POC shims/flags, keep minimal logging. | Not started |

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
