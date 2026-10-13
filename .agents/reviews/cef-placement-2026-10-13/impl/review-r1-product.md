# Code review r1 — CEF/OBS placement, product files (Opus 5.5, HIGH)

Scope: `git diff 99d53542 ecb1de98` for `live_runtime.py`, `live_host.py`, `managed_obs.py`, `obs_websocket.py`,
`web/live.py`, `live_session.py`, `dashboard/src/live/*` and their tests. Line numbers are at `ecb1de98`.
Targeted suites run: `test_live_host/managed_obs/live_session/live_api/obs_websocket/live_runtime` → 699 passed, 3 failed
(the known census reds in `test_live_runtime`, not this PR).

Verdict: **1 major, 6 medium, 9 low.** No false grant into a new document was found: the page-side lease, the
`_placement_renew_expr` "still equal" guard and uniqueContextId-bound commit hold under every race I traced. The defects
are in the suppression contract, how revoke failures are handled, which threads can change host state, and on-air
behaviour after a reconnect.

Verified as correct: W1 `frac` admission/draw matches §2.6/§11.5 exactly (one `pl` read, underlay then quad, whole-backing
alpha scan, `dx/dy` preserved); the O1 split drops `__obedFreezeTake`/`__obedFreeze` and both call-site replacements.
The stricter `_apply_replacements` count check is fine. Chrome knowledge channel semantics are unchanged (round trip still
`true,snap,true,invalid`; `frac`/ms rejected). Lock ordering has no deadlock: no CDP under `_placement_lock`, ManagedObs
`_lock` is an RLock and is never held across waits, and Stop holds nothing cleanup needs. Session recalibrate never
touches `pending_navigation`/`pending_visibility` and replays by request ID. JSON field names and enums match §11.3
and `api.ts`. No Python 3.10 incompatibilities. Style: no new inline comments; the docstrings are minimal.

---

### 1. major — new class — suppression is unreachable when a disturbed/isolation-failed run has no evidence
- **Where:** `src/obed_edom/live_host.py:2083–2091` (`_complete_probe` order); `src/obed_edom/managed_obs.py:1291`, `:1305`, `:641`.
- **Scenario:** `_complete_probe` returns `probe-failed` (no suppression) on `result.evidence is None` **before** it looks at
  `program.ok` or `isolation_ok`. Any isolation verification failure (`_verify_calibration_isolation` during install or
  inside `capture_png`) raises out of `measure`, so evidence is always `None` whenever isolation actually failed. W3's own
  `program-change` row confirms this (`evidence None`, `isolation_ok False`). The `isolation-failed` + suppression branch is
  therefore dead in practice. A Studio-toggle stutter (`program.ok False`) in a run whose measurement also aborts (likely,
  because disturbance and timeouts go together) also lands on `probe-failed`. Result: automatic probes keep firing on the
  next reload or reconnect after an on-air disturbance, which is what §2.3/§11.3 "Runtime moving/isolation failure →
  automaticProbesDisabled" exists to stop. Host tests only cover `program=False` *with* evidence
  (`tests/test_live_host.py` state-machine test).
- **Fix:** In `_complete_probe`, evaluate `result.program is not None and result.program.ok is False` → `program-disturbed`
  (suppress) and an isolation violation → `isolation-failed` (suppress) **before** the `evidence is None` check. In W3, report
  isolation separately from refusal and transport errors. Keep `isolation_ok` true through prechecks/refusals (bad-output,
  transition-active and preview-unreadable must not suppress). Set it false only when a post-mutation isolation/identity
  comparison in `_verify_calibration_isolation`/`_verify_offcanvas_transform`/cleanup readback finds a mismatch, not when a
  request times out or is cancelled. In `capture_png`, drop the blanket `except Exception: isolation_ok=False`. Add host
  rows: `evidence=None` + `program.ok=False` → suppressed; `evidence=None` + isolation violation → suppressed; `evidence=None`
  + precheck refusal → not suppressed.

### 2. medium — edge case — a transient engine state clears launch-scoped suppression
- **Where:** `src/obed_edom/live_host.py:1727–1734`; `src/obed_edom/managed_obs.py` `_calibration_identity` (returns `None`
  unless `_state == "ready"` and `_identity()` is `"ours"`).
- **Scenario:** `_liveness` moves the same OBS launch `ready → blocked` (pageLost/obsUnreachable/identityUnknown/
  deviceInactive), or `_identity` reads `"unknown"` once. `identity()` goes X → None → X with unchanged pid/launch
  date/ready generation. Both transitions take the `engine != self._engine_identity` branch, which resets
  `automaticProbesDisabled=False`. The next reload or reconnect (new context/generation key) then probes automatically on a
  launch the plan says must stay suppressed ("only a new engine launch resets it"). As a side effect, X → None also revokes
  a valid grant, and because `_automatic_probe_key` still matches, no probe follows until a reload.
- **Fix:** Track the last non-None identity (`_last_engine`). Clear suppression only when a non-None identity differs from
  it. On None, revoke/cancel but keep `_engine_identity`/suppression. Add a host row: X → None → X with suppression set →
  still suppressed after a reload.

### 3. medium — new class — Program guard reports ordinary program activity as disturbance (then suppresses)
- **Where:** `src/obed_edom/live_host.py:1049–1055` (guard JS); no cancel in `_prepare_navigation_placement`
  (`live_host.py:2486`).
- **Scenario:** Media records are keyed by `v.id||v.currentSrc||"video-"+i`. Two elements with the same asset (one
  playing, one paused or preloaded) share one record: the paused element hits `else if(m.playing)m.monotonic=false`, and
  their differing `currentTime`s trip the monotonic check. A looping movie wrapping (`ct < lastTime`), a movie reaching its
  end, or an operator advance/goTo during the probe (allowed; the probe is not cancelled) also sets `monotonic=false` or
  causes a rAF gap of more than 2× baseline. If the measurement succeeds, `_complete_probe` → `program-disturbed`,
  `automaticProbesDisabled=true` for the launch. With realistic on-air content, the result is frequent false suppression and
  "Calibration paused".
- **Fix:** Key media records per element (a `WeakMap` with a synthetic id), never by `currentSrc`/index. Count stalls only
  while `!paused && !ended`, and treat a pause, end or loop wrap (`v.loop && ct < last`) as a segment boundary, not
  non-monotonic. In `_prepare_navigation_placement` (or `execute` for advance/goTo), cancel an in-flight probe with reason
  `cancelled` (no suppression) and clear `_automatic_probe_key`, so the automatic probe reschedules once the player is not
  busy. Add guard rows: shared-src paused+playing, loop wrap and natural end → `ok True`.

### 4. medium — edge case — a reconnect revoke *timeout* is treated as channel compromise and hides the output
- **Where:** `src/obed_edom/live_host.py:1621–1625`.
- **Scenario:** `observe()` fails because the CEF renderer stalls (15 s timeout) → `_reconnect_managed_transport` →
  `_revoke_placement(context)` hits its 1 s deadline → `False` → `channel-compromised` + `evaluate("window.__obedOutput.hide()")`.
  The hide was already sent, so CDP does not cancel it on a host-side timeout. When the renderer recovers, it executes and
  blanks the program on air. `channel-compromised` then refuses Show for the session (`live_host.py:2477`). Before this PR
  the same stall left the output visible. `_revoke_placement` returns `False` both for "no answer" and for "channel answered
  wrongly", so the two cannot be told apart.
- **Fix:** Have `_revoke_placement` return a tri-state (or raise on transport failure). In reconnect, treat
  timeout/LiveHostError as `disconnected` with `_reconnect_revoke_required=True` and **no hide**. Reserve
  `channel-compromised` + hide for a responsive channel returning a value other than `"invalid"` (null/missing updater).

### 5. medium — edge case — `execute` keeps the pre-reconnect transport
- **Where:** `src/obed_edom/live_host.py:2406–2408` (`transport = self._require_transport()` before `before = self.observe()`),
  then `_execute(operation, slide, transport, …)`.
- **Scenario:** The CDP socket drops just before an operator Advance. `execute`'s own `observe()` reconnects successfully
  (new `self._transport`), but `_execute` sends input on the detached old object → `LiveHostError("Program browser stopped
  unexpectedly.")`. That is not a `PlayerCommandRejected`, so `LiveSessionService._fail` puts the session into `error` and
  the presentation is dead, even though the reconnect itself worked.
- **Fix:** In `execute`, re-read `transport = self._require_transport()` after `before = self.observe()` (and use it for
  `_log_execute`). Add a host row: the first `__obedLive` evaluate inside `execute("advance")` fails → reconnect → advance
  succeeds on the replacement.

### 6. medium — new class — host placement state is updated from three threads without an epoch (lost updates)
- **Where:** `src/obed_edom/live_host.py:2242` (renewal's final `_set_placement(grant,"granted")`), `:2178–2186`
  (`_complete_probe` success after clearing `_probe_run_id`), vs `_schedule_probe`/`_sync_probe_placement`/reconnect on the
  session thread.
- **Scenario:** The renewal thread snapshots `valid` and sends the renew expression. Meanwhile the operator presses
  Recalibrate: `_schedule_probe` revokes the page and publishes `probing`. Renewal then writes `valid/granted` (if its
  evaluate ran before the revoke), or `invalid/leaseLapsed` over `probing` (if after). Either way product JSON breaks
  §11.3 ("state probing never advertises a grant"). While stuck at `valid`, `_sync_probe_placement` returns early and never
  starts a deferred (`waiting-for-transition`) probe. Similarly, `_complete_probe` can publish `valid` after the session
  thread has moved `_placement_context` to a new document. The page stays safe (renew requires equality, commit is
  context-bound), but host state and W6 `life-cal-*` evidence can be wrong for up to one renewal period.
- **Fix:** Add a `_placement_epoch` incremented under `_placement_lock` by every revoke/schedule/finish/reconnect/stop
  transition. Renewal and `_complete_probe` capture it with their snapshot, and inside `_placement_lock` immediately before
  the final `_set_placement` (and before sending the renew expression) bail with no state change if it moved. Also make
  `_start_renewal_thread` a no-op when `_stopped` (see 8).

### 7. medium — edge case — failed revokes are ignored, so "revoke before every probe" is not enforced
- **Where:** `src/obed_edom/live_host.py:1783` (`_schedule_probe`), `:2151`, `:2169`, `:2173` (`_complete_probe` failure
  paths), `:2629` (stop), `:1757–1758` is the only path that sets `_reconnect_revoke_required`.
- **Scenario:** Recalibrate on a valid `frac` grant: `_schedule_probe`'s revoke times out (1 s, lock contention). The page
  keeps the old lease for up to 15 s while the host shows `probing`/`invalid`, and renewal has stopped. A take in that
  window uses a grant the host has already withdrawn. If the new probe then fails, the "never restores the previous result"
  rule is broken for the remaining lease. The same applies when a commit evaluate times out after it executed page-side
  (`:2169`): the host says `stale-result` while the page holds a fresh 15 s lease.
- **Fix:** Wherever `_revoke_placement` returns False on a context that is still current, set
  `_reconnect_revoke_required = True`. Navigation already enforces that flag. In `_schedule_probe`, if the revoke fails, do
  not start the probe (`disconnected`, retry on the next sync).

### 8. low — edge case — renewal thread lifecycle
- **Where:** `src/obed_edom/live_host.py:2218` (`self._program_context()` outside try → `_require_transport()` raises while
  `_transport is None` during reconnect); `:2189–2195` (`_start_renewal_thread` clears `_renew_stop`).
- **Scenario:** (a) The renewal thread dies with an uncaught `LiveHostError` mid-reconnect. No `leaseLapsed` is logged and
  nothing renews until the next grant. (b) `_complete_probe` passes its `_stopped` check just before `stop()`, commits and
  calls `_start_renewal_thread()`, which clears the stop event and starts a thread that `stop()` never joins. That thread
  then loops forever.
- **Fix:** Wrap the context read in `_renew_probe_lease` (exception → `leaseLapsed`). In `_start_renewal_thread`, return
  without clearing or starting under `_placement_lock` when `self._stopped`, and have `stop()` set `_stopped` under the same
  lock.

### 9. low — edge case — a finishing probe can clear a newer run's server files
- **Where:** `src/obed_edom/live_host.py:2067`.
- **Scenario:** `_finish_probe_state`/success clears `_probe_run_id`. Before the `finally` calls `set_probe_run(None)`, the
  session thread schedules and starts a new run (`set_probe_run(new)`). The old `finally` then wipes it, so the new probe
  page 404s and that run fails.
- **Fix:** `set_probe_run(None, run_id=…)` should clear only when the registered run matches, and the server run should be
  cleared before `_probe_run_id` is released.

### 10. low — edge case — the probe transport is torn down with `stop()`, which navigates the probe target
- **Where:** `src/obed_edom/live_host.py:2046`.
- **Scenario:** `ChromeCdp.stop()` in attach mode opens a fresh socket and `Page.navigate`s the probe page to `about:blank`
  (3 s budget). That is an extra OBS browser navigation during the isolation window, and it can consume up to 3 s of the
  5 s cancel/Stop budget, so Stop reports "Calibration cleanup was not verified".
- **Fix:** Use `transport.detach()` (already added for reconnect) in `_measure_probe`'s finally. W3 removes the source.

### 11. low — new class — per-call process probes on hot paths
- **Where:** `src/obed_edom/managed_obs.py:837` (`_calibration_check_current` → `_identity` → `ps -Eww` subprocess, run
  **twice per OBS request**); `live_host.py` `_sync_probe_placement`/`_capabilities` call `identity()` on every observe.
- **Scenario:** One transaction makes about 260 OBS requests (7 captures × 2 full isolation verifies), so roughly 520+ `ps`
  spawns plus per-poll checks. `ps -Eww` measured 3.1 ms median here (idle), about 1.7 s of the 15 s budget and steady CPU
  churn on the show machine during an on-air calibration. In probe mode every `observe()`, including `_wait_settled`'s 50 ms
  loop, also adds a `ps` spawn and, when valid, a fingerprint CDP evaluate.
- **Fix:** Verify process ownership once per phase (before the first mutation, before each capture, before cleanup), not
  around every request. The lock-protected pid/launch/generation comparison stays per request. Have `identity()` return the
  lock-protected tuple and rely on liveness for process re-verification.

### 12. low — new class — Chrome product Stop path changed (O2)
- **Where:** `src/obed_edom/live_host.py:2629–2630`.
- **Scenario:** For launched Chrome, `stop()` now runs a revoke evaluate (it can wait up to 1 s on `ChromeCdp._lock` while
  another thread is blocked in `call()`, contrary to the Stop docstring) and publishes the new reason `stopped`. §11.3
  says Chrome reason strings remain unchanged.
- **Fix:** Limit the stop-time revoke and the `stopped` reason to `self._placement_mode == "probe"`. Chrome stop terminates
  the process anyway.

### 13. low — edge case — a successful reconnect publishes `disconnected`
- **Where:** `src/obed_edom/live_host.py:1627`; `dashboard/src/live/LivePresenter.tsx:77`.
- **Scenario:** After a working reconnect with automatic probes suppressed, the reason stays `disconnected`, so the presenter
  shows "Waiting for connection to output host" indefinitely while connected and Recalibrate is enabled.
- **Fix:** Publish `not-calibrated` after a successful reconnect revoke. Keep `disconnected` for failed reconnects.

### 14. low — edge case — fail-open defaults and duplicated knowledge in the probe path
- **Where:** `src/obed_edom/live_host.py:1930` (`getattr(transport, "target_url", channel.request.url)` passes vacuously);
  `:1800` (`(self._output_rate or 25) * 2` duplicates `managed_obs.RATES`); `:1880` (full RGBA decode before the size check).
- **Fix:** Default `target_url` to `None` (fail closed). Derive fps from `managed_obs.RATES[rate][1]`. Check `source.size`
  before `convert("RGBA")`.

### 15. low — over-engineering / dead state
- **Where:** `_probe_manual` (`live_host.py:1211`, `:1778`, `:1837`, `:2184`) is written but never read.
  `_ProgramGuard._last` (`:1039`, `:1074`, `:1091`) is stored but never used.
- **Fix:** Remove both.

### 16. low — tests that would pass if the behaviour broke
- **Where:** `tests/test_live_host.py:3714` and the new host/guard tables.
- **Scenario:** The Node `fixedMode` row assigns `window.M`, which is not the closure `M`, so it passes for any mode
  implementation. No Node row tampers with the clock after a grant (`performance.now = () => 0` → lease must still expire),
  although §5/§6 list "tampered clock". No host row covers findings 1, 2, 5 or 7.
- **Fix:** Replace `fixedMode` with an attempt to grant `snap` without ms on a probe-mode document after any page-side
  mutation, plus a knowledge-mode document rejecting `frac,15000`. Add a row where the page reassigns
  `performance.now`/`Performance.prototype.now` after a grant and `atExpiry` is still `invalid`. Add the host rows named in
  1, 2, 5 and 7.
