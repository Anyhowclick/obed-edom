# Dissolve and cut over fill-less slides: a true cross-fade, a clean cut, and movies that freeze and fade

**DRAFT rev 8**, 2026-10-11. Rev 1: Opus planner (`8e572864`). Critique r1–r6: GPT-6 Astra high via Codex (not Opus; owner
2026-10-11), 12 + 7 + 11 + 7 + 6 + 4 findings, all folded, plus the first real-DOM probe (§8, §14). Revs 2–8: Opus planner
(`cd289a05`, `f3bd8b55`, `4ffcd8ad`, `e5c644bb`, `218308c3`, `cacfe9fb`, this). Owner decisions 1–7 recorded (§12). Round 7
is the owner's last critique round. Plan only: no product code, no commits, no OBS, no Keynote. Base: `main` @ `1589d096`.
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; among the listed anchors only R8, D4 and the hook `_ANCHOR` move,
each by 38). Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored); scratch `x` =
its `plan-2026-10-11/planner/x`. Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins),
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
  outgoing texture (§1.4). D4 first requires the page's paint to stay inside element boxes (**paint gate**), then snapshots
  each `<video>` whose chain lies inside a **positive allowlist of the computed styles the player generates** (§3.2),
  tone-matches it (Q5) and redraws overlying texture canvases (Q7); D3 puts it in the outgoing layer's fading wrapper, or
  discards it. The `<video>` is never touched; anything outside keeps today's look. Real P2 DOM (debug build, §8): both movies
  admitted, square redrawn, frozen 48 held; stub DOMs admit every movie on the six Dissolve-ending movie slides.
- **Not in this patch (owner Q6):** main's bridge keeps P2's slide-4 decoder at full strength over the terminal fade, stock and
  patched alike; stopping it and S2's hold at the outgoing transition start is a separate follow-up PR after S2 merges.
- **Measured** (headless Chrome 154, §8): cross-fade residual ≤ 1.5 LSB; nulls pop in (205–206); KB dips to α 191; opaque
  on/off ≤ 1.51; cut: stock shows both slides, patched never; freeze: index = last presented, untoned −11/255 at mid-grey.
  Rev 8's admission is checked against one real P2 DOM (§8); LUT, gate and DSK on the real DOM wait in Q0b (§9.0).
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
  carry HEVC Main 10 `tv, bt709`; `p2-binary`'s untagged H.264 decodes as BT.709 (§8). DSK fixtures are ProRes (never live).

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
- **Frozen movie:** the opaque snapshot `S = L(frame)` plus redrawn overlying canvases covers exactly the admitted region in
  the outgoing wrapper, so the group gives `(1−e)·P_out' + e·P_in` (`P_out'` = texture with `S` there), as admission proves.
- **Cut (exported timing only):** incoming 0→1 mirrors outgoing 1→0 over the same 1 ms, started in one loop: opacities sum to 1
  at every instant; a frame inside that 1 ms shows complementary partial opacities (allowed), never both at full strength.
- **Isolation:** the blend's backdrop is the container group only; it cannot make an independent overlay fade (§1.4, §6.2).

## 3. The patch

### 3.1 Exact replacements (R9–R12 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedShape`, `__obedDissolveLayer`, `__obedFreezeTake`, `__obedFreeze` + `renderEffects(A){` (8 990 B) |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |
| D3 (R11) | after the CSS draw @2313053 (42 B) | `this.cssRenderer.draw(a),a.removeChild(w)}` | `this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}` |
| D4 (R12) | `jumpToScene_partFour` @2353722 / @2353760 (50 B) | `jumpToScene_partFour(A,B){if(this.displayScene(A),` | `jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),` |

The methods (scratch `dpatch11.py`; `node --check` passes on both patched players; `PB` and the controller share the module
scope of `TB` and `UC`). `Q` (qualified colour tuples) and `L` (the tone map) are the two constants Q0b's decision record
fixes (§9.0, §12.5); shown with their provisional values.

```
__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||!1!==x.from.scalar||!0!==x.to.scalar||.001!==x.duration||0!==x.beginTime||"both"!==x.fillMode||x.timingFunction||x.timeOffset||x.repeatCount||x.autoreverses:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,x,u]}catch(E){return null}}
__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=u?"cut":"dissolve",Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}:{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
__obedFreezeTake(U,A){U.__obedFrozen=null;var t0=performance.now();try{var e=U.script.events[A],y=e&&e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),kx=U.script.slideWidth/R.width,ky=U.script.slideHeight/R.height,H=[],N=document.getElementsByTagName("*"),Q=["bt709/bt709/bt709/false"],cs=function(n){return getComputedStyle(n)},dv=function(s,d){return(s||d)===d},bd=function(z){return"none"!==z.borderTopStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle||"none"!==z.borderLeftStyle},rd=function(z){return"0px"!==z.borderTopLeftRadius||"0px"!==z.borderTopRightRadius||"0px"!==z.borderBottomLeftRadius||"0px"!==z.borderBottomRightRadius},deco=function(z){return!/rgba\(0, 0, 0, 0\)|transparent/.test(z.backgroundColor)||"none"!==z.backgroundImage||"none"!==z.boxShadow||bd(z)||"none"!==z.outlineStyle||!dv(z.backdropFilter,"none")},own=function(n,z){return/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED|INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(n.tagName)||deco(z)||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})},bm=function(z){return!deco(z)&&!rd(z)&&"0px"===z.paddingTop&&"0px"===z.paddingRight&&"0px"===z.paddingBottom&&"0px"===z.paddingLeft&&dv(z.objectViewBox,"none")&&dv(z.imageRendering,"auto")},al=function(a){var w=cs(a),s=a===G,u=!s&&a.contains(G),m=w.transform,M;if("block"!==w.display||!dv(w.contain,"none")||!dv(w.contentVisibility,"visible")||"none"!==w.filter||!dv(w.backdropFilter,"none")||"normal"!==w.mixBlendMode||!dv(w.isolation,"auto")||"none"!==w.clipPath||!dv(w.maskImage,"none")||!dv(w.clip,"auto")||"auto"!==w.zIndex||!dv(w.translate,"none")||!dv(w.rotate,"none")||!dv(w.scale,"none")||!dv(w.offsetPath,"none")||!dv(w.willChange,"auto")||!dv(w.zoom,"1")||"none"!==w.outlineStyle||w.overflowX!==w.overflowY||"visible"!==w.overflowX&&!("clip"===w.overflowX&&/^(VIDEO|CANVAS)$/.test(a.tagName))&&("hidden"!==w.overflowX||rd(w)||bd(w)))return!1;if(u)return("static"===w.position||"absolute"===w.position)&&"none"===m;if("absolute"!==w.position||!dv(w.perspective,"none")||!dv(w.backfaceVisibility,"visible")||(s?"preserve-3d"!==w.transformStyle&&"flat"!==w.transformStyle:"flat"!==w.transformStyle&&("preserve-3d"!==w.transformStyle||"none"!==m)||"visible"!==w.visibility))return!1;if("none"===m)return!0;M=new DOMMatrix(m);return M.is2D&&!M.b&&!M.c&&M.a>0&&M.d>0&&Math.abs(M.a/M.d-1)<=.001},vp=function(a){var h=document.documentElement;return a===h||a===document.body&&"visible"===cs(h).overflowX},pc=function(n){if(!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return!0;var w=cs(n),b=getComputedStyle(n,"::before").content,f=getComputedStyle(n,"::after").content;return"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&/^(normal|none)$/.test(w.content||"normal")&&/^(normal|none)$/.test(b||"none")&&/^(normal|none)$/.test(f||"none")&&"list-item"!==w.display&&!Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})&&(!/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED)$/i.test(n.tagName)||"visible"!==w.overflowX||/^(fill|contain|scale-down)$/.test(w.objectFit))},L=UC.__obedLut||(UC.__obedLut=function(){for(var T=new Uint8ClampedArray(256),i=0,l;i<256;i++)l=Math.pow(i/255,1.961),T[i]=255*(l<=.0031308?12.92*l:1.055*Math.pow(l,1/2.4)-.055);return T}());if(!(R.width>0&&R.height>0)||!Array.prototype.every.call(N,pc))return;var ad=[];Array.prototype.slice.call(document.querySelectorAll("video")).reverse().forEach(function(v){try{if(!G.contains(v)||v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;var z=cs(v),fit=z.objectFit,K;if(!bm(z)||"50% 50%"!==z.objectPosition||"fill"!==fit&&"contain"!==fit)return;try{var vf=new VideoFrame(v),cc=vf.colorSpace;K=[cc.primaries,cc.transfer,cc.matrix,cc.fullRange].join("/");vf.close()}catch(E){return}if(Q.indexOf(K)<0)return;var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom],a,q,w,b;for(a=v,q=1;a;a=a.parentElement){if(!al(a))return;w=cs(a);q*=+w.opacity;if(a!==v&&"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)){b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}}if(q<.999)return;var vw=v.videoWidth,vh=v.videoHeight,f="fill"===fit?0:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,ch2=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch2)/2,sx=vw/cw,sy=vh/ch2;if(Math.abs(sx/sy-1)>.001)return;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch2)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;for(var I=Array.prototype.indexOf.call(N,v),i=0,n,o,P,T;i<N.length;i++){n=N[i];if(i===I||n.contains(v))continue;o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||o.top>=c[3]||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;for(P=n.parentElement;!P.contains(v);P=P.parentElement);if(P===G||!G.contains(P))return;for(T=n,a=1;T!==P;T=T.parentElement){w=cs(T);if(!al(T)||i>I&&T!==n&&"visible"!==w.overflowX)return;a*=+w.opacity;if(T!==n&&+w.opacity<1&&Array.prototype.some.call(T.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))a=0}if(i<I)continue;if("VIDEO"===n.tagName){if(ad.indexOf(n)<0)return;continue}w=cs(n);if("CANVAS"!==n.tagName||!bm(w)||"fill"!==w.objectFit||!a)return;Y.push([n,o,a])}var x=document.createElement("canvas");x.width=vw,x.height=vh;var g=x.getContext("2d");g.drawImage(v,0,0);var X0=Math.floor((c[0]-cx)*sx),Y0=Math.floor((c[1]-cy)*sy),D=g.getImageData(X0,Y0,Math.max(1,Math.min(vw,Math.ceil((c[2]-cx)*sx))-X0),Math.max(1,Math.min(vh,Math.ceil((c[3]-cy)*sy))-Y0)),d=D.data,j;for(j=0;j<d.length;j+=4){if(d[j+3]<255)return;d[j]=L[d[j]],d[j+1]=L[d[j+1]],d[j+2]=L[d[j+2]]}g.putImageData(D,X0,Y0);Y.forEach(function(y){g.globalAlpha=y[2],g.drawImage(y[0],(y[1].left-cx)*sx,(y[1].top-cy)*sy,y[1].width*sx,y[1].height*sy)}),g.globalAlpha=1;var h=document.createElement("div"),s=h.style,t=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=(c[0]-R.left)*kx+"px",s.top=(c[1]-R.top)*ky+"px",s.width=(c[2]-c[0])*kx+"px",s.height=(c[3]-c[1])*ky+"px",t.left=(cx-c[0])*kx+"px",t.top=(cy-c[1])*ky+"px",t.width=cw*kx+"px",t.height=ch2*ky+"px",h.appendChild(x),H.push(h),ad.push(v)}catch(E){}}),H.length&&(U.__obedFrozen={scene:A,holders:H.reverse()})}catch(E){U.__obedFrozen=null}finally{window.__obedTakeMs=U.__obedTakeMs=performance.now()-t0}}
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

**Paint gate (once per take, before any rectangle test).** Every rendered element of the document (`checkVisibility` with
opacity and visibility) and its `::before`/`::after` must paint only inside its border box and replace nothing: `box-shadow`,
`filter`, `backdrop-filter`, `border-image-source`, `-webkit-box-reflect` none; `outline-style: none`; `content` `normal`/`none`
(element and both pseudo-elements); no `display: list-item` (marker); no direct text (glyph ink, `text-shadow`, decorations);
a replaced element (`canvas`, `video`, `img`, `svg`, `iframe`, `object`, `embed`) clips its content or uses `object-fit`
`fill`/`contain`/`scale-down`. Any failure skips the whole take (today's look). With paint confined to border boxes, the
rectangle prefilter below is sound.

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
| the movie itself | | plain bitmap (below); `readyState ≥ 2`, decoded size, `checkVisibility({opacityProperty, visibilityProperty})`; chain opacity product ≥ 0.999; `object-fit: contain`, or `fill` with `sx = sy` (0.1 %); `object-position: 50% 50%`; `VideoFrame` colour tuple (primaries/transfer/matrix/fullRange) ∈ `Q`; alpha 255 at every source pixel of the attached region |
| a later painted element | | an admitted `<video>` (its holder is appended after), or a plain-bitmap `<canvas>` with `object-fit: fill`, `overflow: visible` above the leaf and no translucent ancestor painting anything else, redrawn at its rect × (`sx`, `sy`) and effective opacity |
| plain bitmap | | no background colour or image, box-shadow, border, outline or `backdrop-filter`; zero radii and padding; `object-view-box: none`; `image-rendering: auto` |

Why this proves the picture: the gate confines all paint to border boxes; admitted chains and branches are block, absolute,
`z-index: auto` and 2D (coplanar) in one scene subtree, so paint order is document order (CSS 2 App. E); the only clips are
the intersected rectangles; nothing crops, filters, blends or contains paint; ancestor backgrounds paint beneath.

- **Tone match (Q5):** after the opacity check the region's RGB goes through `L` and is written back (`putImageData`); the
  foreground redraw follows, so it is not toned. `L` is identity at 0 and 255 (and everywhere under the fallback).
- **Geometry:** element box → content box (`object-fit`, centred) → ∩ rectangular clips → slide px through the live slide's
  base-layer rect (separate x/y scales); a `div` (overflow hidden) at that rect holds a natural-size canvas at the content box,
  appended in the outgoing wrapper in document order. Identical holders on 1920×1080, 2560×1440 and letterboxed stages (§8).
- **Snapshot, not move; failure model:** a move is a detach the core observes (`stash` re-plays and remounts it); `drawImage`
  is the exact last presented frame (rVFC). Add-only, per movie, after the cross-fade rules are committed; the `<video>` is
  only read (no write; no call besides `checkVisibility`/`getBoundingClientRect`), so the core sees the detach as today.
- **Cost:** `window.__obedTakeMs` (also on the controller, which page scripts cannot reach) = the take's total wall time
  (gate, every candidate incl. rejected ones, copies, readbacks, LUT, redraws), written in a `finally` on every path. Retained: one natural-size canvas per frozen movie
  (1920×540 ≈ 4 MB), freed with the transition DOM; transient: one region `ImageData` per movie and a closed `VideoFrame`.
- **Cleanup is the player's:** holders live in the transition DOM (removed at the next scene, go-to/back, replay, queued skip;
  kept invisibly at the end-of-show endpoint); an unattached take is dropped at D3 or by the next take (lifecycle rows, §9.1).
- **Residuals (today's baked-frame jump):** gate or allowlist misses; G2-drawn movies; undecodable codecs; tuples outside `Q`;
  hyperlink transitions (skip D4; never used live); self-playing mode (host-refused); the bridge/hold until the Q6 follow-up.

## 4. Switch, pins, report

- **Switch (decided):** D1–D4 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`, `patch_rendering` and every synthetic test
  player pick them up; `mm_opacity=False` stays the hook-only bytes (`7cf00b56…` / `4f9fbffd…`); docstrings say "rendering
  fidelity"; README: `OBED_LIVE_MM_OPACITY=off` also restores the export's dissolve, cut and movie behaviour. **Pins:**
  `(on, off, rendering)` kept; `on`, `rendering` re-pinned. **Report** `output.mmOpacity = {mode, sha256}`; `RUNTIME_VERSION`
  stays 2; preview inherits the patch; paint oracle stays stock; `web/live.py` unchanged.

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
2353760 (50)** · hook 2368820 / 2368858 (50). Measured (`overlap_dpatch11.py`, both players): 13 intervals disjoint; no
replacement contains any anchor, its own included; all 6 orders of R1–R5, R6–R8, D1–D4 give identical bytes; every anchor 0
times after, every replacement once.

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

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`)

Builders `dpatch3.py` → `dpatch11.py` (rev 8); drivers `proto3.py` → `proto6.py`, `probe7.py` + `diag7{,b}.js` (one
headless Chrome per arm; `p2cut` = P2 2→3 in Keynote's cut shape, in memory); analysis `analyze_full.py`, `f3analyze.py`,
`f1analyze.py`, `f3model2.py`, `curve.py`, `matched.py`; Node `overlap_dpatch11.py`, `node_ids.py`, `node_r6_test_r11.py`,
`node_r11_near.py`, `node_f3_r11_test.py`, `node_f3_r11_decks.py`; `bake/bake.py`.

**Real P2 DOM, first evidence (Q0b 2; exploratory, untimed, 1-min load 6.2–7.0; `runs11/{exact,dbg}/probe7.json`).** Raw
player, `p2-binary`, headless Chrome 154. Rev-7 bytes skipped the slide-2 movie (`<video>` UA `overflow: clip`; the seven
`preserve-3d` build wrappers; `body`'s propagated `overflow: hidden` clipped to its zero-height box). A debug build allowing
the three admitted both movies: 2→3 redraws `3231B69B` (build frame, α 1) and `3F22E494` (α 0.2947), take 22 ms; 4→end
redraws `2A293753`, `219585B0`, 20 ms. Rev 8's rules replayed on the recorded computed values admit both. Untagged H.264
decodes as `bt709/bt709/bt709/false`. Counter: live 42, 44 (`t23-live-0{0,1}.png`), then 48 in every fade frame
(`t23-fade-00…06.png`, `t23-sheet.png`), square intact. No rVFC hook ran, so 48 = last presented frame is **not** shown (only
consistent with ≈ 4 frames of play after the 44 shot); Q0b 6 binds it. Not covered: the paint gate, DSK, CEF.

**Node, real extracted code, both players (rev 8).** Ids pre-order on the real `VB` classes. All 133 transitions: 46
Dissolves copied (two rules on exactly the ids `VB` then allocates), 8 cuts (no rule), 79 stock, 0 mutations; 21 + 10
near-misses stay stock; five construction failures build the stock tree. **F3 stub table, 123 rows** (UA-correct, zero-height
`body`), video proxy untouched: one out-of-profile row per property of the movie chain (30), the movie (12), a redrawn canvas
or its branch (13) and the gate (12, plus confined and hidden-shadow positives), each skipping; geometry (scales, 2560×1440,
letterbox, clip panel, `fill` equal / unequal, `#stage` 0.05 % / 1 %), attach (cut, missing wrapper, throwing append), order
(earlier behind; earlier static, flex `order`, z-index, outside-scene skip; later movie admitted / not), redraw at α 1 /
0.2947 / 0.5, opacity (sparse, edge, row 400), tuples (BT.709 limited taken; others and missing `VideoFrame` skip), `L(128) =
139`, take time 37 under a controlled clock on every path; root/body propagation and build-wrapper rows admit.
**Deck stub DOMs** (`node_f3_r11_decks.py`; §1.1's live slide as measured, in document order):

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
| Foreground preserved (tone-invariant) | `m-fg` | `m-fg-omit`; scorer cases: shifted, double-painted |
| Tone match — only when Q0b recorded a non-identity `L` | `m-tone` | `m-tone-raw` (identity `L`) |
| No independent overlay | `m-on` | `m-bridge-off` (stock twin) |
| Cost | scorer case: 50 ms; stub rows: total published on success, rejection, exception | scorer case: 50 ms + ε (missing or non-finite → INCONCLUSIVE) |

### 9.0 Q0b — step 0 (scratch, before W1; needs the browser: waits for "free now")

Done (§8): cross-fade, KB, opaque controls, matched progress, cut, rev-4 freeze. Pending (DX-1 criteria; a miss re-plans):
1. **Tone characterisation → decision record** (`Q`, `L`; §12.5): the paused tone movie (§9.1), live vs snapshot in headless
   GPU, `--disable-gpu` and two CEF launches; untagged H.264, BT.709 H.264, HEVC Main 10 BT.709; every decoded tuple recorded.
   **Measured LUT:** ramp and patch interiors (2 px eroded); per channel and observed snapshot value s, the median live value;
   one shared table if channels agree within 1 at every s (else 3-D → fallback); unobserved s interpolated linearly; `L[0] =
   0`, `L[255] = 255`; observed set recorded; analytic curve if within 1 everywhere observed. **HEVC:** undecodable on a path →
   "N/A — never plays live there" with decode evidence; decoded but uncaptured → INCONCLUSIVE; never satisfies (iii) silently.
2. **Engagement on the real DOM** (debug build logging the gate's first failing element and each video's first failed
   property): P2 2→3 and 4→end (first evidence, §8) and DSK 3, 5, 7 admitted as the stubs predict, the gate passing; any
   other verdict → re-plan. Root and body rectangles and overflow recorded.
3. **Foreground and reference:** `m-fg` / `m-fg-omit` outcomes; texture + holder vs the first transition frame, full
   resolution, every pixel incl. geometry and redraw-edge maxima ≤ τ.
4. **Cost:** `window.__obedTakeMs` per take (and per-movie times in the debug build); total > 50 ms stops for re-planning.
5. **Host-path geometry** (letterboxed, 2560×1440, DSF 2) holder residual ≤ τ; **stock P2 4→end** confirms §1.4's bridge.
6. Cut ×3, freeze ×3 incl. `m-paused`, `m-hold`, `m-off`; `screen-on`/`-off`; D2 `on`; CvC; `--disable-gpu` and DSK on
   current bytes; `delay-on`/`-off`; lifecycle dry run.

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver (W2; reused by W3; read-only).** Stock `index.html`, player, slide JSON from `html-unmodified`; PDFs from a fresh
  scratch strip (715cb3f1's stripper); movies mapped to decodable copies (P2: `html-player` H.264; DX-M: the binary counter
  re-encoded BT.709-tagged into scratch unless Q0b qualifies the untagged tuple; tone arms: the **tone movie**, same encoder:
  counter strip, 220-step luma ramp, 25–100 % colour patches, skin tones, in Q0b 1's encodings). Provenance recorded.
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1, own port (never 9222); `LiveOutputHost` attach or launch.
- **Instrument.** Innermost hook from the first rAF with the transition DOM: each leaf's effective opacity (also before any
  animation attaches), every transition animation (`currentTime`, `startTime`, value), scene/hash; every `<video>` tagged
  (`WeakMap` id) with rect, effective opacity, transition-DOM membership, colour tuple, rVFC records and detach time;
  `window.__obedTakeMs`; at that first rAF the textures, every holder (`toDataURL`, slide-px geometry) and the blend/isolation
  chain. Alpha PNG screenshots from 0.35 s before the advance to T + 0.6 s; cut arms add a per-frame screencast.
- **Scorer (pure, every pixel of the mask; reused by DX-2).** A = outgoing texture with the holders composited, B = incoming,
  premultiplied; per admitted screenshot e by least squares on the texture group outside every media rect + 2 px; residual
  `|F − ((1−e)·A + e·B)|` there. Screen arms: RGB vs the cross-fade over black. **Media (DX-M):** each holder binds to the one
  tagged decoder whose admitted region maps to its rect (± 1 px; none or several → INCONCLUSIVE); its reference is that
  decoder's last rVFC record before its detach. The strip is decoded from the holder and from `Ô = (F − e·B)/(1 − e)` on
  admitted frames with e ≤ 0.8, ≥ 3 of them with pairwise Δe ≥ 0.1; never from raw screenshots. **Independent references
  (paused arms):** the last pre-advance live screenshot `S_live` (compositor-painted before D4 runs) is ground truth for the
  movie region; the holder and every `Ô` are compared with it, never with texture + holder.
- **Capture integrity (any violation INCONCLUSIVE):** texture ids, hash before/after, screenshot size, page mode and served
  digest as stated; finite, non-empty measurements; fade arms ≥ 6 mid frames (0.05 < e < 0.95, transition DOM present); delay
  arms ≥ 2 screenshots and rAF coverage in the window; cut arms rAF coverage from DOM insertion to 3 frames after the cut and a
  screencast frame inside; paused arms two identical `S_live`; media arms the evidence below; lifecycle rows a settled frame.

| Check | Threshold (measured) |
|---|---|
| Model | every mid frame max residual ≤ τ = 4 LSB (1.3–1.5 GPU, 2.7 software; KB 64, stock 205–206) |
| Complement | every admitted frame: \|α_in-only + α_out-only − 255\| ≤ 2 (0; stock 254) |
| No dip | overlap α ≥ 252 (255 / 254; KB 191) |
| No flash | effective incoming opacity 0 in every rAF before the first animation frame |
| Curve | two animations, one `startTime`; \|in + out − 1\| ≤ 1e-5; \|in − ease-in-out(ct/T)\| ≤ 1e-4 |
| Monotone | e non-decreasing (−0.01 slack), ≥ 0.99 before the hand-off |
| Hand-off | H = max premultiplied \|first-live − last-transition\| outside the destination's movie rects on the identified frames (either missing → INCONCLUSIVE); H ≤ τ |
| Cut swap | every rAF from DOM insertion: incoming 0 before the cut's first animation frame, then in + out = 1 ± 1e-3 until incoming 1; every screencast frame \|α_in-only + α_out-only − 255\| ≤ 2 (stock: 510) |
| Frozen frame | per bound holder: decoded index = its reference frame (offset 0, §8), and `Ô` decodes to it on every admitted frame |
| Frozen region | `Ô` in the movie region constant over the admitted frames (spread ≤ τ/(1 − e)) |
| Foreground preserved | holder and every `Ô` vs `S_live` on the counter-block pixels under the foreground (0/255 on every tone path) ≤ τ |
| Tone match | non-identity `L`: holder vs `S_live` over ramp and patches (foreground rects + 2 px excluded) ≤ 2/255 per channel, `S_live` CvC ≤ 1 — blocking; identity `L`: the same residual reported, non-blocking |
| No independent overlay | in every rAF of the fade no tagged `<video>` outside the transition DOM with effective opacity > 0 meets the outgoing movie rect, and `Ô` there does not drift |
| Cost | `window.__obedTakeMs` finite and ≤ 50 ms per take |

**Per-arm contract** (required classes ≥ 2 000 px; deviation INCONCLUSIVE):

| Arm | Deck / bytes | Required classes | Checks → expected | Styles | Served digest |
|---|---|---|---|---|---|
| `on` | P2 2→3, DSK 5→6 (alpha) | out-only, in-only, overlap | all → PASS | leaves `plus-lighter`, container `isolate` | pinned `on` |
| `on` D2 | D2 2→3 | overlap | model, no dip, curve, monotone, hand-off → PASS; complement N/A | as `on` | pinned `on` |
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
| `m-fg` / `m-fg-omit` | `m-paused` + in-memory: an opaque texture layer and P2's square moved over the counter blocks / plus one counted splice `Y.forEach(` → `[].forEach(` | out-only | foreground preserved → PASS / FAIL (model N/A: live-only edit) | as `on` + one holder | pinned `on` / + splice |
| `m-tone` / `m-tone-raw` | tone movie on P2 slide 2, paused / plus one counted splice making `L` identity | out-only | non-identity `L`: tone match → PASS / FAIL (mid-grey −11); identity `L`: `m-tone` reported only, `m-tone-raw` not run | as `on` + one holder | pinned `on` / + splice |
| `m-bridge-off` / `m-bridge` | P2 `html-player` (measured plan), slide 4 → end, continuity on | out-only | no independent overlay → FAIL / reported, expected FAIL (known residual until the Q6 follow-up makes it blocking) | none / as `on` | `off` / `on` |
| `on-sw` | P2, `--disable-gpu` | as `on` | all → PASS (tone match report-only) | as `on` | `on` |

**Media evidence** (missing → INCONCLUSIVE, never a negative-control FAIL). `m-on`, `m-paused`, `m-hold`, `m-fg`, `m-tone`: one
bound D4 holder, a reference rVFC record, the colour tuple, ≥ 3 demixable frames. `m-off`: served `off`; live playback first
(≥ 10 presented frames); transition and outgoing texture captured; movie-region pixels on ≥ 3 demixable frames; **no holder by
design** (a holder → INCONCLUSIVE); FAIL: `Ô` misses the reference index. `m-bridge(-off)`: bridged decoder tagged, rVFC, rAF.

**Lifecycle scenario** (one parametrized driver function on `p2-binary` with the patch; each row also passes complement and no
flash on its visible frames; "cleanup" = no transition `layer<id>` node, holder or rule after the next scene):

| Row | Action | Expected |
|---|---|---|
| advance | plain 2→3 | settled frame = stock twin's (outside movie rects); one holder during the fade; cleanup |
| replay | go-to 2, advance again | as advance; fresh holder and rules on fresh ids |
| queued advance | Space mid-dissolve | player's own queue as stock twin; cleanup |
| queued skip | `advanceAndSkipBuild` mid-dissolve (def @2350987 / @2351025) | as stock twin; cleanup |
| go-to / back | go-to 1 or back mid-dissolve | transition DOM, holder and rules gone; destination as stock twin |
| hide / show | hide mid-dissolve, show 0.5 s later | while hidden: output fully transparent (alpha) / black (screen), checked separately; after show the model holds |
| automatic | in-memory override: `automaticPlay: true`, `beginTime` 0.5 s | incoming 0 and the frozen frame through the real delay branch; then as advance |
| loop wrap | in-memory `loopSlideshow: 1`, P2 slide 4's dissolve | as advance onto slide 1 |
| end of show | P2 slide 4's dissolve, loop 0 | held endpoint = stock twin's (DOM, holder, rules legitimately remain); then go-to 1 → cleanup; a bridged decoder is judged by `m-bridge` only |

### 9.2 DX-2 inside OBS CEF — `managed_obs_qualify.py --arm dissolve` (unrecorded)

One launch, the managed bridge with DX-1's hook, resolver, integrity rules and scorer (W2), the advance, a `GetSourceScreenshot`
burst. Sessions: DX-1's P2, `p2cut`, `p2-binary` and tone arms except `screen-*`, `delay-*`, `on-sw` and the lifecycle (tone
arms as the decision record allows); media sessions (not `m-off` or the bridge arms) show a bound D4 holder; all record
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
  movie stops on its current frame and fades out with slide 2, foreground intact; no jump at the hand-off; at the freeze no
  step the owner notices (non-identity `L`) or the documented known limit shown, not a failure (identity fallback).
  **Null** (affected transitions only): `OBED_LIVE_MM_OPACITY=off` shows the pop-in and the jump.
- **Report** candidate and null separately with the served mode, `output.mmOpacity.sha256` and the decision record.

### 9.4 Regression

`run_gates.sh` full tier from a fresh pinned worktree; `mm_opacity_probe.py`, `mm_handback_probe.py`; managed OBS (owner
session) `--arm mmo`, `--arm g2`, `--arm mmo-cef`. Root-cause any change.

## 10. Tests (three new test functions, as rev 3; everything else extends them)

1. **Free:** tuple-parametrized anchor/replacement refusal (both patchers); off identity; `patch_rendering` = `patch_player`
   minus the hook; "every original anchor gone" (`test_live_runtime.py:205`, `:265`, `:367`); new-player equivalence;
   `node --check`; pin mismatch. Synthetic builders derive from the tuple.
2. **Edits** (`test_live_runtime.py`): re-pin; hand-back tests use `HANDBACK = slice(5, 8)`; the composition test runs R1–R5,
   R6–R8, D1–D4 in every order and checks containment including self.
3. **New, REAL-gated, parametrized over both players and one case table** (Node, real extracted code): D1–D4 offsets; ids;
   every committed `tests/fixtures/live_continuity` transition (§8); the 21 + 10 near-misses; the five construction failures;
   the 123 F3 stub rows of §8, profile and gate rows generated from one property → out-of-profile-value table (take/attach count and
   target, geometry, redraws and alpha, `L` output, published `__obedTakeMs`, no write or call on the video).
4. **New `tests/test_dissolve_probe.py`, one parametrized function** (synthetic numpy): cross-fade, pop-in, dip, ±1 LSB, masked
   video, curve, monotone, hand-off and integrity rows, plus: cut union (1, 1) FAIL, complementary (0.5, 0.5) and clean swap
   PASS; strip decode (valid / parity error); strip under incoming content (`Ô` PASS, raw flips); two decoders (match /
   ambiguous → INCONCLUSIVE); index ≠ reference FAIL; `Ô` drifting FAIL; < 3 demixable frames → INCONCLUSIVE; `m-off` complete →
   FAIL, without playback or with a holder → INCONCLUSIVE; foreground correct PASS, omitted / shifted 2 px / double-painted
   FAIL; tone within 2 PASS, untoned (−11) FAIL, identity decision → reported only; cost 50 ms PASS, 50 ms + ε FAIL, missing /
   NaN → INCONCLUSIVE; independent overlay present FAIL / absent PASS; LUT construction (median, interpolation, endpoints).
5. **`test_managed_obs_qualify.py`:** the env-refusal test parametrized over the new arm; the calibration test (n = 4 / 4 + ε).

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | D1–D4 with `Q` and `L` from Q0b's decision record; docstrings; re-pins; tests 1–3 |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | resolver incl. the tagged counter and tone movies, the LUT construction, DX-1 incl. cut, DX-M (fg, tone, bridge arms) and lifecycle; test 4 |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | `--arm dissolve` with every §9.2 session on W2's resolver/driver/scorer; test 5 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, plan status | README fallback line; one SKILL sentence; handover recording the Q6 follow-up PR (after S2 merges: stop main's bridge and S2's hold at the outgoing transition start; make `m-bridge` blocking) and the optional G2 use of `L` |

Order: W0 → Q0b → W1 ∥ W2 → W3 → gates → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-2,
`mmo-cef`, DX-3 (owner session) → one PR to `main`. Never merge.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and construction failure; export JSON never mutated. (3) Rule ids = allocated ids. (4) One `applyCssAnimation` pass; cut only
at the exported timing. (5) D4/D3 add-only, never touch a `<video>`; only gate + allowlist passes are admitted; attach by kind.
(6) `off` = today's bytes. (7) Thresholds measured or by formula; PASS and FAIL controls for every blocking check.

## 12. Owner decisions (all 2026-10-11, in chat)

- **Target (movies):** "in Keynote the vid stops playing and dissolves out" — freeze on the current frame, fade with slide 2.
1. **Switch: fold into `mm_opacity`.** 2. **Scope: every output.** 3. **F1 (`none` cut) in this patch; F2 a separate
   follow-up** with an owner Q-deck (final). 4. **F3 in this patch** (re-confirmed after rev 4: splitting it out declined).
5. **Mid-tone step at the freeze: remove it, player-only** (owner: "is it observable? If the cost is a re-plan let's do it").
   *Observable?* Estimated yes for an attentive viewer: mid-grey 139 → 128 is ≈ 16 % less luminance (ΔL* ≈ 4.3) in one frame
   at near-full outgoing opacity; darks and lights move less; DX-3's eye check confirms. *Design:* the fixed per-channel `L`
   (§1.4, §3.2); moving or pausing the live `<video>` stays out (core changes, deferred by Q6). *Decision record (Q0b 1, DX-2):*
   `Q` = the decoded tuples measured; `L` non-identity when (i) colour patches land within 2/255 after the per-channel map,
   (ii) two CEF launches agree within 1 (headless GPU off by > 1 → DX-1 tone row report-only), (iii) every decodable encoding
   of a tuple in `Q` fits it within 2/255; analytic gamma 1.961 if within 1 of the table, else the table (+≈ 1 KB).
   **Fallback:** `L` = identity, a documented known limit (tone non-blocking; §9.3); moving the `<video>` reconsidered after S2.
6. **Main's bridged movie over P2 slide 4's terminal fade: follow-up after S2.** Player-only on `main`; `m-bridge` reports the
   residual. Stopping a bridged or held decoder's paint at the outgoing transition start (main's `keepAtSlot`, S2's hold) is
   a separate PR after S2 merges, not pushed into S2's in-flight branch; it makes `m-bridge` blocking.
7. **Foreground over a frozen movie: redraw overlying texture canvases** into the snapshot, under the §3.2 allowlist.

## 13. Risks and out of scope

CEF compositor, tone path and `L` unproven until Q0b/DX-2 (fallback §12.5). Id prediction relies on `VB`'s pre-order
allocation (proved; re-checked every run). The allowlist matches one real P2 DOM; gate and DSK unconfirmed: a value outside
either leaves F3 inert (Q0b 2 names it); take cost; software compositing; production transparency; the bridge/hold (Q6). Out of scope: F2, GL effects, Keynote-app comparison (hands off Keynote), S2 and its PR.

## 14. Critique log

Raw rounds: `.agents/reviews/dissolve-crossfade/plan-astra-r{1,…,6}.md`. r1–r5 (12, 7, 11, 7, 6): all folded, rows in `4ffcd8ad`
/ `e5c644bb` / `218308c3` / `cacfe9fb` §14; r6 closed r5-2…6, completes r5-1 with r6 #3, #4. Owner answers in §12.

### r6 — GPT-6 Astra high (Codex), on rev 7 `cacfe9fb`, and the real-DOM probe

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / new | Folded (the probe found it too): `overflow: clip` admitted on `<video>`/`<canvas>` leaves (UA default; content-box clip, no border or padding), including redrawn canvases; ancestor clip rules unchanged; stubs UA-correct; real-DOM admission required before W1 (Q0b 2). | §1.1, §3.2, §8, §9.0 |
| 2 | major / new | Folded (the probe found it too): the root, or `body` when the root is `visible`, clips to the viewport; a static, non-propagating ancestor clips nothing absolute; zero-height propagating `body` rows; stubs corrected; root/body recorded in Q0b. | §1.1, §3.2, §8, §9.0 |
| 3 | major / edge | Folded by the paint gate: `border-image-source`, replacement `content`, `::before`/`::after` content, markers and direct text skip the take; one row each. | §3.2, §8, §10 |
| 4 | major / edge | Folded by the paint gate, run before any rectangle test: shadows, filters, outlines, reflections and replaced-content overflow skip the take, so the rectangle prefilter is sound; outside-box shadow row skips, confined non-intersecting row admits. | §3.2, §8, §10 |
| probe | evidence | Rev-7 bytes skipped the real movie (UA `overflow: clip`; seven `preserve-3d` build wrappers; body clip); a debug build admitted 2→3 and 4→end (22 / 20 ms), redrew the square, held 48; rev 8 allows the wrappers (`preserve-3d` with no transform). Index = last presented not shown (no rVFC hook). | §1.1, §3.2, §8 |
