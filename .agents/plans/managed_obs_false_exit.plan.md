# Managed OBS: false `obsExited` from a LaunchServices blip (plan rev 2, approved 2026-09-25)

## The bug

On 2026-09-25 the OD-2 soak (10:12–10:32, branch `claude/od-2-gl-replay-managed-obs-5bd03f`) failed with a false exit:
- The engine logged "managed OBS exited without AK asking" in minute 1.
- It then stayed in `blocked/exited` with W5 `obsExited` for 19 minutes.
- OBS was running the whole time: its log runs to 10:32 and CDP answered throughout.
- Evidence: `output/gl-replay-managed/{Q-soak.log,runs/soak-20260925-101220.json}` in worktree `autoprompts-toggle-cfdda0`.

On show day, the operator would follow W5 and restart a healthy output. This must be fixed before the 2026-10-10 field test.

## 1. Root cause

Reproduced 2026-09-25 with read-only probes; scripts are in the session scratchpad.

`_identify` returns "gone" when `AppKitLauncher.processes()` leaves out the pid. `processes()` calls
`NSRunningApplication.runningApplicationsWithBundleIdentifier_` (LaunchServices). **LaunchServices sometimes returns an
empty list for every bundle id.**

| probe | target | samples | "absent" windows | window | kernel view in the window |
|---|---|---|---|---|---|
| 60 s, 4 threads, the engine's exact checks | OD-2's live managed OBS, pid 78219 | 17 754 | 8 samples within one second (10:42:22); raw list `[]` | — | alive (pgrep afterwards) |
| 300 s, 1 thread, 5 ms period | Finder 742 + Dock 739 | 41 097 | 12 (8 hit both apps at once) | 6–18 ms | `kill(pid,0)` alive every time |
| critic, 170 s, 1 thread | Finder + Dock | — | 2 | < one `ps` call | `ps -Eww -o command= -p` exit 0, normal output; LS lists the pid again right after |

What the probes show:
- `runningApplicationWithProcessIdentifier_(pid)` also returned nil during some windows.
- `NSWorkspace.runningApplications` updates only while the main run loop runs, so it goes stale in the dashboard.
- The other identity checks never failed in 17 754 samples: (b) launch-date drift, and (c)/(d) `ps -E` failures.
- Load was 4–7 on 10 cores. Another session was launching and quitting OBS and Chrome at the time.
- The windows coincided with other apps launching and quitting. CPU load alone has not been shown to trigger them.

How the soak event is attributed: by elimination. OBS was alive, CDP answered, and the soak had no telemetry. A related
case would behave the same way: LaunchServices not yet listing a pid it has just launched. The fix below covers it too.

Rate: ~2.4 windows/min × ~7 ms. One sample every 2 s hits a window with probability ≈ 2.8e-4, so liveness alone gives
~15 % per 20-min soak. Readiness polls at 5 Hz. `_on_exit` forgets the pid, so one blip becomes a permanent block, and only
Restart clears it.

Other places that act on "gone":
- `_await_ready`: a false `exited` during Take.
- `_terminate_and_wait`: "terminated" before OBS has quit. `cleanExit` is written true too early. The next
  `_launch → _quit_orphans` then finds the old OBS as an orphan, latches `cleanExit` false (a spurious W3), quits it and
  waits.
- `_ensure_started` (managed_obs.py:843) then `_seed` (:912): both treat "gone" as permission. Two blips there would
  launch a second OBS on the same tree while ours is still alive. `_orphans` skips the current pid, so it gives no
  protection.
- `_check` on a `stuck` engine: a blip forgets the stuck OBS.
- `_orphans()`: an empty list hides an orphan.

## 2. Fix

### F1: believe absence only when the kernel agrees (`_identify`; root cause)

When the pid is missing from the LaunchServices list, ask `env_marker(pid)` (kernel-backed `ps -E`):

| `env_marker` result | meaning | identity |
|---|---|---|
| `False` | no such process, or the pid now belongs to a process without our marker | "gone" |
| `True` or `None` | LaunchServices and the kernel disagree, or the kernel cannot be read | "unknown" |

What each caller does with "unknown":
- Liveness counts `_unknown_ticks`. W `obsIdentityUnknown` appears after 3 ticks in a row (~6 s); blips last milliseconds.
- Start and stop fail closed: ensure does not relaunch, seed raises, terminate returns rejected, and stuck stays stuck.
- Readiness keeps polling.

Safety argument: an unknown sample in liveness heals itself, because the warning is dropped when `_unknown_ticks` resets
(:1041–1046). `obsExited` does not heal: it stays until Restart. F1 makes no start or stop path looser, and every caller
runs on the engine thread, so there is no new race.

Latency: a real exit still reads "gone" on the first sample after the process has left the kernel (`ps -p` exits 1 with
empty output). That is at most one liveness tick plus the probe time. A crash held by ReportCrash or a slow teardown reads
"unknown" until the kernel releases the pid, which is correct. Terminate-wait becomes stricter in the same way.

A launch-date mismatch stays "gone": LaunchServices listed a different app instance under that pid.

Outcomes we accept:
- A blip on the first `_identify` of a Quit or Restart gives `obsIdentityUnknown` (Check clears it). Before this fix it
  eventually gave `engineError`.
- A blip on the last readiness poll gives `identityUnknown` instead of timeout.

### F2: corroborate before declaring an exit mid-show (`_liveness` only; defence in depth)

When identity is "gone" and a `target_id` is recorded, call `_cdp_targets` once:
- If the target is listed, log it and treat the sample as "unknown".
- Otherwise call `_on_exit`.

States with no `target_id`, and `_await_ready`, rely on F1 alone. A false exit at readiness costs one Take before the show.
A false exit in liveness breaks a running show and does not clear.

This relies on CEF's DevTools server running in the OBS main process, so it refuses at once when OBS exits and adds no
latency. That is believed, not verified; L1 checks it with `lsof`.

### Telemetry

One `log.info` whenever F1 or F2 turns "gone" into "unknown". It records the check that disagreed, the pid and the
`env_marker` value, and never secrets. Blips are rare, so there is no rate limit.

### Rejected alternatives (so nobody "simplifies" into them later)

- **Retry on an empty list:** a timing guess with no fail-closed guarantee.
- **`NSWorkspace.runningApplications`:** stale off the main run loop, so it would hide real exits.
- **Kernel-first identity:** gives the same result as F1 but bypasses the Launcher seam the fakes test through.
- **N consecutive "gone" samples:** adds (N−1) × 2 s to every real exit. With F1, one sample is already kernel-confirmed.

### Residual in `_orphans()`

A blip empties the list and hides an orphan. Orphans exist only after a dashboard crash. `_quit_orphans` and `_seed` run
within milliseconds of each other, so a single blip can cover both. The risk is ~3e-4 per Take after a dashboard crash, and
the next Take enumerates again. The startup check can also miss an orphan; the next Take quits it. Document this; no fix.

## 3. Tests

### Unit tests (`tests/test_managed_obs.py`)

Two fixture changes:
- `FakeLauncher` gains `ls_hidden: set[int]`. `processes()` leaves those pids out, and `env_marker` keeps answering from
  `alive_pids`/`homes`.
- The Rig models a real exit once: `FakeCdp` answers `/json/list` only while the rig's last launched pid is in
  `alive_pids`, and returns 503 otherwise. Existing exit tests therefore stay byte-identical, including:
  - `test_liveness_vanished_pid_is_w5`
  - `test_active_follows_the_running_pid`
  - `test_operator_closing_obs_during_setup_is_not_w5`
  - `test_restart_after_w5_shows_w3`
  - the sentinel test

New tests:
1. LS hides the pid on one liveness tick: state stays `ready`, no `obsExited`, and the next tick resets `_unknown_ticks`.
2. LS hides the pid during readiness: the engine reaches `ready` once it is unhidden.
3. LS hides the pid during terminate-wait (added via `on_terminate`, `quits=False`): the engine keeps waiting.
   `cleanExit` is written only after the fake really quits.
4. LS hides the pid on `ensure_started` while ours runs: no relaunch and no tree write.
5. LS hides the pid on `check()` of a `stuck` engine: it stays `stuck`.
6. LS hides the pid and `env_marker` returns None for three ticks: `obsIdentityUnknown`, never `obsExited`. Unhiding it
   clears the warning.
7. F2: LS hides the pid, the kernel says gone, and CDP still lists the target: no `obsExited`. When CDP goes, `obsExited`
   is raised on that tick.
8. Pid reuse: LS hides the pid, and the pid is alive but has a different home: "gone", W5.
9. Engine-thread test (real queue, `liveness_s=0.05`): LS hides the pid across ~20 ticks, never `exited`. A real exit then
   gives `exited` within the existing 5 s deadline pattern.
10. `AppKitLauncher.env_marker`, real processes:
    - a reaped child's pid gives False;
    - `Popen([sys.executable, "-c", "import time; time.sleep(30)"], env={"CFFIXED_USER_HOME": str(tmp_path)})` gives
      True;
    - the same child checked against another home gives False.

No route test: the API shape does not change. The dead-output restart exception is already covered
(tests/test_live_api.py:464).

### Live tests

Main session only. One OBS at a time, never while another session's OBS runs. Hands off Keynote.

**L1 stress** (scratch-only script, not committed — owner Q3)
- Setup: scratch home, a real `ManagedObs` Take, liveness at the production 2 s tick, plus a side thread sampling
  `_identify` at ~50 Hz. Run until ≥5 raw LaunchServices absences are seen or 30 minutes pass, and report the rate.
  Launching and quitting a throwaway app (e.g. TextEdit) on a timer may be used as the trigger. CPU burners are optional.
- **Instrument positive control:** the same sampler on `origin/main` code shows false "gone" samples.
- **Fault-occurred control:** the fixed run logs at least one downgrade with `env_marker` True. A downgrade with None
  only counts as absorbed.
- **Pass:** zero "gone" while the kernel says the pid is alive. Zero `obsExited`, a clean quit, and `cleanExit` true.
- **Exit control:** an out-of-band `NSRunningApplication.terminate()` mid-run (a clean quit AK did not ask for; never
  SIGKILL) gives `obsExited` within 2 s plus the probe time, measured from kernel death (poll `kill(pid,0)`).
- **CEF check:** `lsof -nP -iTCP:<cdp> -sTCP:LISTEN -Fp` prints the managed OBS main pid.

**L2:** `uv run python scripts/managed_obs_qualify.py --arm both --rate 25 --takes 2` on the final code.

**Full suites:** `uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`.

## 4. Scope

- Code: `src/obed_edom/managed_obs.py` (`_identify`, `_liveness`).
- Tests: `tests/test_managed_obs.py`.
- Docs: SKILL.md "Alpha Keynote managed OBS", the Ownership and Readiness bullets (the absence rule and the liveness
  CDP corroboration).
- No dashboard or API change. W5 text unchanged.

The OD-2 branch's `--arm soak` stays theirs. After merge, OD-2 rebases and re-runs its soak as the end-to-end check;
the new telemetry line shows any blips it absorbs.

## 5. Owner questions

- **Q1.** For the `_orphans()` blip: document it as a residual (recommended; ~3e-4 per Take, only after a dashboard crash), or re-enumerate?
- **Q2.** Add a consecutive-"gone" requirement on top of F1 + F2? Recommended: no, because it costs 2 s per real exit.
- **Q3.** L1 stress script: keep it scratch-only (critic; the OD-2 soak plus telemetry cover re-runs, and it avoids a third
  liveness harness), or commit it (coordinator's lean; re-runnable on the show Mac before 10-10)?

**Owner answers 2026-09-25:** Q1 residual (documented, no code); Q2 no consecutive-sample rule; Q3 L1 stays scratch-only.

## 6. Review log

- rev 1 (coordinator).
- rev 2 folds the Opus HIGH critique:
  - F2 limited to liveness;
  - a real exit modelled in the Rig fixture, not by editing tests;
  - the `env_marker` premise proved in L1;
  - §1 consequences and arithmetic corrected (2.8e-4, ~15 %/20 min, correlated orphan blips, early-terminate → orphan
    path, not a `_seed` raise);
  - rejected alternatives recorded;
  - `ls_hidden` replaces a call-count blip model;
  - pid-reuse and real-process `env_marker` tests;
  - route test dropped;
  - L1 triggered by app churn, with controls relabelled.
