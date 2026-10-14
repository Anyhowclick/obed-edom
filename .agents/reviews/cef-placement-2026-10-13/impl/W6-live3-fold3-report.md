# W6 live3 fold 3 report

Date: 2026-10-14  
Branch/worktree: `claude/cef-obs-placement` / `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Plan: `keynote_live_cef_placement.plan.md` rev 3.3, §5 and frozen contract §11.6  
Review: `review-live3-r3.md`  
Authoritative historical run rescored: `placement-20261013-231739.json` (25 fps)

## Outcome

Fold 3 is implemented in the two already-modified W6 files. BL1's manufactured nooffset-y failure path is gone: displaced-content attribution can only make the pixel result INCONCLUSIVE, never overwrite a real PASS/FAIL. A harness-only, in-memory `nooffsety` slide override puts the real p2-binary decoder at y=125 CSS px while retaining the corrected near clip. On the real export geometry the clip starts 107.418584 px into the 267.6214599609375 px content, the top counter strip is outside the clip, and `masksToBounds` remains true. The offline arm proof now reads: correct offset-included holder `holder_pixels=PASS`, attribution `PASS`, arm `MISMATCH`; displaced negative holder `holder_pixels=FAIL`, arm `MATCH`.

BL2 is also implemented. The DSK document no longer writes inert `movie.startTime`; its second selected asset's in-memory native/web URL is `...mov#t=5`, while the served request path and SHA-pinned bytes remain unchanged. Resolver checks pin the actual DSK/p2 player path from `assets[*].url.native` through `setAttribute("src", this.src)`. Every live DSK record now stores both decoders' first-rVFC media times, and the scorer requires an absolute delta of 5 s within one 30 fps frame; missing, inconsistent, or same-start evidence makes the arm INCONCLUSIVE. Non-alias DSK movies use the existing `h264_copy` route.

The required targeted suite is green: **500 passed, 1 skipped, 0 failed**. Python compilation and `git diff --check` pass. No OBS, Chrome/headless browser, Keynote, or live gate was run.

## Files changed

- `scripts/dissolve_probe.py`: existing W6 qualification implementation plus the fold-3 nooffset-y fixture/scoring correction, DSK media-fragment rewrite, non-alias H.264 routing, first-rVFC timing record, and fail-closed timing scorer.
- `tests/test_dissolve_probe.py`: existing single parametrized scorer test extended with real p2-binary geometry, correct-vs-defective holder rows, actual DSK document URL/player-anchor checks, H.264-route checks, and first-rVFC missing/inert controls.
- `scripts/managed_obs_qualify.py`: unchanged in this fold; the existing §11.6 live transaction, record, persistence, recording/RGBA, Chrome/W5, and offline-rescore implementation remains in use.
- `tests/test_managed_obs_qualify.py`: unchanged in this fold.

No `.agents` file, fixture byte, Keynote `main.js`, product source file, or other stream's file was edited. There are still only the existing two modified W6 files in the worktree.

## Review findings and fixes

### BL1 — nooffset-y must fail only on pixels

- Removed the `integer-phase backing` branch from `score_displaced_holder`; empty displaced overlap now returns INCONCLUSIVE (`scripts/dissolve_probe.py:2304-2363`).
- Removed the scorer-side forced `holder_pixels=FAIL`; a PASS attribution now leaves the pixel scorer's own verdict untouched, while a non-PASS attribution still makes it INCONCLUSIVE (`scripts/dissolve_probe.py:3535-3548`).
- Added `NOOFFSET_Y_DISPLACEMENT=125.0`, scoped `nooffsety` only to `m-snap-cef-nooffset-y` and its twin, and implemented the in-memory parent translation after the corrected near-y clip (`scripts/dissolve_probe.py:241`, `:462-468`, `:1459-1467`). No on-disk slide/player file is changed.
- Real p2-binary geometry proof and the correct-holder/negative-holder outcome rows are at `tests/test_dissolve_probe.py:969-996` and `:1569-1575`. The direct attribution table also proves the removed backing case is INCONCLUSIVE (`tests/test_dissolve_probe.py:1135-1157`).

### BL2 — effective DSK 5 s start and fail-closed proof

- `_dsk_counter` now rewrites the selected second asset URL to `#t=5` instead of changing player-ignored `startTime`; both movie `startTime` values remain 0 in the resolved document (`scripts/dissolve_probe.py:1441-1456`).
- The actual DSK player is pinned to the observed path: `getMovieUrl` reads `url.native`, and `initVideo` assigns `this.src` to the video element. Count checks are at `scripts/dissolve_probe.py:237-240` and `:1565-1568`.
- `record_dsk_counter_timing` writes the two first-rVFC media times and one-frame tolerance into every DSK live record (`scripts/dissolve_probe.py:3177-3187`, called at `:4310`). `media_integrity` validates record consistency and the approximately 5 s delta, so missing/same-start evidence is an integrity problem and therefore INCONCLUSIVE (`scripts/dissolve_probe.py:3260-3288`).
- The offline fixture obtains its delta from the rewritten document URL rather than a hard-coded `media + 5.0`, proves the selected media fragment and unchanged inert start fields, and covers missing/inert timing plus swapped holders (`tests/test_dissolve_probe.py:999-1063`, `:1576-1582`).

### M1 — non-alias DSK movies

`movies="dsk-counter"` now sends every non-selected movie through the same `h264_copy` path as `cef-skip-dsk`; only the two target-slide aliases bind to the pinned counter (`scripts/dissolve_probe.py:1515-1535`). The resolver test proves non-target movies hit that path while the two selected target paths do not (`tests/test_dissolve_probe.py:999-1020`).

### L1 — cost representativeness

The DSK cost gate measures take time for the substituted 1920×540, silent, opaque H.264 binary counter. The original selected DSK clips are 1922×1080 and 1282×1080, and other deck movies may have different codec/audio/entropy. This makes a cost PASS easier and qualifies only the counter-backed harness path; it is not evidence that native DSK footage has equivalent decode, audio, entropy, or resolution cost. The live report must retain this limitation.

### L2 — underlay-omit inheritance

`m-snap-cef-underlay-omit` is derived from `m-snap-cef`, so it inherits the `edgefg` override before changing only splice/capture/holder expectations (`scripts/dissolve_probe.py:475-477`). Its alpha-refusal control therefore uses the same strip-clear, edge-crossing foreground layout as the base CEF row.

### L3 — intended diff

The worktree still contains only the pre-existing W6 modifications to `scripts/dissolve_probe.py` and `tests/test_dissolve_probe.py`. Fold 3 adds no new stream file and does not modify the managed-OBS files.

## §5 / §11.6 contract mapping

| Contract item | Implementation |
|---|---|
| `placementCalibration` schema v1, strict recursive serialization, full-digest relative `FileRef`, PNG replacement refs, transaction evidence `$ref`, no `default=str` | `scripts/dissolve_probe.py:809-1044`; record construction in `scripts/managed_obs_qualify.py:698-723` |
| Same product classifier and W3 persistence APIs in live and offline scoring | `scripts/managed_obs_qualify.py:373-681`, `:3100-3175` |
| Freshness, isolation/lifecycle, moving-program null and Program-toggle positive control | `scripts/managed_obs_qualify.py:409-535`, `:1733-1770`, `:2082-2089` |
| Continuous lossless Program recording, transaction bracketing, frame/audio checks and controls | `scripts/managed_obs_qualify.py:536-614`, `:861-935`, `:2096-2173` |
| Sampled raw RGBA over transparent Program at required phases | `scripts/managed_obs_qualify.py:616-635`, `:936-978`, `:2073-2186` |
| CEF clip/holder/reference/mask/foreground/tone/cost arms | `scripts/dissolve_probe.py:425-477`, `:2133-2363`, `:2663-2704`, `:3153-3560` |
| nooffset attribution gates only; correct holder cannot be manufactured into FAIL | `scripts/dissolve_probe.py:2304-2363`, `:3535-3548`; tests `tests/test_dissolve_probe.py:969-996`, `:1569-1575` |
| DSK two-holder binding, SHA-pinned alias, real 5 s decoder start, first-rVFC timing proof, non-alias H.264 route | `scripts/dissolve_probe.py:228-241`, `:470-474`, `:1441-1456`, `:1515-1535`, `:1565-1568`, `:3177-3187`, `:3235-3288`, `:4310` |
| Harness-only Chrome classifier and W5 tone rows using script-only `placement_mode` | `scripts/dissolve_probe.py:3862-4053`; `scripts/managed_obs_qualify.py:409-472`, `:664-681`, `:2235-2271` |
| O1 forged snap/frac assignment/getter rows in existing `m-raw-prod` / `m-preview-prod`, with no holder binding | `scripts/dissolve_probe.py:379-390`, `:3020`; existing offline rows remain green |
| Missing/malformed evidence fails closed | schema/scorer paths above; DSK timing specifically `scripts/dissolve_probe.py:3275-3288` |

There is **no deviation from §11**. The fold-3 DSK timing evidence is an additive harness record outside the frozen `placementCalibration` object; it neither renames nor relaxes that schema. The selected movie bytes/path remain SHA-pinned and unchanged because the media fragment is a document URL fragment, not part of the HTTP request.

## Fresh 25 fps offline rescore

Fresh APFS clone: `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold3-rescore.WwkhyE`  
Detail: `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold3-rescore.WwkhyE-detail.json`

Command used the historical 25 fps record, q0b decision record, and tool `baseline` mode. Result: **`VERDICT FAIL invalid None`**.

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

Gate summary: `model`, `complement`, `no_dip`, `curve`, `monotone`, `handoff`, `foreground`, and `cvc` PASS; `matched` is REPORTED; `frozen_frame`, `frozen_region`, `cost`, `holder_pixels`, `reference`, `mask`, and `geometry` are INCONCLUSIVE.

The old recording cannot exercise the new nooffset-y slide override: near-y/nooffset-y still have zero holders and no paused decoder. Its old DSK row also has only four mid frames, undecodable real-video holder strips, duplicate old references `[79,79]`, and no `dskCounterTiming`; the new fail-closed scorer correctly adds `DSK first-rVFC media-time record missing or inconsistent`. Those historic gaps cannot be repaired offline and require a live rerun.

## Tests and checks

Required final command:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

Final result: **500 passed, 1 skipped, 0 failed in 101.47 s**.

Focused final checks:

- `... pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k 'nooffset or DSK'`: **6 passed, 0 failed in 3.62 s**.
- `... pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k 'lbfrac and engagement'`: **9 passed, 0 failed in 6.48 s**.
- `env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m py_compile scripts/dissolve_probe.py scripts/managed_obs_qualify.py tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py`: PASS.
- `git diff --check`: PASS, no output.

Development failures were diagnosed before the final run: the first focused pass was 2 passed/4 failed, the second was 5 passed/1 failed, and the first full pass was 491 passed/1 skipped/9 failed. The first two exposed player-anchor cardinality/test-route mistakes; the nine full failures were all a synthetic fixture's double application of letterbox y after the nooffset-y extension. The corrected final commands above are green. The three declared external census reds were not run and did not appear.

No new test function was added; all fold-3 coverage is table-driven through the existing parametrized scorer test.

## Open items for the coordinator

1. Run a new live CEF placement qualification on the final bytes. It must produce a real nooffset-y holder/pixel FAIL under the y=125 override and the correct-holder positive proof must remain a MISMATCH.
2. Confirm the DSK live record contains two first-rVFC media times separated by 5 s ± one 30 fps frame, distinct holder frame identities, at least five mid frames, and accepted screenshot durations. Any missing/tied timing remains INCONCLUSIVE.
3. Treat DSK cost as counter-path evidence only; do not generalize it to the original 1922×1080/1282×1080 footage, codec/audio/entropy, or decoder load without a representative live cost leg.
4. Run the full managed OBS placement qualification to populate final §11.6 freshness/isolation/lifecycle, persistence, continuous recording/RGBA, Chrome classifier, and W5 tone evidence. Missing live evidence stays INCONCLUSIVE.
5. The configured DeckLink preview-output behavior remains the §11 field-test item; no response was guessed or allowlisted.
6. Coordinator should commit only `scripts/dissolve_probe.py` and `tests/test_dissolve_probe.py` from W6.

## Skill used

The repo's `obed-edom` skill supplied the managed-OBS/Keynote qualification vocabulary and constraints. It did not cause edits outside W6's allowed files.
