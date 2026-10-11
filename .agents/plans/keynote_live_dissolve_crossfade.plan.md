# Dissolve and cut over fill-less slides: a true cross-fade, a clean cut, and movies that freeze and fade

**DRAFT rev 5**, 2026-10-11. Rev 1: Opus planner (`8e572864`). Critique r1–r3: GPT-6 Astra high via Codex (not Opus; owner
2026-10-11), 12 + 7 + 11 findings, all folded (§14). Revs 2–5: Opus planner (`cd289a05`, `f3bd8b55`, `4ffcd8ad`, this).
Owner decisions 1–4 are recorded (§12; decision 4 re-confirmed: F3 stays in this patch). Owner questions 5–7 are open: the plan
proceeds on each recommendation as a **provisional default — owner to confirm** (§12). The plan iterates (rev + Astra) to round
7, then stops for owner review. Plan only: no product code, no commits, no OBS, no Keynote. Base: `main` @ `1589d096`.
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; among the listed anchors only R8, D4 and the hook `_ANCHOR` move,
each by 38). Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored); scratch `x` =
its `plan-2026-10-11/planner/x`. Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins),
`keynote_live_handback_geometry.plan.md` (R6–R8), `keynote_live_paint_oracle.plan.md` (oracle stays stock).

## 0. Summary

- **Root cause (player, not host).** Keynote exports a slide transition as two flattened full-slide textures: the incoming
  slide at the bottom with **no animation**, the outgoing slide on top animated away (Dissolve: `opacity 1→0`, EaseInEaseOut;
  `none` cut: `hidden` false→true over 1 ms). Keynote's own exports hide the incoming under a full-slide black fill. Without
  that fill (the real DSK case, §1.3) the incoming shows at full strength while the outgoing is still on screen: the Dissolve
  pops in; the cut shows both slides at once (§1.5).
- **Cross-fade and cut (D1, D2: commit before construct).** For a tree of exactly the Dissolve or cut shape, one method
  commits what is needed before the player builds anything and returns a **copy**: for a Dissolve two read-back rules
  (`#layer<c>{isolation:isolate}`, `#layer<in>,#layer<out>{mix-blend-mode:plus-lighter}`, on the ids about to be allocated) and
  an incoming leaf starting at opacity 0 with the mirror `0→1`; for a cut of Keynote's exported timing only, an incoming leaf
  starting hidden with the mirror `hidden` true→false. Any failure yields the stock transition. Result: premultiplied
  `(1−e)·P_out + e·P_in`; a cut whose layers swap within its 1 ms and never show both at full strength.
- **Movie freeze (D4 takes, D3 attaches; add-only).** Owner: "in Keynote the vid stops playing and dissolves out". The player
  deletes the playing `<video>` as the transition starts, so the movie jumps back to the **opening frame** baked into the
  outgoing texture (§1.4). D4, just before that, snapshots each `<video>` whose look a snapshot reproduces exactly
  (**conservative admission**, §3.2; overlying plain canvases redrawn, question 7); D3 puts it in the outgoing layer's fading
  wrapper (a cut: the layer), or discards it. The `<video>` is never moved, paused or marked; a failure leaves today's look.
- **Not fixed here (pre-existing, §1.4):** main's continuity bridge keeps P2's slide-4 decoder at full strength over the
  terminal fade, stock and patched alike; S2 ends that and its own hold (owner question 6).
- **Measured** (headless Chrome 154, §8): cross-fade residual ≤ 1.3 LSB (P2) / 1.5 (DSK, 17c0c938); nulls pop in (205–206);
  KB without the blend dips to α 191; opaque on/off ≤ 1.51. Cut: stock shows both slides in 2 rAF / 1 screencast frames,
  patched 0 / 0. Freeze (rev-4 admission): index = last presented, constant; mid-grey −11/255 at the freeze (question 5).
  Rev 5's admission and attach rules are Node-verified only (§8); browser runs wait in Q0b (§9.0).
- **Switch:** `mm_opacity` (`OBED_LIVE_MM_OPACITY=off` restores today's bytes); every output; `RUNTIME_VERSION` stays 2.

## 1. Facts (code-read on both players; every anchor count-checked)

### 1.1 How the player draws a slide transition

| Step | Where (byte, both players unless split) | What |
|---|---|---|
| GL vs CSS | `jC` @2368216 / @2368254; routing `qC&&-1!==jC.indexOf(C.name)` @2312807 (`PB.renderEffects`) and @2314108 (`PB.renderEffect`, per-object builds) | `apple:dissolve` and `none` are not in `jC`: the CSS renderer `NB` (@2292342) draws them. |
| Build | `PB.renderEffects` @2311803; `const A=new VB(C.baseLayer,…)` @2312557 … `this.cssRenderer.draw(a),a.removeChild(w)}` @2313053 | `yB` keeps the export's `baseLayer` by reference (@2270532). `VB` allocates `layerId=TB,TB+=1` (`let TB=0` @2270526, same module scope as `PB`) pre-order: root, container, incoming, outgoing = TB … TB+3 (proved, §8). `WB` creates keyframe rules during construction. `NB.draw` builds `layer<id>` divs (a `layer<id>-opacity` wrapper per animated opacity; a `hidden` animation runs on the layer itself). The DOM it replaces (`w`, drawn by `displayScene` with no live `<video>`: §1.4) is removed in the same task. |
| Keyframes | `WB` @2271556; `EaseInEaseOut` → `ease-in-out` @2282229; `WB.createAnimationRuleForKeyframe` (≈@2283770) turns `hidden` into **opacity** keyframes 1/0, interpolated over the duration; `createAnimation` @1953007 | rules live in the animation manager's own `<style media="screen">` |
| Animate | `PB.playCurrentScene` @2356281 / @2356319: `renderEffects()` then `setTimeout(()=>{…animateEffects…},1e3*g)` (`},1e3*g)` @2357455 / @2357493) | Render and animate are separate tasks; `applyCssAnimation` @2303763 sets visibility and starts every layer's animation in one loop. |
| Cleanup | `displayScene` @2354643 / @2354681 → `deleteAllAnimations()` @1953106 + `removeEvent` @2291872 | at the next scene or any go-to; at the end of the show (`currentSceneDidComplete` @2357464 / @2357502) the held endpoint keeps its DOM and rules until navigation. |

### 1.2 The export data (every transition on disk)

Census over the 25 export roots under `output/fixtures` (scratch `census.py`): **42 `apple:dissolve`** and **8 `none` cuts**
(D1–D6), all root → one container (no texture, animation or `objectID`) → two textured leaves (no `objectID`, no video flags,
identity geometry); incoming without animation; outgoing with one animation (Dissolve: `opacity` 1→0, `EaseInEaseOut`,
`fillMode both`, 1.5 s or 1.0 s; cut: `hidden` false→true, `duration` 0.001, `beginTime` 0, `fillMode both`, no
`timingFunction`, `timeOffset`/`repeatCount` 0, no autoreverse). Also 67 Magic Moves (GL), 382 per-object CSS builds. P2 2→3
= slide `0C652BEB` event 3. **D2 is the only D deck with a Dissolve** (overlap only); `minimal-alpha-dsk-17c0c938` is the
17c0c938 pop-in deck (5→6). Every on-disk cut is a deck's last transition, to the shared background `9B0DBE…` (empty stripped).

### 1.3 What the live presenter serves

`html_preview.export_html` is the only export path, served unmodified in screen mode (black page, `#obed-output-black` hide) and
keyer mode (alpha page, `#body` opacity hide; `live_host.py:418–436`); the product never strips (715cb3f1). **The trigger is a
fill-less outgoing texture, not the page**: RAWT-1 (Keynote's PDFs, transparent page) does not pop in; STRIPT-1 and NULLSTRIP
(stripped PDFs on the black page) do. Fill-less decks (DSK decks use the wall deck's transparent layout, README :21; DSK clip
slides are forced to dissolve, `dsk_assemble.py:2958–2968`, `:4204–4207`) are the real case; production: DX-3 pre-check.

### 1.4 Movies at a transition start

- **The export bakes the opening frame.** DSK 7→8 (scratch `bake/bake.py`): the outgoing texture matches frames 7 / 4, frame 0
  within +1.4 MAD; an advance 0.5–10 s in differs by MAD 10–70 (floor ≈ 21). Keynote freezes the current frame (owner).
- **When it goes.** On an advance: `jumpToScene` → (100 ms) `jumpToScene_partFour` @2353722 / @2353760 → `displayScene`
  (removes the live slide, `<video>` included) → `playCurrentScene` → `renderEffects`, one task (measured on `p2-binary`:
  detach +480 ms, `renderEffects` +479.8 ms with no `<video>` left); so the freeze is taken before `displayScene`.
- **Who owns the playing `<video>`.** Raw player: slide 2's own element inside `w`. Main's continuity core: that element or a
  remounted decoder (inside or outside `w`); its `MutationObserver` on removed `<video>` nodes (`live_continuity_js.py:1750`)
  calls `stash` (`:719–807`: pools a planned movie, re-plays it, schedules `tryRemount`, `:809–842`). In the LIVE runs (P2
  **2→3**) nothing main paints is visible during the dissolve. S2 (`d88584eb`) holds a restarting decoder through it at
  opacity 1 (`:758–763`, `:1759–1777`, `:2158–2169`).
- **Main's bridge over the terminal transition (static read; pixels Q0b).** Only continuity-qualified plans engage the core
  (`QUALIFIED_PLAN_SHA256`, `live_continuity.py:627`, refusal `:895`: P2-measured plans only). There the 3→4 bridged decoder
  lives in `#body`, outside the slide DOM; `keepAtSlot` (`live_continuity_js.py:1056–1093`) re-attaches, re-plays and sets
  `opacity 1` every frame while the hash is ≥ slide 4 and it has not ended; `slotLive` (`:1007`) has no transition condition.
  So at P2 slide 4's terminal Dissolve **stock and patched alike** show it at full strength, playing, through and after the
  fade (Astra r3: extracted `keepAtSlot` at hashes 9–11 keeps opacity 1). Pre-existing; owner question 6.
- **Foreground over movies (export JSON).** P2 slide 2: a translucent square (canvas texture `3F22E494`, opacity 0.2947, slide
  px 789,673 353×313) follows the movie (109,795 952×268) in paint order and overlaps it. DSK slide 7: labels (47,799 257×65;
  361,799 283×65) over its two clips. Every known movie deck has foreground over its movie (owner question 7).
- **Codecs.** DSK clip fixtures are ProRes (neither headless Chrome nor CEF decodes it: no jump); H.264 movies play and jump.

### 1.5 The `none` cut (F1)

A cut's outgoing `hidden` animation is opacity keyframes 1→0 over 1 ms with `fillMode both`; its first animated frame samples
keyframe 0% (outgoing visible) while the incoming, which has no animation, is already visible beneath: on fill-less textures
that frame shows both slides, and so does any frame painted in the render→animate gap (§8). Every cut on disk goes to the
empty background, so it shows nothing extra; a cut between two content slides does.

## 2. Arithmetic (premultiplied RGBA, 0..1; e = eased progress)

- **Stock Dissolve:** `C = (1−e)·P_out + (1 − (1−e)·α_out)·P_in`: exact where `α_out = 1`, `P_in` at once where `α_out = 0`.
- **Plain opposite fades (rejected):** `α = 1 − e + e²` = 0.75 at e = 0.5 where both are opaque.
- **Fix:** in the isolated container group, incoming (opacity e, `plus-lighter` onto zero) = `e·P_in`; outgoing (opacity 1 − e,
  `plus-lighter`) gives `G = (1−e)·P_out + e·P_in`, `α_G = (1−e)·α_out + e·α_in`, never clamped. Preconditions enforced by the
  predicate (§3.2): two texture leaves, no video/poster layer, identity 2D geometry (the grouping properties flatten
  `transform-style`, CSS Transforms 2 §7.1). Endpoints exact. 8-bit: 1.3–1.5 LSB GPU, 2.7 software; τ = 4. Opaque textures:
  algebraically stock; measured on/off ≤ 1.51 LSB (report-only bound 2).
- **Frozen movie:** the snapshot `S` (frozen frame plus each overlying plain canvas at its effective opacity) is opaque and
  covers exactly the admitted region above the outgoing texture inside the outgoing wrapper, so the group gives
  `(1−e)·P_out' + e·P_in` with `P_out'` = texture with `S` over that region; valid for what admission proves (§3.2).
- **Cut (exported timing only):** incoming opacity 0→1 mirrors outgoing 1→0 over the same 1 ms, `fillMode both`, started in
  one loop: the opacities sum to 1 at every instant and the swap completes 1 ms after the first animated frame. Only a frame
  sampled inside that 1 ms shows partial opacities (never seen, §8); none shows both at full strength (the stock defect).
- **Isolation:** the blend's backdrop is the container group only; it cannot make an independent overlay fade (§1.4, §6.2).

## 3. The patch

### 3.1 Exact replacements (R9–R12 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedShape`, `__obedDissolveLayer`, `__obedFreezeTake`, `__obedFreeze` + `renderEffects(A){` (7 010 B) |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |
| D3 (R11) | after the CSS draw @2313053 (42 B) | `this.cssRenderer.draw(a),a.removeChild(w)}` | `this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}` |
| D4 (R12) | `jumpToScene_partFour` @2353722 / @2353760 (50 B) | `jumpToScene_partFour(A,B){if(this.displayScene(A),` | `jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),` |

The methods (scratch `dpatch8.py`, Q7 default; `node --check` passes on both patched players; `PB` and the controller share the
module scope of `TB` and `UC`). Q7(a) is scratch `dpatch7.py`: `if(i>I){var a=ok(n,v);if(!a)return;Y.push([n,o,a]);continue}`
becomes `if(i>I)return;`, and `ok`, `Y` and the redraw go (D1 5 903 B).

```
__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||!1!==x.from.scalar||!0!==x.to.scalar||.001!==x.duration||0!==x.beginTime||"both"!==x.fillMode||x.timingFunction||x.timeOffset||x.repeatCount||x.autoreverses:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,x,u]}catch(E){return null}}
__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=u?"cut":"dissolve",Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}:{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
__obedFreezeTake(U,A){U.__obedFrozen=null;try{var e=U.script.events[A],y=e&&e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),k=U.script.slideWidth/R.width,H=[],N=document.getElementsByTagName("*"),cs=function(n){return getComputedStyle(n)},own=function(n,z){var t=n.tagName;return/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED|INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(t)||!/rgba\(0, 0, 0, 0\)|transparent/.test(z.backgroundColor)||"none"!==z.backgroundImage||"none"!==z.boxShadow||"none"!==z.borderTopStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle||"none"!==z.borderLeftStyle||"none"!==z.outlineStyle||Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\S/.test(c.data)})};if(!(R.width>0))return;var ok=function(n,v){var z=cs(n),q=1,P,Q;if("CANVAS"!==n.tagName||"fill"!==z.objectFit||"0px"!==z.paddingTop||"0px"!==z.paddingLeft||"0px"!==z.paddingRight||"0px"!==z.paddingBottom||"none"!==z.borderTopStyle||"none"!==z.borderLeftStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle)return 0;for(P=n;;P=P.parentElement){var w=cs(P),m=w.transform;q*=+w.opacity;if("none"!==w.filter||"normal"!==w.mixBlendMode||"none"!==w.clipPath||"none"!==w.maskImage||"auto"!==w.zIndex||"visible"!==w.overflowX||"visible"!==w.overflowY)return 0;if("none"!==m){var M=new DOMMatrix(m);if(!M.is2D||M.b||M.c||!(M.a>0)||M.a!==M.d)return 0}if(P!==n&&+w.opacity<1&&Array.prototype.some.call(P.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))return 0;if(P.parentElement.contains(v))break}for(Q=v;!Q.parentElement.contains(n);Q=Q.parentElement);return"static"===cs(P).position||"static"===cs(Q).position?0:q};Array.prototype.forEach.call(document.querySelectorAll("video"),function(v){try{if(v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;var z=cs(v);if("50% 50%"!==z.objectPosition||"0px"!==z.paddingTop||"0px"!==z.paddingLeft||"0px"!==z.paddingRight||"0px"!==z.paddingBottom||"none"!==z.borderTopStyle||"none"!==z.borderLeftStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle)return;var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom];for(var a=v,q=1;a&&1===a.nodeType;a=a.parentElement){var w=cs(a),m=w.transform;q*=+w.opacity;if("none"!==w.filter||"normal"!==w.mixBlendMode||"none"!==w.clipPath||"none"!==w.maskImage||"auto"!==w.zIndex&&a!==document.documentElement)return;if("none"!==m){var M=new DOMMatrix(m);if(!M.is2D||M.b||M.c||!(M.a>0)||M.a!==M.d)return}if(a!==v&&("visible"!==w.overflowX||"visible"!==w.overflowY)){if("visible"===w.overflowX||"visible"===w.overflowY||"0px"!==w.borderTopLeftRadius||"0px"!==w.borderTopRightRadius||"0px"!==w.borderBottomLeftRadius||"0px"!==w.borderBottomRightRadius)return;var b=a.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}}if(q<.999)return;var vw=v.videoWidth,vh=v.videoHeight,fit=z.objectFit,f="fill"===fit?null:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,ch=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch)/2;if("fill"!==fit&&"contain"!==fit)return;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;for(var I=Array.prototype.indexOf.call(N,v),i=0;i<N.length;i++){var n=N[i];if(i===I||n.contains(v))continue;var o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||o.top>=c[3]||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;if(i>I){var a=ok(n,v);if(!a)return;Y.push([n,o,a]);continue}for(var P=n;P&&!P.contains(v);P=P.parentElement)if("auto"!==cs(P).zIndex)return}var x=document.createElement("canvas");x.width=vw,x.height=vh;var g=x.getContext("2d");g.drawImage(v,0,0);var sx=vw/cw,X0=Math.floor((c[0]-cx)*sx),Y0=Math.floor((c[1]-cy)*sx),X1=Math.ceil((c[2]-cx)*sx),Y1=Math.ceil((c[3]-cy)*sx);for(var d=g.getImageData(X0,Y0,Math.max(1,Math.min(vw,X1)-X0),Math.max(1,Math.min(vh,Y1)-Y0)).data,j=3;j<d.length;j+=4)if(d[j]<255)return;Y.forEach(function(y){g.globalAlpha=y[2],g.drawImage(y[0],(y[1].left-cx)*sx,(y[1].top-cy)*sx,y[1].width*sx,y[1].height*sx)}),g.globalAlpha=1;var D=document.createElement("div"),s=D.style,t=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=(c[0]-R.left)*k+"px",s.top=(c[1]-R.top)*k+"px",s.width=(c[2]-c[0])*k+"px",s.height=(c[3]-c[1])*k+"px",t.left=(cx-c[0])*k+"px",t.top=(cy-c[1])*k+"px",t.width=cw*k+"px",t.height=ch*k+"px",D.appendChild(x),H.push(D)}catch(E){}}),H.length&&(U.__obedFrozen={scene:A,holders:H})}catch(E){U.__obedFrozen=null}}
__obedFreeze(C,A){var F=UC.__obedFrozen;UC.__obedFrozen=null;if(C.obedDissolve&&F&&F.scene===this.sceneIndex)try{var O=A.layers[0].layers[1],W=document.getElementById("layer"+O.layerId+("cut"===C.obedDissolve?"":"-opacity"));if(!W)return;var Q=document.createDocumentFragment();F.holders.forEach(function(h){Q.appendChild(h)}),W.appendChild(Q)}catch(E){}}
```

### 3.2 How it works

**Construction (D1's `__obedDissolveLayer`, called by D2).**
- **Predicate (faithful or unchanged):** stock unless a `transition` named `apple:dissolve` or `none`; exactly root → one
  container → two textured leaves without sublayers; root and container without texture or animation; container and leaves
  without `objectID`, `isVideoLayer`, `isWebVideoPosterLayer` or 3D `transform`, identity affine, rotation 0, scale 1, opacity
  1, not hidden; leaves with identity `sublayerTransform`; incoming without animation; outgoing with exactly one animation
  without `keyTimes`/`path`/group: Dissolve `opacity` 1→0 (timing copied, so the mirror runs through the same `WB` code); cut
  `hidden` false→true with exactly §1.2's exported timing. 50/50 on-disk transitions match.
- **Dissolve: commit before construction.** Two rules for ids TB+1 … TB+3 are inserted and read back via `CSSStyleRule.style`
  (a dropped declaration reads empty); only then is the copy returned, and `new VB(copy)` allocates exactly those ids.
- **Cut:** no rules; the copy starts the incoming `hidden` (`addNode` writes `visibility:hidden`) with the mirror;
  `applyCssAnimation` makes it visible and starts both animations in one loop, the backwards fill holding its opacity at 0.
- **One failure point, before anything is built:** predicate miss, no stylesheet, a throwing `insertRule` or a dropped
  declaration return the export's own tree; after a partial insert `TB += 4` abandons those ids. Copies only along root →
  container → incoming; export JSON never mutated. The engaged kind `obedDissolve = "dissolve" | "cut"` lives on `yB`.

**Freeze: take (D4) before teardown, attach (D3) at the transition start, same task.** `__obedFreezeTake` runs only when
`jumpToScene_partFour` plays the scene now (`B`: advance and automatic paths) and its first effect has the §1.2 shape. It
stores detached holders as `UC.__obedFrozen = {scene, holders}`. `__obedFreeze` (D3) always clears the slot and attaches **by
engaged kind**: a Dissolve needs `layer<out>-opacity` (absent → discard: the leaf never fades); a cut uses `layer<out>`; all
holders go in one `DocumentFragment` append, so an append that throws attaches none.

**Admission (per `<video>`; any miss or exception skips that movie, which keeps today's look):**

| Rule | Reason |
|---|---|
| `readyState ≥ 2`, decoded size, `checkVisibility({opacityProperty, visibilityProperty})` | decodable and displayed |
| every element from the video to `<html>`: no `filter`, `mix-blend-mode`, `clip-path` or `mask`; `z-index: auto` (`<html>` exempt); `transform` none or positive uniform scale + translation (`a = d > 0`, `b = c = 0`); product of `opacity` ≥ 0.999 | snapshot drawn unreflected, isotropic, at full strength |
| video: `object-fit` `contain`/`fill`, `object-position: 50% 50%`, zero padding and border | the computed content box is the drawn frame |
| each clipping ancestor: `overflow` non-visible on **both** axes, all radii 0 (rect intersected); otherwise skip | rectangular clips only |
| alpha 255 at **every** source pixel of the attached region (`getImageData`, natural resolution) | never a double image over the baked frame |
| every other visible element with own paint (canvas, video, img, svg, iframe, object, embed, form control, background, box-shadow, border, outline, direct text) meeting the region: **earlier** in document order → `z-index: auto` on its chain to the common ancestor, else skip; **later** → Q7(b): a plain `<canvas>` (`object-fit: fill`, no padding/border; chain to the common ancestor passes the chain rules with `overflow` visible; a translucent ancestor paints nothing else; both branches at the common ancestor positioned) is redrawn into the snapshot at its geometry and effective opacity, in document order; anything else skips (Q7(a): any later one skips) | foreground and paint order preserved, or the movie skipped |

Positioned `z-index: auto` elements (the player's absolutely positioned layers) paint in document order; the position and
z-index rules keep every admitted case there. Of two overlapping movies the later is frozen, the earlier skipped.

- **Geometry:** element box → content box (`object-fit`, centred) → ∩ rectangular clips → slide px through the live slide's
  base-layer rect; a `div` (overflow hidden) at that rect holds a natural-size canvas at the content box, appended last in the
  outgoing wrapper. Stub rows give identical slide-px holders on 1920×1080, 2560×1440 and letterboxed 1440×810 stages (§8).
- **Snapshot, not move (decided by evidence):** moving the live element is a detach the core observes (`stash` re-plays and
  remounts it, §1.4; S2's stage pins pull it back). `drawImage` touches nothing; measured exact (last rVFC frame); its one
  cost is the tone path (Chromium's video layer lifts mid-grey by 11/255, `drawImage` does not): owner question 5.
- **Failure model:** add-only, per movie; the cross-fade rules are already committed. The `<video>` is only read (no write; no
  call besides `checkVisibility`/`getBoundingClientRect`; every stub row, §8), so `displayScene` removes it and the core handles
  the detach exactly as today. **Cost:** one natural-size `drawImage` + region `getImageData` per admitted movie, synchronous
  in the transition-start task (Q0b); one canvas per frozen movie (1920×540 ≈ 4 MB), freed with the transition DOM.
- **Cleanup is the player's:** holders live in the transition DOM, removed by `removeEvent` at the next scene, go-to/back,
  replay (fresh snapshot) or queued skip; at the end of the show they stay invisibly (outgoing at opacity 0) with the held
  endpoint until navigation; hide/show acts on the whole group. An unattached take is dropped at D3 or by the next take.
  Every path (advance, completion, replay, queued advance/skip, go-to/back, hide/show, automatic delay, loop wrap, end of
  show) is a row of DX-1's lifecycle scenario (§9.1).
- **Residuals (today's baked-frame jump, by design):** every admission miss above; movies drawn by G2; undecodable codecs;
  hyperlink transitions (`jumpToHyperlinkSlide` skips D4; never used live); self-playing mode (host-refused). Main's bridge
  and S2's hold paint over any freeze until S2 ends them (Q6).

## 4. Switch, pins, report

- **Switch (decided):** D1–D4 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`, `patch_rendering` and every synthetic test
  player pick them up. `mm_opacity=False` stays the hook-only bytes (`7cf00b56…` / `4f9fbffd…`). Docstrings say "rendering
  fidelity"; names and error text unchanged. README: `OBED_LIVE_MM_OPACITY=off` also restores the export's dissolve, cut and
  movie behaviour. **Pins:** `(on, off, rendering)` shape kept; `on` and `rendering` re-pinned for both players.
- **Report** `output.mmOpacity = {mode, sha256}` unchanged; `RUNTIME_VERSION` stays 2; preview inherits the patch; paint
  oracle stays stock; `web/live.py` unchanged.

## 5. Scope

**Every output; `apple:dissolve` and `none` of the §1.2 shape (50/50 on disk); admitted movies of the outgoing slide.**

| Effect | On disk | Fill-less textures | Plan |
|---|---|---|---|
| `apple:dissolve` | 42 | pop-in | D1–D2 |
| `none` cut | 8 | both slides for ≥ 1 frame (§1.5, §8) | D1–D2 |
| movies at a Dissolve/cut start | every DSK clip slide; P2, D decks | jump to the baked opening frame | D4 + D3 (admitted, §3.2) |
| main's bridged movie at P2 slide 4 → end | P2-measured plans | full strength over the fade (stock too) | none (Q6 default); S2 |
| per-object builds | 382 | ok | none |
| GL effects (`jC`) | 67 | not CSS | R1–R8 |
| other CSS transitions the player special-cases, smart/action builds | 0 | unknown | F2: separate PR, owner Q-deck |

## 6. Interplay

### 6.1 Anchor map (byte offset, length; e9b2fad4 / 17c0c938)

R7 2190367 (36) · R3 2190440 (46) · R4 2192650 (72) · R6 2263321 (52) · R1 2263373 (165) · R2 2264160 (68) ·
**D1 2311794 (26)** · **D2 2312557 (65)** · **D3 2313053 (42)** · R5 2317031 (62) · R8 2347821 / 2347859 (50) · **D4 2353722 /
2353760 (50)** · hook 2368820 / 2368858 (50). Measured (`overlap_dpatch{7,8}.py`, both players): 13 intervals disjoint; no
replacement contains any anchor, its own included; all 6 orders of R1–R5, R6–R8, D1–D4 give identical bytes; every anchor 0
times after, every replacement once.

### 6.2 Subsystems (files outside `live_runtime.py` that change: `scripts/dissolve_probe.py` (new), `scripts/managed_obs_qualify.py`, their tests, docs)

| Subsystem | Interaction | Change / re-run |
|---|---|---|
| R1–R8 | disjoint bytes; GL renderer | composition test |
| G2 GL replay | WebGL only; a movie G2 is drawing at a transition start is not a visible `<video>` and keeps today's look | none; `EXPECTED_STATS` move only with an independent diagnosis |
| Continuity core (main) | D4/D3 touch no `<video>`; `displayScene`'s detach reaches `stash`/`tryRemount` as today. P2 2→3: nothing main paints is visible. P2 slide 4 → end: the bridge paints at full strength (§1.4) | **Q6 default (b): no change in this patch**; `m-bridge` reports the residual (§9.1); under Q6(a), W5 (§11) |
| **S2** (`d88584eb`) | D4 snapshots whatever S2 shows as slide 2's movie and the copy fades; S2 then holds the decoder at full strength over the fade; S2 carries main's bridge | **S2's core stops painting its hold and the bridge (`keepAtSlot`) when the outgoing Dissolve/cut starts**, leaving the holder to own the fade, with fresh-decoder restarts intact; S2 takes this after merging `main` and makes `m-bridge` blocking |
| `managed_obs_qualify.py` | `mmo-cef` crosses the dissolve (`:611` → `mm_opacity_probe.drive`, `PLAN` has `d23`); `make_export` (`:299`) copies the grey-bug `html-player` PDFs | `--arm dissolve` (DX-2) on the shared resolver; re-run `mmo-cef` |
| `mm_opacity_probe.py`, `mm_handback_probe.py` | cross 2→3 to reach 3→4; score GL frames | re-run |
| `p2_recovery_html_adversarial.py` | the 2→3 movie ROI now shows the frozen counter (square redrawn) fading instead of the baked poster; `deliberateRestart2to3` and bridge-off timing read decoder identity/rVFC after the restart | re-run every arm; any moved finding is root-caused (§13) |
| `run_gates.sh` | pins no player sha | no edit; re-run full tier from a fresh pinned worktree |

## 7. Browser support

`plus-lighter`: Chrome 100 (ChromeStatus 5677338286096384); CSS Compositing 2; CSS Transforms 2 §7.1. `checkVisibility`
options: Chrome 121. OBS 32.2.2 bundles CEF 127: availability only (compositor and `drawImage` tone path: DX-2). Headless:
Chrome 154.0.8037.59, ANGLE Metal; software compositing via `--disable-gpu`.

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`)

Builders `dpatch3.py` → `dpatch8.py` (rev 5: `dpatch7.py` = Q7(a), `dpatch8.py` = Q7(b)); drivers `proto3.py` → `proto6.py`
(one headless Chrome per arm; alpha PNG, texture readback, rAF/rVFC log; `p2cut` = P2 2→3 in Keynote's cut shape, in memory);
analysis `analyze_full.py`, `f3analyze.py`, `f1analyze.py`, `f3model2.py`, `curve.py`, `matched.py`; Node `overlap_dpatch{7,8}.py`,
`node_ids.py`, `node_r6_test_r8.py`, `node_r7_near.py`, `node_f3_r8_test.py`; `bake/bake.py`.

**Node, real extracted code, both players, both Q7 variants.** Ids pre-order on the real `VB` classes. All 133 transitions
on disk and in the committed fixtures: 46 Dissolves copied (kind `dissolve`, two rules naming exactly the ids `VB` then
allocated); 8 cuts copied (kind `cut`, incoming hidden, mirror true→false, no rule); 79 stock, no rule; 0 mutations. 21
Dissolve and 10 cut near-misses (100 ms; fill `removed`/`forwards`; `beginTime` 0.5; a timing function; `timeOffset`;
`repeatCount`; autoreverse; swapped; `opacity`) stay stock; five construction failures build the stock tree with no rule on a
built node. **F3 stub table, 47 rows** (scratch `node_f3_r8_test.py`): attached at the computed geometry: success, uniform
scale, 2560×1440 and letterboxed stage (identical holders), letterboxed video, clipping panel, real cut (on `layer<out>`);
nothing attached: Dissolve without wrapper, throwing append; skipped: every §3.2 rule's violation incl. reflected, non-uniform,
off-centre, padded, rounded/one-axis clip, clip-path, mask, sparse (one pixel α 254) and edge (α 0) transparency, earlier
z-indexed cover, `div` with background, `img`; ignored: non-intersecting, behind, unpainted `div`; canvas foreground: (a)
skipped, (b) redrawn at α 1 / 0.2947 / 0.5 at the mapped rect, skipped when static, rotated, clipped, blended, z-indexed or
sharing a translucent group; overlapping videos → the later only. The video proxy records **no** write or other call.

| Arm (bytes; 1-min load at start) | Mid frames | Max residual, full res (LSB) | Overlap α min | Complement | Notes |
|---|---|---|---|---|---|
| `p2-t-patch` (rev 3; 3.39) / `p2-t-noblend` KB (3.17) / `p2-t-stock` (2.61) | 6 / 6 / 8 | 1.3 / 64.0 / 206.4 | 255 / 191 / 255 | 0 / 0 / 254 | patch: one `startTime`; in − ease ≤ 1e-6; computed styles on the right nodes |
| `k17-t-patch` DSK 5→6 (rev 2; 3.57) / stock (4.23, exploratory) | 6 / 6 | 1.5 / 204.5 | 255 | 0 / 254 | |
| `p2-t-patch-sw` `--disable-gpu` (rev 1; 4.98, exploratory) | 4 | 2.7 | 254 | 1 | |
| `p2-o-stock` / `p2-o-patch` opaque-texture (rev 2; 3.27 / 3.14) | 8 / 8 | 0.7 / 1.2 | 255 | n/a | matched on/off ≤ 1.51 |
| `p2cut-t-stock` / `p2cut-t-patch` (rev 4; 3.34 / 3.33) | – | – | – | – | stock **both slides**: 2 of 27 rAFs, 1 of 47 screencast frames; patch 0 of 44, 0 of 38 |
| `p2bin-t-patchdbg` freeze at D3 (3.97; 2.46, 4.48 exploratory) | – | – | – | – | **no snapshot**: no `<video>` left at `renderEffects` → D4 |
| `p2bin-t-patchdbg` freeze at D4 (rev 4 admission; 3.51) | 11 | 1.7 vs a screenshot reference | 255 | – | index 56 = last rVFC-presented 56 in every screenshot with α ≥ 128 (raw decode); live mid-grey 139 → frozen 128 |

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
| Cut: no union frame | `cut-on` | `cut-off` |
| Frozen frame (index, constancy) | `m-paused` (frame known in advance) | `m-off` (baked frame) |
| Frozen region fades | `m-on` | `m-hold` (full-strength copy) |
| No independent overlay | `m-on` | `m-bridge-off` (stock twin) |

### 9.0 Q0b — step 0 (scratch, before W1; needs the browser: waits for "free now")

Done (§8): cross-fade, KB, opaque-texture controls, matched progress, cut (one take per arm), rev-4 freeze. Pending, each with
DX-1 criteria; a miss stops the plan for re-planning, never a threshold change:
1. **Stock P2 4→end** (P2 `html-player`, continuity on; `off` and `on`): DOM + pixels confirm §1.4's bridge behaviour.
2. **Engagement on the real DOM** (debug build logging each video's verdict and failed rule): P2 and `p2-binary` slide 2 →
   admitted with one redrawn canvas `3F22E494` at α 0.2947 (Q7(b)) / skipped (a); any other failed rule → re-plan.
3. **Reconstructed reference:** texture + holder (A2) vs the first transition frame, full resolution, every pixel incl.
   geometry and redraw-edge maxima ≤ τ.
4. **Cost:** take time per admitted movie (`drawImage` + full-region `getImageData`) reported; > 50 ms stops for re-planning.
5. **Host-path geometry** (letterboxed window, 2560×1440, DSF 2) and **visual cases** (foreground as exported and opaque via
   in-memory live opacity 1; an in-memory second, overlapping movie) on `p2-binary`: holder residual ≤ τ, no foreground lost.
6. Cut ×3, freeze ×3 incl. `m-paused`, `m-hold`, `m-off`; `screen-on`/`-off`; D2 `on`; CvC; `--disable-gpu` and DSK on
   current bytes; `delay-on`/`-off`; lifecycle dry run; F3 and its tone step inside CEF (DX-2).

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver (W2; reused by W3; read-only).** Stock `index.html`, player and slide JSON from `html-unmodified`; PDFs/`.pdfp`
  from a fresh scratch strip (715cb3f1's stripper); movies mapped to decodable copies (P2: `html-player` H.264; DX-M:
  `p2-binary`). In-memory overrides only where a row says so. Provenance (source, sha, override) and continuity state
  (enabled, plan qualified, G2) recorded; every required movie must decode.
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1, own port (never 9222); `LiveOutputHost` attach (alpha) or
  headless launch mode with the host's screenshots (screen).
- **Instrument.** Innermost hook from the first rAF with the transition DOM: each leaf's effective opacity (also before any
  animation attaches), every transition animation (`currentTime`, `startTime`, value), scene/hash; every `<video>` tagged
  (`WeakMap` id) with rect, effective opacity, transition-DOM membership, rVFC records and detach time; at that first rAF the
  textures, every holder (`toDataURL`, slide-px geometry) and the computed blend/isolation chain. Alpha PNG screenshots from
  0.35 s before the advance to T + 0.6 s; cut arms add a per-frame screencast.
- **Scorer (pure, every pixel of the mask; reused by DX-2).** A = outgoing texture with the holders composited, B = incoming,
  premultiplied; per admitted screenshot e by least squares on the texture group outside every media rect + 2 px; residual
  `|F − ((1−e)·A + e·B)|` there. Screen arms: RGB vs the cross-fade over black. **Media (DX-M):** each holder binds to the one
  tagged decoder whose admitted region maps to its rect (± 1 px; none or several → INCONCLUSIVE); its reference is that
  decoder's last rVFC record before its detach (D4 runs just before it). The binary strip is decoded from the holder and from
  `Ô = (F − e·B)/(1 − e)` on admitted frames with e ≤ 0.8 (error × ≤ 5), ≥ 3 of them with pairwise Δe ≥ 0.1; bits under
  foreground α > 0.5 excluded. Never from raw screenshots: incoming content under the strip changes `F`, not `Ô`.
- **Capture integrity (any violation INCONCLUSIVE):** texture ids equal the export JSON's; hash before/after = the transition's
  slides; screenshot size and page mode as the arm states; finite, non-empty measurements; served digest as stated; fade arms
  ≥ 6 mid frames (0.05 < e < 0.95, transition DOM present); delay arms ≥ 2 screenshots and rAF coverage in the window; cut arms
  rAF coverage from DOM insertion to 3 frames after the cut and a screencast frame inside; media arms the evidence below;
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
| Frozen frame | per bound holder: decoded index = its reference frame (offset measured 0, §8), and `Ô` decodes to it on every admitted frame |
| Frozen region | `Ô` in the movie region constant over the admitted frames (spread ≤ τ/(1 − e)); a moving movie or full-strength copy drifts; the baked frame stays constant but fails the index |
| No independent overlay | in every rAF of the fade no tagged `<video>` outside the transition DOM with effective opacity > 0 meets the outgoing movie rect, and `Ô` there does not drift |
| Tone step | mid-grey (Y = 126) frozen minus last live: −11 ± 1 (measured), black/white 0 ± 1; report-only (Q5) |

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
| `m-on` | `p2-binary` 2→3 through `LiveOutputHost` (continuity on) | out-only, in-only | frozen frame, frozen region, model, no independent overlay → PASS | as `on` + one holder | pinned `on` |
| `m-paused` | as `m-on`, the movie paused on a known frame before the advance | as `m-on` | frozen index = that frame exactly → PASS | as `m-on` | pinned `on` |
| `m-off` | as `m-on`, patch off | out-only, in-only | frozen frame → FAIL | none | pinned `off` |
| `m-hold` | as `m-on`; one counted splice appends the holder to the container instead of the wrapper | as `m-on` | frozen region → FAIL (`Ô` drifts with 1/(1 − e)) | as `on` | base + splice |
| `m-bridge-off` / `m-bridge` | P2 `html-player` (measured plan), slide 4 → end, continuity on | out-only | no independent overlay → FAIL / Q6(b): reported, FAIL as `-off` (known residual, non-blocking here; blocking PASS in S2's round or under Q6(a)) | none / as `on` | `off` / `on` |
| `on-sw` | P2, `--disable-gpu` | as `on` | all → PASS | as `on` | `on` |

**Media evidence** (missing → INCONCLUSIVE). `m-on`, `m-paused`, `m-hold`: one D4 holder bound to its decoder, a reference
rVFC record, ≥ 3 demixable frames. `m-off`: served digest = pinned `off`; live playback before the advance (≥ 10 presented
frames, media time advancing); the transition identified by texture ids and its outgoing texture captured; movie-region pixels
on ≥ 3 demixable frames; **no holder by design** (a holder → INCONCLUSIVE); its FAIL: `Ô` does not decode to the reference
index. `m-bridge(-off)`: the bridged decoder tagged, its rVFC through the fade, rAF coverage of the fade.

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

One launch through the managed bridge with DX-1's hook, resolver, integrity rules and scorer (W2), the advance and a
`GetSourceScreenshot` (PNG, alpha) burst. Sessions `on`, `on2`, `off`, `noblend`, `opaque-off`, `opaque-on`, `cut-off`, `cut-on`
(P2 / `p2cut`), `m-on`, `m-paused`, `m-off`, `m-hold` (`p2-binary`); each media session but `m-off` shows a bound D4 holder;
each records continuity, G2 state and served digest; cut sessions need rAF coverage from DOM insertion to 3 frames after the cut
and ≥ 1 source screenshot inside (no screencast in CEF). Controls are read before the candidate counts. **Calibration fixed
before capture, applied without clamping:** n = max mid-frame residual of `opaque-off`; τ_CEF = max(4, ⌈n⌉ + 1); complement 2 +
⌈n⌉; no dip 252 − ⌈n⌉; caps τ_CEF ≤ 8, complement ≤ 6, no dip ≥ 248, so n > 4 is INCONCLUSIVE. CEF tone step measured on `m-on`,
report-only (Q5). Refuses while `OBED_LIVE_MM_OPACITY` is set.

### 9.3 DX-3 owner check in real OBS

- **Pre-check:** DX-1's texture classifier on the chosen production transition: fill-less outgoing and ≥ 2 000 px in-only →
  affected, else a regression control. Movie: an H.264 slide that plays live in OBS, preferably with foreground over it.
- **Where:** Take output (Keyer): stripped P2 2→3, the pre-checked transition, an H.264 movie slide several seconds in.
- **Pass:** slide 3 fades in from nothing over the whole fade; slide 2 keeps its colours while fading; no darker or more
  transparent moment where both overlap; the movie stops on its current frame and fades out with slide 2, foreground intact
  (no jump back to its opening frame); no jump at the hand-off. A brightness step the owner notices at the freeze reopens Q5.
  **Null** (affected transitions only): `OBED_LIVE_MM_OPACITY=off` shows the pop-in and the jump.
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
   pre-order ids; every committed `tests/fixtures/live_continuity` transition (copied with its kind, or stock, as §8); the 21
   Dissolve and 10 cut near-misses; the five construction failures; the 47 F3 stub rows of §8 (take/attach count and target,
   holder geometry, redraw calls and alpha, no write or call on the video).
4. **New `tests/test_dissolve_probe.py`, one parametrized function** (synthetic numpy): rev 3's rows (cross-fade, pop-in, dip,
   ±1 LSB, masked video, curve, monotone, hand-off, integrity → INCONCLUSIVE, INCONCLUSIVE `off` fails the gate) plus: union
   frame FAIL / clean cut PASS; strip decode (valid, parity error → None); frozen strip under overlapping incoming content (`Ô`
   PASS where raw decoding flips); two simultaneous decoders (binding picks the match; ambiguous → INCONCLUSIVE); index ≠
   reference FAIL; `Ô` drifting (moving movie, full-strength copy) FAIL; < 3 demixable frames → INCONCLUSIVE; `m-off` complete →
   FAIL, without playback evidence or with a holder → INCONCLUSIVE; independent overlay present FAIL / absent PASS.
5. **`test_managed_obs_qualify.py`:** the existing env-refusal test parametrized over the new arm; the calibration test
   (n = 4 / 4 + ε).

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | D1–D4 (Q7 variant as answered); docstrings; re-pins; tests 1–3 |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | resolver, DX-1 incl. cut, DX-M (with `m-bridge`) and lifecycle; test 4 |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | `--arm dissolve` incl. cut and media sessions, on W2's resolver/driver/scorer; test 5 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, plan status | README fallback line; one SKILL sentence; S2 handover (end hold and bridge at the outgoing transition start; `m-bridge` blocking) |
| W5 | only if Q6 = (a): `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py` | `keepAtSlot`/`slotLive` stop painting at the outgoing transition start; re-pin `PINNED_CORE_SHA256` (`:39`); host gates, carry-cover, P2 re-run |

Order: W0 → Q0b → W1 ∥ W2 (∥ W5) → W3 → gates → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-2,
`mmo-cef`, DX-3 (owner session) → one PR to `main`. Never merge.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and construction failure; nothing mutates export JSON. (3) Rule ids = allocated ids; abandoned ids on partial insert. (4) One
`applyCssAnimation` pass; cut copied only for the exported timing. (5) D4/D3 add-only, per movie, never touch a `<video>`;
every admission miss or failure leaves the baked frame; attach by kind, never the Dissolve leaf. (6) `off` = today's bytes.
(7) Thresholds measured or by formula; PASS and FAIL controls for every blocking check.

## 12. Owner decisions (all 2026-10-11, in chat)

- **Target (movies):** "in Keynote the vid stops playing and dissolves out" — freeze on the current frame, fade with slide 2.
1. **Switch: fold into `mm_opacity`** (decided). 2. **Scope: every output** (decided).
3. **F1 (`none` cut) in this patch; F2 a separate follow-up** with an owner Q-deck (decided, final). 4. **F3 in this patch**
   (decided; re-confirmed after rev 4: splitting it out declined).

5. **Mid-tone step at the freeze. Provisional default (a) — owner to confirm.** The snapshot is the exact frame but ~11/255
   darker in mid-tones than the live movie a frame earlier. (a) **Recommended: accept** it as a known limit, like G2's
   takeover step (README: "midtones may shift slightly"); it avoids adopting decoder ownership. Under (a) the tone rows
   (headless −11 ± 1 at Y = 126; the CEF value) stay report-only, and a step the owner notices in DX-3 reopens this question
   before merge. (b) Freeze the live `<video>` (move and pause it): tone continuity is a prediction to measure, not a
   guarantee; main's and S2's cores must skip a frozen element (`stash` re-plays and remounts it); F3 and its gates are
   re-planned before work starts. Either way Q6's overlay changes (S2's hold and bridge) are still needed.
6. **Main's bridged movie over P2 slide 4's terminal fade. Provisional default (b) — owner to confirm.** (a) Change main's core
   in this patch (W5): stop painting the bridged decoder when its outgoing Dissolve/cut begins; costs a core re-pin,
   host-gate/carry-cover/P2 re-runs and a certain conflict with S2, which rewrites the same functions. (b) **Recommended:**
   player-only on `main`; `m-bridge` reports the residual (stock = patched; continuity-qualified P2 plans only, so no real
   deck reaches it on `main`); S2 ends its hold and the bridge at the outgoing transition start and makes `m-bridge` blocking.
7. **Foreground over a frozen movie. Provisional default (b) — owner to confirm.** Both known movie decks have foreground
   over the movie (§1.4). (a) Skip any movie with later foreground: simplest, but F3 then engages on neither P2 nor DSK-style
   slides, and DX-M needs an in-memory override hiding P2's square. (b) **Recommended:** also redraw overlying plain canvases
   into the snapshot (§3.2): +1.1 KB in D1, 9 more stub rows, DX-M on the unmodified deck; all else still skips. Only (b)
   makes decision 4 visible on the owner's decks.

## 13. Risks and out of scope

CEF compositor and `drawImage` tone path unproven until DX-2. Id prediction relies on `VB`'s pre-order allocation (proved;
re-checked every run). Rev 5's admission is Node-proven only: a real-DOM rule miss leaves F3 inert (Q0b 2); take cost (Q0b 4).
Software compositing cost; production transparency (DX-3 pre-check); P2's 2→3 findings now see a frozen counter; F3 residuals
and the bridge/hold (Q6); F1 on one take per arm (Q0b repeats). Out of scope: F2, GL effects, Keynote-app comparison (hands
off Keynote), S2's core change (S2's PR).

## 14. Critique log

Raw rounds: `.agents/reviews/dissolve-crossfade/plan-astra-r{1,2,3}.md` (+ `.prompt.md`). **r1** (12 findings, rev 1) and
**r2** (7 + the owner's movie answer, rev 2): all folded, rows in `4ffcd8ad` §14; r3 closed r2-1, r2-4 to r2-7, and r2-2/r2-3
complete with r3 #1–3, #7. **rev 4**: owner decisions 1–4; F1 added; F3 at D4/D3; Q5.

### r3 — GPT-6 Astra high (Codex), on rev 4 `4ffcd8ad`

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / new | Folded. Stock P2 4→end established by static read (bridge at full strength; stock = patched; P2-measured plans only); "no change to main" removed; `m-bridge(-off)` with a no-independent-overlay check; S2 ends hold and bridge; a main-core change is owner question 6 (default (b); W5 under (a)). | §1.4, §5, §6.2, §9.1, §11, §12 |
| 2 | major / new | Folded: decoder binding by tag + geometry, reference = its last rVFC before detach; `Ô` demixing, e ≤ 0.8, ≥ 3 spread frames, e fitted outside media rects; A2 full-resolution maxima in Q0b; scorer rows for overlap and two decoders. | §9.0, §9.1, §10 |
| 3 | major / closed | Folded: per-arm media evidence; `m-off` holder absent by design, FAIL from complete evidence; missing holder in `m-on`/`m-paused` stays INCONCLUSIVE; scorer rows. | §9.1, §10 |
| 4 | major / new | Folded: occlusion and paint-order admission; later plain canvases redrawn (Q7 default) or the movie skipped; overlapping movies; stub rows; Q0b visual cases. Evidence: skipping alone is inert on both known movie decks → owner question 7. | §1.4, §3.2, §8, §9.0, §12 |
| 5 | major / edge | Folded: positive uniform scale, centred `object-position`, zero padding/border, two-axis zero-radius clips, no clip-path/mask/filter/blend/z-index; 2560×1440, letterbox, reflected, non-uniform rows; host-path geometry in Q0b. | §3.2, §8, §9.0 |
| 6 | major / edge | Folded: alpha 255 at every source pixel of the attached region (natural resolution); sparse and edge rows; cost in Q0b. | §3.2, §8, §9.0 |
| 7 | major / closed | Folded: attach by engaged kind; missing Dissolve wrapper discards; one fragment append; real cut row; missing-wrapper and append-failure rows. | §3.1, §3.2, §8 |
| 8 | major / closed | Folded: DX-2 adds `cut-off`/`cut-on`, `m-paused`, `m-hold`; a bound D4 holder per media session; continuity/G2 state recorded; cut evidence contract. | §9.2 |
| 9 | minor / edge | Folded: `hidden` = linear opacity keyframes stated; cut copied only for the exported timing (1 ms, `both`, no delay/curve/offset/repeat/autoreverse); 10 near-misses. | §1.1, §1.5, §2, §3.2, §8 |
| 10 | minor / new | Folded: Q5 rewritten (avoids decoder adoption; Q6/S2 changes needed either way; live-element tone a prediction; acceptance under (a) and (b)). | §12 |
| 11 | nit / edge | Folded: R8, D4 and the hook move by 38. | header |
