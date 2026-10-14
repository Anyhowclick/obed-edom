# W5 command/UI report

## Files changed

- `src/obed_edom/web/live.py`
  - Accepts `operation: "recalibrate"` with the existing optional `slide` field.
  - Passes `calibration=managed.calibration_adapter()` only through the already-ready managed-OBS host construction path.
- `src/obed_edom/live_session.py`
  - Adds `recalibrate` to loading/default/applied capability sets and command validation.
  - Treats recalibration as a scheduling command: no player-busy publication, no `pending_navigation`, no `pending_visibility`, immediate `completed` after the adapter returns its scheduling observation, and a revision bump even if that observation is otherwise unchanged.
  - Preserves the existing request-ID replay/conflict cache, in-flight coalescing, capability rejection, and prompt Stop path.
- `tests/test_live_api.py`
  - Adds a fake calibration adapter and managed-only capability behavior.
  - Verifies exact router injection, managed/screen capability propagation, null slide tolerance, non-null slide rejection, probing output, scheduling completion, already-running rejection, and request-ID replay without duplicate scheduling.
- `tests/test_live_session.py`
  - Verifies an in-flight duplicate is coalesced, the completed replay is cached, only one adapter call is made, revision/status/scene/visibility are preserved, neither pending map is used, placement probing is published, and a new request is rejected while probing.
- `dashboard/src/live/api.ts`
  - Adds `recalibrate` to `LiveOperation`.
  - Adds the frozen `Placement` shape and optional `output.placement`.
- `dashboard/src/live/LivePresenter.tsx`
  - Adds the `Recalibrate output` control and exact frozen operator states: `Calibrating…`, `Output calibrated`, `Output not calibrated`, failure, suppression, unsupported, deferred-transition, and disconnected copy.
  - Uses the existing capability/connection/session guards; a probing calibration disables only recalibration, leaving navigation, Hide, and Stop available.
  - A scheduling `completed` response does not enter awaiting-navigation UI.
- `dashboard/tests-ui/live-presenter.ui.test.tsx`
  - Adds one table covering all placement/status/capability states, retry/send behavior, exact disabled reasons, and continued navigation/Hide/Stop availability during probing.

Generated dashboard `dist` output and the npm lockfile were restored after verification and are not W5 changes.

## Frozen-contract mapping

- §11.4 request/response and no-slide wire: `CommandBody` plus the existing commands route in `web/live.py`; service responses remain `{requestId,outcome,reason?,state}`.
- §11.4 managed adapter injection: ready-keyer branch in `web/live.py` passes `managed.calibration_adapter()` to the managed host.
- §11.4 scheduling acknowledgement, revision publication, no navigation/visibility acknowledgement, and request-ID replay: `LiveSessionService.command()` / `_run_command()` in `live_session.py`.
- §11.4 capability propagation/defaults: `_disabled_capabilities()` and `_apply_capabilities()` in `live_session.py`; actual owned/ready/probing eligibility remains the W4 host's contracted responsibility.
- §11.3 placement JSON pass-through: `PlayerObservation.output` remains copied unchanged by the service; the additive TypeScript `Placement` type exactly covers the frozen fields and `output.placement` is optional for old snapshots.
- §11.4 presenter copy and controls: `PlacementStatus` and `send("recalibrate")` in `LivePresenter.tsx`.

## Deviations from §11

None in W5-owned code. No Keynote player file was edited and no alternate route/protocol was introduced.

## Verification

- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_api.py tests/test_live_session.py -q -n 2 -p no:cacheprovider`
  - **82 passed, 0 failed** in 0.89 s.
- `cd dashboard && PATH=$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run test:ui`
  - **44 test files passed; 329 tests passed, 0 failed** in 6.85 s.
  - Existing non-failing jsdom stderr appeared for shader-failure fixtures and unimplemented document navigation.
- `cd dashboard && PATH=$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npx tsc --noEmit`
  - **Passed, 0 diagnostics**.
- `cd dashboard && PATH=$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run build`
  - **Passed**, 134 modules transformed; only Vite's existing large-chunk advisory.
- `cd dashboard && PATH=$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm install`
  - **Passed**, already up to date.
- `git diff --check`
  - **Passed**, no whitespace errors.

No full suite, OBS, Chrome/headless browser, Keynote, run gates, or known external-red rows were run, per stream instructions.

## Open items for the coordinator

- Integrate W4's host half of §11.4: `LiveOutputHost.capabilities()` must publish the exact managed-only/already-probing capability and `execute("recalibrate", None)` must return the scheduling observation. At W5 handoff, the parallel `live_host.py` work had the calibration constructor/state but no `recalibrate` command string yet; W5 tests intentionally use contract fakes.
- Run the coordinator's cross-stream integration/full-suite and gate sequence after W1–W6 settle.
