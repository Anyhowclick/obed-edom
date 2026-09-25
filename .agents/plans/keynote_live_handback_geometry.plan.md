# Magic Move hand-back geometry: the settled GL frame must land on the DOM layout

**LANDED #238 (`45290c5f`, 2026-09-25).** **APPROVED rev 2 — owner 2026-09-25: decisions 1–8 as recommended (1a, 2a, 3a, 4a, 5b, 6a, 7a, 8a).** **Amended 2026-09-25 (owner): decision 3 → 3b** — always-on R8 made P2 bridge-off red (slide-3 restart clock +0.2 s; slide-4 render overlapping the 2→3 dissolve; `.agents/reviews/handback-geometry/gates-r1.md`). 2026-09-25, Opus investigator; rev 2 = Opus HIGH critique (log in §9). Plan only: no product code, no commits, no OBS
launch, no Keynote. Base: `main` @ `0df5ea10` (MM opacity #233/#234 and preview #235/#236 merged). Player `main.js` sha
`e9b2fad4…` (= `live_runtime.PLAYER_SHA256`); every offset below is a **byte** offset (`grep -bo` convention, as the MMO plan's
§3). Evidence: main checkout `output/evidence/handback-geometry/` (gitignored; JSON tables, crops, scratch probe/scorer/candidate; raw P2 `runs/` screenshots not retained).
Parents: `keynote_live_mm_opacity.plan.md` (R1–R5, §7 G2), `keynote_live_gl_replay_arming.plan.md`,
`keynote_live_gl_replay_managed_obs.plan.md`, `dashboard_preview_mm_opacity.plan.md`.

## 0. Summary

- **Root cause.** Keynote's export encodes a *scaled* Magic Move leaf as its slide-1 texture (rasterised at 1×, with a
  1.4–1.9 px transparent margin) plus `scale.to` = the ratio of the **padded texture sizes** (353/178, 313/157). The player
  scales that texture onto exactly the slide-2 texture rect (0.001 px), but the margin scales with it (→ 3.2–3.8 px) while
  the slide-2 texture has its own 1.0–1.9 px margin. The GL content therefore settles 4.9 × 2.7 px smaller than the authored
  object and is off-centre. At build 1 the DOM draws the slide-2 texture, which is the authored geometry, and the
  content jumps. It is a Keynote-export encoding issue that the player replays faithfully, not a canvas/DPR/stage issue.
- **Which side is right.** The DOM. Its content rect equals the export's slide-2 PDF vector frame to ≤ 0.03 px, and it is
  what stays on screen for the rest of the slide. (Against the `.key`: UNVERIFIED.) Corroboration: the 3→4 leaf has the same
  padded-ratio mismatch (−1.3 px, `predicted-geometry.txt`), and Keynote itself fixes it there with a `contents` crossfade.
- **Scope.** Only MM leaves that change geometry **without** a Keynote `contents` animation. All 24 exports under `output/`
  hold 26 distinct MM effects and 110 leaves. Exactly **2 leaves** qualify: P2 1→2 slot 2 (black sentinel) and slot 4 (green
  square). **No owner deck is affected today** (D1–D6: 0); the fix is for P2 and future decks. 3→4 already crossfades via
  Keynote's own `contents` animation and reads 0.004 px.
- **When the snap shows.** At the next advance after the move (build 1 or the next transition starts in the same frame),
  not at the end of the motion.
- **Fix (recommended).** Three more count-checked replacements in `patch_player`/`patch_rendering` (R6–R8), using the
  player's own `contents` crossfade path. For each qualifying leaf, blend from the slide-1 texture to the matched slide-2
  texture over the move. The settled frame is then the DOM frame. Measured headless: max |Δ| 2.788 → 0.000 px @1080,
  3.746 → 0.018 @1440, 2.424 → 0.005 @1600×1000. G2 stays LIVE with no stand-down. MMO composes in either order.
  **Trade:** mid-move pixels change. The object is a blend of two textures whose edges are ≤ 2.1 px apart at mid-move (derived,
  §3.3); owner eyeball decides (decision 8). The fix is best-effort: if the next slide is not rendered at MM start (e.g. a
  queued double-advance) that move stays exactly as today.
- **Gate.** Sub-pixel edge scorer on settled frames. Null and CvC read 0.000; the positive control reads 1.000/0.500
  exactly; known-bad reads 2.42–3.75 px and matches the JSON+PDF prediction to ≤ 0.04 px; fixed reads ≤ 0.018 px; the
  threshold is 0.25 px. **Two existing gates break and must be re-cast** (§3.4): MO-4 `liveGreenEqual` and managed-OBS M3
  edge fidelity.

## 1. Q1: root cause, arithmetic, per-object measurements

### 1.1 Code path (player bytes)

- `fB.setupTexture` (2263021) → `textureInfoFromEffect` (2263373) sets `e.textureRect` (2264013) = Σ `bounds.offset` ×
  the leaf's own `width/height`. `VB` computes `bounds.offset = position − anchor·size`, rounded to 1e-6 (2287297).
- `pB` (Magic Move, 2259434) puts the texture quad at that rect through `baseTransform` (2260233, y-up ortho).
- `QB.renderFrameWithContext` (2189505):
  - translation `s + (to − from)·Z` (2189952);
  - scale about `anchorPoint·size` (2190553), with the post-loop `Z` (2190838);
  - a `contents` animation binds `toTexture` on unit 1 and sets `mixFactor = Z` (2191013).
- The shader is `mix(outgoing, incoming, mixFactor) · Opacity` (1987259). `eB` sets `isBlending = !!texture.toTexture` (2191792).
- Textures are pdf.js renders at `zC=1` (2368709, 2331951), so 1 texel = 1 authored px. The GL canvas backing is
  `slideWidth×slideHeight` (2317655); the viewport is the canvas size (2262512). The canvas and the DOM textures sit in the
  same CSS-scaled `#stage`.

### 1.2 Export data (P2, `output/p2-binary/html-player`, slide `08C861A1` event 1, destination `0C652BEB` events[0])

| leaf | slide-1 texture @ rect | content in texture (PDF vector) | MM scale.to | translation.to | slide-2 texture @ rect | content in texture |
|---|---|---|---|---|---|---|
| green `8F325E` | 178×157 @ (636,723) | fill 1.634..176.090 × 1.366..155.550 | 1.98315 (=353/178), 1.99363 (=313/157) | (240.364, 27.958) | `3F22E4` 353×313 @ (789,673) | 1.153..351.989 × 1.900..311.968 |
| sentinel `1FDCDA` | 266×236 @ (975,722) | fill 3.015..262.568 × 3.417..232.809, 4-px white stroke | 0.68045, 0.68220 | (−475.433, −38.536) | `A637A0` 181×161 @ (542,721) | fill 3.191..177.647 × 3.366..157.550, 4-px stroke |

- Authored content ratio is 2.01103 in both axes (350.836/174.456, 310.067/154.184). The encoded ratio is 1.983/1.994.
- The slide-1 group frame (174.456×154.184 @ 637.634,724.366) equals the PDF fill rect to 1e-3, and so does the slide-2
  group origin (790.153, 674.900).
- Reading the `.key` via keynote-parser was not needed: the export's JSON and PDF vectors agree. It is UNVERIFIED against the `.key`.

### 1.3 Arithmetic: predicted vs measured (authored px = screen px @1920×1080; Δ = DOM − GL)

GL end quad = offset + to + anchor − scale·anchor gives (789.000, 673.000, 353.000, 313.000) for green and
(542, 721, 181, 161) for the sentinel. Both equal the DOM texture rects exactly (`evidence/predicted-geometry.txt`).

| edge | GL predicted | GL OBS | DOM authored (PDF) | DOM OBS | Δ predicted | Δ OBS (10 sessions) | Δ headless |
|---|---|---|---|---|---|---|---|
| green left | 792.240 | 792.235 | 790.153 | 790.176 | −2.087 | −2.059 | −2.060 |
| green right | 1138.211 | 1138.206 | 1140.989 | 1140.971 | +2.777 | +2.765 | +2.788 |
| green top | 675.723 | 675.765 | 674.900 | 674.912 | −0.823 | −0.853 | −0.817 |
| green bottom | 983.108 | 983.088 | 984.968 | 984.941 | +1.859 | +1.853 | +1.843 |
| sentinel stroke L (centre) | 544.052 | 544.069 | 545.191 | 545.251 | +1.139 | +1.182 | +1.114 |
| sentinel stroke R | 720.665 | 720.653 | 719.647 | 719.749 | −1.018 | −0.905 | −1.043 |
| sentinel stroke T | 723.331 | 723.349 | 724.366 | 724.251 | +1.035 | +0.903 | +1.063 |
| movie outline L/T/R (static) | — | — | — | — | 0 | 0.000 | 0.000 |

- The sentinel stroke is 2.59–2.65 px wide in GL (predicted 4 × 0.68 = 2.72) and 4.00 px in the DOM. Its bottom edge lies
  over the playing movie and is not measured.
- Only scaled leaves move. The static movie footprint (`935F60`, same texture on both slides) reads 0.000.
- The owner's "~3 px/side, 1.7 %" came from an integer bbox threshold on the 4-px GL blur ramp. The true content is
  1.39 % small (345.97 vs 350.84) and off-centre.
- Candidates ruled out:
  - (b) MVP ≠ CSS: the quad is exact.
  - (c) canvas/DPR/stage: the Δ scales with the stage factor (§2), and the static control reads 0.
  - (a)+(d) is the cause: the texture is rasterised at slide-1 size with its margin, and the export's scale is a
    padded-texture ratio.

### 1.4 Instrument and controls (OBS recordings, UtVideo lossless, Y plane, tv-range)

- **Recordings.** `qualify-home/recordings/mmo-20260925-143530/` (25 fps) and `…-144012/` (30 fps) (recording not retained: trashed 2026-09-25; H.264 copies in main checkout `output/evidence/mmo-gates/obs-mo7/eyeball/`); measured edges kept in main checkout `output/evidence/handback-geometry/obs-recordings-edges.json`. `14-37-02.avi` is
  `g2-on-2`, the MO-7 control twin of `g2-on` (`obs-mo7/run.log`: "decoding g2-on-2"). The hand-back frames are found
  automatically (first green-right jump): 25 fps 409/408/407/435/436, 30 fps 493/492/491/525/520.
- **Metrics.**
  - Step edges use the area method: edge = window start + Σ(hi − p)/(hi − lo), on a band-averaged profile.
  - Strokes use the first moment of (p − lo)/(white − lo), which gives the centroid and the width.
- **Controls.**
  - Null: two consecutive settled GL frames, and two consecutive DOM frames, read 0.000 in every session.
  - Positive: a synthetic 1-px or 0.5-px shift of the settled frame reads 1.000/0.500, with max error 0.0000.
  - Synthetic box-filtered edges at 10.0/10.3/10.5/10.77 read back exactly.
  - CvC: `g2-on` vs `g2-on-2` reads 0.000 at 25 and at 30 fps.
  - All 10 sessions agree per edge within 0.028 px, whatever the MMO and G2 settings: the jump pre-dates MMO.
  - The nulls and the shift control validate the capture chain and scorer only. The end-to-end positive control is the
    known-bad itself: measured Δ matches the JSON+PDF prediction (table above) to ≤ 0.04 px on green.
  - **Critique spot-check (independent code, same file).** `14-37-02.avi` Y plane, frames 380–430: GL frames 380–407
    read R 1138.206 / L 792.235 / T 675.765 / B 983.088, DOM frames 408–430 read 1140.971 / 790.176 / 674.912 / 984.941 —
    identical to the table. A different estimator (50 % crossing) gives Δ R +2.885, L −2.268: same sign and size, within
    0.21 px; the area method sits closer to the prediction.
- **Headless vs OBS @1920.** The green edges agree within 0.03 px and the sentinel strokes within 0.16 px (thin line,
  tv-range luma). The headless in-page `readPixels` capture has ±0.2 px quantisation at the translucent low-contrast green
  edge in RGB, so the gate uses screenshots, or the alpha channel for in-page captures.

## 2. Q2: other Magic Moves and viewports (headless, `LiveOutputHost`, GL off unless stated)

Max |Δ| in **screen px** at the 1→2 hand-back (build 1). The settled-GL screenshot and the first DOM screenshot are each
taken as a pair ≥ 0.5 s apart, and both pairs read 0.000. Values in brackets are divided by the stage factor s, i.e. in
authored px.

| viewport (stage) | today (main `0df5ea10`) | with R6–R8 | CvC |
|---|---|---|---|
| 1920×1080 (s 1, origin 0) | 2.788 (green R); same with G2 on | 0.000; 0.000 with G2 LIVE | 0.000 (stock×2, fix×2) |
| 2560×1440 (s 1.333, origin 0) | 3.746 [2.81] | 0.018 | — |
| 1600×1000 (s 0.833, letterbox y 50) | 2.424 [2.91] | 0.005 | — |

- **3→4 MM** (the movie footprint, which translates and scales). Keynote exported a `contents` animation `088511 → A22395`
  (dest texture shipped in slide 3's assets), so the player already settles on the destination texture. The DOM takes over
  immediately (slide 4's automatic `movie-start`), so the GL frame is transient and is captured in-page.
  - @1920 the Δ is 0.004 px in both arms.
  - At 1440/1600 the in-page (1× canvas) vs screen comparison reads 0.4–1.2 px **identically in both arms**. This is
    cross-resolution resampling next to the live `<video>`, not a jump. UNVERIFIED at non-native viewports.
- **Census** (`evidence/census-affected-leaves.txt`, mirror of the R6 rule) over the 26 distinct MM effects / 110 leaves:
  - 41 already have `contents`;
  - 51 are fades or other properties;
  - 16 have no animation group;
  - **2 qualify, both in the P2 1→2 effect**, which `p2-binary`, `p2-recovery`, `p2-loop` and `gl-decks/Minimal Alpha_DSK` share.
  - D1–D6 are untouched. An earlier broader rule caught 11 text fades there; that is why fades are refused.

## 3. Q3: the fix

### 3.1 Design

Do what Keynote itself does when it ships a `contents` animation. For a leaf that changes geometry without one, crossfade
from the source texture to the destination texture over the move. The quad geometry is untouched. At Z = 1 the GL draws the
destination texture onto its own rect, which is exactly what the DOM paints. The destination texture lives only in the
**next slide's** cache, and today that is loaded only after the MM ends (`preloadTextures` 2347697 loads the current or next
*scene*). So R8 preloads one scene further ahead. Without R8 the fix never engages (measured: arm `hbnopre` reads 2.788).

Match rule, resolved once when the MM is set up (never mid-flight):
- Effect `apple:magic-move-implied-motion-path`. Source slide k is found by `slideCache[k].textureAssets === this.textureAssets`.
- The destination is slide k+1, or 0 when `loopSlideshow`. Its `slideCache` entry must already be loaded, otherwise stock.
- The leaf has an animation group of only `transform.scale.x|y`, `transform.translation` and constant `opacity`. It has no
  `contents`/`toTextureId`, has `initialState.scale === 1`, and changes geometry (decision 5: under the recommended (b) the
  guard becomes `1===sx&&1===sy&&(ok=!1)`).
- Its end quad matches **exactly one** visible leaf of the destination's `events[0].baseLayer` within 0.01 px, with a
  different texture id.

Anything else keeps today's bytes and behaviour.

### 3.2 Exact replacements (appended after `_MM_OPACITY_REPLACEMENTS` R1–R5; each anchor `count == 1` before, each after `count == 1`)

| # | Site (byte) | Before | After |
|---|---|---|---|
| R6 | `fB.setupTexture` tail (2263321) | `B[g].toTexture=R.createTexture(this.gl,i)}}return B}` | same + `return"apple:magic-move-implied-motion-path"===A.name&&this.__obedHandbackTextures(A,B),B}` + method below |
| R7 | `QB` contents case (2190367) | `case"contents":C=e.toTexture}}var T=` (as shipped: extended by `var T=` so the anchor is not contained in its replacement) | `case"contents":C=e.toTexture}}e.obedMix&&(C=e.toTexture);var T=` |
| R8 | `preloadTextures` tail (2347821) | `this.textureManager.loadScene(B)}unloadTextures(){` | as shipped (3b): `this.textureManager.loadScene(B);var M=A.events[B],N=M&&M.effects&&M.effects[0];N&&"apple:magic-move-implied-motion-path"===N.name&&B+1<A.numScenes&&this.textureManager.loadScene(B+1)}unloadTextures(){` (rev 2 always preloaded: `…loadScene(B),B+1<A.numScenes&&this.textureManager.loadScene(B+1)}…`) |

The R6 method, verbatim as it would sit in `live_runtime.py` (also `evidence/candidate_replacements_hbfix4.py`):

```python
_MM_HANDBACK_METHOD = (
    b"__obedHandbackTextures(A,B){try{var s=UC.script,c=UC.textureManager.slideCache,k=null;"
    b"for(var n in c)if(c[n]&&c[n].textureAssets===this.textureAssets){k=+n;break}if(null===k)return;"
    b"var d=k+1<s.slideList.length?k+1:s.loopSlideshow?0:-1,D=d<0?null:c[d],S=d<0?null:s.slides[s.slideList[d]];"
    b"if(!D||!D.textureAssets||!S||!S.events||!S.events.length)return;var L=[];"
    b"(function W(l,x,y){var t=l.initialState,a=t.anchorPoint,"
    b"X=x+Math.round(1e6*(t.position.pointX-a.pointX*t.width))/1e6,Y=y+Math.round(1e6*(t.position.pointY-a.pointY*t.height))/1e6;"
    b"l.texture&&!t.hidden&&L.push({t:l.texture,x:X,y:Y,w:t.width,h:t.height});for(var i=0;i<(l.layers||[]).length;i++)W(l.layers[i],X,Y)})"
    b"(S.events[0].baseLayer,0,0);"
    b"for(var g=0;g<B.length;g++){var e=B[g],J=e.animations&&e.animations[0]&&e.animations[0].animations;"
    b"if(e.toTextureId||!J||1!==e.initialState.scale)continue;var sx=1,sy=1,tx=0,ty=0,ok=!0;"
    b"for(var j=0;j<J.length;j++){var p=J[j],P=p.property;"
    b"\"transform.scale.x\"===P?sx=p.to.scalar:\"transform.scale.y\"===P?sy=p.to.scalar:"
    b"\"transform.translation\"===P?(tx=p.to.pointX,ty=p.to.pointY):\"opacity\"===P&&p.from.scalar===p.to.scalar||(ok=!1)}"
    b"1===sx&&1===sy&&(ok=!1);"
    b"var W=e.initialState.anchorPoint,ax=W.pointX*e.width,ay=W.pointY*e.height,"
    b"qx=e.offset.pointX+tx+ax-sx*ax,qy=e.offset.pointY+ty+ay-sy*ay,qw=sx*e.width,qh=sy*e.height,"
    b"m=L.filter(function(r){return Math.abs(r.x-qx)<=.01&&Math.abs(r.y-qy)<=.01&&Math.abs(r.w-qw)<=.01&&Math.abs(r.h-qh)<=.01});"
    b"ok&&1===m.length&&m[0].t!==e.textureId&&D.textureAssets[m[0].t]&&"
    b"(e.toTexture=R.createTexture(this.gl,D.textureAssets[m[0].t]),e.obedMix=!0)}}catch(E){}}"
)
```

- **Name safety.** `R` inside `renderFrameWithContext` is a *local* (`R=p.from`). R6 therefore creates the texture in the
  `fB` method, where `R` is the module's GL util, and R7 only reads `e.toTexture`. An earlier draft that created it in `QB`
  would have thrown. Every new name uses the `__obed`/`obed` prefix (0 occurrences in the stock player). `node --check` passes.
- **Composition with MMO.** Checked on the real bytes.
  - R6–R8 anchors do not overlap R1–R5. R6's anchor ends at `return B}`, immediately before R1's `textureInfoFromEffect(`,
    and neither pair's bytes contain the other.
  - Applying MMO then R6–R8, or R6–R8 then MMO, gives identical bytes. All 8 after-counts are 1.
  - `patch_rendering` (no hook) takes them unchanged.
  - Served sha (as shipped, 5b + 3b): `574274e8…` (`patch_player`), `fd811938…` (`patch_rendering`); 5b with always-on R8 was `e17264c0…` / `5797b302…`; rev 2 prototype (any-geometry rule) was `ba709b7a…` / `1c779a82…`.
  - R3's `var T=` (2190397) sits 30 bytes after R7's site, untouched.
- **Where.** Append R6–R8 to `_MM_OPACITY_REPLACEMENTS` (decision 2), so the existing loop, count checks, switch, preview
  split and synthetic-player tests (`test_live_runtime.py:171–245`, `test_live_host.py:85`, `test_live_api.py:318`,
  `test_p2_adversarial_gl_replay.py:763–837`) all pick them up.

### 3.3 Measured effect (headless, scratch player, `evidence/headless-final-main-0df5ea10.json`)

- **Settled GL vs DOM.** 0.000 @1920 (GL off, GL auto, a second run, and an immediate advance after arrival). 0.018 @1440.
  0.005 @1600. The static movie outline stays ≤ 0.004.
- **In-flight** (`evidence/inflight-width-vs-progress.txt`, per-frame G−R band profile in-page, two separate runs matched
  by elapsed time):
  - the width difference fix − stock grows with move progress: 0 → +1.86 (p 0.51) → +4.84 px at settle;
  - its largest frame-to-frame change is 0.24 px (right edge alone 0.435); the move itself changes the width by ~2 px/frame.
  - **Limits.** The area method is linear in the blend, so this curve is Z·(edge separation) by construction: it rules out
    a mid-flight texture swap, not ghosting. 0.24 px is at the in-page instrument's own ±0.2 px quantisation, and there is
    no stock-vs-stock in-flight CvC. The fixed arm's right-edge max |2nd diff| is 2.70 vs stock 1.33, unexplained
    (rAF jitter or the blend). "Smooth" is therefore UNVERIFIED beyond "no step".
  - **Derived ghost bound** (JSON + PDF insets): the two textures' edges are `sx·1.05` px (green L), `sx·1.40` px (green R)
    apart, i.e. ≤ 2.1 px at mid-move where the weights are ~50/50, and ~2.8 px at the end where the weight is ~1. The
    sentinel's 4-px white stroke is mid-move a mix of a ~3.4 px and a ~4.9 px stroke ~1.4 px apart. Whether a viewer
    sees it while the object moves ~4–8 px/frame: UNVERIFIED (owner eyeball).
  - Side effect: the green square's second half sharpens (1:1 destination texture instead of a 2× upscaled one).
  - The MM start is unchanged: Z(0) = 0 draws the source texture.
- **G2** (GL auto @1920): LIVE, no stand-downs, `glErrors` 0, `occludedBands` 0, rest opacity `[1,0,1,1,0.2947]`. The
  LIVE screenshot vs the DOM after build 1 reads 0.000.
  - `frameLen` is 96 (was 88): +8 calls for the two blending leaves.
  - `opacityUnproven` is `[{4,"size"}]` (was `"rest-opacity"`). With mix = 1 the `Texture` sampler holds the 353×313
    destination, so `size` (`live_gl_replay_js.py:794`) fails before `rest-opacity` (:807).
  - Same fail-closed meaning as MMO §7 (iii): no override, the player's own value is replayed. G2 bytes are unchanged.
- **Continuity core.** Unaffected.
  - At 1→2 the movie slot (`935F60`) is static, so it is not matched. `tryRemount`/`keepAtFootprint`
    (`live_continuity_js.py:1316`, :863) are untouched.
  - At 3→4 the movie leaf has `contents`, so it is excluded. `keepThroughBridge` (:914) still interpolates to the slide-4
    rect, which the GL already matches.
  - G2's poster/video substitution is on slot 3, never blended.
- **Paint oracle / live_continuity_probe V arms:** UNVERIFIED. They should not move (movie slot untouched). Run them in W4.

### 3.4 Risks and why each is bounded

- **The destination is not loaded at MM start** (advance within the pdf.js render time of the next slide, on a big deck):
  that leaf stays stock, i.e. today's jump. There is never a mid-flight step, because resolution is setup-time only.
  A texture enters `textureAssets` only after its pdf.js render promise resolves (`handleRequestPdfPageCompleted`), so a
  half-rendered canvas cannot be picked up. Measured: an advance right after the host's settlement wait still engaged.
  **Not engaged by construction:** a queued key (`doIdleProcessing` runs `preloadTextures` and then the queued action in
  the same tick, so the MM is set up before the render finishes). Latency on large decks: UNVERIFIED.
- **Engagement is timing-dependent**, so any twin-compared harness must assert it (on-arm `frameLen` 96 / both leaves
  blended), else mark the run INCONCLUSIVE; never let a non-engaged run read as a stock twin.
- **R8 widens preloading before a Magic Move** (as shipped, 3b; rev 2 widened it for every slide, which made P2 bridge-off red — gates-r1), by one scene of lookahead. An automatic-play MM with no idle stop before it is never preloaded and stays stock. `unloadTextures` keeps slides g−1..g+1 and R8 loads
  at most slide g+1, so the **retention window is unchanged**; slide g+1 is filled earlier. `loadScene` without a callback
  does not touch `sceneDidLoadCallbackHandler`; go-to (`jumpToScene` → `isScenePreloaded`) only gets more cache hits. No
  product code reads `slideCache`/`loadScene` (grep). What moves: slide g+1's main-thread pdf.js render now runs in the idle
  **before** the move instead of after it, so a fast advance can overlap it with the MM's first frames. UNVERIFIED; W4 reads
  the managed-OBS cadence gates (repeat/gaps) with a fast advance. The alternative is decision 3.
- **Broken existing gates (must be re-cast in W3, not just re-baselined).**
  - MO-4 `liveGreenEqual` (`mm_opacity_probe.py:506`) demands exact pixel equality of `ROI_TOP` x 793–808 on vs off. Column
    793 is inside today's GL edge ramp: OBS Y plane reads 45 in the GL settle and 50 in the DOM (`14-37-02.avi`). With the
    fix LIVE = DOM geometry, so the check fails. Move `ROI_TOP` inward (x ≥ 797) or compare LIVE to the DOM.
  - Managed-OBS M3 "edge: G2-S alpha == round(mm-off-S alpha × 0.2947)" (`managed_obs_qualify.py:1021`, enforced) compares
    the edge band to the mm-off twin, which keeps today's geometry. With the fix it fails by construction (2–2.8 px shift).
    Re-cast: enforce edge G2-S vs G2-P3 (DOM) (today report-only at :1027), keep the unscaled KB. Derived, UNVERIFIED on OBS.
- **Wrong partner match.** It requires an exact 0.01-px quad match, uniqueness, a visible destination leaf, a different
  texture id and the property whitelist. The census finds no other match in 110 leaves.
- **Looping wrap (last → first MM):** R8 does not preload across the wrap, and `unloadTextures` evicts slide 0 at the last
  slide of a deck with ≥ 3 slides, so the leaf stays stock. A 2-slide looping deck may still hold slide 0 and engage.
  Either outcome is fail-closed.
- **Translation-only leaves** (decision 5): no padded scale, but the two textures' sub-pixel phases differ, so the derived
  hand-back error is < 1 px. No on-disk case.
- **Re-baselines** (§6 W3): the two G2 expectations change: `managed_obs_qualify.py:120–121` (`frameLen` 96 on-mode,
  unproven `size`) and `mm_opacity_probe.py:81` `UNPROVEN_ON`, plus their tests (`test_managed_obs_qualify.py:89`,
  `test_mm_opacity_probe.py:434–436`). MO-1's settle ROI is interior and flat (expected unchanged, UNVERIFIED).
- **Error text.** Appending to `_MM_OPACITY_REPLACEMENTS` keeps the "Magic Move opacity anchor" messages; rename the tuple
  and message to cover both fixes.

### 3.5 Alternatives considered

- **Fix the DOM side.** Rejected: the DOM is the authored geometry and persists for the rest of the slide.
- **Rescale the end transform to the content ratio.** Rejected: the destination's content insets exist only in the PDF
  vectors, not the JSON. Assuming equal padding leaves ≤ 0.9 px.
- **Hand back at settle instead of build 1.** Rejected: it moves the same 2.8-px snap to the end of the motion.
- **Crossfade enabled lazily mid-flight (no R8).** Rejected: without R8 it never engages, and a late load would step.
- **Accept.** The residual is 2.8 px @1080 (3.7 @1440), shown at the next advance, on MM leaves that scale without a
  Keynote `contents` animation: today the P2 green square and sentinel only, no owner deck. It is visible to the owner's
  eye on the fixture. Cost of the fix instead: 3 replacements, always-on one-scene lookahead, a changed mid-move look, 2
  gate re-casts + 3 re-baselines, a new probe, one OBS session.

## 4. Q4: gate design

**Instrument.** A pure scorer (area-method step edges, moment stroke centroids, stage mapping `screen = authored·s + origin`)
plus a driver `scripts/mm_handback_probe.py`. The driver runs one fresh headless Chrome per arm through `LiveOutputHost` and
reuses `live_continuity_probe.prepare_export/force_viewport`, the `mm_opacity_probe` Chrome cap and `live_host_probe.wait_for_settlement`.
- Settled GL: CDP screenshot pair ≥ 0.5 s apart, 2.5 s after settle. The 1→2 GL window is static until build 1.
- DOM: screenshot pair 2 s after build 1 settles.
- Transient 3→4: in-page capture after the last draw, scored on **alpha**.

**ROIs (authored px, P2; a premise check asserts the fixture's texture rects).**

| Object | Edges and windows |
|---|---|
| green | L x[780,800) rows 690–780; R x[1128,1152) rows 690–970; T y[663,687) cols 800–1130; B y[972,996) cols 1072–1135 |
| sentinel strokes | L x[536,554) rows 730–785; R x[712,730); T y[714,734) cols 560–705 |
| movie outline, static control | L x[100,108) rows 800–1050; T y[786,794) cols 120–530; R x[1062,1070) rows 990–1055 |

| Gate | Arms / viewports | Metric | Threshold | Prototype reading |
|---|---|---|---|---|
| HB-1 (blocking) | `on`, `on2`, `off`, `off2` × 1920×1080, 2560×1440, 1600×1000; GL off | max \|Δ\| over green + sentinel edges, screen px; premise: on-arms engaged (2 blended leaves), off-arms not, else INCONCLUSIVE | on ≤ 0.25; KB off ≥ 1.0 (must fail); CvC per edge ≤ 0.05 | on 0.000 / 0.018 / 0.005; off 2.788 / 3.746 / 2.424; CvC 0.000 (on×2, off×2 @1920; not yet run @1440/1600) |
| HB-1 controls (blocking) | every run | GL pair, DOM pair, slide-1 pair; movie outline Δ; synthetic 1/0.5-px shift of the GL shot | ≤ 0.05; ≤ 0.05; 1.000 / 0.500 ± 0.02 | 0.000; ≤ 0.004; 1.000 / 0.500 (err 0.0000) |
| HB-2 (blocking) | `on`, `off`; 1920; GL auto | G2 LIVE screenshot vs DOM; G2 stats | ≤ 0.25; LIVE, 0 stand-downs, `glErrors` 0, `frameLen` 96/88, unproven `[{4,size}]`/`[]` | 0.000 / 2.788; as expected |
| HB-3 (report-only) | `on` vs `off`, plus `off` vs `off2` (CvC); 1920 | width(on) − width(off) vs progress; per-frame step **divided by Δprogress** (a dropped frame under load otherwise doubles a raw step) | report; the owner eyeball (decision 8) judges the look | raw step 0.24 (at the ±0.2 px instrument floor); end 4.837; no CvC yet |
| HB-4 (report-only) | `on`, `off`; 3→4 | in-page alpha GL vs DOM | report | 0.004 @1920 both arms; 0.4–1.2 @1440/1600 both arms (instrument) |
| HB-OBS (report, then eyeball) | managed `--arm mmo` recordings | same scorer on the Y plane at the build-1 hand-back frame pair | ≤ 0.25 with fix | today 2.765 (10 sessions, spread ≤ 0.03), CvC 0.000 |

Margins: the worst fixed reading (0.018) is 14× under the threshold, and the smallest known-bad (2.424) is 9.7× over it.
Headless is primary. OBS confirms on the real render path (they agree within 0.03 px on green).
- **Load / rate robustness.** HB-1/HB-2 score static settled frames, so machine load and 25/30 fps cannot move them (10 OBS
  sessions at both rates agree within 0.028 px). Only the in-flight HB-3 is timing-dependent, hence report-only.
- **Why HB-3 is not blocking.** Its metric is linear in the blend (§3.3), cannot see ghosting, and sits at the instrument
  floor. A blocking in-flight gate would need a ghost metric and a CvC it does not have; the owner's eyeball is the real test.

## 5. Test plan

1. **Unit**, `tests/test_live_runtime.py`:
   - R6–R8 anchors `count == 1` on the real bytes (REAL-gated) and on the synthetic player;
   - MMO/HB order independence;
   - `patch_rendering` = `patch_player` minus the hook;
   - `mm_opacity=False` output byte-identical to today.
2. **Node behavioural**, on the real extracted `fB`/`QB` methods with `effect_1_to_2.json` plus a committed slide-2 layer tree:
   - `obedMix` only on slots 2 and 4;
   - at p = 1, unit 1 holds the destination and `mixFactor` is 1;
   - fades, hidden destinations, ambiguous matches, a missing cache and `contents` leaves all stay stock.
3. **Census mirror (pinned).** Committed fixtures, plus a REAL-gated sweep of `output/`: the affected set is
   {P2 1→2 slots 2, 4}.
4. **Scorer tests**, `tests/test_mm_handback_probe.py`, all synthetic:
   - box-filtered edges at sub-pixel positions (error < 0.01);
   - stroke centroid and width;
   - shift positive controls;
   - stage mapping at s 1.333 and 0.833 with a letterbox;
   - gate logic (KB must fail, CvC, nulls, premise).
5. **Headless.**
   - HB-1..HB-4 via `mm_handback_probe.py`.
   - `mm_opacity_probe.py` (all MO gates, with the re-baselined `UNPROVEN_ON` and the re-cast MO-4 `liveGreenEqual`).
   - `live_continuity_probe.py` including the V/Voff and paint-oracle passes.
   - P2 adversarial, 14 findings (`--reuse-export --disposable`, both wait profiles).
   - Never a full bake. At most 3 headless Chromes machine-wide.
6. **Full local suites** (`uv run pytest tests/ -n auto --dist loadfile -rs` with the `html-adversarial` symlink, `test:ui`,
   `test:maps`).
7. **Managed OBS** (owner-authorised session only): `managed_obs_qualify --arm mmo` at 25 and 30, with the new geometry
   report and the re-cast M3 edge check, plus one fast-advance take for the cadence gates (R8 timing), then the owner's
   eyeball take of `g2off` fix vs stock side by side, **at speed and stepped mid-move**, as the last step.

## 6. Work streams (disjoint files; only the coordinator commits)

- **W1 `live_runtime.py` + tests (1–3).** R6–R8 appended to `_MM_OPACITY_REPLACEMENTS`; docstring "rendering fidelity";
  Node test and census mirror.
- **W2 `scripts/mm_handback_probe.py` + `tests/test_mm_handback_probe.py`.** Driver and pure scorer (4). New files only.
- **W3 re-baselines, gate re-casts + docs** (sole owner of `managed_obs_qualify.py` and `mm_opacity_probe.py`; rev 1 had
  W2 and W3 both editing `managed_obs_qualify.py`).
  - `managed_obs_qualify.py:120–121` (`frameLen` becomes mode-keyed: 96 on / 88 off; unproven `size`); M3 edge re-cast
    (§3.4); HB-OBS geometry report importing W2's scorer (lands after W2).
  - `mm_opacity_probe.py:81` `UNPROVEN_ON`; MO-4 `liveGreenEqual` re-cast (§3.4); on-arm engagement premise.
  - Their tests.
  - README live section, SKILL live section, MMO plan §7 cross-reference, `dashboard_preview_mm_opacity.plan.md` note if
    decision 4 = yes.
- **W4 qualification** (5–7) and the gate record `.agents/reviews/handback-geometry/gates-r1.md`.

## 7. Owner decisions

1. **Fix or accept?**
   - (a) Fix with R6–R8, the crossfade to the destination texture. **Recommended**, conditional on decision 8: removes
     the settled jump at every viewport, mirrors what Keynote itself exports for 3→4, and composes with MMO and G2.
   - (b) Accept and document: zero code; the P2 fixture keeps a 2.8 px snap at the next advance; no owner deck is affected
     today (§2 census), future decks with a scaled MM shape would be.
   - (c) Park: accept now and revisit when an owner deck hits it (re-run the census on each new export).
2. **Switch.**
   - (a) Fold into the existing `mm_opacity` switch (`OBED_LIVE_MM_OPACITY`) as R6–R8. **Recommended**: one rollback,
     preview inherits it, and `off` restores today's bytes, including G2's slot-4 override.
   - (b) A separate switch. It needs a guard, because R6–R8 with MMO off would drop G2's slot-4 override (the `size` proof
     fails first).
3. **Preload scope (R8).**
   - (a) Always load the next scene's slide as well. **Recommended**: one line, and retained by `unloadTextures`.
   - (b) Only when the next scene is an MM transition: narrower, more bytes and one more anchor.
4. **Dashboard preview.**
   - (a) The preview gets the fix via `patch_rendering`. **Recommended**: the author sees the same settle and build-1
     frames that go on air, at no extra cost if 2(a).
   - (b) Live only: the preview keeps the jump.
5. **Rule breadth.**
   - (a) Any geometry change, scale or translation. Covers the derived < 1 px phase error of translation-only leaves;
     no on-disk case to test it on.
   - (b) Scale only (`sx ≠ 1 or sy ≠ 1`). **Recommended (rev 2; rev 1 recommended a)**: the root cause is the padded
     scale, both evidenced leaves scale, and it ships no behaviour on an untested class. Same code size.
6. **G2 note.**
   - (a) Accept `opacityUnproven [{4,"size"}]` and `frameLen` 96 as the new on-mode baseline. **Recommended**: G2 bytes
     and sha unchanged, same fail-closed meaning.
   - (b) Reorder G2 proofs: re-pins the G2 sha and triggers re-qualification.
7. **Gate strictness.**
   - (a) HB-1, HB-2 and HB-3 blocking; HB-4 and HB-OBS report-only; the owner eyeball final. **Recommended**.
   - (b) HB-OBS blocking too, which needs an OBS session per change.
8. **Mid-move look** (new in rev 2). The fix trades a 2.8 px snap at the next advance for a blend during the move (edges
   ≤ 2.1 px apart mid-move, §3.3). Native Keynote cannot be compared (hands off).
   - (a) Owner eyeball of fix vs stock at speed and stepped (§5.7) is the acceptance test; any visible ghosting → (b) or 1(b).
     **Recommended.**
   - (b) Blend only over the last part of the move (mix = clamp((Z − z0)/(1 − z0))): less mid-move mixing, a faster late
     crossfade. One more token in R7; not measured.

## 8. Unverified / out of scope

- Native Keynote's rendering of this move (hands off Keynote). The `.key` geometry via keynote-parser (the export's JSON
  and PDF agree).
- 3→4 at 1440/1600: the instrument is limited there.
- Destination-load latency on large decks.
- MO-1 settle residual with the fix.
- Paint oracle, V arms, P2 adversarial.
- Managed OBS with the fix.
- A looping deck's last→first MM, which stays stock by design.
- Mid-move look / ghosting (derived bound only); the fixed arm's doubled right-edge 2nd difference.
- R8's earlier pdf.js render overlapping a fast advance (cadence).
- MO-4 / M3 re-casts: derived from the code and the OBS Y plane, not yet run.
- HB-1 CvC at 1440/1600.
- Not in scope: MMs whose `contents` crossfade Keynote already ships (already exact); non-MM WebGL effects.

## 9. Critique r1 (Opus HIGH, 2026-09-25)

Checked: arithmetic re-derived from `effect_1_to_2.json` (green end quad 789.000/673.000/353×313, sentinel 542/721/181×161;
content edges match `predicted-geometry.txt`); all three anchors `count == 1` at the cited offsets; MMO∘HB == HB∘MMO
(sha `1c779a82…`); `UC.textureManager`/`R` scoping; `textureAssets` is filled only after the render promise; OBS spot-check
(§1.4) reproduced every green edge exactly and with a second estimator.

| # | Finding | Class | Change |
|---|---|---|---|
| 1 | MO-4 `liveGreenEqual` (exact on-vs-off pixels at `ROI_TOP` x 793) fails with the fix: col 793 is in today's GL edge ramp (OBS Y 45 vs DOM 50). Missed in rev 1. | new-class | §3.4, W3, §5 |
| 2 | Managed-OBS M3 edge fidelity (enforced) compares the edge band to the mm-off twin's old geometry; fails by construction. Missed in rev 1. | new-class | §3.4 re-cast, W3, §5.7 |
| 3 | Engagement is timing-dependent (queued key → never engages). Twin-compared harnesses could flake between 96/88 and `size`/`rest-opacity`. | new-class | §3.4, HB-1 premise |
| 4 | Mid-move pixels change (blend); rev 1 called it "smooth" from a metric that is linear in the blend and at the ±0.2 px instrument floor, without a CvC. Ghost bound derived; owner-visible trade. | closed-class (claim overstated) | §0, §3.3, HB-3 → report-only, decision 8 |
| 5 | W2 and W3 both edited `managed_obs_qualify.py`. | closed-class | §6 |
| 6 | No owner deck is affected (census): the accept option was under-costed. | closed-class | §0, §3.5, decision 1 (b)/(c) |
| 7 | Rule breadth: translation-only has no padded scale; recommending it ships behaviour on an untested class. | edge-case | decision 5 rec → (b) |
| 8 | R8 "adds memory": retention window is unchanged; the real change is when pdf.js renders (before the move). | edge-case | §3.4 |
| 9 | Loop wrap: slide 0 is retained on a 2-slide loop deck, so it can engage there. | edge-case | §3.4 |
| 10 | "DOM = authored" is established against the export (JSON+PDF), not the `.key`; 3→4 corroborates the mechanism. | edge-case | §0 wording |
| 11 | The end-to-end positive control is the known-bad matching the prediction; the shift control only tests the scorer. | edge-case | §1.4 |
| 12 | Tuple and error text still say "opacity" once R6–R8 are appended. | edge-case | §3.4 |

Holds: root cause, the (b)/(c) candidate rule-outs, anchor safety, MMO composition, G2 fail-closed meaning, continuity
core / 3→4 / freeze untouched, HB-1 margins and load independence.

## 10. Review log

- Critique r1 (Opus HIGH, plan): §9 above.
- Code review Opus r1 (raw round deleted at merge; `git show 45290c5f:.agents/reviews/handback-geometry/opus-r1.md`): 4 minor
  (HB-2 `frameLen`, engagement on every patch-on G2 session, partial-run PASS, settled-GL premise) folded in `572d1fbf` / `7b260aa6`; nits
  kept (R6 walk ignores hidden ancestors/transforms, `W` reuse, per-setup texture never freed like stock).
- Opus r2 (same file): R8 3b correct on the real bytes; r2-2/r2-3 doc fixes folded `e46ac0e7`; r2-1 (`A.events` guard) kept, real scripts always have it.
- Gates: `.agents/reviews/handback-geometry/gates-r1.md` — headless r1 (P2 bridge-off red → decision 3b), r2 (green), managed OBS r1 PASS,
  owner eyeball PASS.
