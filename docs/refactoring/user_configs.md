# User Config Layering Plan

Goal: keep shipping `overlay_groupings.json` with defaults while letting users customize placements and survive upgrades, without changing `define_plugin_group()` behavior.

Constraints:
- Keep shipping `overlay_groupings.json`; plugin updates can change it.
- `define_plugin_group()` must keep writing to the shipped file (same path and semantics as today).
- Users need a separate, durable layer for their own placements that is not overwritten on upgrade.

Use this doc to jot requirements, constraints, and experiments as we iterate.

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

## Phase Overview

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Define user-config file location plus merge semantics for defaults + user overrides; document expectations and edge cases. | Complete |
| 2 | Implement layered loading/merging in client + controller; keep API writes on the shipped file but direct controller edits to the user file. | In progress |
| 3 | Add migration/backfill so existing user edits (currently in the shipped file) are copied into the user layer on upgrade; handle absence/corruption gracefully. | Not started |
| 4 | Tests and docs: unit/integration coverage for the loader/merger + controller writes; update user/operator docs and release notes. | Not started |
| 5 | Update installers/scripts to preserve the user config file during upgrades (never overwrite `overlay_groupings.user.json` if present). | Not started |

## Phase Notes

### Phase 1: Layout and semantics

| Stage | Description | Status |
| --- | --- | --- |
| 1.1 | Pick platform-aware user config path/filename (e.g., `overlay_groupings.user.json` in the EDMC app data root) and confirm separation from the shipped file. | Complete |
| 1.2 | Define merge precedence and schema rules for defaults + user overlay (per-plugin/group overlay, user-only entries, fallback behavior). | Complete |
| 1.3 | Decide how to represent deletions/disablement (e.g., `disabled` flag or null semantics) vs. always inheriting defaults. | Complete |
| 1.4 | Document reload/watch expectations across shipped/user files and what “no user file” means; note error-handling/logging stance. | Complete |

- Stage 1.1 Plan:
  - Keep user config in the plugin root alongside the shipped file, named `overlay_groupings.user.json` (mirrors shipped name, avoids collisions).
  - Enforce separation despite co-location: shipped file `overlay_groupings.json` can be overwritten on upgrade; user file must be ignored by installers and is the controller write target.
  - Define path resolution order with plugin-root default: explicit override (env/CLI) > plugin root default. Log a warning if an override points elsewhere but allow it for tests/tools; never silently fall back to shipped file for writes.
  - Document the chosen path/override rules in `docs/developer.md` once finalized so plugin authors know where to read/write.
  - Risks/Mitigations:
    - Override misuse: validate override path exists/writable before use; warn clearly and reject dangerous locations; do not silently redirect.
    - Silent clobber by installers: update installers to skip `overlay_groupings.user.json`; add a preservation check in packaging/tests.
    - Fallback mistakes: centralize writes through a helper that only targets the user file; raise/log on failure instead of writing to the shipped file; add unit tests to assert writes never hit `overlay_groupings.json`.
    - Permission/RO installs: detect read-only plugin root early; surface a clear error and suggest override path usage; avoid silent failure.
    - Divergent copies: log the active user-config path at startup and expose it in diagnostics/UI; warn when override path differs from plugin root; document rules in `developer.md`.
  - Output for 1.1: written decision on path/filename, override knobs (env/CLI), co-location rules, and fallback behaviors recorded in this doc; status stays open until documented.

#### Stage 1.1 Decisions (user config path)
- Default location: plugin root, filename `overlay_groupings.user.json` (co-located with shipped `overlay_groupings.json`).
- Overrides: allow an env var `MODERN_OVERLAY_USER_GROUPINGS_PATH` and a CLI flag `--user-groupings-path` (for tooling/tests) to point elsewhere; warn if override is outside plugin root but honor it for tests/tools.
- Writes: controller and helpers write only to the user file; never redirect writes to the shipped file. If override path is invalid/unwritable, surface an error instead of falling back to the shipped file.
- Reads: loader uses shipped file as base plus user file overlay when present; if user file is absent/unreadable, treat as “no overrides” and log at warn/debug.
- Installers: must skip `overlay_groupings.user.json` during upgrades; add a check in install scripts to preserve it.
- Docs: capture these rules in `docs/developer.md` when wiring the feature so plugin authors know the active paths and override knobs.

#### Stage 1.2 Plan (merge precedence and schema rules)
- Merge precedence: shipped defaults as base; user entries overlay per plugin/group; user values win per field; user-only plugins/groups are allowed.
- Schema: reuse existing `overlay_groupings.json` schema for user file; allow optional `disabled` flag per plugin/group if we support hiding defaults (decide in 1.3).
- Field merge rules: per plugin, merge `matchingPrefixes`, `idPrefixGroups` entries by key; per group, override offsets/anchors/justification/prefix lists when provided, otherwise inherit defaults.
- Validation: ignore malformed entries with warnings; keep merge tolerant (skip bad entries instead of failing all).
- Justification/anchors/prefix casing: normalize the same way as API does (lowercase/casefold) to keep behavior consistent.
- Output for 1.2: documented merge algorithm (precedence, per-field behavior, error handling) in this doc; ready to drive loader implementation.
  - Risks/Mitigations:
    - Delete/disable semantics: decide on explicit `disabled` flag (or require user-side removal only) and document; treat absent flag as inherit; add tests for enable/disable edges.
    - Merge precedence confusion: specify per-field replace/merge rules in the doc/dev guide; implement deterministically; cover with unit tests.
    - Malformed user entries: tolerate/skip bad nodes with clear warnings; keep the rest of the merge intact; validate schema and add tests for bad types/JSON.
    - Normalization drift: reuse the same normalization helpers as `define_plugin_group()` for casefold/anchors/justification; test casing/anchor behaviors.
    - Prefix collisions: enforce uniqueness per plugin/group; on conflict, log and pick a deterministic winner (e.g., user last-wins); add collision tests.
    - Performance/reload churn: cache parsed files and mtimes; debounce reload; rate-limit warnings; fall back to last-good merged view on merge failure.
  - Unit tests to add:
    - Merge precedence: user overrides win per field; defaults inherited when absent.
    - User-only plugins/groups are preserved and surfaced.
    - `disabled` semantics (once decided) hide defaults and re-enable correctly.
    - Malformed entries are skipped with warnings; good entries still merge.
    - Normalization (casefolded prefixes/anchors/justification) matches `define_plugin_group()` behavior.
    - Prefix collision handling is deterministic (e.g., user last-wins) and logged.
    - Reload/merge caching respects mtimes and debounces warnings.

#### Stage 1.2 Decisions (merge semantics)
- Base + overlay: load shipped `overlay_groupings.json` as the base; overlay `overlay_groupings.user.json` per plugin/group; user values win per field.
- Plugin-level: if user defines `matchingPrefixes`, replace the shipped list; otherwise inherit shipped. User-only plugins are allowed and kept as-is.
- Group-level: merge `idPrefixGroups` by key. For an existing group, user-specified fields replace shipped ones (`idPrefixes`, `idPrefixGroupAnchor`, `offsetX/Y`, `payloadJustification`). Omitted fields inherit shipped values. User-only groups are allowed.
- `idPrefixes`: user list replaces shipped list for that group; normalization matches API (casefold/strip, parse objects).
- Normalization: reuse API normalization for prefixes/anchors/justification to avoid drift; enforce consistent casing.
- Error handling: if user file is malformed or a node is invalid, log a warning, skip the bad node, and continue merging the rest; keep last-good merged view available.
- Disable semantics: not enabled yet—defaults always inherit unless overridden. Decision on `disabled` flag deferred to Stage 1.3.
- Tests: cover precedence, user-only entries, normalization parity, collision handling (user last-wins per group), malformed-entry tolerance, and mtime/debounce behaviors when implemented.

#### Stage 1.3 Plan (disable/hide semantics)
- Goal: decide whether and how users can hide shipped plugins/groups.
- Options to evaluate:
  - `disabled` flag at plugin and/or group level in user file to suppress shipped entries.
  - Explicit null/empty sentinel to indicate “drop this entry”.
  - No disable support (always inherit unless overridden).
- Decision criteria:
  - Minimal schema impact (prefer a single boolean flag).
  - Backward compatibility with existing JSON/schema.
  - Clear merge behavior (disabled beats shipped, reversible by removing flag).
- Proposed behavior (for evaluation): support `disabled: true` in user file at plugin/group scope to remove that entry from the merged view; removing the flag re-enables inheritance.
- Error handling: invalid types for `disabled` are warned and ignored; no silent drop.
- Tests to add: disabled plugin removes plugin; disabled group removes group while others remain; disabled + overrides logs and ignores overrides; removing flag restores defaults; malformed flags ignored.
- Output for 1.3: documented choice (enable/disable semantics), per-scope behavior, merge precedence, and test checklist; ready to wire into merge helper.
  - Risks/Mitigations:
    - Ambiguity: define explicit scopes (plugin-level and group-level) and document; no cross-scope side effects.
    - Schema drift: add `disabled` to schema/validators; warn on unknown/invalid types without applying them.
    - Merge conflicts: `disabled` wins over overrides at that scope; if both are present, ignore overrides and log.
    - Reversibility: removing `disabled` restores inheritance; consider helper/CLI to clear flags; document reversal path.
    - Error handling: reject non-boolean `disabled` with warnings; do not drop entries on bad types.
    - Observability: log when entries are skipped due to `disabled`; expose active state/path in diagnostics/UI.
    - Compatibility: note that older clients ignore `disabled`; prefer merged loader usage to enforce consistency; feature-flag if needed.

#### Stage 1.3 Decisions (disable/hide semantics)
- Semantics: support `disabled: true` in the user file at plugin and group scope to hide shipped entries for that scope. Removing the flag restores inheritance of shipped defaults.
- Precedence: `disabled` wins over other overrides at the same scope; if both `disabled` and overrides are present, ignore overrides and log.
- Scope: no cross-scope effects—disabling a group does not disable the plugin; disabling a plugin hides all its groups.
- Validation: `disabled` must be boolean; invalid types are warned and ignored (entry remains enabled/inherited).
- Observability: log when entries are skipped due to `disabled`; include active paths/state in diagnostics/UI.
- Tests: cover plugin/group disable, disable+overrides ignored with logging, restoration when flag removed, malformed flag ignored.

#### Stage 1.4 Plan (reload/watch expectations and error handling)
- Goal: document how reloads/watchers should behave when either file changes and what “no user file” means.
- Reload triggers: watchers/mtime checks must consider both shipped and user files; any change triggers merge reload (debounced).
- Fallback behavior: if user file is missing/unreadable, treat as “no overrides” and continue with shipped defaults; log at warn/debug.
- Error handling: on merge failure, keep last-good merged view; log errors and avoid blocking the overlay/controller.
- Observability: log active merged file paths and last reload time; surface in diagnostics/UI where feasible.
- Tests to add: watcher detects user file change; missing user file treated as no overrides; malformed user file triggers warning and falls back to last-good; merge reload uses both mtimes/debouncing.
  - Risks/Mitigations:
    - Missed reloads: watch both shipped and user files; fall back to periodic mtime polling if watch fails; include both mtimes in reload signature.
    - Reload thrash: debounce reloads; coalesce multiple mtime changes; consider checksum compare to avoid reload on identical content.
    - Last-good drift: on merge failure, keep last-good merged view and log with path; expose “stale since” in diagnostics.
    - Warning spam: rate-limit warnings for repeated parse failures; only re-emit after content/mtime change.
    - Inconsistent paths: log active paths and last reload time; show current paths in diagnostics/UI.
    - Blocking failures: wrap IO/JSON parse in try/except; on error, skip reload and keep watcher loop alive.
  - Unit tests to add:
    - Shipped file change triggers reload (combined mtime/signature).
    - User file change triggers reload (combined mtime/signature).
    - Debounce/coalesce: rapid successive writes produce a single reload within debounce window.
    - Missing/unreadable user file treated as no overrides with warning, no crash.
    - Malformed user file warns and falls back to last-good; watcher loop continues.
    - Recovery: after a parse failure, a subsequent valid user file restores merged view.
    - Warning rate limit: repeated malformed user file does not spam logs until content/mtime changes.
    - Diagnostics: active paths and last reload time are exposed (e.g., in logs/UI) and updated on reload.

#### Stage 1.4 Decisions (reload/watch/error handling)
- Triggers: consider both shipped and user files; any mtime/size change triggers reload (debounced/coalesced). Fallback to periodic mtime polling if watch isn’t available.
- No user file: treat as “no overrides”; proceed with shipped defaults; log at warn/debug.
- Error path: on read/parse/merge failure, keep last-good merged view, mark stale, log path + error; recover on next valid read.
- Observability: log active shipped/user paths and last reload time; expose via diagnostics/UI where feasible; rate-limit repeated warnings.
- Debounce: coalesce rapid changes; use combined mtime/signature to avoid redundant reloads; rate-limit warnings for repeated malformed content until mtime/content changes.

- Choose the user-config path (per-EDMC app data dir, platform-aware) distinct from the plugin directory. File name proposal: `overlay_groupings.user.json`.
- Merge strategy: load shipped defaults as base, apply user file as an overlay (per-plugin key), allowing user-only plugins/groups and per-group overrides of offsets/anchors/justification/prefix lists. User values win per field; absent fields fall back to defaults.
- Define how to treat deletions: consider a `disabled` flag or explicit nulls if we need to support “hide default group”; otherwise, keep defaults unless overridden.
- Document reload expectations: watcher/mtime checks should consider both files; missing/empty user file means “no overrides”.

### Phase 2: Loader + writer changes

| Stage | Description | Status |
| --- | --- | --- |
| 2.1 | Implement shared loader/merger module returning merged view + raw/default/user paths with mtime/cache, normalization, `disabled` handling, and last-good fallback. | Complete |
| 2.2 | Wire overlay client to use merged loader for grouping data; ensure reload signals/caches cover both files; surface active paths in diagnostics. | Complete |
| 2.3 | Wire overlay controller to read merged view but write only to user file; keep debounce/reload signaling unchanged; block writes to shipped file. | Complete |
| 2.4 | Plumb env/CLI override support into loader/consumers; keep `define_plugin_group()` behavior unchanged (writes shipped only) and guard against accidental user-file writes. | Complete |

- Stage 2.1 Plan:
  - Build a helper (module/class) to load shipped + user files, merge per 1.2/1.3 rules, normalize via existing API helpers, and expose paths + mtimes + merged view.
  - Include last-good caching and error handling per 1.4; rate-limit warnings; expose diagnostics (paths, last reload, stale status).
  - Keep API surface small: `load()`/`merged()`/`paths()` plus `reload_if_changed()` with combined mtime signature.
  - Risks/Mitigations:
    - Incorrect merges: reuse API normalization; add unit tests for precedence, disabled, collisions, malformed entries.
    - Missed reloads/thrash: use combined mtime signature, debounce reloads, coalesce changes; fallback to polling if watch fails.
    - Stale view: keep last-good merged cache; on failure, log path and stale status; recover on next good read.
    - Warning spam: rate-limit parse/merge warnings; re-emit only on content/mtime change.
    - Path confusion: expose active shipped/user paths and last reload via helper diagnostics; log overrides.
    - API sprawl: keep surface minimal; document methods and expected behaviors for consumers.
- Unit tests to add:
    - Base+overlay precedence: shipped defaults merged with user overrides; user-only plugins/groups preserved.
    - `disabled` handling: plugin/group disabled hides shipped entry; removing flag restores it; `disabled` + overrides logs and ignores overrides.
    - Normalization parity: prefixes/anchors/justification casefolded like API; parsed `idPrefixes` respected.
    - Malformed inputs: bad user JSON or wrong types are warned, skipped, and merge continues using last-good.
    - Collision handling: duplicate prefixes/groups resolve deterministically (user last-wins) with a log.
    - Last-good cache: on parse failure, merged view stays at last-good/stale; next good file restores.
    - Reload trigger logic: combined mtime/signature changes cause reload; rapid successive changes are debounced/coalesced.
    - Override paths: env/CLI override honored; active paths surfaced in diagnostics/logs.

## Stage 2.2 Plan (client wiring)
- Goal: overlay client uses the shared loader for grouping data; reloads/caches reflect shipped+user files; diagnostics show active paths.
- Tasks:
  - Inject GroupingsLoader into the client setup (pointed at plugin-root shipped/user paths, honoring env/CLI override).
  - Replace direct reads of `overlay_groupings.json` with loader.merged() in grouping helper/override manager entry.
  - Ensure reload signals/mtime checks consider both files via loader.reload_if_changed(); coalesce into existing reload hooks.
  - Surface active paths/last reload/stale flag in client diagnostics/logs.
- Risks/Mitigations:
  - Missed reloads: always call loader.reload_if_changed() where we previously polled; include both files’ mtimes.
  - Stale cache: if merge fails, ensure client keeps last-good and warns; do not crash rendering.
  - Override path misuse: log active paths and warn on overrides outside plugin root; keep writes targeting user file only.
  - Regression in grouping parsing: reuse existing adapter/override manager flows; add focused tests to catch differences.
  - Performance: avoid excessive reload calls; reuse loader’s debounce/signature.
- Unit tests to add:
  - Client uses merged view (user overrides reflected, user-only group present).
  - Disabled entries respected in client view.
  - reload_if_changed() picks up user file change and triggers refresh hook.
  - Malformed user file keeps last-good view and logs (no crash).
  - Diagnostics expose active paths/last reload/stale status.

#### Stage 2.2 Decisions (client wiring)
- Loader injected into client setup: GroupingsLoader created at startup with plugin-root shipped/user paths; paths logged.
- PluginOverrideManager now accepts optional loader and uses it for reload/merge; last-good/stale handling preserved.
- Grouping data in client now comes from merged view via loader-backed override manager; direct file reads replaced.
- Diagnostics: loader paths logged at startup; diagnostics available via loader/manager.
- Tests: added `tests/test_plugin_override_loader.py` covering loader-fed override manager (user overrides and user-only plugins); existing loader tests cover merge/reload/error paths.

## Stage 2.3 Plan (controller wiring)
- Goal: overlay controller reads merged groupings via shared loader; writes continue to target user file only; reload signaling unchanged.
- Tasks:
  - Instantiate GroupingsLoader in controller with shipped/user paths (honoring env/CLI override) and log paths.
  - Replace controller reads of `overlay_groupings.json` with loader.merged(); ensure dropdown/options use merged view.
  - Ensure controller write path updates only the user file (`overlay_groupings.user.json`), never the shipped file.
  - Hook reload/poll to use loader.reload_if_changed(); keep debounce; surface diagnostics (paths/last reload/stale).
- Risks/Mitigations:
  - Accidental writes to shipped file: guard write path to user file only; add checks/tests; log target path.
  - Missed reloads: use loader.reload_if_changed() in poll; include both files’ mtimes; fallback to last-good on error.
  - Stale/failed merge: keep last-good view and warn; do not crash UI; allow recovery on next good read.
  - Override misuse: warn when override path outside plugin root; log active paths.
  - Performance: debounce reload checks; reuse loader signature; avoid UI churn on unchanged content.
- Unit tests to add:
  - Controller uses merged view (user overrides/user-only groups appear in options/cache filter).
  - Disabled entries hidden in controller view.
  - Writes go to user file only; shipped file unchanged after controller edits.
  - Reload poll picks up user file change via loader.reload_if_changed().
  - Malformed user file keeps last-good view with warning; UI remains responsive.
  - Diagnostics/logs expose active paths/last reload/stale status.

#### Stage 2.3 Decisions (controller wiring)
- Loader: controller now creates `GroupingsLoader` with shipped/user paths (env override supported) and logs paths.
- Read path: controller `_load_idprefix_options` pulls merged view via loader (with reload_if_changed and last-good fallback).
- Write path: controller writes configs to user file only (`overlay_groupings.user.json`); shipped file remains untouched.
- Polling: status/cache poll calls loader.reload_if_changed() and refreshes options on change; cache polling unchanged.
- Diagnostics: paths logged at startup; stale/last reload available via loader diagnostics (hooked via logging).
- Tests: added `overlay_controller/tests/test_controller_groupings_loader.py` covering merged view (user-only groups) and user-only write path.

## Stage 2.4 Plan (override plumbing and API guardrails)
- Goal: ensure env/CLI overrides are plumbed consistently across loader consumers; `define_plugin_group()` keeps writing shipped file; guard against accidental writes to wrong file.
- Tasks:
  - Expose/propagate env var `MODERN_OVERLAY_USER_GROUPINGS_PATH` and CLI flag `--user-groupings-path` to loader consumers (client, controller, CLI tools).
  - Ensure diagnostics/logging surface active paths and overrides.
  - Keep `define_plugin_group()` targeting shipped file; add guardrails to prevent it from being pointed to user file.
  - Add a small helper for path resolution to avoid duplication.
- Risks/Mitigations:
  - Inconsistent override handling: centralize path resolution helper; unit tests for env/CLI precedence across components.
  - Accidental user-file writes from API: assert/guard in register_grouping_store/define_plugin_group to use shipped path; document.
  - Confusing diagnostics: log active paths/override source in client/controller; expose via diagnostics for support.
  - CLI flag misuse: validate override path is writable; warn on dangerous locations; fall back to error rather than writing elsewhere.
- Unit tests to add:
  - Env/CLI override respected in client/controller loader instantiation (paths exposed in diagnostics/logs).
  - `define_plugin_group()` continues to write shipped file even when override set.
  - Path resolution helper precedence: CLI > env > default; invalid override errors rather than falling back silently.
  - Guard prevents API from writing to user file when invoked via define_plugin_group/register_grouping_store.

#### Stage 2.4 Decisions (override plumbing)
- Env override: client and controller accept `MODERN_OVERLAY_USER_GROUPINGS_PATH` for user file path; paths logged when loader is created.
- CLI: plugin_group_cli accepts env `MODERN_OVERLAY_GROUPINGS_PATH` and CLI `--groupings-path` to override target path (default shipped).
- Guardrails: `register_grouping_store` rejects `overlay_groupings.user.json` and warns on unexpected filenames, keeping `define_plugin_group()` on shipped file.
- Diagnostics: loaders log shipped/user paths at startup; manager/loader diagnostics expose paths and reload state.
- Tests: added guard in `tests/test_overlay_api.py`; loader/controller/client tests already cover merged views and loader-fed override manager.

#### Stage 2.1 Decisions (loader/merger design)
- Helper: create a shared loader module/class that loads shipped + user files, merges per 1.2/1.3 (user overlay wins, `disabled` supported), and exposes `load()`, `merged()`, `paths()`, and `reload_if_changed()` with combined mtime signature.
- Normalization: reuse existing API normalization for prefixes/anchors/justification and `idPrefixes` parsing to avoid drift.
- Caching/error handling: maintain last-good merged view; on parse/IO failure log path and mark stale, keep last-good, and recover on next good read; rate-limit warnings.
- Diagnostics: expose active shipped/user paths and last reload time/stale status for logs/UI; log when overrides are in effect.
- Overrides: honor env/CLI override for user path; default to plugin-root `overlay_groupings.user.json`; never redirect writes to shipped file.
- Debounce: coalesce rapid mtime changes; combined mtime/signature used to detect changes; fallback to polling if watch unavailable.
- Stage 2.2 Plan:
  - Replace client direct reads with the helper; ensure grouping caches/reload signals observe both files.
  - Surface active shipped/user paths and last reload in client diagnostics/logs.
- Stage 2.3 Plan:
  - Controller reads merged view via helper; writes go only to user file path; debounce/reload signals unchanged.
  - Add guardrails to prevent controller from touching shipped file even if overrides change paths.
- Stage 2.4 Plan:
  - Wire env var/CLI override (`MODERN_OVERLAY_USER_GROUPINGS_PATH`/`--user-groupings-path`) into loader/consumers.
  - Keep `define_plugin_group()` pointed at shipped file; ensure overrides do not alter its target; add defensive checks/logging.

### Phase 3: Migration/backfill
- On first run after the feature lands, if the user file is absent but the shipped file differs from the packaged baseline (or contains user edits), copy those entries into the user file once. Provide a conservative heuristic (hash/mtime or a simple “if no user file, clone current shipped contents once” guard).
- Handle malformed user/shipped files by logging and skipping migration rather than blocking startup; prefer leaving user data intact over overwriting.
- Consider a one-shot CLI/utility (optional) to force re-migration or to export/import user overrides for support scenarios.

### Phase 4: Tests + docs
- Tests: unit coverage for merge helper (override precedence, user-only groups, missing fields), controller write path targeting user file, and `define_plugin_group()` remaining unchanged. Add integration-style tests around reload signals if they depend on mtime.
- Docs: update `docs/overlay-groupings.md` (or a short addendum) to explain the layered config, file locations, and how to reset/override defaults. Mention migration behavior in release notes.
- Manual checks: start plugin, tweak placements via controller, verify user file captures changes and upgrades to shipped defaults preserve user overrides.
