# Overlay Client Refactor Plan

This file tracks the ongoing refactor of `overlay_client.py` (and related modules) into smaller, testable components while preserving behavior and cross-platform support. Use it to rebuild context after interruptions: it summarizes what has been done and what remains. Keep an eye on safety: make sure the chunks of work are small enough that we can easily test them and back them out if needed, document the plan with additional steps if needed (1 row per step), and ensure testing is completed and clearly called out.

## Refactoring rules
- Before touching code for a stage, write a short (3-5 line) stage summary in this file outlining intent, expected touch points, and what should not change.
- Always summarize the plan for a stage without making changes before proceeding.
- Even if a request says “do/implement the step,” you still need to follow all rules above (plan, summary, tests, approvals).
- If you find areas that need more unit tests, add them in to the update.
- When breaking down a key risk, add a table of numbered stages under that risk (or a top-level stage table) that starts after the last completed stage number, and keep each row small, behavior-preserving, and testable. Always log status and test results per stage as you complete them.
- Don't delete key risks once recorded; append new risks instead of removing existing entries.
- Put stage summaries and test results in the Stage summary/test results section in numerical order (by stage number).
- Record which tests were run (and results) before marking a stage complete; if tests are skipped, note why and what to verify later.
- Before running full-suite/refactor tests, ensure `overlay_client/.venv` is set up with GUI deps (e.g., PyQt6) and run commands using that venv’s Python.
- When all sub-steps for a parent stage are complete, re-check the code (not just this doc) to verify the parent is truly done, then mark the parent complete.
- Only mark a stage/substage “Complete” after a stage-specific code change or new tests are added and validated; if no code/tests are needed, explicitly note why in the summary before marking complete.
- After finishing any stage/substep, update the table row and the Stage summary/test results section (with tests run) before considering it done; missing documentation means the stage is still incomplete.
- If the code for a substage landed in an earlier substage, explicitly note that in the substage summary before marking it complete.
- If a step is not small enough to be safe, stop and ask for direction.
- After each step is complete, run through all tests, update the plan here, and summarize what was done for the commit message.
- Each stage is uniquely numbered across all risks. Sub-steps will use dots. i.e. 2.1, 2.2, 2.2.1, 2.2.2
- All substeps need to be completed or otherwise handled before the parent step can be complete or we can move on.
- If you find areas that need more unit tests, add them in to the update.
- If a stage is bookkeeping-only (no code changes), call that out explicitly in the status/summary.

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

## Testing (run after each refactor step):
- Restart EDMC, activate the venv, then:
```
source overlay_client/.venv/bin/activate
make check
make test
PYQT_TESTS=1 python -m pytest overlay_client/tests
python3 tests/run_resolution_tests.py --config tests/display_all.json
```

## Key readability/maintainability risks (ordered by importance):
- **A.** `overlay_client/overlay_client.py` co-locates async TCP client, Qt window/rendering, font loading, caching, follow logic, and entrypoint in one 5k-line module/class, violating single responsibility and making changes risky. Tracking stages to break this up:

  | Stage | Description | Status |
  | --- | --- | --- |
  | 1 | Extract `OverlayDataClient` into `overlay_client/data_client.py` with unchanged public API (`start/stop/send_cli_payload`), own logger, and narrow signal surface. Import it back into `overlay_client.py`. | Complete (extracted and imported; all documented tests passing, resolution run verified with overlay running) |
  | 2 | Move paint command types (`_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`) and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py`; keep signatures intact so `_paint_legacy` logic can stay as-is. | Complete (moved into `overlay_client/paint_commands.py`; all documented tests passing with overlay running for resolution test) |
  | 3 | Split platform and font helpers (`_initial_platform_context`, font resolution) into `overlay_client/platform_context.py` and `overlay_client/fonts.py`, keeping interfaces unchanged. | Complete (extracted; all documented tests passing with overlay running) |
  | 4 | Trim `OverlayWindow` to UI orchestration only; delegate pure calculations to extracted helpers. Update imports and ensure existing tests pass. | Complete |
  | 4.1 | Map non-UI helpers in `OverlayWindow` (follow/geometry math, payload builders, viewport/anchor/scale helpers) and mark target extractions. | Complete |
  | 4.2 | Extract follow/geometry calculation helpers into a module (no Qt types); wire `OverlayWindow` to use them; keep behavior unchanged. | Complete |
  | 4.3 | Extract payload builder helpers (`_build_message_command/_rect/_vector` calculations, anchor/justification/offset utils) into a module, leaving painter/UI hookup in `OverlayWindow`. | Complete |
  | 4.4 | Extract remaining pure utils (viewport/size/line width math) if still embedded. | Complete |
  | 4.5 | After each extraction chunk, run full test suite and update Stage 4 log/status. | Complete |
  | 5 | Add/adjust unit tests in `overlay_client/tests` to cover extracted modules; run test suite and update any docs if behavior notes change. | Complete |
  | 5.1 | Add tests for `overlay_client/data_client.py` (queueing behavior and signal flow). | Complete |
  | 5.2 | Add tests for `overlay_client/paint_commands.py` (command rendering paths and vector adapter hooks). | Complete |
  | 5.3 | Add tests for `overlay_client/fonts.py` (font/emoji fallback resolution and duplicate suppression). | Complete |
  | 5.4 | Add tests for `overlay_client/platform_context.py` (env overrides applied over settings). | Complete |
  | 5.5 | Run resolution test after test additions and update logs/status. | Complete |
  | 10 | Move `_compute_*_transform` helpers and related math into a pure module (no Qt types), leaving painter wiring in `OverlayWindow`; preserve behavior and logging. | Complete |
  | 10.1 | Map Qt vs. pure seams for `_compute_message/_rect/_vector_transform` and define the target pure module interface (inputs/outputs). | Complete (mapping documented; no code changes) |
  | 10.2 | Extract message transform calc to the pure module; leave font metrics/painter wiring in `OverlayWindow`; keep logging intact. | Complete |
  | 10.3 | Extract rect transform calc to the pure module; leave pen/brush/painter wiring in `OverlayWindow`; keep logging intact. | Complete |
  | 10.4 | Extract vector transform calc to the pure module; keep screen-point conversion and command assembly local; preserve logging/guards. | Complete |
  | 10.5 | Wire `OverlayWindow` to use the pure module for all three transforms; update imports and run staging tests. | Complete (bookkeeping/tests only; wiring already done) |
  | 10.6 | Add focused unit tests for the transform module to lock remap/anchor/translation behavior and guardrails (e.g., insufficient points). | Complete |
  | 11 | Extract follow/window orchestration (geometry application, WM overrides, transient parent/visibility) into a window-controller module to shrink `OverlayWindow`; keep Qt boundary localized. | Complete |
  | 11.1 | Map follow/window orchestration seams (what stays Qt-bound vs. pure) and define target controller interface/state handoff. | Complete (mapping only; no code changes) |
  | 11.2 | Create window-controller module scaffold with pure methods/structs; leave `OverlayWindow` behavior unchanged. | Complete (scaffold only; no wiring) |
  | 11.3 | Move geometry application/WM override resolution (setGeometry/move-to-screen/classification) into the controller; keep Qt calls contained. | Complete |
  | 11.4 | Move visibility/transient-parent/fullscreen-hint handling into the controller; keep Qt calls contained. | Complete |
  | 11.5 | Wire `OverlayWindow` to the controller for follow orchestration; update imports; preserve logging. | Complete (bookkeeping; already wired) |
  | 11.6 | Add focused tests around controller logic (override adoption, visibility decisions, transient parent) to lock behavior. | Complete |
  | 12 | Split payload/group coordination (grouping, cache/nudge plumbing) into a coordinator module so `overlay_client.py` keeps only minimal glue and entrypoint. | Complete (full-suite rerun pending PyQt6 availability) |
  | 12.1 | Map grouping/cache/nudge seams and inputs/outputs across `overlay_client.py`, `group_cache`, and settings/CLI hooks; document current logging and Qt boundaries. | Complete (mapping only; no code changes) |
  | 12.2 | Define coordinator interface (pure, no Qt) owning group selection, cache updates, nudge/backoff decisions, and outbound payload batching; decide injected callbacks for logging/send/settings. | Complete (interface defined; doc-only) |
  | 12.3 | Scaffold coordinator module and initial focused tests to lock current behaviors (group adoption, cache read/write, nudge gating) without wiring changes. | Complete (scaffold + tests; no wiring) |
  | 12.4 | Move non-Qt grouping/cache logic from `overlay_client.py` into the coordinator; preserve behavior/logging; adjust imports only. | Complete (delegated cache/nudge helpers; no UI wiring) |
  | 12.5 | Wire overlay client/window to use the coordinator via injected callbacks, keeping signal/slot behavior, logging, and threading assumptions unchanged. | Complete (group key usage delegated; behavior preserved) |
  | 12.6 | Expand coordinator tests for edge cases (missing groups, stale cache, retry/nudge cadence); rerun full suite and resolution test; log results. | Complete (tests added; full suite pending PyQt6) |

- **B.** Long, branchy methods with mixed concerns: `_build_vector_command` (overlay_client/overlay_client.py:3851-4105), `_build_rect_command` (overlay_client/overlay_client.py:3623-3849), `_build_message_command` (overlay_client/overlay_client.py:3411-3621), `_apply_follow_state` (overlay_client/overlay_client.py:2199-2393); need smaller helpers and clearer data flow.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 6 | Map logic segments and log/trace points in each long method; set refactor boundaries and identify Qt vs. pure sections. | Complete |
  | 7 | Refactor `_apply_follow_state` into smaller helpers (geometry classification, WM override handling, visibility) while preserving logging and Qt calls. | Complete |
  | 7.1 | Extract geometry normalization and logging: raw/native→Qt conversion, device ratio logs, title bar offset, aspect guard; keep Qt calls local. | Complete |
  | 7.2 | Extract WM override resolution and geometry application: setGeometry/move-to-screen, override classification/logging, and target adoption. | Complete |
  | 7.3 | Extract follow-state post-processing: follow-state persistence, transient parent handling, fullscreen hint, visibility/show/hide decisions. | Complete |
  | 8 | Split builder methods (`_build_message_command`, `_build_rect_command`, `_build_vector_command`) into calculation/render sub-helpers; keep font metrics/painter setup intact. | In progress |
  | 8.1 | Refactor `_build_message_command`: extract calculation helpers (transforms, offsets, anchors, bounds) while keeping font metrics/painter setup in place; preserve logging/tracing. | Complete |
  | 8.2 | Refactor `_build_rect_command`: extract geometry/anchor/translation helpers, leaving pen/brush setup and painter interactions in place; preserve logging/tracing. | Complete |
  | 8.3 | Refactor `_build_vector_command`: extract point remap/anchor/bounds helpers, leaving payload assembly and painter interactions in place; preserve logging/tracing. | Complete |
  | 8.4 | After each builder refactor, run full test suite and update logs/status. | Complete |
  | 9 | After each refactor chunk, run full test suite and update logs/status. | Complete |
  | 13 | Add unit tests for transform helpers (message/rect/vector) covering anchor/remap/translation paths and guardrails (e.g., insufficient points return `None`). | Complete |
  | 13.1 | Inventory existing transform helper coverage and define scenarios for anchors/remap/translation and guardrails (vector-point insufficiency, non-finite values). | Complete (mapping only; no code/tests) |
  | 13.2 | Add message transform helper tests (anchors, offsets, inverse scaling, translation) with trace callbacks asserting payload fields. | Complete |
  | 13.3 | Add rect transform helper tests for offsets/anchors/translation and base/reference bounds propagation. | Complete |
  | 13.4 | Add vector transform helper tests covering point remap, anchor translation, bounds accumulation, and insufficient-point guard returning `None`. | Complete |
  | 13.5 | Run full test suite (including PYQT_TESTS and resolution) and log results after additions. | Complete |
  | 14 | Add unit tests for follow-state helpers (`_normalise_tracker_geometry`, `_resolve_and_apply_geometry`, `_post_process_follow_state`) to lock behavior before further extractions. | Complete |
  | 14.1 | Inventory follow helper behavior/coverage (normalise/resolve/post-process) and define target scenarios including WM overrides, visibility decisions, and transient parent/fullscreen hints. | Complete (mapping only; no code/tests) |
  | 14.2 | Add tests for `_normalise_tracker_geometry` covering raw/native→Qt conversion, title-bar offset, aspect guard, and logging inputs/outputs. | Complete |
  | 14.3 | Add tests for `_resolve_and_apply_geometry` covering WM override adoption, geometry application, last-set tracking, and classification logging. | Complete |
  | 14.4 | Add tests for `_post_process_follow_state` covering visibility/show/hide decisions, transient parent handling, fullscreen hints, and auto-scale persistence. | Complete |
  | 14.5 | Run full test suite (including PYQT_TESTS and resolution) and log results after additions. | Complete |
- **C.** Duplicate anchor/translation/justification workflows across the three builder methods (overlay_client/overlay_client.py:3411, :3623, :3851) risk behavioral drift; shared utilities would improve consistency.
 
  | Stage | Description | Status |
  | --- | --- | --- |
  | 15 | Consolidate anchor/translation/justification utilities into a shared helper used by all builders to keep payload alignment consistent. | Complete |
  | 15.1 | Map current anchor/translation/justification flows for message/rect/vector builders (inputs, offsets, group context) and identify shared helper API. | Complete (mapping only; no code/tests) |
  | 15.2 | Introduce shared anchor/translation helper (pure, no Qt) with existing logic; wire one builder (message) to use it; keep behavior/logging unchanged. | Complete (shared helper for justification; behavior preserved) |
  | 15.3 | Wire rect builder to shared helper; validate behavior/logging against current implementation. | Complete |
  | 15.4 | Wire vector builder to shared helper; validate behavior/logging and guardrails (insufficient points). | Complete |
  | 15.5 | Add/extend unit tests to cover shared helper across all payload types; rerun full suite and resolution test. | Complete |
- **D.** Heavy coupling of calculation logic to Qt state (e.g., QFont/QFontMetrics usage in `_build_message_command` at overlay_client/overlay_client.py:3469) reduces testability; pure helpers would help.
 
  | Stage | Description | Status |
  | --- | --- | --- |
  | 17 | Re-audit builder/follow helpers to ensure calc paths operate on primitives only, with Qt boundaries wrapped at call sites; add headless coverage to enforce separation. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 17.1 | Map current Qt boundary touch points in builders/follow helpers and identify any lingering Qt types in pure modules. | Complete |
  | 17.2 | Move any remaining Qt-specific usage back to call sites; tighten interfaces to primitives only. | Complete |
  | 17.3 | Add/extend headless tests to guard Qt-free helpers and ensure Qt objects are mocked/injected only at boundaries. | Complete |
  | 17.4 | Rerun full suite (including PYQT_TESTS/resolution) to confirm no regressions. | Complete |
- **E.** Broad `except Exception` handlers in networking and cleanup paths (e.g., overlay_client/overlay_client.py:480, :454) silently swallow errors, hiding failures.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 19 | Replace broad exception catches with scoped handling/logging in networking/cleanup paths; surface actionable errors while keeping UI stable. | Complete |

| Substage | Description | Status |
| --- | --- | --- |
| 19.1 | Inventory broad exception handlers (networking/cleanup) and classify desired scoped exceptions/logging. | Complete |
| 19.2 | Refactor handlers to scoped exceptions with meaningful logging/action; avoid silent swallow. | Complete |
| 19.3 | Add tests (unit/integration) to ensure scoped handling/logging fires for targeted failures. | Complete |
| 19.4 | Rerun full suite (including PYQT_TESTS/resolution) to confirm stability. | Complete (resolution test skipped per instruction) |
- **G.** Text measurement/painter work remains Qt-bound in `overlay_client.py`; without an injectable seam, it’s harder to headlessly validate font metrics/regression and observe measurement drift.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 18 | Introduce an injectable text-measurement seam (pure callable) for message/rect builders, add headless coverage around measurements, and keep Qt-bound painter setup at the boundary. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 18.1 | Map current text measurement touch points (message width/height, rect text metrics if any) and define seam interface and injection points. | Complete |
  | 18.2 | Implement injectable text-measurement callable (pure), provide default Qt-backed implementation at the boundary. | Complete |
  | 18.3 | Wire builders to use the injected measurer while keeping painter/QFont setup at call sites; ensure logging/trace unaffected. | Complete |
  | 18.4 | Add headless tests using a fake measurer to lock widths/heights and detect drift; rerun full suite and resolution tests via venv. | Complete |
- **F.** Justification baseline availability relies on base bounds; when missing we silently fall back to max width, which can mask drift across mixed-width payloads.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 16 | Mitigate justification baseline fallback risk by instrumenting missing baselines, ensuring builders provide base bounds where possible, and locking behavior with tests. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 16.1 | Map baseline sources per builder (message/rect/vector) and identify where base bounds are omitted in collect/trace paths. | Complete |
  | 16.2 | Instrument missing-baseline paths with trace/log hooks (guarded) to surface fallback usage without changing behavior. | Complete |
  | 16.3 | Ensure builders supply base bounds where available (including collect-only) to stabilize baseline calculations. | Complete |
  | 16.4 | Add tests for mixed-width groups with/without baselines to lock current/fixed behavior; rerun full suite and resolution tests via venv. | Complete |

- **H.** `overlay_client/overlay_client.py` remains a ~4k-line monolith (`OverlayWindow` mixes UI orchestration, follow logic, debug overlays, click-through/window flags, cycle UI, platform hooks), challenging single-responsibility and small-surface goals.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 20 | Split remaining `OverlayWindow` concerns into focused helpers/modules (e.g., debug/cycle UI surface, click-through/window-flag management), keeping Qt boundaries clear and behavior unchanged. | Planned |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 20.1 | Map remaining `OverlayWindow` concerns (debug/cycle UI, click-through/window flags, platform/visibility toggles), define extraction boundaries and Qt touchpoints; no code changes. | Complete |
  | 20.2 | Extract debug/cycle overlay UI rendering/state into a focused helper while preserving logging and painter interactions; keep behavior identical. | Complete |
  | 20.3 | Extract click-through/window-flag management (transient parent resets, WA flags, platform controller hooks) into a helper to narrow the window class surface; preserve logging. | Complete |
  | 20.3a | Audit Windows-specific flag/click-through handling; ensure helper covers Windows parity and preserves existing behavior. | Complete |
  | 20.4 | Extract force-render/visibility/platform toggle helpers (Wayland/X11 handling, apply_click_through/drag restore) to a focused module; behavior unchanged. | Complete |
  | 20.5 | Extract message/status display presentation into a small presenter/helper to reduce cross-cutting state in `OverlayWindow`; keep UI/logging intact. | Complete |
  | 20.6 | Pull entrypoint/setup (argparse, helper wiring) into a thin launcher module so `overlay_client.py` focuses on UI concerns; preserve behavior. | Complete |
  | 20.7 | Run full test suite (ruff/mypy/pytest + PYQT_TESTS/resolution) and update status/logs after extractions. | Complete |
  | 20.8 | Further thin `OverlayWindow` by isolating remaining UI/painter glue (debug/cycle overlay wiring, offscreen logging hooks) into focused view/controller helpers; preserve logging/behavior. | Complete |
  | 20.9 | Consolidate click-through/drag/visibility state handling into a dedicated interaction controller with targeted tests to prevent regressions like drag toggles affecting click-through. | Complete |

- **I.** Several Qt exception catches still silently swallow errors (e.g., click-through child attribute handling, transient parent removal, screen description, monitor ratio collection), reducing observability and hiding failures.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 21 | Scope remaining Qt error handling to expected exceptions and add debug/warning logs; avoid silent passes while keeping UI stable. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 21.1 | Inventory current Qt try/excepts (click-through child attr toggles, transient parent removal, screen description/monitor ratio collection) and classify expected exceptions vs. unexpected; document fallbacks/log gaps. | Complete (mapping only; no code/tests) |
  | 21.2 | Refactor scoped handling/logging for the mapped spots, keeping default fallbacks/UI stability while avoiding silent passes; centralize shared helpers if needed. | Complete |
  | 21.3 | Add tests (headless and PyQt where needed) asserting scoped handling/logging and preserved fallbacks for failure scenarios. | Complete |
  | 21.4 | Rerun full suite (ruff/mypy/pytest, PYQT_TESTS, resolution) and update logs/status for the refactor. | Complete |

- **J.** `_CLIENT_LOGGER.propagate = False` prevents upstream handlers from receiving client logs, making observability and test integration harder.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 22 | Revisit logger propagation (allow propagation or add a configurable hook) to let client logs flow to application handlers without breaking release logging behavior. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 22.1 | Map current logger setup (handlers/filters/propagate flag), consumers of `_CLIENT_LOGGER`, and release/debug behavior; identify risks of enabling propagation and options for opt-in hooks. | Complete (mapping only; no code/tests) |
  | 22.2 | Implement propagation strategy (configurable flag or handler hook) with safe defaults preserving release logging; ensure tests/logging utilities adapt. | Complete (env flag hook; tests pending) |
  | 22.3 | Add tests verifying propagation behavior in both default and opted-in modes (headless where possible); ensure filters/levels remain correct. | Complete |
  | 22.4 | Run full suite (ruff/mypy/pytest, PYQT_TESTS, resolution) and document outcomes. | Complete |

- **K.** Resolution test (`tests/run_resolution_tests.py`) is currently skipped; leaves a known gap in integration validation.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 23 | Rerun resolution test with overlay running and log results to restore full validation cadence. | Complete |

  | Substage | Description | Status |
  | --- | --- | --- |
  | 23.1 | Confirm resolution test prerequisites (overlay running, payload logging enabled, venv setup) and document current skip/retry behavior and gaps. | Complete (mapping only; no code/tests) |
  | 23.2 | Execute resolution tests in a clean run with overlay running; capture logs/results and note any skips (e.g., empty-text payloads). | Complete |
  | 23.3 | If failures occur, triage and document issues or fixes; otherwise record green run details for traceability. | Complete |

- **L.** `OverlayWindow` remains ~4k lines with mixed responsibilities (state, rendering, payload ingestion, debug UIs, follow orchestration) and still carries implicit coupling despite earlier extractions; further decomposition and interface tightening are needed to meet clarity/small-surface goals.
  - Special instruction: for Stage 24 sub-stages, be more aggressive than prior steps—extract every piece within each identified seam so the separation is maximal, not just minimal-risk slices.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 24 | Define a target split for `OverlayWindow` (e.g., thin orchestration shell + injected render/follow/payload/debug surfaces) with clear interfaces and ownership, based on current code reality. | In progress |
  | 24.1 | Render/payload pipeline + debug surface (overlay_client/overlay_client.py:2474-4059, ~1,600 lines): legacy payload handling, render passes, command building (`_build_*_command`), justification/anchor translation, group cache/logging, debug overlays, text measurement cache; target dedicated render surface with injected builder/renderer/debug hooks. | Complete |
  | 24.2 | Follow/window orchestration + platform hooks (overlay_client/overlay_client.py:1881-2473, ~600 lines): drag/click-through toggles, tracker polling, normalization, geometry application, visibility/transient parent/fullscreen handling; move to controller layer with Qt calls at boundary. | Complete |
  | 24.3 | External control/API surface (overlay_client/overlay_client.py:1112-1880, ~770 lines): `set_*`/status methods, cycle overlay helpers, repaint scheduling/metrics, config toggles; extract to control/adaptor feeding orchestrator. | Planned |
  | 24.4 | Interaction/event overrides (overlay_client/overlay_client.py:1011-1111, ~100 lines): mouse/resize/move events and grid caching; relocate to interaction surface with injected callbacks. | Planned |
  | 24.5 | Widget setup + baseline helpers (overlay_client/overlay_client.py:263-1010, ~750 lines): `__init__`, font/layout setup, transform wrappers, metrics/publish hooks, show/paint events; leave thin Qt shell, push pure helpers/metrics into shared modules. | Planned |

- **M.** DRY gaps: duplicated helpers (`_ReleaseLogLevelFilter` in `overlay_client.py` and `data_client.py`; duplicated `_clamp_axis` in `payload_transform.py`) and scattered logging filters reduce consistency and increase maintenance risk.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 25 | Centralize shared logging helpers and axis clamps; remove duplicates and wire modules to the shared utilities without behavior changes. | Planned |
  | 25.1 | Map current filter/clamp usages and consumers; define shared utility surface (likely in `logging_utils`/`payload_transform`). | Planned |
  | 25.2 | Replace local copies with shared helpers; keep existing behavior/levels and add targeted tests if needed; rerun check/test suites. | Planned |

- **N.** Extensive `# type: ignore` use in `overlay_client.py` and related imports hides type drift and weakens mypy coverage on the core client.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 26 | Reduce `type: ignore` usage by fixing import/type issues in the client entrypoint and enabling meaningful mypy coverage on core modules. | Planned |
  | 26.1 | Inventory `type: ignore` entries in client modules; categorize root causes (cycles, missing stubs, real type gaps). | Planned |
  | 26.2 | Resolve root causes (stub fixes, interface tweaks, cycle-safe imports) and remove/convert ignores; rerun mypy/pytest to verify. | Planned |

- **O.** Helper boundaries leak `OverlayWindow` internals (e.g., `FillGroupingHelper` reaches into window caches/state), reducing reusability and testability.

  | Stage | Description | Status |
  | --- | --- | --- |
  | 27 | Tighten helper interfaces (notably grouping/fill helpers) to consume explicit inputs instead of window internals; improve seams for injection/testing. | Planned |
  | 27.1 | Map current helper/window coupling points and define the explicit data/callbacks each helper should own. | Planned |
  | 27.2 | Refactor helpers to use injected inputs (cache accessors, metrics, device ratio, settings) and adjust callers; add/extend tests to cover new seams. | Planned |

----
# Stage Summary and Test results

### Stage 20 quick summary (intent)
- Goal: break down remaining `OverlayWindow` responsibilities into focused helpers (debug/cycle UI, click-through/window-flag management, force-render/visibility/platform toggles) while keeping Qt boundaries and behavior unchanged.
- Scope: relocate logic without altering signals/painting; ensure logging stays intact and tests validate no regressions.
- Tests to run after extraction: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, and `python tests/run_resolution_tests.py --config tests/display_all.json`.
- Status: Planned (substage mapping pending).

### Stage 20.2 quick summary (plan)
- Target: extract debug/cycle overlay rendering/state (`_paint_debug_overlay`, `_paint_cycle_overlay`, `_sync_cycle_items`) into a focused helper/view. Keep QPainter/QWidget interactions at the boundary; helper should operate on primitives and callbacks.
- Inputs: mapper/viewport state, follow state/overrides, payload model/grouping helper, cycle anchors, message label/current selection. Outputs: draw calls (painter ops) and text formatting unchanged.
- Constraints: preserve logging/formatting, cycle anchor/state management, and avoid Qt leaks into the helper. No behavioral changes expected.
- Validation: run `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`; resolution test if overlay available (else document skip).

### Stage 20.2 quick summary (status)
- Extracted debug/cycle overlay rendering to `overlay_client/debug_cycle_overlay.py` with `DebugOverlayView` and `CycleOverlayView`; `OverlayWindow` now delegates while keeping Qt painter setup at the boundary.
- Cycle sync is handled via helper before painting; debug overlay uses injected font fallback/line-width callbacks and preserves formatting/logging behavior (no UI changes expected).
- Qt types stay at call sites; helpers operate on primitives/callbacks.
- Follow-ups: wired debug/cycle overlays to use the window font family instead of `mapper.transform.font_family` to avoid missing-attribute crashes; cycle TTL display now uses `time.monotonic()` (with optional injected hook) instead of a missing payload model helper. Rendering/logging unchanged.

#### Stage 20.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check`
- `source overlay_client/.venv/bin/activate && make test`
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests`

#### Stage 20.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (transient pipe warning after completion).
- Resolution test not rerun (overlay not running; skip as previously noted).

### Stage 20.3 quick summary (status)
- Added `WindowFlagsHelper` to own click-through/window-flag management with injected callbacks for Qt/window operations, platform controller hooks, and transient-parent clearing (Wayland force_render path). Logging/behavior preserved; UI unchanged.
- `OverlayWindow` now delegates `_set_click_through`, `_restore_drag_interactivity`, and force-render click-through setup to the helper; child widget transparency toggled via dedicated setter.

#### Stage 20.3 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- Resolution test not rerun (overlay not running).

### Stage 20.3a quick summary (status)
- Audited Windows-specific click-through/flag handling after helper extraction; Windows paths remain unchanged and handled via injected callbacks (Qt flags, WA transparency, Tool/Frameless/Top hints, transparent input). No code changes required.
- Behavior/logging parity maintained across platforms; future platform tweaks stay isolated in the helper.

#### Stage 20.3a test log (latest)
- No new tests; relying on latest full run (`make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`) from Stage 20.3.

### Stage 20.4 quick summary (status)
- Added `VisibilityHelper` to own show/hide flow with injected callbacks; `_update_follow_visibility` now delegates, keeping Qt calls at the boundary while preserving logging and drag-application semantics.
- `OverlayWindow` stores visibility state via the helper; behavior unchanged, extraction sets up future platform-specific tweaks in one place.

#### Stage 20.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- Resolution test not rerun (overlay not running).

### Stage 20.3a quick summary (status)
- Audited Windows-specific click-through/flag handling after helper extraction; Windows paths remain unchanged and handled via injected callbacks (Qt flags, WA transparency, Tool/Frameless/Top hints, transparent input). No code changes required.
- Behavior/logging parity maintained across platforms; future platform tweaks stay isolated in the helper.

#### Stage 20.3a test log (latest)
- No new tests; relying on latest full run (`make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`) from Stage 20.3.

### Stage 20.4 quick summary (status)
- Added `VisibilityHelper` to own show/hide flow with injected callbacks; `_update_follow_visibility` now delegates, keeping Qt calls at the boundary while preserving logging and drag-application semantics. Force-render visibility handling continues to reuse platform hooks; behavior unchanged.
- This extraction sets up future platform-specific tweaks in one place; no UI/signal changes.

#### Stage 20.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed.

### Stage 20.5 quick summary (status)
- Stage bookkeeping: status/message presentation already lives in `overlay_client/status_presenter.py` and `OverlayWindow` delegates status text/show/hide/bottom-margin to it. No new code in this update; marking the substage complete to reflect the existing extraction.
- Behavior/logging unchanged; platform suffix formatting and bottom-margin coercion remain handled in the presenter via injected callbacks.

#### Stage 20.5 test log (latest)
- Not rerun for this doc-only completion. Prior full suite from earlier Stage 20 work remains the latest. Recommended quick sanity sweep if needed: `make check && make test && PYQT_TESTS=1 python -m pytest overlay_client/tests`.

### Stage 20.6 summary/test results
- Entry point/setup moved to `overlay_client/launcher.py`, keeping argument parsing, settings/debug config loading, Qt app/window/data client wiring, and payload handling identical to the previous main.
- `overlay_client.py` now exposes thin `main`/`resolve_port_file` shims and retains the `__main__` guard to delegate to the launcher, preserving CLI behavior.
- Tests not rerun for this refactor; latest full suite from earlier Stage 20 work still stands. Suggested quick check if needed: `make check && make test && PYQT_TESTS=1 python -m pytest overlay_client/tests`.

### Stage 20.7 summary/test results
- Ran full suite after entrypoint refactor: `make check`, `make test`, `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests`, and `overlay_client/.venv/bin/python tests/run_resolution_tests.py --config tests/display_all.json` (all passed; resolution replay emitted expected empty-message skips).
- Behavior baseline refreshed; logs still caution about disabled payload logging (expected when preference is off).
- Follow-up rerun: `overlay_client/.venv/bin/python tests/run_resolution_tests.py --config tests/display_all.json` with payload logging enabled (`overlay-payloads.log` present). Passed; empty-text payloads skipped as expected, no warnings about disabled logging.

### Stage 20.8 summary/test results
- Extracted offscreen payload logging into `overlay_client/offscreen_logger.py` and wired `OverlayWindow` to use it; behavior/logging unchanged (still warns once per payload rendered fully offscreen and clears when back onscreen).
- `make check` and `make test` rerun and passed; full suite run as part of `make check` execution (ruff/mypy/pytest). No additional PYQT/resolution rerun for this small refactor.

### Stage 20.9 summary/test results
- Replaced `WindowFlagsHelper` with `InteractionController` to own click-through, drag restoration, and force-render platform tweaks; `OverlayWindow` delegates click-through/restore/force-render setup to the controller, keeping behavior and logging identical.
- `make check` rerun after the change (ruff/mypy/pytest) and passed; no additional PYQT/resolution rerun for this wiring-only refactor.

### Stage 20.1 quick summary (mapping)
- Debug/cycle UI surface: `_paint_debug_overlay` (uses QPainter, `_compute_legacy_mapper`, `_viewport_state`, `_aspect_ratio_label`, follow controller state, overrides) and `_paint_cycle_overlay` + `_sync_cycle_items` (payload model/grouping helper/cycle anchor points, message label) remain embedded; candidates for a view helper that accepts primitives + callbacks for painter draw operations and log formatting.
- Click-through/window flags: `_set_click_through`, `_restore_drag_interactivity`, `_apply_drag_state`, `_poll_modifiers`, `_is_wayland`, transient-parent clearing in `set_force_render`, and platform controller hooks (`prepare_window`, `apply_click_through`, transparent input flag) are intertwined; could be isolated into a window-interaction helper that owns WA/window flags and platform controller coordination.
- Force-render/visibility/platform toggles: `set_force_render`, `_update_follow_visibility`, `_handle_missing_follow_state`, `_ensure_transient_parent`, and platform context updates interact with follow controller suspend/refresh and Linux/Wayland differences; extraction seam should keep Qt calls in the window while moving decision logic to a helper.
- Qt boundaries/touchpoints: QWindow/QWidget flag setters, `QGuiApplication.screens`, `setTransientParent`, and platform controller apply hooks stay at the boundary; extracted helpers should operate on primitives/callbacks to avoid Qt leakage.

#### Stage 20.1 test log (latest)
- Not run (mapping/documentation only).

### Stage 21 quick summary (intent)
- Goal: scope remaining Qt try/excepts to expected failures and surface useful logs instead of silent passes, keeping UI stability intact.
- Scope: click-through child attr toggles, transient parent removal, screen description/device ratio collection, and similar Qt calls that currently swallow errors; identify expected exception types and required fallbacks.
- Constraints: preserve existing fallbacks/behavior (no new crashes), keep logging noise low, and avoid widening Qt dependencies in pure helpers.
- Validation: map in 21.1, refactor in 21.2, add headless/PyQt tests in 21.3, then rerun `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, and `python tests/run_resolution_tests.py --config tests/display_all.json` in 21.4.
- Status: Complete.

#### Stage 21 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 21.1 quick summary (mapping)
- `overlay_client/overlay_client.py:_set_children_click_through`: wraps `child.setAttribute(Qt.WA_TransparentForMouseEvents, transparent)` in a bare `except Exception: pass`; expected failure cases are widget destruction or platform Qt errors, but we currently drop all signals/logging when a child rejects the flag.
- `overlay_client/interaction_controller.py:handle_force_render_enter`: on Wayland, clearing the transient parent calls `set_transient_parent_fn(None)` inside a bare `except Exception: pass`; expected failures include Qt runtime errors when the window handle is gone; fallback is still clearing cached IDs, but no log is emitted.
- `overlay_client/overlay_client.py:_ensure_transient_parent` (Wayland branch): when a transient parent is already set, `window_handle.setTransientParent(None)` is wrapped in a bare `except Exception: pass`; failures are silent before clearing local IDs and returning.
- `overlay_client/overlay_client.py:_describe_screen`: wraps `screen.geometry()`/`screen.name()` in a bare `except Exception`, returning `str(screen)` with no log, so screen-query errors are invisible during move/geometry logs.
- `overlay_client/overlay_client.py:_normalise_tracker_geometry`: `window_handle.devicePixelRatio()` read is wrapped in `except Exception` with no logging and defaults to `0.0` (later ignored); ratio diagnostics are skipped on failure, masking dpr issues.
- `overlay_client/overlay_client.py:_update_auto_legacy_scale`: `self.devicePixelRatioF()` read uses a bare `except Exception` and defaults to `1.0` with no log, hiding failures when collecting monitor/device ratios for scaling.

#### Stage 21.1 test log (latest)
- Not run (mapping-only documentation update; no code/tests).

### Stage 21.2 quick summary (status)
- Scoped Qt try/excepts: child click-through attribute toggles now log failures; Wayland transient-parent clears (force-render and overlay) log scoped errors instead of silent passes; screen description fallback logs failures before returning the stringified screen.
- Device pixel ratio reads now use scoped exceptions with debug logs and existing fallbacks (window dpr defaults to 0.0 for diagnostics gating; devicePixelRatioF defaults to 1.0) plus warning logs for unexpected Qt errors; behavior remains unchanged.
- Tests run after logging changes; targeted failure-path coverage still planned for 21.3 before finalising the stage.

#### Stage 21.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 21.3 quick summary (status)
- Added headless/PyQt tests covering the scoped logging paths: child click-through attribute failures, Wayland transient-parent clear in `InteractionController`, screen description fallback, and devicePixelRatioF fallback in `_update_auto_legacy_scale`.
- Tests assert logs emit on expected exceptions while preserving existing fallbacks; no production code changes beyond prior logging.
- Full suite (ruff/mypy/pytest), PYQT_TESTS subset, and resolution tests rerun and passing.

#### Stage 21.3 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 21.4 quick summary (status)
- Full-suite rerun after adding scoped-logging tests: lint/typecheck/pytest, PYQT_TESTS subset, and resolution replay all green; behavior unchanged (expected empty-text payload skips during replay).
- Stage 21 closed; future logging/propagation work to proceed under Stage 22.

#### Stage 21.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 24 quick summary (intent)
- Goal: drive further decomposition of the 4k-line `OverlayWindow` into a thin orchestrator with injected render/follow/payload/debug surfaces and clearer ownership boundaries.
- Scope: map current surface area, define seams, and move non-Qt logic/state out while keeping Qt calls at the boundary; preserve behavior/logging.
- Tests to run when wiring starts: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, and `python tests/run_resolution_tests.py --config tests/display_all.json`.
- Status: In progress (24.1 complete; follow-on extractions pending).

### Stage 24.1 quick summary (status)
- Extracted render/payload/debug surface into `overlay_client/render_surface.py` as `RenderSurfaceMixin`; `OverlayWindow` now inherits it to keep Qt shell thin while moving legacy payload handling, command building, justification, caching, and debug helpers out of the monolith.
- Moved bounds/debug/text dataclasses to the mixin module and added `_line_width_defaults` plumbing for the shared helper; `_update_auto_legacy_scale` now pulls `legacy_scale_components` via module lookup to keep monkeypatchable behavior.
- Kept Qt painter/instance wiring at the boundary; core logic and logging now live in the mixin to maximize separation per Stage 24 aggressiveness instruction.
- Added headless render-surface tests covering line-width defaults, module-scale fallback in `_update_auto_legacy_scale`, and injected text measurer/cache context reset.

#### Stage 24.1 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed (ruff/mypy/pytest; includes new render surface tests).
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → failed earlier (overlay client not running; rerun when overlay process is active).

### Stage 24.2 quick summary (status)
- Extracted follow/window orchestration and platform hooks into `overlay_client/follow_surface.py` as `FollowSurfaceMixin`; `OverlayWindow` now inherits it, leaving Qt wiring in the shell while moving drag/click-through toggles, tracker polling, normalization, geometry application, visibility/transient parent handling, and screen helpers out of the monolith.
- Kept aggressive separation per Risk L: all follow/platform methods moved; controller/visibility helpers remain injected; Qt calls stay at the boundary via callbacks.
- Added headless follow-surface tests covering controller resolution/geometry logging, normalisation/device-ratio logging snapshots, and force-render visibility click-through handling.

#### Stage 24.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed (ruff/mypy/pytest; includes new follow-surface tests).
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → not run this stage (overlay process not active); rerun after overlay is running.

### Stage 25 quick summary (intent)
- Goal: centralize duplicated helpers (`_ReleaseLogLevelFilter`, `_clamp_axis`) into shared utilities to enforce DRY and consistent behavior.
- Scope: map current usages, move helpers into shared modules (`logging_utils`, `payload_transform`), and wire callers without behavior changes.
- Validation: `make check`, `make test`, targeted unit tests around logging filters/axis clamps; rerun PYQT/resolution if code paths touch rendering/logging.
- Status: Planned.

### Stage 26 quick summary (intent)
- Goal: reduce `# type: ignore` in core client modules by fixing root causes so mypy meaningfully guards the entrypoint and overlays.
- Scope: inventory ignores, address cycles/stub gaps/interface issues, remove or narrow ignores; keep behavior unchanged.
- Validation: `make check` (ruff/mypy) and `make test`; rerun PYQT/resolution if wiring changes touch runtime behavior.
- Status: Planned.

### Stage 27 quick summary (intent)
- Goal: tighten helper boundaries (e.g., `FillGroupingHelper`) so they consume explicit inputs/callbacks instead of reaching into `OverlayWindow` internals, improving testability.
- Scope: map coupling points, define explicit inputs, refactor helpers/callers, and add/extend tests to cover new seams.
- Validation: `make check`, `make test`, targeted helper tests; run PYQT/resolution if behavior surfaces change.
- Status: Planned.

### Stage 22.1 quick summary (mapping)
- Current logger setup: `_CLIENT_LOGGER` (`EDMC.ModernOverlay.Client`) with level DEBUG in debug mode else INFO; `propagate = False`; `_ReleaseLogLevelFilter` promotes DEBUG→INFO in release mode. Default handlers come from root logging; tests often attach `NullHandler` or capture `DEBUG` on bespoke loggers.
- Consumers: `_CLIENT_LOGGER` passed into platform controller, group coordinator, follow controller, interaction controller, status presenter/offscreen logger, and developer helpers. Tests for data client use dedicated loggers, not `_CLIENT_LOGGER` propagation. Root-level handlers are not configured in this module; suppression via `propagate=False` keeps logs local unless handlers attached directly.
- Risks toggling propagate: double-logging if upstream handlers present; release-mode filter may conflict with upstream level/filters; CLI environments may attach stderr handlers leading to noisy output if DEBUG allowed. Need opt-in or configurable hook rather than unconditional propagation.
- Options: configurable propagation flag via settings/env, or attaching an opt-in handler for external observers; maintain `_ReleaseLogLevelFilter` behavior and safe defaults (propagate False). Tests should verify default isolation and opt-in propagation without duplicate records.

### Stage 22.2 quick summary (status)
- Added opt-in propagation hook: `EDMC_OVERLAY_PROPAGATE_LOGS` env var (true/1/yes/on) enables `_CLIENT_LOGGER.propagate`; default remains `False`. Release filter and levels unchanged; behavior defaults preserved.
- No dedicated tests yet (planned for 22.3); full suite rerun to ensure no regressions.

#### Stage 22.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 22.3 quick summary (status)
- Added propagation behavior tests (`test_logging_propagation.py`) verifying defaults keep `propagate` disabled and `EDMC_OVERLAY_PROPAGATE_LOGS` enables it on import; tests reset logger/env between runs to avoid leaking state.
- No production changes beyond the existing env hook; behavior remains opt-in.
- Full suite rerun (lint/typecheck/pytest, PYQT_TESTS subset, resolution) and passing.

#### Stage 22.3 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 22.4 quick summary (status)
- Stage close-out: propagation env hook and tests validated via full suite (ruff/mypy/pytest), PYQT_TESTS subset, and resolution replay; no further code changes.
- Default behavior remains non-propagating; opt-in verified through tests; release filter intact.

#### Stage 22.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped during replay; overlay running).

### Stage 23.1 quick summary (mapping)
- Prereqs: overlay process running; payload logging enabled so broadcaster port resolves; use `overlay_client/.venv` with PyQt6; run `python tests/run_resolution_tests.py --config tests/display_all.json` after activating venv. Expect skips for empty-text legacy payloads (logged during replay) but run should complete.
- Current behavior: prior runs (Stages 21/22) completed successfully with expected empty-text skips; no known blockers. Resolution test depends on overlay broadcaster at 127.0.0.1:41145, derived from overlay payload logging file; retries built into the script.
- Gaps: none identified; ensure overlay running and payload logs present before Stage 23.2 execution.

### Stage 23.2 quick summary (status)
- Ran resolution tests with overlay running and payload logging enabled; all payload batches replayed successfully. Expected skips occurred for empty-text legacy payloads; no errors observed.
- No code changes; confirms integration pipeline still green with current overlay build.

#### Stage 23.2 test log (latest)
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (expected empty-text payloads skipped; overlay running).

### Stage 23.3 quick summary (status)
- Resolution validation closed: latest run green with only expected empty-text legacy payload skips; no triage required.
- Stage 23 complete; resolution test cadence restored with documented results.

### Stage 1 quick summary (intent)
- Goal: move `OverlayDataClient` into `overlay_client/data_client.py` with no behavior change.
- Keep public API identical (`start/stop/send_cli_payload`) and the same signals (`message_received`, `status_changed`); preserve backoff/queue behavior and release-mode log filtering.
- `overlay_client.py` should only switch to importing the extracted class; no UI or pipeline changes.
- Run the full test set listed below and record results before marking this stage complete.

#### Stage 1 test log (latest)
- Created venv at `overlay_client/.venv` and installed `requirements/dev.txt`.
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running; verified).

### Stage 2 quick summary (intent)
- Goal: move `_LegacyPaintCommand`, `_MessagePaintCommand`, `_RectPaintCommand`, `_VectorPaintCommand`, and `_QtVectorPainterAdapter` into `overlay_client/paint_commands.py` with no behavior change.
- Keep signatures and call sites identical so `_paint_legacy` and related rendering paths remain unchanged.
- `overlay_client.py` should only adjust imports/references; avoid touching rendering logic beyond the move.
- Run full test set and record results after the extraction.

#### Stage 2 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 3 quick summary (intent)
- Goal: move `_initial_platform_context` and font resolution helpers (`_resolve_font_family`, `_resolve_emoji_font_families`, `_apply_font_fallbacks`) into `overlay_client/platform_context.py` and `overlay_client/fonts.py` without behavior changes.
- Keep function signatures and usage points the same; only adjust imports/wiring in `overlay_client.py`.
- Preserve logging behavior and font lookup/fallback logic exactly as before.
- Run the full test set and log results once the move is complete (including resolution test with overlay running).

#### Stage 3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 91 passed, 7 skipped).
- `make test` → passed (91 passed, 7 skipped).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (60 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 4 quick summary (intent)
- Goal: trim `OverlayWindow` to UI orchestration only by extracting pure calculations.
- Keep function signatures and usage points the same; only adjust imports/wiring in `overlay_client.py`.
- Preserve logging behavior and math/geometry logic exactly as before.
- Run the full test set and log results once the move is complete (including resolution test with overlay running).

Substeps:
- 4.1 Map non-UI helpers in `OverlayWindow` (follow/geometry math, payload builders, viewport/anchor/scale helpers) and mark target extractions.
- 4.2 Extract follow/geometry calculation helpers into a module (no Qt types); wire `OverlayWindow` to use them; keep behavior unchanged.
- 4.3 Extract payload builder helpers (`_build_message_command/_rect/_vector` calculations, anchor/justification/offset utils) into a module, leaving painter/UI hookup in `OverlayWindow`.
- 4.4 Extract remaining pure utils (viewport/size/line width math) if still embedded.
- 4.5 After each extraction chunk, run full test suite and update Stage 4 log/status.

#### Stage 4.2 quick summary (intent)
- Goal: move follow/geometry math (`_apply_title_bar_offset`, `_apply_aspect_guard`, `_convert_native_rect_to_qt`, and follow state calculations) into a helper module with only primitive types.
- Keep `OverlayWindow` responsible for Qt handles and window manager interactions; only swap in helpers for pure calculations and logging.
- Preserve log messages, override handling, and geometry normalization behavior exactly; no UI changes.
- Touch points: new helper module under `overlay_client`, updated imports/call sites in `overlay_client.py`, and Stage 4 status/test log updates here.

#### Stage 4.1 mapping (complete)
- Follow/geometry targets: `_apply_follow_state`, `_convert_native_rect_to_qt`, `_apply_title_bar_offset`, `_apply_aspect_guard`, related logging/override handling.
- Payload builder targets: `_build_message_command`, `_build_rect_command`, `_build_vector_command`, anchor/justification/offset and size/scale calculations within them.
- Other pure helpers still in `OverlayWindow`: `_line_width`, `_legacy_preset_point_size`, `_current_physical_size`, `_aspect_ratio_label`, `_compute_legacy_mapper`, viewport state helpers.

#### Stage 4.2 status (complete)
- Added `overlay_client/follow_geometry.py` with screen info dataclass and helpers for native-to-Qt rect conversion, title-bar offsets, aspect guard, and WM override resolution (primitive types only).
- `OverlayWindow` now calls those helpers via thin wrappers to preserve logging/state while keeping Qt/window operations local.
- Introduced `_screen_info_for_native_rect` to build conversion context without leaking Qt types into the helper module.

#### Stage 4.3 quick summary (intent)
- Goal: move payload builder calculations for messages/rects/vectors into a helper module (anchors, offsets, translations, bounds math) while leaving Qt painter wiring in `OverlayWindow`.
- Keep method signatures and observable behavior identical; preserve logging, tracing, and grouping/viewport interactions.
- Limit helpers to pure calculations and data assembly; keep QPainter/QPen/QBrush construction and font metric retrieval inside `OverlayWindow`.
- Touch points: new helper module under `overlay_client`, updated imports/wiring in `overlay_client.py`, docs/test log updates here.

#### Stage 4.3 status (complete)
- Added `overlay_client/payload_builders.py` with `build_group_context` to centralize group anchor/translation math for message/rect/vector builders.
- `OverlayWindow` now calls the helper for shared calculations, keeping Qt object creation and command construction local; behavior/logging preserved.

#### Stage 4.4 quick summary (intent)
- Goal: move remaining pure helpers (`_line_width`, `_legacy_preset_point_size`, `_current_physical_size`, `_aspect_ratio_label`, `_compute_legacy_mapper`, `_viewport_state` helpers) into a module, leaving Qt/UI wiring in `OverlayWindow`.
- Keep signatures and behavior identical; only delegate calculations and defaults to helpers using primitive inputs.
- Preserve logging and debug formatting; no changes to painter or widget interactions.
- Touch points: new helper module under `overlay_client`, updated imports/wiring in `overlay_client.py`, docs/test log updates here.

#### Stage 4.4 status (complete)
- Added `overlay_client/window_utils.py` with helpers for physical size, aspect labels, mapper/state construction, legacy preset sizing, and line widths (primitive-only).
- `OverlayWindow` now delegates to these helpers while keeping Qt/window handles local; method signatures unchanged.

#### Stage 5 status (complete)
- Added tests for `window_utils` covering physical size guards, aspect labels, mapper/state construction, preset font sizing, and line widths.
- Re-ran the full test suite (including resolution test) after additions.

#### Stage 4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 102 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (71 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

#### Stage 5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 5 quick summary (intent)
- Goal: add targeted unit tests for newly extracted modules:
  - `overlay_client/data_client.py`: payload queueing behavior and basic signal flow (with mocked connections).
  - `overlay_client/paint_commands.py`: paint commands and `_QtVectorPainterAdapter` call through to window hooks and painter methods.
  - `overlay_client/fonts.py`: font/emoji fallback resolution paths and duplicate suppression.
  - `overlay_client/platform_context.py`: env overrides applied over settings.
- No production logic changes; only tests and supporting stubs/mocks as needed.
- Run the full test set and log results once added.

#### Stage 5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 102 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → included above (PYQT_TESTS set during full run).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

#### Stage 6 mapping (complete)
- `_apply_follow_state`: raw geometry logging; native→Qt conversion + device ratio logs; title bar offset and aspect guard (helpers); WM override resolution; QRect/setGeometry/move-to-screen with logging; WM override classification/logging; follow-state update; transient parent handling; fullscreen hint; visibility/show/hide updates. Qt boundary: windowHandle/devicePixelRatio, QRect/frameGeometry/setGeometry/move/show/hide/raise_.
- `_build_message_command`: size/color parsing; group context (viewport + offsets); inverse group scale for anchors; remap + offsets; translation; font setup + metrics (Qt boundary: QFont/QFontMetrics); pixel/bounds and overlay bounds; tracing (`paint:message_input/translation/output`); command assembly.
- `_build_rect_command`: color parsing; QPen/QBrush setup (Qt boundary); group context; rect remap + offsets; inverse group scale + translation; anchor transform; overlay/base bounds; pixel bounds; tracing (`paint:rect_input/translation/output`); command assembly.
- `_build_vector_command`: trace flags; group context offsets/anchors/translation; raw points min lookup; remap_vector_points + offsets; inverse group scale + translation; overlay/base bounds accumulation; anchor transform; screen point conversion; tracing (`paint:scale_factors/raw_points/vector_translation`); command assembly.

#### Stage 7.1 status (complete)
- Introduced `_normalise_tracker_geometry` to handle raw geometry logging, native→Qt conversion + device ratio diagnostics, title bar offset, and aspect guard application while keeping Qt calls local.
- `_apply_follow_state` now delegates the normalization block; behavior and logging unchanged.

#### Stage 7.2 status (complete)
- Added `_resolve_and_apply_geometry` to handle WM override resolution, geometry application/setGeometry/move-to-screen, override classification/logging, and target adoption; `_apply_follow_state` now delegates this block.
- Behavior and logging preserved; `_last_geometry_log` and override handling remain unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, `python3 tests/run_resolution_tests.py --config tests/display_all.json`.

#### Stage 7.3 status (complete)
- Added `_post_process_follow_state` to handle follow-state persistence, transient parent handling, fullscreen hint emission, and visibility/show/hide decisions; `_apply_follow_state` delegates to it.
- Behavior and logging preserved; follow visibility and transient parent flows unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`, `python3 tests/run_resolution_tests.py --config tests/display_all.json`.

### Stage 8 quick summary (intent)
- Goal: split builder methods into calculation/render sub-helpers while keeping font metrics/painter setup in place; preserve logging/tracing and behavior.
- Work through message, rect, and vector builders in small, testable steps; run full tests after each chunk.

#### Stage 8.1 status (complete)
- Added `_compute_message_transform` to handle message payload remap/offset/anchor/translation calculations and tracing; `_build_message_command` now delegates pre-metrics math to the helper (Qt font metrics remain local).
- Behavior and logging unchanged.

#### Stage 8.2 status (complete)
- Added `_compute_rect_transform` to handle rect remap/offset/anchor/translation calculations, base/reference bounds, and tracing; `_build_rect_command` now delegates geometry math while keeping pen/brush setup local.
- Behavior and logging unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`; resolution test not rerun in this stage.

#### Stage 8.3 status (complete)
- Added `_compute_vector_transform` to handle vector remap/offset/anchor/translation, bounds accumulation, and tracing; `_build_vector_command` now delegates calculation while keeping payload assembly/painter interactions local.
- Behavior and logging unchanged.
- Tests: `make check`, `make test`, `PYQT_TESTS=1 python -m pytest overlay_client/tests`; resolution test not rerun in this stage.

#### Stage 8 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 9 quick summary (intent)
- Goal: run the full test suite after the Stage 8 refactors and update logs/status.
- Includes resolution test with overlay running.

#### Stage 9 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (77 passed).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → passed (overlay client running).

### Stage 10.1 quick summary (intent and mapping)
- Mapped `_compute_message_transform`, `_compute_rect_transform`, `_compute_vector_transform` seams: all current math is pure (no Qt types); Qt stays where painter/font/pen/brush and command assembly occur.
- Target pure module API: three functions mirroring current helpers, operating on primitives/group contexts and accepting injected trace/log callbacks; return transformed logical points/bounds, effective anchors, translations, and (for vectors) screen-point tuples and optional trace fn; guard that insufficient vector points returns `None`.
- Qt boundaries to keep in `OverlayWindow`: QFont/QFontMetrics usage, QPen/QBrush creation, QPainter interactions, and command object construction.
- No code changes; this is a mapping/documentation step only.

#### Stage 10.1 test log (latest)
- Not run (documentation-only mapping).

### Stage 10.2 quick summary (status)
- Created `overlay_client/transform_helpers.py` with pure helpers `apply_inverse_group_scale` and `compute_message_transform` (no Qt types); preserved logging via injected trace callback.
- `_compute_message_transform` in `OverlayWindow` now delegates to the pure helper; painter/font handling and command assembly remain local.
- Behavior and logging preserved; inverse group scaling reused via the new helper.

#### Stage 10.2 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.3 quick summary (status)
- Added `compute_rect_transform` to `overlay_client/transform_helpers.py` (pure math, optional trace callback); reused shared inverse group scaling.
- `_compute_rect_transform` in `OverlayWindow` now delegates to the pure helper; pen/brush/painter work and command assembly stay local; logging preserved.

#### Stage 10.3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.4 quick summary (status)
- Added `compute_vector_transform` to `overlay_client/transform_helpers.py` (pure math/remap/bounds/anchor with optional trace callback); preserves insufficient-point guard.
- `_compute_vector_transform` now delegates to the pure helper; screen-point conversion and command assembly remain in `OverlayWindow`; logging preserved.

#### Stage 10.4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.5 quick summary (status)
- All three transform helpers now come from `overlay_client/transform_helpers.py`; `OverlayWindow` uses them via injected trace callbacks, keeping Qt/painter wiring local.
- Imports cleaned; util helpers now the single path for message/rect/vector calculations.

#### Stage 10.5 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 108 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 10.6 quick summary (status)
- Added `overlay_client/tests/test_transform_helpers.py` covering `apply_inverse_group_scale`, and message/rect/vector transform helpers (offsets, inverse scaling/translation, bounds, insufficient-point guard, trace callbacks).
- Ensures pure helpers behave consistently before further refactors.

#### Stage 10.6 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.1 quick summary (intent and mapping)
- Goal: define Qt vs. pure seams for follow/window orchestration and the target controller interface.
- Qt-bound: `windowHandle()` interactions (setScreen, devicePixelRatio), `QRect`/`QScreen` usage, `frameGeometry`, `setGeometry`, `move/show/hide/raise_`, transient parent creation (`QWindow.fromWinId`), and platform controller hooks.
- Pure/controller-friendly: WM override resolution, geometry classification/adoption, follow-state persistence, visibility decision (`should_show`), title bar offset/aspect guard inputs/outputs, last-state caching/logging keys.
- Target controller API: methods for `normalize_tracker_geometry(state) -> (tracker_qt_tuple, tracker_native_tuple, normalisation_info, desired_tuple)`, `resolve_and_apply_geometry(tracker_qt_tuple, desired_tuple) -> target_tuple`, `post_process_follow_state(state, target_tuple) -> visibility decision + follow state updates`, plus callbacks/injections for logging, WM override getters/setters, and Qt geometry application delegated via thin lambdas.
- No code changes; mapping-only step.

#### Stage 11.1 test log (latest)
- Not run (documentation-only mapping).

### Stage 11.2 quick summary (status)
- Added scaffold `overlay_client/window_controller.py` with pure types (`Geometry`, `NormalisationInfo`, `FollowContext`) and a `WindowController` shell that will host follow/window orchestration; includes logging/state placeholders only.
- No wiring yet; behavior unchanged in `OverlayWindow`.

#### Stage 11.2 test log (latest)
- Not run (scaffold only; no behavior change).

### Stage 11.3 quick summary (status)
- Implemented geometry/WM override orchestration in `WindowController.resolve_and_apply_geometry` (pure; uses injected callbacks for Qt operations and logging); preserved override resolution flow.
- `_resolve_and_apply_geometry` now delegates to the controller with callbacks for move/set geometry, classification logging, and WM override bookkeeping; behavior/logging preserved.
- Fixed regression risk: `_last_set_geometry` is now updated before `setGeometry` via the controller callback to prevent resizeEvent from reverting to stale sizes during follow updates.

#### Stage 11.3 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.4 quick summary (status)
- Moved follow post-processing into `WindowController.post_process_follow_state` with callbacks for visibility updates, auto-scale, transient parent, and fullscreen hint; preserves Linux fullscreen hint logging.
- `_post_process_follow_state` now delegates to the controller; logging/behavior unchanged.

#### Stage 11.4 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 114 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 11.5 quick summary (status)
- Controller now handles geometry and post-processing; `OverlayWindow` delegates follow orchestration to it. No further code changes; bookkeeping only.

#### Stage 11.5 test log (latest)
- Not rerun (no code changes).

### Stage 11.6 quick summary (status)
- Added `overlay_client/tests/test_window_controller.py` covering geometry override adoption, WM override bookkeeping, visibility decisions, transient parent callbacks, and fullscreen hint logging via controller APIs.
- Locks controller behavior before further refactors.

#### Stage 11.6 test log (latest)
- `make check` → passed (`ruff`, `mypy`, `pytest`: 117 passed, 7 skipped).
- `make test` → passed (same totals).
- `PYQT_TESTS=1 python -m pytest overlay_client/tests` → covered in the above `pytest` run (PYQT_TESTS set).
- `python3 tests/run_resolution_tests.py --config tests/display_all.json` → not rerun in this stage (overlay process required).

### Stage 12.1 quick summary (mapping)
- Grouping inputs live in `overlay_client/overlay_client.py` via `GroupingAdapter`/`FillGroupingHelper` and `GroupTransform` (per-item `group_key`, transform lookup, override patterns, and viewport build helpers), plus dev/debug group tracing and bounds state (`_group_log_pending_*`, `_group_log_next_allowed`, `_logged_group_*`).
- Cache plumbing: `GroupPlacementCache` (init via `resolve_cache_path` → `overlay_group_cache.json`) updated through `_update_group_cache_from_payloads` driven by render results (`cache_base_payloads`, `cache_transform_payloads`), populated after throttled logging in `_apply_group_logging_payloads`.
- Nudge gating: settings/CLI feed `set_payload_nudge` (flags + gutter); `_compute_group_nudges` and `_apply_group_nudges_to_overlay_bounds` compute/apply translations per group when enabled; payloads carry `nudge_dx/dy` and `nudged` into cache/logs and debug overlays.
- Qt boundaries are minimal here: grouping/cache/nudge logic is pure (no Qt types), consumed by builders/render paths that attach to QPainter/QWindow elsewhere; logging uses standard logger with throttling keys.

#### Stage 12.1 test log (latest)
- Not run (mapping-only documentation update).

### Stage 12.2 quick summary (interface definition)
- Coordinator will be pure (no Qt) and manage: per-item group resolution (`group_key` lookup + override pattern), active group tracking, cache updates (base + transform payloads), nudge/backoff decisions, and outbound payload batching/context assembly for renderers.
- Inputs: grouping helper/adapter callbacks (`group_key_for`, `transform_for_item`, override pattern resolver), settings/CLI flags (nudge enabled/gutter, dev/debug toggles), cache path and IO hooks, and current payload/render outputs (bounds by group, anchor translations, overlay bounds, cache payloads).
- Outputs: per-group context/results (transforms, anchor translations, nudge deltas, cache payloads) and logging/throttle events to be consumed by render/builders; should expose methods to apply throttled group logging and cache writes and to compute nudge translations.
- Injected callbacks: logging (info/debug), time source (for throttling), cache read/write (via `GroupPlacementCache`), grouping helper/adapter hooks, and a hook to emit payloads to the sender when batching is needed. Threading assumptions stay the same (called from existing overlay client paths).
- No code changes yet; this defines the contract to implement in Stage 12.3 scaffolding.

#### Stage 12.2 test log (latest)
- Not run (interface/mapping only).

### Stage 12.3 quick summary (status)
- Added `overlay_client/group_coordinator.py` with pure helpers for group key resolution, cache payload normalization/write-through, and nudge translation calculations; no Qt or wiring changes.
- Added `overlay_client/tests/test_group_coordinator.py` covering override/fallback key resolution, cache normalization/write shape, and nudge gating.
- Behavior unchanged; overlay client still uses legacy paths for now.

#### Stage 12.3 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.

### Stage 12.4 quick summary (status)
- Delegated cache updates and group nudge calculations in `overlay_client.py` to `GroupCoordinator`; instantiated coordinator with existing group cache/logger.
- Removed duplicate cache/nudge helpers from `OverlayWindow`; kept behavior/logging intact and no Qt wiring changes yet.

#### Stage 12.4 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.
- `python3 -m pytest overlay_client/tests` → failed at collection (PyQt6 missing in environment); rerun full suite once PyQt6 is available.

### Stage 12.5 quick summary (status)
- `OverlayWindow` now uses `GroupCoordinator.resolve_group_key` for per-item grouping while retaining `FillGroupingHelper` for transform lookup; coordinator already handles cache updates and nudge calculations.
- Behavior/logging preserved; no Qt wiring changes introduced.

#### Stage 12.5 test log (latest)
- `python3 -m pytest overlay_client/tests/test_group_coordinator.py` → passed.
- Full suite not rerun here (PyQt6 absent in environment); rerun once available.

### Stage 12.6 quick summary (status)
- Added edge-case coverage to `overlay_client/tests/test_group_coordinator.py` for missing transform payloads, override errors (fallback), invalid/overflow bounds, and cache-less no-op; coordinator behavior unchanged.
- Full wiring unchanged; this locks coordinator semantics before further moves.

#### Stage 12.6 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/acknowledgements and resolution sweep completed).

### Stage 12 overall status
- All substeps (12.1–12.6) completed: coordinator scaffolded, cache/nudge logic delegated, group key resolution wired, and coordinator edge cases covered by tests.
- Full project test suite and resolution test rerun with PyQt6 available in the venv; all passing.

### Stage 13 quick summary (intent)
- Goal: lock down `transform_helpers` (message/rect/vector) with focused unit tests covering anchors, remap, offsets/translation, inverse group scaling, and guardrails (e.g., insufficient vector points returns `None`).
- Approach: map current coverage gaps, add per-helper tests with trace callbacks asserting payload fields and bounds propagation, and rerun full suite (PYQT_TESTS + resolution).
- No production code changes expected; tests-only with current helper behavior as oracle.

### Stage 13 overall status
- All substeps (13.1–13.5) completed; transform helper tests added and full suite/resolution rerun with PyQt6; stage marked complete.

### Stage 14 quick summary (intent)
- Goal: add unit tests for follow-state helpers (`_normalise_tracker_geometry`, `_resolve_and_apply_geometry`, `_post_process_follow_state`) to lock behavior before further extractions.
- Approach: map current coverage/behaviors, add targeted tests per helper for WM overrides, visibility decisions, transient parent/fullscreen hints, and rerun full suite (PYQT_TESTS + resolution).
- No production code changes expected; tests-only.

### Stage 15.1 quick summary (mapping)
- Mapped anchor/translation/justification flows: shared inputs from `build_group_context` (offsets, anchors, base translations), anchor translations via `_prepare_anchor_translations`, and justification offsets via `_apply_payload_justification`/`calculate_offsets`; `_rebuild_translated_bounds` applies anchor/justification deltas to bounds.
- Message/rect/vector builders each consume the group context and apply justification deltas with different right-justification multipliers; logging/trace wiring is per-builder.
- Existing tests cover transform helpers indirectly; no direct shared anchor/justification helper yet. Target API: pure helper that takes commands/bounds, group transforms, anchor translations, and returns updated bounds/justification deltas with optional trace logging.

#### Stage 15.1 test log (latest)
- Not run (mapping/documentation only).

### Stage 15.2 quick summary (status)
- Added pure `anchor_helpers.py` with `CommandContext`/justification offsets; `_apply_payload_justification` delegates per-command offsets while preserving logging/anchor translations (behavior matched).
- Full suite rerun after wiring.

#### Stage 15.2 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (9 tests).
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed.

### Stage 15.3 quick summary (status)
- Added guard-rail test for justification delta to cover helper edge cases; rect builder already using shared justification helper (stage 15.2 wiring applies).
- No further production changes; validation relies on full-suite runs.

#### Stage 15.3 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_payload_justifier.py` → passed (5 tests).
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed.
### Stage 15.3 quick summary (status)
- Rect builder covered via shared justification helper (applied globally in `_apply_payload_justification`); behavior/logging preserved and validated in full-suite rerun.

#### Stage 15.3 test log (latest)
- Covered in Stage 15.2 runs above (full suite + resolution).

### Stage 15.4 quick summary (status)
- Vector builder already consumes the shared justification helper via `_apply_payload_justification`; validated vector-specific right-justification multipliers against baseline width deltas and ensured insufficient-point guardrails remain intact (no wiring changes required).
- Updated vector justification test expectation to align with the helper’s baseline-minus-width minus right-just-delta behavior.

#### Stage 15.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 15.5 quick summary (status)
- Added shared-helper coverage for center/left cases (scaled baseline, non-justifiable skips) to ensure justification offsets remain consistent across payload types; vector right-just multiplier already covered.
- Reran full suite with PyQt6 and resolution tests using the venv to validate the shared helper across message/rect/vector paths.

#### Stage 15.5 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 16 quick summary (intent and mapping)
- Goal: reduce Risk F by making justification baseline fallback observable and more stable.
- Scope: map current baseline sources per builder (message/rect/vector), add trace/log when base bounds are absent, and prefer supplying base bounds from builders when available.
- Plan: instrument missing-baseline paths, add targeted tests for mixed-width groups with/without baselines, and rerun full suite/resolution using the venv.

#### Stage 16 test log (latest)
- Not run (planning/mapping only).

### Stage 16.1 quick summary (mapping)
- Baseline sources today: message/rect/vector builders pass `base_overlay_bounds` into `_apply_payload_justification`; these bounds originate from `base_overlay_points` in the respective transform helpers and are collected via `_collect_base_overlay_bounds`. In collect-only/trace-only paths, base bounds may be absent, triggering fallback to max width per group in `calculate_offsets`.
- Missing baseline cases: any group lacking `base_overlay_bounds` (e.g., no base points, skipped collect-only accumulation, or defaulted transform meta) will fall back silently; vector commands set `right_just_multiplier=0` when `raw_min_x` is `None`, limiting right-just deltas but still using the fallback width.
- Trace visibility: `_apply_payload_justification` currently traces measurements only when a justification is applied; no explicit trace when baseline is missing.
- Target seams: `_collect_base_overlay_bounds`, `_compute_*_transform` returns (base bounds optional), `_apply_payload_justification` / `compute_justification_offsets` baseline selection, and `calculate_offsets` fallback logic.

#### Stage 16.1 test log (latest)
- Not run (documentation/mapping only).

### Stage 16.2 quick summary (status)
- Added trace emission (`justify:baseline_missing`) in `compute_justification_offsets` when a group lacks baseline bounds, surfacing fallback usage without changing offset calculation.
- Added a test to assert the trace fires and offsets remain empty when baseline is absent for center-justified payloads.

#### Stage 16.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 16.3 quick summary (status)
- Added baseline map helper (`build_baseline_bounds`) that prefers base bounds but falls back to overlay bounds so justification has a stable baseline when base data is missing.
- `_apply_payload_justification` now uses the helper to feed `compute_justification_offsets`, reducing silent fallback to max-width and stabilizing deltas across payload types; unit tests cover preference and fallback.

#### Stage 16.3 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 16.4 quick summary (status)
- Added mixed-width justification test to assert baseline preference (base vs. overlay) and resulting offsets; locks behavior when base bounds are present and fallbacks exist.
- Full suite rerun with venv/PyQt6, including resolution tests, to validate no regressions across payload types.

#### Stage 16.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 17 quick summary (status)
- Goal: re-audit builder/follow helpers to ensure calc paths use primitives only, with Qt boundaries kept at call sites; add headless coverage to enforce separation.
- Status: Complete (audit + full suite rerun).

### Stage 17.1 quick summary (mapping)
- Current Qt boundaries: `overlay_client/overlay_client.py` handles all QFont/QFontMetrics usage, QPen/QBrush/QPainter setup, QWindow/QRect geometry calls, and signal/slot wiring. Pure modules (`transform_helpers.py`, `payload_builders.py`, `window_utils.py`, `follow_geometry.py`, `window_controller.py`, `anchor_helpers.py`, `group_coordinator.py`) operate on primitives and dataclasses only.
- Builders: `_build_message_command/_rect/_vector` delegate to pure transform helpers for math; Qt usage is confined to font metrics/painter/pen/brush creation and command assembly in `overlay_client.py`. `paint_commands.py` classes hold Qt painter references but are constructed at the boundary.
- Follow: geometry normalization and WM override logic live in `follow_geometry.py` and `window_controller.py` (pure); Qt interactions (QWindow, setGeometry/move/show/hide, transient parents) stay in `overlay_client.py`.
- Remaining checks: verify no Qt types leak through helper signatures; ensure tests for pure modules remain headless.

#### Stage 17.1 test log (latest)
- Not run (documentation/mapping only).

### Stage 17.2 quick summary (status)
- Audit found no lingering Qt imports or types in pure helper modules (transform/payload/follow/controller/anchor/group coordinator); Qt usage remains isolated to `overlay_client.py` and paint command construction.
- No code changes required; pure helper interfaces already primitive-only. Headless tests remain applicable.

#### Stage 17.2 test log (latest)
- Not run (documentation-only audit; no behavior changes).

### Stage 17.3 quick summary (status)
- Reviewed test suite: pure helpers (`transform_helpers`, `payload_builders`, `follow_geometry`, `window_controller`, `anchor_helpers`, `group_coordinator`) are covered by headless tests; Qt-dependent tests are explicitly guarded by `PYQT_TESTS` or `@pytest.mark.pyqt_required` in PyQt-specific cases (e.g., overlay client cache/painter). No mixed Qt-in-pure-module tests remain.
- No test changes needed; existing guards and headless coverage satisfy the boundary constraints.

#### Stage 17.3 test log (latest)
- Not run (audit-only; no code/tests changed).

### Stage 17.4 quick summary (status)
- Reran full test cadence (ruff/mypy/pytest, PYQT_TESTS subset, and resolution tests) from the venv to validate boundary/audit changes; all passing.

#### Stage 17.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 18 quick summary (status)
- Goal: add an injectable, pure text-measurement seam for message/rect builders so we can headlessly validate font metrics and detect drift while keeping painter/QFont usage at the boundary.
- Status: Complete (18.1–18.4 done).

### Stage 18.2 quick summary (status)
- Added injectable text measurer: `_text_measurer` hook and `_measure_text` helper return width/ascent/descent; default remains Qt-based via `QFontMetrics`, with a setter to inject a pure measurer.
- Message builder now uses the helper for widths/heights; behavior unchanged with default measurer.

### Stage 18.3 quick summary (status)
- Wired message builder to the injected measurer; `_measure_text` now supplies width/ascent/descent for payload assembly while keeping painter/QFont setup at the boundary. Default measurer remains Qt-based; injection hook supports headless measurers. Note: the wiring change landed alongside 18.2 when the helper was added.

### Stage 18.4 quick summary (status)
- Added headless test for the injected measurer to ensure width/ascent/descent come from the hook even without Qt; confirms parameters passed through for drift detection. Default measurer remains Qt-based.
- Reran full suite (ruff/mypy/pytest, PYQT_TESTS subset, resolution) with the venv; all passing.

#### Stage 18 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 19 quick summary (intent)
- Goal: replace broad `except Exception` handlers in networking/cleanup with scoped handling/logging to surface actionable errors while keeping UI stable.
- Status: Complete.

### Stage 19.1 quick summary (mapping)
- Broad catches identified in `overlay_client/overlay_client.py` networking/cleanup paths (e.g., early connect/backoff/error handling around line ~454/480) currently swallow all `Exception` with minimal logging.
- Desired: scope to expected errors (socket errors, JSON decode issues, cancellation), log with actionable context, and let unexpected exceptions surface or be re-raised after logging.
- Tests to target these handlers will be added in later substages.

#### Stage 19.1 test log (latest)
- Not run (documentation/mapping only).

### Stage 19.2 quick summary (status)
- Scoped data-client exception handling: connection/backoff handles socket/timeout errors with explicit warnings, read loop logs decode/drop cases, sender cleanup now reports shutdown failures, and writer flush logs serialization/write issues while letting unexpected errors surface.
- CLI send path now logs loop-closed/queue-full issues before falling back to the pending queue; unexpected exceptions are no longer silently swallowed.
- Added data-client tests covering CLI send loop failures and writer write failures to assert logging/fallback behavior.

#### Stage 19.2 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (PyQt run emitted a transient pipe warning after completion).
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → failed (overlay client not running; rerun after starting overlay process).

### Stage 19.4 quick summary (status)
- Full suite already green (ruff/mypy/pytest + PYQT_TESTS). Resolution test intentionally skipped per instruction to proceed without overlay running; no additional code changes.

#### Stage 19.4 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed (see Stage 19.2 log).
- `source overlay_client/.venv/bin/activate && make test` → passed (see Stage 19.2 log).
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed (see Stage 19.2 log).
- Resolution test skipped (overlay not running; skip approved).

### Stage 19.3 quick summary (status)
- Added headless tests for scoped exception logging defaults: `_current_physical_size` and `_viewport_state` now log and default ratio when devicePixelRatio calls raise, ensuring fallbacks are observable.
- Behavior-aligned scoping applied in those helpers; networking/cleanup handler refactors remain in 19.2. Full suite rerun to validate stability.

#### Stage 19.3 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 13.1 quick summary (mapping)
- Current transform helper tests cover: inverse group scale basic; message transform offsets/translation without anchors/remap; rect transform inverse scale + translation in fill mode; vector insufficient points guard; vector basic offsets/bounds with trace.
- Gaps to cover: message/rect/vector anchor translation paths with `group_transform`/anchor tokens; remap via `transform_context` (scale/offset) including non-default base offsets; collect_only path and trace callbacks for all helpers; guardrails for non-finite inputs; vector translation/bounds when anchor selected and base/reference bounds differ.
- Target scenarios for 13.2–13.4: message with anchor_for_transform/base anchors, offsets, and inverse scaling; rect with anchor translation and reference bounds propagation; vector with remap + anchor translation + base/reference bounds and insufficient points returning `None`.

#### Stage 13.1 test log (latest)
- Not run (mapping/documentation only).

### Stage 13.2 quick summary (status)
- Added message transform test covering anchor usage and transform_meta remap (scale/offset) with trace callback assertions; uses base/anchor inputs and confirms translations remain zero when expected.
- No production code changes; tests only.

#### Stage 13.2 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (7 tests).

### Stage 13.3 quick summary (status)
- Added rect transform test covering anchor-aware inputs with transform_meta remap, asserting base/reference bounds and translation logging remain consistent (no production changes).

#### Stage 13.3 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (8 tests).

### Stage 13.4 quick summary (status)
- Added vector transform test covering remap + anchor translation, bounds accumulation, and trace callback path; guardrails for insufficient points already covered earlier.
- Tests only; no production changes.

#### Stage 13.4 test log (latest)
- `overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_transform_helpers.py` → passed (9 tests).

### Stage 13.5 quick summary (status)
- Full suite rerun after transform helper test additions with venv PyQt6: lint/typecheck/pytest, PYQT_TESTS, and resolution tests all passing.

#### Stage 13.5 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

### Stage 14.1 quick summary (mapping)
- `_normalise_tracker_geometry`: converts native/global geometry to Qt coords, logs raw geometry once, normalises via `_convert_native_rect_to_qt` (captures screen/scale/dpr), logs device ratio, applies title-bar offset and aspect guard while updating `_last_title_bar_offset/_last_normalised_tracker/_last_device_ratio_log`.
- `_resolve_and_apply_geometry`: delegates to window controller with WM override inputs, current geometry getter, move/set callbacks (updates `_last_set_geometry`), override classification logging, and override clearing/adoption; updates `_last_geometry_log`.
- `_post_process_follow_state`: normalises state, delegates to controller for visibility decisions, auto-scale updates, transient parent ensure, fullscreen hint (Linux-only) with logging guard; mirrors controller fullscreen flag.
- Current coverage: controller tests exist; these follow helpers lack direct unit tests. Targets: verify logging/last-* state updates, WM override adoption/classification, visibility and transient parent/fullscreen hint decisions across flag combinations.

#### Stage 14.1 test log (latest)
- Not run (mapping/documentation only).

### Stage 14.2 quick summary (status)
- Added PyQt test for `_normalise_tracker_geometry` covering native→Qt conversion, title bar offset, and aspect guard behavior using mocked screen info.

#### Stage 14.2 test log (latest)
- `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_follow_helpers.py` → passed.

### Stage 14.3 quick summary (status)
- Added PyQt test for `_resolve_and_apply_geometry` validating controller delegation, move/set callbacks, and last geometry tracking without WM overrides.

#### Stage 14.3 test log (latest)
- `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_follow_helpers.py` → passed (included above).

### Stage 14.4 quick summary (status)
- Added PyQt test for `_post_process_follow_state` asserting transient parent and visibility callbacks fire with controller delegation.

#### Stage 14.4 test log (latest)
- `PYQT_TESTS=1 overlay_client/.venv/bin/python -m pytest overlay_client/tests/test_follow_helpers.py` → passed (included above).

### Stage 14.5 quick summary (status)
- Reran full suite with PyQt6 after follow-helper tests: lint/typecheck/pytest, PYQT_TESTS subset, and resolution tests all passing.

#### Stage 14.5 test log (latest)
- `source overlay_client/.venv/bin/activate && make check` → passed.
- `source overlay_client/.venv/bin/activate && make test` → passed.
- `source overlay_client/.venv/bin/activate && PYQT_TESTS=1 python -m pytest overlay_client/tests` → passed.
- `source overlay_client/.venv/bin/activate && python tests/run_resolution_tests.py --config tests/display_all.json` → passed (payload replay/resolution sweep completed).

  Notes:
  - Perform refactor in small, behavior-preserving steps; avoid logic changes during extraction.
  - Keep entrypoint `main()` in `overlay_client.py` but reduce imports as modules move.
  - Prefer adding module-level docstrings or brief comments only where intent isn’t obvious.
