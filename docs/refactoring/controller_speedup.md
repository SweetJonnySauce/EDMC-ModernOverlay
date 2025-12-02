# Controller Feedback Speedup

Goal: improve real-time feedback when tweaking payload group placement via the Overlay Controller.

Working notes:
- Capture current latency sources (config write debounce, overlay reload strategy, cache flush cadence, controller poll interval, TTL interactions).
- Define acceptance targets (e.g., sub-second config→onscreen move when controller is open).
- Enumerate mitigation options (e.g., on-demand override reload, faster cache flush while controller active, higher-frequency controller polls, heartbeat/timeout safeguards).

Use this doc to jot requirements, constraints, and experiments as we iterate.

## Dev Best Practices

- Keep changes small and behavior-scoped; prefer feature flags/dev-mode toggles for risky tweaks.
- Plan before coding: note touch points, expected unchanged behavior, and tests you’ll run.
- Avoid Qt/UI work off the main thread; keep new helpers pure/data-only where possible.
- Record tests run (or skipped with reasons) when landing changes; default to headless tests for pure helpers.
- Prefer fast/no-op paths in release builds; keep debug logging/dev overlays gated behind dev mode.



## Requirement: Controller Active vs Inactive Modes

- Define explicit modes (Active vs Inactive) to toggle performance levers.
- Active mode: controller is open/connected; aim for near-real-time feedback (sub-second config→onscreen). Enable aggressive settings: very short config write debounce, immediate override reload signal, fast cache flush cadence, higher controller poll frequency.
- Inactive mode: controller closed; prioritize reduced churn. Use longer debounces and normal cache flush cadence; keep override reload on mtime or periodic checks only.
- Need a mode switch signal (controller→overlay) plus a heartbeat/timeout to auto-fall-back to Inactive if the controller disappears unexpectedly.

## Requirement: Active Mode Target Box On-Screen

- When the controller is active, draw a target box around the live payload group on the HUD, matching the look/behavior of the preview pane’s target box.
- Should mirror preview visuals (outline style, anchor marker) and track the group’s transformed bounds, including offsets/anchor/justification/nudge.
- Toggle with Active mode; in Inactive mode, the HUD stays clean (no target box).
- Only the active idPrefix group being edited should show a target box; avoid regressions that draw multiple or unrelated boxes.

## Requirement: Filter Groups by Cache Presence

- Controller dropdown should only list groups present in the cache; if a group is missing from `overlay_group_cache.json`, omit it entirely instead of showing a disabled/greyed option.
- Add polling to re-check the cache so newly captured groups appear once their cache entry exists.

## Requirement: Sample Payload for Offscreen Groups (Future)

- When the active idPrefix group has no live payloads on-screen, render a sample payload based on that group so the target box/preview has something to show.
- Capture a representative payload per group once and stash it in a lightweight payload store; provide a dev_mode button to flush this store.
- Store minimal metadata (e.g., in `overlay_groupings.json`) to keep lookup fast and avoid heavy file IO; client should check for presence cheaply before replaying a sample.
- Keep this as future work; design current scaffolding (mode signals, cache checks) so adding sample-replay later doesn’t require major refactors.

## Phased Plan

### Phase 1: Mode plumbing and overrides reload

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Reuse existing controller-active signal (“Overlay Controller is Active”) as the mode flag; add heartbeat/timeout to auto-revert. Mitigate risks: strict payload schema/validation, UI-thread timers, timeout > heartbeat interval, keep legacy status untouched, log mode flips. | In progress |
| 1.2 | Gate fast-path behaviors on mode; keep defaults safe in Inactive. | Not started |
| 1.3 | Add controller-triggered override reload signal after writes; overlay forces immediate reload (bypass mtime) and resets grouping helper. | Not started |
| 1.4 | Add/update tests covering mode signal/timeout and override force-reload path; include invalid/duplicate signal handling. | Not started |

### Phase 2: Group list filtering and cache cadence

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Filter dropdown to cache-present groups only; omit missing groups instead of greying out. | Not started |
| 2.2 | Add cache polling to refresh the list when new groups appear; preserve selection when possible. | Not started |
| 2.3 | Tie cache flush cadence/poll interval to mode (fast in Active, normal in Inactive) with fallback to normal on heartbeat timeout; replace debug vs. release timing with mode-based timing. | Not started |
| 2.4 | Add/update tests for cache-based filtering and mode-tied cadence behavior. | Not started |

### Phase 3: Target box overlay (Active-only)

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Render HUD target box in Active mode, matching preview style (outline + anchor) and tracking transformed bounds (offset/anchor/justification/nudge). | Not started |
| 3.2 | Ensure only the active idPrefix group shows a target box; no multiple/unrelated boxes. | Not started |
| 3.3 | Add/update tests for target-box gating to the active group and mode-only rendering. | Not started |

### Phase 4: Scaffolding for sample payloads (future)

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Add lightweight metadata hook to record presence of a captured sample payload per group (e.g., in overlay_groupings.json or cache). | Not started |
| 4.2 | Add a cheap presence check seam for future sample replay when the active group is offscreen; include a dev_mode flush hook placeholder. | Not started |
| 4.3 | Add/update tests for metadata presence checks and dev_mode flush hook (even if stubbed). | Not started |
