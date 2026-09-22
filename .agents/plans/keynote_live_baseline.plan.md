# Baseline: per-boundary refusal + visible carry (owner decision 2026-09-20)

DRAFT for owner review — written overnight 2026-09-20 by Opus (read-only); nothing here is implemented.
Parent: [`keynote_live_visible_content.plan.md`](keynote_live_visible_content.plan.md) §5–§7 (diagnosis, decision, spike:
option (b) is dead at Q2). Note: since this was drafted, `live_continuity_js.py` gained `slotLive`/`retireSlot`
(commit `6bee983`) — cite functions by name.

Read-only pass at `claude/keynote-live-continuity-next`. Every claim below is from code/JSON read today.
Note: `src/obed_edom/live_continuity_js.py` was being edited by another session while I read it — its line
numbers shifted ~+27 mid-session, so it is cited by **function name** plus an approximate line.

## 0. What I measured (new facts, not in any existing plan)

The destination slide's **draw order is explicit and exact** in the export. Each event carries
`baseLayer.layers` — a flat, back-to-front list of one wrapper per authored object; the wrapper's single
child holds the object's rect and, when the object has any effect, its `objectID`. The movie node
(`{"movie":…, "baseLayer":…}`, found by `_find_movie_nodes`, `live_continuity.py:262`) lives under
`events[i].effects…` and its `objectID` **matches its slot's child objectID exactly** — no geometric guessing.
Measured on `output/p2-recovery/html-adversarial/html-player/assets/<uuid>/<uuid>.json`:

| slide | slots (z ascending, authored rect) | movie slot |
|---|---|---|
| 1 | 0 bg · **1 movie#2** (1073,874,671,195) · 2 black (976,723,266,236) · **3 movie#1** (107,793,960,276) · 4 green α0.29 (638,724,178,157) | 1 and 3 |
| 2 | 0 bg · 1 black (543,722,181,161) · 2,3,4 build-in squares (no overlap) · **5 movie** (107,793,960,276) · 6 green α0.29 (**790,675,353,313**) | 5 |
| 3 | 0 bg · **1 untitled** · **2 WA0125** | 1, 2 |
| 4 | 0 bg · **1 movie** (324,706,1274,364) | 1 |

So on slide 2 exactly **one** later-authored object overlaps the carried movie: the green square (z 6 > 5,
intersection ≈ 790..1061 × 795..988). The black box overlaps geometrically but is z 1 — **behind** — which is
what P2 Finding 2's `blackBehind` asserts (`p2_recovery_html_adversarial.py:82-88`). Slide 4 has nothing above
the movie ⇒ the 3→4 bridge is carryable. The brief's "green square **and** black box overlap" is half right:
the black box must not trigger a refusal, and the rule must read z, not just rects.

Second measured fact: the movie node's whole subtree uses a **closed key vocabulary** across all four slides —
node `{attributes,baseLayer,beginTime,duration,effects,movie,name,objectID,type}`, layer
`{animations,initialState,isVideoLayer,layers,objectID,texture,texturedRectangle}`, initialState
`{affineTransform,anchorPoint,contentsRect,edgeAntialiasingMask,height,hidden,masksToBounds,opacity,position,rotation,scale,sublayerTransform,width}`. `masksToBounds` is false and `contentsRect` is the unit rect everywhere. There is **no mask vocabulary at all** in this export — that is the whole basis for §2's interim rule.

## 1. Refusal granularity — **recommend per-boundary, expressed as an explicit `retire`**

Whole-deck `unsupported` is wrong here: it would also kill the 3→4 bridge, whose destination provably has
nothing above the movie, and would leave the project with **zero** green fixtures. Per-boundary refusal is
strictly the fail-closed direction *for the boundary that is unsafe* and leaves the rest as authored.

The minimal honest expression is **one new runtime action, `retire`** — the first slice of the generalisation's
`pin|bridge|restart|retire` (`keynote_live_continuity_generalisation.md:36-44`) — and **not** making `pin`
explicit yet. Making pin explicit means teaching the runtime a zone walk (limitations #2/#3) — that is the
generalisation, not this PR. `retire` alone says exactly what is needed: *at this scene, hand this movie back
to the player*. The implicit pin zone before the first boundary stays, and stays true (slide 1 is untouched).

**Before** (derived today, verified by running `derive_plan` on the fixture):

```json
{"movies":{"movie1":{"assetKeys":["untitled.mov"],"footprint":{"x":109,"y":795,"w":952,"h":268}}},
 "boundaries":[{"atScene":6,"action":"restart"},
               {"atScene":8,"action":"bridge","movieKey":"movie1",
                "srcRect":{"x":198,"y":797,"w":952,"h":268},"durationSeconds":1.5,
                "rect":{"x":327,"y":709,"w":1266,"h":356}}]}
```

**After** — one inserted entry (`atScene` 2 = `scene_index_by_player[1]`, the 1→2 destination):

```json
 "boundaries":[{"atScene":2,"action":"retire","movieKey":"movie1"},
               {"atScene":6,"action":"restart"}, {"atScene":8,"action":"bridge", …unchanged}]
```

`to_runtime()` guards, strictly additive and fail-closed (`live_continuity.py:172-237`): at most **one**
`retire`; it must precede the first restart and any bridge; a refusal on any other boundary ⇒ whole-deck
`Unsupported` (untested generality is not shipped). Derivation stays structural: `MovieContinuity` gains
`refusal: str | None = None` (last field, default `None`, so the positional construction at
`tests/test_live_continuity.py:377` still works); `action` keeps saying `pin`. Add
`ContinuityPlan.refusals: tuple[dict,…] = ()` (additive, **not** in `to_runtime`, like `slide_instances`,
`live_continuity.py:104-109`) and surface it as `continuity.notCarried` in `_continuity_info`
(`live_host.py:875-881`) so the owner sees *why* on air.

**Must change in one commit** (the signature moves):
1. `QUALIFIED_PLAN_SHA256` (`live_continuity.py:37`) — **replace**, do not append: the old shape is no longer derivable and leaving it allows an unqualified plan.
2. `tests/test_live_continuity.py` — the pinned literal (`:748`), `test_to_runtime_matches_p2_injected_plan` (`:351`, boundary set becomes `{2,6,8}`), the signature test (`:556`).
3. `scripts/p2_recovery_html_adversarial.py:2467-2491` — injected plan gains the retire entry + a `SLIDE2_MIN_HASH = 2` constant beside `SLIDE3_MIN_HASH` (`:115`). `--disable-bridge34` still removes only the bridge.
4. `scripts/p2_recovery_html_dissolve_live.py:891-898` — **unchanged**: that fixture has no Magic Move, so "pin throughout" stays correct and its docstring stays true.
5. `live_continuity_js.py` `CONTINUITY_VERSION` 3→4 + `tests/test_live_continuity_js.py:24,28`.

## 2. Overlap and mask derivation in `derive_plan`

**Overlap rule** (runs only for a boundary whose movie action is `pin` or `bridge`, on the **destination** slide):
1. `_slide_movie_instances` (`:330`) also returns each instance's `objectID`; a movie node without a non-empty
   string `objectID` ⇒ refuse.
2. For **every** event of the destination slide: `slots = event["baseLayer"]["layers"]` (missing/not a list ⇒ refuse).
   A slot's object node is its single child; a slot **above the movie slot** with ≠1 child ⇒ refuse
   (`unrecognised slide layer shape`). Find `m` = the slot whose object node's `objectID` equals the instance's.
   If `m` is absent in an event, **skip that event** (the flattened transition event — slide 2 event 3 is a single
   1920×1080 slot, slide 1/3/4 event 1 likewise); if absent in *every* event ⇒ refuse.
3. Artwork = every slot at index > `m`, unioned across the scanned events. Rect = object node
   `position ± width/2, height/2` (same convention as `_movie_rect`, `:313-318`).
4. Compare against the **video sub-layer** rect (`_movie_rect`'s result — the painted rect), not the movie
   baseLayer. Refuse when the intersection is wider **and** taller than `_OVERLAP_MIN_PX = 1.0` authored px
   (edge-touching and AA seams do not refuse).
5. **Opacity / `hidden` are deliberately ignored.** An object that builds in later sits in the slot list from
   event 0 and the export does not mark it as not-yet-built (slide 2's slots 2/3/4 are `buildIn` characters and
   carry `opacity: 1` in the initial state) — so there is no way to tell "invisible forever" from "invisible
   until its build". Treating every slot as artwork makes the build case automatically correct ("the carried
   movie stays correct through every build") at the price of refusing a deliberately transparent object. That
   is the fail-closed direction, and it is documented, not worked around.
6. Groups and text need no special case: both are slots with an object node and a rect. Text over the movie
   refuses — correct, a caption must not be painted under a body-level overlay.
7. Reason: `"later-authored artwork overlaps the carried '<asset>' on the destination slide (player index N, draw slot J)"`.

**Mask rule (interim, encoding UNMEASURED).** Applied inside `_movie_rect` (`:290`) to *every* movie node, so a
masked movie also cannot supply a `slide_instances` rect the V pass would trust. Refuse when, on the movie
baseLayer or its `isVideoLayer` sub-layer: `masksToBounds` is true; `contentsRect` ≠ `{0,0,1,1}` (1e-6);
the video rect is not contained in the base rect (0.5 px); a `shapePath` appears anywhere in the subtree; or
**any key falls outside the measured vocabulary in §0**. Reason:
`"movie on slide <name> carries an unrecognised layer encoding (possible mask): <key>"`.
Measurement when the owner supplies the masked deck: export it, diff the movie node's subtree key set and
`initialState` values against §0's vocabulary, and record which knob moved (expect `masksToBounds` + a shrunk
baseLayer, a non-unit `contentsRect`, or an extra mask sub-layer). Then replace the allowlist refusal with the
specific rule + a unit test on the real JSON. **Risk:** the key allowlist will refuse decks that merely use a
feature this fixture lacks. Acceptable while the signature allowlist still gates everything; it becomes the
dominant refusal source only at generalisation step (d), and must be revisited there.

## 3. Runtime (S5) — split in two; only the first half is provable today

With 1→2 refused, the fixture **never takes the in-layer remount path**: the only surviving carry is 3→4, which
already goes to `<body>` (`bridgeTo34`/`keepAtSlot`, ≈`:737,:673`). So the visible-target remount cannot be
proven on this deck. Split accordingly.

**S5a — retire zone (lands now, ~55 lines).** One predicate `preserveAllowed(v)`: false when
`currentHashNum() >= ` the retire `atScene` for `movieAssetKey(src)`. Used by `stash` (`:384`),
`patchSrcAccessor`'s empty-src branch (≈`:1217`), the `removeAttribute` hook and `tryRemount` (`:894`). Critical
detail: the src-clear hook today swallows the clear **unconditionally**, so without this the refused movie still
deviates from raw — `preserveAllowed` must let the real setter run. Plus a `hashchange` sweep that retires
already-pooled decoders of a retired key (the 1→2 detach can fire while the hash is still 1). Every block emits
a **positive** note — `preserve-refused {key, scene}` / `retire-boundary {key, elIds, atScene}` — so the gates
assert an event, never silence.

**S5b — hold until the positive-control deck exists (~55 lines).**
- *Visible-target remount*: after placement in the authored-parent and poster-canvas branches of `tryRemount`,
  test `v.isConnected && v.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && opacityProduct(v) > 0.02`
  (never `elementsFromPoint` — measured useless, plan §5) and fall through to the existing stage/body overlay
  otherwise. Evaluate the test only from the **second** retry onward (≈200 ms), so the synchronous in-detach
  placement that the footprint-owner crossing check depends on is untouched and a transient opacity-0 during a
  dissolve is not mistaken for the WebGL case. Once a video falls back, stamp `v.__obedOverlay = epoch` so later
  retries re-assert the overlay instead of oscillating back into the layer.
- *Instance admission in `stash()`*: the trustworthy rect is the one captured **while attached** by the 200 ms
  `captureLayout` interval (≈`:1192`) — detach zeroes `getBoundingClientRect`. Have `captureLayout` also stamp
  `v.__obedAuthoredRect` using the `stageMap()` read in the *same* tick, so no stale-transform conversion is ever
  needed on a scaled stage. Admit only if that rect matches, within `footprintKeyForRect`'s 20/30 authored px
  (`:858`), one of the plan rects for the movie's key (`movies[k].footprint` + every boundary `srcRect`/`rect`
  with that `movieKey`). No trustworthy rect ⇒ do **not** preserve (worst case is the raw restart).
  On the fixture: (109,795,952,268) admitted, (1076,876,663,186) rejected — the stray, by geometry.
- *Keyed footprint fallback*: replace `fps[((v.__obedElId||1)-1) % fps.length]` (`:957`) with
  `planMovies()[movieAssetKey(src)].footprint`; unknown ⇒ note and **no remount**.

Each byte of `live_continuity_js.py` costs the ~45 min re-qualification; S5a and S5b are therefore two
qualification runs. Recommending that over one run is deliberate: shipping S5b unproven-on-pixels is exactly the
class of mistake (green gates, invisible movie) this whole baseline exists to correct.

## 4. P2 gate re-scope (the 14 findings under refusal)

Unchanged, no re-scope: `sourceUnchanged`, `emptyCanvasPre`, `blackSentinelOpaquePre`, `greenTranslucentPre`
(`:3090-3093`), `blackSurvivesAfter1to2`, `emptyCanvasAfter1to2` (`:3173-3182`), `reachedSlide3` (`:3213`),
`overlayRemovedOnLeave` (`:3222`), `deliberateRestart2to3` (`:3242` — it scores actual slide-3 playback, which a
never-pooled key gives natively).

**`overlappingArtworkComposedAfter1to2` (Finding 2, `:3183-3211`) is NOT re-scoped.** §6.4 of the visible-content
plan assumed the D3(a)-only world where a body overlay covers the green square. Under (c)+(a) the fixture never
overlays slide 2, so the authored z-order is the player's own and green-in-front / black-behind stay provable
exactly where they are. **Refusal is what keeps Finding 2 honest** — say so in the report note. *Risk:* today
`BLACK_BEHIND_ROI` (560,800,140,70) happens to sit inside the 663×186 stray, so it currently reads a *live*
grating; after the fix it reads the *frozen poster* grating. Both are mid-grey (`rgbMean > 40`), but this must be
confirmed on the re-qualification run — if it dips, that is a true red to investigate, never a loosened threshold.

**`continueThroughMagicMove1to2` (Finding 1, `:3094`) becomes `refusedCarry1to2`** — a refusal-honoured finding.
Its continuity criteria (`cont.continuesThroughDissolve`, `index_run`, `liveContinuity1to2`) are all false **by
design** now, so they must be replaced, not merely relaxed. New pass gate, all required:
(a) the injected plan contains the retire boundary at `SLIDE2_MIN_HASH` (read back from
`continuity-plan-inject.json`); (b) a `preserve-refused` or `retire-boundary` preserve event for `movie1` at
scene ≥ 2; (c) **zero** `remount-*` / `reuse-decoder` events for `movie1` at scene ≥ 2; (d) on settled slide 2,
zero `<video>` elements with `data-obed-preserved` / `data-obed-remounted` and zero visible `<video>`s
overlapping the slide-1/2 footprints — reuse the existing `lingering_movie_overlays` helper that
`overlayRemovedOnLeave` already uses, pointed at slide 2; (e) the composite in `INDEX_PATCH_ROI` is **frozen**
(the raw export's behaviour) and `hash1 != hash2`; (f) no `player_build_errors`.

**`preserveDidNotBlockRestart` (`:3275`) must be re-scoped, or it goes red for the wrong reason.** It requires
`reuse_skip_boundary_matching_restart >= 1` **and** `retire_events_for_target >= 1` — both produced by the
`inDissolveRestartZone && q && q.length` branch (≈`:1272`). With `movie1` never pooled, the pool is empty at
scene 6 and neither event fires. Re-scope to: the existing negative clauses stay verbatim (no manual clear, zero
`reuse-decoder` at/after the boundary, no stitched restart), and the positive pair is required **unless** a
`retire-boundary`/`preserve-refused` event for the target key at scene ≥ 2 is present with no later stash of that
key. That is a strengthening, not a weakening: "nothing was even pooled" beats "the pool was skipped", and it is
proven by a positive event.

**`continueThroughMovingMagicMove3to4` (`:3316`) keeps every existing criterion and gains `footprintFullyLive`.**
This is where the shared scorer belongs, not Finding 1: slide 4 is the only surviving carry and is measured
visibly correct. Capture a `Page.captureScreenshot` burst at the probe's `BURST_OFFSETS_MS`
(`live_continuity_probe.py:98`) on settled slide 4 and run `html_alpha_probe.score_live_coverage` +
`score_noise_floor` over the single expected rect `SLIDE4_MOVIE_RECT` (`:124`), control patch =
`EMPTY_CORNERS[0]`. Thresholds imported, never re-tuned. The bridge decoder is created fresh at the 2→3 restart,
so the scene-2 retire cannot touch it. **`--disable-bridge34` is untouched**: it removes only the bridge entry,
the retire stays, and the only red stays `continueThroughMovingMagicMove3to4` (now doubly: identity *and* pixels).

`freezeControlCaughtByCounter` (`:3368`) brackets the **1→2** boundary and asserts `liveContinuity1to2` stays
green in arm B — that premise dies with the refusal. Move the A-B-A bracket to the **3→4** boundary (the same
mechanism, the only live-carry cut left) and gate on `movingIndexRun` going red with `freeze run at cut` while
`movingContinuity3to4` stays green. If that proves too costly this round, the honest alternative is to mark it
`inconclusive` (which already blocks `success`, `:3397-3401`) until it is moved — **never** to drop it.

### Host probe arms and the expectation model

Arm expectations are today hard-wired (`overall_status:1528`, `continue1to2` must be True in A/C/attach). Derive
them from the plan instead (`ground_truth_facts:313`): a boundary carried by the installed plan ⇒ `True`; a
boundary the plan **retires** ⇒ `False` **plus** a positive `refused1to2` verdict — on settled slide 2, zero
painting `<video>`s overlapping the movie rect (`PAINTING_VIDEOS_JS:141` already answers exactly this) and no
pooled/preserved entry for `movie1` in `__OBED_P2_PRESERVE__.snapshot()`. Without that positive half, "did not
continue" is a vacuous assertion.

**V/Voff expectation model.** Per-rect expectation ∈ {live, dead}, derived from the plan, and **both** are
scored:
- destination of a **carried** `pin`/`bridge` ⇒ **live**;
- destination of a **retired** `pin` ⇒ **dead** (measured: with continuity off the fixture's slide 2 is "fully
  dead" — handover `:40`; the export creates no fresh element for a geometry-static Magic Move);
- destination of a `restart`, a `bridge` under the raw player, or the first slide ⇒ **live** (measured: Voff
  slides 1/3/4 green — a geometry-*changing* Magic Move does get a fresh autoplay-from-0 element).

So under the baseline **slide 2 is "dead, expected" = GREEN by refusal** in *both* V and Voff, and an
unexpectedly dead carried rect (slide 4) is RED. Feed refused rects to `score_visible_slide`'s existing
`ignore_rects` parameter so the stray check tolerates whatever the player paints there, and score them with an
inverted verdict (`liveFrac <= 0.05` with the noise floor green). `expected_screen_rects` (`:1114`) gains the
expectation flag; `visible_reasons` (`:1489`) replaces its `boundaryPlayerIndex` red-slide logic.
**No new arm is needed for the red control**: the instrument is proven two-sided *within each pass* — slides
1/3/4 must read live (not always-red) while slide 2 must read dead (not blind). Voff is kept as the raw-export
reference and the `mode == 'off'` assertion.

## 5. Fixtures the owner must author (agents never touch Keynote)

All three: 1920×1080, movie asset = the **existing grating-with-counter test movie** (so `index_run`,
`score_visible_slide` and the neutral-grating green test keep working), no other movies, nothing else animated.

**(i) Positive control — 4 slides, "nothing over the movie".** S1: the movie alone, roughly centred, plus one
shape *behind* it (to keep a z-order control) and nothing above it. S1→S2 **Magic Move, geometry-static** (the
movie at the identical rect on S2) — this is the case the fixture can no longer test. S2→S3 **Magic Move,
moving + scaling** (move and enlarge the movie; nothing above it on S3). S3→S4 **dissolve** with the movie
present on S4 — the deliberate restart. Every destination slide must have *nothing* in a higher draw slot
overlapping the movie rect. This deck alone qualifies S5b.

**(ii) Masked movie — MOOT (2026-09-22): Keynote cannot mask a movie, and a DSK-generator crop is a pre-cropped file with a plain rect; nothing to author. Kept for the record.** S1: one movie with a **shape mask / crop** applied in Keynote (an ellipse or a
rectangle smaller than the movie). S1→S2 Magic Move, same rect. Purpose is the *encoding measurement*, not a
green run: the expected outcome is `Unsupported: possible mask`.

**(iii) Optional, overlap-after-build — 2 slides.** S1: movie alone. S1→S2 geometry-static Magic Move; on S2 a
rectangle that **builds in on click** and overlaps the movie. Expected: refused at derivation (the object is in
the slot list from event 0), which is what turns §2 step 5 from an argument into a measurement.

## 6. Increments, order, acceptance

Disjoint files, so I1/I2 and I3 can run in parallel.

| # | Files | Work | Gated today? |
|---|---|---|---|
| I1 | `src/obed_edom/live_continuity.py`, `tests/test_live_continuity.py` | overlap + mask refusals, `refusal`/`refusals` fields, `retire` in `to_runtime`, new allowlist sha | **Yes** — unit tests on the real fixture JSON |
| I2 | `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py` | S5a retire zone + notes, `CONTINUITY_VERSION` 4 | **Yes** — Node sandbox + P2 |
| I3 | `scripts/live_continuity_probe.py`, `src/obed_edom/html_alpha_probe.py` (+ tests) | plan-derived arm expectations, `refused1to2`, live/dead expectation model, `ignore_rects` wiring | **Yes** |
| I4 | `scripts/p2_recovery_html_adversarial.py` | injected retire, `refusedCarry1to2`, `preserveDidNotBlockRestart` re-scope, `footprintFullyLive` on slide 4, freeze bracket moved to 3→4 | **Yes** |
| I5 | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | `continuity.notCarried` surface | Yes |
| I6 | `live_continuity_js.py` (2nd pass) | S5b: visible-target remount, instance admission, keyed fallback | **No — needs deck (i)** |

**Order.** I1 ∥ I3 → I2 (needs I1's plan shape) → I4 (needs I2's note names) → I5 → full re-qualification →
Codex. Then, when deck (i) and (ii) land: measure the mask encoding, replace the interim rule, run I6 and a
second re-qualification, add the new decks' signatures to the allowlist.

**Acceptance per increment.** I1: `derive_plan` on the fixture yields exactly the After JSON of §1 and
`refusals` names the 1→2 boundary with the green square's slot; a synthetic variant with the green square moved
to slot 4 (below the movie) must **not** refuse; a synthetic `masksToBounds: true` must refuse. I2: Node tests —
a retired key is neither pooled nor remounted, the src clear passes through, the sweep retires a
pooled-before-the-hash decoder, and `preserve-refused` is emitted. I3: pure-scorer unit tests for the
dead-expectation inversion; `overall_status` unit tests for the new arm table. I4: P2 `--reuse-export
--disposable` `--wait-profile fast` **and** `slow` 14/14, and `--disable-bridge34` red **only** on
`continueThroughMovingMagicMove3to4`. Whole baseline: host gate at 1920×1080, 2560×1440, 1600×1000 (each with
V/Voff), full unit suite, one real-OBS attach pass, new `CONTINUITY_VERSION`/sha recorded in the handover.

**Risks.** (1) `BLACK_BEHIND_ROI` now reads the frozen poster (§4) — verify, never loosen. (2) The retire may
race the 1→2 detach; the sweep + the `tryRemount` guard cover both orders, but the P2 finding must accept either
event, which is why both notes exist. (3) `freezeControlCaughtByCounter` loses its boundary — moving it is real
work; if it slips, it must go `inconclusive`, which already blocks `success`. (4) The mask key-allowlist will
refuse decks using any unmeasured feature; visible and intended, revisit at generalisation (d). (5) S5b lands
unproven on pixels if the owner overrides §3's split — then say so explicitly in the capability report.

### Critical Files for Implementation
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/p2_recovery_html_adversarial.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/live_continuity_probe.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/html_alpha_probe.py

---

Two things I could not determine and how to measure them, called out above but repeated here so they are not
lost: **(a)** how the export encodes a movie mask — the fixture has none and the entire key vocabulary is closed
(§0), so the interim rule refuses on any unknown key; measure by diffing deck (ii)'s movie-node subtree against
§0's vocabulary. **(b)** whether "a geometry-static Magic Move destination is frozen under the raw player" holds
beyond this export family — it is measured only on this fixture (handover `:40`); deck (i)'s S1→S2 re-tests it,
and if it fails there, only Voff's expectation table changes, not V's.
