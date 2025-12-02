# Controller Feedback Speedup

Goal: improve real-time feedback when tweaking payload group placement via the Overlay Controller.

Working notes:
- Capture current latency sources (config write debounce, overlay reload strategy, cache flush cadence, controller poll interval, TTL interactions).
- Define acceptance targets (e.g., sub-second config→onscreen move when controller is open).
- Enumerate mitigation options (e.g., on-demand override reload, faster cache flush while controller active, higher-frequency controller polls, heartbeat/timeout safeguards).

Use this doc to jot requirements, constraints, and experiments as we iterate.

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
