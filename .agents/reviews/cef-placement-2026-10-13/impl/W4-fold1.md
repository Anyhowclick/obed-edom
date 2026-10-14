# W4 review round 1 fold

## Files changed

- `src/obed_edom/live_host.py`
- `tests/test_live_host.py`

No other stream-owned file was edited. The worktree also contains concurrent changes in W1/W2/W3/W6-owned files; those were left untouched.

## Product review findings

1. **Folded (W4 side).** `_complete_probe` now evaluates an explicit `program.ok is False` and `isolation_ok is False` before testing for absent evidence. Either condition suppresses automatic probes even when `evidence is None`; a precheck-style no-evidence result with program/isolation still good remains an ordinary `probe-failed` and does not suppress. The state-machine test covers all three rows. The review's W3-side requirement to distinguish post-mutation isolation mismatch from refusal/transport failure belongs to `managed_obs.py` and was not changed by W4.

2. **Folded.** Added `_last_engine`, which retains the last non-`None` launch identity. A transient `X -> None -> X` revokes/cancels and clears the automatic request key but does not clear launch-scoped suppression. Only a different non-`None` launch identity resets suppression. The state-machine test covers transient loss, reload, restoration of the same identity, and a genuinely new launch.

3. **Folded.** Program media telemetry now uses a `WeakMap` keyed by element with synthetic IDs. Paused, ended, and not-ready elements end a segment; loop wraps start a new segment; stall accounting runs only on an active playing segment. A Node-backed row exercises two same-source elements (one paused), a loop wrap, and natural end. `_prepare_navigation_placement` cancels an in-flight calibration and clears its automatic key before advance/goTo; the reconnect-during-advance row verifies cancellation and successful input delivery.

4. **Folded.** `_revoke_placement` now distinguishes `revoked`, responsive `compromised`, and transport `disconnected`. A reconnect revoke timeout records `disconnected`, retains `_reconnect_revoke_required`, and does not issue `window.__obedOutput.hide()`. Only a responsive non-`invalid` answer produces `channel-compromised` and hides/refuses Show. The state-machine test injects a reconnect revoke timeout while the fake output is visible and verifies it remains visible.

5. **Folded.** `execute` re-reads `_require_transport()` after `observe()`, so a reconnect performed by that observation supplies the transport used for `_execute` and `_log_execute`. The state-machine row drops the first `__obedLive` evaluation during `execute("advance")`, reconnects, and verifies Space reaches the replacement transport.

6. **Folded.** Added `_placement_epoch`, advanced by revoke, schedule, finish/discard, reconnect, cancellation, and Stop transitions. Probe completion and renewal capture the epoch and recheck it before commit/state publication; renewal also rechecks after the reply before interpreting or publishing it. Probe completion conditionally discards only its own obsolete run. Tests block classification across a reload and a renewal reply across recalibration; neither can publish stale `valid`/`leaseLapsed` state over the newer transition.

7. **Folded.** All probe-path revoke failures retain `_reconnect_revoke_required`. `_schedule_probe` now revokes before allocating/registering a run and returns without starting on failure. Commit/fingerprint/Stop failures preserve the reconnect requirement. A test injects a recalibration revoke timeout, verifies no adapter start and `disconnected`, then verifies the retry path can proceed after transport recovery.

8. **Folded.** Renewal wraps `_program_context()` failure as lapsed/unreadable input handling, checks epochs around every terminal state write, and `_start_renewal_thread` refuses to clear/start after `_stopped`. `stop()` sets `_stopped`, the epoch, and the renewal event under `_placement_lock`. The Stop row calls `_start_renewal_thread` again and verifies no new worker is created.

9. **Folded.** `_AssetServer.set_probe_run(None, run_id=...)` clears only the matching registered run. Every completion/failure/success clears server assets while its run ID is still held under `_placement_lock`; the old unconditional completion `finally` was removed. The asset-server test proves an old run cannot clear a replacement run.

10. **Folded.** `_measure_probe` now detaches its separate probe CDP transport. It no longer calls attach-mode `stop()`, so it does not navigate the calibration target to `about:blank`. The measurement test asserts detach and asserts that stop/navigation teardown was not used.

12. **Folded.** Stop-time placement revoke and the `stopped` placement reason are restricted to probe mode. The Chrome knowledge-mode Stop test snapshots placement and verifies it remains unchanged, preserving the existing Chrome reason vocabulary and behavior.

13. **Folded.** A successful managed reconnect publishes `not-calibrated`; a delayed successful required-revoke retry also changes `disconnected` to `not-calibrated`. The suppression/reconnect row verifies the connected suppressed session does not remain labelled disconnected.

14. **Folded.** Probe target URL lookup now defaults to `None` and fails closed. Probe FPS comes from `managed_obs.RATES[rate][1]`. PNG dimensions are checked from `source.size` before RGBA conversion.

15. **Folded.** Removed unused `_probe_manual` and `_ProgramGuard._last` state.

16. **Folded.** Replaced the vacuous `window.M` row with probe-mode post-mutation lease enforcement and a knowledge-mode leased-`frac` rejection. Added a post-grant reassignment of both `performance.now` and `Performance.prototype.now`; the bound pre-page clock still expires the lease. Added host coverage for findings 1, 2, 5, and 7, plus reconnect-timeout, epoch, conditional asset cleanup, detach, and Chrome Stop regression rows.

## Probe review finding 1 (W4 fixture)

**Folded.** `tests/test_live_host.py` now mirrors the shipped page's contain-fit arithmetic: for the 1920x540 video in a 480.53125x135.140625 CSS rect, height is limiting, so `cw = 1920 * (135.140625 / 540) = 480.5`, `ch = 135.140625`, and `cx = rect.x + (480.53125 - 480.5) / 2 = rect.x + 0.015625`; `cy = rect.y`. This was confirmed against `placement_probe.py`'s `geometry()` implementation, which uses exactly `f=min(r.width/vw,r.height/vh)` and the centered contain box.

## Deviations and cross-stream items

- No W4 frozen-contract deviation.
- Product finding 1's requested W3 error taxonomy/capture behavior is outside W4 ownership (`src/obed_edom/managed_obs.py`) and was left to W3; W4 now consumes the resulting `program`/`isolation_ok` fields in the required order.
- Product finding 11 was not assigned to W4 in this fold request and requires W3 ownership/process-probe changes; no W4 change was made for it.

## Verification

Authorized command:

`env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_host.py -q -n 2 -p no:cacheprovider`

- First fold run: **344 passed, 2 failed**. Both failures were new-test defects: an attach-host assertion expected a slide mapping the fixture does not have, and the knowledge rejection expected the wrapper expression's `null` instead of testing the channel's boolean directly.
- Second fold run: **345 passed, 1 failed**. The remaining race test exposed a real ordering bug: a stale renewal interpreted its post-revoke `null` before its epoch recheck and published `leaseLapsed` over `probing`.
- Focused diagnostic: **1 failed** (`-k managed_probe_state_machine`), confirming `leaseLapsed` as the stale write.
- Focused post-fix check: **1 passed** (`-k managed_probe_state_machine`).
- Full post-fix run: **346 passed, 0 failed**.
- Final full run after completion-epoch and stopped-start hardening: **346 passed, 0 failed** in 2.12 s.
- `git diff --check -- src/obed_edom/live_host.py tests/test_live_host.py`: pass.
- `.venv/bin/python -m py_compile src/obed_edom/live_host.py tests/test_live_host.py`: pass.

No OBS, Chrome/headless browser, Keynote, full suite, or gate runner was invoked.

## Open items for the coordinator

- Confirm W3 folded product finding 1's isolation taxonomy and removed the blanket `capture_png` exception-to-isolation mapping.
- Confirm W3/W6 disposition of unassigned product finding 11.
- The coordinator should run cross-stream/full gates after all six fold streams land; W4's authorized host suite is fully green.
