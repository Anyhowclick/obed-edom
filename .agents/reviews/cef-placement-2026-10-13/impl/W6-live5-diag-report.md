Investigation conclusion: no DSK product regression is demonstrated. The two 25-fps mismatches are caused by a racy frame-reference check; the four-frame result is capture cadence. B25’s placement failure is a transient ownership-verification flake mislabelled as isolation failure. A30’s frozen-region gate is a scorer-control wiring defect.

No repository files were changed.

## 1. `m-snap-cef-dsk`

### Frame mismatch

**Cause/class:** INSTRUMENT. The check is wrong; the saved evidence does not show a visible product step-back.

The recorder saves rVFC `presentationTime`, `mediaTime`, `presentedFrames`, and callback time `rvAt`, but omits `expectedDisplayTime` ([dissolve_probe.py:564](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:564)). `pre_detach()` then compares `presentationTime`—when the frame was submitted to the compositor—to DOM detach time and ignores callback time ([dissolve_probe.py:3169](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:3169)). The equality check uses that selected row at [dissolve_probe.py:3321](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:3321).

| Run | Take window, ms | Selected rVFC: presentation / callback | Holder → selected |
|---|---:|---:|---|
| A25 `165947` | 39313.1–39320.0 | 39315.9 / **39323.1** | d9 76→76; d10 **225→226** |
| A30 `172217` | 39162.3–39169.1 | 39155.3 / 39155.3 | 76→76; 226→226 |
| B25 `174926` | 39183.4–39190.5 | **39190.9** / **39193.7** | **75→76; 225→226** |

Evidence is in each `live5/out/shots/<run>/runs/m-snap-cef-dsk/record.json:1`.

The decisive fact is that the “reference” callback was appended after the holder take completed in both failures. In B25, even its `presentationTime` is 0.4 ms after the take ended. The WICG specification explicitly says rVFC callbacks may be a v-sync late and identifies `expectedDisplayTime` as the visibility timestamp; `presentationTime` only means submission to the compositor. [WICG rVFC specification](https://wicg.github.io/video-rvfc/)

A25 also explains the mixed result:

- DSK holder 1/decoder 10 is drawn first and retained frame 225.
- Holder 0/decoder 9 is drawn later and captured frame 76.
- Holder 0’s fractional geometry has `fx=0.418762`, causing exactly one left-column repair under the W1 logic at [live_runtime.py:158](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py:158). The review already records the residual possibility that a repair may sample N+1 while playing ([review-edgefix-r1.md:13](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/reviews/cef-placement-2026-10-13/review-edgefix-r1.md:13)).
- The one repair does not explain holder 1 being “old”; it only slightly widens a sequential take that crossed a video-frame boundary.

Three live4 takes had the final callback 3.6–12.4 ms before take start. The remaining live4 A30 callback was also late but happened to identify the frame captured, demonstrating that equality can pass accidentally under the same race.

Matching live4/A30 records have a later zero-cost `dump.takes` entry roughly two seconds later; failing live5 records end with the exercised 6.9/7.1-ms take. That later zero is outside `[advanceAt, first transition rAF]` and is intentionally ignored by `score_cost()` ([dissolve_probe.py:2086](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2086)); it does not identify the frame drawn into the holder.

**Required behavior:** per §5 and §11.5, each holder should contain the video frame actually on-screen/current when that video is drawn during the take—not whichever rVFC metadata row happens to have the latest pre-detach `presentationTime`. The contract does not require the two DSK videos to be sampled atomically.

**Proposed fix:** record `expectedDisplayTime` and a per-video freeze-draw timestamp, then select the frame visible at that draw. Keep `rvAt` as a lateness diagnostic. Do not replace this with a ±1-frame tolerance. These fields are additive `dump`/DSK timing evidence, outside frozen `placementCalibration`.

**Contract/owner decision:** no §5/§11 change and no owner decision.

**Fresh live verification:** yes. Existing evidence lacks `expectedDisplayTime` and exact draw times.

### `4 mid frames < 5`

**Cause/class:** HARNESS cadence.

A25’s transition screenshots took 122–215 ms each. Its fitted progress crossed the mid-window as:

- `0.047063` — just below 0.05
- `0.172555`, `0.368633`, `0.596063`, `0.827478` — four admitted
- `0.952944` — just above 0.95

B25 at the same 25-fps output obtained five (`0.149034…0.937222`), while A30 obtained five (`0.062767…0.850981`). Therefore this is screenshot phase/cost, not an inherent 25-fps limitation. The minimum remains five at [dissolve_probe.py:1824](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:1824) and in the CEF profile at [dissolve_probe.py:2733](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2733).

**Proposed fix:** boundedly recapture only the DSK arm when coverage is `<5`, failing closed if retries remain insufficient. If recurrence is frequent, extract naturally timed in-window frames from the existing continuous lossless recording instead. Never lower five or admit boundary frames.

**Fresh live verification:** yes, at 25 fps.

## 2. `wrongrule-cef-twin` B25 placement evidence

**Cause/class:** HARNESS/process-identity flake, with an INSTRUMENT verdict-labeling defect. It is not a calibration-pixel or isolation product failure.

Direct read-only `score_placement_calibration()` reproduced:

- Overall: `FAIL`
- `iso-obs-preview`: **FAIL**
- `probe-cef`: `INCONCLUSIVE`
- `life-cal-preview`: `INCONCLUSIVE`
- Classification/input: missing
- Transaction error: `ManagedObsError: Calibration engine ownership could not be verified.`

Artifact: `live5/out/shots/placement-20261014-174926/runs/wrongrule-cef-twin/record.json:1`.

The transaction still records:

- `isolation_ok=true`
- `cleanup_verified=true`
- `restored=true`
- Program guard OK
- No classifier evidence, because calibration aborted before capture

The failing session used engine PID `73927`, launch `1791971366.244432`, generation `2`. The preceding and following arms used that identical engine; `m-snap-cef-nooffset-x-twin` began 20.0 seconds later and classified `frac` successfully. Only this one of the repeated transactions failed.

The ownership verifier performs a one-shot LaunchServices/`ps -E` identity observation and rejects anything other than `"ours"` ([managed_obs.py:850](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/managed_obs.py:850), [managed_obs.py:1754](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/managed_obs.py:1754)). Meanwhile, the scorer maps every transaction error to `iso-obs-* FAIL`, even when `isolation_ok` stayed true ([managed_obs_qualify.py:481](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/managed_obs_qualify.py:481)).

**Proposed fixes:**

- Boundedly retry only an `"unknown"` ownership observation within the existing calibration deadline; never retry or accept `"gone"`/mismatched ownership.
- Score an aborted ownership check with no isolation violation as `iso-obs-preview INCONCLUSIVE`, not FAIL. It must still fail closed overall.

**Contract/owner decision:** no change. Treating absent classifier evidence as INCONCLUSIVE restores §5’s existing missing-evidence rule.

**Fresh live verification:** yes. The missing classifier input cannot be reconstructed offline; rerun B25, preferably the complete placement round.

## 3. `frozen_region` control

**Cause/class:** INSTRUMENT/profile wiring.

`CEF_PLACEMENT` names `m-snap-cef` as its PASS control at [dissolve_probe.py:2720](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:2720). That arm uses reference capture, so `_score_arm()` intentionally creates no timed fade rows ([dissolve_probe.py:3571](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/scripts/dissolve_probe.py:3571)); forcing the check yields `0 demixed frames (need 3)`. Thus “missing” is deterministic.

The faithful existing positive is `m-fg-cef`:

- It has one real holder and a naturally captured transition.
- A30 frozen-region result: PASS.
- Spreads: `1.9103, 2.0021, 2.3440, 3.0028`.
- `m-hold-cef` remains the independent FAIL control.
- `m-snap-cef-dsk` remains the moving-video PASS candidate.

Scratch-only in-memory monkeypatch:

1. Added `frozen_region: PASS` to `m-fg-cef`’s scoring contract.
2. Changed the positive control from `m-snap-cef` to `m-fg-cef`.
3. Re-scored A30 through the production scorer.

Result: `frozen_region PASS`, overall `PASS`, all 29 arms `MATCH`, and no non-PASS enforced gate. Other possible existing positives also scored PASS (`m-paused-cef`, `m-fg-omit-cef`, `m-fg-swap-cef`), but `m-fg-cef` is the cleanest independent known-good control.

**Proposed fix:** the two scorer-only changes above. No new `m-on-cef` arm and no ~28-second rate cost are needed.

**Contract/owner decision:** no §5/§11 change and no owner decision.

**Fresh live verification:** no for this fix; A30’s retained evidence is sufficient for offline acceptance. The broader round still needs fresh evidence for items 1 and 2.

One execution limitation: the filesystem policy denied creating `SCR/w6live5`, so no APFS clone could be made. I therefore avoided mutating `placement_gates()` and used only pure/read-only scorer functions against the originals. Python was invoked with the requested single-thread environment and `nice -n 15`; macOS denied the priority change with `setpriority: Operation not permitted`.