# W6 live4 fold report

Implemented only live4 diagnosis items 2 and 3. No OBS, Chrome, Keynote, full suite, gate runner, source/runtime file, managed qualification file, or other stream file was touched.

## Files changed

- `scripts/dissolve_probe.py`
- `tests/test_dissolve_probe.py`

`scripts/managed_obs_qualify.py` and `tests/test_managed_obs_qualify.py` were unchanged.

## Item 2 — nooffset-y harness placement

- `scripts/dissolve_probe.py:241`: changed `NOOFFSET_Y_DISPLACEMENT` from `125.0` to `-80.0`.
- `scripts/dissolve_probe.py:2338-2347`: allowed the existing displaced-holder attribution scorer to handle either sign of non-zero displacement. This is required because the corrected content origin is above the stage (`-80`) while the missing `r.top-R.top` term moves the defective quad downward by 80 px. Zero displacement still fails closed.
- `tests/test_dissolve_probe.py:445-453`: retained an opaque backing in the synthetic nooffset-y negative and gave its movie a vertical signal shifted in the same direction as the omitted offset.
- `tests/test_dissolve_probe.py:990-1044`, table row at `:1665-1671`: the existing real-p2bin row now proves:
  - content top `-80.0`, content height `267.6214599609375`, so `abs(displacement) < content height`;
  - visible near-clip box `(109.351707, 27.418584, 951.542969, 160.202876)`, ending at `187.621460`;
  - the only later-painted build texture is `18B86872E5CD75C18A5696F17F574999` at `(740, 190, 353, 313)`, with no positive-area overlap with the visible clip;
  - counter-strip bottom `-56.211426`, outside the clip;
  - predicted displaced-content attribution overlap `(951.542969, 80.202876)`, non-empty;
  - both main/twin retain the `nooffsety` override and the correct holder remains PASS while the synthetic nooffset defect remains FAIL/MATCH.

This maps to §5 `m-snap-cef-nooffset-y` and holder-pixel attribution, while retaining §11.6's existing arm/record/gate formats.

## Item 3 — amplification-aware foreground scoring

- `scripts/dissolve_probe.py:2032-2046`: extracted `_demix_limit(cal, e) = tau / (1-e)` and made the existing region scorer use it.
- `scripts/dissolve_probe.py:2049-2059`: kept the direct holder candidate at `tau`; every subsequent demixed candidate now receives the shared amplification-aware bound for its own eased progress. Missing/mismatched/non-finite progress remains INCONCLUSIVE.
- `scripts/dissolve_probe.py:3433-3434`: `score_media` passes the exact eased progress values paired with its demixed foreground candidates.
- `tests/test_dissolve_probe.py:245-261`, table row at `:1449-1450`: at `e=0.7994`, a one-LSB pre-division perturbation becomes a 5-LSB demixed residual and PASSes against bounds `[4.0, 19.940179]`; a 25-LSB foreground defect at the same progress FAILs; a direct-holder 5-LSB residual also FAILs, proving the holder threshold was not raised.

This maps to §5 Geometry/foreground and §11.6 offline rescoring through the same scorer API. No §11 contract deviation was required.

## Tests

Red-capable regression run after adding the rows and before the implementation:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k 'nooffset or demix'
2 failed, 4 passed in 1.82s
```

Final focused regression run:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k 'nooffset or demix'
6 passed in 1.66s
```

Full permitted W6 target run:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
501 passed, 1 skipped in 112.14s
```

`git diff --check -- scripts/dissolve_probe.py tests/test_dissolve_probe.py` produced no output.

## Offline re-score of the four live4 takes

Each take was read from its own fresh APFS clone under:

```text
/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/live4-rescore-final.25nPUj
```

The replay called `managed_obs_qualify.placement_gates` and the final `dissolve_probe` scorer. It retained the supplied rescore tool's captured-paused-animation compatibility rule. All four strict results are identical because the parallel W1 item-1 change re-pinned the final live player after these takes were recorded: the captures contain pin `e57025c3047b2d842fdb10ff550851d1609c65707f0b9b59663cd9146e583b5b`, while the current final pin is `d3ddd770dae1cd4aeb67a68a7e6aa12ef3d890b5ce4cd1cb19db81ec5e709d54`. Per the integrity contract, unspliced old-byte evidence is INCONCLUSIVE rather than silently waived.

| Take | Rate | Overall | MATCH arms | INCONCLUSIVE arms |
|---|---:|---|---|---|
| `placement-20261014-123807` | 25 | FAIL | `cut-off`, `m-fg-omit-cef`, `m-fg-swap-cef`, `m-hold-cef`, `m-off-cef`, `m-snap-cef-underlay-omit`, `noblend`, `off`, `opaque-off` | `cut-on`, `m-fg-cef`, `m-geo-base`, `m-geo-scale`, `m-paused-cef`, `m-snap-cef`, `m-snap-cef-dsk`, `m-snap-cef-far-x`, `m-snap-cef-far-y`, `m-snap-cef-near-x`, `m-snap-cef-near-y`, `m-snap-cef-nooffset-x`, `m-snap-cef-nooffset-y`, `m-tone-cef`, `m-tone-raw-cef`, `on`, `on2`, `opaque-on`, `perfect-shift`, `wrongrule-cef` |
| `placement-20261014-130028` | 30 | FAIL | same 9 arms | same 20 arms |
| `placement-20261014-132259` | 25 | FAIL | same 9 arms | same 20 arms |
| `placement-20261014-134519` | 30 | FAIL | same 9 arms | same 20 arms |

There are no MISMATCH outcomes in the strict final-byte replay. Gate outcomes are also identical: `cvc=PASS`, `matched=REPORTED`, and model/complement/no-dip/curve/monotone/handoff/frozen-frame/frozen-region/foreground/cost/holder-pixels/reference/mask/geometry are INCONCLUSIVE.

The saved `m-snap-cef-nooffset-y` captures were made with the old `y=125` harness and contain zero holders, so they cannot demonstrate the new placement offline. A fresh live qualification on the final combined player/harness bytes is required for that arm. The strict final-pin rule likewise prevents today's old-byte `m-fg-cef` capture from becoming an acceptance result, although the exact `e=0.7994` amplification case is locked by the new offline row.

## Deviations and coordinator open items

- Frozen §11 contracts: no deviation.
- Item 1/product edge row: untouched as directed; current `src/obed_edom/live_runtime.py` and `tests/test_live_runtime.py` changes belong to W1.
- Coordinator must rerun live4 qualification on the final W1+W6 bytes. Today's four takes are valid diagnostic evidence but fail closed for final acceptance because of the player-pin change, and their nooffset-y arm predates the `-80` layout.
- Known external reds listed in the brief were not run or changed.
