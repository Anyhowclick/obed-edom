# Live continuity — visible-content gate, slide-2 invisibility diagnosis, and the minimal retire fix

Status: **LANDED via #175 → #158 (2026-09-20).** Drafted 2026-09-19 by Opus (read-only) from evidence measured the same day; owner said "go as far as you can" —
proceeding on the recommended options D1a · D2a · D3 (per diagnosis) · D4 (b1+b2) · D5, all revisitable.
Evidence: with continuity ON the fixture's slide 2 shows the static POSTER in the big movie's rect and only a stray
663×186 copy of the second `Untitled.mov` instance at its top-left, while every gate was green.

Read at `claude/keynote-live-continuity-next`. Every claim cites code read today. Fail-closed throughout; no threshold in an existing gate is loosened.

## 0. What today's evidence actually indicts

The gates are geometry/identity gates, not *paint* gates. `footprintOwnerDecoderId` (`src/obed_edom/live_continuity_js.py:229-294`) resolves ownership by IoU ≥ 0.75 against the plan footprint and `isCompositing(v)` (`:691`) — DOM-level, never pixels. The probe's sampler records `getBoundingClientRect` + `currentTime` only (`scripts/live_continuity_probe.py:145-165`). P2's Finding 1 explicitly does **not** gate composited pixels (`scripts/p2_recovery_html_adversarial.py:739-746`); composited proof comes from `index_run`, decoded at a **fixed ROI derived from the big movie's footprint** (`INDEX_PATCH_ROI`, `:101-106`, `index_patch_roi_for` `src/obed_edom/html_alpha_probe.py:1363-1381`). Nothing binds those pixels to the decoder that owns the rect. The 663×186 stray at (109,795) satisfies the counter and no gate asks whether the other 63 % of the big rect is live. That is the gap to close first.

The stray itself comes from two places: `stash()` admits any video whose src matches a plan `assetKeys` (`live_continuity_js.py:411`) with no per-instance test, and the `tryRemount` footprint fallback places it at `fps[((v.__obedElId||1)-1) % fps.length]` (`:930`) — one movie key ⇒ always movie1's footprint.

## 1. Instrument: a visible-content pass (must be RED on today's build)

### 1.1 Method (decision D1 — **recommend (a)**)
- **(a) In-arm temporal difference + band coverage** ← recommended. On a settled slide take a burst of `Page.captureScreenshot(format='png')` (lossless; transport supports `transport.call(...)`, `live_host.py:553`). A pixel is **live** iff `max_t(channel) − min_t(channel) ≥ DELTA_MIN` over the burst. Posters, frozen video, opaque occluders and static artwork are all not-live; a *translucent* occluder (the fixture's green square, P2 `:88` "translucent green IN FRONT") still modulates and stays live. No cross-run alignment, works inside every arm including the OFF arm.
- **(b) Continuity-OFF reference diff** — rejected: the OFF arm is itself a red control (it cannot be its own reference), the diff proves only "different from the poster" (a frozen non-poster frame passes), and it couples two browser processes' build timing.

### 1.2 Verdicts per settled slide
Expected rects = **every movie instance the export authors on that slide**, authored px, converted to screen px with the probe's own stage map (`stageMapOf`, `live_continuity_probe.py:135-144`; `to_authored_rect` `:393`), then inset 2 px to drop AA edges.
1. `liveCoverage` per rect: split into **16 column bands × 8 row bands**; a band is live iff ≥ 5 % of its pixels are live. PASS iff **all 24 bands live** AND `liveFrac ≥ 0.35`. Bands beat a bbox/whole-rect test: an interior opaque occluder (P2 `BLACK_ROI_S2` 134×114 in a 952×268 rect, `:80`) never blanks a full band, while today's 663×186 sub-rect blanks ~6 column and ~2 row bands ⇒ **RED at slide 2 today**.
2. `noStrayMovie` per slide: liveness mask minus all expected rects dilated by 6 px; `cv2.connectedComponentsWithStats` (cv2 is a dep, `pyproject.toml:15`); any component ≥ 2000 px² ⇒ RED. This is the brief's stray check (`keynote_live_continuity_generalisation.md:58-60`) and re-proves the `stash` plan filter (WA0125 on slide 4).
3. `noiseFloor`: 99th-percentile delta over a known-static control region (letterbox bars, or a 40×40 patch at the stage corner) must be `< 6`; otherwise the slide is **INCONCLUSIVE**, never a pass.

### 1.3 Thresholds and sampling
`DELTA_MIN = 12`; burst of **5** shots at offsets `0, 130, 290, 500, 770 ms` after settle (gaps 130/160/210/270 — deliberately unequal so a periodic two-state grating cannot alias, the failure `score_index_progression` was written against, `html_alpha_probe.py:1420-1441`); liveness uses max−min across **all** shots, not consecutive pairs. Settle = existing `advance_until_original_slide` + `POST_ADVANCE_SETTLE_S` (`live_continuity_probe.py:318-342`, `:70`), plus `observe().busy == False` and `__obedLive.snapshot().sceneId` identical before and after the burst (one retry, then INCONCLUSIVE). Screenshot dimensions must equal the forced viewport (deviceScaleFactor 1 is already forced, `:877`, `:895-916`) else fail closed.

**Known failure modes (documented, not worked around):** a genuinely static movie segment or a near-uniform dark movie region ⇒ false RED (artifact records per-rect `maxDelta`); a full-width or full-height *opaque* occluder ⇒ false RED (treat as "deck not qualified", the correct fail-closed direction); an animated non-movie element inside a rect ⇒ false GREEN for coverage only — bounded because the stray check covers everything outside rects; a build that reveals a movie after settle ⇒ RED (documented limitation).

### 1.4 Where it runs (timing safety)
A **separate pass**, never inside arms A/B/C: screenshots cost 30–80 ms and would perturb the rAF sampler's clock/stall windows (`WINDOW_PAD_S`, `:82`). Add two passes with their own `LiveOutputHost` sessions and **no `SAMPLER_JS`**: `V` (continuity on ⇒ must PASS) and `Voff` (`CONTINUITY_ENV=off` ⇒ must be RED at the 1→2 slide, proving the instrument sees the raw-export defect). Both assert `continuity.mode` as A/B do (`:1052`, `overall_status` `:1043-1060`). They gate `overall_status` (decision D5).

### 1.5 Ground truth for per-slide rects
`ContinuityPlan.slide_rects` **drops multi-instance assets** (`live_continuity.py:414-418`: `if len(rects) == 1`), so it cannot describe slide 1's two `Untitled.mov` instances. Add an additive field `slide_instances: dict[int, dict[str, list[dict]]]` to `ContinuityPlan` (default `{}`, last field) populated from the already-computed `instances_by_player` (`:403`). `to_runtime()` output is untouched ⇒ **`plan_signature` and the allowlist entry do not move** (`:40-45`, `:229`). `as_dict()` round-trip tests stay valid (`tests/test_live_continuity.py:321,333`); `:377` constructs the dataclass positionally, hence the default.

### 1.6 Artifact and unit tests
Artifact per pass: `slides: [{playerIndex, sceneId, expectedRects:[{asset,instance,authored,screen}], perRect:[{liveFrac, deadBands, maxDelta, verdict}], stray:[{bbox,area}], noiseFloor, shotOffsetsMs, stageMap, verdict}]`; on failure also write `output/.../visible/slide<N>-mask.png`.
Pure scorers (`liveness_mask`, `score_live_coverage`, `score_no_stray_movie`) live in `src/obed_edom/html_alpha_probe.py` beside the existing pure pixel scorers so **both** gates import one copy. Unit tests on synthetic numpy stacks, no browser: full-rect live ⇒ PASS; left-half live only ⇒ RED (today's shape); interior opaque box ⇒ PASS; translucent-modulated box ⇒ PASS; full-height opaque stripe ⇒ RED; two-state periodic pattern sampled at the aliasing period ⇒ still live (unequal gaps); all-static ⇒ RED; noise-floor 8 ⇒ INCONCLUSIVE; stray blob 45×45 outside rects ⇒ RED, 20×20 ⇒ PASS.

### 1.7 P2 (decision D2 — **recommend (a)**)
- **(a) Gate it inside the existing Finding 1** `liveContinuity1to2` (`p2_recovery_html_adversarial.py:697`) as one added criterion `footprintFullyLive`, using the shared scorer on a settled slide-2 burst; existing criteria and thresholds untouched, no 15th finding. Rationale: Finding 1's composited proof is precisely what the evidence undermined, and the PR owns the file. Cost: **P2 is 13/14 until the fix lands** — that RED is a true finding and is part of the deliverable.
- (b) probe-only now, P2 as follow-up — only if the owner wants P2 kept green through the interim.

## 2. Browser diagnosis: why elId 1 does not paint on slide 2 (for the implementer)

Throwaway headless session, continuity ON, advance to slide 2, then, in order:
1. `document.elementsFromPoint(x,y)` at 9 points across the big screen rect → the topmost painter at each. Expect either the movie's poster canvas or a stage-wide WebGL canvas above the video.
2. Ancestor chain of elId 1 **and** of its poster canvas (`findMovieCanvas` picked it, `live_continuity_js.py:774-812`): per node `id, tagName, getBoundingClientRect, computed {transform, transform-style, perspective, z-index, position, opacity, filter, mix-blend-mode, isolation, will-change, clip-path, overflow}`. A `preserve-3d` ancestor makes **translateZ**, not DOM order, decide paint order — the remount inserts the video as `posterCanvas.nextSibling` (`:947`) and deliberately removes z-index to protect Finding 2 (`:975`, comment `:961-968`).
3. Is `layer39` the *composited* layer? `v.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})`, product of ancestor `opacity`, and whether an ancestor is the outgoing scene container (`display:none`/`opacity:0`/`visibility:hidden`).
4. All `canvas` elements with rect ≈ the stage and their context type / stacking — a full-stage WebGL composite painting above `#stage` children.
5. Decoder liveness: `v.getVideoPlaybackQuality().totalVideoFrames` and `currentTime` sampled 500 ms apart; `requestVideoFrameCallback` firing.
6. Two one-line mutation probes with a screenshot each: `posterCanvas.style.visibility='hidden'`; then `v.style.zIndex='2147483647'`.

**Implications.** Grating appears when the poster is hidden ⇒ paint-order inside the authored layer ⇒ fix (a2). Appears only with the z-index bump ⇒ same family but the z fix breaks Finding 2. Appears in neither ⇒ elId 1 is in a non-composited/outgoing layer ⇒ `findMovieCanvas` matched a stale layer's canvas ⇒ fix (a1)/(a3). Frames not advancing ⇒ Chrome is culling a hidden subtree ⇒ the layer is definitely wrong, not the stacking.

## 3. Fix options

### (a) Big-movie visibility — **pick after §2, do not choose blind**
1. **Visible-target selection + proven fallback**: after the authored-layer remount, verify paint cheaply (`checkVisibility` + ancestor-opacity product + `elementsFromPoint(center)` contains `v` before any canvas); if not, fall through to the existing `<body>`-level overlay (the path that is *visibly correct* at 3→4). ~25 lines in `tryRemount` (`:941-1000`). Blast radius: new `CONTINUITY_VERSION`/sha; a body-level overlay paints over the green square ⇒ **Finding 2 would flip RED** — but only on decks where the layer path is already invisible, where Finding 2 is unprovable anyway. Rank 1 if §2 says "wrong/outgoing layer".
2. **Neutralise the poster canvas under a mounted preserved decoder** (`posterCanvas.style.visibility='hidden'`, restored on retire/`clear()`). Smallest change, keeps the video inside the authored layer ⇒ **Finding 2 unaffected**. Rank 1 if §2 says "poster in front". ~10 lines.
3. **Copy the poster canvas's translateZ (+ε) onto the video.** Fragile against arbitrary authored transforms and interacts with the measure-and-correct placement (`:969-974`). Rank 3.
4. **z-index bump** — rejected outright: it is the exact thing the comment at `:966-968` forbids because it breaks Finding 2.

### (b) Retire the same-asset second instance at 1→2 — **minimal and correct today**
1. **Per-instance geometric admission in `stash()`** (recommended). Today the only test is asset key (`:411`). Add: the video's last trustworthy **authored** rect must match one of the rects the plan names for its key — `movies[k].footprint` plus every boundary `srcRect`/`rect` for that `movieKey` (tolerance as `footprintKeyForRect`, 20/30 authored px, `:831-845`). The small instance (663×186 @ 1076,876) matches none ⇒ never pooled ⇒ never remounted ⇒ it retires with the player. Identity is **plan geometry, never `pool.get(key).shift()` order** (brief limitation #4, `generalisation.md:27`). When no rect is trustworthy (the `nearZero`/`nearStageOrigin` detach case, `:922-926`), **do not preserve** — worst case is the raw player's restart, i.e. fail-closed. ~12 lines; plan shape unchanged ⇒ **allowlist signature and P2's injected plan unchanged**.
2. **Key the footprint fallback instead of modulo-indexing it**: replace `fps[((v.__obedElId||1)-1) % fps.length]` (`:930`) with a lookup by `movieAssetKey(src)`; unknown ⇒ no remount. ~8 lines, strictly narrowing. Land with (1).
3. **Explicit per-boundary per-instance `pin|bridge|restart|retire` + instance identity in the plan** — the brief's target design (`generalisation.md:36-44`). Changes the runtime plan shape ⇒ new signature ⇒ new allowlist entry + P2 plan-injection update in the same commit (`:69-71`). **Generalisation work, not this PR.**

## 4. Work split, ordering, decisions

| # | Files (disjoint) | Work |
|---|---|---|
| S1 | `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py` | V/Voff passes, artifact, `overall_status` wiring |
| S2 | `src/obed_edom/html_alpha_probe.py` + its tests; `src/obed_edom/live_continuity.py` + `tests/test_live_continuity.py` | shared pure scorers (§1.6 API, fixed up front so S1 runs in parallel); `slide_instances` |
| S3 | `scripts/p2_recovery_html_adversarial.py` | Finding 1 `footprintFullyLive` (after S2) |
| S4 | *no files* | §2 diagnosis, report only |
| S5 | `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py` | (a) per §2 outcome + (b1)+(b2) |

**Order.** S2+S1 in parallel with S4 → **capture the RED artifact on today's build (V pass RED at slide 2, Voff RED at 1→2)** → S3 → S5 → full re-qualification: P2 `--reuse-export --disposable` `--wait-profile fast` and `slow` (14/14) and `--disable-bridge34` (RED only on `continueThroughMovingMagicMove3to4`); host gate at 1920×1080, 2560×1440, 1600×1000 (each with V/Voff); unit suite; real-OBS attach pass (`generalisation.md:72-73`). New `CONTINUITY_VERSION`/sha recorded.

**Owner decisions (recommendation first).** D1 liveness method: **(a) temporal diff + bands** vs (b) OFF-arm reference. D2 P2 wiring: **(a) gate inside Finding 1 now, accept 13/14 until the fix** vs (b) probe-only. D3 visibility fix: **defer to §2; pre-approve option (a2) if the poster is in front**. D4 retire scope: **(b1)+(b2), plan shape unchanged** vs full per-instance plan actions now. D5: **the V pass gates `overall_status` immediately** (the RED is the deliverable).

### Critical Files for Implementation
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/live_continuity_probe.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/html_alpha_probe.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity_js.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/src/obed_edom/live_continuity.py
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/friendly-sammet-32dab4/scripts/p2_recovery_html_adversarial.py

## 5. Diagnosis result (§2, measured 2026-09-19 night, headless, clean `dfd1c13`) — OWNER DECISION NEEDED before the fix
**Root cause:** on settled slide 2 the player paints the WHOLE slide with one stage-wide WebGL canvas (`#0-canvas`,
child of `#stage`); the only DOM layer tree (`#layer30`) is at computed `opacity: 0` from settle to at least +14 s.
`findMovieCanvas` matches the poster canvas inside that hidden tree, so the remounted decoder (elId 1) is mounted
where nothing can paint: `checkVisibility()` false, ancestor-opacity product 0, while its decoder is live
(151→169 frames in 600 ms, rVFC firing). Not a stacking problem: hiding the poster canvas, a max z-index and a
translateZ bump are all measured no-ops (the poster the viewer sees is WebGL). `elementsFromPoint` is useless as a
paint oracle (it never returns the video, even on slide 3 where it is plainly visible). Slide 3 is healthy (no WebGL
canvas, layer tree opacity 1, full grating visible, green square correctly in front). Poster canvas ids are reused
across scenes, so `findMovieCanvas` silently re-targets a different tree at each boundary. The stray small copy is
an independent defect (modulo footprint fallback), not the cause.
**What works:** mounting the decoder at stage/body level at its footprint shows the full 952×268 movie — and paints
it OVER the lower-left of the slide's green square, i.e. P2 Finding 2 ("green square in front of the movie") goes
RED on slide 2. So fix (a2) and (a3) are dead; (a1) works with that trade.
**Decision D3 (owner):** on a Magic-Move-settled slide that the player composites in WebGL, a DOM `<video>` can only
be in front of everything or invisible.
 (a) accept "movie in front of later-authored artwork on such slides" (visible-target test = `checkVisibility` +
     ancestor-opacity product, else body-level overlay); Finding 2 is then re-scoped to slides where the authored
     layer paints (slide 3) — simple, ships the visible carry, wrong z-order where artwork overlaps the movie;
 (b) restore z-order by feeding the live decoder INTO the player's WebGL texture for that movie (the canvas
     texture-feed approach P2 abandoned and I0 removed as dead code) — correct compositing, large and risky;
 (c) refuse: report `continuity: unsupported` for a boundary whose destination slide overlaps the movie with
     later-authored artwork, carry only where nothing overlaps (derivable from the export) — fail-closed, and
     combinable with (a) for the non-overlapping case.
 Recommendation: (c)+(a) — carry with a body-level overlay when no later-authored object overlaps the movie rect on
 the destination slide, refuse otherwise; keep (b) as research. The fixture's slide 2 then becomes a REFUSAL
 fixture, and a second fixture without the overlap is needed as the positive control.
Evidence (ignored): `output/live-visible-content/diag/` (12 screenshots, `diag.json`, `diag2.json`).

## 6. Owner decision 2026-09-20: BASELINE first, then the WebGL SPIKE
**Baseline = D3 (c)+(a) + mask refusal** (fail-closed; small):
1. `derive_plan` refusals (⇒ `continuity: unsupported` + reason, raw player): (i) on a continuing boundary's
   DESTINATION slide, any later-authored object (higher z than the movie) whose rect intersects the movie rect
   ⇒ `artwork overlaps the carried movie`; (ii) a movie node carrying a shape mask (anything beyond its own
   bounds rect) ⇒ `masked movie`. How the export encodes a movie mask is UNMEASURED — the fixture has none
   (only the generic `masksToBounds` layer flag); needs an owner-authored fixture: one masked movie crossing a
   Magic Move. Until the encoding is known, refuse on any mask-like key rather than guess.
2. Runtime S5 per §3: visible-target remount (paint test = `checkVisibility({checkOpacity,checkVisibilityCSS})`
   AND ancestor-opacity product — NOT `elementsFromPoint`), else the stage/body-level overlay; retire the
   same-asset second instance by plan geometry in `stash()`; key the footprint fallback by movie, not modulo.
3. The current fixture's 1→2 becomes a REFUSAL fixture under (i) (green square + black box overlap the movie on
   slide 2). A positive control needs a deck whose destination slide has nothing over the movie — owner-authored
   (agents never touch Keynote). The allowlist signature changes with the plan ⇒ new entry + P2 injected plan.
4. S3: P2 Finding 1 gains `footprintFullyLive`; Finding 2 is re-scoped to slides where the authored layer paints.
5. Full re-qualification from the gate worktree (P2 ×3, host ×3 viewports incl. V/Voff), Codex review.

**Spike = D3 (b), time-boxed research in a disposable worktree, no product code, headless only.** Ordered questions,
stop at the first "no":
 Q1 Does the player keep a render loop while a Magic-Move-settled slide rests on the stage-wide WebGL canvas
    (`#0-canvas`)? Measure: wrap `WebGLRenderingContext.prototype.drawArrays/drawElements` + `requestAnimationFrame`
    and count calls per second at rest on slide 2 (+1 s … +14 s).
 Q2 If not: can a redraw be forced cleanly (a public player hook / re-dispatching the event that made it render)
    without replaying draw calls or reaching into minified internals per build? If only by internals ⇒ DEAD.
 Q3 Can the movie's texture be identified robustly (intercept `texImage2D` uploads: source element/size/poster
    asset) including two instances of one asset, and swapped per frame with `texImage2D(video)`; cost at
    2560×1440 with two movies; behaviour in OBS's CEF (Chrome 127).
 Success is scored by the existing visible-content gate (full rect live on slide 2) AND P2 Finding 2 (green square
 still in front). Payoff if it works: correct z-order, masks, opacity, and the player's own 3→4 motion/easing.

## 7. Spike result 2026-09-20 (headless, raw player and continuity on — identical WebGL numbers)
**Q1: the player does NOT render at rest.** `#0-canvas` (WebGL1) is created when the 1→2 Magic Move starts, draws
195–255 `drawElements`/s for ~2 s, then ZERO draw / clear / bind / upload calls for the 13 s the settled slide 2
rested; it just retains its last frame. It is gone again on slide 3. During the move the player makes exactly 6
`texImage2D` uploads in one burst, all from unnamed `HTMLCanvasElement` copies (big-movie poster = 960×276, small
instance = 671×195); it never uses an `HTMLVideoElement` as a texture source — there is no video-texture path.
**Q2: no clean forced redraw.** 9 triggers produced zero draw calls (window `resize`, the player's
`StageSizeDidChangeEvent`, `webkitfullscreenchange`, `visibilitychange`, `orientationchange`, `scroll`, a style touch,
and a REAL viewport resize via CDP and back); no player object or redraw hook is reachable from `window`.
Micro-experiment: `texImage2D(video)` into the movie's texture succeeds (GL error 0, state restored) and the screen
does not change — byte-identical screenshots. **Verdict: option (b) is DEAD at Q2** under the stop rule, unless the
owner wants the minified player opened per build, or its ~250 draw calls replayed (both previously ruled out).
Still true and useful: a settled Magic-Move slide is a STATIC image, so whatever sits over the movie there is static.
Unexplored idea for the owner, NOT started: keep the stage-level `<video>` overlay (baseline (a)) and lay a static
2D-canvas "occluder cut-out" over it — the pixels of the settled WebGL frame inside the movie rect that differ from
the poster the player uploaded (both are readable) — restoring opaque artwork-in-front without touching the player.
Translucent artwork and anything animated by a later build would not be reproduced. It would turn the baseline's
overlap REFUSAL into a carry for the common opaque case; needs its own plan and gate (visible-content + Finding 2).
Evidence (ignored): `output/live-visible-content/spike/`.
