# W6 live pass 2A report

Date: 2026-10-14  
Branch/worktree: `claude/cef-obs-placement` / `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Plan: `keynote_live_cef_placement.plan.md` rev 3.3, especially §5 and frozen contract §11.6  
Authoritative run rescored: `placement-20261013-231739.json` (25 fps)  
Read-only evidence source: `/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-13/live3/raw-out`

## Outcome

Implemented the spec-faithful Web Animations timing rule and fixed three W6 harness/instrument causes: the near-side clip coordinate transform, the raw-tone same-frame twin, and false shared-integrity rejection of intentionally undecodable no-offset negative-control strips. The final offline rescore improves `m-tone-raw-cef` and `m-snap-cef-nooffset-x` from INCONCLUSIVE to MATCH. The 25 fps round remains `VERDICT FAIL invalid None` because eight arms still do not MATCH: seven are evidence/harness limitations requiring new live evidence, and `m-tone-cef` is the inherited product/W5 non-identity tone-application gap.

No OBS, Chrome, headless browser, or Keynote process was run. The source evidence directory was never written; all rescoring used an APFS clone.

## Files changed

- `scripts/dissolve_probe.py`
  - `ARMS["m-tone-raw-cef"]` now reuses `m-tone-cef-twin`, which is the already-captured same-frame CEF omit twin (`:432-446`).
  - Both no-offset twins explicitly expect `holder_pixels=FAIL`, so the pair represents the same deliberate displaced-strip control (`:438-446`).
  - `_clip_near` now keeps the movie content coordinate and parent far edge fixed while moving only the parent near clipping edge; the former code mixed a video-local coordinate with a parent coordinate and displaced the content (`:1361-1375`).
  - `anim_problem` accepts unresolved `startTime` for a paused animation with resolved held `currentTime`, and for a running animation awaiting its pending play task. A null `currentTime` in any timed state remains invalid, as does a finished animation with null `startTime` (`:2538-2557`).
  - `media_integrity` still rejects a missing holder image, but an undecodable holder strip no longer voids the explicit no-offset negative controls whose declared result is `holder_pixels=FAIL`; the pixel gate itself must still produce FAIL (`:2984-3038`).
- `tests/test_dissolve_probe.py`
  - Extended the existing single parametrized scorer table; no new test function was added.
  - Added the live animation shape `{ct:750,start:null,state:"paused"}`, the running pending-play shape, and still-invalid null-current/finished-null-start shapes (`:1157-1164`).
  - Added synthetic coverage for the raw-tone twin, x/y near-clip coordinate invariants, and undecodable no-offset negative strips (`:865-898`, `:1292-1301`).
  - Tone fixtures now provide a same-frame foreground mask even for the paused raw control, matching the live twin contract (`:396-538`).
- `scripts/managed_obs_qualify.py`: unchanged.
- `tests/test_managed_obs_qualify.py`: unchanged.

The untracked `.agents/reviews/cef-placement-2026-10-13/*` files visible in the worktree pre-existed this work and were not edited.

## §5 / §11.6 contract mapping

The existing W6 implementation continues to map the frozen record contract as follows; this pass did not redesign it.

| Contract item | Implementation |
|---|---|
| Recursive `placementCalibration` serialization, enum/snake-case conversion, PNG `FileRef`, transaction evidence `$ref` | `serialize_placement_calibration`, `placement_file_ref`, and `_placement_ref_bytes` in `scripts/dissolve_probe.py:784-1002` |
| Required schema fields and rejection of unsupported/malformed records | `placement_calibration_problems` in `scripts/dissolve_probe.py:873-1019` |
| Exact §11.6 record creation (`backend`, placement, OBS/engine/request/assets/player/input/classification/transaction/events/persistence/integrity/gates) | `placement_record` in `scripts/managed_obs_qualify.py:698-735`; populated in the managed session at `:2199-2208` |
| Same W2 classifier input/result and W3 transaction/persistence evidence | `score_placement_calibration` in `scripts/managed_obs_qualify.py:409-617` |
| Freshness, isolation, moving-program null/positive controls, lifecycle, persistence, continuous recording, sampled RGBA, and fail-closed missing evidence | `score_placement_calibration` gates at `scripts/managed_obs_qualify.py:409-617`; live capture/telemetry construction at `:2084-2208` |
| Program-toggle positive control and static null/visible/behind-transparent controls | `program_guard_controls` result consumed at `scripts/managed_obs_qualify.py:516-535`; recorded at `:2085`, `:2132-2134`, `:2182` |
| Lossless program recording, frame coverage, skipped-frame/audio checks and positive controls | `analyze_program_recording` and `recording_positive_controls` at `scripts/managed_obs_qualify.py:861-935`, `:1276-1322`; fail-closed scorer at `:536-614` |
| Alpha/RGBA evidence around install/capture/cleanup/restore | `analyze_rgba_samples` at `scripts/managed_obs_qualify.py:936-978`; capture/reference emission at `:2151-2186` |
| CEF clip, holder/reference/mask, geometry, tone, cost, DSK, and O1 arms | arm table and profiles in `scripts/dissolve_probe.py:280-505`; scorers at `:1936-2180`, `:2984-3150` |
| Harness-only Chrome classifier and script-only placement mode | Chrome arms/profile in `scripts/dissolve_probe.py:412-415`, `:2410-2517`; no product grant is introduced |
| O1 forged snap/frac rows in existing `m-raw-prod` / `m-preview-prod`, with no holder expected except the pinned known-bad control | `FORGERIES` arm expansion in `scripts/dissolve_probe.py:366-389` and existing scorer-table rows in `tests/test_dissolve_probe.py:1275-1280` |
| Offline rescore through the same classifier, persistence and arm APIs; missing evidence remains INCONCLUSIVE | `placement_gates` in `scripts/managed_obs_qualify.py:3100-3175`, calling `score_placement_calibration` and `dissolve_probe.score_runs` |

No §11.6 schema deviation was introduced. The fixes preserve the required fail-closed behavior: missing images/evidence still become INCONCLUSIVE, and an expected FAIL is accepted only when the dedicated scorer actually returns FAIL.

## Root causes and disposition

Paths below use `E=.../raw-out/shots/placement-20261013-231739/runs`. Every `record.json` is minified, so JSON evidence is at line 1 and is identified by its field path.

| Arm(s) / issue | Class; age | Evidence | Fix or proposal |
|---|---|---|---|
| Paused `startTime:null` rejected before arm scoring | INSTRUMENT; inherited from the dissolve scorer | Live records contain paused animation rows with `ct=750` and no `start`; Web Animations permits an unresolved start time while paused with held current time. The former predicate at `dissolve_probe.py:2553` rejected it. | Fixed at `scripts/dissolve_probe.py:2538-2557`. Timed `ct:null` and finished `start:null` remain errors. |
| `m-snap-cef-near-y`, `m-snap-cef-nooffset-y`, and twins: 0 holders/no decoder/reference `None` | HARNESS; new to the CEF-placement y-near fixture | `E/m-snap-cef-near-y/record.json:1` has content and region both `[109.3673,112.4186,951.5,267.6094]`: no near clipping occurred and the content moved from the normal y≈795 position. The matching far-y cell has content y≈795 and clipped region height≈160.94. Near-x happened to bind, but its content x moved to≈386, also proving the old helper moved content. The 30 fps invalid-for-sleep run repeats the exact geometries and 0-holder y result, excluding a one-off session race. Override/player digests differ from the unclipped cell, so the setup reached the served slide; this evidence does not establish a product admission refusal. | Fixed `_clip_near` at `scripts/dissolve_probe.py:1361-1375`; unit evidence proves unchanged content, moved near edge, unchanged far edge for x and y. Existing captures cannot be repaired, so these arms need a fresh live rerun. If a corrected rerun still refuses y, add a sha-pinned in-memory admission-reason probe and then classify product behavior. |
| `m-snap-cef-nooffset-x` and twin: holder strip would not decode | INSTRUMENT; new | `E/m-snap-cef-nooffset-x/record.json:1` has one holder and a bound paused decoder. The no-offset splice deliberately shifts the binary strip, so decoding that strip as a shared integrity prerequisite erased the intended pixel-negative signal. Final rescore obtains `holder_pixels FAIL {interior:250,edge:0}`, `reference PASS`, `mask PASS`. | Fixed only for arms explicitly declaring `holder_pixels=FAIL`; both arm and twin carry that expectation. Missing holder pixels are still an integrity error. Final outcome MATCH. The y twin remains blocked by the old near-y capture, not by strip decoding. |
| `m-snap-cef-dsk`: strip decode failure and four mid frames | HARNESS; new | `E/m-snap-cef-dsk/record.json:1` binds two holders/decoders but the arm inherits `movies="h264"` from `cef-skip-dsk` (`scripts/dissolve_probe.py:346`, `:448-449`). `E/m-snap-cef-dsk/holder-0.png` and `holder-1.png` are real church-video pixels, not the counter strip required by `media_integrity`. The record has only four usable mid frames; §5 requires five. The 30 fps run repeats two holders with the same non-counter fixture. | Not weakened or guessed around. Proposed harness fix: provide each DSK decoder a pinned decodable frame marker/reference (or capture an independently bound, lossless pre-detach reference for each real video), and obtain at least five in-window frames from the continuous recording/capture path. Do not lower the five-frame contract or treat arbitrary video as a counter strip. |
| `m-snap-cef`, `wrongrule-cef`: empty edge band | HARNESS; new | Final score: `m-snap-cef` has `interior=2, edge=null`; `wrongrule-cef` has `interior=183, edge=null`. Both reference and mask gates PASS, but `score_holder_pixels` correctly returns INCONCLUSIVE at `scripts/dissolve_probe.py:2151-2169` when either the unmasked interior or edge band is empty. Plan §5 explicitly requires interior **and edge** scoring; an interior-only wrong-rule failure cannot satisfy it. The 30 fps run repeats the same holder layout. | No scorer change. Proposed harness fix: adjust the live foreground/twin fixture so the verified production mask leaves measurable holder-edge pixels while still crossing the video, then rerun both cells. Passing an empty edge or redefining the edge band would violate §5. |
| `m-tone-cef`: tone FAIL, worst 12 LSB, CvC 0 | PRODUCT; inherited/open W5 tone-map item | Final rescore independently classifies the CEF probe as GPU analytic, but the take remains identity-mapped: `tone FAIL {worst:12,cvc:0}` in the final detail. Stable CvC zero rules out frame instability. The arm expects tone PASS; raw identity control expects tone FAIL and now does so. | No W6 product edit. This is the plan's explicit “non-identity application still requires its separate qualification” item. Coordinator/W5 must decide and qualify application of the observed map on product bytes; identity behavior remains a required visible retained step, not a scorer tolerance change. |
| `m-tone-raw-cef`: “no twin to verify the production mask” | HARNESS; inherited arm-definition omission | `m-tone-cef-twin` was already in `PLACEMENT_ARMS`, but `m-tone-raw-cef` inherited `twin=None`; this was not an intentional §5 exemption because tone scoring requires verified mask coverage. | Fixed by pointing `m-tone-raw-cef` at the existing same-frame `m-tone-cef-twin`; no extra session added. Final outcome MATCH with the expected identity `tone FAIL {worst:12,cvc:0}`. |
| `cut-on`, `cut-off`: no frame inside insertion→completion | HARNESS; inherited parent DX-1 cut limitation | Both final details say `no screencast frame inside [DOM insertion, cut completion]`. `scripts/managed_obs_qualify.py:1805-1810` supplies paced OBS source screenshots as cast frames; the 1 ms cut interval closes before one can fall wholly inside. The 30 fps run repeats the same setup; its invalid sleep timing is irrelevant to this structural interval issue. | Not weakened. Proposed parent-harness fix: timestamp frames from the continuous program-wire recording/screencast at sufficient cadence and bind one to the cut interval. Do not widen the interval or accept an outside frame. |

## Final 25 fps offline rescore

Clone: `$SCR/w6/live3-final2`  
Detail: `$SCR/w6/live3-final2-detail.json`  
Log: `$SCR/w6/live3-final2-rescore.log`

Command:

```text
PYTHONPATH=src .venv/bin/python "$SCR/tools/rescore.py" "$SCR/w6/live3-final2/runs/placement-20261013-231739.json" "$SCR/w6/live3-final2" /Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json baseline "$SCR/w6/live3-final2-detail.json"
```

Overall: `VERDICT FAIL invalid None`.

| Arm | Outcome | Remaining reason when not MATCH |
|---|---|---|
| opaque-off | MATCH | — |
| off | MATCH | — |
| noblend | MATCH | — |
| on2 | MATCH | — |
| cut-on | INCONCLUSIVE | no screencast frame wholly inside insertion→cut completion |
| cut-off | INCONCLUSIVE | same |
| m-paused-cef | MATCH | — |
| m-off-cef | MATCH | — |
| m-snap-cef | INCONCLUSIVE | no kept edge-band pixels (`interior=2`, `edge=null`) |
| m-hold-cef | MATCH | — |
| m-fg-cef | MATCH | — |
| m-fg-omit-cef | MATCH | — |
| m-fg-swap-cef | MATCH | — |
| m-tone-cef | MISMATCH | expected PASS; tone FAIL (`worst=12`, `cvc=0`) |
| m-tone-raw-cef | MATCH | fixed; expected tone FAIL observed |
| m-snap-cef-far-x | MATCH | — |
| m-snap-cef-far-y | MATCH | — |
| m-snap-cef-near-x | MATCH | old capture scores, but old helper was not a true content-preserving near clip; rerun with corrected helper |
| m-snap-cef-near-y | INCONCLUSIVE | old malformed near-y fixture yielded 0 holders; corrected helper needs live rerun |
| m-snap-cef-nooffset-x | MATCH | fixed; expected pixel FAIL observed |
| m-snap-cef-nooffset-y | INCONCLUSIVE | old malformed near-y fixture yielded 0 holders; corrected helper needs live rerun |
| m-snap-cef-underlay-omit | MATCH | — |
| wrongrule-cef | INCONCLUSIVE | no kept edge-band pixels (`interior=183`, `edge=null`) |
| perfect-shift | MATCH | — |
| m-snap-cef-dsk | INCONCLUSIVE | non-decodable real-video holders and `4 mid frames < 5` |
| m-geo-scale | MATCH | — |
| m-geo-base | MATCH | — |
| on | MATCH | — |
| opaque-on | MATCH | — |

Gate summary:

| Gate | Verdict |
|---|---|
| model, complement, no_dip, curve, monotone, handoff | PASS |
| foreground | PASS |
| cvc | PASS |
| matched | REPORTED |
| cut | INCONCLUSIVE |
| frozen_frame | INCONCLUSIVE |
| frozen_region | INCONCLUSIVE |
| tone | INCONCLUSIVE |
| cost | INCONCLUSIVE |
| holder_pixels | INCONCLUSIVE |
| reference | INCONCLUSIVE |
| mask | INCONCLUSIVE |
| geometry | INCONCLUSIVE |

The FAIL is therefore an acceptance failure from fail-closed arm/gate outcomes, not an invalid run envelope (`invalid None`).

## Tests and checks

Red-before-fix targeted reproduction:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest 'tests/test_dissolve_probe.py::test_dissolve_scorer[live3 animation timing follows unresolved start-time semantics]' 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement raw tone control reuses the same-frame CEF omit twin]' 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement near-side clip preserves content and moves only the clipping edge]' 'tests/test_dissolve_probe.py::test_dissolve_scorer[placement nooffset defect remains a valid FAIL when its holder strip is undecodable]' -q -n 2 -p no:cacheprovider
```

Result before implementation: **4 failed, 0 passed**.  
Result after final implementation: **4 passed, 0 failed** in 2.96 s.

Required targeted files:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

Result after final implementation: **489 passed, 1 skipped, 0 failed** in 229.95 s (3:49).

`git diff --check`: PASS, no output.

No known external reds appeared because the prohibited full/other-stream suite was not run.

## Open items for the coordinator

1. Run a new live CEF placement pass with corrected `_clip_near`; treat old near-x as non-qualifying geometry even though it rescored MATCH, and confirm near-y/nooffset-y now bind. If corrected y still refuses, instrument the sha-pinned in-memory player admission reason before assigning a product bug.
2. Redesign the `m-snap-cef`/`wrongrule-cef` live foreground/twin layout to leave verified edge-band pixels; retain both-edge-and-interior scoring.
3. Replace the DSK qualification's arbitrary real-video strip assumption with a pinned per-decoder reference/marker path and collect at least five mid frames.
4. Resolve the inherited W5/product non-identity tone-application item; do not widen the 2-LSB gate. `m-tone-raw-cef` now supplies the correct identity negative control.
5. Fix the inherited cut evidence source using continuous program-wire timestamps rather than paced source screenshots.
6. Re-run the 25 and 30 fps live qualifications after the harness changes. The 30 fps `placement-20261013-234036.json` remains invalid for sleep and must not qualify timing, although it independently repeats the near-y 0-holder geometry and the DSK/edge fixture shapes.
