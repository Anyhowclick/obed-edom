# Alpha b6to7 / b7to8 hand-back placement — diagnosis (2026-10-15)

Diagnosis only. No product code changed. Branch `claude/friendly-stonebraker-16d950`, fast-forwarded to `claude/stage-b-arch`
(`ed8e24e2`). Core `live_continuity_js.py` is byte-identical to `16f6c9fa` (core sha `302c218d…`).
Results are in `output/evidence/stage-b-2026-10-13/alpha-placement/`: `ab-summary.txt`, `*.verdicts.json`, `*.placement.txt`,
`stacks/`, and `repro/` (the scratch wrapper and its DOM recorder).

## Summary

**Root cause.** Keynote's `renderMovie` build draws two canvases at each destination movie rect:
- `layers[0]`: the poster, inside a `visibility:hidden` layer.
- `layers[1]`: an opaque frame canvas in a sibling layer that paints above it. Its size differs by a sub-pixel.

For a short moment around the hand-back, the movie object's own texture layer (`layerNNN-isPlaying`) also sits at the
rect.

`findMovieCanvas` (`src/obed_edom/live_continuity_js.py:1675-1712`) chooses the anchor by geometric distance alone. That
causes both symptoms:

1. **`#body` on the second hand-back frame.** `carry()` releases the interim slot and remounts synchronously
   (`:2507`, `:2521-2536` → `scheduleRemount` `:1154` → `tryRemount` `:1945`). At that instant the `-isPlaying` canvas
   and the hidden poster are both at distance 0. That is a tie, so the core notes `remount-canvas-ambiguous` (`:1706`)
   and falls through to the `#body` append (`:2008-2047`, `remount-done`). The decoder then paints above every
   artwork and label for about 50 ms, until the +50 ms retry (`:1157`).
2. **`artworkAbove` false, and a static frame over the video for the rest of the slide.** From the +50 ms retry on, the
   hidden poster (exact size) beats the visible frame canvas (sub-pixel off). The decoder is inserted after the poster,
   inside the hidden layer, so the opaque frame canvas in the sibling layer covers it.
   - Pixel read at the movie centre: alpha 255, a static frame.
   - Slide 7 (b5to6) only works by luck: there the visible frame canvas is the closer one (823 vs 824 px).
   - The instrument's single `settledArtwork` read lands in the `#body` window, so it reports `artworkAbove` false. In
     the A/B, removing the `#body` frame turns it true.

**Pre-existing on 51ead0a8.** Same code paths. The `alpha-feed-HEAD` headless run used core `00b9a823`, which is exactly
the 51ead0a8 core. It shows the same 8 `remount-canvas-ambiguous` → `remount-done` events and the same `artworkAbove`
false reads.

**Proposed minimal fix** (core only, about 6 lines in `findMovieCanvas`; A/B-proven in scratch, see below):
1. Drop candidates under an `[id$="-isPlaying"]` layer (keep them only if nothing else matches).
2. Then prefer candidates whose computed `visibility` is not `hidden` (keep all only if none are visible).
3. Then apply the existing min-distance and tie logic.

## Pinning the moves by content

Plan derived offline (`repro/plan.py`, plan sha `c9e54655…`, the same as the owner run). Owner slide N is player N−1 and
scenes run 2 per slide.

| Move | atScene | Movie (asset) | src → dst instance | src rect → dst rect (authored px) | Feed |
|---|---|---|---|---|---|
| b5to6 | 10 | wa0125 | 2FE5195A → F3703784 | 1153,795,485,273 → 548,603,823,463 | draw 3/5 |
| b6to7 | 12 | wa0125 | F3703784 → A94D1E57 | 548,603,823,463 → 216,664,714,402 | draw 4/9 |
| b7to8 | 14 | wa0121 | 0F9F4FEF → A0064856 | 930,664,714,402 → 764,739,582,327 | draw 2/12 |
| b7to8 | 14 | wa0125 | A94D1E57 → DF992E47 | 216,664,714,402 → 181,739,582,327 | draw 4/12 |

`renderMovie` layers on each destination slide (`events[0].effects[*].effects[0].baseLayer.layers`), as
(texture, hidden, width):

| Destination | Instance | `layers[0]` hidden poster | `layers[1]` visible frame |
|---|---|---|---|
| slide 7 (02FFC05C) | F3703784 | 0FB20670, hidden, 824 | C01CA56A, visible, **823.0** |
| slide 8 (DAC21D01) | A94D1E57 | CF6BC171, hidden, **714** | C01CA56A, visible, 714.25 |
| slide 8 (DAC21D01) | 0F9F4FEF | 0634CBF8, hidden, 715 | B75EFA5A, visible, 714.25 |
| slide 9 (D4A1DF22) | DF992E47 | F86E3188, hidden, **582** | C01CA56A, visible, 581.85 |
| slide 9 (D4A1DF22) | A0064856 | 45AAEB5D, hidden, **582** | B75EFA5A, visible, 581.85 |

Bold marks the canvas that is nearest to the authored rect, which is the one the current code picks once the tie clears.

## Observed facts per move

### Owner run (managed OBS, `q7-attempt3/Alpha/runs/feed-20261015-150437.json`, core `4c917be4` = 03a35b28)

`handbacks[].frames[].dom` per hand-back frame:

| Move | Frame 1 | Frame 2 | Frame 3 |
|---|---|---|---|
| b5to6 | 1557: in stage, after canvas | 1558: same | 1559: same |
| b6to7 | 1664: interim, after canvas | 1666: **afterCanvas False** (1665 not sampled) | 1667: **afterCanvas False** |
| b7to8 wa0121 | 1752: interim, after canvas | 1754: **onBody True**, inStage False | 1755: **afterCanvas False** |
| b7to8 wa0125 | 1752: interim, after canvas | 1754: **onBody True**, inStage False | 1755: **afterCanvas False** |

`artwork` reads: b5to6 true ×2; b6to7 false ×3; b7to8 wa0121 false ×5; b7to8 wa0125 false ×3.

### Headless, current core (`r2`; `alpha-diag` adds only a note field, same events)

Chrome 155, feed on, pre-move `capture()` disabled (observer-effect control), DOM recorder on every rAF.

**b6to7** (`r2.placement.txt`):
- 36975 feed linger ends (`take`).
- 36976.6 `interim-placed`: root `layer208`, anchor `layer218` (the movie slot). The decoder sits at root level after
  the slot and below `layer221…233` (artwork).
- 36983.2 `bridge-3to4` → `interim-release` → `pin-rehome`.
- 36983.2 `remount-canvas-ambiguous`. Candidates: `309718` in `layer238-isPlaying` (visible, distance 0) and `CF6BC1` in
  `layer243` (hidden, distance 0).
- 36983.4 `remount-done`.
- 36993.6 the decoder is on `body#body`, last child, above `#stageArea` (all artwork and labels).
- 37042.9 the decoder is in `layer243`, after `CF6BC1` (the hidden poster).
- It stays there through scene 13. `layer244`, which holds the visible `C01CA56A` frame canvas (alpha 255, rgb 4,5,0),
  paints above it.
- Hit stack at the movie centre, slide 8 +1.2 s: `… layer221 > canvas#C01CA56A > layer244 > video[4] > layer242-…`.
  The frame canvas is above the decoder.
- The player's own (uncarried) wa0121 element on the same slide sits *before* `B75EFA5A`, and the player then removes
  that canvas. The carried decoder never gets that removal.

**b7to8 (both movies):**
- 41755 linger ends.
- 41756 interim places both (anchors `layer304` and `layer310`).
- 41768.7 / 41769.8 hand-back. Each is `remount-canvas-ambiguous` (`C6571B` in `layer339-isPlaying` vs `F86E31` hidden,
  and `F89B74` in `layer342-isPlaying` vs `45AAEB` hidden) → `remount-done`.
- 41778 the wa0125 decoder is on `body#body`.
- 41825.9 both decoders are in `layer344` / `layer347`, after the hidden posters, under the visible frame canvases in
  `layer345` / `layer348` (alpha 255; rgb 5,6,1 for wa0125 and 237,239,241 for wa0121).

Verdicts (`alpha-diag`):

| Move | handbackContinuity | artworkAbove |
|---|---|---|
| b5to6 | True | True |
| b6to7 | False ("static poster exposed during DOM hand-back") | False |
| b7to8 wa0121 | False | False |
| b7to8 wa0125 | False | False |

This reproduces the owner run.

## Scratch A/B (core text monkeypatched in the probe process only; `repro/run_dbg.py` `CORE_PATCH=diag|fix|fix2`)

Uptime per batch is in `uptime-*.txt` (the load average was still decaying from a peer's suites at the first pair).

| Arm | Core sha | Hand-back ambiguity → `#body` | Alpha hand-back b5/b6/b7a/b7b | Alpha artwork b5/b6/b7a/b7b | D7 hand-back / artwork (6 carries) |
|---|---|---|---|---|---|
| `diag` (baseline) | `54521380` | Alpha 4, D7 6 | T / **F / F / F** | T / **F / F / F** | all T / all T |
| `fix` (visible-only) | `a1f3ab07` | 0 | T / T / **None / None** | T / T / **None / None** | b2to3 None (×2) |
| `fix2` (proposal) | `65088ff7` | 0 | **T / T / T / T** | **T / T / T / T** | all T / all T (= diag) |

- **`fix` is rejected.** The synchronous pick lands in the transient `-isPlaying` layer, which the player removes. On the
  last fed move of each deck (Alpha b7to8, D7 b2to3) the carried decoder leaves the DOM, and the player's own element
  plays instead (with an empty `src`).
- **`fix2` placement.** On slide 8 the decoder lands in `layer244` after `C01CA56A`, and the hit stack at the movie centre
  starts `… layer221 > video[4] > canvas#C01CA56A`. On slide 9 the decoders land in `layer345` / `layer348`. There are
  no `#body` rows in the 300 ms after any hand-back (diag has 3). D7 keeps its visible overlay `C700B0` and its verdicts
  are unchanged.
- **Unchanged in every arm, so not this fix:** Alpha b5to6 and b7to8-wa0121 read `noRiderAboveCanvas` False, and so do
  D7 b0to1 a/b. D7's top-level carry verdicts are False in every arm (paint `missingSamples` during the hidden ride).
  These are on the current core with pre-move capture disabled; at 03a35b28 headless, D7 `noRider` was green. See
  follow-ups.

## Proposed minimal fix (needs the owner's go; not applied)

`findMovieCanvas`, right after `if (!candidates.length) return null;` (`live_continuity_js.py:1696`). Rank on `ranked`
instead of `candidates` in the min-distance and tie lines that follow:

```js
    const built = candidates.filter((c) => !c.c.closest('[id$="-isPlaying"]'));
    const usable = built.length ? built : candidates;
    const shown = usable.filter((c) => getComputedStyle(c.c).visibility !== 'hidden');
    const ranked = shown.length ? shown : usable;
```

- **Why this anchor.** The stock player keeps its video in the visible `layers[1]` layer and drops that frame canvas
  once it plays. A carried decoder never triggers that removal, so it must sit after the visible frame canvas. b5to6
  already lands there today. `interimAnchor` (`:2168`) is unaffected: it anchors at root level.
- **Served bytes.** The core sha changes from `302c218d…`. Re-pin:
  - `tests/test_live_continuity_js.py:34`
  - `tests/test_live_host.py:1781`
  - `scripts/detach_experiment.py:76` (not refactor-owned)

  The plan JSON, plan sha (Alpha `c9e54655…`, D7 unchanged) and feed JS are unchanged; nothing changes on the Python
  side. No variant transform in `scripts/continuity_core_variants.py` touches `findMovieCanvas`.
- **Tests.**
  - `test_live_continuity_js.py:4301` (`…hidden_ride`, `tied` cases) uses fake canvases without `visibility`. Its fake
    `getComputedStyle` must return a visibility, and its `layer96` poster / `layer97` overlay pair should mark the
    poster hidden.
  - Add one case: a hidden poster at the exact rect, a visible frame canvas 0.25 px off, and a `-isPlaying` canvas at
    distance 0. Expect the anchor to be the visible frame canvas, with no `remount-canvas-ambiguous` and no
    `remount-done`.
  - Run the full suites (3.12 and the 3.10 floor).
- **Headless proof** (Chrome 155 qualified in-process; pre-move capture disabled or the F1 instrument fix landed;
  `repro/run_dbg.py` is the template):
  - Alpha and D7, feed on, baseline vs fix.
  - Expect the Alpha b6to7 and b7to8 ×2 hand-back and artwork verdicts to go True, with no `#body` row after any
    hand-back, and D7 verdicts identical to its baseline.
  - D7s as a third deck.
- **Controls that must stay red** on the fixed core: `departure-early-hide`, `interim-delay` (static poster exposed),
  `no-linger` (`handbackContinuity` False), `overlay-ride` (`noRiderAboveCanvas` False). None of their transforms touch
  `findMovieCanvas`, so they are expected to stay red, but that still has to be run.
- **Live.** In Q7 attempt 4, the owner should watch slides 8 and 9: the carried videos should keep moving after the move
  instead of showing a static frame.

## Follow-ups (not done here)

1. `noRiderAboveCanvas` False on the current core headless: Alpha b5to6 and b7to8-wa0121, D7 b0to1 a/b, in every arm.
   - Candidates: the departure fix (`302c218d`, not run headless before today) or the scratch pre-move-capture disable.
   - It needs its own A/B: old `03a35b28` vs current, capture on vs off.
2. Instrument (refactor scope):
   - `settledArtwork` takes one read at the first settled-visible frame, so a 1-frame excursion decides the verdict.
   - `domRead.afterCanvas` counts only visible matching canvases. That is correct for this bug, but it should be
     documented as "decoder above the visible frame canvas".
   - My own recorder's opacity product treats an inherited `visibility:hidden` as 0. The decoder overrides it with
     `visibility:visible`, so ignore the `op=0` values in `r1`.
