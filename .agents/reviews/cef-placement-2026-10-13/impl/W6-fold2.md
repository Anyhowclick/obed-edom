# W6 review round 2 fold

## Files changed

- `scripts/dissolve_probe.py`
- `scripts/managed_obs_qualify.py`
- `tests/test_dissolve_probe.py`
- `tests/test_managed_obs_qualify.py`

W6 did not edit any other stream's files. The worktree contains concurrent W3/W4 changes in `src/obed_edom/live_host.py`, `src/obed_edom/managed_obs.py`, `tests/test_live_host.py`, and `tests/test_managed_obs.py`.

## Finding disposition

### R1 — folded

`persistence-worker` now decides only from authoritative rows: any authoritative mismatch FAILs; an authoritative clean quit PASSes even when cleanup predates the restored upper bound; missing/non-authoritative quit evidence is INCONCLUSIVE. Non-authoritative cleanup remains in gate detail. The fixture now sets `cleanup.mtimeNs < lastRemovalMtimeNs` with a clean quit and asserts PASS.

### R2 — folded

Recording analysis and the live positive use the canvas rate obtained from `GetVideoSettings.fpsNumerator/fpsDenominator`, with the numeric prefix of `RATES[rate][0]` as the validated fallback. They no longer use the 50/60 browser-source rate. The flash is held for two canvas frames. The analyzer requires a bounded interval of centre-white frames whose surrounding frames equal the initial frame. A 25 fps, 1.0 s, 25-frame fixture asserts complete frame coverage and detects a two-frame flash; unrelated changed pixels do not count as a flash.

### R3 — folded

Removed `m-geo-dpr125`, `m-geo-2560`, and the fractional-origin arm from `CEF_PLACEMENT_ARMS` and its geometry controls. Added script-only Chrome DX-1 arms `m-geo-frac-origin-chrome`, `m-geo-frac-dpr15`, and `m-geo-frac-dpr2`, all with `placement_mode="probe"`, forced frac, no holder, and geometry FAIL. Offline behavioral rows cover all three and assert that the fixed CEF profile excludes the unproducible viewport/DPR cases.

### M1 — folded

Lifecycle ordering now derives states only from host-observed `event == "placement"` rows. The harness-authored `calibration-start` marker cannot satisfy probing-to-valid. A fixture with only that marker plus a valid host state is INCONCLUSIVE.

### M2 — folded

Added real pre-candidate calibration sessions:

- valid preview and offcanvas startup sessions both begin with Studio Mode enabled and require W3 isolation, cleanup, restoration, and a valid probe grant;
- failed-on-air preview/offcanvas sessions span prior Studio Mode false/true, inject a capture exception after the first real capture, and require host rejection with no grant plus W3 isolation, cleanup, and restoration;
- the aggregate `startup`, `failedOnAir`, and `priorStudioStates` rows are PASS only when the real sessions pass. Missing sessions are `NOT-RUN`, which keeps `iso-obs-*` INCONCLUSIVE.

The former aliases to screenshot equality and visible-origin leakage were removed.

### M3 — folded

`QualificationCalibrationAdapter` now wraps the host's real `measure` callback with a `CalibrationIO` proxy. Three sessions run before every candidate:

- replay returns capture 1 for capture 2 after still taking the second live OBS screenshot;
- transparent replaces the first live screenshot with a transparent 1920×1080 PNG;
- frozen-video pauses `#obed-probe-video` after capture 1 and overrides `play()` to keep it paused for motion captures 2 and 3 while page rAF continues.

Each session requires the product host to publish an invalid `probe-failed` placement with no grant, and requires W3 program integrity, isolation, cleanup, and restoration to pass. The result records `placementProbeRejected`, the output state, transaction summary, and control capture count. The earlier offline classifier mutations remain instrument checks, and CEF scoring now requires all three live-session records.

### M4 — folded

Both retained placement recordings now use `shutil.move`, removing the original from the managed recording directory. FileRef SHA-256 uses 1 MiB chunks; schema validation hashes a recording without loading its contents into memory. `--arm placement` performs a free-space preflight before launch, prints the expected recording count, retained bytes, working bytes, and free bytes, and refuses insufficient same-volume or split-volume capacity. Tests cover the computed count, refusal, and a multi-chunk no-load FileRef validation.

### L1 — folded

Tone-row candidate width, height, and snap origins now use `floor(value + 0.5)`, matching JavaScript `Math.round` for the positive page geometry values.

### L2 — folded

The offline cold-dormant control now replaces the first freshness PNG with a transparent 1920×1080 capture and requires `stale-capture`. The metadata-only row is retained separately as `notDecoded` and requires `invalid-evidence`.

### L3 — folded

`nullBefore` and `nullAfter` are digest-verified and byte-compared. `nullStable` is included in persistence gate detail, and a change without a transaction FAILs. The fixture covers the mismatch.

### L4 — folded

The underlay-omission alpha-refusal result now independently requires exactly one valid take-cost publication in the advance-to-transition window and `record["placement"] == "frac"`. Otherwise holder-pixel scoring is INCONCLUSIVE. A no-take behavioral row asserts INCONCLUSIVE.

### L5 — folded

Settle order is now: live integrity controls, recording controls, one-second Program-toggle control, bounded `GetInputList` polling until every `AK-Control-*` source is absent, then the two equal OBS baseline samples. The absence result is retained in settle telemetry.

### L6 — folded

The flash positive no longer treats arbitrary frame changes as detection. It requires one or more contiguous changed frames with a white centre pixel and baseline-identical frames immediately before and after the interval. Tests cover a valid two-frame flash and an unrelated changed pixel.

### L7 — folded within W6 ownership

The qualification fixture now requests the explicitly defined `_input("snap")` case instead of relying on the undefined `"software-snap"` fallthrough. No edit to W2-owned `tests/test_placement_probe.py` was needed.

## Deviations and refutations

No assigned finding was refuted, and no frozen-contract redesign was required. The live session implementations are present but were not executed because this round explicitly forbids OBS, Chrome, and Keynote runs. Their records fail closed when a source, capture, rejection, restoration, recording, or disk-capacity requirement is absent.

## Verification

Mandated final command:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
484 passed, 1 skipped in 121.07s
```

Earlier complete development runs after the fold also passed:

- 484 passed, 1 skipped in 94.93s.
- 484 passed, 1 skipped in 97.39s.

Additional checks:

```text
env PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3.10 -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py
PASS

git diff --check -- scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py
PASS
```

No OBS, Chrome, headless browser, Keynote, full suite, or gate runner was invoked. No known external red was encountered by the targeted files.

## Open items for the coordinator

- Run the live placement qualification to measure the seven new pre-candidate sessions, confirm the frozen-video CDP pause produces the classifier's stale-motion rejection, and confirm both Studio-mode startup/restoration paths.
- Confirm the local OBS build renders the two-canvas-frame white control as a bounded white interval and whether the seeded `reroute_audio=false` path leaves the audio positive REPORTED as designed.
- Review the printed free-space estimate against the intended number of placement takes before starting the live run; the preflight deliberately refuses when the estimated retained plus working footprint does not fit.
