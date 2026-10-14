# W6 edge-fix fold report

Implemented B1 and L3-L5 in the two W6-owned files, then completed L6 offline diagnostics. No OBS, Chrome, Keynote, full suite, gate runner, source/runtime file, managed-qualification implementation file, .agents file, README, commit, stash, reset, checkout or rebase was touched.

## Files changed and contract mapping

- scripts/dissolve_probe.py:241-242: added NOOFFSET_X_DISPLACEMENT = -80.0 beside the y constant.
- scripts/dissolve_probe.py:457-463: both m-snap-cef-nooffset-x arms apply the nooffsetx in-memory override while retaining the near-x clip, frac-nooffset-x splice, displaced-x attribution and omit twin.
- scripts/dissolve_probe.py:1462-1479 and :1493-1499: shared axis-neutral nooffset placement; registered _nooffset_x; retained _nooffset_y on the same implementation. Each override builds the near clip before translating the renderMovie parent to a -80.0 content near edge.
- tests/test_dissolve_probe.py:438-452: synthetic fixtures follow each axis-specific nooffset placement.
- tests/test_dissolve_probe.py:1001-1063 and rows :1701-1717: real p2bin proofs cover both axes. X records content -80.0, visible clip (300.987187,795.036194,570.555781,267.62146), strip far edge 260.969564 outside the clip, displaced overlap (490.555781,267.62146), and all three pre-transition event/effect paint rectangles with no overlap. With the x splice applied, (fx,fy,fw,fh,ww,hh)=(-301,0.036194,952,268,571,268), so the W1 containment guard is false. The widened y proof checks the same three event/effect rectangles and computes (0.351707,-27,952,268,952,161), also accepted.
- scripts/dissolve_probe.py:2352-2356, tests/test_dissolve_probe.py:1261-1291 and row :1719: L3 makes absolute displacement below one device pixel INCONCLUSIVE, including 0.5 px.
- scripts/dissolve_probe.py:3447-3448, tests/test_dissolve_probe.py:264-271 and row :1485: L4 supplies eased progress only for demixed candidates that exist. With ev.B None the holder alone PASSes at [4.0].
- tests/test_dissolve_probe.py:1029-1030 and rows :1701-1717: L5 widens the nooffset overlap census to every pre-transition event/effect.
- Existing amplification-aware foreground work remains at scripts/dissolve_probe.py:2045-2071 and tests/test_dissolve_probe.py:245-261, row :1483: the holder uses tau and each demixed candidate uses tau/(1-e).

B1 maps to the plan section 5 m-snap-cef-nooffset-x holder-pixel control and Geometry/foreground gate. L3-L5 preserve section 11.6 scorer/run/gate formats and fail-closed evidence behavior. No Keynote main.js was edited; player work remains sha-pinned and W1-owned.

## Tests

Focused:
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k 'nooffset or foreground or displaced'
Result: 23 passed in 8.34s.

Required W6 targets:
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
Result: 503 passed, 1 skipped in 102.25s.

git diff --check -- scripts/dissolve_probe.py tests/test_dissolve_probe.py produced no output.

## L6 diagnostic offline rescore

The four 2026-10-14 live4 take trees were APFS-cloned to /private/tmp/w6-edgefix-rescore.poXHDJ. The scratch-only monkeypatch removed exactly the integrity problem "served digest is not the pinned digest for the mode"; no animation, evidence, threshold, expectation, player bytes or other scorer rule was altered.

| Take | Rate | m-fg-cef | Foreground | Other arms |
|---|---:|---|---|---|
| placement-20261014-123807 | 25 | MATCH/PASS | worst 2; limits [4.0,4.358758,5.003612,6.333312,9.899423] | 27 MATCH; m-snap-cef MISMATCH; nooffset-y INCONCLUSIVE |
| placement-20261014-130028 | 30 | MATCH/PASS | worst 5; limits [4.0,4.358758,5.003612,6.333312,9.899423,19.944793] | 27 MATCH; m-snap-cef MISMATCH; nooffset-y INCONCLUSIVE |
| placement-20261014-132259 | 25 | MATCH/PASS | worst 3; limits [4.0,4.553395,5.428426,7.729253,13.411108] | 27 MATCH; m-snap-cef MISMATCH; nooffset-y INCONCLUSIVE |
| placement-20261014-134519 | 30 | MATCH/PASS | worst 3; limits [4.0,4.553395,5.428426,7.729253,13.411108] | 27 MATCH; m-snap-cef MISMATCH; nooffset-y INCONCLUSIVE |

The 27 MATCH arms in every take are opaque-off, off, noblend, on2, m-paused-cef, m-off-cef, m-hold-cef, m-fg-cef, m-fg-omit-cef, m-fg-swap-cef, m-snap-cef-far-x, m-snap-cef-far-y, m-snap-cef-near-x, m-snap-cef-near-y, m-snap-cef-nooffset-x, m-snap-cef-underlay-omit, wrongrule-cef, perfect-shift, m-tone-cef, m-snap-cef-dsk, m-geo-scale, m-geo-base, cut-on, cut-off, on, opaque-on and m-tone-raw-cef.

Per take, model, complement, no-dip, curve, monotone, handoff, frozen-frame, foreground, cost and CvC PASS; matched is REPORTED. Frozen-region, holder-pixels, reference, mask and geometry remain INCONCLUSIVE. Overall remains FAIL due m-snap-cef MISMATCH. This diagnostic proves the current foreground scorer accepts m-fg-cef when only pin equality is relaxed; it does not turn old-byte captures into acceptance evidence.

## Deviations and coordinator open items

- Frozen section 11 contracts: no deviation.
- Historical nooffset captures do not qualify B1: x predates nooffsetx and y predates -80. The offline real-p2bin rows prove repaired geometry; final live qualification still needs fresh combined W1+W6 captures.
- m-snap-cef remains MISMATCH in all four pin-relaxed historical takes. Treat it as stale pre-edge-fix evidence and rerun final live placement qualification; do not weaken expectations.
- Listed external reds were not run or changed.
