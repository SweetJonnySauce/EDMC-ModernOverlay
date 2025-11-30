# EDMC Compliance Tracker

This file tracks adherence to EDMC’s plugin best practices for the Modern Overlay project. Use it to preserve context about gaps, decisions, and verification steps so we can keep the plugin aligned with EDMC core expectations across releases.

## Compliance rules
These are EDMC best practices. Evaluate the code to make sure it's adhering to these best practices. For each item give me a clear yes or no type answer. If the answer is no, say why and what needs to change. PLUGINS.md refers to https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md
- Stay aligned with EDMC core: check the tested Python version in docs/Releasing before coding (PLUGINS.md:12), keep every plugin in its own directory with a load.py file (PLUGINS.md:24), implement plugin_start3 as the entry point (PLUGINS.md:297), and watch GitHub releases/discussions so you learn about plugin-impacting changes early (PLUGINS.md:41).
- Use only the supported plugin API and helpers: limit imports to the documented modules such as config, theme, monitor, timeout_session, etc. (PLUGINS.md:74), rely on helpers like monitor.game_running()/monitor.is_live_galaxy() to detect player state instead of reimplementing detection (PLUGINS.md:113), and create HTTP sessions via timeout_session.new_session or at least apply config.user_agent so your requests inherit EDMC’s defaults (PLUGINS.md:128). Persist plugin settings with config.set/get_* and namespaced keys plus share common assets through utilities like plugins/common_coreutils.py to avoid collisions or circular imports (PLUGINS.md:85) (PLUGINS.md:452) (PLUGINS.md:156). Note: The overlay client uses overlay_settings.json since it runs outside the EDMC environment. Settings are managed within EDMC for compatibility and replicated to the settings file.
- Adopt EDMC’s logging/versioning patterns: initialize a logging logger using the plugin directory name and drop print in favor of logger.info/debug/... so messages flow through EDMC’s handlers (PLUGINS.md:168). Keeping plugin_name identical to the folder name ensures the logger wiring works (PLUGINS.md:212), while logger.exception/logger.debug(..., exc_info=e) should be used for tracebacks (PLUGINS.md:230). Gate version-specific behavior with config.appversion so you stay compatible across releases (PLUGINS.md:263).
- Keep runtime work responsive and Tk-safe: offload any long-running or network-bound task to a worker thread because every hook is invoked on the Tk main loop (PLUGINS.md:335) (PLUGINS.md:599). Only touch Tk widgets on the main thread, use event_generate sparingly, never trigger it while shutting down, and treat config.shutting_down as a property to avoid hangs (PLUGINS.md:349) (PLUGINS.md:362) (PLUGINS.md:371). Use requests (ideally through timeout_session) instead of urllib to benefit from the bundled CA store and consistent timeout behavior (PLUGINS.md:397).
- Integrate with EDMC’s prefs/UI hooks: build settings tabs with plugin_prefs/prefs_changed, using myNotebook widgets, config.get_int/str/bool/list, locale-aware helpers like number_from_string, and plugin-specific prefixes for keys (PLUGINS.md:417) (PLUGINS.md:455) (PLUGINS.md:452). Return widgets or frames from plugin_app, update their look via Tk/theming helpers, and ensure all UI manipulation stays on the main thread (PLUGINS.md:530) (PLUGINS.md:585) (PLUGINS.md:587).
- Package dependencies and debug HTTP responsibly: develop inside a Python virtual environment so you know which modules must be bundled with the plugin, then copy any third-party packages from site-packages into your plugin directory when needed (PLUGINS.md:1323) (PLUGINS.md:1346). Name the plugin directory so it’s importable (no hyphens or dots) and verify imports through that namespace (PLUGINS.md:1358) (PLUGINS.md:1378). When troubleshooting network calls, respect config.debug_senders and redirect traffic to the built-in debug webserver to capture requests safely (PLUGINS.md:1387) (PLUGINS.md:1391).

## Guiding traits for EDMC plugins
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

## Checks (run per release or compliance review)
- Confirm target Python version matches the version stated in EDMC core `docs/Releasing`; baseline (as of this review) is Python 3.10.3 32-bit for Windows builds. Update this file if the baseline changes.
- Run `python scripts/check_edmc_python.py` to enforce the baseline in `docs/compliance/edmc_python_version.txt` (override with `ALLOW_EDMC_PYTHON_MISMATCH=1` only for non-release/dev work).
  - CI runs this via `.github/workflows/ci.yml` (override enabled because CI uses non-baseline Python/arch).
- Re-scan imports to ensure only supported EDMC APIs/helpers (`config`, `monitor`, `theme`, `timeout_session`, etc.) are used in plugin code.
- Verify logger wiring (`plugin_name`, folder name, logger name) aligns and that `logger.exception`/`exc_info` is used instead of `print`.
- Confirm long-running or network work runs in worker threads and that Tk widgets are only touched on the main thread.
- Review prefs/UI hooks (`plugin_prefs`, `prefs_changed`, `plugin_app`) for correct `myNotebook` usage and namespaced `config.get/set` keys.
- Validate dependency handling: venv for bundled packages, copied dependencies when needed, and debug HTTP routing via `config.debug_senders`.
- Monitor EDMC releases/discussions: subscribe to `EDCD/EDMarketConnector` GitHub Releases and Discussions; check weekly and before shipping a plugin release, logging any plugin-impacting changes here.
  - PRs must tick the compliance items in `.github/pull_request_template.md`.

## Current compliance assessment

| Item | Status | Notes/Actions |
| --- | --- | --- |
| Stay aligned with EDMC core (PLUGINS.md:12/24/297/41) | Yes | Baseline pinned and enforced via `docs/compliance/edmc_python_version.txt` + `scripts/check_edmc_python.py`; release monitoring documented and added to PR checklist. |
| Use only supported plugin API/helpers (PLUGINS.md:74/85/113/128/156/452) | Yes | Player-state handling now gates journal processing on `monitor.game_running()`/`monitor.is_live_galaxy()` with state resets; settings use namespaced `config` keys and `overlay_settings.json` shadowing is documented/intentional. |
| Logging/versioning patterns (PLUGINS.md:168/212/230/263) | No | `PLUGIN_NAME`/`plugin_name` use `EDMCModernOverlay` while the folder is `EDMCModernOverlayDev`; align the directory and naming so logger wiring matches EDMC expectations. |
| Responsive & Tk-safe runtime (PLUGINS.md:335/349/362/397/599) | Yes | Long-running work is threaded (watchdog, broadcaster, prefs worker, version check); Tk is untouched off the main thread; networking uses `requests`/`timeout_session`. |
| Prefs/UI hooks (PLUGINS.md:417/452/455/530/585/587) | Yes | `plugin_prefs`/`prefs_changed` implemented; UI built with `myNotebook`; settings namespaced via `config` with `overlay_settings.json` shadow for the external client. |
| Dependencies & HTTP debug (PLUGINS.md:1323/1346/1358/1378/1387/1391) | Yes | Plugin is importable; overlay dependencies isolated under `overlay_client/.venv`; HTTP debug respects `config.debug_senders`; third-party packaging handled via venv copy guidance. |

## Exceptions
- The working directory is `EDMCModernOverlayDev` while `PLUGIN_NAME`/`plugin_name` remain `EDMCModernOverlay`. This mismatch is acceptable during active development; the naming should be realigned before shipping a release.

## Key gaps to address (ordered by importance)
- **A. Core alignment and release monitoring**

  | Stage | Description | Status |
  | --- | --- | --- |
  | 1 | Document the EDMC-tested Python version (from EDMC `docs/Releasing`) and add a lightweight check/reminder in docs/tooling so coding/testing follows that baseline. | Complete (baseline recorded: Python 3.10.3 32-bit; enforced via `scripts/check_edmc_python.py` and `docs/compliance/edmc_python_version.txt`) |
  | 2 | Document the process for monitoring EDMC releases/discussions for plugin-impacting changes (who watches, where, and how updates are captured here). | Complete (process documented; reinforced via PR checklist to confirm EDMC Releases/Discussions were reviewed) |

- **B. Supported API usage**

  | Stage | Description | Status |
  | --- | --- | --- |
  | 3 | Replace manual game-state tracking in `load.py:428-473` with EDMC `monitor.game_running()`/`monitor.is_live_galaxy()` helpers (or gate logic with them) to align with PLUGINS.md guidance. | Complete (monitor helpers gate journal handling; non-live galaxy resets state) |
  | 3.1 | Import `monitor.game_running`/`monitor.is_live_galaxy` in `load.py` and gate journal handling so early returns occur when EDMC reports the game not running. | Complete (helpers imported with fallbacks; `handle_journal` now returns early when `game_running()` is False) |
  | 3.2 | Use `is_live_galaxy()` to suppress/bounds payloads when not in live galaxy (e.g., main menu), updating `_state` resets accordingly. | Complete (handle_journal now early-returns when `is_live_galaxy()` is False and clears system/station/docked state) |
  | 3.3 | Retain journal-derived cache only as a supplement; ensure broadcasts/logging note monitor gating and add a brief comment referencing PLUGINS.md:113. | Complete (comment added in `handle_journal` explaining monitor gating per PLUGINS.md:113; journal cache remains supplemental) |
  | 3.4 | Add/update tests or manual verification notes to confirm monitor gating works and doesn’t break journal-driven state updates. | Complete (manual verification plan: with EDMC running at main menu, confirm no overlay broadcasts/state updates; in-live galaxy, confirm state updates and broadcasts resume) |

- **C. Naming consistency for logging**

  | Stage | Description | Status |
  | --- | --- | --- |
  | 4 | Align plugin folder name with `PLUGIN_NAME`/`plugin_name` (`EDMCModernOverlayDev` vs `EDMCModernOverlay`) so logger wiring matches EDMC expectations and avoids handler mismatches. | Accepted (covered by active development exception; revisit before release) |
