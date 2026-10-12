# Dissolve and cut over fill-less slides: a true cross-fade, a clean cut, and movies that freeze and fade

**rev 10 — re-plan after Q0b, for owner review**, 2026-10-12. Rev 1: Opus planner (`8e572864`). Critique r1–r7: GPT-6 Astra
high via Codex (not Opus; owner 2026-10-11), 12 + 7 + 11 + 7 + 6 + 4 + 3 findings, all folded (§14). Revs 2–9: Opus planner
(`cd289a05`, `f3bd8b55`, `4ffcd8ad`, `e5c644bb`, `218308c3`, `cacfe9fb`, `d299b549`, rev 9 = owner GO 2026-10-11 22:10, W1–W4
implemented on this branch up to `fbe105e0`). Rev 10: Opus planner, after Q0b's five re-plan triggers, the Astra xhigh advisory
(`.agents/reviews/dissolve-crossfade/replan-astra-xhigh.md`) and owner decisions 8–11 (2026-10-12, §12). Owner decisions 1–7 in
§12. Plan only: no product code, no commits, no OBS, no Keynote. Base: `main` @ `1589d096`.
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; among the listed anchors only R8, D4 and the hook `_ANCHOR` move,
each by 38). Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored); scratch `x` =
its `plan-2026-10-11/planner/x`; Q0b = its `q0b-2026-10-11/`; rev-10 prototypes = its `plan-rev10-2026-10-12/` (§8). Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins),
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
  generates** (§3.2) onto the **device pixels of the box Chromium paints it at** (decision 9), untoned (**identity `L`**,
  decision 10: the GPU mid-tone step is a known limit), redraws overlying canvases (Q7); D3 puts it in the outgoing fading
  wrapper, or discards it. The `<video>` is never touched; anything outside keeps today's look.
- **Not in this patch (owner Q6):** main's bridge keeps P2's slide-4 decoder at full strength over the terminal fade, stock and
  patched alike; stopping it and S2's hold at the outgoing transition start is a separate follow-up PR after S2 merges.
- **Measured** (headless Chrome 154, §8): cross-fade residual ≤ 1.5 LSB; nulls pop in (205–206); KB dips to α 191; opaque
  on/off ≤ 1.51; cut: stock shows both slides, patched never; freeze: index = last presented. Q0b on rev 9 raised five
  re-plan triggers; rev 10's prototypes answer them: raw export and preview now freeze (P2 2→3 and 4→end), an overflowing
  off-viewport caption or an open navigator skips; holder vs the live movie, browser-rendered, ≤ 3 LSB after the documented
  tone step at 1920×1080 and letterboxed (rev 9: 78), edge band not yet matched at DSF 2 and 2560×1440 (§13); DSK 7→8 take
  9.4–9.8 ms (rev 9 same session 70.3; budget 50).
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
| Where Chromium paints a movie (measured §8) | Blink pixel snapping | The live picture is a bilinear draw of the frame into the content box with every edge rounded on the stage-local CSS grid: P2 slide 2 `[109.35, 795.04, 951.53, 267.61]` paints at `[109, 795, 952, 268]` (fit mean 0.16 LSB after the tone step; the fractional box: max 179). At DSF 2 a row fit (x only) puts the origin on the device grid (x 219) and the size on the CSS grid (1 904); at stage scale 4/3 (2560×1440) no single box fits yet. |

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
  covers exactly the admitted region in the outgoing wrapper, so the group gives `(1−e)·P_out' + e·P_in` (`P_out'` = texture
  with `S` there), as admission proves. On the GPU path `S` lacks the live transfer step (≤ +11.3/255), the known limit.
- **Cut (exported timing only):** incoming 0→1 mirrors outgoing 1→0 over the same 1 ms, started in one loop: opacities sum to 1
  at every instant; a frame inside that 1 ms shows complementary partial opacities (allowed), never both at full strength.
- **Isolation:** the blend's backdrop is the container group only; it cannot make an independent overlay fade (§1.4, §6.2).

## 3. The patch

### 3.1 Exact replacements (R9–R12 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedShape`, `__obedDissolveLayer`, `__obedFreezeTake`, `__obedFreeze` + `renderEffects(A){` (10 237 B; rev 9: 9 225) |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |
| D3 (R11) | after the CSS draw @2313053 (42 B) | `this.cssRenderer.draw(a),a.removeChild(w)}` | `this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}` |
| D4 (R12) | `jumpToScene_partFour` @2353722 / @2353760 (50 B) | `jumpToScene_partFour(A,B){if(this.displayScene(A),` | `jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),` |

The methods (rev 10: `plan-rev10-2026-10-12/scripts/r10.py` `methods10t()`, built by counted substitution from W1's rev-9
constants; `node --check` passes on both patched players, `on` and `rendering`; `PB` and the controller share the module
scope of `TB` and `UC`). Only `__obedFreezeTake` changes: the exterior proof `xo` and the visible stage `V` (decision 8), the
snapped device-pixel holder (decision 9), identity tone with the alpha scan kept (decision 10; `L`, its table and
`_FREEZE_TONE_LUT` go), and the `fill` aspect test goes. `Q` stays the one qualified tuple (`_FREEZE_QUALIFIED_TUPLES`).
Candidate digests (W1 re-pins; `off` unchanged): `on` e9b2fad4 `42104c1b…`, 17c0c938 `bf1ee409…`; `rendering` e9b2fad4
`f2f086eb…`, 17c0c938 `60fac881…`.

```
__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||!1!==x.from.scalar||!0!==x.to.scalar||.001!==x.duration||0!==x.beginTime||"both"!==x.fillMode||x.timingFunction||x.timeOffset||x.repeatCount||x.autoreverses:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,x,u]}catch(E){return null}}
__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=u?"cut":"dissolve",Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}:{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
__obedFreezeTake(U,A){U.__obedFrozen=null;var t0=performance.now();try{var e=U.script.events[A],y=e&&e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),kx=U.script.slideWidth/R.width,ky=U.script.slideHeight/R.height,H=[],N=document.getElementsByTagName("*"),Q=["bt709/bt709/bt709/false"],cs=function(n){return getComputedStyle(n)},dv=function(s,d){return(s||d)===d},bd=function(z){return"none"!==z.borderTopStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle||"none"!==z.borderLeftStyle},rd=function(z){return"0px"!==z.borderTopLeftRadius||"0px"!==z.borderTopRightRadius||"0px"!==z.borderBottomLeftRadius||"0px"!==z.borderBottomRightRadius},deco=function(z){return!/rgba\(0, 0, 0, 0\)|transparent/.test(z.backgroundColor)||"none"!==z.backgroundImage||"none"!==z.boxShadow||bd(z)||"none"!==z.outlineStyle||!dv(z.backdropFilter,"none")},own=function(n,z){return/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED|INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(n.tagName)||deco(z)||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})},bm=function(z){return!deco(z)&&!rd(z)&&"0px"===z.paddingTop&&"0px"===z.paddingRight&&"0px"===z.paddingBottom&&"0px"===z.paddingLeft&&dv(z.objectViewBox,"none")&&dv(z.imageRendering,"auto")},al=function(a){var w=cs(a),s=a===G,u=!s&&a.contains(G),m=w.transform,M;if("block"!==w.display||!dv(w.contain,"none")||!dv(w.contentVisibility,"visible")||"none"!==w.filter||!dv(w.backdropFilter,"none")||"normal"!==w.mixBlendMode||!dv(w.isolation,"auto")||"none"!==w.clipPath||!dv(w.maskImage,"none")||!dv(w.clip,"auto")||"auto"!==w.zIndex||!dv(w.translate,"none")||!dv(w.rotate,"none")||!dv(w.scale,"none")||!dv(w.offsetPath,"none")||!dv(w.willChange,"auto")||!dv(w.zoom,"1")||"none"!==w.outlineStyle||w.overflowX!==w.overflowY||"visible"!==w.overflowX&&!("clip"===w.overflowX&&/^(VIDEO|CANVAS)$/.test(a.tagName))&&("hidden"!==w.overflowX||rd(w)||bd(w)))return!1;if(u)return("static"===w.position||"absolute"===w.position)&&"none"===m;if("absolute"!==w.position||!dv(w.perspective,"none")||!dv(w.backfaceVisibility,"visible")||(s?"preserve-3d"!==w.transformStyle&&"flat"!==w.transformStyle:"flat"!==w.transformStyle&&("preserve-3d"!==w.transformStyle||"none"!==m)||"visible"!==w.visibility))return!1;if("none"===m)return!0;M=new DOMMatrix(m);return M.is2D&&!M.b&&!M.c&&M.a>0&&M.d>0&&Math.abs(M.a/M.d-1)<=.001},xo=function(n){for(var a=n,w,r;!a.contains(G);a=a.parentElement){w=cs(a);if("fixed"===getComputedStyle(a,"::before").position||"fixed"===getComputedStyle(a,"::after").position)return!1;if("hidden"===w.overflowX&&"hidden"===w.overflowY&&"static"!==w.position&&/^(block|flow-root|flex|grid)$/.test(w.display)&&"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&(r=a.getBoundingClientRect(),r.right<=V[0]||r.left>=V[2]||r.bottom<=V[1]||r.top>=V[3]))return!0;if("fixed"===w.position)return!1}return!1},vp=function(a){var h=document.documentElement;return a===h||a===document.body&&"visible"===cs(h).overflowX},pc=function(n){var t=n.tagName,w,b,f;if(/^(HEAD|SCRIPT|STYLE|LINK|META|TITLE|BASE|TEMPLATE|NOSCRIPT)$/i.test(t))return!0;w=cs(n);if("contents"===w.display)return!1;if(!n.checkVisibility({opacityProperty:!0}))return!0;b=getComputedStyle(n,"::before").content;f=getComputedStyle(n,"::after").content;if(!/^(normal|none)$/.test(b||"none")||!/^(normal|none)$/.test(f||"none")||!/^(normal|none)$/.test(w.content||"normal")||"list-item"===w.display||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)}))return!1;if("visible"!==w.visibility)return!0;if(!/^(HTML|BODY|DIV|CANVAS|VIDEO)$/.test(t)||/^(CANVAS|VIDEO)$/.test(t)&&("50% 50%"!==w.objectPosition||!dv(w.objectViewBox,"none")||!/^(fill|contain)$/.test(w.objectFit)))return!1;return"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&dv(w.columnRuleStyle,"none")};for(var V=[0,0,innerWidth,innerHeight],a=G,w,b;a;a=a.parentElement)w=cs(a),"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)&&(b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect(),V=[Math.max(V[0],b.left),Math.max(V[1],b.top),Math.min(V[2],b.right),Math.min(V[3],b.bottom)]);if(!(R.width>0&&R.height>0)||!Array.prototype.every.call(N,function(n){return pc(n)||!G.contains(n)&&!n.contains(G)&&xo(n)}))return;var ad=[];Array.prototype.slice.call(document.querySelectorAll("video")).reverse().forEach(function(v){try{if(!G.contains(v)||v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;var z=cs(v),fit=z.objectFit,K;if(!bm(z)||"50% 50%"!==z.objectPosition||"fill"!==fit&&"contain"!==fit)return;try{var vf=new VideoFrame(v),cc=vf.colorSpace;K=[cc.primaries,cc.transfer,cc.matrix,cc.fullRange].join("/");vf.close()}catch(E){return}if(Q.indexOf(K)<0)return;var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom],a,q,w,b;for(a=v,q=1;a;a=a.parentElement){if(!al(a))return;w=cs(a);q*=+w.opacity;if(a!==v&&"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)){b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}}if(q<.999)return;var vw=v.videoWidth,vh=v.videoHeight,f="fill"===fit?0:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,ch2=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch2)/2;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch2)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;for(var I=Array.prototype.indexOf.call(N,v),i=0,n,o,P,T;i<N.length;i++){n=N[i];if(i===I||n.contains(v))continue;o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||o.top>=c[3]||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;for(P=n.parentElement;!P.contains(v);P=P.parentElement);if(P===G||!G.contains(P))return;for(T=n,a=1;T!==P;T=T.parentElement){w=cs(T);if(!al(T)||i>I&&T!==n&&"visible"!==w.overflowX)return;a*=+w.opacity;if(T!==n&&+w.opacity<1&&Array.prototype.some.call(T.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))a=0}if(i<I)continue;if("VIDEO"===n.tagName){if(ad.indexOf(n)<0)return;continue}w=cs(n);if("CANVAS"!==n.tagName||!bm(w)||"fill"!==w.objectFit||!a)return;Y.push([n,o,a])}var p=devicePixelRatio||1,sn=function(z,e,k){return Math.round((z-e)*k)},u0=sn(cx,R.left,kx),v0=sn(cy,R.top,ky),u1=sn(cx+cw,R.left,kx),v1=sn(cy+ch2,R.top,ky),a0=sn(c[0],R.left,kx),b0=sn(c[1],R.top,ky),a1=sn(c[2],R.left,kx),b1=sn(c[3],R.top,ky),ww=Math.round((a1-a0)/kx*p),hh=Math.round((b1-b0)/ky*p),dx=(u0-a0)/kx*p,dy=(v0-b0)/ky*p,dw=(u1-u0)/kx*p,dh=(v1-v0)/ky*p,i0=Math.max(0,Math.ceil(dx)),j0=Math.max(0,Math.ceil(dy)),i1=Math.min(ww,Math.floor(dx+dw)),j1=Math.min(hh,Math.floor(dy+dh)),x,g,d,j;if(i1<=i0||j1<=j0)return;x=document.createElement("canvas");x.width=ww,x.height=hh;g=x.getContext("2d");g.drawImage(v,dx,dy,dw,dh);for(d=g.getImageData(i0,j0,i1-i0,j1-j0).data,j=3;j<d.length;j+=4)if(d[j]<255)return;Y.forEach(function(y){var l=sn(y[1].left,R.left,kx),m=sn(y[1].top,R.top,ky);g.globalAlpha=y[2],g.drawImage(y[0],(l-a0)/kx*p,(m-b0)/ky*p,(sn(y[1].right,R.left,kx)-l)/kx*p,(sn(y[1].bottom,R.top,ky)-m)/ky*p)}),g.globalAlpha=1;var h=document.createElement("div"),s=h.style,t=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=a0+"px",s.top=b0+"px",s.width=t.width=a1-a0+"px",s.height=t.height=b1-b0+"px",t.left=t.top="0px",h.appendChild(x),H.push(h),ad.push(v)}catch(E){}}),H.length&&(U.__obedFrozen={scene:A,holders:H.reverse()})}catch(E){U.__obedFrozen=null}finally{window.__obedTakeMs=U.__obedTakeMs=performance.now()-t0}}
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

**Paint gate (once per take, before any rectangle test; any failure skips the take; decision 8).** Every element of the
document passes the **element test** or, outside the stage, the **exterior proof**.
- *Element test (rev 9's, unchanged; mandatory for `#stage`, its subtree and its ancestors):* non-rendering
  `head`/`script`/`style`/`link`/`meta`/`title`/`base`/`template`/`noscript` pass; `display: contents` fails; no box or an
  opacity-0 group (`checkVisibility({opacityProperty})` false: nothing of it paints) passes. Otherwise, before any visibility
  shortcut, `::before`/`::after` and own `content` must be `none`/`normal`, no `display: list-item`, no direct text. A
  `visibility`-hidden element then passes (its own box does not paint). A visible one must be a supported paint family —
  `html`, `body`, `div`, `canvas`, `video` (no `img`, `svg`, `object`, `embed`, `iframe`, form control) — without `box-shadow`,
  `filter`, `backdrop-filter`, `outline`, `border-image`, `-webkit-box-reflect` or column rule; a `canvas`/`video` needs
  `object-position: 50% 50%`, `object-fit` `fill`/`contain`, no `object-view-box` (content inside its box). Its paint is then
  confined to its border box, so the per-movie rectangle test sees it: an exterior element that passes (main's bridged decoder
  in `#body` is one) and meets a movie's region skips that movie (no common ancestor inside the scene), as in rev 9.
- *Exterior proof (an element neither inside `#stage` nor an ancestor of it that fails the element test):* walking from it up
  to, not including, its first ancestor that contains `#stage`, a **validated clipping ancestor** `A` is reached before any
  `position: fixed` element (`A` itself may be fixed), and no element on the walk (`A` included) has a fixed `::before` or
  `::after`. `A` has `overflow: hidden` on both axes (no `clip` margin, no scroll), is positioned (every non-fixed descendant's
  containing block is then inside it, so its overflow clip applies to all of them), has `display` `block`/`flow-root`/`flex`/
  `grid` (overflow applies), paints nothing outside its own box (no `box-shadow`, `filter`, `backdrop-filter`, `outline`,
  `border-image`, `-webkit-box-reflect`), and its transformed bounding box is disjoint from the **visible stage** `V`. `V` = the
  viewport ∩ every rectangle clip on `#stage`'s chain, by the same rule admission intersects (positioned ancestor with
  non-`visible` overflow; root, or `body` when the root is `visible`, to the viewport), so every admitted region lies inside
  `V`, and nothing below `A` can paint inside `V`. Border-box disjointness of the failing element itself is never used.
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
| scene elements (below `#stage`): scene root, layer and movie divs, texture `<canvas>`, `<video>` | `NB.draw`, `NB.addNode`, `xB.initVideo`, `movieDiv` | `position: absolute`; `visibility: visible`; `transform-style: flat`, or `preserve-3d` with `transform: none` (the build wrappers; every transform below is 2D, so all is coplanar); `perspective: none`; `backface-visibility: visible`; `transform` none or 2D `matrix(a, 0, 0, d, e, f)` with a, d > 0 and \|a/d − 1\| ≤ 0.1 % |
| `#stage` | `Cg.adjustStageToFit` | `position: absolute`; `transform-style: preserve-3d` or `flat`; `transform` as above (its `scaleX`/`scaleY`); `visibility` any (inherits `#stageArea`'s hidden) |
| above `#stage` (`#stageArea`, `body`, `html`) | page CSS, host | `position: absolute` or `static`; `transform: none`; background and visibility any |
| the movie itself | | plain bitmap (below); `readyState ≥ 2`, decoded size, `checkVisibility({opacityProperty, visibilityProperty})`; chain opacity product ≥ 0.999; `object-fit` `contain` or `fill`; `object-position: 50% 50%`; `VideoFrame` colour tuple (primaries/transfer/matrix/fullRange) ∈ `Q`; alpha 255 at every device pixel fully inside the snapped content box ∩ region, read after the draw and before any redraw |
| a later painted element | | an admitted `<video>` (its holder is appended after), or a plain-bitmap `<canvas>` with `object-fit: fill`, `overflow: visible` above the leaf and no translucent ancestor painting anything else, redrawn into its snapped rect at device scale and its effective opacity |
| plain bitmap | | no background colour or image, box-shadow, border, outline or `backdrop-filter`; zero radii and padding; `object-view-box: none`; `image-rendering: auto` |

Why this proves the picture: the gate confines all paint to border boxes; admitted chains and branches are block, absolute,
`z-index: auto` and 2D (coplanar) in one scene subtree, so paint order is document order (CSS 2 App. E); the only clips are
the intersected rectangles; nothing crops, filters, blends or contains paint; ancestor backgrounds paint beneath.

- **Tone (decision 10):** identity `L` — the snapshot is the decoded frame as `drawImage` gives it; no RGB write, no
  `putImageData`, no table. The alpha scan stays: every device pixel fully inside the snapped content box ∩ region must read
  α 255 after the movie draw and before the foreground redraw, so the holder covers its region opaquely (the baked frame below
  never shows through). Known limit (§12.5): on the GPU compositing path the live movie carries Chromium's `BT709_APPLE`
  transfer step (mid-grey 128 → 139, max +11.3/255 at 113, 0 at black/white) and the frozen frame does not; software
  compositing is identity (Q0b 1). `Q` stays the one measured tuple; W5 decides whether a host-calibrated `L` can come back.
- **Geometry (decision 9; device pixels, snapped as Blink snaps the movie):** element box → content box (`object-fit`,
  centred) → ∩ rectangular clips = region `c` (screen px). Chromium paints a `<video>` into its content box with every edge
  rounded on the stage-local CSS grid (slide px): the live picture matches a bilinear draw into the snapped box
  `[109, 795, 952, 268]`, not the fractional `[109.36, 795.03, 951.5, 267.61]` (§8). The take snaps the same way:
  `sn(z) = round((z − R.left)·kx)` (y with `R.top`, `ky`) for the content box (`u0`…`v1`) and the region (`a0`…`b1`), in
  slide px. The holder is a `div` (overflow hidden) at the snapped region, holding one canvas of the same CSS size whose
  backing is its device size (`round((a1 − a0)/kx·DPR)` × `round((b1 − b0)/ky·DPR)`); the movie is drawn once into the snapped
  content box at device scale, `drawImage(v, dx, dy, dw, dh)`, and each redrawn canvas into its own snapped rect at its
  effective opacity. At stage scale 1 (1920×1080, letterboxed, DSF 2) the canvas lands 1:1 on device pixels; at a non-unity stage
  scale (2560×1440) Blink snaps the canvas in slide px and the compositor resamples it (residual quantified, §8, §13).
  `object-fit: fill` needs no aspect test any more (the destination is the content box itself).
- **Snapshot, not move; failure model:** a move is a detach the core observes (`stash` re-plays and remounts it); `drawImage`
  is the exact last presented frame (rVFC). Add-only, per movie, after the cross-fade rules are committed; the `<video>` is
  only read (no write; no call besides `checkVisibility`/`getBoundingClientRect`), so the core sees the detach as today.
- **Cost:** `window.__obedTakeMs` (also on the controller, which page scripts cannot reach) = the take's total wall time
  (gate, every candidate incl. rejected ones, draws, readbacks, alpha scans, redraws), written in a `finally` on every path.
  Work now scales with the movie's on-screen device area, not its natural size (DSK 7→8: 313×263 + 469×263 device px instead
  of 1282×1080 + 1922×1080 source px). Retained: one region-sized canvas per frozen movie (P2: 952×268 ≈ 1 MB at DSF 1),
  freed with the transition DOM; transient: one interior `ImageData` per movie and a closed `VideoFrame`.
- **Cleanup is the player's:** holders live in the transition DOM (removed at the next scene, go-to/back, replay, queued skip;
  kept invisibly at the end-of-show endpoint); an unattached take is dropped at D3 or by the next take (lifecycle rows, §9.1).
- **Residuals (today's baked-frame jump):** gate or allowlist misses (incl. an open preview navigator); G2-drawn movies;
  undecodable codecs; tuples outside `Q` (incl. untagged H.264 under software compositing, which decodes `smpte170m…` — it
  would freeze exactly there, but the tuple is unmeasured on GPU); hyperlink transitions (skip D4; never used live);
  self-playing mode (host-refused); the bridge/hold until the Q6 follow-up. **Known limits (frozen, not jumping):** the
  mid-tone step (identity `L`); holder edge resampling at non-unity stage scales (§13).

## 4. Switch, pins, report

- **Switch (decided):** D1–D4 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`, `patch_rendering` and every synthetic test
  player pick them up; `mm_opacity=False` stays the hook-only bytes (`7cf00b56…` / `4f9fbffd…`); docstrings say "rendering
  fidelity"; README: `OBED_LIVE_MM_OPACITY=off` also restores the export's dissolve, cut and movie behaviour. **Pins:**
  `(on, off, rendering)` kept; `on`, `rendering` re-pinned. **Report** `output.mmOpacity = {mode, sha256}`; `RUNTIME_VERSION`
  stays 2; preview inherits the patch, F3 included (the raw/preview page now passes the gate, decision 8); paint oracle stays stock; `web/live.py` unchanged.

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
anchors and their offsets are unchanged (only D1's replacement grows, to 10 237 B); the same five properties hold.

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
options: Chrome 121; `VideoFrame(video).colorSpace`: Chrome 94. OBS 32.2.2 bundles CEF 127: availability only (compositor,
tone path and LUT: DX-2). Headless: Chrome 154.0.8037.59, ANGLE Metal; software compositing via `--disable-gpu`.

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`; Q0b; rev 10)

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
| rev 10, DSF 2 | 1904×536 | 250 | 250 (244 p99; 7.0 %; 99.5 % within 2 px of a content edge; flat 5) | 1 | INCONCLUSIVE (the transition completed before the capture); 0 for the same canvas box in window 1 |
| rev 10, 2560×1440 (stage scale 4/3) | 1269×357 | 158 | 165 (150; 9.4 %, all on content edges; flat 3) | 12 | 163 (canvas resampled by the compositor) |

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
toned the full 1282×1080 and 1922×1080 frames. The source-region crop is not adopted: the draw costs ≤ 0.3 ms and on every
measured slide the region is the whole content box. The DSK 7→8 window-1 figures are the fractional-box bytes, which do the same
pixel work as §3.1 at DSF 1; W1's Q0b-bis re-times the exact bytes (§9.0).

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
| Holder pixels (browser-rendered; tone-compensated; stage scale 1) | `m-snap` (1920×1080, letterboxed); instrument: `perfect` | `m-snap-frac` (`sn` unrounded) |
| Exterior gate (raw / preview pages engage; unproven exterior paint skips) | `m-raw` (P2 2→3, 4→end) | `m-raw-caption`, `m-raw-nav-open` |
| Tone match — blocking only if a non-identity `L` returns (W5); report-only under identity | (`m-tone`) | (`m-tone-raw`) |
| No independent overlay | `m-on` | `m-bridge-off` (stock twin) |
| Cost | scorer case: 50 ms; stub rows: total published on success, rejection, exception | scorer case: 50 ms + ε (missing or non-finite → INCONCLUSIVE) |

### 9.0 Q0b-bis — step 0 on the rev-10 bytes (scratch; after W1's re-pin, before DX-1; browser windows on request)

Done: Q0b on rev 9 (§8.1); rev-10 prototypes (§8.2). Pending (a miss re-plans):
1. **Exact bytes, cost:** W1's built `on` player (the §3.1 digests) on DSK 7→8, five fresh launches at load < 4, plus raw P2
   2→3 and 4→end; every take ≤ 50 ms; per-stage times from the timer variant recorded.
2. **CEF preflight (decision 11, T5; measurement only):** a scratch `ManagedObs` driver, OBS 32.2.2 / CEF 127, the served
   bytes of step 1 (or W1's current bytes if they are not ready), two fresh launches. Per launch: OBS/CEF version, browser
   acceleration setting, served digest, continuity and G2 state; the tone movie paused at frames 30/300/900 in `h264u`, `h264t`,
   `hevc10` and Keynote HEVC — live `GetSourceScreenshot` vs the holder (`toDataURL`) on the verified exposed mask, decoded
   tuple, and decode evidence for anything undecodable; engagement (P2 2→3 one bound holder, DSK 7→8 two); DSK 7→8 cost ×3
   (each ≤ 50 ms); holder vs live at the source geometry (stage scale 1), tone-compensated with the launch's own measured map,
   reported. Recorded as a "CEF preflight" block of the decision record. A cost > 50 ms, an engagement miss or holder edges
   > τ at the source geometry re-plan before DX-2; tone results feed W5 only.
3. **Geometry beyond stage scale 1** (DSF 2, 2560×1440): §8.2's band measurement repeated on the exact bytes, reported for
   the owner (§13); not a gate.
4. **Dry runs of the new captures:** `m-snap`/`-frac`/`perfect`, `m-raw*`, the hide/hide-screen screencast rows, D2 `on` on
   the both-opaque class, `m-tone` with its twin.

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver (W2; reused by W3; read-only).** Stock `index.html`, player, slide JSON from `html-unmodified`; PDFs from a fresh
  scratch strip (715cb3f1's stripper); movies mapped to decodable copies (P2: `html-player` H.264; DX-M: the binary counter
  re-encoded BT.709-tagged into scratch unless Q0b qualifies the untagged tuple; tone arms: the **tone movie**, same encoder:
  counter strip, 220-step luma ramp, 25–100 % colour patches, skin tones, in Q0b 1's encodings). Provenance recorded.
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1 unless the arm says otherwise, own port (never 9222);
  `LiveOutputHost` attach or launch; `m-raw*` arms serve the resolver's export as-is (its own `index.html`, navigator present)
  over the same static server and advance with Space over CDP.
- **Instrument.** Innermost hook from the first rAF with the transition DOM: each leaf's effective opacity (also before any
  animation attaches), every transition animation (`currentTime`, `startTime`, value), scene/hash; every `<video>` tagged
  (`WeakMap` id) with rect, effective opacity, transition-DOM membership, colour tuple, rVFC records and detach time;
  `window.__obedTakeMs`; at that first rAF the textures, every holder (`toDataURL`, slide-px geometry) and the blend/isolation
  chain. Alpha PNG screenshots from 0.35 s before the advance to T + 0.6 s; cut arms **and the hide / hide-screen lifecycle
  rows** add a per-frame screencast (DX-1's ~6 fps full-resolution screenshots cannot put six mid frames outside a 0.5 s hidden
  interval; a measurement change, no contract change). **Reference capture (`m-snap*`, `m-tone`; paused):** after the first
  transition rAF the driver pauses every document animation, seeks it to 0.5·T, 0.9995·T and 0 and screenshots each state
  (`F50`, `B`, `A0`: browser-rendered, progress exact and outside the media); the `perfect` instrument control then overwrites
  the holder canvas with `S_live`'s own device pixels and screenshots once more. Before the advance, the redrawn foreground
  canvases are kept (`toDataURL`, rect, effective opacity).
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
  analytic table, within 1 of measurement; software: identity), so the known tone limit is not read as geometry. **Verified
  painted-foreground mask:** α > 0 of every redrawn canvas mapped to its device rect, ∪ pixels where the holder differs from its
  `m-fg-omit` twin's (same paused frame), dilated 2 px; valid only if the twins differ nowhere outside the dilated α mask.
- **Capture integrity (any violation INCONCLUSIVE):** texture ids, hash before/after, screenshot size, page mode and served
  digest as stated; finite, non-empty measurements; fade arms ≥ 6 mid frames (0.05 < e < 0.95, transition DOM present); delay
  arms ≥ 2 screenshots and rAF coverage in the window; cut arms rAF coverage from DOM insertion to 3 frames after the cut and a
  screencast frame inside; paused arms two identical `S_live`; media arms the evidence below; lifecycle rows a settled frame,
  hide rows ≥ 6 screencast mid frames outside the hidden interval; reference arms the transition DOM present at every seeked
  capture, each animation's `currentTime` as requested (± 1 ms), and `|F50 − (A0 + B)/2|` ≤ 2 over the frame (measured 1);
  tone arms the mask verification above and coverage: a cell (ramp step or patch, eroded 2 px) counts with ≥ 16 exposed px,
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
| Holder pixels | stage scale 1: interior and edge band max ≤ τ = 4 (1920×1080 and letterboxed: 3 and 1; FAIL control `m-snap-frac` 216, 5.3 % of px > τ; `perfect` 0); DSF 2 and 2560×1440: band reported (§8.2: 250 / 165, 7.0 % / 9.4 % of px, on content edges) |
| Exterior gate | `m-raw`: each take publishes `__obedTakeMs` and binds one holder in `layer<out>-opacity`; negatives: a published take, the transition DOM present, and no holder (measured: 1 / 1 holder; 0 / 0) |
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
| `m-snap` | `m-paused` at 1920×1080 and at a letterboxed 1920×1200 viewport; reference capture | out-only | holder pixels → PASS; `perfect` → 0 (instrument) | as `on` + one holder | pinned `on` |
| `m-snap-frac` | as `m-snap` 1920×1080; one counted splice `sn=function(z,e,k){return Math.round((z-e)*k)}` → `sn=function(z,e,k){return(z-e)*k}` | out-only | holder pixels → FAIL | as `m-snap` | base + splice |
| `m-snap-dsf2` / `m-snap-2560` | as `m-snap` at DSF 2 / 2560×1440 | out-only | holder pixels → REPORTED (band, §13) | as `m-snap` | pinned `on` |
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
| hide / show | hide mid-dissolve, show 0.5 s later; per-frame screencast | while hidden: output fully transparent (alpha) / black (screen), checked separately; after show the model holds on ≥ 6 screencast mid frames |
| automatic | in-memory override: `automaticPlay: true`, `beginTime` 0.5 s | incoming 0 and the frozen frame through the real delay branch; then as advance |
| loop wrap | in-memory `loopSlideshow: 1`, P2 slide 4's dissolve | as advance onto slide 1 |
| end of show | P2 slide 4's dissolve, loop 0 | held endpoint = stock twin's (DOM, holder, rules legitimately remain); then go-to 1 → cleanup; a bridged decoder is judged by `m-bridge` only |

Q0b's lifecycle pass was a dry run (advance, replay, back without a stock-twin destination, queued advance reported), not
qualification: DX-1 runs every row against its stock twin, the go-to/back destination included.

### 9.2 DX-2 inside OBS CEF — `managed_obs_qualify.py --arm dissolve` (unrecorded)

One launch, the managed bridge with DX-1's hook, resolver, integrity rules and scorer (W2), the advance, a `GetSourceScreenshot`
burst. Sessions: DX-1's P2, `p2cut`, `p2-binary` and tone arms except `screen-*`, `delay-*`, `on-sw` and the lifecycle (tone
arms report-only under identity `L`), plus DSK 7→8 (two bound holders; cost ≤ 50 ms, decision 11) and `m-snap` at the browser
source's geometry (holder pixels vs a pre-advance source screenshot, tone-compensated with that launch's measured map, ≤ τ_CEF);
media sessions (not `m-off` or the bridge arms) show a bound D4 holder; all record
continuity, G2 state, colour tuples and served digest; cut sessions need rAF coverage from DOM insertion to 3 frames after the
cut and ≥ 1 source screenshot inside (no screencast in CEF). Every control outcome (incl. the `m-bridge-off` FAIL) is read
before `m-on` and the candidate count; `m-bridge` is reported only. **Calibration fixed before capture, applied without
clamping:** n = max mid-frame residual of `opaque-off`; τ_CEF = max(4, ⌈n⌉ + 1); complement 2 + ⌈n⌉; no dip 252 − ⌈n⌉; caps
τ_CEF ≤ 8, complement ≤ 6, no dip ≥ 248, so n > 4 is INCONCLUSIVE. Refuses while `OBED_LIVE_MM_OPACITY` is set.

### 9.3 DX-3 owner check in real OBS

- **Pre-check:** DX-1's texture classifier on the chosen production transition: fill-less outgoing and ≥ 2 000 px in-only →
  affected, else a regression control. Movie: an H.264 slide that plays live in OBS, preferably with foreground over it.
- **Where:** Take output (Keyer): stripped P2 2→3, the pre-checked transition, an H.264 movie slide several seconds in.
- **Pass:** slide 3 fades in from nothing; slide 2 keeps its colours while fading; no darker or more transparent overlap; the
  movie stops on its current frame and fades out with slide 2, foreground intact; no jump at the hand-off. At the freeze the
  documented mid-tone step (identity `L`, decision 10) is shown to the owner as the known limit, not a failure.
  **Null** (affected transitions only): `OBED_LIVE_MM_OPACITY=off` shows the pop-in and the jump.
- **Report** candidate and null separately with the served mode, `output.mmOpacity.sha256` and the decision record.

### 9.4 Regression

`run_gates.sh` full tier from a fresh pinned worktree; `mm_opacity_probe.py`, `mm_handback_probe.py`; managed OBS (owner
session) `--arm mmo`, `--arm g2`, `--arm mmo-cef`. Root-cause any change.

## 10. Tests (three new test functions, as rev 3; everything else extends them; rev 10 adds rows, no new function)

1. **Free:** tuple-parametrized anchor/replacement refusal (both patchers); off identity; `patch_rendering` = `patch_player` minus
   the hook; "every original anchor gone" (`test_live_runtime.py:205`, `:265`, `:367`); equivalence; `node --check`; pin mismatch.
2. **Edits** (`test_live_runtime.py`): re-pin (§3.1 candidate digests); hand-back tests use `HANDBACK = slice(5, 8)`; the
   composition test runs R1–R5, R6–R8, D1–D4 in every order and checks containment including self.
3. **REAL-gated Node function, both players, one case table** (real extracted code): D1–D4 offsets; ids; committed transitions;
   near-misses; construction failures; the 200 freeze-stub rows (§8.2) with rev 10's expectations: `devicePixelRatio` stubbed
   (1 by default; rows at 2, 1.5 and 2 × stage 4/3); snapped device-pixel holder geometry and backing; no `putImageData` on any
   path (trace pattern `(v(gf*)?)?`); the alpha rows index the scanned device interior (first, last, one inside; one partial
   edge pixel outside it admits); `fillAspectChange` admits; the `L` rows become "pixels untouched". **Exterior-proof rows**
   (one property each, from the same property table): a failing off-stage subtree under a validated clipper disjoint from `V`
   admits (the navigator shape); each skips: clipper meets `V`; clipper `overflow` `visible`/`auto`/`clip`; clipper `static`;
   clipper `display: inline`; clipper with `box-shadow`/`outline`/`filter`/`border-image`; a `position: fixed` element between
   the failing node and the clipper; a fixed `::before` on the walk; a failing element with an off-viewport border box and no
   clipper (the overflowing caption); a failing ancestor of `#stage`; a passing exterior `<video>` meeting the region (main's
   bridge) skips that movie.
4. **`tests/test_dissolve_probe.py`, the one parametrized function** (synthetic numpy), existing rows kept, plus: holder pixels —
   exact holder PASS, 1-px shifted FAIL, tone step only (compensated by `L_path`) PASS, edge-band step FAIL; painted mask — twin
   differs outside the dilated α mask → INCONCLUSIVE; tone coverage < 50 % → INCONCLUSIVE; reference capture — `currentTime`
   off, transition DOM gone, `F50` inconsistent → INCONCLUSIVE; no dip on the both-opaque class with identical colours (α 255
   PASS, KB α 191 FAIL); hide row with < 6 screencast mid frames → INCONCLUSIVE; exterior gate — bound holder PASS, published
   take without holder FAIL, no published take → INCONCLUSIVE; strip decode from a device-scale holder.
5. **`test_managed_obs_qualify.py`:** the env-refusal test parametrized over the new arm; the calibration test (n = 4 / 4 + ε);
   the session list includes DSK 7→8 and `m-snap`.

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` (done, `7fa7c8dd`) |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | rev 10's `__obedFreezeTake` byte-exact to §3.1 (`_FREEZE_TONE_LUT` removed; `Q` kept); docstrings (identity tone, device-pixel holder, exterior proof); re-pins; tests 1–3 |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | reference capture (seek + `perfect`), holder-pixel scorer with `L_path`, verified painted-foreground mask (+ twin), tone coverage, device-scale holder paste and strip decode, `m-snap*` and `m-raw*` arms (raw-page driver), hide-row screencast, both-opaque no-dip class; test 4 |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | DSK 7→8 cost and `m-snap` sessions; tone sessions report-only; test 5 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, `.agents/handovers/keynote-live-dissolve-crossfade-followups.md` | README/SKILL: the identity-tone known limit; follow-ups handover: W5, the Q6 PR, holder geometry beyond stage scale 1, the optional G2 use of a qualified `L` |
| W5 | scratch + evidence only (no tracked file) | **Host-side compositing-path calibration feasibility probe** (decision 10; non-blocking for this PR, needed before Q5 closes): can the host, at startup, identify the compositing path and its map (qualified path + tuple → `L`, unknown → identity) from compositor-painted pixels? Headless `LiveOutputHost` (GPU, `--disable-gpu`) and managed OBS (acceleration on/off), two fresh launches each: the tone movie paused in an off-screen-safe calibration slot, CDP screenshot / `GetSourceScreenshot` vs `drawImage`; repeatability, distinguishability of GPU vs software for the same tuple, invalidation on GPU-state change (GPU process loss, acceleration toggle); a record with a go/no-go and, on go, the player-boundary change it would need (owner decision) |
| Q0b-bis | scratch + evidence only | §9.0: exact-bytes cost, CEF preflight (T5), geometry band beyond stage scale 1, dry runs of the new captures |

Order: W1 ∥ W2 ∥ W3 ∥ W4 → Q0b-bis → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-1
(fresh pinned worktree, controls first) → DX-2, `mmo-cef`, regression (§9.4), DX-3 (owner session) → one PR to `main`. Never
merge. W5 runs whenever a browser window is free; it does not gate the PR.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and construction failure; export JSON never mutated. (3) Rule ids = allocated ids. (4) One `applyCssAnimation` pass; cut only
at the exported timing. (5) D4/D3 add-only, never touch a `<video>`; only gate + allowlist passes are admitted; attach by kind.
(6) `off` = today's bytes. (7) Thresholds measured or by formula; PASS and FAIL controls for every blocking check. (8) The
exterior proof never trusts a failing element's own border box; every pruned subtree is clipped by a validated ancestor
disjoint from `V`. (9) Holder canvas = device pixels of the snapped box; alpha scan before the redraw; no tone write.

## 12. Owner decisions (1–7 2026-10-11, 8–11 2026-10-12, in chat)

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

8. **T2, gate: strict stage admission plus a conservative exterior pass.** An off-stage subtree is pruned only when its paint
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

## 13. Risks and out of scope

- **Holder geometry beyond stage scale 1 (the owner's quantification, decision 9; no envelope).** At DSF 2 the live movie's
  origin snaps on the device grid while the holder canvas can only start on the CSS grid: 7.0 % of the region's px exceed τ,
  99.5 % of them within 2 px of a content edge, max 250, flat max 5. At 2560×1440 (stage scale 4/3) Blink snaps the canvas in
  slide px and the compositor resamples it: 9.4 % of px > τ, all on content edges, max 165, flat max 3. In both, the frozen
  frame is the right frame at the right place; content edges inside it are one device pixel off or resampled for the 1.5 s
  fade. Every geometry DX-1 and DX-2 qualify runs at stage scale 1 (1920×1080, DSF 1); the CEF preflight records the source
  geometry. Open for the owner (not decided here): accept as a documented limit; skip the take when stage scale or DSF ≠ 1
  (today's jump instead); or a follow-up that models Blink's snapping per DSF and scale.
- **Tone:** identity `L` keeps the GPU mid-tone step (≤ +11.3/255, ΔL* ≈ 4.3 at mid-grey) at the freeze; W5 may bring a
  qualified `L` back. Software compositing would freeze exactly, but its untagged-H.264 tuple is outside `Q`.
- **CEF:** compositor, snapping at the source geometry, tone path and cost unproven until the preflight and DX-2.
- **Exterior proof** relies on overflow clipping semantics (positioned clipper, no fixed escape); a page that adds fixed or
  unclipped chrome later simply skips the take.
- ids rest on `VB`'s pre-order allocation (proved); production transparency; the bridge/hold (Q6).

Out of scope: F2, GL effects, Keynote-app comparison, S2 and its follow-up.

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
| T1 cost (DSK 7→8 47.6–51.9 ms) | Bound kept at 50 ms. Profiled per stage; the cost was full-resolution readback and toning of 1282×1080 + 1922×1080 frames shown at 312×263 + 468×263. Device-pixel holder + identity tone: 9.4–9.8 ms (rev 9 same session 70.3); source crop measured unnecessary (draw ≤ 0.3 ms, region = content box) | §3.2, §8.2, §9.0 |
| T2 gate (raw/preview miss) | Element test kept for the stage and its ancestors; exterior proof (validated clipping ancestor disjoint from `V`) for everything else; raw P2 2→3 and 4→end freeze; overflowing caption and open navigator skip; bridge still blocks | §3.1, §3.2, §8.2, §9 (`m-raw*`), §10 |
| T3 holder edges (78 LSB) | Re-measured with browser-rendered references (seeked animations; progress exact, outside the media); the holder is drawn into the device pixels of the box Blink snaps the movie to: ≤ 3 LSB after the tone step at 1920×1080 and letterboxed (FAIL control 216); DSF 2 / 2560×1440 band quantified, open for the owner | §1.1, §3.2, §8.2, §9.1, §13 |
| T4 tone (software path identity, same tuple) | Identity `L` shipped; RGB writes, `putImageData` and the table removed; alpha scan kept; W5 feasibility probe for a host-calibrated path + tuple → `L` | §2, §3.2, §11, §12.10 |
| T5 CEF | Preflight on the rev-10 bytes before DX-2 (tone ×2 launches, engagement, DSK 7→8 cost, holder at the source geometry) | §9.0, §9.2 |
| Hide / hide-screen rows INCONCLUSIVE by construction | Per-frame screencast for those rows (measurement change) | §9.1 |
| Tone mask empty (`3231B69B` covers the movie rect) | Verified painted-pixel mask (α > 0 ∪ twin difference, dilated 2 px; twin agreement checked) with a coverage rule; measured 162/220 ramp steps, 22/28 patches, 8/8 skin; report-only under identity | §8.2, §9.1 |
| D2 `on` no-dip INCONCLUSIVE (classes < 2 000 px) | No dip read on the both-opaque class (α is colour-independent): D2 has 180 687 px (differing overlap 0, hence rev 9's empty class) | §9.1 |
| Dry run ≠ qualification | Lifecycle rows run against stock twins in DX-1, go-to/back destination included | §9.1 |
