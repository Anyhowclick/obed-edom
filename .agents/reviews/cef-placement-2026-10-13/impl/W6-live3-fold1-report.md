# W6 live3 fold 1 report

Date: 2026-10-14  
Branch/worktree: `claude/cef-obs-placement` / `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Plan: `keynote_live_cef_placement.plan.md` rev 3.3, §5 and frozen contract §11.6  
Authoritative run rescored: `placement-20261013-231739.json` (25 fps)

## Outcome

Implemented all non-live fold requirements in W6's files. Near clipping is geometry-preserving for every child, a fully off-canvas counter strip is accepted only with paused rVFC identity evidence, partial/unreadable geometry still fails closed, no-offset controls use an explicit displaced-strip mode plus pixel attribution, and the base/wrong-rule CEF cells now use an inset foreground fixture that leaves both the interior and the existing edge band measurable. `cut` and `tone` are reported in the CEF placement profile as directed.

The required targeted suite passes: **494 passed, 1 skipped, 0 failed**. No OBS, Chrome/headless browser, or Keynote process was run. The 25 fps evidence was rescored from a fresh APFS clone in tool-baseline mode and remains `VERDICT FAIL invalid None`; the remaining INCONCLUSIVEs are old-capture evidence that the new fixture/scorer cannot retroactively supply, plus the DSK five-frame/counter-strip limitation.

## Files changed

- `scripts/dissolve_probe.py`
  - Adds the explicit `Arm.counter_strip` contract and assigns `displaced-x`/`displaced-y` to both no-offset arm/twin pairs; twins no longer carry trigger-only expectations (`:256-259`, `:433-451`).
  - Gives `m-snap-cef`, its twin, and `wrongrule-cef`/twin the `edgefg` override. `_edge_foreground` retains the purpose-built inset foreground layers but removes the fixture's full movie-frame foreground texture, the source of the empty edge band (`:416-450`, `:1339-1346`, `:1403-1407`).
  - Reworks `_clip_near` so only the parent near clipping edge moves: the far edge remains fixed and every direct child is translated by the same inverse amount, preserving every child's absolute near edge (`:1373-1392`).
  - Adds strip-vs-canvas geometry classification and displaced-holder attribution over the predicted overlap (`:2068-2084`, `:2207-2260`).
  - Makes holder integrity geometry-aware: missing pixels remain an error; an undecodable strip is accepted only when it is fully outside a paused holder with valid rVFC evidence, or for an explicitly declared displaced control. Partial overlap and malformed geometry remain failures (`:3120-3134`).
  - Scores a fully clipped paused strip through the verified rVFC reference and records the exact diagnostic `strip clipped by geometry`; holder scoring also records it (`:3171-3182`, `:3385-3403`).
  - Reports inherited `cut` and identity-take `tone` checks in `CEF_PLACEMENT` (`:2581-2597`).
  - Retains the prior live3 corrections: raw-tone reuses the same-frame CEF twin, and Web Animations permits unresolved `startTime` for paused/running pending-play states while requiring resolved `currentTime` and a finished start time (`:435-437`, `:2626-2645`).
- `tests/test_dissolve_probe.py`
  - Extends the existing single parametrized scorer table; no new pytest function was added.
  - Uses the real p2bin slide to prove all three direct child absolute near edges are unchanged for both axes while only the parent near edge moves and the far edge stays fixed (`:881-911`, case at `:1389-1390`).
  - Adds correct x/y near-clip MATCH rows with `strip clipped by geometry`, plus partial-overlap and stale-rVFC fail-closed rows (`:913-941`, cases at `:1391-1394`).
  - Proves the edge fixture removes the identified full-frame foreground child and leaves unmasked pixels in both the unchanged interior and edge masks (`:943-972`, case at `:1395-1396`).
  - Covers explicit displaced modes for both twins, matching, wrong-pixel, and fully clipped attribution outcomes (`:974-994`, cases at `:1397-1400`).
  - Preserves/extends raw-tone and animation timing regressions and adapts synthetic near-clip media without using the production helper's own geometry model (`:385-538`, `:1245-1253`, `:1382-1388`).
- `scripts/managed_obs_qualify.py`: unchanged; its existing §11.6 harness implementation already supplies the requested record, gates, recording/RGBA, controls, Chrome/W5, and offline rescore paths.
- `tests/test_managed_obs_qualify.py`: unchanged; its existing offline fixtures remained green.

The untracked `.agents/reviews/cef-placement-2026-10-13/*` files pre-existed this work and were not edited.

## Review findings

### M1 / O-M1 — geometry-aware near strips

Fixed at `scripts/dissolve_probe.py:2068-2084`, `:3120-3134`, and `:3171-3182`. The scorer distinguishes `outside`, `inside`, `partial`, and unreadable geometry. Only `outside` plus a paused capture can bypass strip decoding, and the existing media-integrity checks still require the requested rVFC frame. `score_media` then uses that verified reference for frame identity and records `strip clipped by geometry`. A real-p2bin-derived x/y positive scores MATCH. Partial overlap and a stale paused frame are explicitly tested and remain integrity failures.

### M2 — child-preserving near clip and empty edge band

Fixed at `scripts/dissolve_probe.py:1373-1392`. The real p2bin test independently computes each child's absolute edge before and after and obtains zero delta for all three children on x and y; it also proves the intended parent near edge and unchanged far edge.

The old 25 fps records identify a different cause for `m-snap-cef`/`wrongrule-cef`: their verified production mask leaves interior pixels but no edge pixels (`2/null` and `183/null` respectively). Inspection of the real p2bin hierarchy showed the stock foreground movie-frame texture covering the holder edge. The new `edgefg` fixture removes only texture `3231B69B05EF0523B6E951F3B1F2B938` while retaining the inset foreground texture/square layers. The test applies the unchanged production mask dilation and proves both interior and edge support. Historic captures still contain the former layout, so only a live rerun can settle those cells.

### M4 — explicit displaced-strip controls and attribution

Fixed at `scripts/dissolve_probe.py:256-259`, `:433-451`, `:2207-2260`, and `:3385-3403`. Detection no longer depends on a splice substring. Both arm and twin declare `counter_strip="displaced-x"` or `"displaced-y"`; twins inherit no `expect`. The attribution scorer derives the predicted displacement from decoder rect versus stage origin, intersects decoder content with the holder/source/shifted-target canvases, excludes the verified production mask at both samples, applies the selected tone LUT, and requires the premultiplied RGBA residual to be within `tau`. A geometry-empty overlap is recorded as `displaced content clipped by geometry`; missing/malformed evidence is INCONCLUSIVE.

The old nooffset-x record now correctly becomes INCONCLUSIVE: its original holder-pixel negative is FAIL as expected, but the newly required attribution is also FAIL (`worst=6`, `tau=2`, 22,363 overlap pixels). That evidence cannot prove the intended cause and must not MATCH. Nooffset-y lacks holders in the old malformed near-y capture.

### M3 / owner profile decisions

`cut` and `tone` were added to `CEF_PLACEMENT.reported` at `scripts/dissolve_probe.py:2581-2597`. Both cut rows remain executed and both now MATCH as reported observations. `m-tone-cef` remains the identity take, its mask is enforced, and its recorded tone observation remains visible (`REPORTED`, observed FAIL, worst 12, CvC 0). The independent managed qualification check still enforces that drive-time tone matches classification at `scripts/managed_obs_qualify.py:649-660`; W5 tone-row completeness remains fail-closed at `:663-671`. `m-tone-raw-cef` remains the identity negative and reuses `m-tone-cef-twin`.

### DSK investigation and proposal

No DSK implementation was made because the reuse condition is only half satisfied and the five-mid-frame condition is not satisfied.

- Both DSK decoders play `clip-10-1000001.mov-0.0000-20.8000.mov` / `clip-10-1000002.mov-0.0000-50.2000.mov`; `resolve()` only installs the existing counter replacement for names matching `Untitled.mov-*.mov` (`scripts/dissolve_probe.py:1440-1460`). Thus the present two holder captures contain real program pixels, not decodable counter strips.
- The already pinned/generated `Untitled.mov-*` counter path could be explicitly aliased to both DSK decoder URLs without adding fixture bytes, but both retained live runs produced only four usable mid frames: the valid 25 fps run `231739` and the 30 fps invalid-for-sleep corroboration run `234036`. The current screenshot cadence therefore does not meet §5's five-frame requirement.

Concrete proposal: add an arm-scoped resolver alias in `scripts/dissolve_probe.py` that maps each of the two DSK clip URLs to the existing pinned counter movie while retaining distinct decoder IDs and holder bindings; add an existing-format, alpha-capable capture source in `scripts/managed_obs_qualify.py` that demonstrably supplies at least five in-window frames; cover the resolver/binding and offline scorer paths in the two W6 test files. Contract delta/risk: using decoded program-recording frames would change the current screenshot evidence semantics and may lose alpha/unpremultiplication fidelity, while binding one movie twice could accidentally collapse decoder identity. This needs coordinator/owner selection rather than silently weakening the five-frame or strip contract.

## §5 / §11.6 contract mapping

| Frozen item | Implementation |
|---|---|
| Schema v1, exact fields, recursive dataclass/enum serialization, full-digest relative `FileRef`, PNG capture refs, transaction evidence `$ref` | `scripts/dissolve_probe.py:788-1008` (`placement_file_ref`, `_placement_ref_bytes`, `serialize_placement_calibration`, `deserialize_placement_calibration`, `placement_schema_problems`) |
| Record constructor for backend/placement/OBS/engine/request/assets/player/input/classification/transaction/events/persistence/integrity/gates | `scripts/managed_obs_qualify.py:698-723`; CEF population at `:2199-2209`; Chrome-harness population at `:2259-2263` |
| Same W2 classifier and W3 persistence API for live/offline scoring; missing evidence → INCONCLUSIVE | `scripts/managed_obs_qualify.py:373-403`, `:409-681`, and `:3100-3175` |
| Freshness/isolation/lifecycle, moving-program null and Program-toggle positive control | scoring at `scripts/managed_obs_qualify.py:495-535`, `:638-660`; live controls at `:1212-1273`, `:1733-1770`, `:2082-2089` |
| Continuous lossless Program recording, frame coverage, skipped-frame/audio checks, flash/audio controls | analysis/scoring at `scripts/managed_obs_qualify.py:536-614`, `:861-935`, `:1276-1325`; transaction bracketing at `:2096-2100`, `:2161-2173` |
| Sampled raw RGBA over transparent Program before/install/captures/cleanup/restore and alpha controls | `scripts/managed_obs_qualify.py:616-635`, `:936-978`, `:2073-2076`, `:2151-2186` |
| CEF clip rows, holder/reference/mask/geometry/tone/cost, reported cut/tone, DSK | arm/profile/scorer definitions in `scripts/dissolve_probe.py:280-505`, `:1936-2260`, `:2581-2597`, `:3120-3403` |
| Harness-only Chrome classifier and W5 tone rows; script-only `placement_mode="probe"` | `scripts/dissolve_probe.py:3862-3900`; `scripts/managed_obs_qualify.py:664-671`, `:2110-2116`, `:2240-2264` |
| O1 forged snap/frac rows stay in existing `m-raw-prod` / `m-preview-prod` arms and bind no holder | existing `FORGERIES` expansion at `scripts/dissolve_probe.py:366-389`; existing offline scorer cases remain green |
| Offline rescore uses the same classifier/persistence and dissolve APIs | `scripts/managed_obs_qualify.py:3100-3175` and `scripts/dissolve_probe.py:4520-4590` |

No §11.6 record-schema deviation was introduced. The only unimplemented requested cell is DSK counter/five-frame qualification, for the evidenced contract/risk reasons above; it remains INCONCLUSIVE rather than being silently redesigned or treated as an expected failure.

## Final 25 fps offline rescore

Fresh APFS clone: `$SCR/w6/live3-fold1-final2`  
Detail: `$SCR/w6/live3-fold1-final2-detail.json`

Command:

```text
PYTHONPATH=src .venv/bin/python "$SCR/tools/rescore.py" "$SCR/w6/live3-fold1-final2/runs/placement-20261013-231739.json" "$SCR/w6/live3-fold1-final2" /Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json baseline "$SCR/w6/live3-fold1-final2-detail.json"
```

Result: `VERDICT FAIL invalid None`.

| Arm | Outcome | Note / live-rerun status |
|---|---|---|
| opaque-off | MATCH | — |
| off | MATCH | — |
| noblend | MATCH | — |
| on2 | MATCH | — |
| cut-on | MATCH | Reported; observation remains INCONCLUSIVE in detail |
| cut-off | MATCH | Reported; observation remains INCONCLUSIVE in detail |
| m-paused-cef | MATCH | — |
| m-off-cef | MATCH | — |
| m-snap-cef | INCONCLUSIVE | Old edge layout has no kept edge pixels; **live rerun required** |
| m-hold-cef | MATCH | — |
| m-fg-cef | MATCH | — |
| m-fg-omit-cef | MATCH | — |
| m-fg-swap-cef | MATCH | — |
| m-tone-cef | MATCH | Reported identity observation: tone FAIL, worst 12, CvC 0 |
| m-tone-raw-cef | MATCH | Identity negative observed |
| m-snap-cef-far-x | MATCH | — |
| m-snap-cef-far-y | MATCH | — |
| m-snap-cef-near-x | MATCH | Historic geometry was not child-preserving; **live rerun required to qualify** |
| m-snap-cef-near-y | INCONCLUSIVE | Historic malformed near-y capture has 0 holders; **live rerun required** |
| m-snap-cef-nooffset-x | INCONCLUSIVE | Historic attribution residual 6 > tau 2; **live rerun required** |
| m-snap-cef-nooffset-y | INCONCLUSIVE | Historic malformed near-y capture has 0 holders; **live rerun required** |
| m-snap-cef-underlay-omit | MATCH | — |
| wrongrule-cef | INCONCLUSIVE | Old edge layout has no kept edge pixels; **live rerun required** |
| perfect-shift | MATCH | — |
| m-snap-cef-dsk | INCONCLUSIVE | 4 mid frames < 5 and holder strips do not decode; proposal above |
| m-geo-scale | MATCH | — |
| m-geo-base | MATCH | — |
| on | MATCH | — |
| opaque-on | MATCH | — |

Gate summary: `model`, `complement`, `no_dip`, `curve`, `monotone`, `handoff`, `foreground`, and `cvc` PASS; `matched` is REPORTED; `frozen_frame`, `frozen_region`, `cost`, `holder_pixels`, `reference`, `mask`, and `geometry` are INCONCLUSIVE. `cut` and `tone` no longer participate in the profile's acceptance controls because they are explicitly reported.

## Tests and checks

Required targeted command:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

Exact result: **494 passed, 1 skipped, 0 failed in 95.59 s**.

Additional non-live checks:

- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile scripts/dissolve_probe.py tests/test_dissolve_probe.py`: PASS.
- `git diff --check`: PASS, no output.
- No prohibited full suite or other-stream tests were run; therefore none of the three declared external census reds appeared.

## Open items for the coordinator

1. Run the corrected live CEF rows for `m-snap-cef`/twin, `wrongrule-cef`/twin, near-x/y and their twins, and nooffset-x/y and their twins. Historic near-x must not be used as qualifying geometry even though it rescored MATCH.
2. Review/choose the DSK proposal. Do not lower the five-mid-frame rule or accept real-video pixels as a counter strip. If recording-derived frames are selected, record the §5/§11 evidence-format decision explicitly.
3. Run the managed OBS qualification to populate the currently missing live §11.6 evidence, including lifecycle/persistence quit state, Program recording/RGBA, Chrome launches, and full W5 tone rows. This implementation deliberately did not run live applications.
4. Resolve the separate W5 non-identity tone-application qualification if desired; the CEF placement take remains identity and reported per the owner decision.
5. Coordinator should commit only the two allowed modified W6 files. The pre-existing untracked `.agents/reviews/...` files were not touched.

## Skills used

- [obed-edom skill](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/skills/obed-edom/SKILL.md) for repo-specific qualification and validation workflow.
- [diagnosing-bugs skill](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/skills/diagnosing-bugs/SKILL.md) for evidence-led root-cause classification and fail-closed fixes.
