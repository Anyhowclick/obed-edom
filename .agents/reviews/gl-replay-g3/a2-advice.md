# GL-replay G3: advice on A2 and on the gate-6 frozen frame

Advisor: Opus, working read-only. No headless Chrome was run. Every claim below comes from code or from saved artifacts.
- Core line cites are `live_continuity_js.py` at `2884e116`. The worktree copy is being edited by other agents, so I cite `git show HEAD:`.
- G2 line cites are `live_gl_replay_js.py` at `2884e116`, which has the same bytes as the pinned `985afeb1`.
- Pixel numbers were sampled from `output/live-visible-content/g3/r1/*/*.png` (1920×1080, s = 1) with PIL.

## TL;DR

**A2: take (a), plus one guard (G). Neither (a) alone nor (b) is enough.**
- **(a) fixes three A2 symptoms**: the build-3 size snap, the #5 misregistration against the poster/frame, and the ≈4 px later-build pops. What remains is a ≤ 0.35 px transient.
- **Why (a) works (root cause).** At the hand-off, `tryRemount` starts a `keepAtFootprint` rAF loop. That loop never stops before hash 6, and it pulls every later placement back to the hand-off origin (:843-873, :1420). Today that origin is G2's slot. Under (a) it is the authored instance.
- **(a) does NOT fix the top-z stage append.** That append does not happen in the #5 dwell. It happens in the **2→3 transition window**: the advance from #5, 16296→18267 ms, with the hash still `#5`. There, `findMovieCanvas` never finds a canvas. This needs guard G: in `released`, the memo and its facade never take the stage append.
- **The build-1 cost of (a) is precise.** All four movie edges move inward by 4.19–4.23 px, and the outer ≈2 px of the movie's authored 4 px white frame reappears on all sides.
- **Today's hand-off is not geometry-clean either.** `object-fit: contain` in the 960×276 box letterboxes the video by 3.0 px top and bottom. So the true increment of (a) over today is +4.2 px on each side edge and +1.2 px on the top and bottom edges.
- **What (a) buys.** It removes today's larger build-3 snap (right edge −8.5 px) and the permanent #5 misregistration. From build 1 onward the movie sits exactly where the control's own movie sits.
- (b) keeps the video 4.2 px outside the authored frame for the rest of slide 2. Parking is worse than both. (c) is right long-term, but it is a G2 v2 with a full G2 re-gate. Not now.

**Gate 6: this is a G2 bug, not a policy question. Fix it in G2 (F1 + F2); do not rule it acceptable.**
- **The "poster snapshot" is not the poster.** G2 takes it at ARM-POST (`posterOf`, :1045). By then, the per-clear uploads have redefined the poster texture as the 1920×540 video (`uploadInto` :335). So `restorePoster` "restores" the bottom-left 960×276 texels of the last video frame, which the slot shows at 2× magnification.
- **The red class is 10 arms, not 2.**
  - `sceneMismatch` and `posterAmbiguous` (twice each, with repeats) show the full frozen frame.
  - `canvasRemoved`, `contextLost`, `frameLengthChanged`, `glError`, `occlusionTooHigh` and `posterUnreadable` (hash `#1`), plus late `glError` and late `frameLengthChanged` (P2d), all show the 2× crop.
  - The crop hides the counter patch. That is the only reason these arms read "counter None" and passed.
  - Inside the movie rect, max\|Δ\| against the control is 249–252 for 0.79 of the pixels. Control against control is 0.
- **D4 allows only the notes stream to differ**, so this fails D4.
- **Product exposure.** Any real LIVE-phase failure (OD-1 → retire) puts a zoomed crop of the movie on air for the rest of the slide-2 dwell. That dwell is unbounded: it lasts until the operator clicks.

## Evidence

| # | Fact | Kind | Source |
|---|---|---|---|
| E1 | The movie has an authored ≈4 px white frame centred on the instance edge. On the control poster at 1920×1080: left x106 = 38 (anti-aliased edge pixel), x107–110 = 255, x111 = 231; right x1058 = 192, x1059–1062 = 255, x1063 = 101; top y792 = 119, y793–796 = 255; bottom y1061–1064 = 255, y1065 = 40. Outside it is black (0). The pad (slot − instance, 4.19–4.23 px per edge) holds the frame's outer ≈2 px plus anti-aliasing. It is not a blank pad. | measured | `control/P2c-live-stable.png`, rows y = 930/1030, column x = 300 |
| E2 | GL LIVE draws the whole video frame across the full slot: content spans x 105→1064 and y 791→1066, and there is no white pixel in the ring. Mechanism: `texImage2D(video)` redefines the texture at 1920×540 (:335). The player's quad maps the full texture onto `slotRects[3]`, which G2 proves via the MVP decode. Scale is x 0.5000, y 0.5111, a 2.2 % vertical stretch. | measured + code | `armed-2/P2c-live-stable.png`; G2 :325-341, :731-738 |
| E3 | Today's hand-off DOM uses the slot box with `object-fit: contain`. Content is 960×270 at y 793.85–1063.85. The 3 px letterbox bars show the poster canvas: y792 = 119, y793 = 255, video from y794; bottom video to y1063, then y1064 = 255, y1065 = 40. Left/right content starts at x105, with no frame. | measured | `armed-2/P3-after-build1.png` |
| E4 | The hand-off `tryRemount` starts `keepAtFootprint(v, box.x, box.y)` (:1420). The `__obedPinning` guard (:844) turns every later call into a no-op. The loop stops only when the memo is retired, ended or detached at a rAF (:847), or at hash ≥ 6 (:851). Every build re-inserts the memo synchronously inside the MutationObserver callback (:815), so the loop survives. Every later placement converges back to the slot origin: 105.109…/790.85… at 11711, 14514, 15414 and 16497 ms; 87.59/709.05 at the letterboxed viewport. | code + measured | `armed-2`, `armed-lb` `coreEvents` |
| E5 | After a subtree detach, `captureLayout` finds zero boxes and falls back to the element's style: {x: `pr.left‖0` = 0, y: 0, w/h from the style} (:1582-1596). The zero origin sends `tryRemount` to the footprint fallback (:1348-1371). There, x/y come from the plan footprint (int {109, 795}, picked by `fps[(elId−1) % n]` at :1365) and w/h come from the style (960×276 today). | code + measured | `armed-2` 11659.9 `remount-footprint-rect {109,795,960,276}` |
| E6 | Build 3 (#4→#5): the player creates elId 3 at 15016. `reuse-decoder` copies its instance-size style onto elId 1 (:1767-1771), and the facade is bound (:1772). From here the size is 951.53×267.61 while the loop holds the origin at the slot (E4): the T5 state is {105.13, 790.85, 951.53, 267.61}. | measured | `armed-2` `states["tail#5"]` |
| E7 | At #5 the DOM draws the white frame **above** the video. armed-2 T5: x105 = video, x107–110 = 255, then video. A video sliver shows left of the frame and above it (y791–792). At the right, x1055–1056 = video, then the poster's own content at x1057, then the frame. The control's own element at T5 sits at exactly {109.3517, 795.0362, 951.53, 267.61}. | measured | `armed-2/T5-tail.png`; `control` `states["tail#5"]` |
| E8 | The 20 `remount-done` notes start 164 ms **after** the T5 shot (16132.7 → 16296.6). They run until hash `#6` at 18267, which is the 2→3 transition. No shot samples this window. `findMovieCanvas` returned null on the synchronous attempt and on every timer. | measured | `armed-2` `shots` / `coreEvents` |
| E9 | The note `rect` is `__obedRect`, which only the 200 ms interval refreshes. It is not the rendered box. The loop (E4) corrects the rendered box in the next rAF, before paint. A2's "≈50 ms pop" is therefore an upper bound from note spacing; the real pop is 0–1 frame. That is not measured at frame resolution. | code | :843-873, :1604-1606 |
| E10 | Build 1 changes 165,722 px outside the slot in the control, in bbox (542, 625)–(1561, 985). That overlaps the movie's top-right; its left and bottom edges are far from it. Release runs synchronously in G2's MutationObserver callback (G2 :871 → core :676), so no frame is painted between the DOM swap and the remount. | measured + code | control P2c vs P3 diff |
| E11 | **Ring instrument**: the slot rect minus the instance dilated by 1 px, minus slot 4 (6,729 px). Null: control-2 and control-rep vs control give max\|Δ\| = 0 at P2c/P3/P4/T4/T5. Armed/armed-2 vs control, count of pixels > 8: P3 964/718, P4 718/725, T4 718/718, T5 1240/787, P2c 4992/5163 (LIVE stretch, by design). This makes it a RED-first check for A2. | measured | scratch script over r1 PNGs |
| E12 | G2 gate-6 mechanism. In ARM-PRE, every player `clear` triggers `perClearUpload` → `uploadInto(posterTex, video)` (:298, :403-410). ARM-POST then snapshots with `posterOf(posterTex, 960×276)` (:1045), which is `readPixels(0, 0, 960, 276)` on the 1920×540 video texture (:374). `restorePoster` (:384-401) writes that crop back. Forced `sceneMismatch` fires in `poll` (:1144) before `armPost`, so `state.poster` and `state.frame` are both null: restore is a no-op (:386) and there is no replay (:855). The canvas keeps the last move frame. Forced `posterAmbiguous` (:1044) has `state.frame` but no poster, so it replays the frozen texture. | code | G2 at `2884e116` |
| E13 | Gate-6 inside-movie-rect parity vs control, as max\|Δ\| / fraction of pixels > 8. P2c: `canvasRemoved`, `contextLost`, `frameLengthChanged`, `glError`, `occlusionTooHigh` and `posterUnreadable` are 249/0.79; `sceneMismatch`(-rep) and `posterAmbiguous`(-rep) are 252/0.79. P2d: late `glError` and late `frameLengthChanged` are 249/0.79; late `contextLost` is 251/0.98. The other 12 forced arms are 0/0.00. Visual check: the 249 arms show a stripe period 2× the live one with no counter patch, i.e. the bottom-left crop. The 252 arms show a full frame with the counter. The same result holds in G2 r5 (`g2/r5/fail-posterUnreadable` etc. 249/0.79). **P3/P4 are 0 for every arm** except `writebackFailed` and late `canvasRemoved`, which hand off. | measured | r1 and r5 PNGs; visual strip in scratch |

## A2: what the picture does, per option

The geometry and the frame state come from E1–E7. The (a), (b) and (c) rows are **predicted** from code and the E1/E3 pixels, not measured.

| Moment | Today (slot hand-off) | (a) instance hand-off + G | (b) slot, sticky ×3 | park (retire at build 1) | (c) G2 inner sub-rect + (a) |
|---|---|---|---|---|---|
| Move start → LIVE (#1→#2) | The movie grows 4.2 px per edge, is stretched 2.2 %, and loses its frame (R2) | same | same | same | no grow; frame's outer half kept |
| **Build 1** | top/bottom content 3.0 px inward; 1 px frame line appears top/bottom only; left/right unchanged | **all edges 4.19–4.23 px inward; the outer ≈2 px of the frame reappears on all four sides** | = today | live → **static poster** (as the control) | no change |
| Builds 2–3 (#3, #4) | 0–1 frame 4 px pop at each footprint fallback (E9) | ≤ 0.35 px transient (footprint ints vs instance floats) | none | poster | ≤ 0.35 px |
| Build 3 (#4→#5) | size snap: right edge −8.5 px, bottom −5.4 px, top 3 px up; then 4.2 px misregistered vs the DOM frame (slivers, double edge) | the DOM frame appears over the video's edge, as authored; geometry unchanged | video extends 4.2 px outside the frame left/right; letterbox bars top/bottom | **restart from 0** (control behaviour) | = (a) |
| #5 dwell | misregistered (E6/E7) | = control geometry (E7) | misregistered by 4.2 px/edge | restarted movie | = (a) |
| 2→3 transition (hash `#5`) | memo + stub appended top-z for ≈2 s, at full opacity over the transition and over the green square; they vanish at `#6` | **not painted by us** (G); `glreplay-hold {via:'stage'}` | top-z (same as today) unless G is added | n/a | = (a) |
| Code risk | — | 2 small edits behind `GL && zone === 'released'` | 3 special cases (stash, tryRemount, reuse) | trivial | G2 compositor (2D canvas per frame), unmeasured in CEF |
| Re-gate | — | G-P2; gates 4 ×2, 4b; gate-6 `writebackFailed`; the new tail checks | same | gates 4/4b/6 | the whole G2 suite + Q3 + a CEF perf check |

**What "shrink at build 1" is under (a), frame by frame.**
- **Last GL frame.** Video content fills 105.12–1065.12 × 790.85–1066.85, with no frame (E2).
- **First DOM frame.** This is the same task as the DOM swap (E10). The `<video>` fills 109.35–1060.89 × 795.04–1062.66, and its aspect matches the video's (3.5556), so there are no bars.
  - Between the edge of the `<video>` and the slot edge, the viewer sees the poster canvas's ring: black (0), anti-aliasing (38), then ≈2.35 px of white on each side. This is the control's P3 ring, pixel for pixel, except the 1-px column the video partly covers.
  - The frame's inner half lies under the video until build 3, where the DOM draws it on top (E7).
- **Is it masked?** Partly. It lands in the same composited frame as build 1, which is a 165k-px change overlapping the movie's top-right (E10). The left and bottom edges are not near that change.
- **Size of the move.** It is 0.9 % of the movie's width, and it is the movie settling into its authored frame. That is smaller than today's build-3 snap (8.5 px), and it happens once.

## A2: every listed symptom traced under (a)

1. **Footprint fallback at #3 and #4 (E5).** It still fires, and the notes remain. The box becomes (109, 795) plus the style size 951.54×267.62, which is −0.35/−0.04 px from the instance. On the next rAF, the hand-off loop, now targeting the instance origin, pulls it to the exact instance (E4). The residual is ≤ 0.35 px for ≤ 1 frame. At the letterboxed viewport it is 0.29 px.
2. **Reuse style copy at build 3 (E6).** It copies the player's style: w/h 951.543×267.621 in authored px, the same size the memo already has. There is no size change. `dom-swap` puts the memo in the player's own slot, and the loop target is that same origin.
3. **Carried rect at #5.** This becomes toScreen(instanceRect), which equals the control's element and the DOM frame (E7). Fixed.
4. **Top-z append (E8).** **Not fixed by (a).** Both `fp` and the style give a box that `findMovieCanvas` cannot match during the transition, so the memo and stub go to `#body`, as today. Guard G is needed.

The residual dependence: (1) relies on the plan footprint being the rounded instance, which holds under pin, and on the hand-off loop surviving. The loop is an existing behaviour, not a new mechanism. See risk R-a1.

## Recommendation for A2: (a) + G

Change list (`src/obed_edom/live_continuity_js.py`, cites at `2884e116`):
1. **`releaseArmed`** :665-672.
   - Set `const screen = toScreen(GL.instanceRect, map);`.
   - Use `screen` both for the row-9 pre-check `findMovieCanvas(screen, v)` and for `v.__obedRect = screen`.
   - G2's `rect` stays an input that is validated only: row 7's containment test in `handbackRectOk` is unchanged, and it still proves G2 means this instance.
2. **`handbackRectOk`** :599. Run the near-origin tests on the box `tryRemount` will actually use: `const s = toScreen(GL.instanceRect, map);`.
3. **Guard G**, in `tryRemount` immediately before the stage append (:1435):
   ```js
   if (GL && zone === 'released' && carriedMemo && (v === carriedMemo || v.__obedFacadeFor === carriedMemo)) {
     noteHold(v, remountSrc, 'stage');
     return;
   }
   ```
   With G, the memo stays detached (and keep-warm), and `retire-on-start-movie` at `#6` retires it as it does today. Pin for any other decoder is unchanged.
4. **Tests** (`tests/test_live_continuity_js.py`), RED against `2884e116` first:
   - (i) release lands with `__obedRect == toScreen(instanceRect)` and style w/h == instance w/h, at s = 1 and at s = 0.8333/oy 50;
   - (ii) after the hand-off, a subtree detach with no matching canvas leaves the memo, and a facade stub bound to it, out of `#body`, with `glreplay-hold {via:'stage'}`;
   - (iii) a non-memo decoder under ordinary pin still reaches `remount-done`.

   G3's own hand-off tests that assert the slot rect move with this change. They are new in `e59927e4`, not pre-existing.
5. **Plan** (`keynote_live_gl_replay_g3g4.plan.md`):
   - §2 row 10: "`v.__obedRect = toScreen(instanceRect)`; G2's rect is validated, not used for placement".
   - R2: resolved at build 1. The LIVE-phase stretch remains until (c).
   - R3: the footprint fallback still fires, with a ≤ 0.35 px residual; the loop reliance is documented.
   - New R9: the 2→3 transition window, handled by G.
   - F9: note that the ≈4 px pop was really held by the stale loop.

**Optional hardening (b1)**, one line: at `stash` :754-756, `} else if (!(GL && zone === 'released' && v === carriedMemo)) { captureLayout(v); }`.
- The memo then keeps its last attached `__obedRect`, so the footprint fallback, and its elId-parity footprint pick (:1365), become unreachable for it.
- Take it if you want the tail check to demand zero `remount-footprint-rect`. Without it, that count stays report-only.

**Gating tail check**, added to gate 4 (n = 2) and 4b, in `g3/analyse_g3.py`:
- **T-geom.** At P3, P4, T4 and T5, the memo's `getBoundingClientRect()` is within 0.5 screen px of `toScreen(instanceRect)`.
- **T-ring.** At P3, P4, T4 and T5, max\|Δ\| over the ring (E11) armed vs control is ≤ 2. It is RED on r1 (718–1240 px > 8) and 0 on the null control. At 4b the ring is computed via `toScreen`.
- **T-topz.** From the hand-off to hash `#6`, there are 0 `remount-done` notes for the memo's elId or its facade.
- **T-transition.** Take a new state sample at about +300 ms and about +1200 ms after the #5 advance, before `#6`. The memo is `inDoc: false`. Screenshot parity in this window is report-only, because it is timing-fragile.
- **Report-only.** P2c ring (LIVE stretch), `remount-footprint-rect` count (gating only with b1), and the counter burst across build 1 (unchanged).

## Gate 6: root cause and recommendation

**Is it acceptable against D4?** No.
- D4 (arming §5 and §8, accepted 2026-09-21) says the fail-closed arm's artifacts equal the retire artifacts, and only the notes may differ.
- Ten arms show a non-poster image in the movie rect for the whole pre-build dwell (E13).
- The gate's "counter None" proxy for "shows the poster" is unsound: the crop has no counter patch.
- The G2 design says what should happen: "poster snapshot via FBO" (G2 plan §2.3) and "restore the poster" (§2.5 step 3). The code does not do this (E12), so this is a defect rather than a policy question.

**Fix in G2 (`src/obed_edom/live_gl_replay_js.py`).** F1 and F2 are small and independent.
- **F1: snapshot before the first overwrite.** In `perClearUpload` (:403-410), before `uploadInto`:
  ```js
  if (!state.poster){
    state.poster = posterOf(state.posterTex, {w: ENTRY.slotSizes[MOVIE_SLOT][0], h: ENTRY.slotSizes[MOVIE_SLOT][1],
      intFmt: state.posterUpload.intFmt, extFmt: state.posterUpload.extFmt, type: state.posterUpload.type});
    if (!assertOr('posterUnreadable', state.poster.complete, null)) return;
  }
  ```
  - Delete the ARM-POST re-snapshot and its assert (:1045-1047). This keeps "one emitting site per reason".
  - The texture then still holds the player's poster, because `state.posterTex` is set at the player's poster upload (:266) and nothing has written to it since.
  - `restorePoster` already writes texels back with flipY/premul off. Since the snapshot is the stored texels, the restore is byte-exact.
  - F1 alone fixes 8 of the 10 arms: the six crop arms, the two late arms, and `posterAmbiguous`, which already has `state.frame`.
- **F2: repaint after a settle-time stand-down with no recorded frame (`sceneMismatch`).**
  - Factor out `armPost`'s frame choice (:1033-1039, segment if delimited, else retained within `SETTLE_QUIET_TICKS`) into `settledSegment()`.
  - In `standDown` (:852-857), replay `state.frame || (state.readyAt != null ? settledSegment() : null)` with `{rest: true}`. The same exclusions apply (lost, `canvasRemoved`, `unflaggedPlayerCall`, disconnected canvas).
  - A mid-move stand-down needs no replay: the player keeps drawing, and after F1 it draws from the restored poster.
- **Do not delay the per-clear upload.** It is the feature (the movie plays through the move). The defect is only the snapshot's timing and the missing repaint.
- **Tests** (`tests/test_live_gl_replay_js.py`), RED first:
  - the fake GL's `texImage2D(source)` must redefine the bound texture's level-0 size and content to the source's (1920×540 distinguishable pixels) — today's fake cannot show E12;
  - `restorePoster` then yields the player's poster bytes, not video bytes;
  - forced `sceneMismatch` at settle → poster restored AND the last segment replayed;
  - forced `posterAmbiguous` → poster restored;
  - a stand-down mid-move → restore without replay.
  - Re-pin `PINNED_JS_SHA256` (`tests/test_live_gl_replay_js.py:140`).
- **Gate-6 criterion** (G3 harness). Add inside-movie-rect parity vs control, max\|Δ\| ≤ 2: at P2c for the hash-`#1` arms, at P2d for the late arms. On r1 it reads 249–252 for the 10 arms, 0 for the other 12 and for control vs control.
  - **Late `contextLost` stays different by design.** A forced `contextLost` with a live context skips all GL work (G2 :816-818, :849). Change that arm to force a real `WEBGL_lose_context.loseContext()`, or rule it report-only at P2d. Q3 already covers the real loss.
- **Re-gate cost.**
  - Moving the G2 sha changes the G3 plan's "985afeb1 must not move" rule. That is an owner call: either a separate G2 commit in this integration PR, or a G2.1 PR first.
  - Headless re-runs: gate 1, gate 2 (the opacity proofs now run over the true poster instead of the crop; expect `opacityUnproven []`, and report `posterOf` time on the first move frame, one 1.06 MB `readPixels`, with a first-move-frame clear-gap check), gate 4/4b, and gate 6 with all 20 arms plus the 4 late arms.
  - G-P2 is unaffected (no module in P2). Q3 is only affected by the snapshot timing, so it is optional.
- **If you do not want G2 to move now:** the alternative is a written ruling. It would say: known D4 deviation; `gl_replay` stays default-off (D5); fix in G2.1 before any `auto` default. The gate-6 table in `gates-r1.md` must then list all 10 arms, not 2.

## Open risks

- **R-a1.** Under (a), the zero residual at later builds depends on two things: the plan footprint being the rounded instance, and the hand-off `keepAtFootprint` loop surviving each build (E4).
  - The fallback's footprint pick is by elId parity (:1365). On a plan with several movies, it could pick another movie's footprint for ≤ 1 frame before the loop pulls it back.
  - Only single-movie data exists. (b1) removes this dependency.
- **R-a2.** The build-1 inward move (E-row "Build 1") is predicted, not captured. The burst shots across build 1 are not saved as PNGs. Saving B00–B09 would measure it.
- **R-a3.** The GL LIVE geometry (grow and stretch, no frame; R2) is unchanged by (a). Only (c) fixes it.
- **R-a4.** In the 2→3 transition with G, armed has a media-less facade stub where the control had the player's own element. Both are detached at the transition start (E8, control has no notes there), so parity is expected but unmeasured. T-transition samples it.
- **R-g1.** F1 moves a 1.06 MB `readPixels` into the first frame of the Magic Move. A frame hitch is possible but unmeasured; gate 2 must report it.
- **R-g2.** A real `frameNotDelimited` at ARM-POST (no delimited frame) still cannot repaint. F1 restores the texture, but the idle player never redraws, so a still of the movie remains until build 1. This is residual and documented.
- **Corrections to A2 / gates-r1.**
  - The top-z append is in the 2→3 transition window, not "the whole of scene 5" (E8).
  - The #3/#4 pop is 0–1 frame, not ≈50 ms (E9).
  - The build-3 snap happens at build 3, not mid-dwell.
  - Today's hand-off already has the 3 px vertical letterbox change (E3).
  - Gate 6 is red for 10 arms, not 2 (E13).
