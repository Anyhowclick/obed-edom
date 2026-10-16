# C2 offline checkpoint (stream V): gate record, 2026-10-16

Scope: plan §4, the offline pieces only. New `scripts/live_run_validity.py` and `tests/test_live_run_validity.py`. No other file changed. Probe integration, producers' `instrumentCost`, and calibration (gate 3) come later.

- Branch `claude/stage-b-c2`, cut from `claude/stage-b-arch` @ `8e136d37`.
- Implementer: Codex GPT-5.6 Sol high (the initial draft plus the r1 and r2 folds). Reviewer: Opus 5.5 high, rounds 1–3, all severities folded.
- r1 was NOT READY: 0 blocker/major, 5 medium, 10 low, all folded. The mediums:
  - negative cost values were accepted;
  - a malformed hook could make the run False;
  - the policy snapshot overwrote `requiredHooks`;
  - a closed GL overlap swallowed the post-GL stall;
  - the caller's qualification row was trusted.
- r2 was READY with 6 lows (style, key shape, JSON round trip, a test gap), all folded.
- r3 was READY with 2 trivial lows, which the coordinator session folded.
- Tests: `tests/test_live_run_validity.py` has 3 functions and 33 cases, all passing on 3.13. Both files also parse under 3.10. The full suites are not run here; they wait for the machine window or for gate 6a.

## What it does
- `run_validity(capture, qualification, *, gl_intervals=None) -> {ok, reasons, measured, policy}`.
  - False means observed cost or environment invalidity. None means unproven.
  - The supplied qualification is only an identity check against the canonical `QUALIFICATIONS[capture["hostKind"]]`.
- Host rows:
  - headless Chrome and qualified Chrome attach: P = 1000/60;
  - managed OBS 25: P = 40, source 50;
  - managed OBS 30: P = 1000/30, source 60.
  - The OBS rows come from `managed_obs.RATES` and `PINNED_OBS`.
- Environment:
  - Chrome rows: a build other than `155.0.8059.79` gives False; a missing or unparseable product gives None.
  - CEF rows: never checked against the Chrome build. They check the pinned OBS version and the configured and observed output and source rates.
  - Attach: always None until a display/timing profile field exists.
- Cost:
  - a 6-hook required inventory;
  - p95 > 8 ms on any well-formed hook gives False;
  - a missing or malformed hook gives None;
  - a hook observed with zero calls is fine.
- Cadence: measurement only. It records per-settled-visit median, p95 and max, the over-2P count and GL-excluded deltas (strict overlap). Its `ok` is always None, so `ok` cannot be True before gate 5a.

## Open for gate 5a and integration
1. **Q2: the settled-cadence statistic.** Not frozen; the gate lands as a separate V checkpoint after 5a.
2. **Q1: host rows.** `HOST_ROWS_POLICY_STATUS` is OPEN.
3. **Attach display/timing profile.** No capture field exists yet, so attach validity is None. The field has to be defined at integration.
4. **Cost budget.** 8 ms p95 is a draft from the C1 timing split and still needs the gate 3 all-hook clean calibration.
5. **`REQUIRED_HOOKS` names** (`sampler.tick`, `paint.prePaint`, `feed.rvfc`, `feed.raf`, `feed.draw`, `frame.total`) are proposals. They are frozen together with the F/P producers at C2 integration.
6. **Load, uptime and Chrome-count observations** are recorded with no threshold.
7. **OBS observed output rate** must match exactly (within 1e-9). `canvas_fps` elsewhere tolerates ±0.2. Exact match is the owner's call.
8. **`gl_intervals` keyword.** This is an addition to the plan's two-argument signature: P passes the under-artwork GL intervals at integration. Without it, cadence records "GL intervals were not supplied".
9. **Host-kind constants** now live here as well as in the probe. The drift test asserts they are equal. At integration the probe should import them from here.
