## Goal: To address Github Issue # 29 without causing regression for other users

## Overview of Issue
https://github.com/SweetJonnySauce/EDMCModernOverlay/issues/29

## Refactorer Persona
- Bias toward carving out modules aggressively while guarding behavior: no feature changes, no silent regressions.
- Prefer pure/push-down seams, explicit interfaces, and fast feedback loops (tests + dev-mode toggles) before deleting code from the monolith.
- Treat risky edges (I/O, timers, sockets, UI focus) as contract-driven: write down invariants, probe with tests, and keep escape hatches to revert quickly.
- Default to “lift then prove” refactors: move code intact behind an API, add coverage, then trim/reshape once behavior is anchored.
- Resolve the “be aggressive” vs. “keep changes small” tension by staging extractions: lift intact, add tests, then slim in follow-ups so each step stays behavior-scoped and reversible.
- Track progress with per-phase tables of stages (stage #, description, status). Mark each stage as completed when done; when all stages in a phase are complete, flip the phase status to “Completed.”
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
| 1 | Implement gated physical clamp (default off; setting surfaced in User prefs and mirrored to overlay_settings.json) | Completed |
| 2 | Add per-monitor override option (escape hatch when auto clamp is insufficient) | Pending |
| 3 | QA and rollout (flag default-off verification; optional opt-in release) | Pending |

## Phase Details

### Issue Context (29) — overlay misplacement with fractional desktop scaling (Cinnamon/GNOME on X11)
- Symptom: Overlay anchored between monitors and shrunk when desktop scaling is ~1.4x; Qt reports DPR≈1.396 with logical/native geoms identical, so we downscale to ~0.7 and clip.
- Environment: Linux Mint Debian Edition, Cinnamon on X11, flatpak EDMC. Desktop `text-scaling-factor` set to 1.4; Xft.dpi at 134; xrandr shows two monitors (2560x1440 primary at +1920+0; 1920x1080 secondary at +0+360).
- What we tried: Launching EDMC with various QT_* scaling env vars and QT rounding policy—Qt still reported DPR≈1.396. Moving desktop scaling back to 1.0 (Cinnamon/GNOME gsettings + Xft.dpi 96) fixed the overlay placement.
- Confirmed fix: Setting `org.cinnamon.desktop.interface text-scaling-factor` and `org.gnome.desktop.interface text-scaling-factor` to 1.0, and Xft.dpi to 96; after logout/login, overlay anchors correctly and Qt DPR=1.0 in logs.
- Ongoing need: For users who insist on >1x scaling, we need plugin-side mitigation (see “Issue 29” section below for options).
- Code changes so far (fix_for_#29 branch):
  - a55c78e: Added DPI-aware fallback in `overlay_client/follow_geometry.py` to downscale by 1/dpr when DPR>1 and logical/native geoms match but reported native size disagrees with DPR; adjusted origins; added tests (`overlay_client/tests/test_follow_geometry.py`); minor settings tweak.
  - c88d5fe: Added debug instrumentation (geometry normalisation, aspect guard pass, WM override decision).
  - 4f2b8c5: Reduced log verbosity by deduping geometry normalisation logs and kept a plugin-compat note about desktop scaling.

## Issue 29: Handling fractional desktop scaling (user keeps >1x)

If desktop scaling stays above 1.0, plugin-level mitigations to avoid overlay misplacement:

| Option | Summary | Risk | Likely success | Tried? |
| --- | --- | --- | --- | --- |
| Auto ignore/clamp when geoms match | If logical/native geoms align and DPR is non-integer, force scale_x/scale_y to 1.0 (or xrandr-derived) to avoid shrink/offset. | High: changes core geometry math for all; can misplace overlays on legit fractional DPR/mismatched geoms. | High | No |
| Physical-pixel clamp | Use xrandr native sizes to map tracker→Qt; ignore non-integer DPR when geoms align (tolerates drift). | High: core-path change; assumes xrandr is accurate; risk of offsets on mixed DPI/rotation/Xwayland cases. | High | No |
| Per-monitor override | User-configurable clamp per screen (e.g., `DisplayPort-2=1.0`) as an escape hatch. | Low: opt-in, scoped to one monitor. | Low-Med (env-level attempt had no effect; plugin-level toggle might still help) | Yes — tried via QT_SCREEN_SCALE_FACTORS=DisplayPort-2=1;HDMI-A-0=1 and had no effect |
| Compat DPI toggle | User-facing switch to disable HighDPI inside overlay (PassThrough rounding, QT_AUTO_SCREEN_SCALE_FACTOR=0, QT_ENABLE_HIGHDPI_SCALING=0, QT_SCALE_FACTOR=1). | Low: opt-in, isolated to overlay process. | Medium (helps only if desktop scaling isn’t forcing DPR) | Yes — ineffective alone in user test (DPR stayed ~1.396) |
| Integer rounding fallback | If DPR is non-integer and geoms match, round to 1.0 or 2.0 before applying. | Medium: simple fallback; less precise; narrower impact. | Medium | No |

Recommendation: ship auto clamp (physical-pixel approach) with care, provide per-monitor override and compat DPI toggle, and keep integer rounding as a low-effort fallback.

## Mitigation plan: gated physical clamp

- Goal: Provide an opt-in “physical clamp” that neutralizes fractional DPR from desktop scaling without changing system settings, while leaving defaults unchanged.
- Approach: Add a setting (default off). When enabled and geometries effectively match and DPR is non-integer, compute tracker→Qt mapping from xrandr native sizes or force scale=1.0, skipping DPR shrink. When disabled, keep current behavior.
- Scope/Guard: Guard the new path with the setting and a geom-match check; optionally allow per-monitor map to scope the clamp. Surface the setting in the User section of the preferences pane and mirror it into `overlay_settings.json` so the client can read it at startup.
- Tests: Verify flag on/off with fractional DPR and mixed cases; ensure “off” path is identical; manual QA on dual-monitor X11 and a fractional DPI setup.
- Risk: High if enabled broadly (core geometry change; xrandr accuracy); mitigated by default-off and per-monitor scoping.

### Phase 1: Gated physical clamp (default off)
- Implement the opt-in clamp path and setting; ensure defaults unchanged and client reads the flag at startup via overlay_settings.json.

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Add setting flag (User prefs UI) and mirror to overlay_settings.json | Completed (runtime OverlayConfig propagation added) |
| 1.2 | Implement guarded clamp in follow_geometry (geom match, non-integer DPR) | Completed |
| 1.3 | Unit tests for on/off paths; ensure off-path unchanged | Completed (pytest passing) |
| 1.4 | Manual QA on dual-monitor X11 with fractional DPR | Completed |

#### Stage 1.1 Plan — Setting flag (User prefs UI + overlay_settings.json)
- Tasks:
  - Add a User-section checkbox/toggle for “Physical clamp” (default off).
  - Persist the value via prefs services, mirroring into `overlay_settings.json` so the client can read it at startup.
  - Ensure the overlay client tolerates missing/legacy keys (default false).
- Risks:
  - Breaking prefs save/load or `overlay_settings.json` schema; unintended default-on behavior.
  - Client startup errors if the key is absent or malformed.
- Mitigations:
  - Default false; keep backward-compatible parsing (missing => false).
  - Add a unit test covering prefs round-trip and JSON export/import with/without the new key.
  - Manual smoke: toggle in UI, restart plugin/client, confirm flag reflects in `overlay_settings.json`.

#### Stage 1.1 Addendum — Runtime OverlayConfig propagation (implemented)
- Tasks:
  - Include `physical_clamp_enabled` in the `OverlayConfig` payload built in `load.py` so runtime toggles reach the client without restart. ✅
  - Verify the client applies the incoming flag via the existing setter (`set_physical_clamp_enabled`), then writes back any WM overrides reset. ✅ (setter already wired; payload now delivers)
  - Add a regression test to assert the payload contains the flag and that the client updates state on receipt. ✅ (`tests/test_overlay_config_payload.py`)
- Risks:
  - **Config payload regression:** Adding a field could break clients if not backward compatible.
  - **Unexpected enablement:** A bad default or parse could flip the flag on for users who never toggled it.
  - **Toggle churn:** Frequent config rebroadcasts might clear WM overrides too often if the flag flaps.
- Mitigations:
  - Default false everywhere; guard parsing with `bool(...)` and tolerate missing keys.
  - Add unit coverage for payload emit/parse to lock defaults and ensure legacy clients ignore the new field. ✅
  - Emit a single log line when the flag changes to aid QA; ensure WM override clears only on actual state change. (existing logging)

#### Stage 1.2 Plan — Guarded clamp in follow_geometry
- Tasks:
  - Trace the current geometry pipeline (`overlay_client/follow_geometry.py`) to capture the existing scaling branches (geom-match DPR path vs. mismatch path) and document expected unchanged behavior when the flag is off.
  - Introduce a clamp predicate that requires: setting enabled, non-integer DPR (tolerance: e.g., `abs(dpr - round(dpr)) > 0.05`), and effectively matching logical/native geoms (within existing tolerance).
  - When predicate passes, bypass the DPR shrink: force `scale_x/scale_y` to physical/native mapping (1.0 when geoms match; otherwise derived from native width/height), keep origins consistent, and emit a one-time debug log indicating clamp activation and chosen scales.
  - Preserve the legacy paths verbatim when the predicate fails (flag off, integer DPR, or mismatched geoms) to keep default behavior unchanged.
  - Add guard rails: sanity-check scales for >0 and finite values; fall back to legacy math on validation failure; ensure `_last_normalisation_log` only updates when behavior changes to avoid log spam.
- Risks:
  - **False positives on real HiDPI**: A legitimate fractional DPR (or driver rounding) could be clamped, misplacing overlays on mixed-DPI/rotated/Xwayland setups.
  - **Bad inputs from platform**: Incorrect/zero native sizes or origins could yield bogus scales or crashes if not validated.
  - **Regression with flag off**: Refactor could subtly alter the off-path (e.g., tolerances or defaults), changing placement for all users.
  - **Noise/instability**: Extra logging or state drift (`_last_normalisation_log`) could mask real changes or spam logs in dev mode.
- Mitigations:
  - Keep the flag default-off; gate all new math behind the predicate plus geometry-match + non-integer DPR checks; require validation of scales before use.
  - Maintain a strict fallback: on any validation failure, bail to the existing path unchanged; include a debug breadcrumb when clamping is skipped or reverted.
  - Reuse current tolerances for geom matching; avoid touching other branches; add targeted unit coverage in Stage 1.3 to assert the off-path is byte-for-byte equivalent for representative inputs.
  - Limit logging to first activation per screen and include the flag state in the message to aid QA without flooding logs.

##### Stage 1.2 Implementation (code landed; unit tests passing)
- Changes:
  - `overlay_client/follow_geometry.py`: `_convert_native_rect_to_qt` now accepts `physical_clamp_enabled`; when flag is on and DPR is fractional with matching geoms, we keep a 1:1 mapping (skip DPR shrink), log clamp once, and fall back to legacy math otherwise.
  - `overlay_client/follow_surface.py`: threads the flag into geometry conversion based on `_physical_clamp_enabled`.
  - `overlay_client/setup_surface.py`: stores initial `_physical_clamp_enabled` from boot settings.
  - `overlay_client/control_surface.py`: new setter `set_physical_clamp_enabled` to toggle and refresh follow geometry; clears WM overrides on change.
  - `overlay_client/developer_helpers.py`: applies the flag at startup and from payloads.
- Guard rails in code: non-finite DPR coerced to 1.0; clamp only when flag+fractional DPR+geom match; otherwise legacy path unchanged; debug logs emitted once per change.
- Testing status: `python3 -m pytest overlay_client/tests/test_follow_geometry.py` passes (Stage 1.3 coverage added and green).

#### Stage 1.3 Plan — Unit tests for on/off paths and regressions
- Tasks:
  - Add targeted tests in `overlay_client/tests/test_follow_geometry.py` to cover: flag off (fractional DPR + matching geoms stays legacy scaled), flag on (fractional DPR clamps to 1:1), flag on with mismatched geoms (fallback to legacy path), integer DPR with flag on (no clamp), and invalid/zero DPR (coerced to 1.0).
  - Add a log snapshot/assertion helper to confirm clamp activation emits a single debug log entry (dev mode) while preserving `_last_normalisation_log` deduping.
  - If needed, add a thin integration test for the flag plumbing in `follow_surface` (ensuring `_physical_clamp_enabled` is passed through) using a stubbed `_screen_info_for_native_rect`.
  - Keep existing tests intact to verify no behavioral drift on legacy paths; rerun the suite scoped to follow geometry tests.
- Risks:
  - **Behavioral drift in legacy path**: tests might encode new expectations that mask regressions or overfit to current tolerances.
  - **Log assertions brittle**: debug log ordering/deduping could change, causing false negatives.
  - **Test flakiness on platforms**: Qt availability or environment differences could break integration-style tests.
- Mitigations:
  - Anchor off-path expectations to pre-change math (explicit inputs/outputs); avoid altering tolerances in the tests.
  - Prefer structural assertions (presence of clamp log once) rather than exact log ordering; guard with dev-mode enabling where required.
  - Keep tests headless/pure where possible; if integration is added, mark it to skip when Qt is unavailable; scope test runs to `overlay_client/tests/test_follow_geometry.py` for quick feedback before broader runs.

##### Stage 1.3 Implementation (tests added)
- Tests added in `overlay_client/tests/test_follow_geometry.py` covering:
  - Flag on clamps fractional DPR with matching geoms (1:1).
  - Flag off retains legacy fractional scaling.
  - Flag on with mismatched geoms falls back to legacy scaling.
  - Flag on with integer DPR uses legacy scaling (no clamp).
  - Non-finite/zero DPR coerced to 1.0.
  - Clamp log emitted once when re-invoked (forces logger propagation for capture).
- Test execution: `python3 -m pytest overlay_client/tests/test_follow_geometry.py -q` passing locally.

##### Phase 1 gaps uncovered in review
- Runtime propagation missing: `physical_clamp_enabled` is not included in the `OverlayConfig` payload sent by the plugin (`load.py`). Result: toggling the checkbox only updates `overlay_settings.json`; the running client never receives the change. Action: add the flag to `OverlayConfig` payload/logging, ensure the client applies it via the existing setter, and add a regression test.
- Optional: add a thin integration test to assert `_physical_clamp_enabled` is threaded through `_screen_info_for_native_rect` in `follow_surface`.

#### Stage 1.4 Plan — Manual QA on dual-monitor X11 with fractional DPR
- Environment:
  - X11 with dual monitors (e.g., 2560x1440 primary + 1920x1080 secondary).
  - Desktop scaling/text-scaling-factor ~1.4 (or similar fractional DPR); Xft.dpi ≈ 134.
- Scenarios to cover:
  - **Flag off (default)**: launch overlay, confirm placement matches pre-change behavior (no clamp). Verify debug logs show normalisation without “Physical clamp applied”.
  - **Flag on**: enable Physical Clamp in prefs, restart overlay/client, reproduce overlay; confirm it anchors correctly on the target monitor without shrinking/offset. Check logs contain one “Physical clamp applied…” entry per screen.
  - **Mixed monitors**: move the game window between monitors (primary/secondary) and confirm clamp behavior does not misplace on the other display.
  - **Integer DPR check**: set scaling to 1.0, confirm flag on/off behaves identically (no regressions).
- Steps:
  1) Set scaling to ~1.4 (Cinnamon/GNOME text-scaling-factor 1.4; Xft.dpi 134), log out/in.
  2) Start EDMC + overlay with flag off; trigger overlay; note placement and logs.
  3) Toggle Physical Clamp on in prefs; restart overlay/client; trigger overlay; note placement and logs.
  4) Move game window between monitors and repeat trigger to observe any offsets.
  5) Return scaling to 1.0; repeat quick smoke with flag on/off to confirm no regression.
- Observations to capture:
  - Overlay position/size per monitor and before/after flag toggle.
  - Presence of “Physical clamp applied” log and normalisation scales.
  - Any misplacement, clipping, or WM override clearing when toggling the flag.

### Phase 2: Per-monitor override option
- Allow per-screen clamp configuration as an escape hatch when auto clamp isn’t enough.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add per-monitor map setting (UI + overlay_settings.json) | Completed |
| 2.2 | Apply per-monitor clamp in follow_geometry when present | Completed |
| 2.3 | Tests/QA for override application and fallback behavior | Pending |

##### Stage 2.1 Implementation (per-monitor map setting)
- Changes:
  - Added `physical_clamp_overrides` preference with validation/clamping (0.5–3.0) and stable formatting helpers; persisted to both EDMC config and `overlay_settings.json` (default `{}`).
  - User prefs UI now exposes a comma-separated per-monitor override field under the clamp toggle; helper text clarifies expected `name=scale` format; invalid entries are skipped with inline status.
  - OverlayConfig payload now carries `physical_clamp_overrides` so runtime clients can consume overrides without restart.
  - Default settings file includes the empty overrides map for discoverability.
- Tests:
  - `tests/test_preferences_persistence.py` covers persistence/merge of `physical_clamp_overrides` across config and shadow JSON.
  - `tests/test_overlay_config_payload.py` asserts `OverlayConfig` includes both `physical_clamp_enabled` and the overrides map.
- Notes:
  - Overrides accept JSON/object or `name=scale` strings; invalid/non-finite/non-positive scales are rejected, and out-of-range values are clamped with a warning.
  - Stage 2.2 will apply these per-monitor scales inside `follow_geometry`; current change is storage + payload only.

#### Stage 2.2 Plan — apply per-monitor clamp in follow_geometry
- Tasks:
  - Thread `physical_clamp_overrides` into the client (bootstrap and runtime payload) and surface it to `follow_geometry._convert_native_rect_to_qt`.
  - Add override lookup: when the map contains the current screen name, use the override scale instead of the physical clamp heuristic; keep flag off/empty map as no-op.
  - Validate and log: ignore non-finite/zero/negative scales from the map at runtime; emit a debug breadcrumb when an override is applied or skipped due to a missing screen name.
  - Ensure overrides do not clear WM overrides unless the scale changes; reuse existing clamp logging to avoid extra spam.
  - Keep backward compatibility: legacy clients that don’t understand overrides should continue using the existing clamp flag path.
- Risks:
  - **Misapplied overrides**: wrong/mismatched screen IDs could lead to silent no-op or applying the wrong scale.
  - **Runtime instability**: bad values (NaN/inf/zero) could crash or distort geometry if not revalidated client-side.
  - **Regression on default path**: injecting override handling could perturb the flag-off or no-override behavior.
  - **Logging noise**: per-frame logs when overrides are present could spam dev logs.
- Mitigations:
  - Validate override scales again in the client (finite, >0, clamp to safe range) and bail to existing clamp/legacy path on failure.
  - Match screen names exactly; log a single debug once per screen when applying/skipping an override to aid QA; avoid per-frame spam by caching last log.
  - Keep predicate ordering: only consult overrides when the map is non-empty; when absent, leave existing clamp logic untouched; add targeted unit tests for override hit/miss/default-off.
  - Maintain fallback to legacy clamp behavior when overrides are absent or invalid; ensure runtime payload parsing tolerates missing keys.

##### Stage 2.2 Implementation (apply overrides in client)
- Changes:
  - Client bootstrap and runtime config now carry `physical_clamp_overrides`; developer helpers pass them to the window, and a new setter normalises/clamps scales (0.5–3.0) before applying.
  - `follow_geometry._convert_native_rect_to_qt` consumes overrides (when the clamp flag is on), applying the per-monitor scale in place of the fractional-DPR heuristic and logging once per screen; invalid overrides are ignored with a debug breadcrumb.
  - Follow surface threads the override map into geometry conversion; overrides are stored on the window at setup and refreshed on updates without disturbing default paths.
- Tests:
  - `overlay_client/tests/test_follow_geometry.py` now covers override hit, override ignored when the flag is off, and invalid override fallback.
  - Existing config/persistence tests still pass, verifying payload includes overrides and preferences persist them.

#### Stage 2.1 Plan — per-monitor map setting (UI + overlay_settings.json)
- Tasks:
  - Add a User-pref input for per-monitor clamp overrides (e.g., `DisplayPort-2=1.0, HDMI-0=1.25`), default empty, with helper text showing the screen name format the client reports.
  - Persist overrides as a dict in `overlay_settings.json` (and include in the runtime `OverlayConfig` payload) so the client can read them without a restart once Stage 2.2 lands.
  - Validate scales (finite, >0, bounded to a safe range like 0.5–3.0) and normalise keys (strip whitespace, case-stable) before writing; drop invalid entries with a user-facing warning/log.
  - Keep backward compatibility: missing/empty map must preserve current behavior; older clients should ignore the new key gracefully.
  - Add unit tests for prefs round-trip and JSON export/import covering valid/invalid entries and default-empty behavior.
- Risks:
  - **Invalid input crashes or silently flips on overrides**: malformed map entries or extreme scales could break parsing or clamp unexpectedly.
  - **Wrong screen identifiers**: users may enter names that do not match Qt/xrandr labels, leading to “override does nothing” confusion.
  - **Backward-compat regression**: adding the key could disturb existing settings consumers or older clients if defaults are wrong.
- Mitigations:
  - Harden parsing with strict validation, bounded scales, and safe defaults (empty map). Reject/skip bad entries and emit a clear warning instead of applying them.
  - Surface helper text/examples (and optionally last-seen screen names from the client) so users target the right identifiers; log when an override is ignored due to a name miss.
  - Default to empty map, tolerate missing key on load, and cover the serializer/deserializer path with tests to lock the default-off behavior.

### Phase 3: QA and rollout
- Validate stability with default-off, document opt-in, and plan release.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Default-off regression check (unit + manual smoke) | Pending |
| 3.2 | Document opt-in/escape-hatch usage | Pending |
| 3.3 | Decide rollout (keep opt-in or enable for affected profiles) | Pending |
