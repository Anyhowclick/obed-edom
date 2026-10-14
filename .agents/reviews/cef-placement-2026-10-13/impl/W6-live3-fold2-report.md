# W6 live3 fold 2 report

Date: 2026-10-14  
Branch/worktree: `claude/cef-obs-placement` / `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Plan: `keynote_live_cef_placement.plan.md` rev 3.3, §5 and frozen contract §11.6  
Authoritative historical run rescored: `placement-20261013-231739.json` (25 fps)

## Outcome

Implemented the fold-2 review decisions in W6's existing qualification harness. The inset foreground now leaves the counter strip clear while crossing a holder/video edge; fractional displaced-holder attribution brackets the two adjacent device phases and proves the historical nooffset-x row at its actual phase; nooffset-y falls back only to explicitly verified integer-phase backing; near clipping rejects non-zero bounds origins and transforms; and the DSK arm maps both decoders to the existing SHA-pinned counter movie at distinct seek offsets, verifies holder-to-decoder identity, rejects swapped bindings, and records every screenshot duration.

The required targeted suite passes: **498 passed, 1 skipped, 0 failed**. Python compilation and `git diff --check` pass. No OBS, Chrome/headless browser, Keynote, or live gate was run.

## Files changed

- `scripts/dissolve_probe.py`: implementation of the CEF placement arms, fixture rewrites, counter resolver, media integrity, displaced attribution, scoring, and screenshot-duration evidence.
- `tests/test_dissolve_probe.py`: offline synthetic/real-fixture regressions folded into the existing single parametrized test function.
- `scripts/managed_obs_qualify.py`: unchanged; the existing §11.6 record/scorer/live harness is reused.
- `tests/test_managed_obs_qualify.py`: unchanged; the existing offline qualification fixtures remain green.

Only the two allowed W6 files above are modified in the worktree. No `.agents` file, fixture byte, Keynote `main.js`, or other stream's file was edited.

## Review findings and fixes

### B1 + M2 — inset foreground, clear strip, real edge crossing

Fixed in `scripts/dissolve_probe.py:226-227`, `:1351-1372`, and the CEF arm wiring at `:425-455`. `_edge_foreground` removes the stock full-frame foreground texture, moves all three retained foreground layers below the top counter-strip rows, and places the first inset across the video/holder left edge by several device pixels. The synthetic painter now understands `edgefg` at `tests/test_dissolve_probe.py:548-563`. The regression at `tests/test_dissolve_probe.py:1029-1065` applies the real slide override and then proves all four affected arms use it, the holder strip still decodes, both interior and edge masks retain usable pixels with zero residual, and an inset crosses the video edge.

### B2 — fractional bracket attribution

Fixed in `scripts/dissolve_probe.py:2272-2335`. The scorer keeps the exact fractional displacement and compares the reference against the per-channel interval formed by the live samples at `floor(d)` and `ceil(d)`, widened by the calibrated `tau`. The regression at `tests/test_dissolve_probe.py:1068-1100` uses `d=5.37`, proves offsets `[5, 6]` PASS, and proves `d-2` and `d+2` both FAIL. The historical run's calibration is **tau = 4**; the fold-1 report's “tau 2” wording was wrong and is superseded here.

### M1 — nooffset-y integer-phase backing attribution

Fixed in `scripts/dissolve_probe.py:2298-2315` and fail-closed scoring at `:3488-3500`. When the displaced overlap is clipped, the scorer may use the visible backing only if its decoder-to-canvas phase is strictly subpixel and the same fractional bracket proves the content; the result is labelled `integer-phase backing`. Missing geometry, mask, LUT, overlap, or a non-subpixel phase remains INCONCLUSIVE. A proven backing attribution forces the intended holder-pixel negative; it is not accepted as a weak negative. `tests/test_dissolve_probe.py:1086-1100` covers the positive phase, and the malformed historical nooffset-y capture still remains INCONCLUSIVE.

### L1 — raw tone wording

`m-tone-raw-cef` is a **diagnostic/report-only observation**, not an enforced identity negative. `cut` and `tone` are in `CEF_PLACEMENT.reported` at `scripts/dissolve_probe.py:2663-2684`; the regression at `tests/test_dissolve_probe.py:1513-1515` proves neither participates in acceptance controls. The row still reuses the same-frame `m-tone-cef-twin` so its diagnostic remains comparable.

### L3 — near-clip preconditions

Fixed in `scripts/dissolve_probe.py:1400-1430`. `_clip_near` raises before rewriting if the parent has a non-zero bounds origin, non-identity affine or sublayer transform, rotation, or scale. The existing child-preserving translation remains intact. `tests/test_dissolve_probe.py:946-961` covers non-zero origin, affine translation, and non-identity sublayer transform; each fails closed with the same explicit error.

### DSK — one pinned counter, two checkable identities

Implemented at `scripts/dissolve_probe.py:228-235`, `:461-466`, `:1432-1442`, and `:1492-1506`.

- Both DSK clip URLs resolve in memory to the already pinned p2-binary counter movie; no fixture bytes or on-disk player source changed.
- The resolver checks SHA-256 `947f8944ba743878133bd0749d3a154c552e0a3cb4482b67ddbe8c23f2bd7203` and restricts aliases to the selected DSK slide.
- The two builds retain distinct identities through seek offsets `0.0 s` and `5.0 s`.
- `media_integrity` at `scripts/dissolve_probe.py:3225-3234` requires each holder strip to match its bound decoder's last pre-detach rVFC frame and requires the two decoder references to be distinct. A holder swap is therefore detected.
- `_shot_record` at `scripts/dissolve_probe.py:4135-4136` stores `durationMs` for each shot; `burst` uses it. The live rerun can therefore show whether the observed DSK screenshots remain near the prior ~190 ms rather than the lower-load ~100 ms.

Offline coverage is at `tests/test_dissolve_probe.py:963-1000` and cases `:1507-1512`: two aliases, one pinned path, offsets `(0.0, 5.0)`, exact digest, independently decoded holder strips, swapped-binding rejection, and per-shot duration.

The original DSK clips are ProRes `yuv422p10le`, and the counter is H.264 `yuv420p`; neither video format has an alpha plane. Thus the replacement does not remove source-video alpha that existed in the original fixtures. It does replace real church-video content/audio, intrinsic dimensions, codec, and PNG entropy with a silent opaque binary counter. The DSK row therefore qualifies binding, frozen-frame/region, geometry, and measured live cost/cadence for the counter content; it does not claim representative real-footage codec/audio/entropy behavior.

## §5 / §11.6 contract mapping

| Frozen contract item | Implementation |
|---|---|
| `placementCalibration` v1, exact recursive serialization, full-digest relative `FileRef`, PNG refs, transaction `$ref`, fail-closed validation | `scripts/dissolve_probe.py:800-1007` |
| Record constructor and live/offline scoring through the same W2 classifier and W3 persistence APIs | `scripts/managed_obs_qualify.py:373-681`, `:698-723`, `:2199-2263`, `:3100-3175` |
| Freshness, process isolation/lifecycle, moving-program null, Program-toggle positive control | `scripts/managed_obs_qualify.py:495-535`, `:1212-1273`, `:1733-1770`, `:2082-2089` |
| Continuous lossless Program recording, interval coverage, skipped-frame/audio checks and controls | `scripts/managed_obs_qualify.py:536-614`, `:861-935`, `:1276-1325`, `:2096-2173` |
| Sampled raw RGBA over transparent Program before/install/capture/cleanup/restore | `scripts/managed_obs_qualify.py:616-635`, `:936-978`, `:2073-2186` |
| CEF arms: holder/reference/mask/geometry/tone/cost, clips and DSK | `scripts/dissolve_probe.py:425-466`, `:2133-2335`, `:2663-2684`, `:3153-3500` |
| Harness-only Chrome classifier, complete W5 tone rows, script-only placement mode | `scripts/dissolve_probe.py:3862-3900`; `scripts/managed_obs_qualify.py:664-671`, `:2110-2116`, `:2240-2264` |
| O1 forged snap/frac rows in existing `m-raw-prod` / `m-preview-prod` arms, no holder binding | existing `FORGERIES` expansion in `scripts/dissolve_probe.py:366-389`; existing offline cases remain green |
| Missing or malformed required evidence | scorer returns INCONCLUSIVE; no expected-failure escape was added |

There is no frozen-schema deviation. The DSK content substitution is the coordinator's binding decision and remains a SHA-pinned, in-memory resolver replacement. Its representativeness limitation is recorded above rather than silently generalized.

## Fresh 25 fps offline rescore

Fresh APFS clone: `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold2-rescore.IMgxUQ`  
Detail: `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold2-rescore.IMgxUQ-detail.json`

Tool-baseline command used the historical `placement-20261013-231739.json`, the q0b decision record, and `baseline` mode. Result: **`VERDICT FAIL invalid None`**.

| Arm | Outcome |
|---|---|
| opaque-off | MATCH |
| off | MATCH |
| noblend | MATCH |
| on2 | MATCH |
| cut-on | MATCH |
| cut-off | MATCH |
| m-paused-cef | MATCH |
| m-off-cef | MATCH |
| m-snap-cef | INCONCLUSIVE |
| m-hold-cef | MATCH |
| m-fg-cef | MATCH |
| m-fg-omit-cef | MATCH |
| m-fg-swap-cef | MATCH |
| m-tone-cef | MATCH |
| m-tone-raw-cef | MATCH |
| m-snap-cef-far-x | MATCH |
| m-snap-cef-far-y | MATCH |
| m-snap-cef-near-x | MATCH |
| m-snap-cef-near-y | INCONCLUSIVE |
| m-snap-cef-nooffset-x | MATCH |
| m-snap-cef-nooffset-y | INCONCLUSIVE |
| m-snap-cef-underlay-omit | MATCH |
| wrongrule-cef | INCONCLUSIVE |
| perfect-shift | MATCH |
| m-snap-cef-dsk | INCONCLUSIVE |
| m-geo-scale | MATCH |
| m-geo-base | MATCH |
| on | MATCH |
| opaque-on | MATCH |

The corrected nooffset-x attribution is PASS at its true phase: `displacementPx=385.9871826171875`, samples `[385, 386]`, `overlapPx=22363`, `worst=0`, `tau=4`; its intended holder-pixel check is FAIL, so the arm now MATCHes. Historical nooffset-y has zero holders and remains INCONCLUSIVE. Historical DSK remains INCONCLUSIVE because it contains four mid frames, undecodable real-video holder strips, and duplicate old references `[79, 79]`; those are precisely the evidence gaps the new live fixture must replace. Historic `m-snap-cef` and `wrongrule-cef` still lack kept edge pixels and cannot be repaired offline.

Gate summary: `model`, `complement`, `no_dip`, `curve`, `monotone`, `handoff`, `foreground`, and `cvc` PASS; `matched` is REPORTED; `frozen_frame`, `frozen_region`, `cost`, `holder_pixels`, `reference`, `mask`, and `geometry` are INCONCLUSIVE.

## Tests and checks

Required targeted command:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

Exact result: **498 passed, 1 skipped, 0 failed in 133.36 s**.

Additional targeted development subset: **31 passed, 0 failed in 8.99 s**.

Checks:

- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py`: PASS.
- `git diff --check`: PASS, no output.
- The three declared external census reds were not run and did not appear.

## Open items for the coordinator

1. Run the live CEF placement qualification. The old capture cannot supply the new edge fixture, nooffset-y holder evidence, distinct DSK counter identities, five DSK mid frames, or per-shot duration evidence.
2. Inspect the live DSK `durationMs`, cadence/cost gate, distinct seek identities, and holder-strip decode. Do not infer real-footage codec/audio/entropy performance from the counter replacement.
3. Run the managed OBS qualification to populate §11.6 freshness/isolation/lifecycle, persistence, continuous recording/RGBA, Chrome classifier, and W5 tone evidence. Missing live evidence must remain INCONCLUSIVE.
4. Coordinator should commit only `scripts/dissolve_probe.py` and `tests/test_dissolve_probe.py` from W6.

## Skill used

The repo's `obed-edom` skill supplied the qualification terminology and validation workflow; it did not cause edits outside W6's allowed files.
