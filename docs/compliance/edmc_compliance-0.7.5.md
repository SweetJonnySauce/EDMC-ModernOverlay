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
- Confirm target Python version matches the version stated in EDMC core `docs/Releasing`; baseline (as of this review) is Python 3.10.3 32-bit for Windows builds. Update this file if the baseline changes. This applies to the EDMC plugin runtime; the controller/client run in their own environments.
- Run `python scripts/check_edmc_python.py` to enforce the plugin baseline in `docs/compliance/edmc_python_version.txt` (override with `ALLOW_EDMC_PYTHON_MISMATCH=1` only for non-release/dev work).
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
| Stay aligned with EDMC core (PLUGINS.md:12/24/297/41) | Yes | Baseline pinned at `docs/compliance/edmc_python_version.txt` (3.10.3 32-bit) and enforced by `scripts/check_edmc_python.py`; plugin ships as `EDMCModernOverlay/` with `plugin_start3` entrypoint (load.py:2892); EDMC release/discussion review captured in `.github/pull_request_template.md`. |
| Use only supported plugin API/helpers (PLUGINS.md:74/85/113/128/156/452) | Yes | Journal handling gates on `monitor.game_running()`/`monitor.is_live_galaxy()` (load.py:528-559); release checks create HTTP sessions via `timeout_session.new_session`/`config.user_agent` and respect `config.debug_senders` (overlay_plugin/version_helper.py:148-199); settings use namespaced `config` keys with `overlay_settings.json` shadowing for the external client (overlay_plugin/preferences.py:17-199). |
| Logging/versioning patterns (PLUGINS.md:168/212/230/263) | Yes | Logger/tag `EDMCModernOverlay` matches the release folder; `_EDMCLogHandler` forwards through EDMC’s log level and uses `exc_info` for tracebacks (load.py:259-299); EDMC `appversion` gates helper selection for HTTP sessions (overlay_plugin/version_helper.py:82-165). |
| Responsive & Tk-safe runtime (PLUGINS.md:335/349/362/397/599) | Yes | Long-running work runs on threads (prefs worker, version check, broadcaster, watchdog, config rebroadcast timers) and network I/O uses `requests` via helpers; Tk touches are limited to `plugin_prefs`/`prefs_changed` on the main thread (load.py:2915-3040). |
| Prefs/UI hooks (PLUGINS.md:417/452/455/530/585/587) | Yes | `plugin_prefs` builds a `myNotebook` frame with callbacks for overlay controls, and `prefs_changed` saves via the panel (load.py:2915-3040); config keys are prefixed with `edmc_modern_overlay.*` and persisted via EDMC config plus a JSON shadow (overlay_plugin/preferences.py:17-199). |
| Dependencies & HTTP debug (PLUGINS.md:1323/1346/1358/1378/1387/1391) | Yes | Plugin folder is importable (`EDMCModernOverlay/`); installers build `overlay_client/.venv` from `overlay_client/requirements.txt` and reuse it; HTTP debug routing honours `config.debug_senders` and user-agent plumbing for release checks (overlay_plugin/version_helper.py:148-199). |

## Exceptions
- None for 0.7.5; local `.disabled` suffix only reflects an intentionally disabled install, while releases ship as `EDMCModernOverlay/`.

## Key gaps to address (ordered by importance)
- None outstanding for 0.7.5. Keep monitoring EDMC Releases/Discussions and rerun these checks ahead of the next release.
