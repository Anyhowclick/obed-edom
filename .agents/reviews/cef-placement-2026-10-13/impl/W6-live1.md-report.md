# W6 live-run diagnosis

## Scope and evidence

This diagnosis used the completed 25 fps take only. The deliberately interrupted 30 fps launch was ignored. In the paths below, `LIVE` is `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/20ff56a9-0814-410f-9628-290bebf3e027/scratchpad/live1`, and `RUNS` is `LIVE/out/shots/placement-20261013-211655/runs`.

The live result establishes that the product classifier path itself worked: 36 CEF arm sessions produced valid `frac` grants, while `program-wire-integrity`, `persistence-worker`, `life-cal-preview`, `startup-preview-on`, and `probe-frozen-video` passed. The failed controls below made the aggregate isolation/probe gates fail or become inconclusive; they do not contradict those successful product observations.

## Findings

### `startup-offcanvas-on`, `failed-offcanvas-on`, and `opaque-off`: PRODUCT activation race; one secondary HARNESS schema defect

- `RUNS/startup-offcanvas-on/record.json:1` records `isolationOk:false`, `cleanupVerified:true`, `restored:true`, `program.ok:true`, zero captures, and `_CalibrationIsolationViolation: Calibration source is not active in the selected isolated placement.` Its output is `invalid/isolation-failed`; `RUNS/startup-offcanvas-on/placement/host-log.json:3-7` confirms the same rejection.
- `RUNS/failed-offcanvas-on/record.json:1` has the same isolation error, clean cleanup/restore and Program guard, and zero captures. `RUNS/failed-offcanvas-on/placement/host-log.json:3-7` confirms `isolation-failed`.
- `RUNS/opaque-off/record.json:1` also has null input/evidence and the same isolation error while `program.ok:true` and `restored:true`.
- The product enables the nested off-canvas item at `src/obed_edom/managed_obs.py:1004-1008`, then performs one immediate `GetSourceActive` and rejects unless active/showing at `src/obed_edom/managed_obs.py:1121-1124`. There is no settling retry. The step-0 measurement proves the placement is valid after settling: `output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-step0-2026-10-13/README.md:14` records the x=2048 nested reference as active/showing with exact transform and unchanged Program.

Root cause: the product isolation verifier races OBS source activation. This is a PRODUCT bug, not evidence that off-canvas isolation is unsupported. The product fix belongs in `managed_obs`: after enabling the nested reference, poll `GetSourceActive` within the existing transaction deadline until the source is active/showing or the deadline expires, while retaining the identity, transform, audio, Program, cleanup, and restore checks. No product file was changed by W6.

There was also a HARNESS schema defect: `scripts/dissolve_probe.py` rejected every non-null transaction lacking an evidence reference, even when both `placementCalibration.input` and `transaction.evidence` were correctly null after an early isolation failure. `scripts/dissolve_probe.py:968-979` now permits null only when both sides are null and still requires the `$ref`/object identity when input exists. Consequently, offline `opaque-off` now reaches the substantive gates and reports FAIL (`ClassifierInput missing`, classifier controls missing, and alpha-integrity failure) instead of the misleading schema INCONCLUSIVE.

### `failed-preview-off`: HARNESS control timing; product guard behaved correctly

- `RUNS/failed-preview-off/record.json:1` records the intended capture fault (`captures:2` and `RuntimeError: injected capture failure after first capture`) with `isolationOk:true`, `cleanupVerified:true`, and `restored:true`. Its Program baseline changes from 20.0 ms to a 33.4 ms maximum rAF gap, so `program.ok:false`, reason `program cadence or media changed`, and the host correctly returns `invalid/program-disturbed` with no grant.
- `RUNS/failed-preview-off/placement/host-log.json:47-79` records `show` with both videos playing. Recalibration starts at lines 81-113 only 0.111 seconds later (timestamps 1791897434.623908 and 1791897434.73503). Lines 115-119 record the correct `program-disturbed` rejection.
- The known visible-media CEF transition can change the cadence from 50 Hz to 30 Hz. The control sampled its new baseline before that transition had settled, so the on-air positive did not test only the injected capture error.

Root cause: HARNESS/control bug. `scripts/managed_obs_qualify.py:1848-1861` now requires the output to remain continuously visible and non-busy for 1.0 second before the on-air recalibration. A future run will establish its guard baseline after the cadence transition. The existing artifact remains FAIL; the rescorer does not waive a real failed Program guard.

### `probe-replay`: HARNESS evidence-location assumption; PRODUCT observability gap

- `RUNS/probe-replay/record.json:1` contains the required negative result: `invalid/probe-failed`, no grant, clean isolation/cleanup/restore/Program, two captures, and the exact transaction error `Probe capture freshness could not be verified.`
- `RUNS/probe-replay/placement/host-log.json:3-7` contains the host rejection as `placementProbeRejected/probe-failed`, not a `placementProbe` row repeating the transaction exception.
- The old scorer required the exact message in the latter host-row shape, so it rejected valid combined evidence. Product code also has an observability gap: `src/obed_edom/live_host.py:2264-2275` maps a null-evidence/error result to `probe-failed` without logging `result.errors`; only thrown futures/exceptions are logged with their exact error at `src/obed_edom/live_host.py:2198-2207`.

Root cause: HARNESS/control bug for this verdict, with a separate PRODUCT logging deficiency. `scripts/managed_obs_qualify.py:1923-1933` now requires both the exact freshness error in the transaction and either the exact host error or the generic `placementProbeRejected/probe-failed` host row. Offline rescore changes this control from FAIL to PASS. The product-side improvement is to log the transaction error list/specific freshness cause before the `probe-failed` finish; W6 did not change `live_host.py`.

### `probe-transparent`: two HARNESS scorer assumptions; same PRODUCT observability gap

- `RUNS/probe-transparent/record.json:1` records `invalid/probe-failed`, no grant, clean isolation/cleanup/restore/Program, the exact freshness transaction error, and `control.kind:transparent`, `captures:1`.
- `RUNS/probe-transparent/placement/host-log.json:3-7` records `placementProbeRejected/probe-failed`.
- Transparency is injected on the first capture, and freshness validation rejects immediately. One capture is therefore proof that this fault intercepted the capture path; requiring two was incorrect.

Root cause: HARNESS/control bug, plus the same PRODUCT logging deficiency described for replay. `scripts/managed_obs_qualify.py:1899-1906` now uses fault-specific minima (`capture-error:2`, `replay:2`, `transparent:1`, `frozen-video:2`), and `scripts/managed_obs_qualify.py:1923-1933` uses the transaction plus host rejection. Offline rescore changes this control from FAIL to PASS.

### `probe-chrome-software`: EXPECTED software negative misclassified by the harness

- `RUNS/probe-chrome-software/placement/telemetry.json:3-12` records candidate `unknown`, no tone map, `grant_eligible:false`, reason `ambiguous`. Its identity scores are approximately snap/frac 0.321/0.444 and 0.322/0.406 at lines 15-26; its analytic scores are approximately 0.707/0.733 and 0.705/0.756 at lines 29-40. No unique placement/tone pair exists.
- The swapped wrong-rule control is likewise `unknown/ambiguous` with no grant at `telemetry.json:44-78`. Replay, DPR, undecodable, frozen-motion, cold-dormant, not-decoded, and wrong-context controls all have the expected rejecting reasons at lines 80-127.
- The old harness hard-coded SNAP/software-map for the candidate and FRAC/software-map for wrong-rule, turning a safe ambiguous/no-grant software result into FAIL.

Root cause: HARNESS/control bug in interpreting an EXPECTED negative outcome. `scripts/managed_obs_qualify.py:457-478` now accepts either a uniquely classified identity/software-map result with no grant or an ambiguous UNKNOWN result with no grant for a software launch. `scripts/managed_obs_qualify.py:761-814` applies the same rule to the forged classifier controls. Offline scoring now recomputes all classifier controls through `classify_probe` instead of trusting stale saved verdict rows (`scripts/managed_obs_qualify.py:436-476`). The per-session classifier and classifier-control gates now pass. The final row is still INCONCLUSIVE, correctly, because this `--takes 1` run supplies only one fresh software Chrome launch and the frozen contract requires two.

### `m-tone-raw-cef` duration 0.03 s: HARNESS stale splice

- `RUNS/m-tone-raw-cef/record.json:1` contains only the arm/load metadata and a traceback ending `ValueError: splice anchor ... found 0 times, expected 1`; it has no `placementCalibration`.
- The current product snapshot is explicitly an identity-tone freeze with no pixel writes at `src/obed_edom/live_runtime.py:314-315`. The harness nevertheless tried to apply the obsolete `lut-identity` splice to the raw-tone arm.

Root cause: HARNESS/control bug. `scripts/dissolve_probe.py:330-331` now serves `m-tone-raw` from the current identity-tone product bytes without that splice; it remains the expected tone-failure negative control. `scripts/managed_obs_qualify.py:3860-3868` also records known placement arms lacking `placementCalibration` as explicit INCONCLUSIVE evidence instead of silently omitting them. The saved broken artifact cannot be repaired offline and now appears as `m-tone-raw-cef INCONCLUSIVE: placementCalibration missing`; a live rerun is required.

### W5 `null timing while paused`: EXPECTED/inherited

- The parent handover explicitly lists reference capture for all `m-snap*` and `m-tone` arms as already INCONCLUSIVE at merge for `null timing while paused`: `.agents/handovers/keynote-live-dissolve-crossfade-followups.md:89-91`.
- The live W5 rows reproduce that existing condition; it is not introduced by CEF placement or this run.

Classification: EXPECTED/inherited. No W6 change or waiver was made. The parent follow-up must either make the producer provide the missing start timing or revise the parent reference schema/scorer based on measured Web Animations paused-state semantics.

## Implemented W6 changes

- `scripts/dissolve_probe.py`: removed the obsolete raw-tone identity splice and corrected null transaction/input evidence consistency.
- `scripts/managed_obs_qualify.py`: added the one-second on-air settling interval; fault-specific capture thresholds; combined transaction/host freshness proof; classifier/control recomputation through the real classifier; accepted safe ambiguous software negatives; propagated current live-probe control verdicts into live and offline scoring; and made missing placement calibration explicit.
- `tests/test_dissolve_probe.py`: extended the existing case table to lock the raw-tone arm to current identity-tone bytes.
- `tests/test_managed_obs_qualify.py`: updated the existing placement-control fixture to reproduce the observed generic host rejection, exact transaction freshness error, and one-capture transparent rejection.

No files outside W6 ownership were modified.

## Offline rescore

Command run after the fixes:

```text
PYTHONPATH=src .venv/bin/python scripts/managed_obs_qualify.py --score /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/20ff56a9-0814-410f-9628-290bebf3e027/scratchpad/live1/out
```

The command completed and wrote `LIVE/out/placement-rescore-20261013-215010.json`. Exit status remains 1 because the artifact still contains genuine product/control failures, only one fresh CEF/Chrome launch, inherited incomplete evidence, and a session that never produced calibration evidence.

| Result | Before (`placement-rescore-20261013-213947.json`) | After (`placement-rescore-20261013-215010.json`) |
|---|---:|---:|
| PASS | 3 | 5 |
| FAIL | 8 | 6 |
| INCONCLUSIVE | 38 | 39 |
| Rows | 49 | 50 |

Material transitions:

- `probe-replay`: FAIL -> PASS.
- `probe-transparent`: FAIL -> PASS.
- `probe-chrome-software`: FAIL -> INCONCLUSIVE; its actual classifier/control gates pass, then the two-fresh-launch gate correctly changes the final row to INCONCLUSIVE (`only 1 fresh Chrome launch(es) for gpu=False; need 2`).
- `opaque-off`: misleading schema INCONCLUSIVE -> substantive FAIL.
- `m-tone-raw-cef`: previously omitted -> explicit INCONCLUSIVE (`placementCalibration missing`).
- `startup-offcanvas-on`, `failed-offcanvas-on`, and `failed-preview-off` remain FAIL because offline scoring correctly preserves the observed product isolation/Program-guard failures. CEF arm rows remain INCONCLUSIVE because the run has only one fresh CEF launch and the startup/failed-on-air isolation controls are not all PASS.

## Verification and coordinator open items

- `git diff --check`: PASS.
- Pytest was not run, as directed, because another session holds the live machine. The coordinator should run only `tests/test_dissolve_probe.py` and `tests/test_managed_obs_qualify.py` with the prescribed `-n 2` command later.
- Product owner: add bounded off-canvas active/showing settling in `managed_obs.py`.
- Product owner: include transaction errors/specific freshness cause in the `live_host.py` probe rejection log.
- Coordinator: rerun at least two fresh CEF and GPU/software Chrome launches after the product activation fix; rerun `m-tone-raw-cef` to obtain calibration evidence.
- Parent follow-up: resolve inherited paused-animation null timing; it should not be treated as a new placement regression.
