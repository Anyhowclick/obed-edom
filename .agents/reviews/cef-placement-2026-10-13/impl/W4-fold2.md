# W4 review round 2 fold

## Files changed

- `src/obed_edom/live_host.py`
- `tests/test_live_host.py`

No other stream files were edited. The worktree also contains parallel changes in W1/W2/W3/W6-owned files; those were left untouched.

## Findings

### R2-1 — folded

- `_cancel_probe` now finishes a deferred run synchronously under `_placement_lock` when no adapter future exists; it does not call `CalibrationAdapter.cancel` for work that never started.
- `_start_scheduled_probe` refuses an already-cancelled run before mutation. A start that becomes epoch-stale keeps its future registered, marks the run cancelled, starts `_await_probe_result`, and clears the server registration only after the adapter future has completed cleanup. `_probe_starting` distinguishes a deferred run from a concurrent adapter start.
- The existing managed state-machine test now covers a busy/deferred automatic run, navigation cancellation, zero adapter starts for the cancelled run, cleared server registration, and exactly one new automatic run when the player becomes idle.

### R2-3 — folded

- Added the sticky `_channel_compromised` latch. Any `channel-compromised` placement write sets it, including installation failure and commit mismatch; `_handle_revoke_failure` also sets it for a responsive wrong revoke answer.
- `_set_placement` preserves `reason="channel-compromised"` and invalid state while latched; only `stopped` may replace the reason. `_sync_placement` and Show use the latch rather than a mutable reason string.
- Added a probe-renewal row where the fingerprint changes and revoke answers wrongly. The reason remains `channel-compromised`, output is hidden, and Show is refused.

### R2-4 — folded

- Program media segments now begin stall timing at their first observed time advance, not at activation or loop wrap.
- Playing media with no completed advance is excluded from the stall verdict, so last-tick activation cannot become a false `program-disturbed` result.
- Extended the existing Node guard row with a 100 ms delayed start and last-tick activation. Both are never false; the delayed row records zero stall.

### R2-5 — folded

- A managed replacement transport whose initial revoke times out now remains attached and returns success from reconnect with `disconnected` state and `_reconnect_revoke_required=True`. The second player snapshot decides whether observation can continue.
- Updated the existing reconnect test: the first `observe()` returns `disconnected` instead of raising, and the next observation recovers to `not-calibrated` after revoke becomes available.

### R2-6 — folded

- The engine-None branch now sets `_engine_identity=None` after handling the transition while retaining `_last_engine` for launch identity comparison.
- Extended the state-machine test to verify a second observation with the engine still unavailable sends no additional revoke.

### R2-7 — folded

- `ProbeSpec` construction and the `RATES` lookup now occur inside `_start_scheduled_probe`'s guarded start block. An unsupported rate terminates the run as `probe-failed` without escaping into `observe()` or calling the adapter.
- Added the unsupported-rate row to the existing state-machine test.

### R2-8 — folded

- `_placement_set_expr` reports a missing `__obedGrant` as the distinct `"absent"` result.
- `_revoke_placement` treats that result as a verified fresh-invalid context without hiding or latching compromise. The host records the channel-less context and does not start a probe in it; a later fresh document with an installed channel may probe normally.
- Extended the managed reconnect test with an unsuppressed channel-less replacement: it stays `not-calibrated`, visible, uncompromised, and starts no adapter run. Reloading into a channel-bearing document restores normal recalibration.
- Updated the Node tamper expectation for a predefined channel collision: direct commit now reports `"absent"` distinctly.

## Contract deviations

None. All assigned findings were folded with the reviewer's requested behavior. The small `_probe_starting` discriminator is required to satisfy R2-1 concurrently: `_probe_future is None` denotes a truly deferred run only when `CalibrationAdapter.start` is not currently in progress.

## Verification

Command used for every run:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_live_host.py -q -n 2 -p no:cacheprovider
```

- Initial implementation run: **344 passed, 2 failed**. Both failures were expected stale assertions: reconnect still expected an exception, and the Node row still expected `None` instead of the new `"absent"` sentinel.
- After folding those rows and adding assigned coverage: **348 passed, 0 failed**.
- After strengthening channel-less reconnect handling: **347 passed, 1 failed**. The continuing state-machine fixture correctly showed that manual recalibration cannot run in the same channel-less document; the fixture was changed to reload a channel-bearing document first.
- Final run: **348 passed, 0 failed** in 2.41 s.
- `git diff --check -- src/obed_edom/live_host.py tests/test_live_host.py`: passed with no output.

## Open items for the coordinator

None for W4. No OBS, Chrome/headless browser, Keynote, full-suite, or gate command was run, as required.
