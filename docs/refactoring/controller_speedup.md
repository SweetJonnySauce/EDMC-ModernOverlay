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

## Requirement: Anchor Widget Mirrors HUD Placement

- The anchor widget should reflect HUD positioning: keep the anchor dot centered in the widget, and show the highlighted square relative to that center point (e.g., NW anchor highlights the lower-right quadrant).
- This is a visual-only change to the anchor widget preview; no changes to payload placement math on the HUD.
- Ensure the widget highlight and anchor marker stay in a consistent location while the group square moves relative to it, matching the on-HUD experience.

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
| 1.1 | Reuse existing controller-active signal (“Overlay Controller is Active”) as the mode flag; add heartbeat/timeout to auto-revert. Mitigate risks: strict payload schema/validation, UI-thread timers, timeout > heartbeat interval, keep legacy status untouched, log mode flips. | Completed |
| 1.2 | Gate fast-path behaviors on mode; keep defaults safe in Inactive. | Completed |
| 1.3 | Add controller-triggered override reload signal after writes; overlay forces immediate reload (bypass mtime) and resets grouping helper. | Completed |
| 1.4 | Add/update tests covering mode signal/timeout and override force-reload path; include invalid/duplicate signal handling. | Completed |

#### 1.2 Plan (mode-aware fast path)

- Knobs + targets: controller debounces (`_write_debounce_ms`, `_offset_write_debounce_ms`) ~50–75 ms Active vs 200 ms Inactive; controller status/cache poll `_status_poll_interval_ms` ~500–750 ms Active vs 2500 ms Inactive; overlay cache flush debounce (`GroupPlacementCache`) ~0.5–1.0 s Active vs 5 s Inactive. Keep heartbeat timeout > heartbeat interval; clamp minimums to avoid zero/hammering.
- Profile helper: central per-mode profile near `ControllerModeTracker`, with precedence `user/debug override > mode profile > defaults`; log chosen values.
- Apply on transitions: `mark_active` applies Active profile and restarts timers after cancel; timeout/`mark_inactive` reverts to Inactive defaults; controller launch starts in Active but can restore defaults on shutdown.
- Observability: log mode flips and applied profile values; keep extra cadence logging behind dev mode to reduce churn in release.
- Risk guards: cancel timers before rearm to avoid overlap; revert on missed heartbeat to avoid mode drift; fall back to Inactive on any signal parse failure; rate-limit cache/log churn if Active sticks; keep Inactive unchanged from today.

#### 1.3 Plan (controller-triggered override reload)

- Signal shape & transport: controller sends a lightweight reload signal after it writes `overlay_groupings.json`/offset updates (e.g., `LegacyOverlay` with `id=controller-override-reload` and a nonce/ts). Only emit once per flush; coalesce rapid writes.
- Plugin listener: `load.py` listens for the signal and immediately forces override reload (bypass mtime), resetting grouping helper state the same way the periodic reload does; ensure normal timers/mtime remain as fallback.
- Overlay client reaction: add a force-reload hook on grouping helper/cache so the broadcast triggers an immediate refresh without waiting for mtime; keep behavior identical to a fresh load.
- Safety/edge cases: ignore malformed/duplicate signals (nonce/ts check), rate-limit logs, and bound emission to post-flush only (not cache reads). Accept only the expected type/id to avoid arbitrary-triggered reloads.
- Risks: duplicate/malformed signals causing extra reloads; spam if not debounced; desync if signals are missed; state regression if force-reload interferes with in-progress edits or overrides normal cadence; security/log noise if validation/rate limits are weak.

#### 1.4 Plan (tests for mode signal/timeout and override force-reload)

- Controller mode/heartbeat tests: cover `ControllerModeTracker` timeout handling and duplicate active signals (already partly covered) plus integration hooks to ensure timer cancel/rearm happens on state flips; add a heartbeat timeout test in client with QTimer stub to verify `mark_inactive` fires after lapse.
- Mode profile application tests: assert mode profile logging/apply paths rearm cache debounce/status polls and clamp values; verify no-op when profile unchanged.
- Override reload signal tests: controller emits `controller_override_reload` once per flush with nonce; duplicates suppressed; payload shape validated. Plugin CLI handler ignores malformed payloads, dedupes by nonce, and broadcasts `OverlayOverrideReload`.
- Client reload handling tests: force-reload hook resets grouping helper/override manager/payload snapshots, triggers repaint/cache dirty, and ignores duplicate nonce.
- Negative/edge tests: malformed reload payload rejected, unknown command returns error, and reload path preserves fallback mtime-based reload (ensure state not broken if signal missed—doc in test notes).
- Mitigations: stub timers instead of real QTimer delays to avoid flake; gate PyQt-dependent tests with skips/markers; prefer minimal stubs over heavy mocking; assert on key fields/flags instead of exact log strings; include duplicate/missing-signal/error-path coverage and rely on mtime/timer reload as fallback to cover missed signals.



### Phase 2: Group list filtering and cache cadence

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Filter dropdown to cache-present groups only; omit missing groups instead of greying out. | Completed |
| 2.2 | Add cache polling to refresh the list when new groups appear; preserve selection when possible. | Completed |
| 2.3 | Tie cache flush cadence/poll interval to mode (fast in Active, normal in Inactive) with fallback to normal on heartbeat timeout; replace debug vs. release timing with mode-based timing. | Completed |
| 2.4 | Add/update tests for cache-based filtering and mode-tied cadence behavior. | Completed |

#### 2.1 Plan (filter dropdown to cache-present groups only)

- Behavior: controller dropdown lists only groups present in `overlay_group_cache.json`; missing groups are omitted (no disabled/greyed options).
- Data source: use the controller’s in-memory cache from `overlay_group_cache.json`; presence of a group entry is the inclusion criterion.
- UI refresh: rebuild options from cache on refresh; preserve current selection when still present, otherwise clear selection and disable controls gracefully; re-enable when selection returns.
- Polling: tie dropdown refresh to existing cache/status poll; debounce/batch UI refresh to avoid flicker; if a poll fails, keep the previous list instead of clearing it.
- Safety/UX: defensive parsing to skip malformed entries without throwing; log when a selection is dropped due to missing cache; keep focus stable during rebuilds.

#### 2.2 Plan (cache polling refresh with selection preservation)

- Goal: keep the dropdown in sync with `overlay_group_cache.json` as new groups appear, without flicker; preserve selection when still present.
- Poll cadence: reuse existing cache/status poll; compute a simple diff/signature of cache groups and rebuild only when it changes; debounce UI rebuilds.
- Selection handling: keep selection if the group still exists; only clear/disable when it truly disappears; restore selection and controls when it reappears; log drops/restores at debug level.
- Safety/observability: defensive JSON parsing (no-op on errors); wrap refresh in try/except to keep the poll loop alive; skip malformed entries; keep focus stable.
- Mode-aware tuning: keep mode-based poll intervals, and cap rebuild frequency in Active mode to avoid churn; ensure Inactive isn’t too sluggish.

#### 2.3 Plan (mode-tied cache flush and poll cadence)

- Goal: Active mode uses faster cache flush debounce and controller status/cache poll interval; Inactive reverts to safe defaults; auto-revert on heartbeat timeout.
- Controller: set poll interval from the mode profile; cancel/rearm on mode flips with clamped minimums (e.g., ≥500 ms Active, ≥2.5 s Inactive); avoid double-start.
- Client: adjust `GroupPlacementCache` debounce and any cache poll cadence on `mark_active`/`mark_inactive`; cancel/rearm timers cleanly; keep defaults if profile lookup fails.
- Fallbacks: heartbeat timeout forces Inactive cadence; treat malformed/missed signals as no-ops; keep current timings on errors.
- Safety/logging: clamp intervals to prevent hammering; rate-limit cadence-change logs; add a grace period to avoid false-negative timeouts; log only on value changes.

#### 2.4 Plan (tests for cache filtering and mode-tied cadence)

- Dropdown/cache filtering: test `_load_idprefix_options` to ensure only cache-present groups appear; malformed entries are skipped without exceptions; selection preserved when present and controls only disabled when missing.
- Refresh polling: test `_refresh_idprefix_options` change detection (no rebuild on unchanged cache, rebuild on added groups), selection drop/restore when cache removes/returns a group.
- Mode cadence: tests that controller poll interval clamps/reschedules on mode change (Active fast, Inactive default) and no-op when unchanged; client cache debounce flips with mode and cancels/rearms timers cleanly.
- Heartbeat/timeout: test timeout/mark_inactive reverts cadence and doesn’t leave fast timers running.
- Mitigations in tests: stub timers/callbacks to stay synchronous; use minimal fakes instead of heavy mocks; assert on key substrings in logs; guard PyQt/platform deps with skips; include malformed-cache and selection drop/restore edge cases.

### Phase 3: Target box overlay (Active-only)

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Render HUD target box in Active mode, matching preview style (outline + anchor) and tracking transformed bounds (offset/anchor/justification/nudge). | Completed |
| 3.2 | Ensure only the active idPrefix group shows a target box; no multiple/unrelated boxes. | Completed |
| 3.3 | Add/update tests for target-box gating to the active group and mode-only rendering. | Completed |

#### 3.1 Plan (Active-mode target box on HUD)

- Goal: render a HUD target box in Active mode matching the controller preview (outline + anchor marker), driven by transformed bounds (offset/anchor/justification/nudge) for the active idPrefix group.
- Gating: draw only when controller is Active and an active group exists; hide in Inactive/no-selection; ensure only one box renders (no stray groups).
- Data source: reuse existing grouping/transform data so HUD box matches actual placement; avoid new math paths.
- Rendering: lightweight outline + anchor marker layer that updates on movement/offset changes; align style to the preview (color/stroke/marker) and respect existing repaint debounce.
- Validation: tests for gating (Active only, correct group) and manual check for visual alignment with preview/HUD.
- Risks/mitigations: wrong gating (restrict to Active + selected group), misaligned bounds (reuse current transform helpers), performance churn (piggyback on existing paint/debounce), style regression (match preview styles), stale boxes (clear on selection change/inactive). Mitigate signal risks by debouncing/deduping selection-change signals, validating plugin/label, clearing state on timeout/invalid payloads, logging at debug on change only, and optionally resending selection on controller activation/heartbeat to heal misses.

#### 3.2 Plan (only active idPrefix shows HUD box)

- Gate rendering strictly to the current controller-selected idPrefix while Active; clear the box on selection change, controller exit, or inactive timeout.
- Use the active-group signal (controller→plugin→client) and the latest live/cached bounds/anchor for that group; ignore all other groups.
- Clear on malformed/missing plugin/label; ignore duplicate signals; process selection changes atomically to avoid flicker.
- Match cache fallback only to the active group (case-insensitive), never to other groups.
- Tests: selection swap removes old box and shows new; no box when inactive/empty selection; invalid signals don’t render anything.

#### 3.3 Plan (tests for target-box gating and Active-only rendering)

- Active-only gating: test HUD target box appears only in Active mode; clears on inactivity/timeout/controller exit.
- Active group only: switching active idPrefix moves the box to the new group and removes it from the old; other groups (even cached) never show a box.
- Cache fallback: when no live payload is present, box uses cache bounds/anchor/offsets for the active group; malformed/missing cache yields no box.
- Signal handling: `OverlayControllerActiveGroup` updates/clears active group and triggers repaint; duplicate/malformed signals don’t render extra boxes.
- Tests/guardrails: stub timers/mode transitions to stay synchronous; use minimal fakes; assert on box presence/absence rather than exact pixels; guard PyQt deps with skips/markers; include malformed/duplicate signal and bad cache-entry cases.
### Phase 4: Scaffolding for sample payloads (future)

| Stage | Description | Status |
| --- | --- | --- |
| 4.1 | Add lightweight metadata hook to record presence of a captured sample payload per group (e.g., in overlay_groupings.json or cache). | Not started |
| 4.2 | Add a cheap presence check seam for future sample replay when the active group is offscreen; include a dev_mode flush hook placeholder. | Not started |
| 4.3 | Add/update tests for metadata presence checks and dev_mode flush hook (even if stubbed). | Not started |

### Phase 5: Anchor widget alignment with HUD

| Stage | Description | Status |
| --- | --- | --- |
| 5.1 | Redesign anchor widget so the anchor dot stays centered and the highlighted square moves relative to center (e.g., NW anchor highlights lower-right quadrant). | Not started |
| 5.2 | Implement visual-only update in the controller widget; no changes to payload placement math. Ensure highlight/anchor positions remain consistent. | Not started |
| 5.3 | Add/update tests or visual sanity checks (e.g., screenshot baseline or geometry assertions) to confirm the widget reflects HUD placement semantics. | Not started |
