# Dissolve and cut over fill-less slides: a true cross-fade, a clean cut, and movies that freeze and fade

**DRAFT rev 4**, 2026-10-11. Rev 1: Opus planner (`8e572864`). Critique r1, r2: GPT-6 Astra high via Codex (not Opus; owner
2026-10-11), 12 + 7 findings, all folded (§14). Rev 2 (`cd289a05`), rev 3 (`f3bd8b55`), rev 4: Opus planner. Rev 4 records the
owner's decisions 1–4 (§12): fold into `mm_opacity`, every output, the `none` cut (F1) and the movie freeze (F3) **in this
patch**. Plan only: no product code, no commits, no OBS, no Keynote. Base: `main` @ `1589d096`.
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; only R8 and the hook `_ANCHOR` move). Evidence: main checkout
`output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored). Planning scratch (scripts, Node checks and result JSON;
frames, patched players and strip copies not kept): its `plan-2026-10-11/{planner,rootcause,coord}/`; "scratch `x`" below
means `plan-2026-10-11/planner/x`. Raw critique rounds: `.agents/reviews/dissolve-crossfade/`.
Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins), `keynote_live_handback_geometry.plan.md` (R6–R8),
`keynote_live_paint_oracle.plan.md` (oracle stays stock).

## 0. Summary

- **Root cause (player, not host).** Keynote exports a slide transition as two flattened full-slide textures: the incoming
  slide at the bottom with **no animation**, the outgoing slide on top animated away (Dissolve: `opacity 1→0`, EaseInEaseOut;
  `none` cut: `hidden` false→true over 1 ms). Keynote's own exports hide the incoming under a full-slide black fill. Without
  that fill (the real DSK case, §1.3) the incoming shows at full strength while the outgoing is still on screen: the Dissolve
  pops in; the cut shows both slides at once (§1.5).
- **Cross-fade and cut (D1, D2: commit before construct).** For a transition whose tree is exactly the Dissolve or cut shape,
  before the player builds anything, one method commits what is needed and returns a **copy** of the tree: for a Dissolve two
  verified stylesheet rules (`#layer<c>{isolation:isolate}`, `#layer<in>,#layer<out>{mix-blend-mode:plus-lighter}`, keyed by
  the ids the player is about to allocate) and an incoming leaf that starts at opacity 0 with the mirror animation `0→1`; for a
  cut, an incoming leaf that starts hidden with the mirror `hidden` true→false. Any failure happens before anything is built
  and yields the stock transition. Result: premultiplied `(1−e)·P_out + e·P_in`; a cut that never shows both slides.
- **Movie freeze (D4 takes, D3 attaches; add-only).** Owner, 2026-10-11: "in Keynote the vid stops playing and dissolves out".
  The player deletes the playing `<video>` when it displays the transition scene (`jumpToScene_partFour` → `displayScene`), in
  the same task as the transition start, so the movie jumps back to the **opening frame** the export baked into the outgoing
  texture (§1.4). D4, just before that teardown, snapshots every fully visible, opaque, decodable `<video>` on screen into a
  detached canvas; D3 places it inside the outgoing layer's fading wrapper at its on-screen geometry. The `<video>` is never
  moved, paused or marked, so no decoder changes hands. Any failure leaves that movie as today (baked frame).
- **Measured** (headless Chrome 154, transparent page, stripped PDFs, full-resolution scoring, §8): cross-fade residual
  ≤ 1.3 LSB (P2) / 1.5 (DSK deck, 17c0c938); nulls pop in (205–206); KB without the blend dips to α 191; opaque-texture on/off
  ≤ 1.51 LSB. Cut: stock paints both slides in 2 rAF frames and 1 screencast frame; patched 0 / 0. Freeze (binary counter):
  frozen index = the last presented frame (56 = 56), constant through the fade, whole frame within 1.7 LSB of the cross-fade
  model; the snapshot path drops mid-grey by **11/255** at the freeze (live 139 → frozen 128 at Y = 126; black and white exact),
  the same tone-path gap as G2's accepted known limit (owner question, §12).
- **Switch:** `mm_opacity` (`OBED_LIVE_MM_OPACITY=off` restores today's bytes); every output; `RUNTIME_VERSION` stays 2.

## 1. Facts (code-read on both players; every anchor count-checked)

### 1.1 How the player draws a slide transition

| Step | Where (byte, both players unless split) | What |
|---|---|---|
| GL vs CSS | `jC` @2368216 / @2368254; routing `qC&&-1!==jC.indexOf(C.name)` @2312807 (`PB.renderEffects`, slide transitions) and @2314108 (`PB.renderEffect`, per-object builds) | `apple:dissolve` and `none` are not in `jC`: the CSS renderer `NB` (@2292342) draws them. |
| Build | `PB.renderEffects` @2311803; `const A=new VB(C.baseLayer,…)` @2312557 … `this.cssRenderer.draw(a),a.removeChild(w)}` @2313053 | `yB` keeps the export's `baseLayer` by reference (@2270532). `VB` allocates `layerId=TB,TB+=1` (`let TB=0` @2270526, same module scope as `PB`) pre-order: root, container, incoming, outgoing = TB … TB+3 (proved on the real classes, §8). `WB` creates keyframe rules in the animation manager's stylesheet during construction. `NB.draw` builds `layer<id>` divs (a `layer<id>-opacity` wrapper per animated opacity; a `hidden` animation runs on the layer itself). The DOM it replaces (`w`, the transition scene as `displayScene` just drew it, with no live `<video>`: §1.4) is removed in the same task. |
| Keyframes | `WB` @2271556; `EaseInEaseOut` → `ease-in-out` @2282229; `hidden` → opacity 1/0 keyframes; `createAnimation` @1953007 | rules live in the animation manager's own `<style media="screen">` |
| Animate | `PB.playCurrentScene` @2356281 / @2356319: `renderEffects()` then `setTimeout(()=>{…animateEffects…},1e3*g)` (`},1e3*g)` @2357455 / @2357493) | Render and animate are separate tasks; `applyCssAnimation` @2303763 starts every layer's animation in one loop, at keyframe 0% on its first frame. |
| Cleanup | `displayScene` @2354643 / @2354681 → `deleteAllAnimations()` @1953106 + `removeEvent` @2291872 | at the next scene or any go-to; at the end of the show (`currentSceneDidComplete` @2357464 / @2357502) the held endpoint keeps its DOM and rules until navigation. |

### 1.2 The export data (every transition on disk)

Census over the 25 export roots under `output/fixtures` (scratch `census.py`): **42 `apple:dissolve`** and **8 `none` cuts**
(D1–D6), all root → one container (no texture, animation or `objectID`) → two textured leaves (no `objectID`, no video flags,
identity geometry); incoming without animation; outgoing with one animation (Dissolve: `opacity` 1→0, `EaseInEaseOut`,
`fillMode both`, 1.5 s or 1.0 s; cut: `hidden` false→true, 0.001 s, `fillMode both`). Also 67 Magic Moves (GL) and 382
per-object CSS builds. P2 2→3 = slide `0C652BEB` event 3. **D2 is the only D deck with a Dissolve** (overlap only, cannot show
a pop-in); `minimal-alpha-dsk-17c0c938` is the pop-in deck on 17c0c938 (5→6 measured). Every on-disk cut is a deck's last
transition and goes to the shared background texture `9B0DBE…`, which is empty once stripped.

### 1.3 What the live presenter serves

`html_preview.export_html` (`export … as HTML`) is the only export path, served unmodified in screen mode (black page,
`#obed-output-black` hide) and keyer mode (alpha page, `#body` opacity hide; `live_host.py:418–436`). The product never strips
(715cb3f1). **The trigger is a fill-less outgoing texture, not the page**: RAWT-1 (Keynote's PDFs, transparent page) does not
pop in; STRIPT-1 and the verifier's NULLSTRIP (stripped PDFs on the opaque black page) do. Fill-less decks (DSK decks use the
wall deck's transparent layout, README :21; DSK clip slides are forced to dissolve, `dsk_assemble.py:2958–2968`, `:4204–4207`)
are the real case; which production exports lack the fill is unverified (DX-3 pre-check).

### 1.4 Movies at a transition start

- **The export bakes the opening frame.** DSK deck 7→8 (ProRes clips; offline Ghostscript render of the outgoing texture vs
  every ffmpeg-decoded frame, scratch `bake/bake.py`): best match frame 7 (0.23 s) and 4 (0.13 s), frame 0 within +1.0/+1.4
  MAD; an advance at 0.5 / 1 / 2 / 5 / 10 s into playback differs from the baked frame by MAD 10–20 / 19–32 / 29–44 / 36–70 /
  41–68 (same-content floor ≈ 21). So the outgoing movie jumps back to its opening frame, then fades. Keynote freezes the
  current frame (owner).
- **When it goes.** On an advance from a scene's final state the player runs `jumpToScene` → (100 ms later)
  `jumpToScene_partFour` @2353722 / @2353760 → `displayScene` (removes the live slide, `<video>` included, and draws the
  transition scene without one) → `playCurrentScene` → `renderEffects`, all in one task. Measured on `p2-binary`: the `<video>`
  is detached at +480 ms after the key, `renderEffects` runs at +479.8 ms, and finds no `<video>` in the document; so the
  freeze must be taken before `displayScene`, not at `renderEffects`.
- **Who owns the playing `<video>`.** Raw player: slide 2's own element inside `w`. Main's continuity core: the same element,
  or a decoder it remounted into the authored layer (inside `w`) or into the stage (outside `w`). The core watches every
  detach: a `MutationObserver` on removed `<video>` nodes (`live_continuity_js.py:1750–1759`) calls `stash` (`:719–807`),
  which pools a planned movie, calls `play()` on it if paused, and schedules `tryRemount` (`:809–842`). In the evidence's LIVE
  runs nothing is visible during the dissolve on main. S2 (`d88584eb`) holds a restarting decoder through the dissolve at
  opacity 1 in the stage (`live_continuity_js.py:758–763`, `:1759–1777`, `:2158–2169`).
- **Codecs.** The DSK clip fixtures are ProRes, which neither headless Chrome nor CEF decodes: such a movie never plays live,
  so it has no jump to fix. H.264 movies (P2, D decks, `p2-binary`) play live and jump.

### 1.5 The `none` cut (F1)

A cut's outgoing `hidden` animation runs 1 ms with `fillMode both`; its first animated frame is keyframe 0% (outgoing visible)
while the incoming, which has no animation, is already visible beneath: on fill-less textures that frame shows both slides,
and so does any frame painted in the render→animate gap. Measured: §8. On disk every cut goes to the empty background, so the
on-disk cuts show nothing extra; a cut between two content slides does.

## 2. Arithmetic (premultiplied RGBA, 0..1; e = eased progress)

- **Stock Dissolve:** `C = (1−e)·P_out + (1 − (1−e)·α_out)·P_in`: exact where `α_out = 1`, `P_in` at once where `α_out = 0`.
- **Plain opposite fades (rejected):** `α = 1 − e + e²` = 0.75 at e = 0.5 where both are opaque.
- **Fix:** in the isolated container group, incoming (opacity e, `plus-lighter` onto zero) = `e·P_in`; outgoing (opacity 1 − e,
  `plus-lighter`) gives `G = (1−e)·P_out + e·P_in`, `α_G = (1−e)·α_out + e·α_in`, never clamped; over black, the two slides
  cross-faded. Preconditions enforced by the predicate (§3.2): two texture leaves, no video/poster layer, identity 2D geometry
  (the grouping properties flatten `transform-style`, CSS Transforms 2 §7.1). Endpoints exact. 8-bit: 1.3–1.5 LSB GPU, 2.7
  software; τ = 4. Opaque textures: algebraically stock; measured on/off ≤ 1.51 LSB (report-only bound 2).
- **Frozen movie:** the snapshot `S` is drawn above the outgoing texture inside the outgoing wrapper, opaque, covering the
  movie's visible region, so the outgoing layer becomes `P_out'` = texture with `S` over the movie region and the group gives
  `(1−e)·P_out' + e·P_in`: the frozen frame fades with slide 2 and blends exactly.
- **Cut:** at its first animated frame the outgoing is visible and the incoming hidden; from the next frame the reverse. No
  frame has two partly visible layers, so a cut needs no blend.
- **Isolation:** the blend's backdrop is the container group only. It never mixes with the page, the host hide, the GL canvas
  or anything the continuity core inserts. It does not make an independently painted overlay (S2's held decoder) fade (§6.2).

## 3. The patch

### 3.1 Exact replacements (R9–R12 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedShape`, `__obedDissolveLayer`, `__obedFreezeTake`, `__obedFreeze` + `renderEffects(A){` |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |
| D3 (R11) | after the CSS draw @2313053 (42 B) | `this.cssRenderer.draw(a),a.removeChild(w)}` | `this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}` |
| D4 (R12) | `jumpToScene_partFour` @2353722 / @2353760 (50 B) | `jumpToScene_partFour(A,B){if(this.displayScene(A),` | `jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),` |

The methods (scratch `dpatch6.py`; `node --check` passes on both patched players; `PB` and the controller share the module
scope that holds `TB` and `UC`):

```
__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||!1!==x.from.scalar||!0!==x.to.scalar:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,x,u]}catch(E){return null}}
__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=!0,Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}:{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
__obedFreezeTake(U,A){U.__obedFrozen=null;try{var e=U.script.events[A],y=e&&e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),k=U.script.slideWidth/R.width,H=[];if(!(R.width>0))return;Array.prototype.forEach.call(document.querySelectorAll("video"),function(v){try{if(v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;for(var e=v,q=1;e&&e!==G.parentElement;e=e.parentElement){var z=getComputedStyle(e),m=z.transform;q*=+z.opacity;if("none"!==m){var M=new DOMMatrix(m);if(!M.is2D||M.b||M.c)return}}if(q<.999)return;var r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom];for(e=v.parentElement;e&&e!==G;e=e.parentElement)if("visible"!==getComputedStyle(e).overflow){var b=e.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}var vw=v.videoWidth,vh=v.videoHeight,fit=getComputedStyle(v).objectFit,f="fill"===fit?null:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,ch=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch)/2;if("fill"!==fit&&"contain"!==fit)return;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;var x=document.createElement("canvas");x.width=vw,x.height=vh,x.getContext("2d").drawImage(v,0,0);var p=document.createElement("canvas");p.width=32,p.height=18;var h=p.getContext("2d");h.drawImage(x,0,0,32,18);for(var d=h.getImageData(0,0,32,18).data,j=3;j<d.length;j+=4)if(d[j]<255)return;var D=document.createElement("div"),s=D.style,t=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=(c[0]-R.left)*k+"px",s.top=(c[1]-R.top)*k+"px",s.width=(c[2]-c[0])*k+"px",s.height=(c[3]-c[1])*k+"px",t.left=(cx-c[0])*k+"px",t.top=(cy-c[1])*k+"px",t.width=cw*k+"px",t.height=ch*k+"px",D.appendChild(x),H.push(D)}catch(E){}}),H.length&&(U.__obedFrozen={scene:A,holders:H})}catch(E){U.__obedFrozen=null}}
__obedFreeze(C,A){var F=UC.__obedFrozen;UC.__obedFrozen=null;if(C.obedDissolve&&F&&F.scene===this.sceneIndex)try{var O=A.layers[0].layers[1],W=document.getElementById("layer"+O.layerId+"-opacity")||document.getElementById("layer"+O.layerId);W&&F.holders.forEach(function(h){W.appendChild(h)})}catch(E){}}
```

### 3.2 How it works

**Construction (D1's `__obedDissolveLayer`, called by D2).**
- **Predicate (faithful or unchanged):** stock unless a `transition` named `apple:dissolve` or `none`; exactly root → one
  container → two textured leaves without sublayers; root and container without texture or animation; container and leaves
  without `objectID`, `isVideoLayer`, `isWebVideoPosterLayer` or 3D `transform`, identity affine, rotation 0, scale 1, opacity
  1, not hidden; leaves with identity `sublayerTransform`; incoming without animation; outgoing with exactly one animation
  without `keyTimes`/`path`/group: Dissolve `opacity` 1→0, cut `hidden` false→true. Timing, curve, `fillMode`, `beginTime`
  and control points are copied, so the mirror runs through the same `WB` code. 50/50 on-disk transitions match.
- **Dissolve: commit before construction.** Two rules for ids TB+1 … TB+3 go into the animation manager's stylesheet and are
  read back through `CSSStyleRule.style` (an unsupported declaration is dropped and reads back empty); only then is the copy
  returned, and `new VB(copy)` allocates exactly those ids. The DOM is styled from its first style pass.
- **Cut:** no rules; the copy starts the incoming `hidden` (so `addNode` writes `visibility:hidden`) with the mirror
  `hidden` true→false; `applyCssAnimation` makes it visible at keyframe 100% in the same pass that hides the outgoing.
- **One failure point, before anything is built:** predicate miss, missing stylesheet, a throwing `insertRule` or a dropped
  declaration return the export's own tree; if a rule was already inserted `TB += 4` abandons those ids. Orphan rules die with
  the next `deleteAllAnimations`. Copies only along root → container → incoming; export JSON never mutated; the flag
  `obedDissolve` lives on the per-play `yB`.

**Freeze: take (D4) before teardown, attach (D3) at the transition start, same task.** `__obedFreezeTake` runs only when
`jumpToScene_partFour` is about to play the scene now (`B`, the advance and automatic paths) and that scene's first effect has
the §1.2 shape (`__obedShape`, pure). It stores detached holders on the controller (`UC.__obedFrozen = {scene, holders}`);
`__obedFreeze` (D3) always clears the slot and appends the holders only if the cross-fade or cut engaged (`obedDissolve`) for
that same scene.
- **Which movies:** every `<video>` in the document with `readyState ≥ 2` and a decoded size, `checkVisibility` true, an
  effective opacity (product of computed `opacity` from the element up to `#stage`, never the element alone) ≥ 0.999, every
  ancestor up to `#stage` with an axis-aligned 2D transform, `object-fit` `contain` or `fill`, and an opaque frame (32×18
  probe). This includes a continuity-remounted decoder anywhere on screen: at this instant everything on screen is slide 2.
- **Geometry:** the element box → its content box (`object-fit`) → intersected with every overflow-clipping ancestor up to
  `#stage` → mapped into slide px through the live slide's base-layer rect (full slide, as the transition leaves). A `div` (overflow hidden) at that clip rect holds a canvas
  of the video's natural size at the content box; it is appended last in the outgoing wrapper `layer<out>-opacity` (a cut has
  no wrapper: the outgoing layer itself), above the texture canvas.
- **What covers the baked frame:** the holder covers exactly the movie's visible content region, the same region Keynote
  baked, with an opaque frame. Letterbox bars lie outside the content box and keep the texture's own pixels (they were
  transparent in the live video too). A movie whose frame has any transparency is skipped (frozen over baked would double the
  image).
- **Snapshot, not move (decided by evidence):** moving the live element is a detach the continuity core observes: `stash`
  calls `play()` on a paused planned movie and schedules `tryRemount` back to the stage (§1.4), un-freezing or stealing it, and
  S2's per-frame stage pins pull it back too; making that safe needs core changes on main and on S2. `drawImage` takes the
  frame and touches nothing. Measured: the snapshot is exactly the last presented frame (rVFC), and its one cost is the tone
  path: Chromium's native video layer lifts mid-grey by 11/255 and `drawImage` does not (live 139 vs frozen 128 at Y = 126;
  0 and 255 identical), so mid-tones step down at the freeze. Owner question 5.
- **Failure model:** add-only and per movie. Any failed check or exception leaves that movie as today (baked frame); an
  exception before the append adds nothing; the cross-fade rules are already committed and untouched. The `<video>` is only
  read (no property write, no method call other than `checkVisibility`/`getBoundingClientRect`; proved on a stub DOM, §8), so
  `displayScene` removes it as today and the core handles the detach exactly as today: no leak, no stolen or restarted decoder,
  no full-strength copy. Never a double image: the holder is opaque and region-exact or absent.
- **Cleanup is the player's:** attached holders live inside the transition DOM, removed by `removeEvent` at the next scene,
  go-to/back mid-transition, replay (fresh snapshot), queued skip; at the end of the show they stay invisibly (outgoing at
  opacity 0) with the held endpoint until navigation; hide/show acts on the whole group. A take that is not attached (cross-fade
  refused, other scene) is dropped at D3 or overwritten by the next take. Memory: one canvas per frozen movie at its natural
  size (1920×540 ≈ 4 MB), freed with the DOM.
- **Residuals (today's look, by design):** a movie drawn by G2 GL replay at the transition start (its `<video>` is not the
  visible element); movies with alpha, rotated, 3D, translucent or `cover`-fitted; codecs the browser cannot decode; transitions
  started by a hyperlink (`jumpToHyperlinkSlide` calls `displayScene` without D4; the live presenter never uses hyperlinks);
  self-playing mode (refused by the host).

### 3.3 Paths

Advance, completion, replay, queued advance/skip, go-to/back, hide/show, automatic delay, loop wrap, end of show: each is a row
of DX-1's lifecycle scenario (§9.1), which checks final pixels, the frozen holder and the removal of the transition DOM and
its rules.

## 4. Switch, pins, report

- **Switch (decided):** D1–D4 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`, `patch_rendering` and every synthetic test
  player pick them up. `mm_opacity=False` stays the hook-only bytes (`7cf00b56…` / `4f9fbffd…`). Docstrings say "rendering
  fidelity"; names and error text unchanged. README: `OBED_LIVE_MM_OPACITY=off` also restores the export's dissolve, cut and
  movie behaviour.
- **Pins:** `(on, off, rendering)` shape kept; `on` and `rendering` re-pinned for both players.
- **Report** `output.mmOpacity = {mode, sha256}` unchanged; `RUNTIME_VERSION` stays 2; preview inherits the patch; paint
  oracle stays stock; `web/live.py` unchanged.

## 5. Scope

**Every output; `apple:dissolve` and `none` of the §1.2 shape (50/50 on disk); movies of the outgoing slide at their start.**

| Effect | On disk | Fill-less textures | Plan |
|---|---|---|---|
| `apple:dissolve` | 42 | pop-in | D1–D2 |
| `none` cut | 8 | both slides for ≥ 1 frame (§1.5, §8) | D1–D2 |
| movies at a Dissolve/cut start | every DSK clip slide; P2, D decks | jump to the baked opening frame | D4 + D3 |
| per-object builds | 382 | ok | none |
| GL effects (`jC`) | 67 | not CSS | R1–R8 |
| other CSS transitions the player special-cases, smart/action builds | 0 | unknown | F2: separate PR, owner Q-deck |

## 6. Interplay

### 6.1 Anchor map (byte offset, length; e9b2fad4 / 17c0c938)

R7 2190367 (36) · R3 2190440 (46) · R4 2192650 (72) · R6 2263321 (52) · R1 2263373 (165) · R2 2264160 (68) ·
**D1 2311794 (26)** · **D2 2312557 (65)** · **D3 2313053 (42)** · R5 2317031 (62) · R8 2347821 / 2347859 (50) · **D4 2353722 /
2353760 (50)** · hook 2368820 / 2368858 (50). Measured (`overlap6.py`, both players): 13 intervals disjoint; no replacement
contains any anchor, its own included; all 6 orders of R1–R5, R6–R8, D1–D4 give identical bytes; every anchor 0 times after,
every replacement once.

### 6.2 Subsystems (files outside `live_runtime.py` that change: `scripts/dissolve_probe.py` (new), `scripts/managed_obs_qualify.py`, their tests, docs)

| Subsystem | Interaction | Change / re-run |
|---|---|---|
| R1–R8 | disjoint bytes; GL renderer | composition test |
| G2 GL replay | WebGL only; D4 freezes only `<video>` elements, so a movie G2 is drawing at a transition start keeps today's look | none; `EXPECTED_STATS` move only with an independent diagnosis |
| Continuity core (main) | D4/D3 touch no `<video>`; `displayScene`'s detach reaches `stash`/`tryRemount` exactly as today; nothing it paints is visible during the dissolve (evidence LIVE/LIVEFIX) | **no change**; DX-M runs through `LiveOutputHost` with continuity and asserts no full-strength movie during the fade |
| **S2** (`d88584eb`) | whatever S2 shows as slide 2's movie before the advance is a visible `<video>`, so D4 snapshots it and the frozen copy fades correctly; but S2 then holds the decoder at full strength over the fade | **S2's core must end the hold at the transition start** (hide or retire the held decoder when the outgoing slide is removed, the moment its own comment at `:2162` currently avoids); it cannot be the frozen element (D4 never adopts elements). S2 picks this up after merging `main`, in its own `live_continuity_js.py`, and adds DX-M to its round. |
| `managed_obs_qualify.py` | `mmo-cef` crosses the dissolve (`:611` → `mm_opacity_probe.drive`, `PLAN` has `d23`); `make_export` (`:299`) copies the grey-bug `html-player` PDFs | `--arm dissolve` (DX-2) with media sessions on `p2-binary`, shared resolver; re-run `mmo-cef` |
| `mm_opacity_probe.py`, `mm_handback_probe.py` | cross 2→3 to reach 3→4; score GL frames | re-run |
| `p2_recovery_html_adversarial.py` | serves the patched player in every arm; during the 2→3 dissolve the movie ROI now shows the frozen counter fading instead of the baked poster; `deliberateRestart2to3` and the bridge-off timing read decoder identity/rVFC and the counter after the restart | re-run every arm; any moved 2→3 finding is root-caused (risk §13) |
| `run_gates.sh` | pins no player sha | no edit; re-run full tier from a fresh pinned worktree |

## 7. Browser support

`plus-lighter`: Chrome 100 (ChromeStatus 5677338286096384; web.dev, March 2022); CSS Compositing 2; CSS Transforms 2 §7.1;
Jake Archibald (2021). `checkVisibility` option names `opacityProperty`/`visibilityProperty`: Chrome 121. OBS 32.2.2 bundles CEF
127 (`…branch-heads/6533`): availability only; CEF's compositor and `drawImage` tone path are qualified by DX-2. Headless:
Chrome 154.0.8037.59, ANGLE Metal; software compositing via `--disable-gpu`.

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`)

Files: `dpatch3.py` → `dpatch6.py` (rev 3 cross-fade; + F3 at D3 (too late, below); + F1; + F3 take at D4), `proto3.py` →
`proto6.py` (one headless Chrome
per arm, transparent PNG, texture readback, rAF log incl. leaf effective opacity and `requestVideoFrameCallback`; `p2cut` deck
= P2 2→3 rewritten in memory to Keynote's own cut shape; per-frame PNG screencast), `analyze_full.py`, `f3analyze.py`,
`f1analyze.py`, `f3model2.py`, `curve.py`, `matched.py`, `overlap6.py`, `node_ids.py`, `node_r6_test.py`, `node_r6_near.py`,
`node_f3_r6_test.py`, `bake/bake.py`.

**Node, real extracted code, both patched players.** Ids pre-order on the real `VB` classes. Over all 133 transitions on disk
and in the committed fixtures: 46 Dissolves copied with two rules naming exactly the ids `VB` then allocated; 8 cuts copied
(incoming hidden, mirror `hidden` true→false, no rule); 79 stock with no rule; 0 source mutations. 21 near-misses stay stock;
five construction failures (dropped blend, dropped isolation, `insertRule` throwing 1st/2nd, no stylesheet) build the stock
tree with no rule on a built node. **F3 on a stub DOM (take + attach):** success takes and attaches one holder at the computed
geometry (also with a 300-px clipping panel, and on a cut's layer); non-matching scene, cross-fade not engaged, other scene at
attach, not ready, invisible, translucent ancestor, rotated ancestor, 3D transform, `cover`, alpha frame, `drawImage` throwing,
missing base layer, fully clipped → nothing attached, slot cleared; in all 16 cases the video proxy records **no** property
write and no method call besides `checkVisibility`/`getBoundingClientRect`.

| Arm (bytes; 1-min load at start) | Mid frames | Max residual, full res (LSB) | Overlap α min | Complement | Notes |
|---|---|---|---|---|---|
| `p2-t-patch` (rev 3; 3.39) | 6 | 1.3 | 255 | 0 | one `startTime`; in − ease ≤ 1e-6; computed blend/isolation on the right nodes |
| `p2-t-noblend` KB (rev 3; 3.17) | 6 | 64.0 | 191 | 0 | |
| `p2-t-stock` null (2.61) | 8 | 206.4 | 255 | 254 | in-only α 255 at the first changed frame |
| `k17-t-patch` DSK 5→6 (rev 2; 3.57) / stock (4.23, exploratory) | 6 / 6 | 1.5 / 204.5 | 255 | 0 / 254 | |
| `p2-t-patch-sw` `--disable-gpu` (rev 1; 4.98, exploratory) | 4 | 2.7 | 254 | 1 | |
| `p2-o-stock` / `p2-o-patch` opaque-texture (rev 2; 3.27 / 3.14) | 8 / 8 | 0.7 / 1.2 | 255 | n/a | matched on/off ≤ 1.51 |
| `p2cut-t-stock` cut null (3.34) | – | – | – | – | **both slides visible**: 2 of 27 rAFs from DOM insertion, 1 of 47 screencast frames |
| `p2cut-t-patch` cut (rev 4; 3.33) | – | – | – | – | 0 of 44 rAFs, 0 of 38 screencast frames (incoming 0 while outgoing 1, then swapped) |
| `p2bin-t-patchdbg` freeze at D3 (3.97; and 2.46, 4.48 exploratory) | – | – | – | – | **no snapshot**: 0 `<video>` in the document at `renderEffects` (detached by `displayScene` at +480 ms, same task) → D4 |
| `p2bin-t-patchdbg` freeze at D4 (rev 4; 3.51) | 11 | 1.7 vs the first transition frame (movie region ≤ 1.7) | 255 | – | frozen index 56 = last rVFC-presented 56 (presentedFrames 57), same index in every screenshot while decodable (α ≥ 128); live mid-grey 139 → frozen 128, black/white 0/255 both |

## 9. Acceptance

**Rule.** Every blocking check has a positive control that must PASS and a negative control that must FAIL, read before the
candidate counts. Missing or malformed evidence is INCONCLUSIVE and invalidates the round; INCONCLUSIVE never satisfies an
expected FAIL. One headless Chrome at a time; 1-min load < 4 at start; no OBS during headless runs.

| Check | Positive (PASS) | Negative (FAIL) |
|---|---|---|
| Model (texture group) | `opaque-off` | `off`, `noblend` |
| Complement | `noblend` | `off` |
| No dip | `opaque-off` | `noblend` |
| Curve / Monotone | rAF of `on2` / `opaque-off` | scorer cases: linear curve / non-monotone e |
| No flash | `delay-on` | `delay-off` |
| Screen path | `screen-on` | `screen-off` |
| Hand-off | `off` and scorer case: unchanged | scorer case: injected step above τ |
| Cut: no union frame | `cut-on` | `cut-off` |
| Frozen frame (index, constancy) | `m-paused` (frame known in advance) | `m-off` (baked frame) |
| Frozen region fades | `m-on` | `m-hold` (full-strength copy) |

### 9.0 Q0b — step 0 (scratch, before W1)

Done (§8): cross-fade, KB, opaque-texture controls, matched progress, cut (one take per arm), freeze on the binary counter.
Pending, DX-1 criteria: cut ×3 more takes per arm; freeze ×3 incl. `m-paused` and `m-hold`;
`screen-on`/`-off`; D2 `on`; CvC; `--disable-gpu` and DSK deck on current bytes; `delay-on`/`-off`; lifecycle dry run;
F3 and its tone step inside CEF (DX-2). A miss stops the plan for re-planning, never a threshold change.

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver contract (W2; reused by W3; read-only).** Stock `index.html`, player and slide JSON from the deck's
  `html-unmodified`; PDFs/`.pdfp` from a fresh scratch strip with the corrected stripper (715cb3f1); movies mapped explicitly
  to decode-compatible copies (P2: `html-player` H.264; DX-M: `p2-binary` binary counter). In-memory overrides only where a
  row says so (loop flag; `automaticPlay`/`beginTime`; the `p2cut` cut shape). Every asset's provenance (source, sha,
  override) recorded; every required movie must decode (`readyState ≥ 2`, `currentTime` advancing).
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1, own port (never 9222). Alpha arms: `LiveOutputHost` attach.
  Screen arms: `LiveOutputHost` headless launch mode, screenshots via the host's transport.
- **Instrument.** Innermost hook (a `MutationObserver` also records `<video>` detaches), from the first rAF with the transition DOM: each leaf's effective opacity (also before any
  animation attaches), every transition animation (`currentTime`, `startTime`, value), visible `<video>` rects, scene/hash,
  `requestVideoFrameCallback` on every `<video>` (presented frames, media time); at that first rAF both texture canvases, every
  frozen holder canvas (`toDataURL`, geometry) and the computed `mix-blend-mode`/`isolation` chain. PNG screenshots with alpha
  at full scale from 0.35 s before the advance to T + 0.6 s; cut arms add a per-frame PNG screencast.
- **Scorer (pure, every pixel of the mask; reused by DX-2).** A = outgoing texture with the frozen holders composited at their
  geometry, B = incoming, premultiplied; per admitted screenshot e by least squares; residual `|F − ((1−e)·A + e·B)|` outside
  visible `<video>` rects + 2 px (the texture group). Screen arms: RGB vs the cross-fade over black. Media (DX-M): the binary
  strip decoded from the holder canvas and from every screenshot in its region (straight RGB is constant while α fades).
- **Capture integrity (shared; any violation INCONCLUSIVE):** texture ids equal the export JSON's; hash before/after = the
  transition's slides; screenshot size 1920×1080 and page mode as the arm states; finite, non-empty measurements; served
  digest as the arm states; fade arms ≥ 6 mid frames (0.05 < e < 0.95, admitted only while the transition DOM is present);
  delay arms ≥ 2 screenshots in the window and rAF coverage of it; cut arms rAF coverage from DOM insertion to 3 frames after
  the cut and a screencast frame inside that span; media arms an rVFC record before the freeze and a decodable holder;
  lifecycle rows ≥ 1 settled final frame plus the DOM/stylesheet census.

| Check | Threshold (measured) |
|---|---|
| Model | every mid frame max residual ≤ τ = 4 LSB (1.3–1.5 GPU, 2.7 software; KB 64, stock 205–206) |
| Complement | every admitted frame: \|α_in-only + α_out-only − 255\| ≤ 2 (0; stock 254) |
| No dip | overlap α ≥ 252 (255 / 254; KB 191) |
| No flash | effective incoming opacity 0 in every rAF before the first animation frame |
| Curve | two animations, one `startTime`; \|in + out − 1\| ≤ 1e-5; \|in − ease-in-out(ct/T)\| ≤ 1e-4 |
| Monotone | e non-decreasing (−0.01 slack), ≥ 0.99 before the hand-off |
| Hand-off | H = max premultiplied \|first-live − last-transition\| outside the destination's movie rects on the identified frames (either missing → INCONCLUSIVE); H ≤ τ |
| Cut: no union | no rAF from DOM insertion on with both leaves' effective opacity > 0, and no screencast frame with both slides' exclusive content |
| Frozen frame | decoded holder index = the last rVFC-presented frame before the freeze (offset measured, §8); the same index in every screenshot while the region's α ≥ 0.25 |
| Frozen region | the outgoing estimate `(F − e·B)/(1 − e)` in the movie region is constant over the frames with e ≤ 0.8 (spread ≤ τ/(1 − e)) and decodes to the frozen index: frozen and fading. A moving movie or a full-strength copy makes it drift; the baked poster keeps it constant but fails the index (measured: whole frame ≤ 1.7 LSB from the model) |
| Tone step | mid-grey (strip background, Y = 126) frozen minus last live: −11 ± 1 (measured), black/white 0 ± 1; report-only until owner question 5 is answered |

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
| `cut-off` / `-on` | `p2cut` (P2 2→3 as a cut, in memory) | out-only, in-only | no union → FAIL / PASS | none | `off` / `on` |
| `m-on` | `p2-binary` 2→3 through `LiveOutputHost` (continuity on) | out-only, in-only | frozen frame, frozen region, model → PASS; no visible full-strength `<video>` during the fade | as `on` + one holder | pinned `on` |
| `m-paused` | as `m-on`, the movie paused on a known frame before the advance | as `m-on` | frozen index = that frame exactly → PASS | as `m-on` | pinned `on` |
| `m-off` | as `m-on`, patch off | out-only, in-only | frozen frame → FAIL (baked poster, no index) | none | pinned `off` |
| `m-hold` | as `m-on`; one counted splice appends the holder to the container instead of the wrapper (a full-strength copy) | as `m-on` | frozen region → FAIL (region α 255 through the fade) | as `on` | base + splice |
| `on-sw` | P2, `--disable-gpu` | as `on` | all → PASS | as `on` | `on` |

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
| end of show | P2 slide 4's dissolve, loop 0 | held endpoint = stock twin's (DOM, holder, rules legitimately remain); then go-to 1 → cleanup |

### 9.2 DX-2 inside OBS CEF — `managed_obs_qualify.py --arm dissolve` (unrecorded)

One launch, the shared resolver, sessions `on`, `on2`, `off`, `noblend`, `opaque-off`, `opaque-on` (P2) and `m-on`, `m-off`
(`p2-binary`) through the managed bridge with DX-1's hook, the advance and a `GetSourceScreenshot` (PNG, alpha) burst; DX-1's
integrity rules. **Calibration fixed before capture, applied without clamping:** n = max mid-frame residual of `opaque-off`;
τ_CEF = max(4, ⌈n⌉ + 1); complement 2 + ⌈n⌉; no dip 252 − ⌈n⌉; caps τ_CEF ≤ 8, complement ≤ 6, no dip ≥ 248, so n > 4 is
INCONCLUSIVE. The CEF tone step at the freeze is measured on `m-on` (report-only, then the Q0b bound). Blocking per the §9
control table. Refuses while `OBED_LIVE_MM_OPACITY` is set.

### 9.3 DX-3 owner check in real OBS

- **Pre-check:** DX-1's texture classifier on the chosen production transition (export only): fill-less outgoing pixels and
  ≥ 2 000 px in-only make it affected; otherwise it is a regression control. For the movie check, a slide whose movie plays
  live in OBS (H.264; ProRes never plays live, §1.4).
- **Where:** Take output (Keyer) on the stripped P2 copy 2→3, the pre-checked production transition, and an H.264 movie slide
  advanced several seconds into playback.
- **Pass:** slide 3 fades in from nothing over the whole fade; slide 2 keeps its colours while fading; no darker or more
  transparent moment where both overlap; the movie stops on its current frame and fades out with slide 2 (no jump back to its
  opening frame, no brightness step the owner notices); no jump at the hand-off. **Null** (affected transitions only):
  `OBED_LIVE_MM_OPACITY=off` shows the pop-in and the jump.
- **Report** candidate and null separately with the served mode and `output.mmOpacity.sha256`.

### 9.4 Regression

`run_gates.sh` full tier from a fresh pinned worktree; `mm_opacity_probe.py`, `mm_handback_probe.py`; managed OBS (owner
session) `--arm mmo`, `--arm g2`, `--arm mmo-cef`. Root-cause any change.

## 10. Tests (three new test functions, as rev 3; everything else extends them)

1. **Free:** tuple-parametrized anchor/replacement refusal (both patchers); off identity; `patch_rendering` = `patch_player`
   minus the hook; "every original anchor gone" (`test_live_runtime.py:205`, `:265`, `:367`); new-player equivalence;
   `node --check`; pin mismatch. Synthetic builders derive from the tuple.
2. **Edits** (`test_live_runtime.py`): re-pin; hand-back tests use `HANDBACK = slice(5, 8)`; the composition test runs R1–R5,
   R6–R8, D1–D4 in every order and checks containment including self.
3. **New, REAL-gated, parametrized over both players and one case table** (Node on the real extracted code): D1–D4 offsets;
   pre-order ids; every committed `tests/fixtures/live_continuity` transition (copied or stock as §8); a cut row (the D1 cut
   shape, copied with no rule); the 21 near-misses; the five construction failures; the 16 F3 stub-DOM rows of §8 (take/attach
   count, geometry, and no write or call on the video).
4. **New `tests/test_dissolve_probe.py`, one parametrized function** (synthetic numpy): rev 3's rows (cross-fade PASS, pop-in
   FAIL, dip FAIL, ±1 LSB PASS, masked video, linear curve and non-monotone FAIL, hand-off unchanged / injected / missing,
   integrity cases → INCONCLUSIVE, INCONCLUSIVE `off` fails the gate) plus: union frame FAIL / clean cut PASS; binary strip
   decode (valid, parity error → None); frozen index equal PASS / ≠ the last presented frame FAIL (measured offset 0);
   outgoing estimate drifting (moving movie, full-strength copy) FAIL; missing rVFC record or undecodable holder → INCONCLUSIVE.
5. **`test_managed_obs_qualify.py`:** the existing env-refusal test parametrized over the new arm; the calibration test
   (n = 4 / 4 + ε).

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | D1–D4; docstrings; re-pins; tests 1–3 |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | resolver, DX-1 incl. cut and DX-M arms, lifecycle; test 4 |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | `--arm dissolve` incl. media sessions, on W2's resolver/scorer; test 5 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, plan status | README fallback line; one SKILL sentence; handover (S2: end the hold at the transition start) |

Order: W0 → Q0b → W1 ∥ W2 → W3 → gates → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-2,
`mmo-cef`, DX-3 (owner session) → one PR to `main`. Never merge.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and construction failure; nothing mutates export JSON. (3) Rule ids = allocated ids; abandoned ids on partial insert. (4) One
`applyCssAnimation` pass; the cut never shows two layers. (5) D4/D3 are add-only, per movie, never touch a `<video>`, and every
failure leaves the baked frame. (6) `off` = today's bytes. (7) Every threshold measured or fixed by formula; every blocking
check has PASS and FAIL controls.

## 12. Owner decisions (all 2026-10-11, in chat)

- **Target (movies):** "in Keynote the vid stops playing and dissolves out" — freeze on the current frame, fade with slide 2.
1. **Switch: fold into `mm_opacity`** (decided).
2. **Scope: every output** (decided).
3. **F1 (`none` cut) in this patch; F2 (other transitions) a separate follow-up** that needs an owner-authored Q-deck (decided:
   "Fold F1 in, F2 separate followup"; final, after two same-day revisions).
4. **F3 (freeze and dissolve out) in this patch** (decided).

5. **Mid-tone step at the freeze (new, design-changing).** The snapshot is the exact frame but ~11/255 darker in mid-tones than
   the live movie a frame earlier (Chromium's video path lifts mid-grey; `drawImage` does not), at the same moment the fade
   starts. (a) **Accept** it as a known limit, like G2's identical takeover step (README: "midtones may shift slightly"), and
   let DX-3 judge it on a real movie. **Recommended**: no ownership crossing, no change to either continuity core.
   (b) Freeze the live `<video>` itself (move and pause it): no step, but main's and S2's cores must learn to skip a frozen
   element (`stash` re-plays and remounts any detached planned movie), a second failure model, and their gates re-run.

## 13. Risks and out of scope

CEF's compositor and `drawImage` tone path unproven until DX-2. The id prediction relies on `VB`'s pre-order allocation
(proved; re-checked by every run's style premise). Software compositing cost during a transition. Production transparency
unverified (DX-3 pre-check). P2's 2→3 findings now see a frozen counter during the dissolve. F3 residuals (§3.2) keep today's
look; the freeze's mid-tone step (owner question 5); F1 measured on one take per arm (Q0b repeats it ×3). Out of scope: F2, GL effects, Keynote-app comparison (hands off Keynote), S2's core change (S2's PR).

## 14. Critique log

Raw rounds and prompts: `.agents/reviews/dissolve-crossfade/plan-astra-r{1,2}.md` (+ `.prompt.md`).

### r1 — GPT-6 Astra high (Codex), on rev 1 `8e572864`

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / new | Folded; superseded in rev 3 by commit-before-construct (r2-1). | §3 |
| 2 | major / new | Folded: D1 consumes its anchor; containment incl. self checked. | §3.1, §6.1 |
| 3 | major / new | Folded; corrected in rev 3 (r2-3) and rev 4 (owner decision 4). | §3.2, §6.2 |
| 4 | major / new | Folded: per-arm contract; INCONCLUSIVE never satisfies a FAIL. | §9.1 |
| 5 | major / new | Folded: CEF controls and fixed calibration (corrected r2-6). | §9.2 |
| 6 | major / edge | Folded (completed r2-4). | §9.1 |
| 7 | major / new | Folded and measured: 1.51 LSB; screen-path arms. | §2, §9.1 |
| 8 | major / closed | Folded: `mmo-cef` re-run. | §6.2, §9.4 |
| 9 | minor / new | Folded: shared resolver. | §9.1 |
| 10 | minor / edge | Folded: geometry/media predicate. | §3.2 |
| 11 | minor / edge | Folded: DX-3 pre-check, regression control. | §9.3 |
| 12 | nit / closed | Folded: 382. | §1.2 |

### r2 — GPT-6 Astra high (Codex), on rev 2 `cd289a05`, and the owner's movie answer

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| r2-1 | major / closed | Folded by commit-before-construct (no post-draw path for the cross-fade). Rev 4's D3 is post-draw but add-only and independent of the cross-fade. | §3 |
| r2-2 | major / new | Folded: shared capture integrity with per-arm minimums. | §9.1 |
| r2-3 | major / new | Folded: frozen media under the outgoing wrapper; media gate with a deterministic counter, a full-strength negative and a positive; the static score stays "texture group". | §3.2, §9.1 |
| r2-4 | major / closed | Folded: lifecycle rows incl. hide/show, queued skip, real automatic branch, end of show. | §9.1 |
| r2-5 | major / new | Folded: hand-off statistic and controls. | §9, §9.1 |
| r2-6 | minor / edge | Folded: n > 4 INCONCLUSIVE. | §9.2 |
| r2-7 | minor / new | Folded: full-resolution scoring. | §8 |
| owner | decision | Recorded; baked frame measured. | §1.4 |

### rev 4 — owner decisions 1–4 (2026-10-11)

| Item | Disposition | Where |
|---|---|---|
| 1 fold, 2 every output | Recorded; alternatives text removed. | §4, §5, §12 |
| 3 F1 now, F2 follow-up | F1 measured (§8) and added to D1–D2 (cut shape: incoming hidden + mirror, no rules); F2 stays out. | §1.5, §3, §8, §9 |
| 4 F3 now | Prototype showed the live `<video>` is already gone at `renderEffects`; the freeze is taken at D4 (`jumpToScene_partFour`, before `displayScene`) and attached at D3. Snapshot, not move (evidence §3.2); add-only failure model; DX-M gate; S2 must end its hold; new owner question 5 (mid-tone step). | §1.4, §3, §6.2, §8, §9, §12 |
