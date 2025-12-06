# Controller Log Level Override

To stabilize `test_controller_log_level_hint.py`, the overlay controller now exposes a test-only hook `set_log_level_hint(value: Optional[int], name: Optional[str])`. This lets tests drive the controller logger without tearing down and re-importing the whole package, eliminating repeated `sys.modules` churn.

## Behaviour
- `_ensure_controller_logger()` checks for an override first, then falls back to the environment hint (exported from the plugin), and finally to the default (DEBUG in dev mode, INFO otherwise).
- `set_log_level_hint()` clears `_CONTROLLER_LOGGER` so the next `_ensure_controller_logger()` call rebuilds the logger with the override.

## Test rewrite
- The controller log-level tests now import `overlay_controller.overlay_controller` once and call `set_log_level_hint()` directly instead of manipulating `sys.modules`. Each test resets the hint before/after via a fixture.

This approach keeps the tests deterministic and avoids flakiness from re-importing packages mid-run.
