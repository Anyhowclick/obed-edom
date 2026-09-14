# Borderlands style — Astra review and implementation plan

Date: 2026-09-14  
Review target: the staged `drop-liberty` worktree, based on `8bd6197b04042f2d3def38f79a56ce482f7d8f1b`  
Worktree: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty`  
Status: reviewed implementation plan; production changes have not been made by this review.

## 1. Review decision

Proceed with a revised version of the proposed direction. Reducing façade strokes is the right visual goal, but removing the zoom-16 cap and simplifying every footprint is insufficient. The first implementation phase should correct coordinate precision and occlusion. Those defects can make even a simple building look messy, and reducing the number of lines would otherwise conceal rather than resolve them.

The selected direction is:

1. Keep the existing filled 3D buildings as the geometric authority.
2. Draw correctly positioned, depth-tested ink against those buildings.
3. Keep continuous outer roof contours, with only conservative simplification that remains visually coincident with the underlying roof.
4. Draw vertical ink at a small number of genuine architectural corners. Do not turn every point on a curved footprint, or every point created by a simplifier, into a vertical stripe.
5. Omit decorative inner-ring ink and retain the current suppression of shallow elevated roof/floor panels.
6. Rebuild from an authoritative current source snapshot after the camera settles. Eliminate the historical zoom-16 freeze and feature-count heuristic.
7. Preserve and strengthen the staged export-flush and fragment-deduplication fixes.
8. Tune softer, thinner ink only after geometry and depth are correct; verify actual LW, FW, and CG captures as well as the live preview.

This is a targeted rendering/style repair. Matching the last reference's hand-painted trees, façade textures, and custom modeled architecture is a separate art direction and asset project.

## 2. User intent and interpretation of the references

The user wants fewer, cleaner lines on roofs and building exteriors, with the last reference as the primary visual target. The comparison images are evidence of the problem and historical appearance; they are not instructions to recreate every line visible in an older screenshot.

| Reference | What is visible | Consequence for the implementation |
| --- | --- | --- |
| 1 — dense downtown buildings | Many closely spaced vertical strokes on curved towers; crossing and doubled lines around lower buildings; distant areas become black clusters. | Reduce eligible vertical corners, eliminate hidden-line bleed-through, and verify precision before changing the fill geometry. |
| 2 — curved/stepped waterfront structure | A blocky inherited extrusion is strongly emphasized by repeated long vertical strokes. | Generic ink rules can reduce emphasis, but cannot make a 2D-footprint extrusion into an accurate wheel/model. Do not promise a geometric reconstruction. |
| 3 — Suntec convention hall | A mostly quiet roof with a small number of roof-crossing and exterior strokes; surrounding towers are still striped. | Preserve the broad hall silhouette and quiet roof. Check whether the remaining lines are real seams, occluded geometry, or offset ink. |
| 4 — older Suntec view | A dense roof grid and dark perimeter, with a different overall palette/rendering state. | Do not infer a zoom-only cause from this image. The source actually contains many elevated roof panels. Restoring the grid would oppose the requested sparse treatment. |
| 5 — desired illustration | Pale roof planes, muted sides, thin charcoal outlines, restrained vertical accents, and substantial unmarked surfaces. Trees and textures contribute to the look. | Prioritize calm roof planes, a clear outer contour, and a few structural corners. Treat trees, painterly texture, and custom architecture as reference context rather than implied requirements. |

Reference files:

- [Reference 1](/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-d1bbc402-eed8-4fa7-80f9-855077b8bfc3.png)
- [Reference 2](/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-c73533db-cbc5-449f-86fa-5e74c535b0db.png)
- [Reference 3](/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-4bf9343b-c453-4d96-8da1-272e26c3ad12.png)
- [Reference 4](/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-fd5e0be8-e0bc-4ca5-aa28-8a530bc26faf.png)
- [Reference 5](/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-1f95ab15-6f60-4cd3-9578-5a991054a80e.png)

The clipboard paths are temporary. Before a later visual implementation session, preserve the supplied references in that session's review artifact directory if they still exist. Do not add those third-party screenshots to application assets or ship them in `dist`.

## 3. What was verified

### 3.1 Inspected scope and baseline

The review read the four Borderlands modules, the capture integration, style resolution, building visibility handling, preview/export scaling, the two Borderlands test files, the installed MapLibre 6.7.0 implementation, cached Liberty/TileJSON documents, and the cached Singapore vector tile.

The staged Borderlands files and thumbnail are now in the index. The earlier report that they were all untracked is no longer the state of this worktree. There are already staged generated dashboard assets and unrelated-to-this-repair Liberty migrations. Preserve that entire baseline.

Focused baseline verification on 2026-09-14:

```text
node --test dashboard/tests/borderlands-ink.test.cjs dashboard/tests/borderlands-style.test.cjs
11 tests passed; 0 failed.
```

The verified runtime was:

```text
/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node
```

The default `/usr/local/bin/node` is too old for `--test`. No full dashboard suite, browser rendering, new export, or performance benchmark was run as part of this planning review. Existing tests passing establishes the baseline; several currently assert the behavior that this repair needs to replace.

### 3.2 The zoom-16 explanation needs correcting

`borderlandsInkPolicy.ts:1–10` caps the rebuild key at zoom 16 and rounds longitude/latitude to three decimal places. `borderlandsFacade.ts:102` accepts `_zoom` but does not use it. Therefore, the cap currently limits cache invalidation; it does not request or generate a deliberately simplified z16 outline.

The cached `output/.maps/tile-cache/planet.json` declares `maxzoom: 14`. Its tile set is `planet/20260906_080001_pt`. The cached Liberty style points its building layer at that source. On this inspected configuration, a z17 or z18 map view does not imply z17 or z18 source geometry. Higher map zooms overscale the source; pitch and viewport changes can also change the source tile coverage.

Consequently, the earlier claim that a later pan necessarily fetches more detailed z17+ building tiles is not supported by the inspected data. The cap can still produce history-dependent or stale ink, but it is not a demonstrated explanation of roof tessellation.

The same camera should produce the same ink after a cold load, a zoom from below 16, a zoom from above 16, and a pan away and back. That is the behavior to fix and test.

### 3.3 Excess vertical lines are directly explained by the planner

`borderlandsFacade.ts:109–125` draws a roof stroke for every retained ring edge and a vertical stroke at every retained vertex. There is no corner-angle test, spatial separation, or per-footprint post budget. The only short-edge threshold is 0.4 m.

For a 96-point curved footprint, the current planner can create roughly 96 full-height stripes. Simplifying that footprint to 16 points and adding posts to all 16 would still produce 16 artificial ribs. Roof contour simplification and vertical-corner selection must be separate operations.

`ringsOf()` flattens `MultiPolygon` members and their holes into one undifferentiated list. This makes inner courtyards, holes, and outer contours receive the same outline-and-post treatment.

### 3.4 Close zoom deliberately exposes hidden ink

`borderlandsInk.ts:320–327` applies a clip-space depth bias of 0.003 or 0.012, a negative polygon offset, and disables `DEPTH_TEST` entirely at map zoom 17.8 and above. At those zooms, rear/hidden building lines can draw through foreground roofs and walls.

The hypothesis that this contributes to the screenshot's crossing lines is strong because the rendering behavior is explicit in the code. Its exact visual contribution still needs an A/B render at the user's camera.

MapLibre's custom `renderingMode: "3d"` is intended to share the depth buffer with other layers. The installed renderer already gives the custom layer a 3D depth mode. Preserve that behavior instead of defeating it at close zoom. [MapLibre custom-layer contract](https://maplibre.org/maplibre-gl-js/docs/API/interfaces/CustomLayerInterface/)

### 3.5 Coordinate precision is a root-cause candidate, not a cosmetic detail

`mercator()` produces global Mercator coordinates near x ≈ 0.788 and y ≈ 0.496 for Singapore. `commit()` immediately places them in a `Float32Array`. The shader also receives a projection matrix that `asMatrix()` has converted to Float32 before any local translation.

At these magnitudes, adjacent Float32 x values are approximately 2.385 m apart on the ground; adjacent y values are approximately 1.193 m apart. Those are representable spacings, not a claim that every vertex has exactly that error. The current 0.4 m wall outset can be lost or distorted by this quantization.

The installed MapLibre 6.7.0 `mercator_transform.ts:903–928` deliberately supplies a Float64 custom-layer matrix so callers can apply further transformations before converting it for WebGL. The current ink path discards that advantage. Local coordinates and a translated matrix should come before increasing depth bias or simplifying away misalignment.

### 3.6 Suntec's roof grid exists in the data

The cached tile at `output/.maps/tile-cache/planet/20260906_080001_pt/14/12918/8133.pbf` was decoded during this review. It uses vector extent 4096 and contains 678 building features.

| Observed feature | Geometry | Heights | Relevance |
| --- | --- | --- | --- |
| `5913018512` | One Polygon; one 13-point closed ring | top 28 m, base 0 m | Main convention-hall footprint in the inspected Suntec area. |
| `3930904030` | MultiPolygon with 71 polygon members; 333 total stored points | top 33 m, base 28 m | The roof-panel grid over the hall. |
| `40399360` | MultiPolygon with 338 polygon members, 339 rings, 2365 stored points | top 5 m, base 0 m | Demonstrates that one source feature can contain many disconnected buildings/parts across a tile. |

The current `buildingExtents()` already rejects elevated slabs whose rise is below 6 m. The Suntec grid rises 5 m, so this exact cached grid is already excluded from the current ink planner. The grid can remain present in the filled extrusion geometry, and historical screenshots may reflect earlier ink rules. Record those distinctions in the implementation report rather than attributing every observed line to a stale z16 mesh.

### 3.7 The wheel is assembled from many extrusion parts

In the cached Singapore Flyer area, the building source includes a low stepped base and multiple narrow polygons with different top/base pairs, including 161/19 m, 162/18 m, 163/17 m, 164/16 m, and 165/15 m. Several are five-point rectangular rings.

A per-ring corner cap cannot turn that collection into a smooth wheel: each narrow rectangle already has few corners. Precision, occlusion, short-leg eligibility, and softer ink will reduce emphasis, but the stepped solid geometry remains inherited from the source. Do not add an OSM-ID-specific wheel exception in this repair.

### 3.8 Feature count and feature ID are not building identity

Because a single source feature can hold hundreds of disjoint polygon members, the present `MAX_FEATURES = 1400` is not a useful bound on either buildings or stroke count. A future per-feature limit of eight lines could accidentally give eight lines to an entire tile's collection of low-rise buildings.

Count and budget each connected outer footprint independently after geometry normalization. Preserve the source ID as provenance and a possible fragment-assembly hint; do not equate it with one physical building or one architectural object.

### 3.9 The previous two findings are partly addressed, with follow-up work needed

The staged `waitIdleForFrame()` now calls `waitForBorderlandsInk()`, which synchronously flushes the pending rebuild and requests another render. That closes the basic 80 ms debounce race. However, its 100 ms timer resolves successfully even if no new render occurs, and cancellation is checked only before the wait. The stronger acceptance contract is a confirmed render of the requested mesh generation, with cancellation and timeout surfaced as errors.

The staged `inkFragmentKey()` now includes geometry samples, so it can retain the two simple tile fragments in the existing test. Its fingerprint uses only ring length, first point, middle point, and last point; it ignores the other vertices and the rendered heights. Different geometries can still collide, identical geometry with a changed starting point can evade deduplication, and vertically distinct volumes must not collapse into one another.

Source queries can return split or duplicated geometry and include features irrespective of whether the style renders them. The plan therefore requires complete fragment identity and explicit building eligibility. [MapLibre source-query contract](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#querysourcefeatures)

## 4. Goals, boundaries, and success definition

### Goals

- Buildings read first as simple volumes with quiet roof planes.
- Outer roof contours remain aligned with the actual extrusion at every supported camera and surface.
- Smooth curves are not converted into vertical pinstripes.
- Major corners remain understandable on rectangular, L-shaped, and stepped buildings.
- Hidden surfaces do not print through foreground buildings at any zoom.
- The final result depends on current camera/source state, not the route taken to reach it.
- Still and movie capture include the correct, rendered ink state.
- Building visibility, style switching, and cleanup remain reliable.
- Work remains testable without live network requests for deterministic geometry cases.

### Non-goals

- Rebuilding or replacing the OpenFreeMap/Liberty extrusion mesh.
- Making an accurate Ferris-wheel model from building polygons.
- Adding trees, façade hatching, rooftop furniture, shadows, animations, random sketch wobble, or new controls.
- Changing other styles, Liberty-to-3D document migrations, map cameras, layer filters, or export dimensions.
- Merging nearby buildings merely because they share a colour, height, or bounding box.
- Maintaining separate hand-tuned renderers for preview, LW, FW, CG, and movies.
- Adding a worker, generalized geometry engine, unbounded cache, or remote telemetry before measurements justify it.

### Visual success

A normal rectangular building has one roof perimeter and its significant corner posts; a detailed curve can keep many short segments to form one smooth perimeter while having no invented posts. A convention hall has a broad quiet roof. In the dense downtown scene, lowering the number and contrast of façade strokes should leave buildings individually legible without black tangles.

Do not use raw segment count alone as the visual score. Sixty segments forming one smooth curved perimeter can be visually quieter than eight full-height interior stripes.

## 5. Alternatives reviewed

| Approach | Benefit | Risk/cost | Decision |
| --- | --- | --- | --- |
| Only thin/recolour the current strokes | Very small change. | Preserves hidden-line leakage, precision error, excessive posts, and history dependence. | Insufficient. Use colour/width tuning after correctness work. |
| Preserve the z16 mesh forever | Can retain a accidentally pleasing snapshot. | Initial-load and pan history change output; coverage becomes stale; does not control the actual source LOD. | Remove. |
| Rebuild at every animation frame | Always sees the newest camera. | Expensive source queries and geometry work during interaction; can flicker as tiles arrive. | Use settled rebuilds, with explicit capture flushes. |
| Aggressively simplify only the ink footprint | Reduces segments and posts quickly. | Chords can cut across a curved roof or a recess while the filled building remains detailed. | Reject aggressive shape change. Constrain any simplification to contour alignment. |
| Simplify the filled buildings and ink together | Coherent simplified volumes. | Requires a new building source/rendering path and changes inherited architecture, heights, occlusion, and exports. | Separate future project if contour-only improvements cannot meet the target. |
| Screen-space edge detection/post-processing | Naturally selects visible silhouettes. | New render targets, projection/depth handling, export integration, and tuning; may also outline roads/text. | Too broad for this repair. |
| Select genuine corners on original contours | Directly removes pinstripes, deterministic, preserves the fill. | Needs good scale-aware corner support and regression fixtures. | Selected. |
| Merge all equal-height buildings | Removes many shared edges. | Can erase useful divisions between unrelated buildings and create huge polygons. | Reject global merging. |
| Assemble verified duplicate/clipped fragments of one rendered volume | Removes duplicate contours and artificial tile seams. | Needs topology care; source IDs may cover many disconnected members. | Use conservative, spatially local handling only; see §8. |

## 6. Rendering contract: coordinates, depth, and stroke weight

### 6.1 Local coordinates

Use a double-precision Mercator origin for each committed mesh, normally the current map centre with z = 0. Compute every segment endpoint in JavaScript double precision, subtract that origin, and only then store the local coordinates in the Float32 vertex buffer.

At render time, obtain the original full-precision `defaultProjectionData.mainMatrix`. Form `localMatrix = mapMatrix × translate(meshOrigin)` in JavaScript double precision. Convert the completed local matrix to Float32 only for `uniformMatrix4fv()`.

For column-major storage, the translation column is the only column affected by a translation-only local origin:

```text
localMatrix[12 + r] =
  mapMatrix[r] * origin.x +
  mapMatrix[4 + r] * origin.y +
  mapMatrix[8 + r] * origin.z +
  mapMatrix[12 + r],  for r = 0..3
```

Keep the other columns from the original matrix. Do not first convert `mapMatrix` to Float32, and do not add the large global origin back in the vertex shader.

Keep the mesh origin attached to the committed vertex buffer. A camera move changes the translated render matrix immediately; it need not rewrite the mesh during the gesture. A later committed mesh may adopt a new origin without changing visible positions.

Use public render inputs, not `map.transform`, private tile caches, or MapLibre renderer internals. The installed source was inspected to verify the public input's precision; it is not a dependency to patch or import.

### 6.2 Depth and placement

- Keep `renderingMode: "3d"` and depth testing enabled at all zooms.
- Keep depth writes disabled for the ink pass so strokes do not incorrectly occlude later map layers.
- Remove the zoom-dependent `DEPTH_TEST` disable branch.
- Start the corrected path with no clip-space depth bias and no additional polygon offset. Fix precision before deciding whether a residual surface offset is needed.
- Use one small, physical surface separation if required by the visual probe; do not stack three unrelated anti-z-fighting mechanisms.
- Initial tuning candidates after the precision probe: roof lift 0.08 m and wall outset 0.05 m, capped by a subpixel projected-displacement allowance at extreme close zoom. These are candidates, not values already visually approved.
- Limit the resulting projected displacement to at most 0.35 reference CSS px for visible roof edges in the required close-zoom scenes. If that cannot be maintained, use a smaller lift/outset and investigate depth alignment.
- Preserve MapLibre's depth range and comparison contract. Save/restore any GL state explicitly changed by the custom layer, including a previously null program binding.
- Reject invalid/missing projection matrices for that frame. Do not accidentally reuse a previous frame's matrix.

A line on the back of a building may disappear when depth testing is restored. That is correct occlusion, not evidence that the old large bias needs to return.

### 6.3 Near-camera robustness

The existing vertex shader clamps `clip.w` to a small positive value. A segment with one endpoint behind the camera can then expand into a very large quad. Include a pitched close-camera fixture/probe. Clip such segments to the near plane in homogeneous coordinates, or reject the invalid segment conservatively; do not project a negative-w endpoint using an arbitrary positive denominator.

This is a bounded shader correction, not a request to build a full 3D clipping framework. It is mandatory only if the required near-camera scene exercises the defect, but the shader must never emit non-finite positions or screen-spanning spikes.

### 6.4 Define width as full stroke width

The existing shader expands each side by `u_width`, so a configured value of 1.2 represents approximately 2.4 drawing-buffer pixels of full width. Rename/define the new contract unambiguously: the policy returns full width in MapLibre's reference CSS pixels, and the shader uses half of the corresponding drawing-buffer width.

Calculate effective pixel ratio from the map's actual canvas/backing-store relationship, using pre-transform layout dimensions. Do not use `getBoundingClientRect()` as the logical width because the preview applies an outer CSS scale. Verify whether `map.getPixelRatio()` already includes any GPU clamp in this MapLibre version; use actual drawing-buffer/layout ratios when that is the more accurate value.

```text
fullWidthBufferPx = fullWidthCssPx × effectivePixelRatio
halfWidthBufferPx = fullWidthBufferPx / 2
```

The same logic must be used in preview and capture. This matters because `MapView` pins pixel ratio to preview scale × device pixel ratio, whereas export surfaces use ratios 1, 2, or 4.

### 6.5 Proposed ink constants

These are starting values for the visual pass, to be recorded with before/after captures. They are not requirements to preserve if the actual reference comparison demonstrates a better nearby value.

| Setting | Initial value | Allowed tuning / reason |
| --- | --- | --- |
| Ink colour | `#4C4B50` | Neutral charcoal, substantially softer than `#141312`; tune approximately within `#414047`–`#56545A`. |
| Full width at authored z14 | 0.70 reference CSS px | Avoid dark clusters near the extrusion-entry zoom. |
| Full width at authored z16 | 0.85 reference CSS px | Main city view. |
| Full width at authored z18+ | 0.95 reference CSS px | Do not thicken indefinitely at close zoom. |
| Width interpolation | Continuous linear interpolation | Eliminate visible width jumps at 15/17 or 17.8. |
| Stroke opacity | 1.0 before edge coverage | Prefer lighter pigment over translucent overlapping strokes that darken at joints. |
| Edge coverage | About 0.5 drawing-buffer px feather | Add minimal analytical edge antialiasing if thin quads otherwise sparkle. |
| Roof lift | Start 0.08 m, subject to projected cap | Much smaller than the current 0.55 m after precision repair. |
| Wall outset | Start 0.05 m, subject to projected cap | Much smaller than the current 0.4 m. |
| Clip-space depth bias | 0 | A large normalized-depth bias is not a substitute for correct placement. |

Use authored zoom for the aesthetic width ramp, obtained from the existing per-surface zoom offset, so switching between FW/LW/CG does not silently cross unrelated styling thresholds. Use the actual map zoom/source state for layer visibility and source coverage. Keep those concepts separate in names and tests.

If analytical antialiasing is added, derive its side coordinate from the existing segment quad attributes. Use premultiplied colour when blending with MapLibre's premultiplied-alpha mode, and verify that joints do not double-darken. Do not add random jitter or a texture pass.

The initial repair keeps the existing building, water, road, and land palette. If geometry is clean but the desired illustration still needs lighter roofs or more muted sides, capture a small palette comparison as a subsequent reviewable decision. A broad palette rewrite is not necessary to evaluate the line treatment.

## 7. Geometry contract and selected corner algorithm

### 7.1 Preserve the hierarchy

Replace the flattening interpretation of `ringsOf()` with a normalized structure that preserves:

```text
source feature
  polygon member
    outer ring
    zero or more hole rings
```

Do not change the source object. Normalize into a new pure-data representation with finite coordinates, source identity/provenance, rendered base/top, and stable component identity.

A `Polygon` contributes one outer ring. A `MultiPolygon` contributes one outer ring per polygon member. Hole rings are retained as topology metadata but do not receive decorative roof loops or vertical posts in the initial sparse style.

Never flatten all outer members and then treat only the first as the building: the cached 338-component feature is a required regression fixture.

### 7.2 Validate rings before doing geometry

1. Accept only Polygon and MultiPolygon structures of the expected nesting depth.
2. Reject an individual invalid polygon member when its ring contains non-finite coordinates or cannot form a valid contour; do not bridge across missing coordinates.
3. Remove consecutive duplicate coordinates and the redundant final closing point for internal processing.
4. Restore closure exactly once when emitting a closed ring.
5. Require at least three distinct, non-collinear points and a positive absolute area. A three-corner building is valid geometry.
6. Normalize orientation consistently in a local metric plane and preserve hole membership.
7. Detect and reject self-intersecting output from any simplification. Do not silently repair arbitrary malformed polygons with a convex hull.
8. Treat longitude wrapping explicitly before metric calculations. Choose the local longitude copy nearest the mesh origin; do not connect points across almost a whole world.

The current test that discards every triangle is too broad. Replace it with separate tests for tiny/degenerate scraps and a legitimate large triangular building.

### 7.3 Match actual extrusion heights

The cached Liberty `building-3d` layer uses `render_height` and `render_min_height` directly. The ink should use the same evaluated physical extents.

Default recommendation: consume finite rendered numeric heights, preserve a real zero as zero, clamp the base as the rendered layer does, and omit ink where there is no rendered extrusion. Do not resurrect a zero `render_height` from a separate `height` or `levels` property through JavaScript `||` fallback.

If supporting numeric strings or OSM level fallback remains desirable, explicitly put an identical coercion/fallback expression into the Borderlands-only extrusion style and test the two contracts together. Do not support it only in the ink planner. The initial repair should favor the direct rendered-height contract already used by the source.

Retain the current aesthetic suppression of shallow elevated panels initially:

```text
base > 1.2 m and top - base < 6 m ⇒ no decorative ink
```

This preserves the already-effective suppression of Suntec's 33/28 m panels. Keep a separate substantial elevated-volume fixture, such as top 80/base 20, to prove that the rule does not erase all elevated buildings. Do not raise the threshold casually to hide other defects.

### 7.4 Metric working space

Use a local east/north plane in metres for ring area, length, angular support, spacing, and simplification. Reuse the current lightweight local conversion approach, but use one ring/component anchor and a consistent latitude scale instead of applying unrelated latitude scales to different steps.

Do not simplify raw longitude/latitude using an unqualified tolerance such as `0.00001`: its ground distance varies with latitude. Keep this pure geometry module independent of MapLibre imports so deterministic unit tests remain cheap.

Use world-space geometric thresholds to choose architectural corners. They should not change when only device pixel ratio or preview panel size changes. A render-context adapter may provide a stricter screen-error ceiling for roof contour simplification.

### 7.5 Separate two contours conceptually

- **Authoritative contour:** cleaned source outer ring, used to know where the filled roof/wall actually is.
- **Roof drawing contour:** the authoritative ring with only safe redundant detail removed.

There is no independently invented simplified building footprint. Vertical posts are selected from real source corners, even when the drawing contour omits intermediate collinear points.

For roofs, start with removal of exact/nearly collinear points. If further reduction is useful, apply deterministic closed-ring Ramer–Douglas–Peucker simplification with a maximum metric tolerance of 0.25 m and a stricter projected-error ceiling of 0.35 reference CSS px. Prefer the unsimplified contour if a safe simplified result cannot be established.

For a closed-ring implementation, choose stable anchors, split into two open chains, simplify the chains, and rejoin them. Pick the lexicographically smallest local coordinate as the first anchor and the farthest point from it as the second; use deterministic tie-breaking. Preserve protected sharp corners. Do not run the open-line algorithm against identical first/last endpoints as though that were a valid chord.

Before accepting a simplified chord:

- Bound its deviation from the corresponding original chain, not merely its distance from an arbitrary bounding box.
- Preserve orientation, non-self-intersection, and closure.
- Reject shortcuts across a meaningful recess or courtyard mouth.
- Keep it within the allowed screen-space stroke envelope of the original roof at the settled camera.
- Do not increase tolerance merely to meet a roof segment quota.

If a trustworthy screen projection is unavailable during planning, limit the first pass to collinear cleanup and retain the original curved perimeter. Removing posts will still deliver most of the requested improvement.

### 7.6 Significant vertical corners

Select posts from the cleaned authoritative outer ring, not the RDP output.

For each candidate vertex:

1. Walk along the ring on both sides to collect stable incoming/outgoing support directions. Collapse collinear runs first so a long straight wall made of many short source edges behaves as one wall.
2. Require useful support on both sides: initial minimum supported leg length 2 m. A tiny notch or a sub-metre zigzag should not create a full-height stripe.
3. Calculate unsigned turning angle as `acos(clamp(dot(incomingUnit, outgoingUnit), -1, 1))`, where a straight continuation is 0° and a rectangular corner is 90°.
4. Require an initial turning angle of at least 40°. Reject a reversal/degenerate cusp rather than treating it as an ideal 180° architectural corner.
5. For supported concave corners, apply the same prominence and spacing requirements. A real L-shaped recess may keep its corner; a small serration should not.
6. Rank candidates deterministically by supported turn/prominence, then supporting leg length, then canonical coordinate order. Do not use source array order as the final tie-breaker.
7. Greedily retain the strongest candidates subject to both cyclic perimeter separation and endpoint separation. Start with `spacing = max(4 m, 0.04 × outer perimeter)`.
8. Keep at most eight posts for each connected outer footprint. A four-corner box should normally retain all four. A smooth circle should normally retain zero; do not invent evenly spaced ribs to fill a quota.

Initial corner-policy constants:

| Constant | Default | Purpose |
| --- | --- | --- |
| `MIN_CORNER_TURN_DEG` | 40 | Reject smooth-curve tessellation vertices. |
| `MIN_CORNER_SUPPORT_M` | 2 | Reject tiny serrations/notches. |
| `MIN_POST_SPACING_M` | 4 | Avoid pairs of nearly coincident long posts. |
| `POST_SPACING_PERIMETER_FACTOR` | 0.04 | Keep large complex halls/towers sparse. |
| `MAX_POSTS_PER_COMPONENT` | 8 | Bound façade accents without allocating by tile feature ID. |
| `MIN_INK_AREA_M2` | 4 | Remove tiny scraps, with height/screen-size checks for tall narrow volumes. |
| `ROOF_SIMPLIFY_MAX_M` | 0.25 | Allow only conservative contour cleanup. |
| `ROOF_MAX_PROJECTED_ERROR_CSS_PX` | 0.35 | Keep outline and filled geometry visually coincident. |

The exact support-direction calculation is the main geometry tuning risk. Tests must include densified straight walls, small serrations, dense arcs, and rounded rectangular corners. If a support window rounds a genuine 90° corner below the threshold, fix the definition/fixture before tuning thresholds indiscriminately.

### 7.7 Offsets and joints

The existing code offsets each roof edge separately and offsets a post using an averaged normal. Those independently shifted endpoints need not meet. Use the same canonical corner/join point for roof edges and an attached post where possible.

Use a bounded miter or bevel join for roof contours; never allow the acute-corner miter to grow without a limit. A limit of twice the stroke half-width is a reasonable starting point. Avoid introducing a complete generalized line renderer if a small correction to the existing segment quads and tiny physical separation suffices.

Visual acceptance is that the roof perimeter appears continuous, without visible corner gaps, spikes, or doubled black joints. Do not count overlapping caps as extra architecture.

### 7.8 Tiny geometry and line budgets

Area filtering must operate on a polygon member, not on a whole MultiPolygon feature. Preserve narrow tall buildings that have a meaningful visible volume even when their footprint is small; combine area with a projected extent/rise check rather than deleting every shape below one area threshold.

Budget priority is:

1. Correct visible outer contours.
2. Significant silhouette/structural corner posts.
3. Additional eligible posts, up to the per-component maximum.

Do not truncate a ring's segment list to satisfy a limit, and do not increase simplification error beyond the contour-alignment contract. A soft roof target of 64 segments may guide profiling; it is not a demand to turn a complex curved roof into a 64-sided approximation. Set a generous per-component safety ceiling, initially 512 contour segments, and treat an over-limit shape as a separately reported fallback rather than silently drawing half its perimeter.

## 8. Fragment identity, shared seams, and topology

### 8.1 Required deduplication fix

Replace the sampled `inkFragmentKey()` with complete deterministic identity that includes:

- source and source-layer;
- rendered base and top, and any relevant rendering filter/volume property;
- full polygon/ring coordinates with explicit nesting boundaries;
- hole membership;
- source ID when present, as provenance rather than the only key.

Canonicalize ring start and direction, and the ordering of independent polygon members, when deciding exact geometric equivalence. Use an explicit small metric or source-coordinate quantization policy for floating-point comparisons; do not reuse the aesthetic simplification tolerance for identity.

For these decoded vector-tile coordinates, begin with exact canonical coordinates where possible. If normalization noise requires tolerance, use approximately 1 cm in the local metric representation and test that adjacent real walls remain distinct. A hash is only an index: if collisions are possible, compare the canonical coordinate payload before dropping a geometry.

Required collision regression: two same-ID five-point rings sharing the first, middle, and closing point but differing at the second point must both survive. Same footprint with different top/base must also survive. Reversed winding or a rotated start index of the same footprint/height must not double the ink.

### 8.2 Fragment assembly rule

Retain every distinct source fragment before any contour operation. Never restore ID-only deduplication.

The minimal core implementation should suppress provably identical shared coplanar edges and the posts created only by their seam endpoints. Match source-space endpoints before applying ink offsets; otherwise the offsets themselves prevent matches. Heights must be part of the edge identity.

For simple adjacent clipped fragments, match opposite edges, split a collinear shared edge at a verified intermediate endpoint when necessary, remove only the shared interior interval, and keep the remaining exterior boundary. This is a narrow shared-edge operation, not a license to infer a building hull.

Buffered overlapping fragments are a different case: edge cancellation alone may not remove an overlap seam. Capture one real overlapping-fragment fixture before choosing a more general assembly operation. If that fixture fails visual acceptance, use an established polygon-boolean library behind a small pure adapter to union only spatially touching/overlapping fragments with compatible source identity and exactly matching rendered extents. Do not implement a general polygon-union engine from scratch.

Any union must return disconnected polygon members as disconnected components, preserve holes as topology, and operate before the per-component line budget. The 338-component source feature must not become one global eight-post object.

This is an explicit implementation gate: shared-edge cancellation is the selected minimal path; a proven buffered-overlap failure justifies a library. If the library is needed, record its exact locked version, licence, bundle cost, fixture, and reason in the implementation handoff. Do not import an undeclared transitive package from MapLibre.

### 8.3 Cases that must not be merged

- Different rendered heights or bases, even with identical XY geometry.
- Neighboring disconnected polygons sharing a source ID.
- Separate buildings with similar colour or height but no compatible fragment identity.
- A courtyard hole and an outer shell.
- Two different world copies bridged across the antimeridian.
- Roof-level decorations into the main building merely to erase detail.

Unknown fragment ownership should preserve source geometry and mark a debug fallback. It should not discard half a building or invent a convex hull. A source seam may remain an honest residual limitation until the corresponding fixture has a justified assembly solution.

## 9. Rebuild, cache, and visibility lifecycle

### 9.1 Replace the current cache key

Remove `INK_DETAIL_ZOOM` as a geometry/rebuild cap and remove the comments claiming that source queries tessellate roofs after z16. If a future line-detail policy has a maximum zoom, name and test it as a visual policy rather than using it to freeze source collection.

The cache has separate inputs:

- Style generation and source identity.
- Source-content revision/readiness.
- Current settled camera and viewport coverage.
- Geometry/ink-policy version or options.
- Rendered building visibility/filter state.
- Optional roof simplification detail bucket, if it actually changes geometry.

Do not use rounded centre coordinates as a proxy for tile coverage. The current 0.001° rounding can ignore approximately 100 m of movement in Singapore. A pure bearing/pitch change can expose different tiles without moving the centre.

### 9.2 Minimal event state

Maintain small per-layer state: `moving`, `cameraDirty`, `sourceDirty`, `sourceRevision`, `styleGeneration`, `requestedGeneration`, `committedGeneration`, and `renderedGeneration`. Avoid a generalized cache framework.

| Event | Required response |
| --- | --- |
| `movestart` | Mark moving and camera dirty; cancel the pending debounce so an old timer cannot rebuild mid-gesture. |
| `moveend` | Mark settled and schedule one trailing rebuild. This covers zoom, pan, bearing, and pitch changes. |
| relevant `sourcedata` content/readiness change | Mark source dirty/revision changed; schedule only when settled. Ignore glyph/raster/unrelated overlay activity. |
| `idle` | If dirty, schedule/complete the settled rebuild. If already current, do nothing; repainting must not cause an idle/rebuild loop. |
| `resize` / preview surface-context change | Invalidate coverage and projection-dependent roof tolerance; preserve correct pixel-width scaling. |
| building filter hidden | Disable drawing immediately; cancel unnecessary pending work. |
| building filter shown | Revalidate current source/camera before showing stale geometry as current. |
| style change | Invalidate old generation, release resources/listeners, and attach the layer only to Borderlands. |
| map/layer removal | Cancel timers, detach all listeners, settle pending capture waiters, and release GPU/CPU resources. |

Keep the existing 80 ms trailing debounce initially. The important change is what makes it dirty and what it commits, not selecting a more fashionable delay.

### 9.3 Authoritative snapshots and empty results

`collectBuildings()` should distinguish a successful empty result from a query error or an unavailable/loading source. Returning `[]` for all cases prevents correct replacement decisions.

- While the relevant source is loading, the live preview may temporarily retain its previous mesh while new tiles settle.
- After an authoritative current snapshot succeeds, replace the mesh even if it contains fewer components or zero components.
- A dense-city-to-water pan must clear the old ink.
- A source error must not be stamped as a successful current generation.
- Export may not silently use a previous-camera mesh when the current snapshot is unavailable.

Remove the `nextCount < prevCount × 0.35` replacement heuristic. Counts are not a reliable measure of mesh validity, and legitimate new views can have very few buildings.

### 9.4 Eligibility must match the building layer

Only draw when `building-3d` is present, layout-visible, and active within its current min/max zoom range. The cached layer begins at actual map zoom 14; `layerVisible()` currently checks only the layout visibility flag.

Use the rendered layer's source-layer and applicable filter when collecting source features. The current cached building layer has no explicit filter; keep tests that introduce one so future source/style changes cannot make invisible volumes produce ink. Do not blindly suppress a property such as `hide_3d` unless the corresponding fill-extrusion actually suppresses it too.

### 9.5 Caching and determinism

Keep at most one current normalized snapshot and one current committed mesh per map layer. Reuse normalized geometry while only the matrix/width changes. Build a new geometry snapshot only when its real inputs change.

Sort candidate components by deterministic visibility/importance criteria before applying an overall budget, with canonical geometry identity as the final tie-breaker. Source query order and asynchronous tile arrival order must not decide which half of the scene gets outlines.

Avoid selection hysteresis in the first implementation: it can make two routes to the same camera produce different output. If movie testing shows a visible selection transition, first reduce dependence on camera-sensitive thresholds. Only introduce hysteresis with an explicit canonical export/static selection rule and corresponding history tests.

## 10. Export and movie readiness

Keep the existing integration through `waitIdleForFrame()`. It is shared by still capture, isolate pairs, and fly-frame capture, and is the right place to ensure that ink is ready.

The contract should be:

```text
current camera applied
  → current visible tile set painted/ready
  → current ink generation built and committed
  → that generation uploaded and drawn, or intentionally empty/hidden
  → capture may read the canvas
```

`flush()` should bypass the interactive debounce, not bypass geometry validation or source readiness. A forced capture of unchanged data may reuse a current mesh; it should not rebuild thousands of segments for every frame merely because the method is called `flush`.

`waitForBorderlandsInk()` should:

1. Return immediately for a non-Borderlands map or an intentionally disabled/empty ink layer whose state is current.
2. Check cancellation before requesting work.
3. Request/flush the generation for the current camera and source snapshot.
4. Await a render that marks that generation as rendered, not just an arbitrary unrelated render event.
5. Continue honoring cancellation while waiting.
6. Reject if the relevant render does not occur before the remaining export deadline.
7. Clean up listeners/timers on success, cancellation, timeout, style replacement, or removal.

Remove the 100 ms success fallback. A timeout is failure to confirm capture readiness, not proof that a frame was painted. Pass the remaining deadline from `waitIdleForFrame()` so the ink wait cannot accidentally extend the total capture wait without bound.

If the GPU program cannot compile/link or the context is lost, the interactive preview can retain the filled 3D base and issue one useful warning. A Borderlands export should report that ink could not be rendered rather than silently claiming a complete stylistic match.

Movie testing must cross z16, the old z17.5/17.8 branches, and a tile-coverage change. Camera-only updates should normally reuse geometry; newly loaded coverage must still become available to the requested frame before capture.

## 11. File-by-file implementation map

Paths below are relative to the reviewed worktree; production edits are proposed, not made by this document.

| File | Planned work |
| --- | --- |
| `dashboard/src/maps/borderlandsFacade.ts` | Preserve Polygon/MultiPolygon/holes; clean/validate rings; align extents with rendered buildings; retain slab suppression; select real significant corners; apply component budgets; keep conservative roof geometry. |
| `dashboard/src/maps/borderlandsInkPolicy.ts` | Replace the z16/rounded-centre key and count-collapse policy; implement complete fragment identity and pure eligibility/budget/width rules as appropriate. Keep this module about policy, not GL allocation. |
| `dashboard/src/maps/borderlandsInk.ts` | Local-coordinate buffer and full-precision matrix composition; depth-correct rendering; width/DPR contract; lifecycle invalidation; authoritative empty/error distinction; strict generation-based flush/render readiness; safe cleanup. |
| Optional `dashboard/src/maps/borderlandsGeometry.ts` | Introduce only if ring cleanup/corner/fragment operations make the existing facade module unwieldy. Pure geometry helpers and their narrow types; no generic geometry framework. |
| Optional `dashboard/src/maps/borderlandsProjection.ts` | A small pure helper for matrix rebasing and pixel-width arithmetic if it materially improves testability. Avoid exporting unrelated rendering internals solely for tests. |
| `dashboard/src/maps/borderlandsStyle.ts` | Keep the current fill palette by default. Only change building-height expressions if needed to make the ink/fill height contract explicit; preserve other layers. |
| `dashboard/src/maps/MapView.tsx` | Pass the existing authored/map zoom offset and surface context to ink sync/update if the width policy requires it. Reuse existing style-load generation handling. |
| `dashboard/src/maps/captureExport.ts` | Pass the same surface/zoom context; preserve the current ink wait integration; forward the remaining deadline/cancellation into the strict readiness contract. |
| `dashboard/src/maps/captureFly.ts` | Normally no production change because it uses `waitIdleForFrame()`. Verify every frame path still goes through that shared readiness gate. |
| `dashboard/src/maps/layers.ts` | Preserve custom-layer building-filter synchronization. Extend only if required by the revised enable/refresh contract. |
| `dashboard/tests/borderlands-ink.test.cjs` | Replace the tests that encode freezing/all-triangle rejection/count-collapse retention; add pure geometry, precision, identity, and deterministic-budget fixtures. |
| `dashboard/tests/borderlands-style.test.cjs` | Preserve base-style invariants, height/filter alignment, and other-style isolation. Avoid asserting every tunable colour value unless it is an intentional design contract. |
| Proposed `dashboard/tests-ui/borderlands-ink-lifecycle.ui.test.ts` | Use Vitest fake timers and a small event-emitting fake map to test the real layer lifecycle and capture readiness. This need not mount React. |
| Proposed small fixture files under `dashboard/tests/fixtures/` | Synthetic corner/roof/fragment cases and a minimal decoded real-data subset with tile/source provenance. Do not depend on mutable network tiles in unit tests. |
| `dashboard/public/style-thumbs/borderlands.png` | Refresh only after visual acceptance if the current thumbnail no longer represents the final style. Use the same standard thumbnail camera/workflow. |
| `dashboard/dist/**` | Rebuild at the verified implementation checkpoint; inspect that generated output includes the intended source and thumbnail. Never hand-edit minified assets. |

No changes are expected to Python map document normalization or Liberty migrations for this visual repair. Re-run their focused tests only if implementation actually touches those contracts or uncovers a related regression.

## 12. Deterministic test matrix

Tests should assert user-visible/geometric contracts rather than hard-code the implementation's internal loop counts. Numerical tolerances should be in named units.

### 12.1 Geometry and visual policy

| Fixture | Required assertion |
| --- | --- |
| 20 × 30 m rectangular building, 40 m high | Continuous outer roof, four real corner posts, no ground ring or intermediate floors. |
| Same rectangle with each side densely subdivided | Same canonical post locations and equivalent roof contour. |
| 96-point and 192-point circles of the same radius | No full-height pinstripe pattern; zero invented architectural posts; roof remains within contour-error tolerance. |
| Rounded rectangle with densely sampled quarter circles | No post per arc vertex; genuine remaining sharp junctions handled consistently. |
| 40 m wall with repeated 0.5 m teeth | Teeth do not become full-height posts; straight mass remains legible. |
| L-shaped building with a substantial recess | Major convex and concave corners remain eligible; no chord spans the recess mouth. |
| Complex footprint with more than eight strong corners | Deterministic maximum of eight posts per connected component, with spacing satisfied. |
| Polygon with a courtyard hole | Outer roof ink retained; no hole-ring posts or decorative inner loop; topology still available to validation. |
| MultiPolygon with several disjoint buildings and holes | Every valid outer member considered independently; holes are not mistaken for extra buildings. |
| Cached 338-member feature | No global eight-post allocation to the whole feature; no loss of unrelated polygon members during normalization. |
| Large triangular building | Retained if valid and significant. |
| Tiny/collinear triangle scrap | Omitted by area/degeneracy criteria, not merely vertex count. |
| Tall narrow building | Not erased solely by low footprint area; post count remains sparse. |
| Open ring / repeated closing point / repeated adjacent vertex | Either normalized correctly or rejected explicitly; no missing final edge, bridge across invalid data, or zero-length segment. |
| NaN/Infinity/malformed nesting/self-intersection | No crash, non-finite GPU values, or fabricated convex hull. |
| Clockwise, counterclockwise, and rotated-start versions | Equivalent canonical roof and post output. |
| Same local geometry near Singapore and at high latitude | Metric spacing/area rules agree within the chosen projection tolerance. |
| Antimeridian-adjacent building | Local contour remains short; no whole-world segment. |

### 12.2 Heights, roofs, and the actual Suntec case

| Fixture | Required assertion |
| --- | --- |
| Suntec main 28/0 m footprint | Main outer contour retained; no synthetic interior grid. |
| Suntec 71-member 33/28 m panel collection | Current shallow-panel suppression preserved; no panel grid reintroduced by normalization. |
| Substantial elevated 80/20 m volume | Eligible; no blanket suppression of nonzero base. |
| Explicit `render_height: 0` plus nonzero `height`/`levels` | No floating ink over a zero-height rendered feature. |
| `render_min_height: 0` plus nonzero `min_height` | No accidental fallback that raises the ink base. |
| Missing/invalid rendered height | Ink agrees with the actual fill-extrusion behavior. |
| Same footprint at two different height intervals | Distinct volumes survive deduplication. |
| Narrow stepped Flyer-like volume collection | No invented smooth model; output remains bounded and does not expose hidden posts through foreground volume. |

### 12.3 Fragments and budgets

| Fixture | Required assertion |
| --- | --- |
| Identical fragment returned twice | One contour/post set. |
| Same ID, different tile-clipped halves | Both exterior halves retained. |
| Same ID and sampled first/middle/last points, changed unsampled point | Both distinct geometries retained; reproduces the weakness in the current fingerprint. |
| Same geometry with different base/top | Both retained. |
| Same geometry with changed winding/start order | Deduplicated after canonicalization. |
| Adjacent fragments with opposite coincident seam edges | Internal seam removed, true outer boundary intact. |
| T-junction/shared edge with an intermediate point | Only the matched interior interval is suppressed. |
| Overlapping buffered real fragments | Either pass the minimal algorithm or trigger the documented boolean-library gate; never silently drop one fragment. |
| Disjoint components with the same ID/height | Remain independent budget units. |
| Reversed/shuffled query ordering and asynchronous tile completion order | Same final selected components and geometry signature. |
| Scene exceeding component/segment budgets | Deterministic selection; no half-drawn roof or unbounded allocation. |

### 12.4 Precision, depth, and stroke scaling

| Test/probe | Required assertion |
| --- | --- |
| Sub-metre neighboring Singapore endpoints | Local-buffer conversion preserves distinct positions to better than 1 cm in the fixture. |
| Full-precision global projection vs rebased local projection | Projected endpoint error under 0.1 reference CSS px for the required camera fixtures. |
| Origin changes with identical world geometry | No visible positional jump. |
| Zoom 17.7, 17.8, and 18.2 | Depth remains enabled; no historical depth-disable branch. |
| Foreground box obscuring rear box | Rear posts/roof lines do not appear through the foreground surfaces in the real WebGL probe. |
| DPR/effective ratio 0.5, 1, 2, and 4 | Full width follows the explicit CSS-to-buffer rule, including preview scales below 1. |
| FW/LW/CG at one authored width-policy zoom | Expected full drawing-buffer width, not accidental half-width or zoom-offset mismatch. |
| One endpoint behind near plane | No giant quad, non-finite position, or screen-spanning spike. |
| GL state sentinel | Depth mask/test, program, buffer/VAO, and any modified blending/offset state are restored. |

Do not pretend a fake GL call log proves correct occlusion. It proves state handling; a real depth-buffer render is needed for the overlapping-buildings assertion.

### 12.5 Lifecycle and capture

| Event sequence | Required assertion |
| --- | --- |
| Cold load directly at z18.2 | Current ink appears after source readiness. |
| z15 → z18.2, same final camera as cold load | Same final normalized geometry/selection signature. |
| z19 → z18.2 | Same final signature. |
| Pan away/back, including movement smaller than 0.001° | Correct current coverage; same final signature at the original camera. |
| Pitch/bearing changes with unchanged centre | Dirty coverage rechecked; final scene has all expected buildings. |
| Tiles finish after moveend at unchanged camera | Rebuild uses the final source-content revision. |
| New gesture starts before the 80 ms timer expires | No stale rebuild during the gesture. |
| Rebuild causes render then idle | No repeated query/rebuild loop. |
| Dense city → empty water | Authoritative empty snapshot clears the old mesh. |
| Query throws / source unavailable | Distinct error state; does not masquerade as a current empty result. |
| Hide buildings / show buildings | Ink hides immediately and returns with valid current geometry. |
| Borderlands → 3D → Borderlands | No duplicate layers/listeners; clean fresh generation. |
| Layer/map removed while timer is pending | No later query, GPU upload, or repaint from the removed layer. |
| Export requested while rebuild is debounced | Flush commits required generation before capture. |
| Tile render occurs before new ink generation is drawn | Capture remains pending. |
| No render after flush | Timeout rejects; no 100 ms success fallback. |
| Cancellation during render wait | Prompt rejection and listener/timer cleanup. |
| Empty/hidden/non-Borderlands capture | No unnecessary deadlock/wait. |
| Repeated movie frames with unchanged source/geometry policy | Current mesh may be reused; no gratuitous full rebuild. |
| Movie frame introduces new tile coverage | New generation drawn before that frame is captured. |

## 13. Visual QA plan

### 13.1 Preserve reproducible scenes

Before tuning, save exact camera tuples, authored surface, current map zoom, preview dimensions, effective pixel ratio, source tile-set identifier, building filter state, and a baseline capture. Do not rely on a loosely similar mouse position.

Use temporary review maps or copies of the user's map document. Do not overwrite authored `.obedmaps` documents merely to establish a screenshot fixture.

Approximate scene centres below are starting points. Verify framing against the supplied images and then record the exact settled camera used for comparisons.

| Scene | Starting centre (longitude, latitude) | What to inspect |
| --- | --- | --- |
| Suntec convention hall | `103.85724, 1.29348` | Broad roof, grid-panel suppression, perimeter continuity, adjoining taller buildings. |
| Suntec towers | `103.8590, 1.2950` | Curved/complex tower façades, corner sparsity, podium/roof overlaps. |
| Singapore Flyer | `103.86313, 1.28931` | Inherited stepped geometry, hidden lines, narrow part behavior. |
| Marina Bay / downtown | `103.8604, 1.2864` | Dense skyline, occlusion, black-cluster reduction, map context. |
| A low-rise/shophouse neighborhood | Choose a clear local source scene | Repeated attached footprints, shared edges, small useful buildings. |
| Known source tile boundary | Choose after inspecting real fragments | Outline continuity across clipping/buffering seams. |
| Open water beside the city | Same region, clearly empty centre | Stale mesh clearing. |

### 13.2 Camera matrix

- Actual map zooms around 14, 15.5, 16, 16.5, 17.5, 17.8, 18.2, and 19.5 where supported by the chosen surface/camera.
- Explicit boundary checks at 17.49/17.51 and 17.79/17.81 to prove removal of the old rendering cliffs.
- Pitches 0°, 45°, and 60°; include the user's steep view and one near-camera extreme.
- Bearings at the saved user-like view and a roughly 90° rotated view.
- Cold load at the target camera, zoom into it, zoom out into it, pan back into it, and change only pitch/bearing.

Use actual map zoom for reproducing the old branch thresholds; also record authored zoom so surface offsets do not make the comparison misleading.

### 13.3 Surfaces and outputs

| Surface/path | Required check |
| --- | --- |
| Live preview on the current display | Stable during manipulation; clean after settling; resize does not change style weight unexpectedly. |
| CG 1920 × 1080 still | Thin strokes remain continuous at pixel ratio 1; no aliasing-induced clutter. |
| LW 3840 × 1080 still | Correct line scaling and full-width capture readiness. |
| FW 7680 × 1080 still | Actual delivery-size inspection at 100%, plus a fit-to-window comparison. |
| Centre-wall preview / side-panel toggle | No coverage or width mismatch between shown band and exported region. |
| Building filter off/on | No residual floating lines; correct restored mesh. |
| Borderlands versus 3D at the same camera | Identifies inherited geometry and checks that the baseline style is unchanged. |
| Short movie hop | Stable ink while zooming/rotating across old thresholds and new tile coverage. |
| Isolate pair with a representative highlight | Shared capture gate works for both base and cutout states. |
| Style thumbnail | Represents the accepted palette/line treatment if regenerated. |

Capture preview/export comparisons at equivalent projected framing and normalize display size deliberately. A 7680 image viewed at 25% is not a reliable test of a one-pixel output defect; inspect the relevant building crop at 100% too.

### 13.4 Required evidence set

Save the following in a dated local QA directory:

1. Before/after Suntec, curved-tower, and Flyer crops at fixed cameras.
2. An occlusion crop showing a rear building behind a foreground roof.
3. A z16-to-z18.2 history comparison with the final geometry signature.
4. A cold-load/export comparison at the same final camera.
5. One full FW still and its CG/LW counterparts.
6. A short movie crossing z16 and the old depth thresholds.
7. A small measurements file with source/geometry counts and rebuild timings.

Do not claim visual verification if only tests or source inspection were completed. Record any unavailable browser/GPU/tile prerequisite as an explicit unverified item.

## 14. Performance and memory constraints

The current feature-count limit does not bound polygon complexity. Introduce explicit component, segment, and input-vertex ceilings after measuring the representative downtown scene. The following are initial engineering budgets, not measured baseline performance:

| Budget | Initial target | Handling |
| --- | --- | --- |
| Steady-state geometry work during a gesture | None | Matrix/width render work only; collect after settle or for a capture request. |
| Settled rebuild, typical city view | Target ≤16 ms | Measure normalization, planning, and buffer creation separately. |
| Settled rebuild p95 across required scenes | Target ≤32 ms | Revisit avoidable work before introducing a worker. |
| Main-thread long tasks attributable to ink | Avoid >50 ms | Use a profile to locate the actual bottleneck. |
| Selected connected components | Initial ceiling 3000 | Cull/choose deterministically by visible relevance; no source-order truncation. |
| Total ink segments | Initial ceiling 50,000 | Preserve whole contours; drop low-priority posts/components through an explicit policy. |
| Raw vertices normalized for one snapshot | Initial ceiling 200,000 | Reject or defer pathological geometry predictably; record fallback count. |
| Per-component roof safety ceiling | Initial 512 segments | Never render half a closed ring. |
| Stored mesh generations | One current, one candidate during replacement | Release superseded CPU arrays/buffers and all removed-layer resources. |
| Idle duplicate work | Zero after current generation settles | No render → idle → rebuild feedback loop. |

At the current layout of six vertices × eight Float32 values per segment, 50,000 segments occupy 9.6 MB of GPU vertex data. A temporary JavaScript number array of the same values is roughly another 19.2 MB before engine overhead, plus the old/new typed arrays. Measure peak allocation during a large rebuild.

Prefer a bounded typed-buffer writer or a counted allocation if the existing number-array construction causes a measurable spike. Do not add a pool/LRU/worker architecture merely to satisfy a speculative performance concern.

If buffered-fragment union becomes necessary, spatially partition candidates and bound each connected work group. Never feed a tile-wide collection of hundreds of disjoint buildings into an unbounded union on every pan. The simple-path fixtures should remain on the simple path.

Budget exhaustion is not an excuse to keep a previous-camera mesh. Produce the deterministic current reduced selection and make the reduction inspectable in debug data.

## 15. Debugging and failure handling

### Minimal justified diagnostics

Use an opt-in local development diagnostic snapshot or structured console record; no external telemetry service and no permanent new user controls. Useful fields are:

```text
style/source generation; actual/authored zoom; source maxzoom;
source feature count; normalized polygon/component count;
duplicate fragments removed; invalid rings skipped; slab panels omitted;
eligible/selected posts; roof segments; total segments;
budget/fragment fallbacks; rebuild duration; upload duration;
requested/committed/rendered generation; effective pixel ratio.
```

Expose enough information for the test harness or reviewer to capture one snapshot. Avoid logging raw coordinates or large feature payloads continuously. A one-time fixture capture can contain geometry locally with its provenance.

### Failure policy

| Failure | Preview behavior | Capture behavior |
| --- | --- | --- |
| Temporarily loading source | Retain previous mesh transiently; settle to current data. | Wait within the existing export deadline. |
| Authoritative empty source/selection | Clear ink. | Capture the intentionally empty state. |
| Invalid individual geometry | Skip that member with a debug count; keep other valid buildings. | Same deterministic omission; report aggregate diagnostics in QA. |
| Fragment ownership cannot be proved | Preserve distinct source fragments; do not fabricate a merge. | Same behavior; mark any acceptance failure explicitly. |
| Simplification validation fails | Use cleaned original contour. | Use the same fallback. |
| Overall budget reached | Current deterministic lower-detail selection. | Same selection policy; no partially written contour. |
| Shader/GL allocation failure | Filled Borderlands base remains usable; warn once. | Report ink-render failure rather than silently calling the export complete. |
| Missing render before deadline | Continue showing available preview state. | Reject with a useful timeout error. |
| Cancellation or map removal | Stop pending work and detach waiters. | Reject/abort promptly, with cleanup. |

## 16. Ordered implementation phases and review gates

### Phase 0 — preserve and reproduce

1. Record `git status`, staged diff, HEAD, and the baseline generated-asset state.
2. Read the current code and project instructions again only where they changed after this review.
3. Save exact user-like camera fixtures and baseline output without editing the user's original map document.
4. Extract minimal deterministic real-data fixtures for Suntec main roof/panels, a curved tower, and clipped fragments from the known cache.
5. Capture initial timing/count diagnostics.

Exit evidence: the reported messy scene can be reproduced, or its unavailable prerequisite is documented. No visual conclusion is inferred solely from an old screenshot.

### Phase 1 — correct placement and occlusion

1. Rebase mesh coordinates and compose the render matrix in full precision.
2. Remove close-zoom depth disabling and large clip-space bias.
3. Align heights and building-layer eligibility.
4. Fix/restabilize tiny roof/wall offsets and obvious join gaps only after the precision probe.
5. Add projection/GL-state tests and capture fixed-camera A/B evidence.

Exit evidence: no hidden-line print-through, no metre-scale outline drift, and no z17.8 rendering cliff. This phase may remove substantial clutter before any decimation.

### Phase 2 — sparse architectural ink

1. Preserve Polygon/MultiPolygon/holes during normalization.
2. Keep outer contours and suppress decorative hole ink.
3. Retain the shallow-panel rule and establish the Suntec regression fixture.
4. Implement significant-corner selection with support/spacing/eight-post limits.
5. Add only conservative roof cleanup, with validated fallback to the original contour.
6. Apply component/segment budgets using stable selection order.

Exit evidence: the circle/densified-wall/serrated/L-shape fixtures behave correctly; the curved tower has far fewer stripes; Suntec remains quiet without changing the underlying filled architecture.

### Phase 3 — current source snapshots and fragments

1. Replace the z16 cache and feature-count-collapse policy with explicit dirty/source-generation handling.
2. Cancel stale timers on movestart/removal.
3. Distinguish authoritative empty snapshots from errors/loading.
4. Strengthen complete fragment identity.
5. Add narrow shared-edge seam suppression.
6. Run the real buffered-fragment fixture; introduce a maintained polygon-boolean dependency only if this gate demonstrates the need.

Exit evidence: cold/zoom/pan/pitch paths converge to the same final output; dense-city-to-water clears; tile boundaries do not lose half a building.

### Phase 4 — capture readiness and surface parity

1. Preserve the existing ink flush integration.
2. Track requested, committed, and rendered ink generations.
3. Remove timeout-as-success and forward the capture deadline/cancellation.
4. Pass the existing surface/zoom context consistently to preview and export.
5. Verify still, isolate pair, and movie capture paths with real rendering.

Exit evidence: capture cannot read a canvas before its requested ink is painted, and every wait cleans up correctly.

### Phase 5 — restrained style tuning

1. Tune the proposed charcoal/full-width values against the last reference and the user's scenes.
2. Check DPR/export width arithmetic and thin-stroke edge coverage.
3. Check roof joints and close-camera clipping.
4. Keep the fill palette stable unless the comparison demonstrates a separate material need.
5. Refresh the thumbnail if necessary.

Exit evidence: quieter façades and roofs at all required delivery sizes, with no clipping/aliasing regressions.

### Phase 6 — required verification and handoff

After source changes, follow the repository dashboard workflow:

```bash
PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm install
PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run test:maps
PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run test:ui
PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run build
```

Run those commands from `dashboard/`. Investigate any lockfile changes from installation and preserve unrelated staged work. Restart the relevant `python -m obed_edom dashboard` instance after a source/build change because the Python dashboard serves `dashboard/dist`; a successful Vite hot-reload view alone does not prove the served dashboard is updated.

If a running server is shared with the user's active work, identify that instance and preserve their work before restarting it. Do not indiscriminately terminate all Python dashboard processes.

Inspect the final source and generated diffs, execute the visual evidence matrix, and report what changed, what was tested, and any remaining inherited geometry limit. No commit, PR, staging sweep, or merge is part of this planning task.

The local `obed-edom` skill informed the build/test/restart requirements. Its peer-review requirement applies to the eventual non-trivial implementation. This document is the requested independent Astra review of the plan; it does not claim that a future implementation diff has been reviewed already.

## 17. Acceptance criteria

All correctness criteria below are required. Visual tuning values may move within the agreed style direction; correctness must not be traded for a prettier isolated screenshot.

- [ ] A smooth densely sampled curved footprint creates no posts merely because it has many vertices.
- [ ] A normal rectangular building retains its useful corners and a continuous outer roof contour.
- [ ] Large recesses and curved silhouettes stay aligned with the filled building.
- [ ] Hole rings and shallow roof panels do not reintroduce decorative roof clutter.
- [ ] Suntec's 71-panel ink grid remains suppressed in the known fixture.
- [ ] Foreground roofs/walls occlude rear ink at every supported zoom, including above 17.8.
- [ ] Sub-metre coordinate precision survives the GPU data path; the real-camera alignment probe passes.
- [ ] Final output at the same camera/source/policy is independent of cold load, zoom direction, or pan history.
- [ ] Pitch/bearing/resize/new tiles invalidate relevant coverage even without a large centre change.
- [ ] A valid empty current view clears stale ink.
- [ ] Identical fragments deduplicate; distinct clipped fragments and different height intervals survive.
- [ ] Budgets apply to connected components and whole contours, not aggregate tile feature IDs or query order.
- [ ] The buildings filter and style switches leave no residual ink or duplicate layer lifecycle.
- [ ] Captures confirm the requested generation was painted; timeout and cancellation cannot silently succeed.
- [ ] Preview and delivery-size CG/LW/FW outputs have intentional, consistent line weight.
- [ ] A movie crossing the old zoom thresholds has no sudden x-ray effect, pinstripe explosion, or missing-ink frame.
- [ ] Rebuild timings and memory remain within the measured/accepted budgets, with no idle rebuild loop.
- [ ] Required dashboard tests/build pass and the served dashboard uses the rebuilt assets.
- [ ] Before/after evidence and any unverified items are included in the implementation handoff.
- [ ] The Flyer limitation is stated accurately: its inherited extruded parts remain, even if the ink becomes quieter.

## 18. Open decisions and recommended defaults

These decisions are ordered by when evidence can resolve them. They should not trigger a blanket stop before making the requested plan concrete.

| Decision | Recommended default | Evidence that would change it |
| --- | --- | --- |
| Quiet line treatment versus a larger palette redesign | Implement the quiet line treatment first, keeping fills stable. | Fixed-camera comparison still falls materially short after geometry/depth are correct. |
| Courtyard interior ink | Omit it in the initial sparse style. | A real important courtyard becomes unreadable; then add a restricted large-courtyard rule with a fixture. |
| Smooth curved façades | Zero invented posts; rely on roof contour and filled volume. | A reviewed scene genuinely needs view-dependent silhouette strokes; treat that as a bounded follow-up rather than adding arbitrary ribs. |
| Roof simplification | Collinear cleanup first; conservative bounded RDP only where safe. | Profiling or a real contour fixture demonstrates useful reduction within the alignment contract. |
| Exact post threshold/budget | 40° turn, 2 m support, spacing `max(4 m, 4% perimeter)`, maximum eight. | Circle/serration/real-tower fixtures reveal an identifiable failure; tune one meaningful parameter at a time. |
| Fragment union dependency | Begin with complete identity and narrow shared-edge handling. | A captured buffered-overlap fixture fails the seam acceptance gate. |
| Numeric-string/level fallback heights | Match the existing rendered numeric-height contract. | Product explicitly needs fallback and the Borderlands extrusion receives the same tested expression. |
| Wheel-specific treatment | Keep generic rendering and document inherited geometry. | The user later requests a landmark-model override or simplified filled-building source. |
| Worker/caching expansion | None beyond one current snapshot/mesh. | Representative profiling exceeds the target after redundant work and budgets are fixed. |
| Palette constants | Charcoal `#4C4B50`, restrained full-width ramp. | Delivery-size visual comparisons justify a nearby value. |

## 19. Rollout and rollback

Keep changes grouped by the ordered phases so a reviewer can distinguish precision/depth correctness, line selection, lifecycle, and visual tuning. Use small verified checkpoints in the working diff; the current request does not authorize commits or PR creation.

Before any later checkpoint commit, record the existing staged baseline explicitly. Do not run a broad `git add -A` that sweeps unrelated feature work, temporary references, or QA captures into the change.

If a visual tuning choice regresses the look, revert only its constants or policy change. Do not bring back global Float32 placement, ID-only deduplication, disabled depth testing, or timeout-as-success as a visual rollback mechanism.

If the complete repair needs to be backed out, use a targeted patch/revert of the repair's known diff while preserving the original staged Borderlands/Liberty work, then rebuild `dist`. Do not reset the worktree or overwrite unrelated user changes. Switching the map to the existing 3D style remains a user-level fallback while a Borderlands rendering failure is investigated.

## 20. Evidence links and implementation references

- [Current facade planner](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/src/maps/borderlandsFacade.ts)
- [Current WebGL ink layer](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/src/maps/borderlandsInk.ts)
- [Current cache and fragment policy](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/src/maps/borderlandsInkPolicy.ts)
- [Shared export readiness path](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/src/maps/captureExport.ts:120)
- [Preview/export surface definitions](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/src/maps/types.ts:225)
- [Cached Liberty source/style](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/output/.maps/tile-cache/styles/liberty.json)
- [Cached source maxzoom/tile set](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/output/.maps/tile-cache/planet.json)
- [Installed MapLibre full-precision custom matrix](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/node_modules/maplibre-gl/src/geo/projection/mercator_transform.ts:903)
- [Installed MapLibre source feature query](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/node_modules/maplibre-gl/src/source/query_features.ts:218)
- [Installed MapLibre 3D custom draw setup](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/drop-liberty/dashboard/node_modules/maplibre-gl/src/webgl/draw/draw_custom.ts)
- [Obed-Edom workflow skill](/Users/anyhowclick/Desktop/work/obed-edom/.agents/skills/obed-edom/SKILL.md)

External API links were checked on 2026-09-14. Their current documentation can differ from the installed version; the installed 6.7.0 source is the compatibility authority for this implementation plan.
