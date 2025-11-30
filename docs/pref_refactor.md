# Preferences Refactor Plan

This plan tracks the work to make preference persistence platform-agnostic and easier to reason about. It mirrors the structure of `client_refactor.md` but scoped to preference storage and bootstrap flows. Keep stages small, testable, and behavior-preserving.

## Current Preference storage differences (i.e. issues)

- The Preferences object takes two different persistence paths. When EDMC’s config object is present (_config_available()), it treats those edmc_modern_overlay.* keys as the source of truth, then mirrors them into overlay_settings.json (overlay_plugin/preferences.py (lines 30-187), 313-375). That’s the normal Windows/EDMC path, so stale config entries can overwrite the JSON on startup.
- If config can’t be imported (common when running the client/CLI/tests outside EDMC, which is often how we run on Linux), the code skips the config path and only reads/writes overlay_settings.json (overlay_plugin/preferences.py (lines 165-186), 313-317). No merge-back to EDMC happens because there’s no config to save to.
- The PyQt client always seeds itself from overlay_settings.json before live updates arrive (overlay_client/overlay_client.py (lines 3871-3890) via overlay_client/client_config.py), so keeping that file in sync is critical regardless of platform; the Windows path does this as a shadow write, the config-less path relies on it exclusively.
- Build mode also affects what “persists”: release builds (typical Windows packages) automatically clear force_render unless allow_force_render_release is set, while dev builds (what we usually run on Linux) keep it (overlay_plugin/preferences.py (lines 383-402) with version.py dev-mode detection). That can make the same toggle feel different across OS even with identical code.
- Linux-only knobs such as force_xwayland are applied when spawning the client (load.py (lines 2186-2203)) but are effectively no-ops on Windows, so they don’t influence Windows persistence.

## Goals
- Single source of truth for preferences across Windows/Linux/macOS.
- Predictable load/save order so UI changes persist regardless of platform or EDMC config availability.
- Clear migration story from the current split (EDMC config primary on Windows, JSON-only elsewhere).
- Maintain existing safety rails (release-mode force-render gating) while making them consistent.

## Ground rules
- Plan before code: add a short stage intent here before editing code.
- Keep behavior stable per stage; document any intentional user-facing change.
- Update stage status and test notes immediately after each stage.
- Prefer small, isolated changes; add focused tests when adding new behavior.

## Proposed approach
- **JSON-first:** Always load from `overlay_settings.json` first; treat EDMC config as an optional mirror, not the source of truth.
- **Unified save path:** Write the full preference payload to `overlay_settings.json` every time; mirror to EDMC config when available, but never let missing/old config overwrite JSON.
- **Consistent gating:** Apply dev/release gating (e.g., `force_render` + `allow_force_render_release`) uniformly, independent of platform/config availability.
- **Storage adapter:** Centralize read/write/merge logic in a small helper (e.g., `PreferenceStore`) so UI panels/runtime don’t duplicate platform checks.
- **Bootstrap symmetry:** Keep the PyQt client seeding from `overlay_settings.json`; ensure the plugin writes the same payload the client reads.
- **Migration:** One-time import from EDMC config into JSON only when JSON is missing/corrupt; mark a version flag to avoid re-import loops.
- **Observability:** Add targeted logging/metrics around load source (JSON vs. config), merge decisions, and failed writes.

## Stages
| Stage | Description | Status |
| --- | --- | --- |
| 1 | Document current load/save flow (JSON vs. EDMC config) and enumerate platform-specific differences/edge cases. | Planned |
| 2 | Introduce JSON-first loading with optional config merge (config only fills holes or missing JSON); keep behavior otherwise unchanged. | Planned |
| 3 | Unify saving: always write JSON, mirror to config when available; ensure release gating runs once per save. | Planned |
| 4 | Add storage adapter/seams used by `Preferences` and the Tk panel; remove duplicated platform branching. | Planned |
| 5 | Implement one-time migration from EDMC config to JSON when JSON is absent/invalid; mark version to prevent repeats. | Planned |
| 6 | Add/extend tests covering load precedence, save mirroring, gating, and migration; document results. | Planned |

## Testing (run after each code stage)
- `make check`
- `make test`
- `PYQT_TESTS=1 python -m pytest overlay_client/tests`
- Targeted preference tests (existing or new) under `tests/` and `overlay_client/tests/`

## Notes/TODOs
- Capture any platform-specific failure modes (e.g., EDMC config write failures) as they arise and add logging expectations here.
- If release gating changes, record the intended user-facing behavior and add regression tests before marking the stage complete.
