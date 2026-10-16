# C1 code review r1 (Opus 5.5 high; three lenses: sampler, decoder/contract, tests; each finding self-refuted, blockers and majors spot-checked by the coordinator)

Target `claude/stage-b-c1` `b77ae598` vs `1cd8efd5`. Implementer: Codex GPT-5.6 Sol high. Confirmed 19 (2 blocker, 6 major,
7 medium, 4 minor). All folded per the review stop rule (r1 folds every severity). Repro scripts:
`/private/tmp/claude-501/c1-review/` (sampler, decoder) and `/private/tmp/claude-501/c1-review-tests/` (mutants).

## Sampler (`scripts/mm_feed_instrument.py`)

**S1 major · report() freezes live state; layered product wrappers stay live and then throw.** Product scripts wrap
`getContext` / `texImage2D` / `drawArrays` over ours (`live_mm_feed_js.py:548,592,635`, `live_gl_replay_js.py:1287`), so
report's identity-checked restores skip them, and no owned wrapper checks `stopped`. `deepFreeze(result)` freezes
`S.contexts/errors/browserFrames/uploads/departures` in place → the next straggler push throws a TypeError into the
product's call (repro `layered.js`: `gl.clear` and `getContext` THREW). Fix: every owned wrapper (gl wrappers,
`ownedGetContext`, `once`, pause/play, claim/stand) passes straight through when `stopped`; freeze a detached copy.

**S2 major · GL patch footprint misregistered and differently filtered from the source sample.** Source reads pixel
`round(uv*(w-1))+dx` (centre `(i+.5)/w`); `vectorFromGl` projects `uv+dx/w` (0.5 cell off at uv .5, up to 0.7 cell in y at
1920×540) and box-averages `(2r+1)²` with r = ceil(half cell). Before C1 both sides were centred on uv. Numpy model: clean
reads failing `dVideo ≤ dPoster/2` rise from 0–13 % to 29–98 %. Fix: project the exact source sample centres and use the same
effective kernel on both sides; separation then re-proven on captures (handover step 3).

**S3 medium · one presented frame sampled once per entry.** In a chain (carried decoder shared by A moveLive and B at
`atScene-1`) the rVFC `forEach` draws/reads twice per present (repro `chain.js`: 2/2). Fix: one lazy `sample()` per rVFC
callback reused by every entry.

**S4 minor · `bestGeneric` lost the next-best-uv fallback when the best uv's GL read fails.** Fix: try candidates in dSep order
until one GL read succeeds.

**S5 minor · fed draw with no decoder/leaf size records a null reason.** Fix: call `sample()` unconditionally (it returns
`reason:'source'`).

## Decoder and contract

**D1 major · JS counter acceptance policy changed without positive/red proof; the F report says no thresholds changed.**
Old JS: spread ≥ 80, midpoint, no band. New: marker contrast ≥ 128 plus a 25 % ambiguity band. GL finals in crossfades mix
two strips (a differing bit at .75W+.25K sits on the band edge): sim decode rate 1.000 → 0.077. No GL `feedRead.counter`
decoded in any of the 9 stored Q7 feed artifacts, old instrument included. Resolution (plan §3 asks for one shared
decoder): keep the shared rules, disclose the change in the fold report and commit, and make gate 2 include D7 crossfade /
from-only captures plus at least one positive GL counter decode. A collapse to `ambiguous`/`marker` goes to the owner as a
measured blocker; no silent loosening.

**D2 medium · OBS recording decode not byte-for-byte: the band moved from mean difference to min/max contrast.** Old
`read_strip`: `0.25*(mean(white)-mean(black))`; new `0.25*(min(white)-max(black))` (strictly narrower with asymmetric
markers; fuzz σ=25: 10.6 % ambiguous → ok). Fix: band on `white-black` means in both decoders (the qualified OBS
semantics); `contrast` stays only for the marker gate. Pin with an asymmetric-marker band-edge vector.

**D3 medium · alpha read without a same-task reference emits `referenceLevels:[]`, `referenceReason:null`; the contract
rejects it and nulls every feed verdict.** Before C1 only that entry went None. Fix: `referenceReason` falls back to
`'source'`; cover it in the fake-GL test.

**D4 minor · contract strictness keys on the artifact's own `counterLayout`.** A C1 report without it validates as legacy.
Fix: strict when `sampling` is present or `config.counterLayout` is present; `sampling` requires `counterLayout`.

**D5 minor · JS/Python decoders diverge on non-canonical layouts; the conformance table has no boundary vectors.**
`parity:'odd'`+ambiguous (py `ambiguous`, js `layout`); `end:[]` (py ValueError, js decodes); `dataBits:12.0` (py `layout`,
js decodes); layout None (py canonical, js `layout`). Fix: one layout gate in the same order in both, rejecting empty
`start`/`end`; add exact cut, contrast == minContrast, band edge, asymmetric markers, parity-odd rows, and 0 / 4095.

**D6 minor · contract never binds counter/reason to levels.** Fix: with full-length levels, require
`decode_counter(levels, layout) == (counter, reason)` for feed, reference and `sampling.latest*`; otherwise a non-null
reason requires `counter is None`.

## Tests

**T1 blocker · ported verdicts are tautological; the fake GL cannot paint a broken feed.** 16 of the deleted test's 20
verdicts are scored on hand-built or deep-copied dicts (`tests/test_mm_feed_instrument.py:150-205`); `drawArrays(){}` is a
no-op and `readPixels` returns the live decoder, so final ≡ reference. Survivors (old test killed each): `final_is_reference`,
`holdMatch_worst`, `label_after_equals_before`, `artwork_ignored`, `no_videoFrame_media`. Fix (inside the existing
lifecycle test): restore the painting model (upload snapshot per texture, draw paints the bound snapshot at the matrix rect,
readPixels reads that buffer), re-add broken/hold/killed/chain/label scenes, one final `report()`, derive every verdict from
`feed.verdict_records`, delete 150–205.

**T2 blocker · pre-draw geometry producer assertions dropped.** Old A1–A7 (`geometryFirst/AfterDraw/Sticky`, framed and
unframed `firstDrawAt`, thrown draw) have no JS-producer replacement; mutants `firstDrawAt_before_draw`,
`unframed_firstDrawAt_before`, `srcErr_min`, `srcErr_not_sticky` survive. Fix: port the geo-1/geo-2 scenes and read them from
the final report.

**T3 major · report-stream and control assertions dropped** (size/uploadedSize, claims, departures, `t<createdAt`,
generation/visit, standDowns, killedOnce, mediaDropped, tamper, framesFed). Fix: bootstrap with `killHoldUpload`, `tamper`,
a fake `once`; assert them on the final report.

**T4 major · probe `counterLayout` wiring unpinned.** Dropping it from both probe payloads survives the probe and feed tests.
Fix: assert `json.dumps(binary_counter_movie.layout())` is in `pre_navigation_scripts[0]` in
`test_feed_instrument_is_registered_before_navigation` (with D4 the contract then also fails closed).

**T5 medium · dimension-aware coverage nominal.** Everything is 1920×540 = `sourceSize`. Fix: alpha video 160×90 into
[100,100], counter video 960×270, `Video.pixel` scaled; assert `uploadedSize`.

**T6 medium · post-report assertions weak; the fake cancels every rVFC.** Fix: cancel by id; invoke pre-report queued
callbacks after report and assert zero draws/reads; `removed == 4`; restore checks for `once`, `decoderFor` and the
`__OBED_CONTINUITY__` descriptor; layered-wrapper case (S1); `Object.isFrozen` on a nested row.

**T7 medium · new contract rejection clauses untested** (10 mutants survive). Fix: one row per clause in the existing
`(mutate, clause)` table at `tests/test_live_evidence_contract.py:481`, via a strict-setup helper.

**T8 minor · redundant tests.** Delete `test_layout_exposes_the_machine_readable_counter_format` and the
`referenceCapacity == 18` literal; merge the Python and JS conformance tests into one `js == py == expected` table; derive
`draws == 57` from report counts; `restored.draw2` checks `gl2.drawArrays`; add the `holdCounterMatch` worst-candidate
case (existing gap) via the T1 hold scene.

## Refuted (summary)
`willReadFrequently` false everywhere; one draw + one read per `sample()`; ring open/refresh/18/holdMatch unchanged;
hand-back three frames; label-before / final-after separate; v2 replay unchanged on all 18 stored producer reports;
numeric `counter` preserved for consumers; managed OBS reuses the pre-navigation scripts; acceptance mutants (second
draw/read, wrf true, ring 17/19) killed.

## Open for the plan
"Rollover" in plan §3 coverage: ring rollover is pinned; a counter loop 4095 → 0 against `abs(counter-referenceCounter) <= 1`
is not. Clarify at the C1 gate record.
