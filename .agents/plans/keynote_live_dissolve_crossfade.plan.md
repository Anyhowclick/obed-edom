# Dissolve and cut over fill-less slides: a true cross-fade, a clean cut, and movies that freeze and fade

**rev 17 — decision 15 (split: Chrome host only in this PR), for owner review**, 2026-10-12. Rev 1: Opus planner (`8e572864`). Critique r1–r7: GPT-6 Astra
high via Codex (not Opus; owner 2026-10-11), 12 + 7 + 11 + 7 + 6 + 4 + 3 findings, all folded (§14). Revs 2–9: Opus planner
(`cd289a05`, `f3bd8b55`, `4ffcd8ad`, `e5c644bb`, `218308c3`, `cacfe9fb`, `d299b549`, rev 9 = owner GO 2026-10-11 22:10, W1–W4
implemented on this branch up to `fbe105e0`). Rev 10: Opus planner, after Q0b's five re-plan triggers, the Astra xhigh advisory
(`.agents/reviews/dissolve-crossfade/replan-astra-xhigh.md`) and owner decisions 8–11 (2026-10-12, §12); rev 10 = `891e4f40`. Rev 11:
Opus planner, folding GPT-6 Astra r8 on rev 10 (9 findings, CHANGES REQUIRED; §14) and decision 12 (made, then reversed the
same day; §12); rev 11 = `b4ff2576`. Rev 12: Opus planner, folding GPT-6 Astra r9 on rev 11 (3 false admissions + 1 wording;
§14). Rev 13: Opus planner, adopting the hi-DPI investigation's fix A (owner decision 12, resolved ~11:45; §12); rev 13 = `54000459`.
Rev 14: Opus planner, folding GPT-6 Astra r11 (geometry coverage matrix, `m-snap-frac` anchor; plan-only, §3.1 unchanged);
rev 14 = `75a6d4ff`. Rev 15: Opus planner, after Q0b-bis (`q0bbis-2026-10-12/`) found CEF 127 does not snap the video quad, the
CEF investigation (`cef-frac-2026-10-12/`) and owner decision 13 (~14:10; §12); rev 15 = `95c55e45`. Rev 16: Opus planner, folding
GPT-6 Astra r12 (6 findings) and owner decision 14 (~14:30: raw export and Build Preview no longer freeze); rev 16 = `41ef609b`.
Rev 17: Opus planner, owner decision 15 (~15:00): this PR freezes only on the Chrome host; CEF/OBS skips; the probe is a
follow-up PR (§13.1). Owner decisions 1–7 in §12. Plan only: no product code, no commits, no OBS, no Keynote. Base: `main` @ `1589d096`.
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; among the listed anchors only R8, D4 and the hook `_ANCHOR` move,
each by 38). Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored); scratch `x` =
its `plan-2026-10-11/planner/x`; Q0b = its `q0b-2026-10-11/`; rev-10 prototypes = its `plan-rev10-2026-10-12/`, rev-11 / 12 / 13 / 15 / 16 / 17 Node evidence = its `plan-rev1{1,2,3,5,6,7}-2026-10-12/`; hi-DPI investigation = its `hidpi-2026-10-12/`; Q0b-bis = its `q0bbis-2026-10-12/`; CEF investigation = its `cef-frac-2026-10-12/` (§8). Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins),
`keynote_live_handback_geometry.plan.md` (R6–R8), `keynote_live_paint_oracle.plan.md` (oracle stays stock).

## 0. Summary

- **Root cause (player, not host).** Keynote exports a slide transition as two flattened full-slide textures: the incoming at
  the bottom with **no animation**, the outgoing on top animated away (Dissolve: `opacity 1→0`; `none` cut: `hidden` over 1 ms).
  Keynote's own exports hide the incoming under a black fill; without it (the real DSK case, §1.3) the incoming shows at full
  strength under the outgoing: the Dissolve pops in; the cut shows both slides at once (§1.5).
- **Cross-fade and cut (D1, D2: commit before construct).** For a tree of exactly the Dissolve or cut shape, one method
  commits before the player builds anything and returns a **copy**: a Dissolve gets two read-back rules (`#layer<c>{isolation:
  isolate}`, `#layer<in>,#layer<out>{mix-blend-mode:plus-lighter}` on the ids about to be allocated) and an incoming leaf at
  opacity 0 with the mirror `0→1`; a cut (exported timing only) an incoming leaf starting hidden with the mirror. Any failure →
  stock. Result: premultiplied `(1−e)·P_out + e·P_in`; a cut that swaps within its 1 ms, never both at full strength.
- **Movie freeze (D4 takes, D3 attaches; add-only).** Owner: "in Keynote the vid stops playing and dissolves out". The player
  deletes the playing `<video>` as the transition starts, so the movie jumps back to the **opening frame** baked into the
  outgoing texture (§1.4). D4 requires every element inside the stage (and its ancestors) to be a supported, box-confined
  paint family and every other element to be either that or **provably clipped away from the visible stage** (**paint gate**,
  decision 8), snapshots each `<video>` whose chain is inside a **positive allowlist of the computed styles the player
  generates** (§3.2) onto the **device pixels of the box Chromium paints it at** (decision 9) — only on the geometry where
  that is measured (DPR 1, 1.5 or 2 at stage scale 1, base-layer box = slide, translation-only transforms; decision 12), with
  the snapped placement **granted by the host only on a Chrome it launched whose engine is qualified** (Chrome 154, GPU
  compositing; decision 15) — managed OBS/CEF, raw export and Build Preview keep today's jump (decisions 14–15; the CEF placement
  probe is a follow-up PR, §13.1) — with every backing pixel proven
  opaque, untoned (**identity `L`**, decision 10: the GPU mid-tone step is a known limit), redraws overlying canvases (Q7);
  D3 puts it in the outgoing fading wrapper, or discards it. The `<video>` is never touched; anything outside keeps today's
  look.
- **Not in this patch (owner Q6):** main's bridge keeps P2's slide-4 decoder at full strength over the terminal fade, stock and
  patched alike; stopping it and S2's hold at the outgoing transition start is a separate follow-up PR after S2 merges.
- **Measured** (headless Chrome 154, §8): cross-fade residual ≤ 1.5 LSB; nulls pop in (205–206); KB dips to α 191; opaque
  on/off ≤ 1.51; cut: stock shows both slides, patched never; freeze: index = last presented. Q0b on rev 9 raised five
  re-plan triggers; rev 10's prototypes answer them: the raw export page passes the gate (P2 2→3 and 4→end; F3 is later limited to host pages,
  decision 14), an overflowing
  off-viewport caption or an open navigator skips; holder vs the live movie, browser-rendered, ≤ 3 LSB after the documented
  tone step at 1920×1080 and letterboxed (rev 9: 78); the hi-DPI investigation's fix A (snap on the stage-local 1/DPR grid)
  brings DSF 1.5, DSF 2 and fractional letterbox origins to the same floor on the real P2 page, while scaled stages
  (2560×1440, 1280×720) and nested scales still miss and skip the take (decision 12). Q0b-bis on the rev-13 bytes: engagement
  PASS on host and raw pages (every negative refused); takes ≤ 18.3 ms headless (DSK 7→8 at DSF 2 included) and ≤ 34.8 ms in
  CEF (budget 50); the 18-cell DPR × origin × clip matrix PASS under a real `--force-device-scale-factor`. **The trigger:** OBS's
  CEF 127 does not snap the video quad (it draws at x 109.352), so snapped holders miss by up to 183 LSB there; a fractional
  draw over a snapped underlay reads 2 / 0 % in CEF but 183 in Chrome 154 — no single rule fits both engines, and no in-page
  test tells them apart. Decision 13 chose a host-side startup probe; decision 15 splits it out: this PR grants the snapped rule
  only on the host-launched, qualified Chrome (§3.3), and the probe follows (§13.1).
- **Switch:** `mm_opacity` (`OBED_LIVE_MM_OPACITY=off` restores today's bytes); every output; `RUNTIME_VERSION` stays 2.

## 1. Facts (code-read on both players; every anchor count-checked)

### 1.1 How the player draws a slide transition

| Step | Where (byte, both players unless split) | What |
|---|---|---|
| GL vs CSS | `jC` @2368216 / @2368254; routing `qC&&-1!==jC.indexOf(C.name)` @2312807 (`PB.renderEffects`) and @2314108 (`PB.renderEffect`, per-object builds) | `apple:dissolve` and `none` are not in `jC`: the CSS renderer `NB` (@2292342) draws them. |
| Build | `PB.renderEffects` @2311803; `const A=new VB(C.baseLayer,…)` @2312557 … `this.cssRenderer.draw(a),a.removeChild(w)}` @2313053 | `yB` keeps the export's `baseLayer` by reference (@2270532). `VB` allocates `layerId=TB,TB+=1` (`let TB=0` @2270526, same module scope as `PB`) pre-order: root, container, incoming, outgoing = TB … TB+3 (proved, §8). `WB` creates keyframe rules during construction. `NB.draw` builds `layer<id>` divs (a `layer<id>-opacity` wrapper per animated opacity; a `hidden` animation runs on the layer itself). The DOM it replaces (`w`, drawn by `displayScene` with no live `<video>`: §1.4) is removed in the same task. |
| Keyframes | `WB` @2271556; `EaseInEaseOut` → `ease-in-out` @2282229; `WB.createAnimationRuleForKeyframe` (≈@2283770) turns `hidden` into **opacity** keyframes 1/0, interpolated over the duration | rules live in the animation manager's own `<style media="screen">` |
| Animate | `PB.playCurrentScene` @2356281 / @2356319: `renderEffects()` then `setTimeout(()=>{…animateEffects…},1e3*g)` (`},1e3*g)` @2357455 / @2357493) | Render and animate are separate tasks; `applyCssAnimation` @2303763 sets visibility and starts every layer's animation in one loop. |
| Cleanup | `displayScene` @2354643 / @2354681 → `deleteAllAnimations()` @1953106 + `removeEvent` @2291872 | at the next scene or any go-to; at the end of the show (`currentSceneDidComplete` @2357464 / @2357502) the held endpoint keeps its DOM and rules until navigation. |
| Live slide DOM (read; confirmed on the real P2 DOM, §8) | page CSS (`body{overflow:hidden;margin:0}`, `div#stageArea{position:absolute;visibility:hidden;overflow:hidden}`, `div.stage{position:absolute;overflow:visible}`); Chromium UA (`video, canvas, img {overflow: clip}`); `Cg.adjustStageToFit`; `NB.draw`/`addNode`/`addAnimationNode`; `xB.initVideo`; `hideMoviePoster` | `body` has a zero-height box (every child is absolute) and its `overflow` propagates to the viewport. `#stage`: `scaleX(g) scaleY(B)` about its centre, `transform-style: preserve-3d`. Scene root and every layer: an absolute div sized to its bounds, `-webkit-transform: matrix(…)` about the anchor, `transform-style: flat`, opacity/visibility on the div, `overflow: hidden` for `masksToBounds`. Textures: absolute `<canvas>` with `translateZ(0px)`. A playing movie: the scene's own video-layer div is hidden and the movie's div from its `renderMovie` build is appended last to that layer's parent (`M.parentNode.appendChild(L.movieDiv)`): `layerN` (flat) → seven build wrappers `layerN-{opacity, position, transform-rotation-z, transform-scale-x, transform-scale-y, bounds, contents}` (`preserve-3d`, no transform) → `layerM` (flat) → the absolute `<video>` (UA `object-fit: contain`, `overflow: clip`); frame textures of the build sit beside `layerM`; the poster canvas is removed once it plays. |
| Page chrome outside the stage (read; measured §8) | `index.html` (`#body` > `#stageArea` > `#stage`, then `#slideshowNavigator`, `#slideNumberControl`, `#slideNumberDisplay`, `#helpPlacard`, `#waitingIndicator`); player CSS | `#slideshowNavigator`: absolute, `overflow: hidden`, transparent, `left: 0`, 140 px wide. Its `.navigatorThumbnailSidebar` (absolute, overflow hidden, `left: −140px`, 129 px + 1 px border, `left` transitions to 0 when opened) holds the thumbnail `img`s, shadowed frames and number text — the 12 elements that failed rev 9's whole-page gate on the raw page. The host page sets `#slideshowNavigator{display:none!important}`. |
| Where Chromium paints a movie (measured fit, §8; not a universal model) | Blink pixel snapping (`video_painter.cc` snaps the local replaced rect plus paint offset) | At stage scale 1 with translation-only scene transforms the live picture is a bilinear draw of the frame into the content box with every edge rounded on the stage-local device grid (1/DPR CSS px; at DSF 1 the CSS grid): P2 slide 2 `[109.35, 795.04, 951.53, 267.61]` paints at `[109, 795, 952, 268]` (fit mean 0.16 LSB after the tone step; the fractional box: max 179). At DSF 2 a row fit (x only) puts the origin on the device grid (x 219). The hi-DPI investigation (§8.5) located it: Chromium lays out zoomed by the DSF, so Blink's LayoutUnits are device px and `VideoPainter` snaps the movie's foreign layer on the stage-local **device** grid (1/DPR CSS px); the holder canvas is its own composited layer and lands 1:1. At stage scale ≠ 1 the movie's device quad follows a chain-dependent rounding that no measured model reproduces on the real P2 chain; nested scales defeat the screen-space `contain` solve. **OBS's CEF 127 does not snap** (Q0b-bis, §8.6): its video quad sits at the content box's fractional origin (x 109.352, bilinear), and its size is the local pre-snapped size; Chrome 154 snaps. A page cannot tell them apart; composited pixels can. |

### 1.2 The export data (every transition on disk)

Census over the 25 export roots under `output/fixtures` (`census.py`): **42 `apple:dissolve`**, **8 `none` cuts** (D1–D6), all
root → one plain container → two textured leaves (identity geometry, no flags); incoming without animation; outgoing with one
(Dissolve: `opacity` 1→0, `EaseInEaseOut`, `fillMode both`, 1.5 / 1.0 s; cut: `hidden` false→true, `duration` 0.001, `beginTime`
0, `fillMode both`, no `timingFunction`, `timeOffset`/`repeatCount` 0, no autoreverse); 67 Magic Moves (GL), 382 per-object
builds. P2 2→3 = slide `0C652BEB` event 3; D2 is the only D deck with a Dissolve (overlap only); `minimal-alpha-dsk-17c0c938`
is the 17c0c938 pop-in deck (5→6); every on-disk cut ends its deck, onto the shared background `9B0DBE…` (empty stripped).

### 1.3 What the live presenter serves

`html_preview.export_html` is the only export path, served unmodified in screen mode (black page) and keyer mode (alpha page;
`live_host.py:418–436`); the product never strips (715cb3f1). **The trigger is a fill-less outgoing texture, not the page**:
Keynote's PDFs on a transparent page do not pop in; stripped PDFs on the black page do. DSK decks (the wall deck's transparent
layout, README :21; clip slides forced to dissolve, `dsk_assemble.py:2958–2968`, `:4204–4207`) are the real case (DX-3).

### 1.4 Movies at a transition start

- **The export bakes the opening frame** (DSK 7→8, `bake/bake.py`: best match frames 7 / 4; an advance 0.5–10 s in differs by
  MAD 10–70, floor ≈ 21). Keynote freezes the current frame (owner).
- **When it goes.** `jumpToScene` → (100 ms) `jumpToScene_partFour` @2353722 / @2353760 → `displayScene` (removes the live
  slide, `<video>` included) → `renderEffects`, one task (measured: no `<video>` left at `renderEffects`); so D4 runs first.
- **Who owns the playing `<video>`.** Raw player: slide 2's element in `w`. Main's core: that or a remounted decoder; its
  `MutationObserver` (`live_continuity_js.py:1750`) calls `stash` (`:719–807`: pools, re-plays, `tryRemount`). LIVE runs (P2
  **2→3**): nothing main paints shows in the dissolve. S2 (`d88584eb`) holds a restarting decoder through it at opacity 1.
- **Main's bridge over the terminal transition (static read; pixels Q0b).** Only P2-measured plans engage the core
  (`QUALIFIED_PLAN_SHA256`, `live_continuity.py:627`, `:895`). `keepAtSlot` (`live_continuity_js.py:1056–1093`) keeps the 3→4
  bridged decoder in `#body` at `opacity 1`, re-attached and playing, while the hash is ≥ slide 4 (`slotLive`, `:1007`, has no
  transition condition): at P2 slide 4's terminal Dissolve **stock and patched alike** show it at full strength. Q6.
- **Foreground over movies.** P2 slide 2: a translucent square (`3F22E494`, opacity 0.2947) overlaps the movie. DSK slide 7:
  labels, divider and frame canvases over two clips that overlap each other by ≈ 1 px (as on DSK slide 3).
- **Tone path (static evidence; Q5).** Native `<video>` gets a transfer conversion that `drawImage`/`texImage2D` skip: ≤ +11/255
  in the midtones, 0 at black/white, identical in OBS and headless (`.agents/reviews/gl-replay-managed/gates-r1.md` finding 1);
  here mid-grey (RGB 128) is 139 live, 128 snapshot. One curve fits both: Chromium's macOS `BT709_APPLE` transfer (gamma
  1.961) to sRGB, `L(v) = 255·sRGB((v/255)^1.961)`: 128 → 139.2, maximum +11.3 at 113, −4.3 at 9, 0/255 fixed (a BT.709-OETF
  model predicts +15.8 at 32); per-channel 1-D after the shared YUV→RGB matrix (Q0b checks colour patches). Keynote exports
  carry HEVC Main 10 `tv, bt709`; `p2-binary`'s untagged H.264 decodes as BT.709 (§8). DSK fixtures are ProRes (never live). Q0b 1: software compositing (`--disable-gpu`) is identity for the same tagged tuple, so a tuple alone cannot select `L`; rev 10 ships identity (decision 10).

### 1.5 The `none` cut (F1)

A cut's outgoing `hidden` animation is opacity keyframes 1→0 over 1 ms (`fillMode both`); its first animated frame shows the
outgoing over the unanimated, already visible incoming: on fill-less textures that frame (and any render→animate gap frame)
shows both slides (§8). On-disk cuts end on the empty background; a cut between two content slides shows the union.

## 2. Arithmetic (premultiplied RGBA, 0..1; e = eased progress)

- **Stock Dissolve:** `C = (1−e)·P_out + (1 − (1−e)·α_out)·P_in`: exact where `α_out = 1`, `P_in` at once where `α_out = 0`.
- **Plain opposite fades (rejected):** `α = 1 − e + e²` = 0.75 at e = 0.5 where both are opaque.
- **Fix:** in the isolated container group, incoming (opacity e, `plus-lighter` onto zero) = `e·P_in`; outgoing (opacity 1 − e,
  `plus-lighter`) gives `G = (1−e)·P_out + e·P_in`, `α_G = (1−e)·α_out + e·α_in`, never clamped; preconditions per §3.2's
  predicate (the grouping properties flatten `transform-style`, CSS Transforms 2 §7.1). Endpoints exact. 8-bit: 1.3–1.5 LSB
  GPU, 2.7 software; τ = 4. Opaque textures: algebraically stock; measured on/off ≤ 1.51 LSB (report-only bound 2).
- **Frozen movie:** the opaque snapshot `S` (the frame as `drawImage` decodes it; identity `L`) plus redrawn overlying canvases
  (α 255 proven at every backing pixel) covers exactly the admitted region in the outgoing wrapper, so the group gives `(1−e)·P_out' + e·P_in` (`P_out'` = texture
  with `S` there), as admission proves. On the GPU path `S` lacks the live transfer step (≤ +11.3/255), the known limit.
- **Cut (exported timing only):** incoming 0→1 mirrors outgoing 1→0 over the same 1 ms, started in one loop: opacities sum to 1
  at every instant; a frame inside that 1 ms shows complementary partial opacities (allowed), never both at full strength.
- **Isolation:** the blend's backdrop is the container group only; it cannot make an independent overlay fade (§1.4, §6.2).

## 3. The patch

### 3.1 Exact replacements (R9–R12 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedShape`, `__obedDissolveLayer`, `__obedFreezeTake`, `__obedFreeze` + `renderEffects(A){` (10 305 B; rev 16: 10 559; rev 15: 10 571; rev 13–14: 10 197; rev 12: 10 195; rev 11: 10 249; rev 10: 10 237; rev 9: 9 225) |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |
| D3 (R11) | after the CSS draw @2313053 (42 B) | `this.cssRenderer.draw(a),a.removeChild(w)}` | `this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}` |
| D4 (R12) | `jumpToScene_partFour` @2353722 / @2353760 (50 B) | `jumpToScene_partFour(A,B){if(this.displayScene(A),` | `jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),` |

The methods (rev 17: `plan-rev17-2026-10-12/scripts/r10.py` `methods17()`, built by counted substitution from W1's rev-9
constants; `node --check` passes on both patched players, `on` and `rendering`; `PB` and the controller share the module
scope of `TB` and `UC`). Only `__obedFreezeTake` changes against rev 9:
- the paint gate: the exterior proof `xo` with HTML-`div` witnesses, the visible stage `V`, the top-layer refusal, open author
  shadow roots refused, descendant-paint effects checked before the visibility shortcut, and no tag exempt by name (decision 8;
  r8 1–2, r9 1–2);
- the snapped device-pixel holder (decision 9), snapped on the stage-local 1/DPR grid (fix A, decision 12);
- the **geometry guard**: `devicePixelRatio` ∈ {1, 1.5, 2}; `kx` = `ky` = 1 (the live base-layer box is the slide); `#stage` and
  every scene transform a pure translation; integer computed `left`/`top` on every scene element (r8 4–5, r9 3; §3.2);
- the **host grant**: the take skips unless the non-configurable getter `window.__obedPlacement` reads `"snap"` (decision 15,
  §3.3). The host grants it only on a Chrome it launched itself whose engine is qualified. The getter is absent on raw/preview
  pages, and nothing is granted under managed OBS/CEF;
- identity tone, with the alpha scan over **every** backing pixel (decision 10; r8 3; `L`, its table and `_FREEZE_TONE_LUT` go);
- the `fill` aspect test goes.

`Q` stays the one qualified tuple (`_FREEZE_QUALIFIED_TUPLES`). Rev 16's fractional (`frac`) draw is gone (follow-up PR,
§13.1).
Candidate digests (W1 re-pins; `off` unchanged): `on` e9b2fad4 `81ac1a33…`, 17c0c938 `a9aa0bde…`; `rendering` e9b2fad4
`dd0db318…`, 17c0c938 `c6c1eb5e…`.

```
__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||!1!==x.from.scalar||!0!==x.to.scalar||.001!==x.duration||0!==x.beginTime||"both"!==x.fillMode||x.timingFunction||x.timeOffset||x.repeatCount||x.autoreverses:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,x,u]}catch(E){return null}}
__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=u?"cut":"dissolve",Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}:{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
__obedFreezeTake(U,A){U.__obedFrozen=null;var t0=performance.now();try{var e=U.script.events[A],y=e&&e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),kx=U.script.slideWidth/R.width,ky=U.script.slideHeight/R.height,H=[],N=document.getElementsByTagName("*"),Q=["bt709/bt709/bt709/false"],pl=window.__obedPlacement,cs=function(n){return getComputedStyle(n)},dv=function(s,d){return(s||d)===d},bd=function(z){return"none"!==z.borderTopStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle||"none"!==z.borderLeftStyle},rd=function(z){return"0px"!==z.borderTopLeftRadius||"0px"!==z.borderTopRightRadius||"0px"!==z.borderBottomLeftRadius||"0px"!==z.borderBottomRightRadius},deco=function(z){return!/rgba\(0, 0, 0, 0\)|transparent/.test(z.backgroundColor)||"none"!==z.backgroundImage||"none"!==z.boxShadow||bd(z)||"none"!==z.outlineStyle||!dv(z.backdropFilter,"none")},own=function(n,z){return/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED|INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(n.tagName)||deco(z)||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})},bm=function(z){return!deco(z)&&!rd(z)&&"0px"===z.paddingTop&&"0px"===z.paddingRight&&"0px"===z.paddingBottom&&"0px"===z.paddingLeft&&dv(z.objectViewBox,"none")&&dv(z.imageRendering,"auto")},al=function(a){var w=cs(a),s=a===G,u=!s&&a.contains(G),m=w.transform,M;if("block"!==w.display||!dv(w.contain,"none")||!dv(w.contentVisibility,"visible")||"none"!==w.filter||!dv(w.backdropFilter,"none")||"normal"!==w.mixBlendMode||!dv(w.isolation,"auto")||"none"!==w.clipPath||!dv(w.maskImage,"none")||!dv(w.clip,"auto")||"auto"!==w.zIndex||!dv(w.translate,"none")||!dv(w.rotate,"none")||!dv(w.scale,"none")||!dv(w.offsetPath,"none")||!dv(w.willChange,"auto")||!dv(w.zoom,"1")||"none"!==w.outlineStyle||w.overflowX!==w.overflowY||"visible"!==w.overflowX&&!("clip"===w.overflowX&&/^(VIDEO|CANVAS)$/.test(a.tagName))&&("hidden"!==w.overflowX||rd(w)||bd(w)))return!1;if(u)return("static"===w.position||"absolute"===w.position)&&"none"===m;if("absolute"!==w.position||!dv(w.perspective,"none")||!dv(w.backfaceVisibility,"visible")||(s?"preserve-3d"!==w.transformStyle&&"flat"!==w.transformStyle:"flat"!==w.transformStyle&&("preserve-3d"!==w.transformStyle||"none"!==m)||"visible"!==w.visibility))return!1;if(!s&&!(/^-?\d+px$/.test(w.left)&&/^-?\d+px$/.test(w.top)))return!1;if("none"===m)return!0;M=new DOMMatrix(m);return M.is2D&&!M.b&&!M.c&&1===M.a&&1===M.d},xo=function(n){for(var a=n,w,r;!a.contains(G);a=a.parentElement){w=cs(a);if("fixed"===getComputedStyle(a,"::before").position||"fixed"===getComputedStyle(a,"::after").position)return!1;if("div"===a.localName&&"http://www.w3.org/1999/xhtml"===a.namespaceURI&&"hidden"===w.overflowX&&"hidden"===w.overflowY&&"static"!==w.position&&/^(block|flow-root|flex|grid)$/.test(w.display)&&"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&(r=a.getBoundingClientRect(),r.right<=V[0]||r.left>=V[2]||r.bottom<=V[1]||r.top>=V[3]))return!0;if("fixed"===w.position)return!1}return!1},vp=function(a){var h=document.documentElement;return a===h||a===document.body&&"visible"===cs(h).overflowX},pc=function(n){var t=n.tagName,w=cs(n),b,f;if("contents"===w.display)return!1;if(!n.checkVisibility({opacityProperty:!0}))return!0;b=getComputedStyle(n,"::before").content;f=getComputedStyle(n,"::after").content;if(!/^(normal|none)$/.test(b||"none")||!/^(normal|none)$/.test(f||"none")||!/^(normal|none)$/.test(w.content||"normal")||"list-item"===w.display||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})||"none"!==w.filter||!dv(w.backdropFilter,"none")||!dv(w.webkitBoxReflect,"none"))return!1;if("visible"!==w.visibility)return!0;if(!/^(HTML|BODY|DIV|CANVAS|VIDEO)$/.test(t)||/^(CANVAS|VIDEO)$/.test(t)&&("50% 50%"!==w.objectPosition||!dv(w.objectViewBox,"none")||!/^(fill|contain)$/.test(w.objectFit)))return!1;return"none"===w.boxShadow&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.columnRuleStyle,"none")};for(var V=[0,0,innerWidth,innerHeight],a=G,w,b;a;a=a.parentElement)w=cs(a),"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)&&(b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect(),V=[Math.max(V[0],b.left),Math.max(V[1],b.top),Math.min(V[2],b.right),Math.min(V[3],b.bottom)]);if(!(R.width>0&&R.height>0)||[1,1.5,2].indexOf(devicePixelRatio)<0||"snap"!==pl||1!==kx||1!==ky||document.querySelector(":modal,:popover-open,:fullscreen")||!Array.prototype.every.call(N,function(n){return!n.shadowRoot&&(pc(n)||!G.contains(n)&&!n.contains(G)&&xo(n))}))return;var ad=[];Array.prototype.slice.call(document.querySelectorAll("video")).reverse().forEach(function(v){try{if(!G.contains(v)||v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;var z=cs(v),fit=z.objectFit,K;if(!bm(z)||"50% 50%"!==z.objectPosition||"fill"!==fit&&"contain"!==fit)return;try{var vf=new VideoFrame(v),cc=vf.colorSpace;K=[cc.primaries,cc.transfer,cc.matrix,cc.fullRange].join("/");vf.close()}catch(E){return}if(Q.indexOf(K)<0)return;var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom],a,q,w,b;for(a=v,q=1;a;a=a.parentElement){if(!al(a))return;w=cs(a);q*=+w.opacity;if(a!==v&&"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)){b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}}if(q<.999)return;var vw=v.videoWidth,vh=v.videoHeight,f="fill"===fit?0:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,ch2=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch2)/2;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch2)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;for(var I=Array.prototype.indexOf.call(N,v),i=0,n,o,P,T;i<N.length;i++){n=N[i];if(i===I||n.contains(v))continue;o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||o.top>=c[3]||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;for(P=n.parentElement;!P.contains(v);P=P.parentElement);if(P===G||!G.contains(P))return;for(T=n,a=1;T!==P;T=T.parentElement){w=cs(T);if(!al(T)||i>I&&T!==n&&"visible"!==w.overflowX)return;a*=+w.opacity;if(T!==n&&+w.opacity<1&&Array.prototype.some.call(T.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))a=0}if(i<I)continue;if("VIDEO"===n.tagName){if(ad.indexOf(n)<0)return;continue}w=cs(n);if("CANVAS"!==n.tagName||!bm(w)||"fill"!==w.objectFit||!a)return;Y.push([n,o,a])}var p=devicePixelRatio||1,sn=function(z,e,k){return Math.round((z-e)*k*p)/p},u0=sn(cx,R.left,kx),v0=sn(cy,R.top,ky),u1=sn(cx+cw,R.left,kx),v1=sn(cy+ch2,R.top,ky),a0=sn(c[0],R.left,kx),b0=sn(c[1],R.top,ky),a1=sn(c[2],R.left,kx),b1=sn(c[3],R.top,ky),ww=Math.round((a1-a0)/kx*p),hh=Math.round((b1-b0)/ky*p),dx=(u0-a0)/kx*p,dy=(v0-b0)/ky*p,dw=(u1-u0)/kx*p,dh=(v1-v0)/ky*p,x,g,d,j;if(ww<1||hh<1)return;x=document.createElement("canvas");x.width=ww,x.height=hh;g=x.getContext("2d");g.drawImage(v,dx,dy,dw,dh);for(d=g.getImageData(0,0,ww,hh).data,j=3;j<d.length;j+=4)if(d[j]<255)return;Y.forEach(function(y){var l=sn(y[1].left,R.left,kx),m=sn(y[1].top,R.top,ky);g.globalAlpha=y[2],g.drawImage(y[0],(l-a0)/kx*p,(m-b0)/ky*p,(sn(y[1].right,R.left,kx)-l)/kx*p,(sn(y[1].bottom,R.top,ky)-m)/ky*p)}),g.globalAlpha=1;var h=document.createElement("div"),s=h.style,t=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=a0+"px",s.top=b0+"px",s.width=t.width=a1-a0+"px",s.height=t.height=b1-b0+"px",t.left=t.top="0px",h.appendChild(x),H.push(h),ad.push(v)}catch(E){}}),H.length&&(U.__obedFrozen={scene:A,holders:H.reverse()})}catch(E){U.__obedFrozen=null}finally{window.__obedTakeMs=U.__obedTakeMs=performance.now()-t0}}
__obedFreeze(C,A){var F=UC.__obedFrozen;UC.__obedFrozen=null;if(C.obedDissolve&&F&&F.scene===this.sceneIndex)try{var O=A.layers[0].layers[1],W=document.getElementById("layer"+O.layerId+("cut"===C.obedDissolve?"":"-opacity"));if(!W)return;var Q=document.createDocumentFragment();F.holders.forEach(function(h){Q.appendChild(h)}),W.appendChild(Q)}catch(E){}}
```

### 3.2 How it works

**Construction (D1's `__obedDissolveLayer`, called by D2).**
- **Predicate (faithful or unchanged):** stock unless a `transition` named `apple:dissolve` or `none`; exactly root → one
  container → two textured leaves without sublayers; root and container without texture or animation; container and leaves
  without `objectID`, video/poster flags or 3D `transform`, identity affine, rotation 0, scale 1, opacity 1, not hidden; leaves
  with identity `sublayerTransform`; incoming without animation; outgoing with exactly one plain animation: Dissolve `opacity`
  1→0 (timing copied into the mirror), cut `hidden` false→true with exactly §1.2's timing. 50/50 on-disk transitions match.
- **Dissolve: commit before construction.** Two rules for ids TB+1 … TB+3 are inserted and read back via `CSSStyleRule.style`
  (a dropped declaration reads empty); only then is the copy returned, and `new VB(copy)` allocates exactly those ids.
- **Cut:** no rules; the copy starts the incoming `hidden` (`addNode` writes `visibility:hidden`) with the mirror;
  `applyCssAnimation` makes it visible and starts both animations in one loop, the backwards fill holding its opacity at 0.
- **One failure point, before anything is built:** predicate miss, no stylesheet, a throwing `insertRule` or a dropped
  declaration return the export's own tree; after a partial insert `TB += 4` abandons those ids. Copies only along root →
  container → incoming; export JSON never mutated. The engaged kind `obedDissolve = "dissolve" | "cut"` lives on `yB`.

**Freeze: take (D4) before teardown, attach (D3) at the transition start, same task.** `__obedFreezeTake` runs only when
`jumpToScene_partFour` plays the scene now (`B`) and its first effect has the §1.2 shape; it stores `UC.__obedFrozen = {scene,
holders}`. `__obedFreeze` (D3) always clears the slot and attaches **by engaged kind**: a Dissolve needs `layer<out>-opacity`
(absent → discard); a cut uses `layer<out>`; one `DocumentFragment` append, so a throwing append attaches none.

**Paint gate (once per take, before any rectangle test; any failure skips the take; decision 8, r8 1–2).** First the **top
layer**: any `:modal`, `:popover-open` or `:fullscreen` element skips the take — top-layer content and its `::backdrop` paint
above the page and escape every ancestor clip, so neither test below may shortcut them (a browser that cannot parse one of
these selectors throws inside the take's `try` and skips too). **Author shadow trees are unsupported paint boundaries** (r9
2): their contents are invisible to `getElementsByTagName` and to the document's top-layer query, so a shadow `dialog` with a
`::backdrop` or a fixed overlay could paint over the stage unseen. Any element with an open `shadowRoot` skips the take before
any shortcut. A closed root cannot be detected from the page (`shadowRoot === null` proves nothing), so supported pages carry a
**checked invariant**: nothing on them creates an author shadow root — the served players (both supported `main.js`), every
export `index.html` and every script the host injects contain no `attachShadow`, `shadowrootmode`/`shadowroot` or
`customElements` (verified 2026-10-12 on both players, the P2 export and `src/obed_edom`; W1 test with a planted-string
control, §10). UA shadow roots (media controls) are not author roots and read `null`. Then every element of the document
passes the **element test** or, outside the stage, the **exterior proof**.
- *Element test (mandatory for `#stage`, its subtree and its ancestors):* `display: contents` fails; an element with no box
  or in an opacity-0 group (`checkVisibility({opacityProperty})` false: nothing of it paints — `display: none` itself or
  inside, which is the UA default for `head`, `script`, `style`, `link`, `meta`, `title`, `base`, `template`, `noscript`)
  passes. **No tag is exempt by name** (r9 1: a rendered `display: block` `script` with overflowing text, or a rendered,
  hidden `head` with a filter over a clipper, passed rev 11 by tag alone); non-rendering is read from the rendering state. Otherwise, before any visibility
  shortcut, `::before`/`::after` and own `content` must be `none`/`normal`, no `display: list-item`, no direct text, and **no
  effect that operates on descendant paint** — `filter`, `backdrop-filter`, `-webkit-box-reflect` — because a hidden element
  still filters or reflects its visible descendants (r8 1: a hidden parent's `drop-shadow` projected a clipped exterior
  subtree into the movie). A `visibility`-hidden element then passes (its own box does not paint). A visible one must be a
  supported paint family — `html`, `body`, `div`, `canvas`, `video` (no `img`, `svg`, `object`, `embed`, `iframe`, form
  control) — without `box-shadow`, `outline`, `border-image` or column rule; a `canvas`/`video` needs
  `object-position: 50% 50%`, `object-fit` `fill`/`contain`, no `object-view-box` (content inside its box). Its paint is then
  confined to its border box, so the per-movie rectangle test sees it: an exterior element that passes (main's bridged decoder
  in `#body` is one) and meets a movie's region skips that movie (no common ancestor inside the scene), as in rev 9.
- *Exterior proof (an element neither inside `#stage` nor an ancestor of it that fails the element test):* walking from it up
  to, not including, its first ancestor that contains `#stage`, a **validated clipping ancestor** `A` is reached before any
  `position: fixed` element (`A` itself may be fixed), and no element on the walk (`A` included) has a fixed `::before` or
  `::after`. `A` is an **HTML `div`** (`localName` `div` in the XHTML namespace: a qualified layout container — an SVG `g`
  styled `display: block; position: relative; overflow: hidden` is not an overflow container, r8 2), has `overflow: hidden` on
  both axes (no `clip` margin, no scroll), is positioned (every non-fixed descendant's containing block is then inside it, so
  its overflow clip applies to all of them), has `display` `block`/`flow-root`/`flex`/`grid` (overflow applies), paints
  nothing outside its own box (no `box-shadow`, `filter`, `backdrop-filter`, `outline`, `border-image`,
  `-webkit-box-reflect`), and its transformed bounding box is disjoint from the **visible stage** `V`. `V` = the
  viewport ∩ every rectangle clip on `#stage`'s chain, by the same rule admission intersects (positioned ancestor with
  non-`visible` overflow; root, or `body` when the root is `visible`, to the viewport), so every admitted region lies inside
  `V`, and nothing below `A` can paint inside `V`. Border-box disjointness of the failing element itself is never used.
  **Nothing above `A` can move its clipped output into `V`:** every ancestor of `A` is itself an element of the document, so it
  passes the element test (no descendant-paint effect even when hidden; a transform only displaces, and `A`'s bounding box is
  measured after every ancestor transform) or fails it and needs its own witness higher up, whose clip bounds whatever it does
  to `A`'s output. **Boundaries:** an `iframe` fails the family test and is judged as one box (its document cannot paint
  outside it except through the top layer, which the parent's `:fullscreen` catches); SVG content (`svg`, `g`,
  `foreignObject`) fails the family test and needs an HTML witness above it; a `div` inside a `foreignObject` witnesses only
  its own subtree. Clipped `absolute`, `sticky` and transformed descendants of a witness stay confined (positives in §10).
- *On the real pages (§8):* the host page hides `#slideshowNavigator` (unchanged). On the raw export / Build Preview page its 12
  failing elements (thumbnail `img`s, shadowed frames, number text) sit inside `.navigatorThumbnailSidebar` (absolute, overflow
  hidden, `left: −140px`, 129 px + 1 px border: box right edge −10 ≤ `V`'s left 0): pruned. The navigator itself (left 0,
  140 px, overflow hidden, transparent, no failing paint of its own) passes the element test. Slid open (`left: 0`) the sidebar
  meets `V` and the take skips; an off-viewport caption whose text overflows into the stage has no clipping ancestor below
  `body` and skips (measured, §8).

**Admission: a positive allowlist of computed values, derived from what the player generates (§1.1).** A movie is admitted
only if every element from it up to `<html>` is inside the profile below; every other painted element meeting its region must
share a common ancestor with it inside the scene (below `#stage`) and have its whole branch below that ancestor inside the
profile. Videos are decided from the last in document order to the first. Anything outside → skip (today's look).

| Applies to | Generated by | Allowed computed values (anything else → skip) |
|---|---|---|
| every element of a chain or branch | — | `display: block`; `z-index: auto`; `contain: none`; `content-visibility: visible`; `filter`, `backdrop-filter`, `clip-path`, `mask-image`, `offset-path`, `translate`, `rotate`, `scale`: `none`; `clip: auto`; `mix-blend-mode: normal`; `isolation: auto`; `will-change: auto`; `zoom: 1`; `outline-style: none`; `overflow-x` = `overflow-y` ∈ {`visible`, `hidden` with no border and zero radii (a rectangle), and `clip` on a `<video>`/`<canvas>` leaf (UA default; clips nothing it shows)}. Clips applied: a positioned ancestor's rectangle; the root, or `body` when the root is `visible`, clips to the viewport; a static, non-propagating ancestor clips nothing absolute |
| scene elements (below `#stage`): scene root, layer and movie divs, texture `<canvas>`, `<video>` | `NB.draw`, `NB.addNode`, `xB.initVideo`, `movieDiv` | `position: absolute`; `visibility: visible`; `transform-style: flat`, or `preserve-3d` with `transform: none` (the build wrappers; every transform below is 2D, so all is coplanar); `perspective: none`; `backface-visibility: visible`; `transform` none or a pure translation `matrix(1, 0, 0, 1, e, f)` (geometry guard; rev 10 allowed uniform scales); computed `left` and `top` integral px (decision 13) |
| `#stage` | `Cg.adjustStageToFit` | `position: absolute`; `transform-style: preserve-3d` or `flat`; `transform` none or a pure translation — stage scale exactly 1 (geometry guard; `Cg.adjustStageToFit`'s `scaleX`/`scaleY` ≠ 1 skips); `visibility` any (inherits `#stageArea`'s hidden) |
| above `#stage` (`#stageArea`, `body`, `html`) | page CSS, host | `position: absolute` or `static`; `transform: none`; background and visibility any |
| the movie itself | | plain bitmap (below); `readyState ≥ 2`, decoded size, `checkVisibility({opacityProperty, visibilityProperty})`; chain opacity product ≥ 0.999; `object-fit` `contain` or `fill`; `object-position: 50% 50%`; `VideoFrame` colour tuple (primaries/transfer/matrix/fullRange) ∈ `Q`; alpha 255 at every backing pixel of the attached canvas, read after the draw and before any redraw; `devicePixelRatio` ∈ {1, 1.5, 2} |
| a later painted element | | an admitted `<video>` (its holder is appended after), or a plain-bitmap `<canvas>` with `object-fit: fill`, `overflow: visible` above the leaf and no translucent ancestor painting anything else, redrawn into its snapped rect at device scale and its effective opacity |
| plain bitmap | | no background colour or image, box-shadow, border, outline or `backdrop-filter`; zero radii and padding; `object-view-box: none`; `image-rendering: auto` |

Why this proves the picture: the gate confines all paint to border boxes; admitted chains and branches are block, absolute,
`z-index: auto` and 2D (coplanar) in one scene subtree, so paint order is document order (CSS 2 App. E); the only clips are
the intersected rectangles; nothing crops, filters, blends or contains paint; ancestor backgrounds paint beneath.

- **Tone (decision 10):** identity `L` — the snapshot is the decoded frame as `drawImage` gives it; no RGB write, no
  `putImageData`, no table. The alpha scan stays and covers **every backing pixel of the attached canvas** (r8 3): after the
  movie draw and before the foreground redraw, `getImageData(0, 0, ww, hh)` must read α 255 everywhere, boundary rows and
  columns included, or the take skips. The canvas is exactly the holder's clip, and under the geometry guard it maps 1:1 onto
  device pixels, so no later scaling samples outside the proven pixels; a partially covered edge (or source transparency)
  anywhere is a skip, never an unchecked admit. Known limit (§12.5): on the GPU compositing path the live movie carries Chromium's `BT709_APPLE`
  transfer step (mid-grey 128 → 139, max +11.3/255 at 113, 0 at black/white) and the frozen frame does not; software
  compositing is identity (Q0b 1). `Q` stays the one measured tuple; W5 decides whether a host-calibrated `L` can come back.
- **Geometry (decision 9; device pixels on the measured model for the qualified geometry; r8 4–5).** Element box → content
  box (`object-fit`, centred) → ∩ rectangular clips = region `c` (screen px). **Measured model, not Chromium's universal rule:**
  on the qualified geometry — `devicePixelRatio` 1, 1.5 or 2, `#stage` transform a pure translation (stage scale 1; a
  letterbox offset, fractional included, is a translation), every scene transform below it a pure 2D translation
  (`matrix(1, 0, 0, 1, e, f)`, fractional `e`/`f` allowed: Blink carries a translation's sub-pixel part into the paint offset
  it snaps) — Chromium paints the `<video>` bilinearly into its content box with every edge rounded on the stage-local
  **device** grid, i.e. 1/DPR CSS px (layout is zoomed by the DSF, so LayoutUnits are device px): P2 slide 2's
  `[109.35, 795.04, 951.53, 267.61]` paints at `[109, 795, 952, 268]` at DSF 1 and starts at device x 219 at DSF 2 (§8.2,
  §8.5). The take snaps the same way (fix A), `sn(z) = round((z − R.left)·kx·DPR)/DPR` (y with `R.top`, `ky`; `kx` = `ky` = 1
  here), for the content box (`u0`…`v1`) and the
  region (`a0`…`b1`); the holder is a `div` (overflow hidden) at the snapped region, holding one canvas of the same CSS size
  whose backing is its device size (`ww` × `hh`); the movie is drawn once into the snapped content box,
  `drawImage(v, dx, dy, dw, dh)`, and each redrawn canvas into its own snapped rect at its effective opacity. Clipped
  boundaries snap like edges (the clip rectangle is rounded with the same `sn`).
- **Geometry guard (decision 12, resolved: fix A).** The take skips unless `devicePixelRatio` is 1, 1.5 or 2 (measured;
  any other value, e.g. 1.25 or 3, is unmeasured and skips), `kx` and `ky` are exactly 1 (the live base-layer box measures the
  slide's own width and height; r9 3: a 960-wide base layer gave `kx` = 2 and a holder attached at twice the width and the
  wrong place), `#stage`'s transform is a pure translation (stage scale 1; fractional letterbox origins are admitted — measured
  exact) and every scene element on the movie chain and on each redrawn branch is a pure translation (`al`: `a = d = 1`,
  `b = c = 0`). Stage scale ≠ 1 and scales below the stage keep today's look: the investigation's best model (option B) fixes
  its replica at stage 4/3 but not the real P2 chain (83 / 5.1 %), and a nested anisotropic scale breaks the screen-space
  `contain` solve (§13). The alpha scan over every backing pixel, the exterior proof, clipping and foreground preservation
  are mandatory in every admitted class (§9.1 "Geometry classes"); a later model for scaled stages would replace exactly this
  guard and `sn`/`ww`/`hh`/`dx`…`dh`, under the same rule.
- **Host grant (decision 15).** The take reads `pl = window.__obedPlacement` once and proceeds only if it is `"snap"`, which
  means the snapped draw above (Chrome 154's measured rule). Anything else — absent, `"invalid"`, any other value — skips the
  take: placement is never guessed in the page, and OBS's CEF 127, which does not snap (§8.6), keeps today's jump in this PR.
- **Integer `left`/`top`:** every scene element (below `#stage`) must have integral computed `left` and `top` in px
  (`/^-?\d+px$/`), so sub-pixel offsets come only from transforms (every export writes `0px`). This is kept from rev 15 as an
  admission narrowing; it costs nothing on the measured decks.
- `object-fit: fill` needs no aspect test (the destination is the content box itself).
- **Snapshot, not move; failure model:** a move is a detach the core observes (`stash` re-plays and remounts it); `drawImage`
  is the exact last presented frame (rVFC). Add-only, per movie, after the cross-fade rules are committed; the `<video>` is
  only read (no write; no call besides `checkVisibility`/`getBoundingClientRect`), so the core sees the detach as today.
- **Cost:** `window.__obedTakeMs` (also on the controller, which page scripts cannot reach) = the take's total wall time
  (gate, every candidate incl. rejected ones, draws, readbacks, alpha scans, redraws), written in a `finally` on every path.
  Work now scales with the movie's on-screen device area, not its natural size (DSK 7→8: 312×263 + 468×263 device px instead
  of 1282×1080 + 1922×1080 source px at DSF 1; four times the pixels at DSF 2, estimated 25–30 ms, to be timed in Q0b-bis).
  Retained: one region-sized canvas per frozen movie (P2: 952×268 ≈ 1 MB at DSF 1, ≈ 4 MB at DSF 2),
  freed with the transition DOM; transient: one interior `ImageData` per movie and a closed `VideoFrame`.
- **Cleanup is the player's:** holders live in the transition DOM (removed at the next scene, go-to/back, replay, queued skip;
  kept invisibly at the end-of-show endpoint); an unattached take is dropped at D3 or by the next take (lifecycle rows, §9.1).
- **Residuals (today's baked-frame jump):** gate or allowlist misses (incl. an open preview navigator); G2-drawn movies;
  undecodable codecs; tuples outside `Q` (incl. untagged H.264 under software compositing, which decodes `smpte170m…` — it
  would freeze exactly there, but the tuple is unmeasured on GPU); hyperlink transitions (skip D4; never used live);
  self-playing mode (host-refused); the bridge/hold until the Q6 follow-up; **every geometry outside the guard** (DPR ∉ {1,
  1.5, 2}, stage scale ≠ 1, a scale below the stage; decision 12); top-layer content on the page. **Known limit (frozen, not
  jumping):** the mid-tone step (identity `L`).

### 3.3 Host grant — the placement channel (decisions 13–15; host stream W6, shrunk)

**What it decides.** Whether the take may draw with the snapped rule. In this PR the grant comes from host knowledge alone, with
no probe (decision 15). The host grants `snap` iff:
- (a) it launched the Chrome process itself, so `LiveOutputHost` is not in attach mode;
- (b) CDP `Browser.getVersion` reports a qualified engine: `product` `Chrome/154.*` or `HeadlessChrome/154.*` (the measured
  engine, Chrome 154.0.8037.59; the allowlist is one constant, `QUALIFIED_SNAP_MAJORS = (154,)`); and
- (c) `SystemInfo.getInfo` reports `gpu_compositing: "enabled"` (the GPU path is the measured one; the software path's holder
  pixels are unqualified).

Anything else — attach mode, managed OBS/CEF (always attach), any other major version, a version or `SystemInfo` call that
fails, software compositing — means no grant: the take skips (today's jump) and `output.placement` records why.

**Channel (r12 1, unforgeable by page code).** Before navigating the output target, the host installs with
`Page.addScriptToEvaluateOnNewDocument` a first-run script. It runs in every new document before any export script:

```
(function(){var T="<128-bit hex, per host session>",r="invalid";Object.defineProperty(window,"__obedPlacement",{get:function(){return r},enumerable:false,configurable:false});Object.defineProperty(window,"__obedGrant",{value:function(t,v){if(t!==T)return!1;r="snap"===v?v:"invalid";return!0},enumerable:false,configurable:false,writable:false})})();
```

The state is private to that closure and starts `invalid` in every document. Page code sees a non-configurable getter and an
updater that does nothing without the token. The token is not in the updater's source text, and only `"snap"` can be granted.

Checked in Node (`plan-rev17-2026-10-12/grant/`):
- assignment (sloppy and strict), `delete`, accessor redefinition, forging `"snap"` by assignment or redefinition, updater
  replacement and a wrong token all leave the host's value;
- a fresh document reads `invalid`;
- a predefined getter makes the init script throw, so no updater exists.

**Lifecycle (what r12 4 still requires).**
- **Context binding.** The grant is bound to the program document's unique execution context. After every
  `Runtime.executionContextCreated` for it, the host runs the round trip in that context with
  `Runtime.evaluate({uniqueContextId, …})`: grant `snap`, read `snap`, revoke, read `invalid`. Only then, if (a)–(c) hold,
  does it commit the grant there. A context that disappears in between fails the evaluate, so the grant is never installed
  into a replacement document. A reload yields a fresh `invalid` document that is re-granted only after its own round trip.
- **Fingerprint.** At every `observe()` the host re-reads `gpu_compositing`. If it is no longer `"enabled"` or cannot be read,
  the host revokes in that context.
- **Channel failure.** A failed round trip (for example a predefined getter, which page scripts cannot cause because they run
  after the first-run script) reports `placement: "channel-compromised"`, keeps the output hidden and refuses `show`.

**Dropped from rev 16, and why.**
- *Lease and keep-alive:* they existed so that a probe-measured rule could go stale and still lapse. A version-and-launch
  grant cannot go stale while its process lives (the version cannot change without a relaunch), and no output command can run
  without the host's CDP connection.
- *Probe, isolation gate, recalibrate command, reconnect re-probe:* they move to the follow-up PR (§13.1).

**Residual (stated, as before):** a player-internal automatic transition that runs while CDP is disconnected, after a
GPU-to-software fallback the host has not yet observed, would use a stale grant. Both conditions must hold.

**Report.** `output.placement = {grant: "snap" | null, reason, product, gpuCompositing, at}`. The reason is one of `granted`,
`attached` (incl. managed OBS), `unqualified-version`, `software-compositing`, `version-unavailable`, `channel-compromised`,
`revoked-fingerprint`.

**Files (W6):** `src/obed_edom/live_host.py` (init-script builder, grant conditions, context-bound round trip and commit,
`observe()` fingerprint, report) and `tests/test_live_host.py`. No change to `web/live.py`, `live_session.py`, `managed_obs.py`
or the dashboard.

## 4. Switch, pins, report

- **Switch (decided):** D1–D4 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`, `patch_rendering` and every synthetic test
  player pick them up; `mm_opacity=False` stays the hook-only bytes (`7cf00b56…` / `4f9fbffd…`); docstrings say "rendering
  fidelity"; README: `OBED_LIVE_MM_OPACITY=off` also restores the export's dissolve, cut and movie behaviour. **Pins:**
  `(on, off, rendering)` kept; `on`, `rendering` re-pinned. **Report** `output.mmOpacity = {mode, sha256}`; `RUNTIME_VERSION`
  stays 2; preview inherits the patch (D1/D2; F3 skips there — no host grant, decision 14); paint oracle stays stock; the report adds
  `output.placement` (§3.3); `web/live.py` unchanged.

## 5. Scope

**Every output; `apple:dissolve` and `none` of the §1.2 shape (50/50 on disk); admitted movies of the outgoing slide.**

| Effect | On disk | Fill-less textures | Plan |
|---|---|---|---|
| `apple:dissolve` | 42 | pop-in | D1–D2 |
| `none` cut | 8 | both slides for ≥ 1 frame (§1.5, §8) | D1–D2 |
| movies at a Dissolve/cut start | every DSK clip slide; P2, D decks | jump to the baked opening frame | D4 + D3 (admitted, §3.2) |
| main's bridged movie at P2 slide 4 → end | P2-measured plans | full strength over the fade (stock too) | Q6 follow-up PR after S2 |
| per-object builds | 382 | ok | none |
| GL effects (`jC`) | 67 | not CSS | R1–R8 |
| other CSS transitions the player special-cases, smart/action builds | 0 | unknown | F2: separate PR, owner Q-deck |

## 6. Interplay

### 6.1 Anchor map (byte offset, length; e9b2fad4 / 17c0c938)

R7 2190367 (36) · R3 2190440 (46) · R4 2192650 (72) · R6 2263321 (52) · R1 2263373 (165) · R2 2264160 (68) ·
**D1 2311794 (26)** · **D2 2312557 (65)** · **D3 2313053 (42)** · R5 2317031 (62) · R8 2347821 / 2347859 (50) · **D4 2353722 /
2353760 (50)** · hook 2368820 / 2368858 (50). Measured (`overlap_dpatch12.py`, both players): 13 intervals disjoint; no
replacement contains any anchor, its own included; all 6 orders of R1–R5, R6–R8, D1–D4 give identical bytes; every anchor 0
times after, every replacement once. **Rev 10 re-check** (`plan-rev10-2026-10-12/scripts/overlap10.py`, both players): the
anchors and their offsets are unchanged (only D1's replacement changes: 10 237 B in rev 10, 10 249 B in
rev 11, 10 195 B in rev 12, 10 197 B in revs 13–14, 10 571 B in rev 15, 10 559 B in rev 16, 10 305 B in rev 17); the same
five properties hold on both revisions.

### 6.2 Subsystems (files outside `live_runtime.py` that change: `scripts/dissolve_probe.py` (new), `scripts/managed_obs_qualify.py`, their tests, docs)

| Subsystem | Interaction | Change / re-run |
|---|---|---|
| R1–R8 | disjoint bytes; GL renderer | composition test |
| G2 GL replay | WebGL only; a movie G2 is drawing at a transition start is not a visible `<video>` and keeps today's look. G2 has the same untoned step at takeover; `L` could later serve it (separate follow-up) | none; `EXPECTED_STATS` move only with an independent diagnosis |
| Continuity core (main) | D4/D3 touch no `<video>`; `displayScene`'s detach reaches `stash`/`tryRemount` as today. P2 2→3: nothing main paints is visible. P2 slide 4 → end: the bridge (in `#body`, outside the scene) paints at full strength (§1.4) and keeps that slide's freeze from being admitted | **no change (owner Q6)**; `m-bridge` reports the residual (§9.1) |
| **S2** (`d88584eb`) | D4 snapshots whatever S2 shows as slide 2's movie and the copy fades; S2 then holds the decoder at full strength over the fade | **nothing asked of S2's in-flight branch.** After S2 merges, a separate follow-up PR stops painting main's bridge (`keepAtSlot`) and S2's hold at the outgoing transition start (fresh-decoder restarts intact) and makes `m-bridge` blocking |
| `managed_obs_qualify.py` | `mmo-cef` crosses the dissolve (`:611` → `mm_opacity_probe.drive`, `PLAN` has `d23`); `make_export` (`:299`) copies the grey-bug `html-player` PDFs | `--arm dissolve` (DX-2) on the shared resolver; re-run `mmo-cef` |
| `mm_opacity_probe.py`, `mm_handback_probe.py` | cross 2→3 to reach 3→4; score GL frames | re-run |
| `p2_recovery_html_adversarial.py` | the 2→3 movie ROI changes only if its movie's tuple is in `Q` (untagged `p2-binary` copies: Q0b decides); `deliberateRestart2to3` and bridge-off timing read decoder identity/rVFC after the restart | re-run every arm; any moved finding is root-caused (§13) |
| `run_gates.sh` | pins no player sha | no edit; re-run full tier from a fresh pinned worktree |

## 7. Browser support

`plus-lighter`: Chrome 100 (ChromeStatus 5677338286096384); CSS Compositing 2; CSS Transforms 2 §7.1. `checkVisibility`
options: Chrome 121; `VideoFrame(video).colorSpace`: Chrome 94; `:modal` 105, `:popover-open` 114, `:fullscreen` 71 (an
unsupported selector throws inside the take's `try` and skips). OBS 32.2.2 bundles CEF 127: availability only (compositor,
tone path and LUT: DX-2). Headless: Chrome 154.0.8037.59, ANGLE Metal; software compositing via `--disable-gpu`.

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`; Q0b; revs 10–17; hi-DPI and CEF investigations; Q0b-bis)

Builders `dpatch3.py` → `dpatch12.py` (rev 9); drivers `proto3.py` → `proto6.py`, `probe7.py` + `diag7{,b}.js` (one
headless Chrome per arm; `p2cut` = P2 2→3 in Keynote's cut shape, in memory); analysis `analyze_full.py`, `f3analyze.py`,
`f1analyze.py`, `f3model2.py`, `curve.py`, `matched.py`; Node `overlap_dpatch12.py`, `node_ids.py`, `node_r6_test_r12.py`,
`node_r12_near.py`, `node_f3_r12_test.py`, `node_f3_r12_decks.py`; `bake/bake.py`.

**Real P2 DOM, first evidence (Q0b 2; exploratory, untimed, load 6.2–7.0; `runs11/{exact,dbg}/probe7.json`).** Raw player,
`p2-binary`, headless Chrome 154. Rev-7 bytes skipped the slide-2 movie (`<video>` UA `overflow: clip`; seven `preserve-3d`
build wrappers; `body`'s propagated `overflow: hidden` clipped to its zero-height box). A debug build allowing the three
admitted both movies: 2→3 redraws `3231B69B` (build frame, α 1) and `3F22E494` (α 0.2947), take 22 ms; 4→end redraws `2A293753`,
`219585B0`, 20 ms. Rev 9's rules on the recorded computed values (admission and the gate's recorded properties, 53 elements)
admit both; untagged H.264 decodes as `bt709/bt709/bt709/false`. Counter: live 42, 44 (`t23-live-0{0,1}.png`), then 48 in every
fade frame (`t23-fade-00…06.png`, `t23-sheet.png`), square intact; with no rVFC hook, 48 = last presented frame is **not** shown
(Q0b 6 binds it). Not covered: the whole-page gate, DSK, CEF.

**Node, real extracted code, both players (rev 9).** Ids pre-order on the real `VB` classes. All 133 transitions: 46 Dissolves
copied (two rules on exactly the ids `VB` then allocates), 8 cuts, 79 stock, 0 mutations; 21 + 10 near-misses stay stock; five
construction failures build the stock tree. **F3 stub table, 134 rows** (UA-correct, zero-height `body`), video proxy untouched:
one out-of-profile row per property of the movie chain (30), the movie (12), a redrawn canvas or branch (13) and the gate (20
negatives incl. r7's shifted `img`/`canvas`, SVG, column rule, hidden-origin pseudo, `display: contents`; 5 positives), each
skipping; geometry, attach, order, redraw (α 1 / 0.2947 / 0.5), opacity, tuple, `L(128) = 139` and controlled-clock cost rows
(37 on every path); root/body propagation and build-wrapper rows admit.
**Deck stub DOMs** (`node_f3_r12_decks.py`; §1.1's live slide as measured, in document order):

| Slide (outgoing Dissolve) | Movies | Admitted | Redrawn foreground |
|---|---|---|---|
| P2 2 (= DSK 2) | 1 | 1 | square `3F22E494` at α 0.2947 |
| P2 4, DSK 5 | 1 | 1 | none |
| DSK 3 | 2 (≈ 1 px overlap) | 2 | none |
| DSK 7 | 2 (≈ 1 px overlap) | 2 | labels `84D61F77`, `0A370629`, `ED5928A0`; divider and frame canvases (6) |

| Arm (bytes; 1-min load at start) | Mid frames | Max residual (LSB) | Overlap α min | Complement | Notes |
|---|---|---|---|---|---|
| `p2-t-patch` (rev 3; 3.39) / `-noblend` KB (3.17) / `-stock` (2.61); `p2-o-stock` / `-patch` opaque (rev 2; 3.27 / 3.14) | 6 / 6 / 8; 8 / 8 | 1.3 / 64.0 / 206.4; 0.7 / 1.2 | 255 / 191 / 255; 255 | 0 / 0 / 254; n/a | patch: one `startTime`, in − ease ≤ 1e-6; opaque on/off matched ≤ 1.51 |
| `k17-t-patch` DSK 5→6 (rev 2; 3.57) / stock (4.23, exploratory); `p2-t-patch-sw` (rev 1; 4.98, exploratory) | 6 / 6; 4 | 1.5 / 204.5; 2.7 | 255; 254 | 0 / 254; 1 | GPU / software |
| `p2cut-t-stock` / `-patch` (rev 4; 3.34 / 3.33); `p2bin-t-patchdbg` freeze at D4 (rev 4; 3.51) | – ; 11 | – ; 1.7 | – ; 255 | – | cut: stock **both slides** in 2 of 27 rAFs, 1 of 47 screencast frames, patch 0 / 0; freeze: index 56 = last rVFC-presented 56; mid-grey 139 → 128 |

### 8.1 Q0b on rev 9 (2026-10-11; `q0b-2026-10-11/README.md`)

Decision record (headless GPU: tuple `bt709/bt709/bt709/false` for untagged, tagged H.264 and HEVC Main 10; analytic `L`
within 1; software compositing identity, untagged H.264 → `smpte170m…`, HEVC undecodable); host-page engagement (P2 2→3, DSK
2/3/5/7 admitted; P2 4→end blocked by the bridge, as designed); `m-fg` PASS / `-omit`, `-swap` FAIL; dry run of every §9.1
control as expected. **Five re-plan triggers:** DSK 7→8 take 47.6–51.9 ms; raw/preview gate miss on `#slideshowNavigator`;
holder edges up to 78 LSB at full resolution (Pillow-resampled reference); software path needs identity `L` but shares the
tuple; CEF not run. Owner decisions 8–11 (§12) answer them.

### 8.2 Rev 10 prototypes (2026-10-12; `plan-rev10-2026-10-12/`)

Headless Chrome 154, one instance at a time on its own port, two coordinated windows (08:57–09:08, 09:19–09:25). Drivers are
Q0b's (`host_run.py` through `LiveOutputHost` with the served player swapped in-process; `eng_run.py` on the raw export),
extended by `r10.py` (counted-substitution builds: `methods10t()` = §3.1; variants: fractional box, `sn` unrounded splice,
foreground-omit, per-stage timers), `geo10b.py`, `band.py`, `model.py`/`model2.py`/`fit2.py`, `tone10.py`, `stages.py`,
`stubrun.py`, `overlap10.py`. The DSK slide-7 ProRes clips were re-encoded to 12 s H.264 copies (as Q0b, `ultrafast`).

**Browser-rendered references (the measurement the owner asked for first).** After the take, every document animation is
paused and seeked (`currentTime` = 0.5·T, 0.9995·T, 0); each state is screenshotted: `A0` = texture + holder as composited,
`B` ≈ the incoming, `F50`. Progress is then exact and comes from outside the media. Model control `|F50 − (A0 + B)/2|` ≤ 1
over the whole frame in all 14 runs captured in this order (five window-1 runs captured `perfect` before `F50`/`B`, so
only their `A0` is used). Positive control `perfect`: the holder canvas is overwritten with `S_live`'s own
device pixels, then screenshotted (0 wherever the canvas lands 1:1 on device pixels). Holder vs the paused pre-advance
`S_live` (two shots, CvC 0) over the holder region; "tone-comp" applies the decision record's analytic `L` to `A0` there and
excludes the verified redrawn-foreground mask (192 920 of 255 136 px kept at 1080):

| Holder bytes / geometry | Canvas | Interior raw max | Tone-comp max (p99.9; share > τ) | Edge band max | `perfect` |
|---|---|---|---|---|---|
| rev 9 natural size, 1920×1080 | 1920×540 | 78 (already toned) | — | 20 | — |
| fractional device box (window 1), 1920×1080 | 952×268 | 179 | — | 1 | 0 |
| rev 10 with `sn` unrounded (FAIL control `m-snap-frac`) | 952×268 | 212 | 216 (174 p99 at edges; 5.3 %) | 23 | 0 |
| **rev 10, 1920×1080** (exact §3.1 bytes and the DSF-1-equivalent candidate: identical) | 952×268 | 12 (the tone step) | **3 (1; 0 %)** | 1 | 0 |
| **rev 10, letterboxed 1920×1200** | 952×268 | 12 | **3 (1; 0 %)** | 1 | 0 |
| rev 10, DSF 2 (revs 11–12: skipped; rev 13: fix A, §8.5) | 1904×536 | 250 | 250 (244 p99; 7.0 %; 99.5 % within 2 px of a content edge; flat 5) | 1 | INCONCLUSIVE (the transition completed before the capture); 0 for the same canvas box in window 1 |
| rev 10, 2560×1440 (stage scale 4/3; rev 11: skipped) | 1269×357 | 158 | 165 (150; 9.4 %, all on content edges; flat 3) | 12 | 163 (canvas resampled by the compositor) |

Why: the compositor draws the live movie bilinearly into its content box **pixel-snapped** on the stage-local CSS grid (row
and area fits: snapped box mean 0.16 LSB after the tone step, fractional box max 179); the fractional device box (window 1)
missed by a sub-pixel phase, rev 9's natural canvas by a different filter (the compositor mipmaps a canvas scaled below ½).
At DSF 2 the movie's origin snaps on the device grid (x 219) while the holder canvas can only start on the CSS grid (218); at
stage scale 4/3 Blink snaps the canvas in slide px and the compositor resamples it. `imageSmoothingQuality` `medium`/`high`
change nothing for a video source (identical residuals).

**Paint gate on the real pages (raw export of `p2-binary`, navigator present; the gate code is identical in every rev-10
candidate run here, and these runs used the window-1 and snapped-with-DPR candidates).** P2 2→3 and P2 4→end: one holder
each in `layer<out>-opacity` (rev 9: none). Negative controls: a 40×20 px `body` child at x −60 whose 40 px caption overflows
into the stage (border box outside the viewport) → no holder; the thumbnail sidebar slid open (`left: 0`) → no holder.
Host page (DSK 2/3/5/7, P2 2→3): engagement unchanged (gate passes, every Q0b-admitted movie admitted).

**Cost** (`window.__obedTakeMs`; window 1 timed: load < 4 at start, 3.4–3.9 at each take; window 2 alternating rev 9 and rev
10 at load 4.1–5.5, indicative only):

| Take | rev 10 (ms) | rev 9 same window (ms) |
|---|---|---|
| DSK 2→3 / 3→4 / 5→6 (window 1, ×2) | 14.4–14.6 / 15.6–15.7 / 7.7–8.5 | — (Q0b: 14.8–16.9 / 20.1–24.9 / 12.1–14.5) |
| **DSK 7→8** (window 1, ×2) | **9.4, 9.8** | 70.3 |
| DSK 7→8 (window 2, alternating) | 10.7 (profiled), 9.4 | 57.1, 53.8 |
| raw P2 2→3 / 4→end (incl. the exterior proof) | 9.7–15.2 | — (rev 9 skipped the take) |

Per stage, DSK 7→8 (two movies, 312×263 and 468×263 device px): gate 0.6 ms over 195 elements; per movie admission 0.4–0.6,
`VideoFrame` ≤ 0.2, `drawImage` 0.2–0.3, readback 2.0–2.5, alpha scan 1.5–2.2, redraw ≤ 0.1, holder ≤ 0.1. Rev 9 read back and
toned the full 1282×1080 and 1922×1080 frames. **Crop (r8 9):** on every measured slide the region is the whole content box,
so no smaller source crop exists there; no crop A/B has been run, and the ≤ 0.3 ms `drawImage` figure is synchronous call time
(deferred GPU work lands in the readback), so it does not show a crop is useless. Decision 11's crop experiment runs in Q0b-bis
on a clipped diagnostic. DSK 7→8 is the **previous** worst case: in these runs DSK 3→4 (15.6–15.7 ms) costs more; every
measured DSK transition is re-timed on the final bytes before a worst case is named. The window-1 figures are the
fractional-box bytes, which do the same pixel work as §3.1 at DSF 1.

**Tone fixture** (P2 slide 2, the tone movie paused at frame 30, `h264t`, rev-10 bytes and their `m-fg-omit` twin): the
redrawn canvases are `3231B69B` (α 1; 14 640 painted px of its 264 960 px rect — a frame, not a cover) and `3F22E494` (α
0.2947). Painted mask = their α > 0 pixels ∪ pixels where the holder differs from the twin's, dilated 2 px; verified: the twins
differ in 57 400 px, 0 of them outside the dilated α mask. Exposed (cells eroded 2 px): 162/220 ramp steps with ≥ 16 px (10 856
px), 22/28 patches (38 295 px), 8/8 skin patches (15 225 px); `S_live` CvC 0. Identity residual (report-only): mid-grey −11,
max 12.

**Node, real extracted code, both players.** Q0b's §8 rows carried by W1's stub harness (200 rows) on the rev-10 methods: every
invariant holds (no write or call on any stub element, tree and placement unchanged, cost = deterministic work, slot cleared,
every `VideoFrame` closed); 146 rows unchanged; 54 change as designed — no `putImageData` (52), device-pixel holder
geometry and backing (48), redraw coordinates (8), traces (4) — with two flips skip → admit: `fillAspectChange` (aspect test
removed) and `lowerTransparency` (its transparent pixel lies outside the device interior the stub models; W1 re-indexes it).
Extra DPR rows: backings 1904×536 (DSF 2), 1428×402 (1.5), 2539×715 (DSF 2 at 2560). `node --check` passes on all four
patched players; §6.1 re-check as stated.

### 8.3 Rev 11 (r8 fold; Node, real extracted code)

Evidence `plan-rev11-2026-10-12/`. W1's freeze-stub harness with three scratch extensions (`scripts/stubrun11.py`: every stub element carries `localName` /
`namespaceURI`; `document.querySelector` answers the top-layer query; `ext` nests exterior elements under `body`) on the rev-10
and rev-11 methods: 226 rows (200 committed + 26 r8), both players give identical outcomes, and every invariant holds on
every row. The committed 200 rows: rev 11 differs from rev 10 only where meant —
`uniformScale` and `stageNearUniform` now skip (translation-only guard); `baseRectUnequal` scans its whole 952×268 backing.
r8 rows (rev 10 → rev 11):

| Row | rev 10 | rev 11 |
|---|---|---|
| navigator shape: failing text under an off-viewport HTML `div` witness | admit | admit |
| same under a `visibility: hidden` parent with `filter: drop-shadow(300px 0 0)` / `-webkit-box-reflect` | **admit** | skip / skip |
| same under a hidden parent without effects | admit | admit |
| a `:modal` / `:popover-open` / `:fullscreen` element present | **admit** | skip |
| SVG `g` (`display: block; position: relative; overflow: hidden`) as witness under a hidden `svg` | **admit** | skip |
| witness meets `V`; witness `static`; witness `overflow: auto`; witness with a shadow; a `fixed` element between | skip | skip |
| transformed descendant of a valid witness; `iframe` under a valid witness | admit | admit |
| `iframe` without witness; overflowing caption without witness | skip | skip |
| DPR 1.5, `fill` 313×263 (backing 470×395) | **admit, reads 469×394** | skip (guard) |
| DPR 1: transparent last backing column / last row | — | skip / skip |
| DPR 2; stage scale 4/3; stage scale 0.75 (stage transform modelled) | admit | skip (guard) |
| letterbox (stage scale 1, offset 60) | admit | admit |
| fractional letterbox origin (y 60.5) | admit | skip (guard) |
| `matrix(1.5, 0, 0, 1.5, 0, 0)` below the stage / `matrix(1, 0, 0, 1, 0.5, 0.25)` | **admit** / admit | skip / admit |

`node --check` passes on both patched players (`on`, `rendering`); the §6.1 re-check holds with D1 at 10 249 B.

### 8.4 Rev 12 (r9 fold; Node, real extracted code)

Evidence `plan-rev12-2026-10-12/`. The rev-11 harness plus `shadowRoot` on every stub element (`x.shadow` makes an open
root): 234 rows (200 committed + 26 r8 + 8 r9) on both players, identical outcomes, every invariant holding; admitted rows
65 (rev 11) → 47 (rev 12). r9 rows:

| Row | rev 11 | rev 12 |
|---|---|---|
| exterior `script` rendered `display: block` with overflowing text, box at x −60 | **admit** | skip |
| rendered, hidden `head` with `drop-shadow(300px 0 0)` over a valid witness | **admit** | skip |
| `script` / `head` + `style` with text at the UA default `display: none` | admit | admit |
| off-stage host with an open shadow root | **admit** | skip |
| live base-layer box 960×1080 (`kx` = 2; rev 11 attached the holder at x 218, width 1 904) | **admit** | skip |
| live base-layer box 1920×1079.5 (fractional `ky`) | **admit** | skip |
| full-slide base layer | admit | admit |

Committed rows that change: the nine `gate_*TextIgnored` rows (the stub renders metadata `display: block`; W1 gives them the UA
`display: none` → admit, and adds the rendered variants → skip), and `stage2560`, `stageScaledInSmallViewport`, `letterbox` (at
0.75), `baseRectUnequal` (now skip by `kx`/`ky` even without the stage transform modelled). **Shadow-DOM invariant check:**
`attachShadow`, `shadowRoot`, `shadowroot`, `customElements` occur 0 times in both supported players, the P2 export
`index.html` and `src/obed_edom/`. `node --check` passes on all four patched players; §6.1 holds with D1 at 10 195 B.

### 8.5 Hi-DPI investigation and rev 13 (2026-10-12; `hidpi-2026-10-12/README.md`, `plan-rev13-2026-10-12/`)

A separate investigator (headless Chrome 154, four coordinator windows, untimed) measured holder variants against the live
movie on a replica of the live slide DOM (synthetic H.264 patterns; a translation-only P2-like chain and a DSK-like chain with
a nested 1.0008/0.9993 scale) and on the **real P2 slide-2 DOM** (raw export, movie paused, later canvases hidden),
tone-compensated with the decision record's analytic map, τ = 4, with a 1-px checker landing control. Its instrument's floor
at the qualified geometry is max 11 over 5 px (the same for every variant, rev 10 included; rev 10's DX-1-style `m-snap`
reads 3 there).

| Real P2 slide 2 | rev 10/12 bytes (`r10t`) | **fix A** (`r10s`: stage-local 1/DPR grid) | option B (compensating transform + model O) |
|---|---|---|---|
| 1920×1080 DSF 1 | 11; 5 px of 257 580 (floor) | 11; 5 px | 11; 5 px |
| DSF 1.5 | 252; 39 679 px (6.9 %) | **11; 17 px of 575 887** | — |
| DSF 2 | 252; 55 661 px (5.4 %) | **11; 20 px of 1 022 985** | 11; 20 px |
| fractional letterbox (1920×1201) | 11; 5 px | **11; 5 px** | (not 1:1) |
| stage 4/3 | 164 / 9.13 % | 162 / 9.33 % | 83 / 5.13 % (replica 3 / 0 %) |
| stage 4/3 @ DSF 2 / stage 2/3 | 226 / 6.54 %; 172 / 13.9 % | 88 / 6.37 %; 160 / 15.0 % | 84 / 4.83 %; 87 / 4.26 % |

Root causes (from Chromium source: `video_painter.cc`, `html_canvas_painter.cc`, `layout_video.cc`, `pending_layer.cc`,
`skia_renderer.cc`; same in M127): at DSF ≠ 1 the movie's edges snap on the stage-local device grid while rev 10/12 snapped the
holder on the slide-px grid (one device px off); the holder canvas lands 1:1 (checker 100 %); compositor quads sample plain
bilinear and the live downscale matches canvas-2D `drawImage` at device size (≤ 2 LSB), so mirroring the transform chain is
refuted (88–255 everywhere). At stage scale ≠ 1 the movie quad's origin rounding is chain-dependent (option B reproduces the
replica, not the real P2 chain). The DSK-like nested anisotropic scale makes the screen-space `contain` solve pick the wrong
axis (content width 312.213 vs Blink's 312.656: 249–255 for every rev-10-style variant). **Owner decision 12 (~11:45):
adopt fix A, keep skipping scaled stages.**

**Rev 13 bytes (Node, real extracted code, both players).** Fix A is `sn(z) = round((z − e)·k·p)/p` plus the guard change
(`devicePixelRatio` ∈ {1, 1.5, 2}; the integer-origin condition dropped): D1 10 197 B; `node --check` passes on all four
patched players; §6.1 holds. W1's committed 260-row harness (HEAD `6d35559a`, copied to scratch, unedited) runs clean on the
rev-12 bytes; on rev 13 exactly four rows change as designed — `dpr2` (backing 1904×536), `dpr15_fillOpaque` (snapped
`[109.333, 795.333, 312.667, 262.667]`, backing 469×394), `stageFractionalOrigin`, `stageFractionalOriginX` now admit — and
with five added rows (`dpr125` and `dpr3` skip; `dpr15_p2Box` admits at 1428×401; a transparent last pixel at DPR 1.5 and at
DPR 2 skips) all 265 rows match the rev-13 expectations on both players, every invariant holding (`run13.py`, `exp13.py`).

### 8.6 Q0b-bis, the CEF investigation and rev 15 (2026-10-12; `q0bbis-2026-10-12/`, `cef-frac-2026-10-12/`, `plan-rev15-2026-10-12/`)

**Q0b-bis on the rev-13 bytes** (headless Chrome 154 and OBS 32.2.2 / CEF 127.0.6533.120 through `ManagedObs`, never together;
timed takes at load < 4): engagement PASS — host P2 2→3 one holder, P2 4→end none (bridge), DSK 2/3/5/7 1/2/1/2; raw P2 2→3
and 4→end one each, `svgclip` admitted, every exterior negative refused at its expected check. Cost PASS — DSK at DSF 1 ≤ 13.4
ms, DSK 7→8 at DSF 2 15.1–18.3 ms, CEF DSK 7→8 11.7–34.8 ms. Matrix PASS: all 18 DPR × origin × clip cells one holder, holder
max 3 (0 % > τ, flat ≤ 1), `perfect` 0/0, clip edge bands included; four DPR-1.5 cells INCONCLUSIVE on the production-mask
excess rule (1.05 %, 6.8 % from BOX-resampled α at a non-integer scale), 3 / 0 % under the exact twin-difference mask.
**Instrument lessons:** CDP `Emulation.setDeviceMetricsOverride` smooths composited canvases (even `perfect` reads 144 / 231),
so DPR arms launch Chrome with `--force-device-scale-factor`; at DPR 2 `perfect` needs the player's teardown timer delayed.
**Controls:** `perfect-shift` FAIL (255 / 64); `m-snap-frac` FAIL at DPR 1.5 (93 / 4.5 %) and 2 (42 / 2.8 %), but at DPR 1
it binds no holder (the unrounded edge is partly covered and the full-backing alpha scan rejects it). **W5 (indicative):** GPU
+11 at mid-grey vs software identity, distinguishable on composited pixels, launches identical, CEF = GPU; GPU-state
invalidation untested. **The trigger:** CEF holder vs live 183 max, 3.1–6.1 % > τ, all within 2 px of edges — CEF 127 draws the
video quad unsnapped (edge offset −0.356 px on average; headless 0.000).

**CEF investigation** (four OBS launches, untimed): drawing the snapped frame as an underlay and the fractional quad on top
(`fdrawu`, +186 B) reads **2 / 0 %** in CEF (launches 1 and 4) but 183 / 6.12 % in Chrome 154; the snapped draw reads 3 / 0 %
in Chrome 154 (DPR 1 and 2) and 183 in CEF. A fractional draw alone binds no holder (antialiased edge column). No in-page
discriminator exists; the host-side probe separates the engines (correct rule ≤ 0.58 %, wrong rule ≥ 39.8 %).

**Rev 15 bytes (Node, real extracted code, both players).** D1 10 571 B (+374 over rev 13: flag read and guard, integer
`left`/`top`, the frac draw); `node --check` passes on all four patched players; §6.1 holds. W1's committed harness (HEAD
`7834624c`, 266 rows, copied to scratch) with three scratch extensions (BASE `left`/`top` `0px`; the placement per row,
default `snap`; trace pattern `vv?`): all 266 rows unchanged under `snap`, and 13 new rows match — flag absent / `unknown`
skip; `frac` admits at DPR 1 with two movie draws (on P2's fractional box the second lands at (0.352, 0.036), 951×268); `frac`
at DPR 1.5 / 2 and at a fractional stage origin skip; `frac` with a fractional translation admits; fractional `left` / `top`
and `left: auto` skip, a negative integer `left` admits — on both players, every invariant holding. The `m-snap-shift` splice
`s.left=a0+"px"` → `s.left=a0+1/p+"px"` and rev 13's `m-snap-frac` anchor each occur exactly once on both players and twins.

### 8.7 Rev 16 (r12 fold; Node; `plan-rev16-2026-10-12/`)

- **Bytes:** the take reads `pl=window.__obedPlacement` (rev 15: `(window.__obedCalib||{}).placement`); D1 10 559 B;
  `node --check` passes on all four patched players; §6.1 holds.
- **Harness:** W1's committed harness (HEAD `7834624c`) runs with the placement as a per-row getter: 284 rows (279 checked,
  5 traced only), 0 differ, both players identical, every invariant holding.
- **Clipped `frac` rows:** P2's fractional box with a far-side clip at x 709.722 / y 930.406 draws the fractional quad at
  (0.352, 0.036), as unclipped. A near-side clip (region from 300.4, 850.3) draws it at (−190.648, −54.964), with the snapped
  underlay at (−191, −55).
- **`nooffset` controls:** the x splice moves the near-side quad to x 0.352 and the y splice to y 0.036; on far-side clips they
  change nothing. So the wrong-offset control is only meaningful on near-side clips, which is why `m-snap-cef[clip]` includes
  them. All three control splices (`nooffset-x`, `nooffset-y`, `shift`) occur exactly once on both players and their omit twins.
- **Calibration channel** (`calib/init.js`, `calib/test.js`, `calib/result.json`): the host token sets `snap` and `frac`;
  page-code assignment (sloppy and strict), `delete`, accessor redefinition (`TypeError`), updater replacement, a wrong token
  and a tampered `performance.now` cannot change or keep the value; a lease lapses after its TTL (15 s cap), revocation reads
  `invalid` at once, unknown values read `invalid`, the updater's source text does not reveal the token, and a predefined
  getter makes the init script throw (no updater; the host's round trip then fails).

### 8.8 Rev 17 (decision 15; Node; `plan-rev17-2026-10-12/`)

- **Bytes.** `methods17()` is rev 13 plus three things: the grant read `pl=window.__obedPlacement`, the guard `"snap"!==pl`, and
  integer `left`/`top`. There is no `frac` draw. D1 is 10 305 B; `node --check` passes on all four patched players; §6.1
  holds. The `m-snap-shift` splice and rev 13's `m-snap-frac` anchor each occur exactly once on both players and twins.
- **Harness.** W1's committed harness (HEAD `7834624c`) with the placement as a per-row getter: 285 rows (284 checked), 0
  differ, both players identical, every invariant holding. Every `frac` row and `SNAP` now skip; `snap` rows are unchanged.
- **Grant channel** (`grant/init.js`, `grant/test.js`, `grant/result.json`):
  - a fresh document reads `invalid`, and the host round trip reads `true, snap, true, invalid`;
  - assignment (sloppy and strict), `delete`, accessor redefinition, forging `snap` by assignment or redefinition, updater
    replacement and a wrong token all leave the host's value;
  - only `snap` can be granted (`frac` reads `invalid`), and the token is not in the updater's source;
  - a predefined getter makes the init script throw, leaving no updater.

## 9. Acceptance

**Rule.** Every blocking check has a positive control that must PASS and a negative control that must FAIL, read before the
candidate counts. Missing or malformed evidence is INCONCLUSIVE and invalidates the round; INCONCLUSIVE never satisfies an
expected FAIL. One headless Chrome at a time; 1-min load < 4 and no other headless Chrome at start; no OBS during headless runs.

| Check | Positive (PASS) | Negative (FAIL) |
|---|---|---|
| Model (texture group) | `opaque-off` | `off`, `noblend` |
| Complement | `noblend` | `off` |
| No dip | `opaque-off` | `noblend` |
| Curve / Monotone | rAF of `on2` / `opaque-off` | scorer cases: linear curve / non-monotone e |
| No flash | `delay-on` | `delay-off` |
| Screen path | `screen-on` | `screen-off` |
| Hand-off | `off` and scorer case: unchanged | scorer case: injected step above τ |
| Cut swap | `cut-on`; scorer case: complementary (0.5, 0.5) | `cut-off` |
| Frozen frame (index, constancy) | `m-paused` (frame known in advance) | `m-off` (baked frame) |
| Frozen region fades | `m-on` | `m-hold` (full-strength copy) |
| Foreground preserved and ordered (tone-invariant) | `m-fg` | `m-fg-omit`, `m-fg-swap`; scorer cases: shifted, double-painted, swapped |
| Holder pixels (browser-rendered; tone-compensated; qualified geometry, production mask) | every cell of `m-snap[dpr, origin, clip]` (§9.0 item 5) | `m-snap-shift[dpr]` (holder one device px right) at DPR 1, 1.5 and 2, and `m-snap-frac[dpr]` (`sn` unrounded) at DPR 1.5 and 2; scorer case: 1-px shifted holder under the production mask |
| Reference capture (instrument, r8 7) | `perfect` on every `m-snap*` arm; scorer case: valid reference set | `perfect-shift` (canvas overwritten 1 px off) FAIL; scorer cases: stale/reused frame, missing or extra animation, unpaused animation → INCONCLUSIVE |
| Foreground mask (instrument, r8 6) | production mask on every twin pair (missed 0, excess ≤ 1 %) | scorer cases: whole-rectangle, 3-px shifted, empty mask → INCONCLUSIVE (rejected before scoring) |
| Geometry guard (decision 12, fix A) | every `m-snap[dpr, origin, clip]` cell (holder bound at stage scale 1, full-slide base layer) | `m-geo-dpr125`, `m-geo-2560`, `m-geo-scale`, `m-geo-base` (published take, no holder) |
| Exterior gate (raw / preview pages engage; unproven exterior paint skips) | `m-raw` (P2 2→3, 4→end; the ordinary page), `m-raw-svgclip` (SVG under an HTML-`div` witness) | `m-raw-caption`, `m-raw-nav-open`, `m-raw-modal`, `m-raw-svg` (false SVG witness), `m-raw-script` (rendered `script` text), `m-raw-shadow-modal`, `m-raw-shadow-fixed` |
| Hide / show capture (instrument, r8 8) | `life-hide` (alpha) and `life-hide-screen` twins: transparent / black frames inside the hidden interval, six timestamped mid frames after show | `life-hide-nohide`, `life-hide-noshow` (driver drops the action) FAIL; scorer cases: duplicate frame, timestamp shift → INCONCLUSIVE |
| Tone match — blocking only if a non-identity `L` returns (W5); report-only under identity | (`m-tone`) | (`m-tone-raw`) |
| No independent overlay | `m-on` | `m-bridge-off` (stock twin) |
| Grant channel (r12 1; decision 15) | Node: the host token grants and revokes; `grant-chrome` (host-launched Chrome 154, GPU) → `snap` committed after the round trip, the take binds a holder | Node: page assignment / delete / accessor redefinition / forged `snap` / updater replacement / wrong token / predefinition → no grant; `grant-attach` (attach mode), `grant-cef` (managed OBS), unit cases `Chrome/153`, `Chrome/155`, `HeadlessChrome/154` with `gpu_compositing` disabled, version call failing → no grant, no holder, reason recorded; live `channel-predefined` (an extra CDP script defines the getter first) → `channel-compromised`, `show` refused |
| Grant lifecycle (r12 4) | `life-grant-valid`: the committed grant freezes the next take | `life-grant-reload` (fresh document `invalid` until its own round trip), `life-grant-navcommit` (navigation between round trip and commit → the old context's evaluate fails, nothing installed) → no holder; unit: `gpu_compositing` no longer enabled at `observe()` → revoked |
| Preview / raw / CEF scope (decisions 14–15) | — | `m-raw-prod`, `m-preview-prod` (production pages, no channel) and `cef-skip` (managed OBS, DX-2) → no holder (stock movie behaviour), reason recorded, cross-fade model PASS |
| Cost | scorer case: 50 ms; stub rows: total published on success, rejection, exception | scorer case: 50 ms + ε (missing or non-finite → INCONCLUSIVE) |

### 9.0 Q0b-ter — step 0 on the rev-17 bytes and W6's grant (scratch; before DX-1; windows on request)

Done: Q0b on rev 9 (§8.1); rev-10 prototypes (§8.2); revs 11–13 Node rows (§8.3–8.5); Q0b-bis and the CEF investigation (§8.6);
revs 15–17 Node checks (§8.6–8.8). Pending (a miss re-plans):
1. **Grant on real engines:** `grant-chrome` (headless and headed HDMI host: `snap` committed after the round trip, the take binds
   a holder); `grant-attach`, `grant-cef` (no grant; reasons `attached`); `channel-predefined` (`show` refused); `life-grant-*`.
2. **Holder pixels, Chrome 154, exact rev-17 bytes:** `m-snap` base cell and `m-snap-shift[1, 1.5, 2]` / `m-snap-frac[1.5, 2]`
   (the snapped path is unchanged since rev 13, so the Q0b-bis matrix carries; its four DPR-1.5 cells re-read with the
   draw-mapped mask).
3. **Engagement and scope:** host Chrome pages as in Q0b-bis; `m-raw*` exterior controls through the privileged channel;
   `m-raw-prod`, `m-preview-prod` and CEF `cef-skip` → no holder, cross-fade intact, reasons recorded.
4. **Still open from Q0b-bis:** the crop experiment; dry runs of `m-geo-*`, the hide rows, D2 `on`, `m-tone` with its twin. DPR
   arms run with a real `--force-device-scale-factor` and, at DPR 2, the teardown timer delayed for `perfect`. (CEF tone and the
   CEF holder matrix move to the follow-up PR, §13.1.)

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver (W2; reused by W3; read-only).** Stock `index.html`, player, slide JSON from `html-unmodified`; PDFs from a fresh
  scratch strip (715cb3f1's stripper); movies mapped to decodable copies (P2: `html-player` H.264; DX-M: the binary counter
  re-encoded BT.709-tagged into scratch unless Q0b qualifies the untagged tuple; tone arms: the **tone movie**, same encoder:
  counter strip, 220-step luma ramp, 25–100 % colour patches, skin tones, in Q0b 1's encodings). Provenance recorded.
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1 unless the arm says otherwise, own port (never 9222);
  `LiveOutputHost` attach or launch; `m-raw*` arms serve the resolver's export as-is (its own `index.html`, navigator present)
  over the same static server and advance with Space over CDP; the exterior-gate `m-raw*` arms install the host's first-run
  script and commit `snap` through the privileged channel before the advance (`m-raw-prod` / `m-preview-prod` do not); DPR arms launch Chrome with `--force-device-scale-factor` (CDP
  emulation smooths composited canvases, §8.6). Every host arm runs the startup probe first and records its result; a probe
  that does not return the engine's expected rule makes the arm INCONCLUSIVE. **Geometry classes (decision 12, fix A):** *qualified* = DPR 1,
  1.5 or 2 at stage scale 1, base-layer box = slide, translation-only scene transforms, any letterbox origin (1920×1080,
  letterboxed 1920×1200 and 1920×1201, each at DPR 1, 1.5 and 2, unclipped or fractionally clipped: the `m-snap` matrix) — every
  check blocking, `m-fg` included at DSF 1.5 and 2;
  *outside the guard* = everything else (other DPRs, stage scale ≠ 1, nested scales, a mismatched base layer) — the only check
  is that the take skips (`m-geo-*`). A later model for scaled stages enters the same way: each geometry it admits becomes a
  qualified class with every safety check (opaque cover of every backing pixel, exterior proof, clipping, foreground
  preservation, `m-fg`) blocking and the holder-pixel criterion it is shown to meet; nothing outside a demonstrated class is
  admitted.
- **Instrument.** Innermost hook from the first rAF with the transition DOM: each leaf's effective opacity (also before any
  animation attaches), every transition animation (`currentTime`, `startTime`, value), scene/hash; every `<video>` tagged
  (`WeakMap` id) with rect, effective opacity, transition-DOM membership, colour tuple, rVFC records and detach time;
  `window.__obedTakeMs`; at that first rAF the textures, every holder (`toDataURL`, slide-px geometry) and the blend/isolation
  chain. Alpha PNG screenshots from 0.35 s before the advance to T + 0.6 s; cut arms **and the hide / hide-screen lifecycle
  rows** add a per-frame screencast (each frame with its CDP timestamp and the matching rAF log time).
- **Reference-capture profile (`m-snap*`, `m-tone`, their twins; paused; r8 7) — a separate profile, not a fade arm.** After
  the first transition rAF: the **animation inventory** (exactly the two transition animations, on `layer<in>-opacity` and
  `layer<out>-opacity` for a Dissolve, nothing else running) is recorded; every document animation is paused and seeked to
  0.5·T, 0.9995·T and 0; at each state the driver reads back `playState` `paused`, each `currentTime` (± 1 ms) and the leaves'
  rendered effective opacities (0.5 / 0.5 ± 1e-3; ≥ 0.999 incoming; 0 / 1), then takes two screenshots that must be identical
  (stable) — `F50`, `B`, `A0`; finally `perfect` overwrites the holder canvas with `S_live`'s own device pixels (and, in
  `perfect-shift`, one device px off) and is screenshotted twice. Required images: `S_live` ×2, `F50`, `B`, `A0` ×2 each,
  `perfect` ×2. **Temporal qualification is not taken from this profile:** fade coverage (≥ 6 mid frames, ≥ 3 demixable frames
  with pairwise Δe ≥ 0.1) stays with the timed arms (`m-on`, `m-paused`, `on`, …) and their unchanged rules.
- **Foreground inventory (r8 6).** Before the advance the hook records every canvas later in document order than the movie
  that meets its region (independently of the take): `toDataURL`, CSS rect, effective opacity, document-order index. The
  **production mask** maps each canvas's α > 0 support to device px through the take's own snapping (`sn`, backing = rect ×
  DPR), dilated 2 px, restricted to the holder region. At a non-integer device scale the α support is mapped the way the take draws
  it (the canvas drawn into its snapped device rect, α > 0 read back), not by a box resample: Q0b-bis's box-resampled masks
  over-masked four DPR-1.5 cells (excess 1.05 % and 6.8 %, missed 0); Q0b-ter re-reads those cells. Every reference geometry runs a same-frame `m-fg-omit` twin; the twin
  difference (holder vs twin holder, `toDataURL`, exact) is the known raster control.
- **Scorer (pure, every pixel of the mask; reused by DX-2).** A = outgoing texture with the holders pasted at their device
  rects (exact at stage scale 1: the holder backing is device pixels; no resampling), B = incoming,
  premultiplied; per admitted screenshot e by least squares on the texture group outside every media rect + 2 px; residual
  `|F − ((1−e)·A + e·B)|` there. Screen arms: RGB vs the cross-fade over black. **Media (DX-M):** each holder binds to the one
  tagged decoder whose admitted region maps to its rect (± 1 px; none or several → INCONCLUSIVE); its reference is that
  decoder's last rVFC record before its detach. The strip is decoded from the holder (at its device scale: content-box offset
  in the canvas and `dw / videoWidth`) and from `Ô = (F − e·B)/(1 − e)` on
  admitted frames with e ≤ 0.8, ≥ 3 of them with pairwise Δe ≥ 0.1; never from raw screenshots. **Independent references
  (paused arms):** the last pre-advance live screenshot `S_live` (compositor-painted before D4 runs) is ground truth for the
  movie region; the holder and every `Ô` are compared with it, never with texture + holder. **Holder pixels (`m-snap*`):**
  `|L_path(A0) − S_live|` over the holder region (interior = inset 1 device px; edge band = the rest), outside the verified
  painted-foreground mask; `L_path` = the decision record's measured map for the arm's compositing path (headless GPU: the
  analytic table, within 1 of measurement; software: identity), so the known tone limit is not read as geometry. **Mask
  verification before scoring:** *missed* support = twin-difference px outside the dilated production mask must be 0;
  *excess* support = production-mask px farther than 2 px from any twin-difference px must be ≤ 1 % of the mask (tone twins:
  57 400 / 57 400 px, missed 0, excess 0; a whole-rectangle mask has 75.6 % excess, a 3-px shift 398 missed px, an empty mask
  misses all — each rejected, INCONCLUSIVE). The production mask must leave a shifted holder detectable (scorer case: 1 px
  shift FAIL; measured `m-snap-frac` with it: 5.3 % of the kept px > τ).
- **Capture integrity (any violation INCONCLUSIVE):** texture ids, hash before/after, screenshot size, page mode and served
  digest as stated; finite, non-empty measurements; fade arms ≥ 6 mid frames (0.05 < e < 0.95, transition DOM present); delay
  arms ≥ 2 screenshots and rAF coverage in the window; cut arms rAF coverage from DOM insertion to 3 frames after the cut and a
  screencast frame inside; paused arms two identical `S_live`; media arms the evidence below; lifecycle rows a settled frame;
  **hide rows (r8 8)** ≥ 1 screencast frame wholly inside the hidden interval and **six distinct, correctly timestamped
  mid-progress frames after show** (distinct content hashes; CDP timestamps strictly increasing and within one rAF interval of
  the matching rAF record; e from the rAF log in (0.05, 0.95)); **reference arms** the full reference-capture profile above
  (inventory exact, paused, `currentTime` and rendered opacities as requested, stable pairs, `A0`, `F50`, `B` pairwise
  different in the texture group where A and B differ by > 30, the transition DOM present at every capture, and
  `|F50 − (A0 + B)/2|` ≤ 2 over the frame, measured 1); tone arms the mask verification above and coverage: a cell (ramp step or patch, eroded 2 px) counts with ≥ 16 exposed px,
  and ≥ 50 % of the ramp steps and of the patches must count (measured 162/220, 22/28, skin 8/8).

| Check | Threshold (measured) |
|---|---|
| Model | every mid frame max residual ≤ τ = 4 LSB (1.3–1.5 GPU, 2.7 software; KB 64, stock 205–206) |
| Complement | every admitted frame: \|α_in-only + α_out-only − 255\| ≤ 2 (0; stock 254) |
| No dip | α ≥ 252 on the **both-opaque class** (`α_A = α_B = 255`; α does not depend on colour, so no colour-difference filter): 255 / 254; KB 191. D2 2→3 has 180 687 such px but 0 differing ones, which made rev 9's filtered class INCONCLUSIVE |
| No flash | effective incoming opacity 0 in every rAF before the first animation frame |
| Curve | two animations, one `startTime`; \|in + out − 1\| ≤ 1e-5; \|in − ease-in-out(ct/T)\| ≤ 1e-4 |
| Monotone | e non-decreasing (−0.01 slack), ≥ 0.99 before the hand-off |
| Hand-off | H = max premultiplied \|first-live − last-transition\| outside the destination's movie rects on the identified frames (either missing → INCONCLUSIVE); H ≤ τ |
| Cut swap | every rAF from DOM insertion: incoming 0 before the cut's first animation frame, then in + out = 1 ± 1e-3 until incoming 1; every screencast frame \|α_in-only + α_out-only − 255\| ≤ 2 (stock: 510) |
| Frozen frame | per bound holder: decoded index = its reference frame (offset 0, §8), and `Ô` decodes to it on every admitted frame |
| Frozen region | `Ô` in the movie region constant over the admitted frames (spread ≤ τ/(1 − e)) |
| Foreground preserved | holder and every `Ô` vs `S_live` on the counter-block pixels under the foreground (0/255 on every tone path) ≤ τ |
| Holder pixels | qualified classes only: interior and edge band max ≤ τ = 4 under the verified production mask (1920×1080 and letterboxed: 3 and 1 with the DX-1 instrument; DSF 1.5, DSF 2 and the fractional letterbox at the investigation instrument's floor, §8.5 — first DX-1-instrument reading in Q0b-bis; FAIL control `m-snap-frac` 216, 5.3 % of px > τ) |
| Reference capture | `perfect` interior and edge max ≤ 1 (measured 0); `perfect-shift` > τ; profile integrity as above |
| Geometry guard | qualified: one bound holder per admitted movie; `m-geo-*`: a published take, the transition DOM present, no holder (stage 4/3: 162 / 9.3 % even with fix A, §8.5) |
| Exterior gate | `m-raw`, `m-raw-svgclip`: each take publishes `__obedTakeMs` and binds one holder in `layer<out>-opacity`; negatives (`-caption`, `-nav-open`, `-modal`, `-svg`, `-script`, `-shadow-modal`, `-shadow-fixed`): a published take, the transition DOM present, and no holder (measured on rev 10: 1 / 1 holder; caption and open navigator 0 / 0) |
| Hide / show | inside the hidden interval: alpha page α ≤ 2 everywhere / screen page RGB ≤ 2 everywhere; after show: the model holds (≤ τ) on six distinct mid frames; `life-hide-nohide` must FAIL the first, `life-hide-noshow` the second |
| Tone match | identity `L` (shipped): holder vs `S_live` per channel on the verified exposed mask, `S_live` CvC ≤ 1 — **reported** (measured: mid-grey −11, max 12); blocking at ≤ 2/255 only if W5 brings back a non-identity `L`, with `m-tone-raw` as its FAIL control |
| No independent overlay | in every rAF of the fade no tagged `<video>` outside the transition DOM with effective opacity > 0 meets the outgoing movie rect, and `Ô` there does not drift |
| Cost | `window.__obedTakeMs` finite and ≤ 50 ms per take |

**Per-arm contract** (required classes ≥ 2 000 px; deviation INCONCLUSIVE):

| Arm | Deck / bytes | Required classes | Checks → expected | Styles | Served digest |
|---|---|---|---|---|---|
| `on` | P2 2→3, DSK 5→6 (alpha) | out-only, in-only, overlap | all → PASS | leaves `plus-lighter`, container `isolate` | pinned `on` |
| `on` D2 | D2 2→3 | both-opaque (no dip), fit pixels (model) | model, no dip, curve, monotone, hand-off → PASS; complement N/A (out/in-only 19 / 22 px) | as `on` | pinned `on` |
| `on2` | P2 | as `on` | CvC: residual distribution within 1 LSB of `on` | as `on` | pinned `on` |
| `off` | P2, DSK 5→6 | out-only, in-only | complement, model → FAIL; hand-off → PASS | none | pinned `off` |
| `noblend` | P2 | all three | no dip → FAIL; complement → PASS | leaves `normal`, container `isolate` | pinned `on` + one counted splice (`plus-lighter` → `normal`, 2 occurrences) |
| `opaque-off` / `-on` | P2, unstripped | overlap | model, no dip, monotone, hand-off → PASS; matched on/off reported (bound 2) | none / as `on` | `off` / `on` |
| `screen-off` / `-on` | P2 stripped, screen path | out-only, in-only | RGB vs cross-fade over black → FAIL / PASS | none / as `on` | `off` / `on` |
| `delay-off` / `-on` | P2; one counted splice `},1e3*g)` → `},1e3*g+300)` | in-only | in-only α in the window 255 → FAIL / 0 → PASS | none / as `on` | base + splice |
| `cut-off` / `-on` | `p2cut` (P2 2→3 as a cut, in memory) | out-only, in-only | cut swap → FAIL / PASS | none | `off` / `on` |
| `m-on` | `p2-binary` 2→3 through `LiveOutputHost` (continuity on) | out-only, in-only | frozen frame, frozen region, model, no independent overlay, cost → PASS | as `on` + one holder | pinned `on` |
| `m-paused` | as `m-on`, the movie paused on a known frame before the advance | as `m-on` | frozen index = that frame exactly → PASS | as `m-on` | pinned `on` |
| `m-off` | as `m-on`, patch off | out-only, in-only | frozen frame → FAIL | none | pinned `off` |
| `m-hold` | as `m-on`; one counted splice appends the holder to the container instead of the wrapper | as `m-on` | frozen region → FAIL (`Ô` drifts with 1/(1 − e)) | as `on` | base + splice |
| `m-fg` / `m-fg-omit` / `m-fg-swap` | `m-paused` + in-memory: two distinguishable opaque texture layers added to the movie's `renderMovie` build tree (inside the seven `preserve-3d` wrappers), overlapping each other over the counter blocks, and P2's square moved there / + one counted splice `Y.forEach(` → `[].forEach(` / + `Y.forEach(` → `Y.reverse().forEach(` | out-only | holder and every `Ô` vs paused pre-D4 `S_live` ≤ τ on counter-block pixels → PASS / FAIL / FAIL; missing overlap, reference or engagement → INCONCLUSIVE (model N/A: live-only edit) | as `on` + one holder | pinned `on` / + splice |
| `m-tone` (+ its `m-fg-omit` twin) | tone movie on P2 slide 2, paused at frame 30; reference capture; twin = + splice `Y.forEach(` → `[].forEach(` (mask verification only) | out-only | tone match → REPORTED (identity `L`); `m-tone-raw` not run while `L` is identity | as `on` + one holder | pinned `on` / + splice |
| `m-snap[dpr, origin, clip]` (one parametrized arm; + same-frame `m-fg-omit` twin per cell) | `m-paused` over the §9.0 item-5 matrix: DPR {1, 1.5, 2} × origin {integer (1920×1200 CSS, y 60), fractional (1920×1201 CSS, y 60.5)} × clip {none, fractional x, fractional y (in-memory clipping layer)}, 18 cells; plus the 1920×1080 base cell; reference-capture profile; twin = + splice `Y.forEach(` → `[].forEach(` | out-only | holder pixels → PASS; `perfect` → instrument PASS; mask verification PASS | as `on` + one holder | pinned `on` / + splice |
| `m-snap-frac[dpr]` (+ twin) | as `m-snap` 1920×1080 at DPR 1.5 and 2 (at DPR 1 the unrounded edge is partly covered, the alpha scan rejects it and no holder binds — measured, so it cannot give its FAIL there); one counted splice `sn=function(z,e,k){return Math.round((z-e)*k*p)/p}` → `sn=function(z,e,k){return(z-e)*k}`, exactly once on both players and on their omit twins (checked: 1 → 0, replacement 1; rev 12's anchor occurs 0 times in rev-13 bytes) | out-only | holder pixels → FAIL (displaced edges) | as `m-snap` | base + splice |
| `m-snap-shift[dpr]` (+ twin) | as `m-snap` 1920×1080 at DPR 1, 1.5 and 2 (real force flag); one counted splice `s.left=a0+"px"` → `s.left=a0+1/p+"px"` (the holder one device px right, every backing pixel still opaque; once on both players and twins) | out-only | holder pixels → FAIL (displaced edges) — the DPR-1 displaced-edge control | as `m-snap` | base + splice |
| `m-raw-prod` / `m-preview-prod` | the production raw export page / Build Preview (`patch_rendering`) for P2 2→3, no first-run script, no injection | out-only | no holder (stock movie behaviour) and model PASS (decision 14) | as `on` | pinned `rendering` |
| `grant-chrome` / `grant-attach` / `grant-cef` / `channel-predefined` | the host's grant on its own launched Chrome 154 (headless and headed) / the same host attached to an external Chrome / attached to managed OBS (CEF 127) / an extra CDP `addScriptToEvaluateOnNewDocument` defining `__obedPlacement` before the host's script | — | `output.placement.grant` = `snap` (round trip passed) / null, reason `attached` / null, reason `attached` / `channel-compromised` and `show` refused; the next movie take binds a holder only in the first | — | pinned `on` |
| `life-grant-valid` / `-reload` / `-navcommit` | from `grant-chrome`: advance / reload the page and advance before and after the host's re-grant / navigate between round trip and commit (the fingerprint case is a unit test, §10) | out-only | holder bound / none before the re-grant, bound after / none (nothing installed) | as `on` | pinned `on` |
| `cef-skip` | managed OBS (CEF 127), P2 2→3 and DSK 7→8 movie slides | out-only | published take, no holder, `output.placement.reason` = `attached`; cross-fade model PASS | as `on` | pinned `on` |
| `perfect-shift` | as `m-snap` 1920×1080; the driver's `perfect` overwrite drawn 1 device px right | out-only | reference capture → FAIL (instrument negative) | as `m-snap` | pinned `on` |
| `m-geo-dpr125` / `m-geo-2560` / `m-geo-scale` / `m-geo-base` | as `m-paused` at DSF 1.25 / 2560×1440 / 1920×1080 with an in-memory `affineTransform` scale 1.5 on the movie's layer / 1920×1080 with the live slide's base layer resized in memory to 960×1080 | out-only | geometry guard → no holder (today's look) | as `on` | pinned `on` |
| `m-raw-script` / `m-raw-shadow-modal` / `m-raw-shadow-fixed` | as `m-raw` + in-page before the advance: a `script type="application/json"` styled `display: block` at x −60 whose non-wrapping text crosses the movie / an off-stage transparent `div` with an open shadow root holding a `dialog` opened with `showModal()` and a coloured `::backdrop` / the same host with a `position: fixed` coloured overlay in its shadow tree | out-only | exterior gate → FAIL (no holder) | as `on` | pinned `on` |
| `m-raw-modal` / `m-raw-svg` / `m-raw-svgclip` | as `m-raw` + in-page before the advance: an off-screen `dialog` opened with `showModal()` / a hidden `svg` (overflow visible) whose `g` is styled `display: block; position: relative; overflow: hidden` with a 40 px-stroked path reaching into the stage / the same SVG inside an off-viewport HTML `div` witness (absolute, overflow hidden) | out-only | exterior gate → FAIL / FAIL / PASS | as `on` (+ one holder for `-svgclip`) | pinned `on` |
| `m-raw` | raw export of `p2-binary` (navigator present), P2 2→3 and 4→end | out-only | exterior gate → PASS; frozen frame on 2→3 → PASS | as `on` + one holder | pinned `on` |
| `m-raw-caption` / `m-raw-nav-open` | as `m-raw` + in-page before the advance: a `body` child at x −60 with an overflowing 40 px caption / `.navigatorThumbnailSidebar` at `left: 0` | out-only | exterior gate → FAIL (no holder) | as `on` | pinned `on` |
| `m-bridge-off` / `m-bridge` | P2 `html-player` (measured plan), slide 4 → end, continuity on | out-only | no independent overlay → FAIL / reported, expected FAIL (known residual until the Q6 follow-up makes it blocking) | none / as `on` | `off` / `on` |
| `on-sw` | P2, `--disable-gpu` | as `on` | all → PASS (tone match report-only) | as `on` | `on` |

**Media evidence** (missing → INCONCLUSIVE, never a negative-control FAIL). `m-on`, `m-paused`, `m-hold`, `m-fg*`, `m-tone`: a
bound D4 holder, reference rVFC record, colour tuple, ≥ 3 demixable frames. `m-off`: served `off`; ≥ 10 presented frames first;
transition, outgoing texture and movie-region pixels on ≥ 3 demixable frames; **no holder by design** (a holder → INCONCLUSIVE);
FAIL: `Ô` misses the reference index. `m-bridge(-off)`: bridged decoder tagged, rVFC, rAF.

**Lifecycle scenario** (one parametrized driver function on `p2-binary` with the patch; each row also passes complement and no
flash on its visible frames; "cleanup" = no transition `layer<id>` node, holder or rule after the next scene):

| Row | Action | Expected |
|---|---|---|
| advance | plain 2→3 | settled frame = stock twin's (outside movie rects); one holder during the fade; cleanup |
| replay | go-to 2, advance again | as advance; fresh holder and rules on fresh ids |
| queued advance | Space mid-dissolve | player's own queue as stock twin; cleanup |
| queued skip | `advanceAndSkipBuild` mid-dissolve (def @2350987 / @2351025) | as stock twin; cleanup |
| go-to / back | go-to 1 or back mid-dissolve | transition DOM, holder and rules gone; destination as stock twin |
| hide / show | hide mid-dissolve, show 0.5 s later; per-frame screencast; alpha and screen pages separately | while hidden: output fully transparent (alpha) / black (screen) on every screencast frame wholly inside the interval; after show the model holds on six distinct, correctly timestamped mid frames. Controls listed in the round manifest before the lifecycle candidates count: the stock twins (positives), `life-hide-nohide` (driver drops the hide → visible frames inside the interval → FAIL), `life-hide-noshow` (driver drops the show → no content after show → FAIL), scorer cases duplicate frame and timestamp shift → INCONCLUSIVE |
| automatic | in-memory override: `automaticPlay: true`, `beginTime` 0.5 s | incoming 0 and the frozen frame through the real delay branch; then as advance |
| loop wrap | in-memory `loopSlideshow: 1`, P2 slide 4's dissolve | as advance onto slide 1 |
| end of show | P2 slide 4's dissolve, loop 0 | held endpoint = stock twin's (DOM, holder, rules legitimately remain); then go-to 1 → cleanup; a bridged decoder is judged by `m-bridge` only |

Q0b's lifecycle pass was a dry run (advance, replay, back without a stock-twin destination, queued advance reported), not
qualification: DX-1 runs every row against its stock twin, the go-to/back destination included.

### 9.2 DX-2 inside OBS CEF — `managed_obs_qualify.py --arm dissolve` (unrecorded)

One launch, the managed bridge with DX-1's hook, resolver, integrity rules and scorer (W2), the advance, a `GetSourceScreenshot`
burst.
- **Sessions:** DX-1's P2 cross-fade, `p2cut` and opaque arms, except `screen-*`, `delay-*`, `on-sw` and the lifecycle;
  plus **`cef-skip`** (decision 15): P2 2→3 and DSK 7→8 movie slides must publish a take, bind **no holder**, and record
  `output.placement` = `{grant: null, reason: "attached"}`, with the cross-fade model passing. A bound holder in CEF is a
  FAIL. The media, tone and `m-snap` sessions are not run in CEF in this PR (follow-up PR, §13.1).
- **Recorded:** every session records continuity, G2 state, colour tuples and served digest.
- **Cut sessions** need rAF coverage from DOM insertion to 3 frames after the cut and ≥ 1 source screenshot inside (no
  screencast in CEF).
- **Controls first:** every control outcome is read before the candidate count.
- **Calibration fixed before capture, applied without clamping:** n = max mid-frame residual of `opaque-off`;
  τ_CEF = max(4, ⌈n⌉ + 1); complement 2 + ⌈n⌉; no dip 252 − ⌈n⌉. Caps: τ_CEF ≤ 8, complement ≤ 6, no dip ≥ 248, so n > 4 is
  INCONCLUSIVE.
- Refuses while `OBED_LIVE_MM_OPACITY` is set.

### 9.3 DX-3 owner check (real OBS for the cross-fade; the HDMI host for the freeze)

- **Pre-check:** DX-1's texture classifier on the chosen production transition: fill-less outgoing and ≥ 2 000 px in-only →
  affected, else a regression control. Movie: an H.264 slide several seconds in, preferably with foreground over it.
- **Where:**
  - OBS Take output (Keyer): stripped P2 2→3 and the pre-checked transition.
  - The Chrome HDMI host (`LiveOutputHost`, `output.placement.grant` = `snap`): the movie slide.
- **Pass:**
  - Slide 3 fades in from nothing; slide 2 keeps its colours while fading; no darker or more transparent overlap; no jump at
    the hand-off.
  - On the HDMI host the movie stops on its current frame and fades out with slide 2, foreground intact; the documented
    mid-tone step (identity `L`, decision 10) is shown as the known limit, not a failure.
  - **In OBS the movie keeps today's jump** (decision 15), shown as expected.
  - **Null** (affected transitions only): `OBED_LIVE_MM_OPACITY=off` shows the pop-in and the jump.
- **Report** candidate and null separately with the served mode, `output.mmOpacity.sha256`, `output.placement` and the decision
  record.

### 9.4 Regression

`run_gates.sh` full tier from a fresh pinned worktree; `mm_opacity_probe.py`, `mm_handback_probe.py`; managed OBS (owner
session) `--arm mmo`, `--arm g2`, `--arm mmo-cef`. Root-cause any change.

## 10. Tests (three new test functions, as rev 3; everything else extends them; rev 10 adds rows, no new function)

1. **Free:** tuple-parametrized anchor/replacement refusal (both patchers); off identity; `patch_rendering` = `patch_player` minus
   the hook; "every original anchor gone" (`test_live_runtime.py:205`, `:265`, `:367`); equivalence; `node --check`; pin mismatch;
   the **shadow-DOM invariant** (r9 2) as rows of the same table: no `attachShadow`, `shadowroot`/`shadowrootmode` or
   `customElements` in either supported player (stock and patched), the committed export `index.html` fixtures, or any JS the
   host injects (`src/obed_edom`), with a planted-string control that the checker flags.
2. **Edits** (`test_live_runtime.py`): re-pin (§3.1 candidate digests); hand-back tests use `HANDBACK = slice(5, 8)`; the
   composition test runs R1–R5, R6–R8, D1–D4 in every order and checks containment including self.
3. **REAL-gated Node function, both players, one case table** (real extracted code): D1–D4 offsets; ids; committed transitions;
   near-misses; construction failures; the 200 freeze-stub rows (§8.2) with rev 12's expectations. Harness: every stub element
   carries `localName`/`namespaceURI` and `shadowRoot` (null unless a row opens one); `document.querySelector` answers the
   top-layer query; `devicePixelRatio` stubbed (1 by default); exterior subtrees nest under `body`; metadata rows carry the UA
   `display: none` (the nine `gate_*TextIgnored` rows stay positives that way); the stage-scale rows (`stage2560`, `stageScaledInSmallViewport`, `letterbox`
   at 0.75, `stageNearUniform`) carry the matching `#stage` transform and now skip. Expectations: snapped device-pixel holder
   geometry and backing; no `putImageData` on any path (trace pattern `(v(gf*)?)?`); the readback is the whole backing on every
   admitted row; the `L` rows become "pixels untouched"; `fillAspectChange` admits; `uniformScale` skips. **r8 rows** (§8.3),
   each from one property: *geometry guard* (rev 13) — DPR 1.25 and 3, stage scale 4/3 and 0.75, a scale below the stage
   skip; DPR 2 (backing 1904×536), DPR 1.5 (`dpr15_fillOpaque` snapped to `[109.333, 795.333, 312.667, 262.667]`, backing
   469×394; the P2 box at 1428×401), fractional stage origins in y and x, a fractional translation and the letterbox admit;
   a transparent last backing pixel at DPR 1.5 and 2 skips (`dpr15_fillLastColumnTransparent` re-indexed to the 469-wide
   backing); *opaque cover* — a
   transparent last backing column, last row and first pixel each skip (replaces rev 10's "partial edge outside the interior
   admits"); *exterior proof* — the navigator shape admits; a hidden parent with `filter` / `-webkit-box-reflect` over a valid
   witness skips while the same parent without effects admits; a top-layer element skips; an SVG `g` witness skips; witness
   meeting `V`, `static`, `overflow: auto`/`visible`/`clip`, `display: inline`, own `box-shadow`/`outline`/`filter`/
   `border-image`, a `fixed` element or fixed `::before` on the walk, the overflowing caption without witness, a failing
   ancestor of `#stage`, an `iframe` without witness each skip; transformed, `absolute` and `sticky` descendants of a valid
   witness and an `iframe` under one admit; a passing exterior `<video>` meeting the region (main's bridge) skips that movie.
   **r9 rows** (§8.4): a rendered `script` (`display: block`) with text, a rendered hidden `head` with a filter over a witness,
   an open shadow host, a 960×1080 and a 1920×1079.5 live base layer skip; metadata at `display: none` and the full-slide base
   layer admit.
4. **`tests/test_dissolve_probe.py`, the one parametrized function** (synthetic numpy), existing rows kept, plus: holder pixels —
   exact holder PASS, 1-px shifted holder under the production mask FAIL, tone step only (compensated by `L_path`) PASS,
   edge-band step FAIL; mask verification — production PASS, whole-rectangle / 3-px shifted / empty mask → INCONCLUSIVE;
   reference profile — valid set PASS, stale (reused) frame, missing or extra animation, unpaused animation, `currentTime` off,
   unstable pair, transition DOM gone → INCONCLUSIVE, `perfect-shift` FAIL; tone coverage < 50 % → INCONCLUSIVE; no dip on the
   both-opaque class with identical colours (α 255 PASS, KB α 191 FAIL); hide rows — correct capture PASS, visible frame inside
   the interval FAIL, no content after show FAIL, duplicate frame / timestamp shift / < 6 after-show mid frames →
   INCONCLUSIVE; exterior gate and geometry guard — bound holder PASS, published take without holder FAIL, no published take →
   INCONCLUSIVE; strip decode from a device-scale holder.
5. **Rev 17 rows** (in the same functions): test 3's harness gives BASE `left`/`top` `0px` and defines `window.__obedPlacement` per
   row (default `snap`; the trace pattern stays `(v(gf*)?)?` — one movie draw); rows (§8.8): grant absent / `invalid` / any other
   value (incl. `frac`, `SNAP`) skip; fractional `left`/`top` and `left: auto` skip, a negative integer `left` admits; an absent
   getter (the production preview/raw path, `patch_rendering` bytes) skips. **`tests/test_live_host.py`, one new parametrized
   function** (W6; fake transport, no browser): the grant matrix — launched + `Chrome/154.*` or `HeadlessChrome/154.*` + GPU
   compositing → `snap`; attach mode, managed OBS, `Chrome/153.*`, `Chrome/155.*`, software compositing, a failing
   `Browser.getVersion` or `SystemInfo` → no grant with its reason; the round trip committed only into the recorded unique
   context (a context change between round trip and commit installs nothing); a reload re-grants only after its own round
   trip; `gpu_compositing` disabled or unreadable at `observe()` → revoke; a failed round trip → `channel-compromised` and
   `show` refused; the init script under Node (`vm`) with the §8.8 tamper rows; `output.placement`. Test 4
   (`test_dissolve_probe.py`) adds the `m-snap-shift`, `grant-*`, `life-grant-*`, `cef-skip` and `*-prod` arms to its arm table
   rows.
6. **`test_managed_obs_qualify.py`:** the env-refusal test parametrized over the new arm; the calibration test (n = 4 / 4 + ε);
   the session list includes DSK 7→8 and `m-snap`.

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` (done, `7fa7c8dd`) |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | rev 17's `__obedFreezeTake` byte-exact to §3.1 (over rev 13: the grant read (`"snap"!==pl` skips) and integer `left`/`top`; no `frac` draw; the rows and harness changes of §10 item 5) (`_FREEZE_TONE_LUT` removed; `Q` kept); docstrings (identity tone, device-pixel holder behind the geometry guard and the host grant, exterior proof, top layer, shadow roots); re-pins; tests 1–3 incl. the shadow-DOM invariant rows |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | reference-capture profile (inventory, paused-state and opacity read-backs, stable pairs, `perfect`/`perfect-shift`), holder-pixel scorer with `L_path`, foreground inventory + production mask + missed/excess verification with a twin per reference geometry, tone coverage, device-scale holder paste and strip decode, `m-snap[dpr, origin, clip]` (one parametrized arm over the §9.0 item-5 matrix) and `m-snap-frac[dpr]` with rev 13's anchor, `m-geo-*` (`-dpr125` replaces `-dsf2`) and `m-raw*` arms (raw-page driver and injections), hide-row screencast with timestamps and the dropped-hide/-show twins, both-opaque no-dip class; test 4; rev 17: the `grant-*`, `life-grant-*`, `cef-skip`, `m-raw-prod`/`m-preview-prod` and `m-snap-shift[dpr]` arms (the follow-up's probe/CEF arms are not built here) |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | DX-2 per §9.2: the cross-fade, cut and opaque sessions plus `cef-skip` (no holder, reason `attached`); media / tone / `m-snap` sessions dropped from CEF in this PR; test 6 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, `.agents/handovers/keynote-live-dissolve-crossfade-followups.md` | README/SKILL: the identity-tone known limit; the freeze works on the Chrome host (HDMI/headless) at DPR 1, 1.5 and 2 and stage scale 1; **OBS/CEF keeps today's movie jump** (decision 15); raw export and Build Preview keep the jump (decision 14); scaled stages keep the jump; follow-ups handover: the **CEF placement follow-up PR outline** (§13.1), W5, the Q6 PR, scaled stages, the optional G2 use of a qualified `L` |
| W5 | scratch + evidence only (no tracked file) | **Host-side compositing-path calibration feasibility probe** (decision 10; non-blocking for this PR, needed before Q5 closes): can the host, at startup, identify the compositing path and its map (qualified path + tuple → `L`, unknown → identity) from compositor-painted pixels? Headless `LiveOutputHost` (GPU, `--disable-gpu`) and managed OBS (acceleration on/off), two fresh launches each: the tone movie paused in an off-screen-safe calibration slot, CDP screenshot / `GetSourceScreenshot` vs `drawImage`; repeatability, distinguishability of GPU vs software for the same tuple, invalidation on GPU-state change (GPU process loss, acceleration toggle); a record with a go/no-go and, on go, the player-boundary change it would need (owner decision) |
| W6 | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | **The host grant** (§3.3; decision 15): first-run init script and private channel (token, round trip), grant conditions (launched, `Browser.getVersion` major in `QUALIFIED_SNAP_MAJORS`, GPU compositing), context-bound commit, re-grant after reload, `observe()` fingerprint revoke, `channel-compromised` handling, `output.placement`; no lease, probe, recalibrate, `managed_obs.py`, `web/live.py`, `live_session.py` or dashboard change |
| Q0b-bis | done (§8.6) | engagement, cost, matrix, CEF preflight (the trigger) |
| Q0b-ter | scratch + evidence only | §9.0: the grant on real engines, Chrome holder pixels on the exact bytes, engagement and scope (`cef-skip`, `*-prod`), the open Q0b-bis items |

Order: W1 ∥ W2 ∥ W3 ∥ W4 ∥ W6 → Q0b-ter → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-1
(fresh pinned worktree, controls first) → DX-2, `mmo-cef`, regression (§9.4), DX-3 (owner session) → one PR to `main`. Never
merge. W5 runs whenever a browser window is free; it does not gate the PR.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and construction failure; export JSON never mutated. (3) Rule ids = allocated ids. (4) One `applyCssAnimation` pass; cut only
at the exported timing. (5) D4/D3 add-only, never touch a `<video>`; only gate + allowlist passes are admitted; attach by kind.
(6) `off` = today's bytes. (7) Thresholds measured or by formula; PASS and FAIL controls for every blocking check. (8) The
exterior proof never trusts a failing element's own border box; every pruned subtree is clipped by a validated ancestor
disjoint from `V`. (9) Holder canvas = device pixels of the snapped box; alpha scan over every backing pixel before the redraw; no tone
write. (10) Top layer and open shadow roots refused first; no tag exempt by name; descendant-paint effects checked before the
visibility shortcut; witnesses are HTML `div`s; the shadow-DOM invariant is a checked test. (11) Geometry guard: DPR ∈ {1, 1.5, 2}, `kx` = `ky` = 1, stage scale 1,
translation-only scene transforms, integer `left`/`top`, `sn` on the 1/DPR grid; everything else skips; (12) placement only from the host's grant
(`snap` on a host-launched, qualified Chrome; never in CEF); absent or anything else skips; safety checks never relaxed for a visual allowance.

## 12. Owner decisions (1–7 2026-10-11, 8–15 2026-10-12, in chat)

- **Target (movies):** "in Keynote the vid stops playing and dissolves out" — freeze on the current frame, fade with slide 2.
1. **Switch: fold into `mm_opacity`.** 2. **Scope: every output.** 3. **F1 (`none` cut) in this patch; F2 a separate
   follow-up** with an owner Q-deck (final). 4. **F3 in this patch** (re-confirmed after rev 4: splitting it out declined).
5. **Mid-tone step at the freeze: remove it, player-only** (owner: "is it observable? If the cost is a re-plan let's do it").
   *Observable?* Estimated yes for an attentive viewer: mid-grey 139 → 128 is ≈ 16 % less luminance (ΔL* ≈ 4.3) in one frame at
   near-full opacity (DX-3's eye check confirms). *Design:* the fixed per-channel `L` (§1.4, §3.2); moving or pausing the live
   `<video>` stays out (core changes, deferred by Q6). *Decision record (Q0b 1, DX-2):* `Q` = the decoded tuples measured; `L`
   non-identity when (i) colour patches land within 2/255 after the per-channel map, (ii) two CEF launches agree within 1
   (headless GPU off by > 1 → DX-1 tone row report-only), (iii) every decodable encoding of a tuple in `Q` fits it within 2/255;
   analytic gamma 1.961 if within 1 of the table, else the table (+≈ 1 KB). **Fallback:** `L` = identity, a known limit (tone
   non-blocking; §9.3); moving the `<video>` reconsidered after S2.
6. **Main's bridged movie over P2 slide 4's terminal fade: follow-up after S2.** Player-only on `main`; `m-bridge` reports the
   residual. Stopping a bridged or held decoder's paint at the outgoing transition start (main's `keepAtSlot`, S2's hold) is
   a separate PR after S2 merges, not pushed into S2's in-flight branch; it makes `m-bridge` blocking.
7. **Foreground over a frozen movie: redraw overlying texture canvases** into the snapshot, under the §3.2 allowlist.

**2026-10-12, on Q0b's re-plan triggers (owner accepted the Astra xhigh advisory; binding):**

8. **T2, gate: strict stage admission plus a conservative exterior pass** (its preview clause superseded by decision 14). An off-stage subtree is pruned only when its paint
   extent is *proven* disjoint from the visible stage (a validated clipping ancestor; border-box non-intersection alone is not
   enough: overflowing text, shadows, pseudo-elements, escaping descendants). Raw export and Build Preview pages then freeze
   with `#slideshowNavigator` present, so preview inherits F3 (§4). The take still sees main's bridged decoder in `#body`.
9. **T3, holder: draw the snapshot on the device-pixel grid of the content box** (backing = screen box × DPR; fractional origin,
   clips and foreground coordinates preserved), not natural size plus CSS scaling; strict τ kept. First re-measure with
   browser-rendered references and progress from outside the media (§9.1); only if device-pixel drawing still fails, quantify
   the remaining edge band for the owner — no invented envelope.
10. **T4, tone: ship identity `L` now** (decision 5's fallback, a known limit; the GPU mid-tone step stays and DX-3 shows it).
    Identity skips the RGB writes and `putImageData`; the alpha scan stays (it proves opaque cover). A host-side
    compositing-path calibration probe (qualified path + tuple → `L`, unknown → identity) is a separate, non-blocking work item
    (W5), needed before Q5 is finally closed. No page-side heuristics.
11. **T1, cost: keep 50 ms**; profile per stage, remove unneeded work, try a source-region crop; DSK 7→8 is the worst case and
    must pass. **T5, CEF:** a preflight on current or new bytes (tone across two launches, engagement, DSK 7→8 cost) before the
    final DX-2; a measurement item.
12. **Holder geometry beyond stage scale 1 / DSF 1 — resolved 2026-10-12 (~11:45): adopt fix A, keep skipping scaled
    stages.** History: first "documented limit", reversed by the owner the same day; a separate investigator then measured the
    options (§8.5). Decision: snap on the stage-local 1/DPR grid (`sn = round((z − e)·k·DPR)/DPR`, matching `ww`/`hh`); admit
    `devicePixelRatio` 1, 1.5 and 2 (measured; other values skip as unmeasured); drop the integer-stage-origin condition
    (fractional letterbox origins measured exact); keep `#stage` a pure translation, `kx` = `ky` = 1 and translation-only
    scene chains; stage scale ≠ 1 and nested scales keep skipping (option B is not shippable without a per-chain rule). An
    output whose viewport is not 1920 CSS px wide (2560×1440 or 1280×720 at DSF 1) keeps today's baked-frame jump; a 4K output
    at DSF 2 (1920×1080 CSS) freezes. Still to measure (Q0b-bis): DSK 7→8 cost at DSF 2, the CEF source's DSF, clip edges at
    DSF ≠ 1 (all measured since, §8.6).
13. **Placement rule from a host startup probe (2026-10-12 ~14:10; deferred to the follow-up PR by decision 15).** OBS's CEF 127 places the video quad unsnapped, Chrome 154
    snaps; no page-side test separates them. A host-side probe compares composited pixels of a snapped and a fractional canvas
    against a test movie at host start (and on reconnect or GPU reset), off-air, in about 1.5 s; it sets `snap` or `frac`;
    ambiguous or unknown means skip. It is **the** startup calibration: it covers the HDMI/headless host (CDP screenshot) and
    managed OBS (`GetSourceScreenshot`), and the same probe can later carry W5's tone-path map (Q5 stays open; this patch keeps
    identity `L` — recommendation §13).
14. **Raw export and Build Preview no longer freeze (2026-10-12 ~14:30).** Without a host there is no calibration, so F3 skips
    on those pages (stock movie behaviour); the cross-fade and cut still apply. This **supersedes decision 8's preview clause**
    ("preview inherits F3"); decision 8's gate design is otherwise unchanged. Other rev-15 defaults stand: an on-air reconnect
    skips the freeze until the probe re-runs; identity `L` with the tone slot reserved.
15. **Split (2026-10-12 ~15:00).** This PR ships the freeze only where the snapped rule is proven: the Chrome host
    (HDMI/headless `LiveOutputHost`). In CEF/OBS the take skips (today's jump). The host grants `snap` from its own knowledge
    only — it launched the Chrome and `Browser.getVersion` reports a qualified engine — through rev 16's private per-document
    channel. The placement probe, the `frac` draw, the isolation gate, the OBS calibrate scene, `recalibrate`, the CEF clip
    matrix and W5's tone map move to a follow-up PR (§13.1), whose first step is the 5-minute OBS feasibility check of
    whether `GetSourceScreenshot` renders a non-program source.

## 13. Risks and out of scope

- **Geometry beyond the guard (decision 12, resolved).** DPR ∉ {1, 1.5, 2}, stage scale ≠ 1 and scales below the stage skip
  the take (today's baked-frame jump): an output host whose viewport is not 1920 CSS px wide (2560×1440 or 1280×720 at DSF 1)
  loses the freeze, not the cross-fade. Fix A at stage 4/3 still reads 162 / 9.3 % on the real P2 page.
- **Latent anisotropic `contain` bug (excluded by the guard).** The take solves `object-fit: contain` in screen space from the
  bounding rect; under an anisotropic local scale (the DSK-like replica's nested 1.0008/0.9993) it picks the wrong axis
  (content width 312.213 vs Blink's 312.656; 249–255 LSB). The translation-only guard keeps such chains out; any future model
  that admits scaled chains must solve `contain` in local units (LayoutUnit-exact) first.
- **Cost at DSF 2:** four times the device pixels; measured 15.1–18.3 ms for DSK 7→8 (Q0b-bis), within the 50 ms bound.
- **Host grant (decision 15).**
  - *Version allowlist:* a Chrome auto-update to a new major means no grant (the reason is recorded) until that version is
    qualified (W1 adds it to `QUALIFIED_SNAP_MAJORS` after an `m-snap` run). A failure here is a skip, never a wrong freeze.
  - *Coverage limit:* a player-internal automatic transition that runs while the host's CDP connection is down, after a
    GPU-to-software fallback the host has not yet observed, would use a stale grant.
  - *Channel:* page code cannot set or keep a grant. A predefined getter needs code running before the host's first-run script
    (another CDP client or an extension); the round trip catches it and keeps the output hidden.
  - *Scope:* OBS/CEF, raw export and Build Preview keep today's jump (decisions 14–15).
- **Tone map (W5).** Identity `L` stays (Q5 open); a host-measured map belongs to the follow-up probe (§13.1).
- **Clip edges at DSF ≠ 1:** measured in Q0b-bis (all clipped matrix cells at the floor, §8.6).
- **The snapping model is a measured fit** for the qualified geometry (P2, DSK slides, the hi-DPI replica; §8.2, §8.5), located
  in Chromium's zoom-for-DSF layout snapping (same painter code in M127), not a general rule for scaled chains; a
  future Chromium that snaps differently there would show in `m-snap` (blocking) before release.
- **Tone:** identity `L` keeps the GPU mid-tone step (≤ +11.3/255, ΔL* ≈ 4.3 at mid-grey) at the freeze; W5 may bring a
  qualified `L` back. Software compositing would freeze exactly, but its untagged-H.264 tuple is outside `Q`.
- **CEF:** does not snap the video quad (§8.6); this PR does not freeze there (decision 15); DX-2 proves the skip.
- **Exterior proof** relies on HTML overflow clipping (positioned `div` clipper, no fixed escape, no descendant-paint effect
  above it, no top layer); a page that adds fixed, unclipped or top-layer chrome later simply skips the take. View-transition
  pseudo-elements also render in the top layer; neither the player nor the host starts one (no `startViewTransition` in either
  player or `src/obed_edom`), and **an active view transition is outside the gate's guarantee**. **Shadow trees:** open author
  roots skip; closed ones are excluded only by the checked invariant that the supported pages create none — a page that adds
  them (an extension, a future host script) falls outside the guarantee until the invariant test is extended to it.
- ids rest on `VB`'s pre-order allocation (proved); production transparency; the bridge/hold (Q6).

Out of scope: F2, GL effects, Keynote-app comparison, S2 and its follow-up, and the CEF placement follow-up below.

### 13.1 Follow-up PR: CEF/OBS placement (decision 15; outline for the follow-ups handover)

Moved out of this PR. The full design is rev 16's §3.3 (`41ef609b`) and §9 (r12 folded).
1. **First step: the 5-minute OBS feasibility check.** Does `GetSourceScreenshot` render a browser source that is not on program
   (a dedicated `AK-Calibrate` scene / `AK-Probe` source)? If not, the follow-up re-plans the isolation gate before anything
   else.
2. **The placement probe:** an isolated probe target or source; the program-capture gate with cleanup on every exit; the shipped
   clip (`p2like.mp4`, sha256 `7b7d66b5…`); the classifier per rev 16 §3.3 (tone maps {identity, GPU analytic}, inner mask,
   max over channels, both poses, ≤ 2 % / ≥ 20 %); the lease, keep-alive and invalid / probing / valid lifecycle; the operator
   `recalibrate` command (`web/live.py`, `live_session.py`, the presenter UI); reconnect re-probe.
3. **The `frac` take draw:** a snapped underlay plus CEF 127's unsnapped quad (the investigator's `fdrawu`, +186 B), at DPR 1 and
   an integer stage origin only. Its grant value joins `snap` in the same channel; this PR's channel and `left`/`top` admission
   are its base.
4. **The CEF acceptance:** `m-snap-cef[clip]` (none, near-side and far-side fractional x and y, foreground crossing), the
   `nooffset[x|y]` controls (only near-side clips move the quad, §8.7), the wrong-rule controls through the privileged channel,
   `iso-*`, `probe-*`, `life-cal-*`, CEF DSK 7→8 cost with the extra draw, CEF `hevc10` / Keynote-HEVC tone.
5. **W5's tone-path map** on the same probe (recorded first, applied only after its own qualification).

## 14. Critique log

Raw rounds: `.agents/reviews/dissolve-crossfade/plan-astra-r{1,…,7}.md`. r1–r5 (12, 7, 11, 7, 6): folded, rows in `4ffcd8ad` /
`e5c644bb` / `218308c3` / `cacfe9fb` §14. r6 (4, on rev 7) and the first real-DOM probe, folded in `d299b549` §14: UA
`overflow: clip` leaves, viewport-propagated `body` overflow, the paint gate, `preserve-3d` build wrappers. Owner answers: §12.

### r7 — GPT-6 Astra high (Codex), on rev 8 `d299b549` — verdict: ready for owner review after listed fixes — folded

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / edge | Folded: the gate admits only supported paint families (`html`, `body`, `div`, centred `canvas`/`video` with `fill`/`contain`, no view-box); `img`, `svg` and other replaced or vector paint, column rules and anything unqualified skip the take; confinement no longer inferred from `object-fit`; rows: shifted outside-box `img` and `canvas`, shifted clipped canvas, SVG, column rule. | §3.2, §8, §10 |
| 2 | major / closed | Folded: pseudo-element, `content` and direct-text checks run before the visibility shortcut; `display: contents` skips; only no-box / opacity-0 subtrees and non-rendering elements are exempt; rows: hidden origin with visible pseudo, `display: contents` text and pseudo; positives for suppressed, opacity-0 and `script` text. | §3.2, §8, §10 |
| 3 | minor / new | Folded: Q0b 3 and `m-fg` exercise the real build-wrapper topology with two overlapping, distinguishable canvases over counter pixels vs paused pre-D4 `S_live` ≤ τ; `m-fg-swap` (reversed redraw) must FAIL; missing overlap, reference or engagement INCONCLUSIVE; ordering recorded. | §9, §9.0, §9.1, §10 |

### Rev 10 — Q0b re-plan (owner decisions 8–11 on the Astra xhigh advisory `replan-astra-xhigh.md`), 2026-10-12

| Trigger / item | Disposition | Where |
|---|---|---|
| T1 cost (DSK 7→8 47.6–51.9 ms) | Bound kept at 50 ms. Profiled per stage; the cost was full-resolution readback and toning of 1282×1080 + 1922×1080 frames shown at 312×263 + 468×263. Device-pixel holder + identity tone: 9.4–9.8 ms (rev 9 same session 70.3); No smaller source crop exists on the measured full-content regions; no crop A/B has run. The clipped diagnostic remains required in Q0b-bis. | §3.2, §8.2, §9.0 |
| T2 gate (raw/preview miss) | Element test kept for the stage and its ancestors; exterior proof (validated clipping ancestor disjoint from `V`) for everything else; raw P2 2→3 and 4→end freeze; overflowing caption and open navigator skip; bridge still blocks | §3.1, §3.2, §8.2, §9 (`m-raw*`), §10 |
| T3 holder edges (78 LSB) | Re-measured with browser-rendered references (seeked animations; progress exact, outside the media); the holder is drawn into the device pixels of the box Blink snaps the movie to: ≤ 3 LSB after the tone step at 1920×1080 and letterboxed (FAIL control 216); DSF 2 / 2560×1440 band quantified, open for the owner | §1.1, §3.2, §8.2, §9.1, §13 |
| T4 tone (software path identity, same tuple) | Identity `L` shipped; RGB writes, `putImageData` and the table removed; alpha scan kept; W5 feasibility probe for a host-calibrated path + tuple → `L` | §2, §3.2, §11, §12.10 |
| T5 CEF | Preflight on the rev-10 bytes before DX-2 (tone ×2 launches, engagement, DSK 7→8 cost, holder at the source geometry) | §9.0, §9.2 |
| Hide / hide-screen rows INCONCLUSIVE by construction | Per-frame screencast for those rows (measurement change) | §9.1 |
| Tone mask empty (`3231B69B` covers the movie rect) | Verified painted-pixel mask (α > 0 ∪ twin difference, dilated 2 px; twin agreement checked) with a coverage rule; measured 162/220 ramp steps, 22/28 patches, 8/8 skin; report-only under identity | §8.2, §9.1 |
| D2 `on` no-dip INCONCLUSIVE (classes < 2 000 px) | No dip read on the both-opaque class (α is colour-independent): D2 has 180 687 px (differing overlap 0, hence rev 9's empty class) | §9.1 |
| Dry run ≠ qualification | Lifecycle rows run against stock twins in DX-1, go-to/back destination included | §9.1 |

### r8 — GPT-6 Astra (Codex), on rev 10 `891e4f40` — verdict: CHANGES REQUIRED (9) — folded in rev 11, with decision 12 (made, then reversed)

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / closed | Folded: `filter`, `backdrop-filter`, `-webkit-box-reflect` fail the element test before the visibility shortcut, so a hidden ancestor cannot expand or displace a witness's clipped output; every ancestor of a witness passes the element test or has its own witness. Rows: hidden filter / reflect parent skip, unfiltered hidden parent admits (rev 10 admitted the filter case) | §3.1, §3.2, §8.3, §10 |
| 2 | major / edge | Folded: top layer (`:modal`, `:popover-open`, `:fullscreen`, hence `::backdrop`) refused before both tests; witnesses only HTML `div`s (SVG `g` never); iframe and `foreignObject` boundaries stated; real-page arms `m-raw-modal`, `m-raw-svg` (FAIL) and `m-raw-svgclip` (PASS); the bridge still blocks; clipped absolute/sticky/transformed descendants stay positives | §3.1, §3.2, §8.3, §9, §10 |
| 3 | major / closed | Folded: the alpha scan reads every backing pixel (`getImageData(0, 0, ww, hh)`) before the redraw; an unproven edge skips; rev 10's "partial edge outside the interior admits" row replaced by transparent last column / row / first pixel rejections | §2, §3.1, §3.2, §10 |
| 4 | major / new | Folded: `sn` described as the measured model for the qualified geometry; scene transforms must be pure translations (fractional allowed), `#stage` scale exactly 1, stage origin integer; everything undemonstrated skips; nested scale, fractional stage origin and DPR cases go to the hi-DPI investigation | §1.1, §3.1, §3.2, §8.3, §9.0 |
| 5 | major / new | Folded with decision 12's reversal: the bytes admit only qualified geometry (guard); `m-geo-*` prove the skip; safety checks stay mandatory in any class the investigation later admits (hook in §3.2/§9.1); §3, §9 and §13 state the same rule; DSF 2's flat max 5 recorded | §3.2, §9, §12.12, §13 |
| 6 | major / closed | Folded: independent foreground inventory, mapping through `sn`, missed and excess support verified against the twin raster (tone twins: missed 0, excess 0; whole-rectangle 75.6 % excess, 3-px shift 398 missed, empty: all rejected); a twin per reference geometry; shifted-holder negative under the production mask | §9, §9.1, §10 |
| 7 | major / closed | Folded: a dedicated reference-capture profile (inventory, paused state, `currentTime`, rendered opacities, stable pairs, required images); temporal coverage stays with the timed arms; stale/reused, missing-animation INCONCLUSIVE controls and a `perfect-shift` FAIL | §9, §9.1, §10 |
| 8 | major / new | Folded: six distinct, correctly timestamped mid frames *after show* plus frames inside the hidden interval, alpha and screen separately; dropped-hide / dropped-show twins FAIL; duplicate-frame and timestamp-shift cases INCONCLUSIVE; all in the round manifest before lifecycle candidates | §9, §9.1, §10 |
| 9 | minor / edge | Folded: no smaller crop exists on the measured full-content regions and no crop A/B has run; the crop experiment on a clipped diagnostic is in Q0b-bis; DSK 7→8 is the previous worst case (3→4 costs more); every measured DSK transition re-timed on final bytes | §8.2, §9.0 |

### r9 — GPT-6 Astra (Codex), on rev 11 `b4ff2576` — verdict: CHANGES REQUIRED (3 false admissions + 1 wording); r8 #3, #5–#8 closed; the four provisional defaults accepted — folded in rev 12

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / exterior-proof escape | Folded: the tag-name exemption in `pc` is gone; non-rendering is read from the rendering state (`checkVisibility` false: `display: none`, the UA default for metadata); a rendered `script` with overflowing text and a rendered hidden `head` with a filter now skip; default metadata stays a positive | §3.1, §3.2, §8.4, §9 (`m-raw-script`), §10 |
| 2 | major / exterior-proof escape | Folded: author shadow trees are unsupported paint boundaries — an open `shadowRoot` skips before any shortcut; closed roots are excluded by a checked invariant (no `attachShadow`, `shadowroot`, `customElements` in either player, the export `index.html` or `src/obed_edom`: 0 occurrences each; W1 rows with a planted-string control); `m-raw-shadow-modal`, `m-raw-shadow-fixed` FAIL, `m-raw` the ordinary-page positive | §3.2, §8.4, §9, §10, §13 |
| 3 | major / geometry | Folded: the guard requires `kx === 1 && ky === 1` (live base-layer box = slide); half-width (960) and fractional-height (1079.5) base layers skip, the full slide admits; `m-geo-base` real-page control | §3.1, §3.2, §8.4, §9, §10 |
| 4 | minor / wording | Folded: §14's T1 row carries the reviewer's sentence (§0 already did not claim it); real-page engagement is §9.0 item 1; §13 states active view transitions are outside the guarantee | §9.0, §13, §14 |

### Rev 13 — decision 12 resolved (owner ~11:45, on the hi-DPI investigation `hidpi-2026-10-12/README.md`)

| Item | Disposition | Where |
|---|---|---|
| Fix A adopted | `sn = round((z − e)·k·DPR)/DPR` with matching `ww`/`hh`; D1 10 197 B; digests re-pinned; `node --check` and §6.1 hold | §3.1, §3.2, §8.5 |
| Guard | DPR ∈ {1, 1.5, 2} (others skip); integer-origin condition dropped; stage translation, `kx` = `ky` = 1 and translation-only chains kept; stage scale ≠ 1 and nested scales skip | §3.2, §9.1, §12.12 |
| Acceptance | `m-geo-dsf2` becomes admitting `m-snap-dsf2`, plus `m-snap-dsf15` and the fractional letterbox, holder pixels PASS; `m-geo-dpr125`, `-2560`, `-scale`, `-base` skip | §9, §9.1 |
| Still to measure | DSK 7→8 cost at DSF 2 (est. 25–30 ms), the CEF source DSF, clip edges at DSF ≠ 1 | §9.0 |
| W1 rows | 4 flips (`dpr2`, `dpr15_fillOpaque`, `stageFractionalOrigin`, `stageFractionalOriginX` admit) + 5 rows (`dpr125`, `dpr3` skip; `dpr15_p2Box` admits; last-pixel transparency at DPR 1.5 and 2 skips); 265 rows match on both players | §8.5, §10 |
| Risks | latent anisotropic `contain` solve (excluded by the guard); scaled-stage outputs keep the jump | §13 |

### r11 — GPT-6 Astra (Codex), on rev 13 `54000459` — bytes, digests and 265 rows confirmed; CHANGES REQUIRED (2, acceptance) — folded in rev 14

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / acceptance coverage | Folded: one parametrized `m-snap[dpr, origin, clip]` arm over DPR {1, 1.5, 2} × integer / fractional letterbox origin × unclipped / fractional x clip / fractional y clip (18 cells), each with engagement, edge-inclusive holder pixels, `perfect` and a same-frame omit twin; `m-snap-frac[dpr]` the displaced-edge FAIL control; any failing cell narrows admission (clipped or not) | §9, §9.0 item 5, §9.1, §11 |
| 2 | major / stale control anchor | Folded: `m-snap-frac` splices `sn=function(z,e,k){return Math.round((z-e)*k*p)/p}` → `sn=function(z,e,k){return(z-e)*k}`; checked exactly once on both players and on their omit twins (rev 12's anchor occurs 0 times) | §9.1 |

### Rev 15 — decision 13 (owner ~14:10, on Q0b-bis `q0bbis-2026-10-12/` and the CEF investigation `cef-frac-2026-10-12/`)

| Item | Disposition | Where |
|---|---|---|
| CEF 127 does not snap the video quad (Q0b-bis trigger: 183 LSB in OBS) | The take reads the host-probed rule: `snap` (Chrome 154) or `frac` (CEF 127: snapped underlay + the unsnapped quad drawn on top, DPR 1 and an integer stage origin only); absent / unknown skips; integer computed `left`/`top` on scene elements; D1 10 571 B, digests re-pinned, `node --check`, §6.1 | §1.1, §3.1, §3.2 |
| Host startup calibration | New W6: `placement_probe.py`, the probe clip, `live_host.py` (start / re-calibrate / off-air re-probe, frozen flag, fingerprint check, `output.placement`), `managed_obs.py` screenshot wrapper; classifier ≤ 2 % vs ≥ 20 %; every failure → no flag | §3.3, §11 |
| Probe controls | `probe-chrome` → snap, `probe-cef` → frac, `probe-undecodable` → no flag; `wrongrule-chrome` / `wrongrule-cef` FAIL; classifier scorer cases | §9, §9.1, §9.2, §10 |
| DPR-1 displaced-edge control | `m-snap-shift[dpr]` (holder one device px right, backing fully opaque) at DPR 1, 1.5, 2; `m-snap-frac` kept at 1.5 and 2 only (at DPR 1 it binds no holder) | §9, §9.1 |
| Instrument | DPR arms need a real `--force-device-scale-factor`; `perfect` at DPR 2 needs the teardown timer delayed; raw-page arms inject the probe result | §9.0, §9.1 |
| Tone (W5) | identity kept; the probe's `tone` slot reserved; Q5 open | §3.3, §12.13, §13 |
| Node | W1's 266 rows unchanged under `snap`, 13 new rows, both players, invariants hold | §8.6, §10 |

### r12 — GPT-6 Astra (Codex), on rev 15 `95c55e45` — CHANGES REQUIRED (6) — folded in rev 16 with decision 14

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / flag integrity | Folded: private per-document state behind a non-configurable getter `window.__obedPlacement` and a token-gated, non-writable updater installed by the host's first-run script; 15 s lease on a pre-captured clock; round trip after every document; tamper rows in Node (assignment, delete, accessor, updater replacement, wrong token, clock, expiry, predefinition); wrong-rule controls through the privileged channel; take bytes read only the getter (D1 10 559 B) | §3.1, §3.2, §3.3, §8.7, §9, §10 |
| 2 | major / output isolation | Folded: the probe never runs in the program page — a second target of the same browser (HDMI/headless) or the `AK-Probe` source in the `AK-Calibrate` scene (managed OBS); program-capture gate before/during; cleanup on every exit; no gate → no calibration; `iso-hdmi`, `iso-obs`, `iso-leak` controls | §3.3, §9, §9.0 |
| 3 | major / classifier | Folded: max-over-channels difference after a tone map from the qualified set {identity, GPU analytic}, inner mask = box eroded 3·DPR, ≤ 2 % / ≥ 20 %, both poses agreeing, one consistent map; lease only for the GPU map (software recorded, skip); shipped clip = the measured `p2like.mp4` (sha256 recorded); `probe-sw`, `probe-undecodable` | §3.3, §9, §10 |
| 4 | major / lifecycle | Folded: invalid / probing / valid bound to target and unique execution context; commit by `uniqueContextId` (late results discarded); revoke on reconnect before commands (or wait for lease expiry); keep-alive with fingerprint; `recalibrate` command through `web/live.py` (changed), `live_session.py`, the presenter UI; `life-cal-*` controls; unchanged-fingerprint GPU reset stated as an unresolved coverage limit | §3.3, §9, §10, §11, §13 |
| 5 | major / acceptance coverage | Folded: `m-snap-cef[clip]` with near-side and far-side fractional clips and foreground crossing, `perfect`, omit twins, edge-inclusive scoring; `m-snap-cef-nooffset[x|y]` wrong-offset controls (Node: only near-side clips move the quad); whole-backing alpha scan stays after both draws | §3.2, §8.7, §9, §9.2 |
| 6 | major / scope | Folded by decision 14 (supersedes decision 8's preview clause); `m-raw-prod`, `m-preview-prod` production-path arms with no channel expect stock movie behaviour; injected `m-raw*` kept as exterior-gate tests only | §3.3, §9, §12 |

### Rev 17 — decision 15 (owner ~15:00: split)

| Item | Disposition | Where |
|---|---|---|
| Take | Rev 13's snapped draw + integer `left`/`top` + the grant read (`"snap"` or skip); `frac` draw removed; D1 10 305 B, digests re-pinned, `node --check`, §6.1 | §3.1, §3.2 |
| Grant | Host knowledge only: launched Chrome + `Browser.getVersion` major 154 + GPU compositing → `snap`; attach / managed OBS / other versions / software / failures → none, reason recorded; rev 16's private channel kept (token, round trip, context-bound commit, re-grant after reload, `observe()` fingerprint revoke); lease and keep-alive dropped (a version-and-launch grant cannot go stale while its process lives) | §3.3 |
| Acceptance | Chrome-only qualification; `cef-skip` in DX-2 (no holder, reason recorded); `grant-*`, `life-grant-*`, channel tamper rows kept; `probe-*`, `iso-*`, `life-cal-*`, `m-snap-cef*`, wrong-rule moved; DX-3 checks the freeze on the HDMI host and the jump in OBS | §9, §9.0–9.3 |
| Streams | W1 rev-17 bytes; W6 shrinks to `live_host.py` + `tests/test_live_host.py`; W2/W3 arms; W4 docs (OBS keeps the jump; follow-up outline) | §10, §11 |
| Follow-up PR | Probe, `frac`, isolation gate, OBS calibrate scene, recalibrate, CEF clip matrix, W5 tone; first step the 5-minute OBS feasibility check | §13.1 |
