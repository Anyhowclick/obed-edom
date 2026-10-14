# Code review r4 — live-run product fixes (major/blocker only) — Opus 5.5 HIGH

Scope: `git diff aac7a026 3eae0fde` for `src/obed_edom/managed_obs.py` and `src/obed_edom/live_host.py`, with context
from `W3-live1.md`, `W4-live1.md` and `W6-live1.md-report.md`. Read-only; no pytest (the machine is in a live OBS run).
Line references are at `3eae0fde`.

## Verdict: **0 blocker, 0 major.** Nothing to fold under the round-4 rule.

### Settle loop (`_await_calibration_active`, used only by install verification)
- **Cannot admit a non-isolated source.**
  - It returns only on the placement-specific final state: preview `videoActive=false, videoShowing=true`; off-canvas
    both true.
  - In the same verify call it runs after the transition, DeckLink-output, program-scene, canvas, target, source
    identity/settings and audio checks. The preview/Studio/program-items checks run after it on fresh reads.
  - Every capture still runs the full fail-fast verify (`settle_active=False`) before and after the screenshot. A program
    change during the settle window is therefore caught before any evidence exists.
  - `capture_png` and later checks do not use the settle path.
- **Cannot exceed the transaction deadline.**
  - Each poll goes through `_calibration_request`. That call checks cancel/deadline/generation before and after, with a
    request timeout of at most the remaining time (and the 2 s socket cap).
  - The loop raises when `clock + poll_s >= deadline_s`, and `poll_s` defaults to 0.2.
  - Cancellation still surfaces as `_CalibrationCancelled`, and the cleanup budget is separate and unchanged.

### Baseline change (`_ProgramGuard.begin`/`arm`, `not_before_s`)
- **A disturbance during the transaction is not excused as settling.**
  - `begin()` runs on the W3 worker before the snapshot, ownership check and install. `arm` resets telemetry before any
    OBS mutation, so every gap, visibility event and media stall from the first mutation through `finish` is counted.
  - `not_before_s` is captured when the guard is constructed. It only delays when the baseline is accepted (at most about
    1.35 s, inside the 15 s transaction budget). It never shifts or shortens the measured window.
  - Navigation or Show during a run cancels the probe (unchanged); they do not extend any settle window.
- **A stable-baseline disturbance does not return None.**
  - With a stable baseline, any of these returns `ok=False` → `program-disturbed` + suppression: a gap greater than
    2×baseline, a visibility event, a non-monotonic media item, or a stall greater than one frame on a media item that
    has advanced. The suppression path is intact.
  - `None` comes only from:
    - an unstable or unavailable pre-transaction baseline (plan §2.3: unstable baseline = INCONCLUSIVE);
    - a playing element with no advance for more than 3 baselines while nothing else is disturbed.
  - Both mean no grant and no suppression, which is fail-closed for grants.
- **Threads and locks:** no new locks.
  - `begin()` uses the existing program transport with evaluate deadlines of at most 0.5 s.
  - `_program_guard_not_before_s` is written and read on the session thread (start/observe/execute/reconnect) and copied
    into the guard at construction. The W3 worker never reads the host field.
  - No CDP calls happen under `_placement_lock`.

### Below threshold (recorded, not for folding)
1. **`arm` also resets media records.** A program video that freezes from the moment of `arm` and never advances before
   `finish` now ends as `ok=None` ("advancement unavailable") instead of a stall failure. That outcome has no grant and no
   suppression. It needs the freeze to start in the roughly 20–50 ms between `arm` and the first mutation and to last the
   whole transaction; a stall after the first post-arm advance is still measured. A cheap tightening is to keep media
   records across `arm` and reset only their stall maxima.
2. **Ordering in `finish()`.** It returns `ok=None` for a missing or unstable baseline before it looks at
   `visibilityEvents`. That ordering predates this change, but the stricter ±10%/6-gap stability rule makes it more
   frequent. A visibility event does not depend on cadence, so evaluating `visibility != 0 → ok=False` before the baseline
   check would keep Studio-toggle disturbances suppressible on jittery programs. Without suppression, automatic re-probing
   still happens only on reload/reconnect/engine change.
3. **Settle deadline classified as isolation failure.** A settle loop that reaches the transaction deadline maps
   `_CalibrationTimeout` to `_CalibrationIsolationViolation` (suppression) rather than `timeout:`. This is deliberate
   per W3 and fail-closed; it costs automatic probes on a slow source load, and manual recalibrate still works.
