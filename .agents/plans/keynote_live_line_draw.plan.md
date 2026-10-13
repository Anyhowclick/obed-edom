# Keynote live: Line Draw builds draw along their path (plan, rev 6: owner go 2026-10-13; implemented on `claude/keynote-live-line-draw`)

## 1. Finding (2026-10-13)

Owner report: slide 2 of `Alpha_DSK.key` (the Line Draw build) differs from Keynote's native player.

- **Export data** (`…/7e3c9301…-p3-r1`, slide 2, event 0): one click starts a chain of three builds:
  1. `com.apple.iWork.Keynote.LineDraw`: the cyan outline around "God". `direction` 31, `sfx-action-acceleration` 3, 0.8 s.
  2. `com.apple.iWork.Keynote.LineDrawForLine`: the curved arrow to the label. `direction` 51,
     `KNBuildCustomAttributesIncludeEndpoints`, 0.7 s.
  3. `apple:dissolve`: the "Elohim (Plural)" label, 1.0 s. This is authored and correct.
- Keynote's exporter bakes both Line Draws as a plain fade. Each one is a single textured leaf (`textureType` 5, a PDF page)
  whose animation group is `opacity 0→1 EaseInEaseOut` plus `hidden false→false`. The exporter keeps the vector data next to
  the texture: `texturedRectangle.shapePath` (texture-local), `repGenerationDictionary.{infoShapePath, strokeWidth 5,
  strokeColor, infoGeometryPosition/Size}`. The stock player never reads it for this effect name.
- **Headless repro** (`LiveOutputHost`, `continuity="off"`, mm_opacity on, `show` first): the three CSS animations
  `layer30-opacity`, `layer33-opacity` and `layer36-opacity` run one after another (0–0.8 s, 0.83–1.53 s, 1.53–2.53 s).
  At mid-build the outline is complete and semi-transparent. **Our patches do not cause this:** the stock export does
  the same, because the fade is in the exported data.
- **Outputs:** every one of them. The build is a CSS animation of the exported data, so HDMI Chrome, the managed OBS Keyer
  (CEF), external attach and Build Preview all fade.

## 2. Proposal

The change lives in the shared, count-checked replacement tuple. `patch_player(mm_opacity=True)` (live) and
`patch_rendering` (Build Preview) both apply it, so the two render the same way. `main.js` on disk stays untouched
(owner rule 2026-09-21). The existing pins stay as they are: live off = the observation-only player, Preview off = stock
bytes. The on and rendering pins of both `SUPPORTED_PLAYERS` move in this PR. D1–D4 and R1–R8 behaviour does not change.

**Coordinates.** Everything below is in texture-local authored units: `shapePath` space, which matches the leaf's
`width`/`height`. For example, the rectangle path starts at (20.83, 3.54); `infoShapePath` is not used. The backing canvas
maps as `k = canvas.width / leaf.width` (and the same for height). Stage and DPR scaling stay the player's own transforms
on the leaf element; the patch never applies them itself.

### 2.1 Admission (fail closed to today's fade)

All of the following must hold. Any failure, at setup or on read-back, leaves the effect and the leaf untouched.

- **Effect.** A `buildIn` named `com.apple.iWork.Keynote.LineDraw` or `…LineDrawForLine`, with exactly one textured leaf
  (`textureType` 5, `isBackgroundTexture`, `contentsRect` 0,0,1,1, identity affine and sublayer transforms, scale 1,
  rotation 0). `masksToBounds` is false on the leaf and on every ancestor layer of the effect, so nothing can clip the
  overlay's swept bounds.
- **Timing.** The leaf's group has a finite `beginTime` with 0 ≤ `beginTime` ≤ 1e-6 (Alpha's is 1e-100), a finite
  positive duration, `timeOffset` 0, `repeatCount` 0, no `autoreverses`, and a
  duration equal to the effect's. Its children are exactly `opacity 0→1` (`EaseInEaseOut`) and `hidden false→false`.
  Each child has `beginTime` 0, `timeOffset` 0, `repeatCount` 0, no `autoreverses`, `additive` false, no `keyTimes`
  and the group's duration. `sfx-action-acceleration` is 3.
- **Path.** `shapePath` has exactly one drawable contour: `MoveTo`, then only `AddLine`/`AddCurve`, an optional
  `CloseSubpath`, and a trailing empty `MoveTo` that is ignored. Every coordinate is finite. `strokePattern` is empty and
  `strokeWidth` > 0.
- **Direction and endpoints:**
  - `direction` 51 (Start to End) on an open contour.
  - `direction` 31 (Clockwise) on a closed contour with positive signed area in y-down coordinates, so it is drawn in path
    order.
  - Endpoints are either none, or `headLineEndIdentifier: "filled arrow"` with `KNBuildCustomAttributesIncludeEndpoints`
    and no tail end.
  - Nothing else is admitted until a deck measures it.
- **Coverage, checked on the texture's pixels once the canvas has its pixels.** Every pixel with alpha > 0 lies either
  within the stroke band (`strokeWidth / 2` + 1.5 px of the path) or, for an arrow, in the head region `R` (§2.3).
  Interior fills, and text or artwork away from the head, fail this check. This is a necessary condition only: artwork
  joined to the head is caught by §2.3's shape check, not by coverage.

- **Implementation additions (review r1/r2; all fail closed to the stock fade):**
  - No layer above the leaf in the effect may be animated.
  - `LineDrawForLine` without endpoints is refused.
  - `LineDraw` with `direction` 51 on an open path is refused.
  - **Setup budget:** at most 2e6 texture pixels and at most 5000 flattened path segments. Each limit is checked
    separately.

### 2.2 Draw: one owned canvas, no SVG and no CSS mask

- **Setup.** When the player applies the leaf's CSS animation (`NB.applyCssAnimation`), the patch does three things:
  - It sets the `layerN-opacity` animation's keyframes to a constant 1. The CSS animation keeps running and becomes the
    clock.
  - It hides the leaf's own canvas (`visibility: hidden`).
  - It inserts one overlay canvas, owned by the effect, next to it in the same wrapper. The overlay is sized to the union
    of the leaf's bounds and every sampled head pose (§2.3), so a pose near the start is not clipped.
  If any of these steps fails, the patch reverses the whole setup.
- **Each frame (rAF).** The patch reads `currentTime` from the player's own `layerN-opacity` Animation object and
  computes `p = ease-in-out(clamp(currentTime / (1000 · effect.duration), 0, 1))`. `currentTime` is in ms and the
  export's duration in s. While `currentTime` is unresolved (pending), the patch draws nothing new and keeps the last
  frame, which is the empty `p = 0` state at setup. It redraws the overlay:
  - **Body.** The source texture, kept to the band revealed so far. The mask is a `Path2D` stroke of width
    `strokeWidth + 3` (the coverage band), with `lineCap` `butt` and `lineJoin` `round`, and a line dash from 0 to the
    body front (`q` for a plain shape, `a − d` for an arrow, §2.3). It is composited `destination-in`. Two extras are
    unioned into it: once the front is above 0, a disc of the band radius at the path start (this covers the start's
    anti-aliasing), and once the front reaches the end of the body, the whole body unmasked.
  - **Identity check (setup).** The full-reveal mask is run through this same compositor and must reproduce the body
    byte for byte. This checks the actual masking step, not only the extraction (Astra r3). If it fails, the stock fade
    plays. Both of Alpha's shapes must pass, as positives.
  - **Head (arrows only).** The head piece at its pose for `q` (§2.3).
  A paused, seeked or slowed player animation therefore carries the draw with it. Nested builds bind on their own
  application (`PB.handleEffectDidComplete` starts them later), so each effect keeps its own clock.
- **Hand-back and cleanup.** When the animation finishes, is cancelled, or the leaf is disconnected, the overlay and its
  rAF go and the leaf canvas becomes visible again. The final frame is therefore the stock texture, byte for byte. The
  last overlay frame actually presented may be at `p < 1`, so the visible step at hand-back is at most one frame of
  progress. §3 measures that step separately from the `p = 1` reconstruction.
  Nothing stays in the document afterwards: no defs, no masks, no `Animation`. This also keeps D4's freeze admission
  unaffected, since that check reads every element. Hide and show touch nothing: the build keeps running under the hidden
  output, and show reveals the current progress.

### 2.3 Arrowhead (owner Q3: the head is there from the start, riding the tip)

Measured on Alpha's line:
- The path ends at the shaft endpoint `E` = (34.63, 8.86). Its last segment, from (32.24, 9.60), is straight.
- The visible tip `T` is about (46.9, 5.1), 12.8 authored px beyond `E` along the end tangent.

Measured further by Astra r2 (from the PDF's filled-path operators, texture-local, y down):
- The rear corners of the head are (30.39, 20.85) and (24.35, 1.36), 7.6 px behind `E` along the end tangent
  `u` = (0.955, −0.296).
- The last straight segment is only 2.5 px long, so the head covers part of the curve.

A straight cut cannot separate this head, so the split is a convex region instead.

**Split.**
- **Wing pixels.** These are the pixels with alpha > 0 that lie outside the shaft band (`strokeWidth / 2` + 1.5 px of
  the path). §2.1's coverage check has already confined them to the head.
- **Head region `R`.** `R` is the convex hull of the wing pixels' corners: each pixel is treated as a unit square, so
  edge pixels are inside it. A pixel belongs to `R` when its centre lies in the hull.
- **Pieces.** The head piece is the texture inside `R`. That covers the filled head, every anti-aliased edge pixel and
  the stretch of shaft under the head. The body is the texture outside `R`.
- **Recomposition check.** Since the two pieces are complementary, they recompose the texture exactly at identity.
  Setup checks this on the canvases (head + body == source, byte for byte).
- **`d`.** This is the arc length of the path inside `R`, from where the path enters `R` to `E`. It is about 7.6 on
  Alpha's line.

**Head-shape check (admission; the narrow "filled arrow" test).** This compares the head with the shape it ought to
be, catching missing pixels and extra pixels alike. It replaces rev 5's symmetry test, which measured 0.83 on the
owner's arrow (Astra r3) and would have refused it.
- **Reference triangle.**
  - Apex: `R`'s pixel furthest along `u`.
  - Rear corners: `R`'s two extreme points on either side of the axis through `E`.
- **Reference shape.** The triangle is rasterised the way the player's canvas is (centre-in-polygon, unit squares), and
  joined with the shaft band inside `R`.
- **Admit when:**
  - the symmetric difference between that reference and `R`'s pixels with alpha > 0 is at most `X` pixels;
  - the apex lies within 1 px of the axis and ahead of `E`;
  - the path enters `R` exactly once;
  - `R` holds no band pixel whose arc length is under `L − d − strokeWidth`.
- **`X`.** It is set at implementation as the owner's arrow's measured value on the real Chrome canvas, plus a recorded
  margin of at most 25 % of it. This bar is never loosened later to admit a deck.
- **Calibration (2026-10-13).** The owner's arrow measured 31 on Chrome 155 (headless `LiveOutputHost`) and 39 on CEF
  127 (managed OBS). The two engines rasterise the PDF texture differently, and a bar of 38, calibrated on Chrome only,
  refused the arrow on the Keyer, which then faded. `X` = 48: the maximum over the two qualified engines (39) plus
  23 %.
- **Admission table.** The table gains two refusals: a symmetric diamond head (excess pixels behind the rear corners)
  and paired protrusions.

**Pose.** `L` is the path length, `q = p·L`, and `a = max(q, d)`.
- The head piece is a rigid body anchored at `E`. `E` is placed at `s(a)` and the piece is rotated by `θ(a) − θ(L)`,
  where `θ` is the path tangent angle. `T` therefore keeps its authored 12.8 px lead ahead of the anchor.
- The body reveals arc `[0, a − d]`. This is where the head's stretch of shaft starts in the moved pose, so the head's
  rear meets the body. Because the stub is rigid, the join is exact on a straight path. On Alpha's curve the residual is
  measured by the attachment gate (§3).
- At `q = L`: `a = L`, the anchor sits at `E` with zero rotation (the identity), and the body is fully revealed outside
  `R`. The composite equals the source.
- When `q < d` (the first frames), the head and its stub sit at the path start. This matches Keynote showing the head
  from the start.

### 2.4 Out of scope

Other builds the exporter degrades; tail or double arrowheads; other end styles, directions or accelerations; the
chained Dissolve, which is already correct.

## 3. Gates

Minimal, pixel-based. Every check is made on captured frames, never on the patch's own state.

- **Unit (one test file):**
  - Replacement counts on both `SUPPORTED_PLAYERS`.
  - The new on and rendering pins; the off pins unchanged.
  - Plan-sha and the continuity corpus unchanged.
  - One table of admission refusals: fill, a second contour, `keyTimes`, another direction, a tail arrow.
- **Headless probe** (`scripts/line_draw_probe.py`, Alpha_DSK slide 2, per-frame screencast), checked against the stock
  textures:
  - **Body reveal.** Path samples whose band pixels match the source give the stationary body's revealed arc length.
    It must match the expected front within one frame: `q` on the rectangle, and `max(q, d) − d` on the arrow (Astra
    r3). Excluded from the comparison: the moving front's anti-aliasing band (one band radius) and, on the arrow, the
    moving head piece, which is scored separately.
  - **Arrow.** The head piece is template-matched over each frame with a rotation search, giving tip position, angle and
    integrity. Tip and angle must match the expected pose within 1 px and 2°, with correlation ≥ 0.95. The gap between
    the shaft and the stub must be ≤ 1 px. If Alpha's curve leaves a larger rigid-stub residual, the measured value goes
    to the owner with a frame, rather than the threshold being loosened.
  - **Hand-back.**
    - A probe-only splice holds the `p = 1` composite for one capture. In the leaf ROIs, outside the pixels covered by
      later builds in the chain (the label's Dissolve overlaps the arrow's tip), that frame is within 1 LSB per channel
      of the stock frame.
    - Implementation deviation (2026-10-13): the plan said "equals". The first Chrome run measured 8 anti-aliased shaft
      pixels off by exactly 1 LSB (canvas compositing rounding) and a natural hand-back step of 0, so the bar is ≤ 1
      LSB. The owner rules on this at review.
    - The natural last presented overlay frame differs from the first stock frame by no more than one frame of
      progress. This is the visible-pop check.
    - The end frame equals the `off` arm's end frame exactly.
  - **Controls.** The `off` arm must fail the reveal check (it is a uniform fade). A `head-static` splice must fail the
    pose check. A `head-notch` splice (head cut by the shaft band) must fail integrity.
  - **Lifecycle.**
    - Hide mid-build, then show: the build resumes at its current progress.
    - Teardown is tested by fault injection that reaches the renderer's destruction path (`NB.destroy`), mid-arrow. The
      probe asserts the disposal happened before the build's own deadline. After it there must be no overlay, no
      further redraws and no extra element.
    - Ordinary go-to while the player is busy is still refused, by both the host and `jumpToScene`. That is a separate
      expectation and does not count as cleanup.
  - **Neighbours.** The label Dissolve is unchanged. A qualified movie Dissolve that plays after a Line Draw keeps its
    freeze (P2 fixture, with a Line Draw slide added in a scratch copy).
- **Keyer:** under managed OBS, `GetSourceScreenshot` frames of the AK source must show partial reveal mid-build and the
  stock end frame afterwards. A DOM measurement inside CEF alone does not count.
- **Owner's eye:** slide 2 on Chrome and on the Keyer, against Keynote native. Keynote stays hands-off, so the owner
  provides the native side.

## 4. Owner decisions (2026-10-13)

- **Eye gate for the arrowhead (after implementation).** On the live run `g2`, the automated pose check could not tell
  the correct build (tip 3.6 px, angle 6° at the search edge, correlation 0.83) from the 2 px / 3° head-offset control
  (3.0 px, 6°, 0.82) at the headless capture size. The owner chose the eye gate:
  - The arrowhead's pose is judged by eye. The owner passed slide 2 on Chrome and on the managed-OBS Keyer.
  - Removed from the probe: the template pose, correlation, tip, angle and attachment checks, and the head-offset and
    head-notch arms.
  - Kept: body reveal; the `off` and head-static controls; the diamond and protrusion refusals; the held `p = 1` and
    pop checks; end equals `off`; the label rect; hide and show; destroy; busy.
- **Recorded deviation: body allowance.** The tolerance is 2 median frames + 4 % (0.0817 on the box). On `g2` the box
  measured 0.0448, against the plan's one-frame bar of 0.0208.

- **Q1:** the problem is that the shapes fade in instead of drawing.
- **Q2:** Clockwise and Ease In & Out on the rectangle (0.8 s); Start to End with Include endpoints on the line (0.7 s).
  Mapping in §2.
- **Q3:** the arrowhead is there from the start of the line's build, travelling at the tip, after the box (native frame
  in the session). See §2 "Arrowhead".
- **Q4:** shares the `mm_opacity` switch.

## 5. Critique log

- **r1:** Codex GPT-6 Astra, high effort, read-only, 2026-10-13. Findings: 2 blockers, 4 majors, 2 mediums; all
  folded in rev 4. Sound areas it confirmed: DOM and pixel access (`NB.addNode` copies the finished PDF.js canvas
  synchronously), the direction and easing mapping, and scope versus G2.
  - B1: the path ends at the shaft, not the tip → §2.3 attaches the head at the rear cut point with the tip offset.
  - B2: an extraction cut by the band notches the head → §2.3 half-plane partition, checked on the canvases.
  - M3: clock → §2.2 reads the player's own Animation each frame.
  - M4: hide and go-to lifecycle → §2.2 hide touches nothing, §3 fault-injected teardown.
  - M5: admission → §2.1.
  - M6: the oracle measured the centroid → §3 tip, angle, integrity and attachment, from pixels, plus the Keyer
    screenshot.
  - m7: leftover SVG resources → §2.2 one owned canvas, with nothing left afterwards.
  - m8: Preview route and pins → §2 preamble.
- **r2:** Codex GPT-6 Astra, high effort, read-only, 2026-10-13. It confirmed r1's M3, M6, m7 and m8 as closed. B1, B2,
  M4 and M5 were not closed. Its new findings were 2 blockers, 1 major and 3 mediums; all are folded in rev 5.
  - B (closed class): a half-plane cut refused the owner's arrow, because the head lies 7.6 px behind `E` over the curve
    → §2.3 convex-hull region `R`, `d` = arc length inside `R`, and the arrow-shape check.
  - B (closed class): anchoring the rear point moved the head forward by `d` → §2.3 anchors at `E`, with the body
    revealed to `a − d`.
  - M (closed class): `jumpToSlide` also refuses mid-build → §3 fault injection through `NB.destroy`, with a deadline
    assertion.
  - m (new class): ms versus s → §2.2.
  - m (closed class): alpha > 0, child timing, `masksToBounds`, coverage that is necessary but not sufficient → §2.1
    and §2.3.
  - m (new class): the terminal frame is not guaranteed to be presented → §2.2 and §3 (a held `p = 1` capture plus a
    separate pop check).
- **r3 (the last plan round):** Codex GPT-6 Astra, high effort, read-only, 2026-10-13. It confirmed as closed: the anchor
  at `E`, `NB.destroy` teardown, ms versus s, and the held terminal capture. The convex hull admits the path once, with
  `d ≈ 8.09` (not 7.6), the apex 0.65 px off-axis, and path locality passing. Its independent PDF.js/Skia raster puts the
  rigid stub's centreline residual at ≈ 1.08 px; the attachment gate measures the visible join. Findings: 1 blocker,
  1 major and 3 mediums; all are folded in rev 6.
  - B (closed class): wing symmetry IoU of 0.83 refuses the owner's arrow → §2.3 reference-triangle comparison, with `X`
    calibrated on the positive.
  - M (closed class): the body oracle expected `q` on the arrow → §3 expects `a − d` and excludes the moving front and
    the head.
  - m (new class): identity was not proven through the mask → §2.2 mask width, caps, start disc and full reveal, checked
    through the real compositor.
  - m (closed class): symmetric attached artwork → §2.3 symmetric-difference check, plus diamond and protrusion refusals.
  - m (edge case): a negative group start → §2.1 requires 0 ≤ `beginTime` ≤ 1e-6.
  - Noted, not folded (scope): the player chains builds with `setTimeout`, so a paused leaf does not pause the chain.
    The host has no pause, so the owner's eye cannot see this.
