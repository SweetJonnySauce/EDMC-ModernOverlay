## Goal: To address Github Issue # 29 without causing regression for other users

## Overview of Issue


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
| 1 | Implement gated physical clamp (default off; setting surfaced in User prefs and mirrored to overlay_settings.json) | Pending |
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
| 1.1 | Add setting flag (User prefs UI) and mirror to overlay_settings.json | Completed |
| 1.2 | Implement guarded clamp in follow_geometry (geom match, non-integer DPR) | Pending |
| 1.3 | Unit tests for on/off paths; ensure off-path unchanged | Pending |
| 1.4 | Manual QA on dual-monitor X11 with fractional DPR | Pending |

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

### Phase 2: Per-monitor override option
- Allow per-screen clamp configuration as an escape hatch when auto clamp isn’t enough.

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Add per-monitor map setting (UI + overlay_settings.json) | Pending |
| 2.2 | Apply per-monitor clamp in follow_geometry when present | Pending |
| 2.3 | Tests/QA for override application and fallback behavior | Pending |

### Phase 3: QA and rollout
- Validate stability with default-off, document opt-in, and plan release.

| Stage | Description | Status |
| --- | --- | --- |
| 3.1 | Default-off regression check (unit + manual smoke) | Pending |
| 3.2 | Document opt-in/escape-hatch usage | Pending |
| 3.3 | Decide rollout (keep opt-in or enable for affected profiles) | Pending |
