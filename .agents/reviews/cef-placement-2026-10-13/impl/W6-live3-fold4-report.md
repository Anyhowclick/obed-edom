# W6 live3 fold 4 report

Date: 2026-10-14  
Branch/worktree: `claude/cef-obs-placement` / `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f`  
Plan: `keynote_live_cef_placement.plan.md` rev 3.3, §5 and frozen contract §11.6  
Review: `review-live3-r4.md`  
Historical run rescored: `placement-20261013-231739.json` (25 fps)

## Outcome

Fold 4 implements BL-A and M-A only. DSK first-rVFC evidence now contains only the outgoing decoders bound to the two holders, and the scorer compares it to current holder/decoder pairs by decoder id rather than list position. The historical `m-snap-cef-dsk/record.json`, read through an APFS clone, produces exactly ids 9 and 10 from its 13-decoder dump.

The `#t=5` proof is directed: that exact decoder source must begin 5 seconds after the base clip within 0.25 seconds, after skipping one leading mediaTime-0 preroll. The two holder strips must differ by `5 s × counter fps ± 3` frames. The fps comes from the SHA-pinned movie through the existing `_ffprobe` helper; an unavailable/mismatched movie fails closed.

Required targeted tests are green: **500 passed, 1 skipped, 0 failed**. No OBS, Chrome/headless browser, Keynote, full suite or gate runner was run.

## Files changed

- `scripts/dissolve_probe.py`: existing W6 implementation plus bound-decoder timing selection, pinned-movie fps probing, directed `#t=5` timing, preroll handling and ±3-frame holder-strip validation.
- `tests/test_dissolve_probe.py`: existing parametrized table extended for extra prior-slide decoders, id-order-independent comparison, preroll, directed source/time controls, fps derivation and ±3/+4 frame boundaries.
- `scripts/managed_obs_qualify.py` and `tests/test_managed_obs_qualify.py`: unchanged in this fold.

No `.agents` file, fixture, Keynote `main.js`, product source file or other stream file was edited. The untracked `.agents/reviews/**` files pre-existed and were untouched.

## Review findings

### BL-A — outgoing holder-bound timing only

- `record_dsk_counter_timing` filters to live `region` plus non-null `detach`, binds candidates to holders, and records only `{holderIndex,id,firstMediaTimeS}` for those pairs (`scripts/dissolve_probe.py:3211-3223`).
- `media_integrity` reconstructs the paired decoder-id map and compares timing rows by id, making record row order irrelevant (`scripts/dissolve_probe.py:3317-3327`).
- The existing table row now includes eleven extra prior-slide decoders with no current region, reverses timing-row order, and still records only synthetic ids `[0,1]` (`tests/test_dissolve_probe.py:1024-1063`, `:1621-1622`). No test function was added.
- Historic APFS-clone verification used the 25 fps `m-snap-cef-dsk/record.json`. Source and clone SHA-256 both equal `ebde8a9926095ef7d689d5fbe2a6c05de96fcacf60f34f799ee2538bd3368f82`. Result:

```json
{"counterFps":30.0,"decoders":[{"firstMediaTimeS":0.033333,"holderIndex":0,"id":9},{"firstMediaTimeS":0.033333,"holderIndex":1,"id":10}],"expectedDeltaS":5.0,"toleranceS":0.25}
```

### M-A — directed clip time and holder-frame spacing

- `dsk_counter_fps` verifies `DSK_COUNTER_SHA256` and calls `obed_edom.dsk_movie_export._ffprobe`; unavailable evidence becomes an integrity problem (`scripts/dissolve_probe.py:3182-3189`). The resolver records the derived fps (`scripts/dissolve_probe.py:1523-1533`).
- `_dsk_first_media_time` skips one leading zero preroll. `_dsk_decoder_offset` accepts only the exact base and `#t=5` filenames (`scripts/dissolve_probe.py:3192-3208`).
- The scorer enforces `first(#t=5) - first(base) = 5 ± 0.25 s`, not `abs(delta)` (`scripts/dissolve_probe.py:3330-3338`).
- Paired holder strips must satisfy `index(#t=5) - index(base) = 5 × probed_fps ± 3`; missing indices or +4 is INCONCLUSIVE (`scripts/dissolve_probe.py:3339-3347`).
- The table proves preroll skip, reversed row order, reversed-source rejection, inclusive +3, rejected +4, and swapped-holder identity (`tests/test_dissolve_probe.py:1030-1103`, `:1621-1622`).

## §5 / §11.6 mapping

| Contract item | Implementation |
|---|---|
| Strict schema-v1 serialization, `FileRef`, PNG refs, transaction `$ref` | `scripts/dissolve_probe.py:810-1045`; `scripts/managed_obs_qualify.py:698-723` |
| Same classifier/persistence APIs live and offline | `scripts/managed_obs_qualify.py:409-681`, `:3100-3175` |
| Freshness, isolation/lifecycle, moving-program null/positive controls | `scripts/managed_obs_qualify.py:409-535`, `:1733-1770`, `:2082-2089` |
| Continuous lossless recording and frame/audio controls | `scripts/managed_obs_qualify.py:536-614`, `:861-935`, `:1276-1322`, `:2096-2173` |
| Raw RGBA sampling over transparent Program | `scripts/managed_obs_qualify.py:616-635`, `:936-978`, `:2073-2186` |
| CEF clip/holder/reference/mask/foreground/tone/cost arms | `scripts/dissolve_probe.py:425-492`, `:2158-2387`, `:2687-2728`, `:3226-3598` |
| DSK pin, `#t=5`, bound timing, directed time/frame proof | `scripts/dissolve_probe.py:228-240`, `:1444-1459`, `:1520-1539`, `:3182-3347`; live call `:4368-4369` |
| Harness-only Chrome/W5 using script-only `placement_mode` | `scripts/dissolve_probe.py:3900-4091`, `:4588-4613`; `scripts/managed_obs_qualify.py:409-472`, `:664-681`, `:2235-2271` |
| O1 forged raw/preview rows, no holder | `scripts/dissolve_probe.py:380-390`, `:3025` |
| Missing/malformed evidence is INCONCLUSIVE | shared scorers above; DSK paths `scripts/dissolve_probe.py:3266-3268`, `:3317-3347` |

There is **no §11 deviation**. `dskCounterTiming` is additive harness evidence outside frozen `placementCalibration`. All missing/wrong evidence remains INCONCLUSIVE and cannot satisfy an expected FAIL.

## Fresh 25 fps offline rescore

APFS clone (`cp -cR`):
`/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold4-rescore.sEhrYu`

Detail:
`/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad/w6/live3-fold4-rescore.sEhrYu-detail.json`

Baseline-mode result: **`VERDICT FAIL invalid None`**.

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

Gate summary: `model`, `complement`, `no_dip`, `curve`, `monotone`, `handoff`, `foreground`, `cvc` PASS; `matched` REPORTED; `frozen_frame`, `frozen_region`, `cost`, `holder_pixels`, `reference`, `mask`, `geometry` INCONCLUSIVE.

The old DSK row correctly remains INCONCLUSIVE: it predates `dskCounterTiming`, lacks the instrumented `#t=5` source fragment, has tied decoder references, old non-counter holder pixels and only four mid frames. The clone check proves BL-A selection only; it does not manufacture M-A live evidence.

## Tests

Focused:

```text
env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py -q -n 2 -p no:cacheprovider -k dsk
```

**2 passed, 0 failed in 3.50 s.**

Required final command:

```text
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f && env -u PYTHONDONTWRITEBYTECODE .venv/bin/python -m pytest tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py -q -n 2 -p no:cacheprovider
```

**500 passed, 1 skipped, 0 failed in 103.08 s.**

Additional checks:

- `py_compile` on all four W6 files: PASS.
- `git diff --check`: PASS, no output.
- Historic clone selection: PASS, ids 9/10 only and identical SHA-256.
- Declared external census reds: not run; none appeared.

## Open items

1. Run a new live CEF qualification on final bytes. DSK must record only the two bound ids, exact base/`#t=5` sources, directed first-media delta within 0.25 s, and strips separated by `5 × probed fps ± 3`; missing evidence stays INCONCLUSIVE.
2. Do not promote the historical DSK row: it cannot establish M-A and still has four mid frames/non-counter holders.
3. Per instruction, r4 lows were not folded: the synthetic correct-holder row is not live qualification; anchor counts establish bytes, not full call-path execution; rVFC still trims at 900 rows.
4. Retain fold-3's cost limitation: the counter-backed DSK leg does not qualify original clip resolution, codec/audio, entropy or decoder load.
5. Existing non-DSK INCONCLUSIVE arms still need final live qualification; no historical evidence was rewritten.
6. Configured DeckLink preview-output behavior remains the §11 field-test item; no response was guessed.
7. Coordinator should commit only `scripts/dissolve_probe.py` and `tests/test_dissolve_probe.py` from W6.

## Skill used

The repo's `obed-edom` skill supplied the managed-OBS/Keynote qualification constraints and caused no edits outside W6's allowed files.
