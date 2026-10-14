# Code review r2 — CEF/OBS placement, product files (Opus 5.5, HIGH)

Scope: `git diff ecb1de98 ba3b9ff5` for the product files (`live_host.py`, `managed_obs.py`; no fold changes in
`live_runtime.py`, `obs_websocket.py`, `web/live.py`, `live_session.py` or `dashboard/src/live/*`), plus the fold
reports `W3-fold1.md` and `W4-fold1.md`. Line numbers are at `ba3b9ff5`.

Tests were **not run** this round: the coordinator put a hold on test commands. I only parsed the seven product modules
with `/usr/local/bin/python3.10` (`ast.parse`); all parse.

Verdict: **0 major, 4 medium, 4 low.** Of the 16 r1 findings, 15 are closed in substance and r1 #4 is partly closed.
Three of the new findings are regressions the fold introduced in closed classes (#1, #3/#6 and #4/F3). The fourth medium
and the four lows are edge cases.

## r1 closure check

| r1 | Status | Evidence |
|---|---|---|
| 1 suppression ordering | **Closed** (see R2-2 for a cleanup regression) | W4 `_complete_probe` checks `program.ok is False` and `isolation_ok is False` before evidence (`live_host.py:2193–2201`). W3 adds a typed taxonomy (`_CalibrationRefused/Cancelled/Timeout/IsolationViolation`), `isolation_ok` starts true, and the blanket `capture_png` mapping is removed. Host rows cover program-disturbed without evidence, isolation-failed without evidence, and an evidence-less failure that does not suppress. |
| 2 identity flap | **Closed** (R2-6 low) | `_last_engine` keeps the last non-None identity, so X→None→X keeps suppression and only a different identity clears it (`:1751–1775`). The test row covers it. |
| 3 guard false positives | **Closed** (R2-4 edge, R2-1 regression) | WeakMap per element, pause/end/not-ready segment boundaries, loop wrap restarts a segment, and navigation cancels an in-flight probe and clears the automatic key (`:1047–1066`, `:2656–2659`). |
| 4 reconnect revoke timeout → hide | **Partly closed** (R2-3, R2-5) | `_revoke_placement` is now tri-state, and a timeout no longer hides (`:1563–1585`). However, the compromise latch can now be overwritten (R2-3), and the timeout path still ends the session (R2-5). |
| 5 stale transport in execute | **Closed** | `execute` reads the transport after `observe()` (`:2574–2575`). A test row covers it. |
| 6 lost updates | **Closed** | `_placement_epoch`; renewal and completion recheck it under `_placement_lock` before every terminal write and after the renew reply. Rows cover a classification blocked across a reload and a renewal blocked across a recalibrate. |
| 7 ignored revoke failures | **Closed** | `_handle_revoke_failure` sets `_reconnect_revoke_required`, and `_schedule_probe` revokes before allocating a run and refuses to start if that fails (`:1820–1827`). |
| 8 renewal lifecycle | **Closed** | The context read in renewal is guarded, `_start_renewal_thread` refuses after `_stopped`, and Stop sets `_stopped`, the epoch and the renewal event under `_placement_lock`. |
| 9 server clear race | **Closed** (one stale path, see R2-1) | `set_probe_run(None, run_id=…)` compare-and-clear, called while the run ID is still held. |
| 10 probe `stop()` | **Closed** | `transport.detach()`. |
| 11 `ps` per request | **Closed** | `identity()` is lock-only. Ownership is verified at three phase boundaries (before the first mutation, per capture, before cleanup). Per-request checks stay lock-only. |
| 12 Chrome Stop | **Closed** | The stop revoke and the `stopped` reason are probe-mode only. A Chrome placement-unchanged row was added. |
| 13 reconnect reason | **Closed** | `not-calibrated` after a successful reconnect or a delayed revoke. |
| 14 fail-open details | **Closed** (R2-7 low) | `target_url` defaults to None, fps comes from `RATES`, and the PNG size is checked before conversion. |
| 15 dead state | **Closed** | `_probe_manual` and `_ProgramGuard._last` removed. |
| 16 vacuous tests | **Closed** | A real `Performance.prototype.now` tamper row and probe/knowledge-mode rows replace `window.M`. |

---

### R2-1. medium — closed-class regression (#3/#6) — a probe cancelled while deferred runs anyway, then is thrown away
- **Where:** `src/obed_edom/live_host.py:1734–1744` (`_cancel_probe` only sets `_probe_cancelled` and leaves the run
  registered), `:1811–1813` (`_sync_probe_placement` restarts any registered run that has no future), `:1847–1852`
  (`_start_scheduled_probe` ignores `_probe_cancelled`), `:2153` and `:2176` (`_complete_probe` → `finish("cancelled")`
  whenever the flag is set).
- **Scenario:**
  1. A probe is scheduled while the player is busy (`waiting-for-transition`, future None). This happens with an automatic
     probe after a reload during a build, or with a manual Recalibrate during a transition.
  2. The operator advances. `_prepare_navigation_placement` → `_cancel_probe("cancelled")` sets the flag and clears
     `_automatic_probe_key`, but `_probe_run_id` stays.
  3. On the next idle `observe()`, `_sync_probe_placement` calls `_start_scheduled_probe()`. That runs a full OBS
     transaction on air (Studio toggle, create/remove scene and input, seven screenshots).
  4. `_complete_probe` reads `_probe_cancelled=True` and discards the result as `cancelled`.
  5. Because the automatic key was cleared, a second automatic transaction follows.

  The same pattern affects the context-change and engine-change cancels of a deferred run: they later start against the
  stale context or engine and fail as `revoked-fingerprint`/`probe-failed`, publishing the wrong reason.

  `_start_scheduled_probe`'s epoch-stale branch (`:1877–1890`) has a related gap. It cancels the started W3 run with
  timeout 0 and calls `set_probe_run(None)` while W3 install/cleanup may still be running (the plan says "server run clears
  only after cleanup"). It also leaves `_probe_run_id` registered, so the same run ID is restarted later.
- **Fix:** In `_cancel_probe`, under `_placement_lock`, finish any run whose `_probe_future is None` immediately via
  `_finish_probe_state(reason, expected_run_id=run_id)`. Only started runs keep the flag and wait for their future. In
  `_start_scheduled_probe`, return `_finish_probe_state("cancelled", expected_run_id=run_id)` if `_probe_cancelled` is set.
  In the epoch-stale branch, keep the run registered with its future and start `_await_probe_result` (marked cancelled),
  so the server run is cleared only after W3 cleanup and the run is not restarted. Add a host row: deferred probe → advance
  → idle observe → no `adapter.start`, reason `cancelled`, and exactly one fresh automatic probe after that.

### R2-2. medium — closed-class regression (#1) — cleanup marks transport errors, slow removal and unowned leftovers as isolation failures
- **Where:** `src/obed_edom/managed_obs.py:1212–1228` (on an absence-poll exception it breaks, `absent` stays False, then
  `isolation_violation = True`), `:1231–1235` ("did not disappear" → isolation), and the unconditional absence poll for
  runs that installed nothing.
- **Scenario:**
  - (a) A WebSocket timeout on one cleanup `GetInputList` → `absence-poll` error → isolation violation → the host
    publishes `isolation-failed` and suppresses automatic probes for the launch. That is the transport-error-as-isolation
    rule r1 #1 removed, now reintroduced in cleanup.
  - (b) A precheck refusal for an **unowned** collision ("An unowned AK-Calibrate scene already exists", nothing
    installed): cleanup still polls absence for 5 s, sees the unowned scene and reports an isolation violation. A
    refusal therefore suppresses probes and costs 5 s.
  - (c) Slow OBS target teardown longer than the remaining cleanup budget is a cleanup failure under §11.3
    (`cleanup-failed`), but it is reported as `isolation-failed`.
- **Fix:** In cleanup, set `isolation_violation` only for observed state mismatches after this run mutated OBS: program
  scene changed, the restored readback differs, or an ambiguous owned reference. A poll request exception or deadline
  should only make `cleanup_ok` False (host → `cleanup-failed`). Skip the absence poll and target wait entirely when
  nothing was installed (`not any((install.scene_created, install.input_created, install.ref_requested))`). Count
  leftovers only for resources this run created (its `source_uuid`/scene UUID), never by name alone. Add W3 rows:
  absence-poll timeout → `isolation_ok True`, `cleanup_verified False`; collision refusal → no poll, `isolation_ok True`.

### R2-3. medium — closed-class regression (#4 / F3) — the `channel-compromised` latch is overwritten in the same call
- **Where:** `src/obed_edom/live_host.py:1804–1809` (`_sync_probe_placement` fingerprint path:
  `_handle_revoke_failure(…)` then an unconditional `_set_placement(None, "revoked-fingerprint")`); `:2367–2373` (renewal:
  `_handle_revoke_failure` does not advance the epoch, so `self._placement_epoch == epoch + 1` still holds and
  `revoked-fingerprint`/`disconnected` replaces it); `:2260–2264`, `:2284–2288`, `:2318–2321` (`_complete_probe`:
  `_handle_revoke_failure` then `finish("revoked-fingerprint"/"stale-result")`, with the local `epoch += 1` that makes
  `finish` succeed).
- **Scenario:** A revoke gets a responsive non-`invalid` answer → `_handle_revoke_failure` publishes
  `channel-compromised` and hides the output. The next statement in the same function rewrites the reason.
  `_sync_placement`'s early return and Show's refusal (`reason == "channel-compromised"`, `live_host.py:2645–2646`) both key on that string, so the operator can Show again and automatic probing resumes on a channel that
  failed its check. Before the fold, compromise was published only as a terminal step, so this path did not exist.
- **Fix:** Add a sticky `_channel_compromised` flag, set in `_handle_revoke_failure`/commit mismatch/install failure and
  read by `_sync_placement` and Show. In `_set_placement`, keep `reason="channel-compromised"` while the flag is set
  (only `stopped` may replace it). Alternatively, return immediately after `_handle_revoke_failure(..., "compromised")`
  on every one of these paths. Add a row: renewal fingerprint change + compromised revoke → reason stays
  `channel-compromised` and Show is refused.

### R2-4. medium — edge case (class #3) — a video that starts during the guard window reads as a stall
- **Where:** `src/obed_edom/live_host.py:1054–1058` (on activation `lastAdvanceAt=t`; the first advance computes
  `maxStallMs = t − lastAdvanceAt − frameMs`); `:1116–1126` (`finish` requires `frameMs > 0` for every `playing`
  element).
- **Scenario:**
  - (a) A slide movie started by an auto-play build or "start automatically" during calibration needs about 50–150 ms
    before `currentTime` moves. That latency counts as a stall. With frameMs ≈ 20–40 ms it exceeds `frameMs`, so the
    result is `ok=False` → `program-disturbed` → launch suppression.
  - (b) An element that becomes active within one tick of `finish` (no advance yet) has `playing=true`, `frameMs=null`,
    so `media_known` is False and `ok=False` (not None), also suppressing.
- **Fix:** Start stall accounting at the first observed advance of a segment (`lastAdvanceAt` stays null until then). In
  `finish`, ignore playing items with no completed advance (or return `ok None` for them) instead of failing. Add Node
  rows: delayed start (100 ms) → ok; activation in the last tick → ok or None, never False.

### R2-5. low — edge case (#4) — a reconnect whose only failure is the revoke still ends the session
- **Where:** `src/obed_edom/live_host.py:1643–1646` (`return False` after a `disconnected` revoke) → `observe()` re-raises →
  `LiveSessionService.state()`/`_fail` → status `error`, which `_pollable` treats as terminal (`live_session.py:248–253`).
- **Scenario:** After a CDP drop, the replacement attaches but the revoke times out once. The session is marked failed
  for good, even though the transport is usable and `_reconnect_revoke_required` already gates navigation and grants. The
  new host row that recovers on a second `observe()` cannot happen in the product, because the session never polls again.
- **Fix:** After a `disconnected` revoke with the replacement attached, return True (state `disconnected`, revoke
  required). Let observe's second snapshot evaluate decide whether the session fails.

### R2-6. low — edge case (#2) — engine-None handling repeats on every observe
- **Where:** `src/obed_edom/live_host.py:1751–1759` (`_engine_identity` is never cleared in the None branch).
- **Scenario:** While the engine stays `blocked` (for example a persistent deviceInactive), every `observe()` runs a
  revoke evaluate, `_cancel_probe` (epoch bump plus a `placement` log record) and `set_placement`. During `_wait_settled`
  that is about 20 Hz of extra CDP calls and log records.
- **Fix:** Act on the transition only. Set `_engine_identity = None` (keeping `_last_engine`) after handling, and guard
  the branch with `self._engine_identity is not None`.

### R2-7. low — edge case (#14) — fps lookup outside the `try`
- **Where:** `src/obed_edom/live_host.py:1859`.
- **Scenario:** `RATES[self._output_rate or 25]` raises `KeyError` for an unsupported rate. That escapes
  `_start_scheduled_probe` → `_sync_probe_placement` → `observe()` and fails the session instead of `probe-failed`. The
  router validates the rate today, so this is latent.
- **Fix:** Move the spec construction inside the `try`, or use `RATES.get` with a `probe-failed` finish.

### R2-8. low — edge case (#4) — a document without the channel is treated as compromised
- **Where:** `src/obed_edom/live_host.py:1563–1572`.
- **Scenario:** If the CDP session dropped before OBS reloaded the program source, the new document has no
  `__obedGrant`. The revoke returns null → `compromised` → hide on air plus a permanent Show refusal. §2.5 says a fresh
  invalid context is acceptable after reconnect, and a channel-less document cannot hold a grant (`pl` is undefined, so
  the take skips).
- **Fix:** Have the revoke expression report channel absence distinctly (`typeof window.__obedGrant!=="function"` →
  `"absent"`). Treat that as a fresh invalid context (no hide), and keep `compromised` for a present channel that
  answers wrongly.
