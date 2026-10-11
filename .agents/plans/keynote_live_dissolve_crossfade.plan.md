# Dissolve over fill-less slides: make Keynote's slide Dissolve a true cross-fade

**DRAFT rev 3**, 2026-10-11, for owner review. Rev 1: Opus planner (`8e572864`). Critique r1 and r2: GPT-6 Astra high via
Codex (not Opus; owner 2026-10-11), 12 + 7 findings, all folded (§14). Rev 2 (`cd289a05`) and rev 3: Opus planner. Rev 3 also
folds the owner's answer on movies (§0, §12). Plan only: no product code, no commits, no OBS, no Keynote.
Base: `main` @ `1589d096` (branch `claude/keynote-live-dissolve-crossfade-plan`).
Players: stock `main.js` `e9b2fad4…` and `17c0c938…` (`live_runtime.SUPPORTED_PLAYERS`). Every offset is a **byte** offset,
read on both players; they are equal below 2331091 (17c0c938 = e9b2fad4 + two 19-byte `,isEvalSupported:!1` at 17c0c938
offsets 2331091 and 2331362: +19 between them, +38 after; only R8 and the hook `_ANCHOR` move). Evidence: main checkout
`output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored). Planning scratch (scripts, Node checks and result JSON;
frames, patched players and strip copies not kept): its `plan-2026-10-11/{planner,rootcause,coord}/`; "scratch `x`" below
means `plan-2026-10-11/planner/x`. Raw critique rounds: `.agents/reviews/dissolve-crossfade/`.
Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, switch, pins), `keynote_live_handback_geometry.plan.md` (R6–R8, decision
2a "fold into the existing switch"), `keynote_live_paint_oracle.plan.md` (oracle stays stock).

## 0. Summary

- **Root cause (player, not host).** Keynote's export encodes a slide Dissolve as two flattened full-slide textures: the
  incoming slide at the bottom with **no animation**, the outgoing slide on top with `opacity 1→0` (EaseInEaseOut, 1.5 s on
  P2). Over an opaque outgoing texture that is already an exact cross-fade; where the outgoing texture is transparent the
  incoming slide shows at full strength from the first frame (pop-in). Keynote's own exports hide it with a full-slide black
  fill. The trigger is that fill's absence, not the transparent page (§1.3).
- **Fix: two count-checked, sha-pinned, in-memory replacements (D1, D2) appended to `_MM_OPACITY_REPLACEMENTS`.** For a
  transition whose tree is exactly the Dissolve shape, before the player builds anything, one method commits the blend as two
  stylesheet rules keyed by the layer ids the player is about to allocate (`#layer<c>{isolation:isolate}`,
  `#layer<in>,#layer<out>{mix-blend-mode:plus-lighter}`), reads them back, and only then returns a **copy** of the tree whose
  incoming leaf starts at opacity 0 with the mirror animation `0→1`. The player then builds, draws and animates with its own
  code; the DOM is born blended. Any failure happens before anything is built and yields the stock transition. There is no
  post-draw code. Result: premultiplied `(1−e)·P_out + e·P_in`.
- **Measured** (headless Chrome 154, transparent page, correctly stripped PDFs, full-resolution scoring, §8). P2 2→3 (rev 3
  bytes, e9b2fad4): residual ≤ 1.3 LSB, overlap α 255, incoming α = 255 − outgoing α, one shared `startTime`,
  `in = ease-in-out(t/1.5 s) ± 1e-6`. DSK deck 5→6 on 17c0c938 (rev 2 bytes, same CSS result): ≤ 1.5 LSB. Nulls pop in
  (residual 205–206). KB (mirror fade without the blend, rev 3): overlap α 191 at e ≈ 0.5, as predicted. Opaque-texture
  controls: stock ≤ 0.7, patched ≤ 1.2, on/off at matched progress ≤ 1.51 LSB.
- **Movies (owner, 2026-10-11): "in Keynote the vid stops playing and dissolves out."** Target: the outgoing movie freezes on
  its current frame and fades with slide 2. Today the player deletes the playing `<video>` at the dissolve start and the
  export's texture shows a **baked opening frame** instead (measured: best match 0.13–0.23 s into the clip; the jump back grows
  to MAD 36–70/255 for an advance ≥ 5 s into playback, §1.4). This patch does not change that; where the freeze lives is
  decision 4 (recommended: a separate follow-up on main). The texture cross-fade is independent of that answer.
- **Scope** every output; only `apple:dissolve`. **Switch** recommended: the existing `mm_opacity` switch. `RUNTIME_VERSION`
  stays 2; `off` stays today's bytes.

## 1. Facts (code-read on both players; every anchor count-checked)

### 1.1 How the player draws a slide transition

| Step | Where (byte, both players unless split) | What |
|---|---|---|
| GL vs CSS | `jC` @2368216 / @2368254; routing `qC&&-1!==jC.indexOf(C.name)` @2312807 (`PB.renderEffects`, slide transitions) and @2314108 (`PB.renderEffect`, per-object builds) | `apple:dissolve` is not in `jC`, so the CSS renderer `NB` (@2292342) draws it. |
| Build | `PB.renderEffects` @2311803; `const A=new VB(C.baseLayer,…)` @2312557 … `this.cssRenderer.draw(a),a.removeChild(w)}` @2313053 | `yB` keeps the export's `baseLayer` **by reference** (@2270532). `VB`'s constructor allocates `layerId=TB,TB+=1` (`let TB=0` @2270526, same module scope as `PB`) and recurses into sublayers after its own id, so ids are **pre-order**: root, container, incoming, outgoing = TB … TB+3 (proved on the real classes in Node, §8). `WB` creates each animated layer's keyframe rule in the animation manager's stylesheet during construction. `NB.draw` builds `layer<id>` divs (+ `layer<id>-opacity` wrappers) and the old slide's live DOM, including any playing `<video>`, is removed in the same task. |
| Keyframes | `WB` @2271556; `EaseInEaseOut` → `ease-in-out` @2282229; `createAnimation` @1953007 inserts at index 0 of the animation manager's own `<style media="screen">` | |
| Animate | `PB.playCurrentScene` @2356281 / @2356319: `renderEffects()` then `setTimeout(()=>{…animateEffects…},1e3*g)` (`},1e3*g)` @2357455 / @2357493) | Render and animate are **separate tasks**: a frame can paint the transition DOM before any animation (evidence FIXT-1 frame 30; the verifier saw the incoming at opacity 1 in one such frame). `applyCssAnimation` @2303763 starts every layer's animation in one loop. |
| Cleanup | `displayScene` @2354643 / @2354681 → `deleteAllAnimations()` @1953106 (deletes **every** rule of that stylesheet) + `removeEvent` @2291872 | Runs at the next scene or any go-to. At the end of the show (`currentSceneDidComplete` @2357464 / @2357502, no next scene) it does not run: the held endpoint keeps its DOM and rules until navigation. |

### 1.2 The export data (every transition on disk)

Census over the 25 export roots under the main checkout's `output/fixtures` (scratch `census.py`): **42 `apple:dissolve`**, all
root → one container (no texture, animation or `objectID`) → two textured leaves (no `objectID`, no video flags, identity
geometry): `[0]` incoming, no animation; `[1]` outgoing, one `opacity` 1→0, `EaseInEaseOut`, `fillMode both`, 1.5 s or 1.0 s
(D2). Also 8 `none` cuts (D1–D6), 67 Magic Moves (GL), 382 per-object CSS builds (48 `apple:dissolve character`, 167 movie
start, 167 `renderMovie`). P2 2→3 = slide `0C652BEB` event 3 (incoming `5F820A…` page 11, outgoing `774F55…` page 10).
**D2 is the only D deck with a dissolve** (2→3, 1.0 s); its textures cover the same opaque area (0 px incoming-only), so it
tests overlap and the curve but cannot show a pop-in. The pop-in deck on 17c0c938 is `minimal-alpha-dsk-17c0c938`: all four
dissolves pop in once stripped (verifier r3); 5→6 (into the DSK clip slide) is measured here.

### 1.3 What the live presenter serves

`html_preview.export_html` (`export … as HTML`, no properties) is the only export path, served unmodified in screen mode
(black page, `#obed-output-black` hide) and keyer mode (alpha page, `#body` opacity hide; `live_host.py:418–436`). The product
never strips (715cb3f1). On the fixtures' unmodified exports both dissolve textures carry the black fill, so stock is exact.
**The trigger is a fill-less outgoing texture, not the page**: RAWT-1 (Keynote's PDFs, transparent page) has no pop-in;
STRIPT-1 and the verifier's NULLSTRIP (stripped PDFs on the **opaque black** page) pop in. Fill-less decks (DSK decks use the
wall deck's transparent layout, README :21; DSK clip slides are forced to dissolve, `dsk_assemble.py:2958–2968`, `:4204–4207`)
are the real case; which production exports lack the fill is unverified on disk (DX-3 pre-check).

### 1.4 Movies in a dissolve (owner input, measured)

The export bakes each slide's movies into the dissolve textures as stills. DSK deck 7→8 (out of the clip slide; ProRes clips,
which Chrome cannot decode, so measured offline: Ghostscript render of the outgoing texture, PDF page 16, against every
ffmpeg-decoded clip frame over the visible panel; scratch `bake/bake.py`):

| Clip (panel) | Best-matching frame | Frame 0 vs best | MAD of the live frame vs the baked one if advanced at 0.5 / 1 / 2 / 5 / 10 s | Same-content floor |
|---|---|---|---|---|
| `clip-10-1000001` (Children's Church) | 7 (0.23 s) | +1.0 | 10 / 19 / 29 / 36 / 41 | ≈ 21 |
| `clip-10-1000002` (Sunday Service) | 4 (0.13 s) | +1.4 | 20 / 32 / 44 / 70 / 68 | ≈ 22 |

So the export bakes the clip's opening (poster) frame, and a dissolve started more than ~1 s into playback jumps back to it,
then fades. Keynote instead freezes the current frame (owner). P2 cannot judge this (its posters are the original clip, its
movies are counter replacements). The floor is the crop-alignment mismatch of the best frame (MAD 21–22), so differences below
it are not content.

## 2. Arithmetic (premultiplied RGBA, 0..1; e = eased progress, outgoing opacity o = 1 − e)

- **Stock:** `C = o·P_out + (1 − o·α_out)·P_in`: the cross-fade where `α_out = 1`, `P_in` from the first frame where `α_out = 0`.
- **Plain opposite fades (rejected):** where both are opaque `α = 1 − e + e²` = 0.75 at e = 0.5 (the dip).
- **Fix:** in the isolated container group, incoming (opacity e, `plus-lighter` onto zero) = `e·P_in`; outgoing (opacity 1 − e,
  `plus-lighter`: `co = min(1, αs·Cs + αb·Cb)`, `αo = min(1, αs + αb)`) gives `G = (1−e)·P_out + e·P_in`,
  `α_G = (1−e)·α_out + e·α_in`, never clamped. Over black, `G` = the two slides on black, cross-faded.
- **Preconditions** (enforced by the predicate, §3.2): two texture leaves; no video/poster layer; identity 2D geometry (the
  grouping properties flatten `transform-style`, CSS Transforms 2 §7.1, which moves no pixel only for identity transforms).
- **Endpoints exact:** e = 0 → `P_out`; e = 1 (`fill both`) → `P_in`.
- **8-bit:** residual 1.3–1.5 LSB GPU, 2.7 software (§8); τ = 4.
- **Opaque textures:** algebraically identical to stock; measured on/off ≤ 1.51 LSB at matched progress (report-only bound 2).
- **Isolation:** the blend's backdrop is the container group only (stacking context via `-webkit-transform`, plus `isolate`).
  It never mixes with the page, the host hide, the GL canvas or anything the continuity core inserts. It does not make an
  independently painted overlay (S2's held decoder) fade; that is decision 4's subject.

## 3. The patch

### 3.1 Exact replacements (R9–R10 of `_MM_OPACITY_REPLACEMENTS`; anchor `count == 1` before, `0` after; replacement `count == 1` after)

| # | Where (byte, length; both players) | Before | After |
|---|---|---|---|
| D1 (R9) | end of `processEffects` / head of `renderEffects` @2311794 (26 B) | `return B}renderEffects(A){` | `return B}` + `__obedDissolveLayer(C){…}` + `renderEffects(A){` |
| D2 (R10) | base-layer `VB` @2312557 (65 B) | `const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});` | `const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});` |

The method (scratch `dpatch3.py`; `node --check` passes on both patched players):

```
__obedDissolveLayer(C){var b=C.baseLayer,n=0;try{var K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,f=function(l,c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};if("transition"!==C.type||"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||[]).length||(i.animations||[]).length||"opacity"!==x.property||x.keyTimes||x.path||x.animations||1!==x.from.scalar||0!==x.to.scalar)return b;var S=UC.animationManager.styleSheet,L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0;return Object.assign({},b,{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,{opacity:0}),animations:[Object.assign({},x,{from:{scalar:0},to:{scalar:1}})]}),o]})]})}catch(E){return n&&(TB+=4),b}}
```

### 3.2 How it works

- **Predicate (faithful or unchanged).** Stock unless: a `transition` named `apple:dissolve`; exactly root → one container →
  two textured leaves without sublayers; root and container without texture or animation; container and leaves without
  `objectID`, `isVideoLayer`, `isWebVideoPosterLayer` or 3D `transform`, with identity `affineTransform`, rotation 0, scale 1,
  opacity 1, not hidden; leaves with identity `sublayerTransform` (the container's perspective term acts only on identity
  children); incoming without animation; outgoing with exactly one `opacity` animation `1→0` without `keyTimes`/`path`/group.
  Timing, curve, `fillMode`, `beginTime` and control points are copied, so the mirror runs through the same `WB` code.
- **Commit before construction.** Rules are inserted into the animation manager's stylesheet (where the player's own keyframes
  live) for ids TB+1 … TB+3 and read back through `CSSStyleRule.style` (a declaration the browser does not support is dropped,
  so it reads back empty). Only then is the copy returned; the very next statement is `new VB(copy)`, which allocates exactly
  those ids. The DOM `NB.draw` builds is therefore styled from its first style pass: no unblended frame, no mirrored fade
  without the blend.
- **One failure point, before anything is built.** Predicate miss, missing stylesheet, a throwing `insertRule`, or a dropped
  declaration → the export's own tree is returned. If a rule was already inserted, `TB += 4` abandons those ids, so the stock
  tree is built on fresh ids no rule targets. Orphan rules die with the next `deleteAllAnimations`. The player's own code then
  builds, draws and removes the old slide exactly as today. Nothing runs after `new VB`.
- **Copy, never mutate**: shallow copies along root → container → incoming; `UC.script.events` untouched, so replays repeat
  identically.
- **Incoming invisible from DOM insertion**: `initialState.opacity 0` makes `addNode` write `opacity:0`; `applyCssAnimation`
  later sets the layer to 1 with its wrapper at keyframe 0% (opacity 0) in the same task as the outgoing's start.
- **Cleanup is the player's**: the rules live in the stylesheet `displayScene` empties. At the end of the show they persist
  with the held endpoint until navigation, like the keyframes.
- New names carry `__obed` (0 occurrences in either stock player); strict-mode safe; reads `TB` and `UC` from the same module.

### 3.3 Alternatives rejected

Post-draw style install with rollback (rev 2: missing nodes and throwing setters cannot be made stock-safe after the DOM
exists, Astra r2-1); WAAPI on the incoming DOM (second clock); mirrored fade without the blend (the dip); per-frame 2D/WebGL
compositing; host-side CSS (ids are per-play); alpha-only patching (the trigger is the texture).

## 4. Switch, pins, report

- **Switch (decision 1, recommended a): fold into `mm_opacity`.** D1–D2 join `_MM_OPACITY_REPLACEMENTS`; `patch_player`,
  `patch_rendering` and every synthetic test player (all built from the tuple) pick them up. `mm_opacity=False` stays the
  hook-only bytes (`7cf00b56…` / `4f9fbffd…`). Docstrings say "rendering fidelity"; names and error text unchanged.
- **Pins:** `(on, off, rendering)` shape kept; `on` and `rendering` re-pinned for both players. No other literal sha in code.
- **Report** `output.mmOpacity = {mode, sha256}` unchanged in shape; **`RUNTIME_VERSION` stays 2**; preview inherits the
  patch (cache and `player_digest` stock); paint oracle stays stock; `web/live.py` unchanged.
- **1(b) cost** (separate `OBED_LIVE_DISSOLVE`): second tuple and kwarg; pins 4 + 2 per player (12 `(ANY,) * 3`
  monkeypatches in 6 test files); 6 synthetic builders; `output.dissolve`; three harness env refusals; README; P2 flag.

## 5. Scope

**Every output** (the trigger is the texture; on black-filled textures the fix is algebraically stock). **In scope:
`apple:dissolve` of the §1.2 shape** (42/42 on disk); unmeasured families stay stock by the predicate.

| Effect | On disk | Fill-less textures | Plan |
|---|---|---|---|
| `apple:dissolve` | 42 | pop-in | fixed here |
| movies inside a dissolve | every DSK clip slide | outgoing movie jumps to its baked opening frame, then fades (§1.4) | F3, decision 4 |
| `none` cut | 8 | the render→animate gap can paint both slides at full for one frame | F1 |
| per-object builds | 382 | ok: nothing relies on being covered | none |
| GL effects (`jC`) | 67 | not CSS | R1–R8 |
| other CSS transitions the player special-cases (`ca-swing`, `BLTSwoosh`, `ca-push`, `BLTFadeThruColor`, `apple-grid`, `BLTMosaicFlip`, `ca-revolve`, `3D-cube`, `doorway`, `KLNComet`, `BLTBlinds`), smart/action builds | 0 | unknown | F2: owner Q-deck, DX-1 classifier |

## 6. Interplay

### 6.1 Anchor map (byte offset, length; e9b2fad4 / 17c0c938)

R7 2190367 (36) · R3 2190440 (46) · R4 2192650 (72) · R6 2263321 (52) · R1 2263373 (165) · R2 2264160 (68) ·
**D1 2311794 (26)** · **D2 2312557 (65)** · R5 2317031 (62) · R8 2347821 / 2347859 (50) · hook 2368820 / 2368858 (50).
Measured (`overlap3.py`, both players): 11 intervals disjoint; no replacement contains any anchor, its own included; all 6
orders of R1–R5, R6–R8, D1–D2 give identical bytes; after patching every anchor occurs 0 times, every replacement once.

### 6.2 Subsystems

| Subsystem | Interaction | Change / re-run |
|---|---|---|
| R1–R8 | disjoint bytes; GL renderer | composition test |
| G2 GL replay | WebGL only; the dissolve issues no GL calls | none; `EXPECTED_STATS` move only with an independent diagnosis |
| Continuity core (main) | sets opacity on `<video>` only; no `<video>` visible during the dissolve (evidence LIVE/LIVEFIX) | DX-1 masks and reports visible videos |
| **S2** (`d88584eb`) | `live_continuity_js.py:758–763` holds a restarting decoder through the dissolve; `:1759–1777` remounts it in the stage at opacity 1; `:2158–2169` retires it when the fresh movie starts. It paints outside the group at full strength: neither the owner's freeze-and-fade nor this patch's fade applies to it. | decision 4; S2's integration round re-runs DX-1 (texture group) and, once F3 exists, F3's media gate |
| `managed_obs_qualify.py` | `mmo-cef` (`:611` → `mm_opacity_probe.drive`, `PLAN` has `d23`, `mm_opacity_probe.py:100–107`) crosses the dissolve; `make_export` (`:299`) copies the grey-bug `html-player` PDFs | `--arm dissolve` (DX-2) on the shared resolver; re-run `mmo-cef` with its matrix |
| `mm_opacity_probe.py`, `mm_handback_probe.py` | cross 2→3 to reach 3→4 | re-run |
| `p2_recovery_html_adversarial.py` | serves `patch_player(raw, mm_opacity=True)` in every arm (non-GL under `--disable-gpu`); 2→3 findings are decoder/counter based | re-run every arm (run_gates full) |
| `run_gates.sh` | pins no player sha | no edit (S2 rewrites it); re-run full tier from a fresh pinned worktree |

**S2 pick-up:** lands on `main` first; S2 merges `origin/main` (nearby S2 hunk only at `test_live_runtime.py:155`); 715cb3f1
is cherry-picked here (W0), an identical change.

## 7. Browser support

`plus-lighter`: Chrome 100 (ChromeStatus 5677338286096384; web.dev, March 2022); CSS Compositing 2 (`plus-lighter`
formulas; stacking contexts are isolated groups); CSS Transforms 2 §7.1 (grouping properties); Jake Archibald, "Cross-fading
any two DOM elements is currently impossible" (2021). OBS 32.2.2 bundles CEF 127 (`…branch-heads/6533`, framework
`Info.plist`): availability only; CEF's compositor is qualified by DX-2. Headless: Chrome 154.0.8037.59, ANGLE Metal;
software compositing via `--disable-gpu`.

## 8. Feasibility prototype (Q0; `plan-2026-10-11/planner/`)

Files: `dpatch3.py` (rev 3 D1–D2 + `noblend` splice), `proto3.py` (one fresh headless Chrome per arm, transparent PNG at full
scale, texture readback, rAF log), `analyze_full.py` (every pixel; rev 2's `analyze.py` subsampled 2×2, Astra r2-7),
`curve.py`, `matched.py`, `overlap3.py`, `node_ids.py`, `node_r3_test.py`, `node_r3_near.py`, `bake/bake.py`.

**Node, real extracted code, both patched players.** (1) Ids: the player's own `let TB`/`yB`/`WB`/`VB` allocate root,
container, incoming, outgoing = TB … TB+3 for all four DSK-deck dissolves. (2) Over all 133 transitions on disk and in the
committed test fixtures: 46 copied (42 on disk + 4 committed full trees), each with its two rules naming exactly the ids `VB`
then allocated; 87 stock with no rule inserted; 0 source objects mutated. (3) 21 near-misses stay stock (dropped CSS, build
type, other name, 0.5→0, two animations, animated incoming, three leaves, translucent incoming, `keyTimes`, no layers, null
base, `isVideoLayer`, `isWebVideoPosterLayer`, leaf/container `objectID`, affine offset, rotation, scale, 3D transform, leaf
`sublayerTransform`, container rotation). (4) Failures: dropped `mix-blend-mode`, dropped `isolation`, `insertRule` throwing
on the 1st or the 2nd rule, no stylesheet → stock tree built (incoming opacity 1, no mirror rule), and no rule targets any
built node (`TB` skipped by 4 when a rule was inserted).

| Arm (bytes; 1-min load at start) | Mid frames | Max residual, full res (LSB) | Overlap α min | Complement error | rAF |
|---|---|---|---|---|---|
| `p2-t-patch` (rev 3; 3.39) | 6 | 1.3 | 255 | 0 | 2 animations, one `startTime`, Σ−1 ≤ 1e-6, in − ease ≤ 1e-6; leaves `plus-lighter`, container `isolate` (computed) |
| `p2-t-noblend` KB (rev 3; 3.17) | 6 | 64.0 | 191 | 0 | 2 animations |
| `p2-t-stock` null (2.61) | 8 | 206.4 | 255 | 254 (in-only α 255 at the first changed frame) | 1 animation |
| `k17-t-patch` DSK 5→6 (rev 2; 3.57) | 6 | 1.5 | 255 | 0 | as P2 |
| `k17-t-stock` null (4.23, over the limit: exploratory) | 6 | 204.5 | 255 | 254 | 1 animation |
| `p2-t-patch-sw` `--disable-gpu` (rev 1; 4.98, exploratory) | 4 | 2.7 | 254 | 1 | as patch |
| `p2-o-stock` / `p2-o-patch` opaque-texture (rev 2; 3.27 / 3.14) | 8 / 8 | 0.7 / 1.2 | 255 | n/a | 1 / 2 animations |

Matched progress, opaque textures (`matched.py`, 8 frames): max 1.51, p99.9 1.22. Instrument lesson: pre-advance frames show
the **live** slide (its playing movie), fit a spurious e ≈ 0.05 with residual ≈ 247; frames are admitted by the rAF log.

## 9. Acceptance

**Rule.** Every blocking check has a positive control that must PASS and a negative control that must FAIL, read before the
candidate counts. Missing or malformed evidence is INCONCLUSIVE and invalidates the round; INCONCLUSIVE never satisfies an
expected FAIL. One headless Chrome at a time; 1-min load < 4 at start; no OBS during headless runs.

| Check | Positive (PASS) | Negative (FAIL) |
|---|---|---|
| Model (texture group) | `opaque-off` | `off`, `noblend` |
| Complement | `noblend` | `off` |
| No dip | `opaque-off` | `noblend` |
| Curve | rAF of `on2` | scorer case: linear curve |
| Monotone | `opaque-off` | scorer case: non-monotone e |
| No flash | `delay-on` | `delay-off` |
| Screen path | `screen-on` | `screen-off` |
| Hand-off | `off` (stock hand-off) and scorer case: unchanged | scorer case: injected step above τ |

### 9.0 Q0b — step 0 (scratch, before W1)

Done (§8): rev 3 patch and KB, opaque-texture controls, matched progress. Pending, DX-1 criteria: `screen-on`/`-off`; D2 `on`;
CvC `on` × 2; `--disable-gpu` and the DSK deck on rev 3 bytes inside the load rule; `delay-on`/`-off`; one lifecycle dry run.
A miss stops the plan for re-planning, never a threshold change.

### 9.1 DX-1 headless gate — `scripts/dissolve_probe.py` (promotes the evidence's `dissolve_ab.py` + hook)

- **Resolver contract (W2; reused by W3; read-only).** Stock `index.html`, player and slide JSON from the deck's
  `html-unmodified`; PDFs/`.pdfp` from a fresh scratch strip of those PDFs with the corrected stripper (715cb3f1); movies
  mapped explicitly to decode-compatible copies (P2: `html-player` H.264). In-memory overrides (`header.json` loop flag, an
  event's `automaticPlay`/`beginTime`) only where a row says so. Every asset's provenance (source, sha, override) is recorded;
  every required movie must decode (`readyState ≥ 2`, `currentTime` advancing). Opaque-texture arms skip the PDF overlay.
- **Driver.** One fresh headless Chrome per arm, 1920×1080, DSF 1, own port (never 9222). Alpha arms: `LiveOutputHost` attach.
  Screen arms: `LiveOutputHost` headless launch mode (black page, `#obed-output-black`), screenshots via the host's transport.
- **Instrument.** Innermost hook, from the first rAF with the transition DOM: each leaf's effective opacity (product up the
  chain, also before any animation attaches), every `-opacity` animation (`currentTime`, `startTime`, value), visible `<video>`
  rects, scene/hash; at that first rAF both texture canvases (`toDataURL`, ids) and the computed `mix-blend-mode`/`isolation`
  chain. PNG screenshots with alpha at full scale from 0.35 s before the advance to T + 0.6 s.
- **Scorer (pure, every pixel of the scoring mask; reused by DX-2).** Textures A (outgoing), B (incoming), premultiplied. Per
  admitted screenshot: e by least squares; residual `|F − ((1−e)·A + e·B)|` outside visible `<video>` rects + 2 px. This is the
  **texture-group** score, not whole-slide or media equivalence. Screen arms: RGB against the cross-fade over black.
- **Capture integrity (shared; any violation INCONCLUSIVE):** both texture ids equal the export JSON's (incoming, outgoing) for
  that transition; hash before/after = the transition's from/to slide; screenshot size 1920×1080 and page mode as the arm
  states (alpha: computed page background `rgba(0, 0, 0, 0)`; screen: opaque); every measurement finite and non-empty; served
  digest as the arm table states; fade-scoring arms ≥ 6 mid frames (0.05 < e < 0.95, admitted only while the transition DOM is
  present); delay arms ≥ 2 screenshots inside the delay window and rAF coverage of all of it; lifecycle rows ≥ 1 settled final
  frame plus the DOM/stylesheet census after it.

| Check | Threshold (measured) |
|---|---|
| Model | every mid frame max residual ≤ τ = 4 LSB (1.3–1.5 GPU, 2.7 software; KB 64, stock 205–206) |
| Complement | every admitted frame: \|α_in-only + α_out-only − 255\| ≤ 2 (0; stock 254) |
| No dip | overlap α ≥ 252 every frame (255 / 254; KB 191) |
| No flash | effective incoming opacity 0 in every rAF before the first animation frame |
| Curve | two animations, one `startTime`; \|in + out − 1\| ≤ 1e-5; \|in − ease-in-out(ct/T)\| ≤ 1e-4; T = export duration ± 1 frame |
| Monotone | e non-decreasing (−0.01 slack), ≥ 0.99 before the hand-off |
| Hand-off | H = max premultiplied \|first-live-frame − last-transition-frame\| outside the destination's movie rects, on the identified last screenshot with the transition DOM (e ≥ 0.99) and first screenshot with the destination scene's DOM; either missing → INCONCLUSIVE; H ≤ τ |

**Per-arm contract** (required classes ≥ 2 000 px; deviation INCONCLUSIVE):

| Arm | Deck / bytes | Required classes | Checks → expected | Styles | Served digest |
|---|---|---|---|---|---|
| `on` | P2 2→3, DSK 5→6 (alpha) | out-only, in-only, overlap | all → PASS | leaves `plus-lighter`, container `isolate` | pinned `on` |
| `on` D2 | D2 2→3 (alpha) | overlap | model, no dip, curve, monotone, hand-off → PASS; complement N/A | as `on` | pinned `on` |
| `on2` | P2 | as `on` | CvC: residual distribution within 1 LSB of `on` | as `on` | pinned `on` |
| `off` | P2, DSK 5→6 | out-only, in-only | complement, model → FAIL; hand-off → PASS | none | pinned `off` |
| `noblend` | P2 | all three | no dip → FAIL; complement → PASS | leaves `normal`, container `isolate` | pinned `on` + one counted splice (`plus-lighter` → `normal`, 2 occurrences) → derived digest |
| `opaque-off` / `-on` | P2, unstripped | overlap | model, no dip, monotone, hand-off → PASS; complement N/A; matched on/off reported (bound 2) | none / as `on` | `off` / `on` |
| `screen-off` / `-on` | P2 stripped, screen path | out-only, in-only | RGB vs cross-fade over black → FAIL / PASS | none / as `on` | `off` / `on` |
| `delay-off` / `-on` | P2; one counted splice `},1e3*g)` → `},1e3*g+300)` | in-only | no flash; in-only α in the window 255 → FAIL / 0 → PASS | none / as `on` | base + splice → derived |
| `on-sw` | P2, `--disable-gpu` | as `on` | all → PASS | as `on` | `on` |

**Lifecycle scenario** (one parametrized driver function, patched bytes; each row's visible frames also pass complement and
no flash; "cleanup" = no transition `layer<id>` node and none of its rules after the next scene):

| Row | Action | Expected |
|---|---|---|
| advance | plain 2→3 | settled frame = stock twin's (outside movie rects); cleanup |
| replay | go-to 2, advance again | as advance; rules re-created on fresh ids |
| queued advance | Space mid-dissolve | player's own queue as stock twin; cleanup |
| queued skip | `advanceAndSkipBuild` mid-dissolve (def @2350987 / @2351025) | as stock twin; cleanup |
| go-to / back | go-to 1 or back mid-dissolve | transition DOM and rules gone; destination as stock twin |
| hide / show | hide mid-dissolve, show 0.5 s later | while hidden: alpha output fully transparent / screen output black (hidden check, separate from visible-frame checks); after show: model holds on the remaining frames |
| automatic | in-memory override: dissolve event `automaticPlay: true`, effect `beginTime` 0.5 s | incoming 0 through the real delay branch; then as advance |
| loop wrap | in-memory `header.json` `loopSlideshow: 1`, P2 slide 4's dissolve | as advance onto slide 1 |
| end of show | P2 slide 4's dissolve, loop 0 | held endpoint = stock twin's (DOM and rules legitimately remain); then go-to 1 → cleanup |

### 9.2 DX-2 inside OBS CEF — `managed_obs_qualify.py --arm dissolve` (unrecorded)

One launch, the shared resolver, sessions `on`, `on2`, `off`, `noblend`, `opaque-off`, `opaque-on` through the managed bridge
with DX-1's hook, the 2→3 advance and a `GetSourceScreenshot` (PNG, alpha) burst; DX-1's integrity rules. **Calibration fixed
before capture, applied without clamping:** n = max mid-frame residual of `opaque-off`; τ_CEF = max(4, ⌈n⌉ + 1); complement
bound 2 + ⌈n⌉; no-dip bound 252 − ⌈n⌉; caps τ_CEF ≤ 8, complement ≤ 6, no dip ≥ 248, so **n > 4 is INCONCLUSIVE**. Blocking
per the §9 control table. Refuses while `OBED_LIVE_MM_OPACITY` is set.

### 9.3 DX-3 owner check in real OBS

- **Pre-check:** run DX-1's texture classifier on the chosen production transition (export only): fill-less outgoing pixels
  and ≥ 2 000 px in-only make it an affected transition; otherwise it is a **regression control** (must look unchanged).
- **Where:** Take output (Keyer) on the stripped P2 copy 2→3 and the pre-checked production transition (a DSK clip slide's
  forced dissolve); switcher key output and OBS's checkerboard preview.
- **Pass:** slide 3 fades in from nothing over the whole fade; slide 2's graphics keep their colour while fading; no darker or
  more transparent moment where both overlap; no jump at the hand-off. Movies: expect today's jump to the opening frame (§1.4)
  until F3. **Null** (affected transitions only): `OBED_LIVE_MM_OPACITY=off` shows the pop-in.
- **Report** candidate and null separately, each with the served mode and `output.mmOpacity.sha256`.

### 9.4 Regression

`run_gates.sh` full tier from a fresh pinned worktree; `mm_opacity_probe.py`, `mm_handback_probe.py`; managed OBS (owner
session) `--arm mmo`, `--arm g2`, `--arm mmo-cef`, each with its control matrix and 3→4 checks. Root-cause any change.

## 10. Tests (three new test functions; the rest extends existing ones)

1. **Free:** tuple-parametrized anchor/replacement refusal (both patchers); off identity; `patch_rendering` = `patch_player`
   minus the hook; "every original anchor gone" (`test_live_runtime.py:205`, `:265`, `:367`); new-player equivalence;
   `node --check`; pin mismatch. Synthetic builders derive from the tuple: no edits elsewhere.
2. **Edits** (`test_live_runtime.py`): re-pin; hand-back tests use `HANDBACK = slice(5, 8)`; the composition test runs the
   groups R1–R5, R6–R8, D1–D2 in every order and checks containment including self.
3. **New, REAL-gated, parametrized over both players and one case table** (Node on the real extracted code): D1–D2 offsets;
   ids pre-order on the real `VB`; every committed `tests/fixtures/live_continuity` transition (4 dissolves copied with their
   two rules naming the built ids; 12 others stock, no rule; no source mutation); the 21 near-misses; the five failure cases of
   §8 (stock tree, no rule targets a built node).
4. **New `tests/test_dissolve_probe.py`, one parametrized function** (synthetic numpy): exact cross-fade PASS; stock pop-in FAIL
   complement and model; plain fades FAIL no dip; ±1 LSB PASS; video rect masked; linear curve FAIL; non-monotone FAIL;
   hand-off unchanged PASS / injected step FAIL / missing endpoint INCONCLUSIVE; integrity: missing texture, wrong texture id,
   wrong scene, wrong size or page mode, non-finite value, < 6 mid frames, short delay window, missing class, wrong digest or
   splice → INCONCLUSIVE; an INCONCLUSIVE `off` fails the gate.
5. **`test_managed_obs_qualify.py`:** parametrize the existing env-refusal test over the new arm; one new calibration test
   (n = 4 → τ 5, bounds 6 / 248; n = 4 + ε → INCONCLUSIVE).

## 11. Work streams (Opus MEDIUM implementers, disjoint files; only the coordinator commits)

| # | Files | Work |
|---|---|---|
| W0 | coordinator | `git cherry-pick 715cb3f1` |
| W1 | `src/obed_edom/live_runtime.py`, `tests/test_live_runtime.py` | D1–D2; docstrings; re-pins; tests 1–3 |
| W2 | `scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py` | resolver, DX-1, lifecycle; test 4 |
| W3 | `scripts/managed_obs_qualify.py`, `tests/test_managed_obs_qualify.py` | `--arm dissolve` on W2's resolver/scorer; test 5 |
| W4 | `README.md`, `.agents/skills/obed-edom/SKILL.md`, plan status | README fallback line; one SKILL sentence; handover |

Order: W0 → Q0b → W1 ∥ W2 → W3 → gates → GPT-6 Astra review (Opus fallback) → fixes → full local suites
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal` (no dashboard files), Python 3.10 floor → DX-2,
`mmo-cef`, DX-3 (owner session) → one PR to `main`. Never merge.

**Reviewer brief.** (1) Anchors unique, consumed, never contained; order independence. (2) Stock tree on every predicate miss
and failure; nothing mutates export JSON; no code after `new VB`. (3) Rule ids = allocated ids; abandoned ids on partial
insert. (4) One `applyCssAnimation` pass. (5) `off` = today's bytes. (6) Every threshold measured or fixed by formula; every
blocking check has PASS and FAIL controls.

## 12. Owner decisions

**Recorded 2026-10-11 (owner):** "in Keynote the vid stops playing and dissolves out" — the target for a movie on the
outgoing slide is freeze on the current frame, then fade with the slide.

1. **Switch.** (a) Fold into `mm_opacity` (R9–R10). **Recommended** (one rollback, no API/pin-shape change, preview inherits,
   precedent hand-back 2a). (b) Separate `OBED_LIVE_DISSOLVE` at the §4 cost.
2. **Scope.** (a) Every output. **Recommended** (§1.3). (b) Keyer only (fill-less decks keep popping in on HDMI).
3. **Follow-ups F1 (`none` cut) and F2 (other transitions).** (a) Separate PRs after this lands. **Recommended.** (b) F1 now.
4. **Where does freeze-and-dissolve-out (F3) live?** In every option the outgoing slide's live `<video>`s are paused at their
   current frame and placed **under the outgoing `layer<out>-opacity` wrapper inside the outgoing blend leaf**, after the
   texture canvas, at their authored geometry, so they fade and blend with slide 2; gated with a deterministic counter movie
   (frozen frame = last presented frame before the advance; region alpha = (1 − e)·255), with today's jump and a
   full-strength hold as negatives. This patch's texture fix stands either way.
   - (a) **In this patch**, at the `removeChild` site: one PR, but it brings back post-draw DOM work (moving live elements),
     touches media and the continuity core's retire/pin logic, and needs the media gate before this pixel-exact fix can land.
   - (b) **Separate follow-up on main, in the player patch.** **Recommended**: it fixes every deck in every continuity mode
     (the jump comes from the player's own DOM removal, which runs whether continuity is on or off), keeps this PR small and
     post-draw-free, and gets its own media gate. Cost: a second PR; it must define the hand-over with main's core (which
     retires restart decoders at 2→3) and tell S2 to end its hold at the dissolve.
   - (c) **S2's continuity core**: S2 already owns held decoders through the dissolve (pause, then parent under the same
     wrapper; this patch would only document the id rule). Covers only continuity-qualified decks; the raw player keeps the jump.

## 13. Risks and out of scope

CEF's compositor unproven until DX-2. The id prediction relies on `VB`'s pre-order allocation (proved on the real classes;
the gate's style premise re-checks it on every run). Software compositing cost during a dissolve (P2 non-GL timing re-run).
Production transparency unverified (DX-3 pre-check). Opaque on/off bound rests on one take. Out of scope: F1–F3, GL effects,
Keynote-app comparison (hands off Keynote).

## 14. Critique log

Raw rounds and prompts: `.agents/reviews/dissolve-crossfade/plan-astra-r{1,2}.md` (+ `.prompt.md`), kept while the plan is
in review.

### r1 — GPT-6 Astra high (Codex), on rev 1 `8e572864`

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| 1 | major / new | Folded; superseded in rev 3 by commit-before-construct (r2-1). | §3 |
| 2 | major / new | Folded: D1 consumes its anchor; containment incl. self checked. | §3.1, §6.1 |
| 3 | major / new | Folded; corrected in rev 3 (r2-3, owner input). | §6.2, §12.4 |
| 4 | major / new | Folded: per-arm contract; INCONCLUSIVE never satisfies a FAIL. | §9.1 |
| 5 | major / new | Folded: CEF controls and fixed calibration (corrected r2-6). | §9.2 |
| 6 | major / edge | Folded (completed r2-4). | §9.1 |
| 7 | major / new | Folded and measured: 1.51 LSB, replacing "≤ 1 LSB"; screen-path arms. | §2, §9.1 |
| 8 | major / closed | Folded: `mmo-cef` re-run. | §6.2, §9.4 |
| 9 | minor / new | Folded: shared resolver. | §9.1 |
| 10 | minor / edge | Folded: geometry/media predicate. | §3.2 |
| 11 | minor / edge | Folded: DX-3 pre-check, regression control. | §9.3 |
| 12 | nit / closed | Folded: 382. | §1.2 |

### r2 — GPT-6 Astra high (Codex), on rev 2 `cd289a05`, and the owner's answer

| # | Severity / class | Disposition | Where |
|---|---|---|---|
| r2-1 | major / closed | Folded by a simpler design (coordinator's preference): blend committed as stylesheet rules keyed by the ids `VB` will allocate, verified, before the copy and before any build; failure returns the stock tree (ids abandoned if a rule went in); D3 and every post-draw path removed. Node: ids proved on the real classes; 46/46 rule selectors = built ids; five failure cases end stock with no rule on a built node. Browser: computed blend/isolation on the right nodes, residual 1.3. | §0, §3, §8, §10.3 |
| r2-2 | major / new | Folded: shared capture-integrity list restored beside the per-arm table, with delay and lifecycle minimums; scorer cases restored. | §9.1, §10.4 |
| r2-3 | major / new | Folded with the owner input: attach point = under `layer<out>-opacity` inside the outgoing leaf; media gate with a deterministic counter movie and a full-strength-hold negative; the static score renamed "texture group", not whole-slide. | §2, §9.1, §12.4 |
| r2-4 | major / closed | Folded: hide/show and `advanceAndSkipBuild` rows; real automatic branch via a provenance-recorded override (timer splice kept as the no-flash control); terminal held endpoint then navigation cleanup; hidden checks separate. | §9.1 |
| r2-5 | major / new | Folded: explicit hand-off statistic on identified frames, missing = INCONCLUSIVE; controls in the table and scorer test. | §9, §9.1, §10.4 |
| r2-6 | minor / edge | Folded: no clamping; n > 4 INCONCLUSIVE; n = 4 / 4 + ε tested. | §9.2, §10.5 |
| r2-7 | minor / new | Folded: full-resolution scoring; P2 1.3 (rev 3), DSK 1.5, software 2.7; τ 4. | §0, §8 |
| owner | decision | Recorded; baked frame measured (opening frame, §1.4); decision 4 rewritten as "where does F3 live". | §0, §1.4, §12 |
