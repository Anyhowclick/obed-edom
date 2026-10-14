# F2 census — player facts and export inventory

2026-10-14. Rev 2 folds critique r1 findings 1, 6–8, 10–12. Source-deck usage remains unrun; no `.key` reader was invoked. Static inspection only: no browser, OBS, Keynote, network, git or test run. Predictions are isolated in §5; they are not measured failures. The supplied base is `origin/main 5b09b379`; that identity was not independently checked with git.

## 0. Sources and anchor convention

- **P** = stock [e9b2fad4 main.js](/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/p2-binary/html-unmodified/assets/player/main.js). `@n` means zero-based **byte**, not character or line. **P17** = [17c0c938 main.js](/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/player/main.js). All P offsets below are identical in P17 unless a pair is printed. Exact literal counts and both offset lists are in [player_f2_anchors.md](player_f2_anchors.md), machine-readable in [player_f2_anchors.json](player_f2_anchors.json).
- **D** = [Dissolve plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/.agents/plans/keynote_live_dissolve_crossfade.plan.md), especially §§0–3, 5, 9.1, 12–13. **L** = [Line Draw plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/.agents/plans/keynote_live_line_draw.plan.md), §§1–4a.
- **C** = the run of [census_f2.py](census_f2.py): [full evidence](census_f2.json), [one row per occurrence](census_f2_rows.tsv), [all 32 shape/timing variants](census_f2_shapes.md). Each occurrence carries absolute JSON path, SHA-256, slide number/UUID, JSON pointer, type/name, attributes, full initial states and animation trees. These are the source anchors for the tables in §4.
- **R** = [live_runtime.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/live_runtime.py:67): shipped name/shape admission at lines 67–84, Line Draw at 185–217, replacements at 219–303, pinning at 389–440.

P is 2,369,488 bytes, SHA-256 `e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354`; P17 is 2,369,526 bytes, SHA-256 `17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91`. The 26 fixture roots contain 24 P and 2 P17. Removing exactly two 19-byte `,isEvalSupported:!1` insertions from P17 makes it byte-identical to P. Insertions: P/P17 coordinates 2331091/2331091 and 2331343/2331362. Thus every inspected renderer anchor below 2331091 is identical; later ones move +38. [C roots; player_f2_anchors.json]

## 1. Routing and the complete name dispatch

### 1.1 Full `jC` (14 names, in source order)

`jC=[` occurs once in each player, P @2368216 / P17 @2368254:

```text
apple:wipe-iris
com.apple.iWork.Keynote.BUKAnvil
com.apple.iWork.Keynote.BUKTwist
com.apple.iWork.Keynote.BUKFlop
com.apple.iWork.Keynote.KLNColorPlanes
com.apple.iWork.Keynote.KLNFlame
com.apple.iWork.Keynote.KLNConfetti
com.apple.iWork.Keynote.KLNDiffuse
com.apple.iWork.Keynote.KNFireworks
com.apple.iWork.Keynote.KLNShimmer
com.apple.iWork.Keynote.KLNSparkle
apple:magic-move-implied-motion-path
apple:ca-text-shimmer
apple:ca-text-sparkle
```

`PB.renderEffects` @2311803 uses `qC&&-1!==jC.indexOf(C.name)` @2312807 for a root replacement; `PB.renderEffect` @2313757 uses `qC&&-1!==jC.indexOf(i)` @2314108 for an object replacement. Both tokens occur exactly once in each player. Otherwise the exported tree is built with `VB` and drawn by `NB`. `qC` starts true and is disabled when the startup canvas cannot obtain WebGL (P @2368694 onward / P17 +38); absence from `jC` is not an exhaustive “never GL” guarantee: see §3. [P anchors; D §1.1]

There is **no closed CSS effect-name registry** in these routes. `WB` consumes animation properties, not a list of authored effect names. Consequently “every name the player recognises” is finite only for **explicit name-dependent code**; arbitrary exported names can use the generic CSS path. `apple:dissolve`, `apple:dissolve character`, `apple:movie-start`, and both Line Draw names occur zero times as exact quoted literals in the stock player, yet are present in C. The exact string `none` occurs 33 times for general CSS/media uses, not a transition-name dispatch. R adds the Dissolve/cut and Line Draw admissions. [P @2271556, @2311803, @2313757; name inventory; C; R]

### 1.2 GL name → handler switches (complete, not F2 implementation scope)

`fB.draw`, P @2264226 vicinity (the `apple:wipe-iris` case begins @2264351), dispatches on effect **type**, then name. A `jC` entry without a case for that particular type uses `GB`. [P @2264150–2265620]

| Type | Name → handler |
|---|---|
| `transition` | `apple:wipe-iris` → `rB`; `…BUKTwist` → `hB`; `…KLNColorPlanes` → `lB`; `…BUKFlop` → `YB`; `…KLNConfetti` → `FB`; `apple:magic-move-implied-motion-path` → `pB`; `apple:ca-text-shimmer` → `RB`; `apple:ca-text-sparkle` → `uB`; default → `GB` |
| `buildIn` / `buildOut` | `apple:wipe-iris` → `DB`; `…BUKAnvil` → `cB`; `…KLNFlame` → `MB`; `…KNFireworks` → `KB`; `…KLNConfetti` → `dB`; `…KLNDiffuse` → `UB`; `…KLNShimmer` → `JB`; `…KLNSparkle` → `mB`; default → `GB` |
| `smartBuild` | `apple:gallery-dissolve` → `IB`; default → `GB` |

Here and below `…` means `com.apple.iWork.Keynote.`. `GB` @2202984 draws an optional second texture at opacity 1 and the first with eased opacity (reversed for build-out); it is a generic fallback, not evidence that all effects named “Dissolve” take GL. `IB` @2197873 binds two textures and a `mixFactor` for its contents shader. [P classes and switches]

### 1.3 CSS tree and keyframes, shared by every non-`jC` row below

- `yB` keeps `type`, `name`, `attributes`, `baseLayer`, timing, object ID and nested `effects`; no translation from UI labels occurs here. `VB` allocates one increasing layer ID per node, recursively preserving exported child order. `NB` makes a layer div for each node it draws, nested property divs, and a canvas for each texture; masking follows `initialState.masksToBounds`. Full-slide root replacement and per-object replacement are distinct. **Neither the number of layers nor incoming/outgoing roles can generally be recovered from a name alone.** [P @2270532, @2286448, @2294205, @2296181, @2311803, @2313757]
- `WB` expands animation groups, `keyTimes`/`values`/`timingFunctions` and path segments into key actions. A path becomes successive `position` segments; the source handles `MoveToPoint`, `AddLine`, `AddCurve`, `AddQuadCurve` by taking their first points, not by a separately named “Path” effect handler. **Unverified:** whether current Keynote emits that path form or already sampled keyframes, particularly for curves. [P @2271556–2275455]
- Timing accepts case-insensitive `easein`, `easeout`, `easeinout`/`easeineaseout`, `custom` control points, otherwise linear. Initial/backward fill values and timing gaps are computed in `createAnimationRules`; `NB.applyCssAnimation` maps `fillMode removed` to CSS `none` and applies the last action's fill mode. Render and animate are separate tasks. [P @2276876 vicinity–2282016, @2282016, @2303763–2307742; D §1.1]

| Export property | Rendered CSS / nodes | Anchor |
|---|---|---|
| `opacity` | opacity wrapper; resets the layer's opacity to 1 when using a new layer | P @2283702–2286448; @2305800 vicinity |
| `hidden` | **opacity** keyframes (`false`→1, `true`→0) on the layer; visibility is exposed when starting visible content | P @2283702; @2305900 vicinity |
| `position`, `zPosition`, `transform`, `transform.translation[.x/.y/.z]`, `transform.rotation[.x/.y/.z]`, `transform.scale[.xy/.x/.y]` | translated, matrix3d, rotated or scaled property wrappers; position keyframes subtract initial position | P @2278600, @2284120–2286448; VB @2286448 |
| `anchorPoint`, `anchorPointZ` | origin plus compensating position/z translation; special exclusions for Cube/Revolve | P @2279300 vicinity–2282016; @2294205; @2303763 |
| `bounds` | `scaleX(width/initialWidth) scaleY(height/initialHeight)` keyframes rebuilt at application | P @2303763–2304800 |
| `doubleSided` | backface visibility | P @2284120–2286448; @2303763 |
| `contents` (ordinary CSS) | two texture canvases in `-contents-from` / `-contents-to`; complementary **step** opacities around 50% (adjusted for start keyframe), not a continuous fade | P @2282473–2283702; @2299100 vicinity–2300580; @2307350–2307742 |
| `contents` (`smartBuild`) | third `-contents-canvas` and nested `fB` WebGL renderer; old two contents wrappers hidden when it starts | P @2306846–2308047; §3 |
| `translationEmphasis`, `rotationEmphasis`, `scaleEmphasis`, `opacityMultiplier`, `isPlaying` | value converters exist; `isPlaying` excluded from CSS application; emphasis vector converters and opacityMultiplier mapping exist, but name/actual exported usage needs an export | P @2284120–2286448; @2305200–2307742 |

## 2. Every explicit non-`jC` effect branch

Tables describe **stock code**, not native Keynote fidelity. `data` means the exported tree controls the remaining properties, layer count and animated sides; these are unknown without an export. A “transition candidate” is a name with transition-related branches; it is not a verified UI-label mapping or a claim that the exporter only uses that type. Shared rendering is §1.3. Exact counts and every occurrence's P/P17 byte offset are in Appendix A.

### 2.1 Transition-related and type-neutral names

| Exact name | Named handling / layers / properties | Animated side known from player? | Anchors |
|---|---|---|---|
| `apple:ca-push` | Chrome disables default transition backface/preserve-3D flags; motion keyframes are data | Unknown; no animation tree synthesized | P @2292945 (`ca-push` @2293142) |
| `com.apple.iWork.Keynote.BLTFadeThruColor` | Same flag exception as Push; colour/layers/opacity timing are data | Unknown; no hard-coded colour or fade curve here | P @2293168 |
| `apple:ca-swing` | Excluded from default transition compositing flags | Data | P @2292990 |
| `com.apple.iWork.Keynote.BLTSwoosh` | For `transition`, removes first child under container child 1/child 0; swaps container children 1 and 2 in current/original trees. Excluded from default flags; adds `translateZ(0px)` compositing treatment | Data; swapping indices does not establish texture identity | P @1958203, @2293017, @2293503; NB @2294205, @2296181 |
| `apple:apple-grid` | Removes first two children of first container in current/original trees; sets grid flag; Chrome texture backface exception | Data, including tile count | P @1958081, @2293374; NB @2296181 |
| `com.apple.iWork.Keynote.BLTMosaicFlip` | Sets mosaic flag; Chrome texture backface exception | Data, including tile count | P @2293427; NB @2296181 |
| `com.apple.iWork.Keynote.BLTBlinds` | For `transition`, removes first two container children. RenderEffects is deferred to animate timeout except old Edge. Old-Edge adjustment additionally clears child 0/1 descendants/animations, inserts child-1 `opacity 1→0`, easeInEaseOut, both, effect duration; unhides both and drops children ≥2 | **Old Edge only:** child 1 fades, child 0 static; incoming/outgoing identity still needs data. Chrome: data | P @1957917, @1971971, @1972671, @2357138 / P17 @2357176 |
| `apple:3D-cube` | Excludes selected anchor/position/z/rotation wrappers from origin-Z handling; suppresses anchorPointZ/zPosition application when origin flags exist. Old Edge uses the two-child fade fallback above | Chrome: data; Edge: child 1 only | P @1972011, @2294913, @2305598 |
| `apple:ca-revolve` | Similar origin-Z exceptions (anchorPoint, position, zPosition); distinct spelling from `apple:revolve` | Data | P @2294826, @2305555 |
| `com.apple.iWork.Keynote.BLTReflection` | Only explicit name handling is old-Edge two-child fade fallback | Edge: child 1 only; otherwise data | P @1972031 |
| `apple:revolve` | Only explicit name handling is old-Edge two-child fade fallback; not an alias proven for `ca-revolve` | Same | P @1972075 |
| `com.apple.iWork.Keynote.BLTRevolvingDoor` | Only explicit name handling is old-Edge two-child fade fallback | Same | P @1972095 |
| `apple:doorway` | Chrome hides full-contents leaf on animation application. Old Edge clears child 0 layers/animations, retimes child 1 and removes child 2 | Data; this is not a general fade constructor | P @1971265, @2303848 |
| `apple:fall` | Chrome appends child-1 constant `transform.translation.z` +1 until duration−0.01, then −1 for 0.01 s, linear/forwards, to existing group | Child 1 gets z changes; remaining motion/sides data | P @1962904–1963750 |
| `apple:scale` | Safari/Chrome/Firefox/old Edge: if child 0 animated, swaps children 0/1, hides new child 1, removes its translation-z action, inserts `hidden false→false` forwards/linear (nested variant starts +0.03 s) | Animated child moved to index 1; incoming/outgoing unproven | P @1960342, @1963758, @1966321, @1969508 |
| `apple:bounce`, `apple:slide`, `apple:pivot` | Old Edge only: same scale adjustment; other engines generic data | Data | P @1969453, @1969472, @1969490 |
| `com.apple.iWork.Keynote.KLNSwap` | Safari/Chrome/Firefox/old Edge finds opacity in child-1 group (or nested group), changes `to` to 0, begin to 0.4T and duration to 0.4T; leaves other data intact | Child 1 fades; other side/motion data | P @1962099, @1965515, @1968078, @1972943 |
| `apple:FlipThrough` | Old Edge: if child 0 animated, duplicates child 1 at index 0, removes animated child's z translation and inserts constant hidden=true over second half on child 2 | Data; creates an extra copy only in that browser adjustment | P @1973711–1975600 |
| `apple:ca-isometric` | VB suppresses dedicated translation and rotation flag selection; data properties enter remaining wrapper handling | Data | P @2288839; VB @2286448–2291700 |
| `com.apple.iWork.Keynote.KLNComet` | If affine x scale is −1, resets it to +1 and sets canvas-flip flag; canvas transform branch can use `rotateY(180deg)` | Data; this name has no type restriction in the branch, so build/transition identity unverified | P @2296584; NB @2296181–2300600 |

Browser names above follow the player's own UA flags (`mC` Chrome, `pC` old `Edge/`, `JC` Safari, `SC` Gecko), P @2366767–2367180 / P17 +38. Old-Edge branches are facts about retained source, **not** evidence that Chromium Edge or the product's Chrome/CEF runs them.

### 2.2 Per-object `buildIn` / `buildOut`

`PB.renderEffect` substitutes the matching object's tree. It does not invent a counterpart for a build-in/out. Whether one leaf, many characters, outgoing and incoming copies, or descendants animate is export-dependent. `VB` records `isBuildIn`/`isBuildOut`; WB gives position starts special initial-fill handling. Names from §2.1 can also pass this route if exported with these types; stock code has no exhaustive in/out-name map. [P @2286448–2291700, @2276876 vicinity, @2313757]

| Observed name / type | Exported drawing facts | Evidence |
|---|---|---|
| `apple:dissolve character` / `buildIn` | 48 fixture occurrences; root→container→one textured leaf; grouped opacity 0→1 EaseInEaseOut plus hidden false→false, 1 s; opacity/group both, hidden forwards. **One leaf** in these exports, despite “character” in the name | C rows filtered by name |
| `apple:dissolve` / `buildIn` | One occurrence; same fade shape, 1 s | C: alpha-dsk-textures slide 2, chained effect; L §1 |
| `com.apple.iWork.Keynote.LineDraw`, `…LineDrawForLine` / `buildIn` | One each; same fade shape, 0.8 / 0.7 s. Native drawing semantics were lost in export data; shipped R admits only measured path/direction/easing/shape variants | C; L §§1–2.1; R @lines 185–217 |
| `apple:movie-start` / `buildIn` | 227 across both collections; one textured leaf with group containing `hidden` and `isPlaying`, 0.001 s; both/removed; no timingFunction. Movie service, not 227 authored entrance styles | C rows; P @2303000–2303763, @2305200–2307742 |
| `renderMovie` / `buildIn` | 227; duration 0, no animations; root with two or three textured children, one video flag; seven movie property wrappers when objectID is present. `renderMovie` is dispatched separately and cache-backed video inserted | C; P @2288869, @2312136, @2313180 vicinity; NB @2296181 |
| `renderWebVideo`, `apple:audio-start` | Explicit services: web-video renderer branch / `OB` audio cache creation; zero occurrences in C. Not slide-fade fixes | P @2311959, @2312160; C |
| Any other `buildIn` / `buildOut` name outside `jC` | CSS property-driven path (§1.3), with applicable name quirks (§2.1); exact animation and movie behaviour **unverified** until exported | P @2313757; C has no buildOut |

On an existing movie, `NB.setVideoLayer` tries to identify its leaf from cache/texture identity; `NB.addNode` can move the cached movie div next to the replacement, hide the model wrapper, or stop/remove controls for build-out. Therefore a movie beside a built still object and a movie that is itself built are separate admission cases. [P @2295380–2296181, @2300440–2300690]

### 2.3 Action builds: complete `vC` name → property map

- Two action routes: still target, first action → node replacement; movie target, or later action on the same object → in-place mutation of the existing layer (vC property filter). Same-event actions merge (stock duration quirk noted).
- Re-read in P/P17: `renderEffects` @2311803 sets chain flag `Q` from an earlier same-object `actionBuild`, `renderMovie` or `renderWebVideo` (@2312380 vicinity). `renderEffect` @2313757 uses `g` to set `B.currentKPFLayer`; otherwise it replaces the node (@2314970 vicinity). The action-scale contents splice is guarded by `!l` (movie-cache presence), @2314516 vicinity. `processEffects` @2311135 assigns `B[g].duration=o.beginTime+o.duration` when extending a merged action: an end time rather than elapsed duration for a chain starting after zero. This is a stock quirk, not a measured F2 failure.

`vC={` occurs once at P @2367654 / P17 @2367692. Its **10** entries are below; this is a property filter when applying to an existing layer (`g` truthy), not a generator of action keyframes. `processEffects` merges same-object `actionBuild` trees/animations and nested effects within one event; an event can therefore contain several actions (none observed in C). [P @2311135, @2305200–2307742]

| Name | `vC` properties (exact order) | Direction / drawing / layers |
|---|---|---|
| `apple:action-opacity` | `opacity` | Existing target only; opacity wrapper; values/timing data |
| `apple:action-motion-path` | `position` | Existing target only; position wrapper; repositions current layer even when no rules on a node (§1.3 path parsing) |
| `apple:action-rotation` | `transform.rotation.z` | Existing target only; Z-rotation wrapper; angle/direction data |
| `apple:action-scale` | `transform.scale.x`, `transform.scale.y`, `anchorPoint`, `contents`, `bounds` | Existing target; scale/origin/bounds wrappers and possibly two contents textures. When chaining on a nonmovie, renderEffect may move newly created from/to canvases into old contents wrappers |
| `apple:action-blink` | `opacity` | Emphasis; repeat count flattened into keyTimes/values/timingFunctions |
| `apple:action-bounce` | `anchorPoint`, `transform.scale.y`, `transform.translation.y`, `transform.scale.x` | Emphasis; keyframes data |
| `apple:action-flip` | `transform.rotation.y`, `transform.scale.xy` | Emphasis; keyframes data |
| `apple:action-jiggle` | `transform.rotation.z` | Emphasis; repeats cloned into group; last repeat can be shortened/returned toward rest |
| `apple:action-pop` | `transform.scale.xy` | Emphasis; keyframes data |
| `apple:action-pulse` | `transform.scale.xy` | Emphasis; repeat count flattened like blink |

Sources: vC; emphasis name list `m` @1984648 (six last entries in order pop, pulse, blink, flip, bounce, jiggle); adjustments @1958525–1960294; motion-path @2303553; action-scale @2314516; wrappers @2286448. “Existing target only” describes object routing, not proof that export layers cannot contain multiple textures. Action types/values for all ten are absent in C.

**UI Move, Scale, Rotate, Opacity, Path:** the source identifies opacity, motion-path/position, rotation-z and scale names above. It has no separate `apple:action-move` or `apple:action-path` literal and no UI-label map. AM and AP are one Keynote action (Move); author one curved Move. UI authorability/options remain unverified here. **Unverified export mapping:** Move and custom Path may both export as `apple:action-motion-path`; only the owner's export can establish that, the group nesting, easing, path sampling, and whether combined actions merge into the existing-object path. [P literal inventory, vC, WB; C zero actionBuild]

## 3. Smart builds are not uniformly CSS

The data model accepts `type: smartBuild`; no enum ties UI labels Flip, Dissolve, Grid, Thumb Through, Spin, Swap to export names. Candidate spellings (`apple:gallery-dissolve`, `apple:apple-grid`, `apple:FlipThrough`, `…KLNSwap`) are suggestive **but UI mappings remain UNVERIFIED**. There is no literal smart-build “Flip” or “Spin” registry; `apple:action-flip` is an emphasis name, not evidence for Smart Flip. [P yB @2270532; literal inventory; fB @2265418]

For a `smartBuild` containing `contents`, `NB.applyCssAnimation` creates `layerN-contents-canvas`, sizes it from the initial layer, creates/caches `fB`, and schedules `animateContentsWillBegin` at effect begin time. That method invokes `fB.draw/animate` and hides the from/to CSS wrappers. Thus `apple:gallery-dissolve` is absent from jC but can use **nested WebGL** (`IB`); unknown smart names dispatched here use `GB`. Other smart properties are still generic CSS. Contents absence, GL unavailability, number/order of images, actual durations/easing and movie interaction are not established by a real export in C. [P @2306846–2308047, @2262229, @2265418, @2197873, @2202984]

**Rev 2 anchor verification (direct byte reads of both main.js files):** the `smartBuild` switch (@2265418) maps `apple:gallery-dissolve` (@2265454) to `IB` (@2197873). The quoted literal begins at @2265453; @2197873 begins `class IB`. All four offsets are identical in P/P17. The `smartBuild` `contents` branch (@2306846) constructs `fB` **without a `qC` check**, unlike both `jC` routes (@2312807 and @2314108), so it is attempted even when startup WebGL failed. The outcome is unverified. The inspected branch contains `N||(N=new fB(b),this.glContentsRenderer[y]=N)` before scheduling contents animation; both player sizes/full hashes still match §0.

Smart/gallery contents render in nested WebGL (`IB`/`GB`), which is GL scope. Not authored in F2. Legacy Smart Build UI availability remains unverified; see plan §2 and OQ-F2-3.

An owner export reveals each UI effect's `type/name/attributes`, object and texture IDs, initial states, layers, animation group nesting, properties/values/path/keyTimes, timing/fill and child effects. A later runtime probe must also log the actual route and canvases; JSON alone cannot show which browser-specific rewrite ran or native Keynote intent. [P §§1–3 anchors; L §1; C schema]

## 4. On-disk census (executed)

`python3 OUT/census_f2.py` completed successfully, using only stdlib, writing only beside the script in OUT. Discovery: every `assets/header.json` under the main checkout fixtures and under each existing `Continuity/*-html`; every slide `assets/*/*.json`, each effect occurrence recursively once, including child effects/hyperlink event trees. JSONP copies are not recounted. No copied-deck deduplication. All 35 roots have players and all header slides were present; there were no unlisted slide JSONs or read/schema errors. Counts are **physical export occurrences**, not unique authored effects. [C script/main, roots/errors]

| Population | Roots | Dissolve transitions | `none` transitions | Magic Move transitions | Other transitions | Nontransition/build records |
|---|---:|---:|---:|---:|---:|---:|
| Main fixtures now | 26 | 45 | 11 | 71 | 0 | 407 |
| Main fixtures minus `alpha-dsk-textures/html-unmodified` | 25 | **42** | **8** | **67** | 0 | **382** |
| Added `alpha-dsk-textures/html-unmodified` | 1 | 3 | 3 | 4 | 0 | 25 |
| Desktop Continuity `*-html` | 9 | 2 | 9 | 25 | 0 | 98 |
| Both requested collections | 35 | **47** | **20** | **96** | **0** | **505** |

**Usage limitation:** the only real DSK export in this inventory, `Alpha_DSK` (`alpha-dsk-textures`), has no F2 effect: only Dissolve/none/Magic Move transitions, Dissolve/Line Draw builds and movie services. The other roots are qualification decks/copies. The 26 fixture roots represent about nine distinct source decks; `p2-*` roots are copies of Minimal Alpha_DSK, not independent usage observations. Deck identity and per-effect membership are in `census_f2_rows.tsv`; no source `.key` census has been run.

Before any authoring, W(−1) runs `iwa_builds.deck_builds` read-only over the owner's source decks in `~/Desktop/Convert wall to 16x9 CGs/*.key` (wall + CG + DSK), at a quiet machine time, and tabulates every transition/build effect. F2's case list = effects found there ∪ effects the owner names in OQ-F2-0. This is future work, prohibited during this revision's timing-sensitive window. See [plan §1 fact 6 and §6](keynote_live_f2_transitions_builds.plan.md).

The older 42 / 8 / 67 / 382 are exactly reproducible on the 25-root subset. This proves the arithmetic reconciliation, not the historical reason the older census omitted that root. All 505 nontransition records have type `buildIn`; **0 buildOut, 0 actionBuild, 0 smartBuild**. Of 407 fixture records, 356 are movie-start/renderMovie service records and 51 are still-object build records; over both collections those counts are 454 and 51. [C]

**“0 on disk” remains true for F2's other transition names and smart/action types in the requested populations.** It is false if read as “no non-jC per-object CSS builds”: 51 still builds and 454 movie service records are present. It also does not validate the older blanket “per-object builds: ok”: L documents the two degraded Line Draws now on disk. No claim is made about other desktop exports or future files. [C; D §5; L §1]

All 47 Dissolves have `N[N[T,T{opacity}]]`, outgoing-only opacity 1→0, EaseInEaseOut, both, 1 or 1.5 s; all 20 cuts have `N[N[T,T{hidden}]]`, outgoing-only hidden false→true, 0.001 s, both, absent timingFunction. For these two shapes, layer 0 is the incoming texture and layer 1 the outgoing (D §§1.2, 3.2); other roles are not guessed. The 96 Magic Moves have multiple geometry/content/fade variants. Exact shapes, durations, timing and fill for **all** 32 variants are in [census_f2_shapes.md](census_f2_shapes.md); all individual decks/slides are in [census_f2_rows.tsv](census_f2_rows.tsv). The tables below are pasted from this run. [C]

### 4.1 Counts by type/name and root

| Source | Type | Effect | Count |
|---|---|---|---:|
| continuity | buildIn | `apple:movie-start` | 49 |
| continuity | buildIn | `renderMovie` | 49 |
| continuity | transition | `apple:dissolve` | 2 |
| continuity | transition | `apple:magic-move-implied-motion-path` | 25 |
| continuity | transition | `none` | 9 |
| fixtures | buildIn | `apple:dissolve` | 1 |
| fixtures | buildIn | `apple:dissolve character` | 48 |
| fixtures | buildIn | `apple:movie-start` | 178 |
| fixtures | buildIn | `com.apple.iWork.Keynote.LineDraw` | 1 |
| fixtures | buildIn | `com.apple.iWork.Keynote.LineDrawForLine` | 1 |
| fixtures | buildIn | `renderMovie` | 178 |
| fixtures | transition | `apple:dissolve` | 45 |
| fixtures | transition | `apple:magic-move-implied-motion-path` | 71 |
| fixtures | transition | `none` | 11 |

| Source | Export root (relative to source) | Transitions | Other effects |
|---|---|---:|---:|
| continuity | `D1-html` | 4 | 8 |
| continuity | `D2-across-html` | 5 | 10 |
| continuity | `D2-html` | 5 | 10 |
| continuity | `D3-html` | 4 | 12 |
| continuity | `D4-html` | 3 | 8 |
| continuity | `D5-html` | 3 | 10 |
| continuity | `D6-html` | 5 | 12 |
| continuity | `D7-html` | 4 | 16 |
| continuity | `D7s-html` | 3 | 12 |
| fixtures | `alpha-dsk-textures/html-unmodified` | 10 | 25 |
| fixtures | `gl-decks/Minimal Alpha_DSK/html` | 9 | 33 |
| fixtures | `gl-decks/Positive Control/html` | 4 | 8 |
| fixtures | `minimal-alpha-dsk-17c0c938/html` | 9 | 33 |
| fixtures | `p2-binary/html-disposable` | 4 | 15 |
| fixtures | `p2-binary/html-player` | 4 | 15 |
| fixtures | `p2-binary/html-unmodified` | 4 | 15 |
| fixtures | `p2-loop-grey/html-player` | 4 | 15 |
| fixtures | `p2-loop-grey/html-unmodified` | 4 | 15 |
| fixtures | `p2-loop/html-player` | 4 | 15 |
| fixtures | `p2-loop/html-unmodified` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/gl-replay/html-disposable` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/gl-replay/html-player` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/gl-replay/html-unmodified` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/html-disposable` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/html-player` | 4 | 15 |
| fixtures | `p2-recovery/html-adversarial/html-unmodified` | 4 | 15 |
| fixtures | `p2-soak-loop/html-unmodified` | 9 | 33 |
| fixtures | `qual-decks/D1/html-unmodified` | 4 | 8 |
| fixtures | `qual-decks/D2-across/html-unmodified` | 5 | 10 |
| fixtures | `qual-decks/D2/html-unmodified` | 5 | 10 |
| fixtures | `qual-decks/D2/html-unmodified.across-first-build` | 5 | 10 |
| fixtures | `qual-decks/D3/html-unmodified` | 4 | 12 |
| fixtures | `qual-decks/D4/html-unmodified` | 3 | 8 |
| fixtures | `qual-decks/D5/html-unmodified` | 3 | 10 |
| fixtures | `qual-decks/D6/html-unmodified` | 5 | 12 |

Export roots: 35; effect occurrences: 668; read/schema errors: 0.

N = untextured layer; T = textured layer; V = video flag; braces = animation properties (group included); brackets = children in order.

Full source paths, SHA-256, JSON pointers, attributes, initial states and animation trees: `census_f2.json`.
One occurrence per row, with shape/timing: `census_f2_rows.tsv`. Missing timing is recorded as `<absent>`, not inferred.

## 5. PREDICTED failure classes — not observed F2 results

Derivation uses D §2 with time/position-dependent premultiplied samples. For ordinary source-over, with transformed/masked outgoing `A_t` above incoming `B_t`, `F=A_t+(1−α_A_t)B_t`. A full incoming sample appears wherever outgoing α=0, regardless of the nominal transition progress. Opposite opacity ramps still give α=0.75 at halfway for two opaque overlapping samples, not the desired cross-fade α=1. Additive blending is valid only for a proven replacement mixture with complementary weights; it is not generally correct for two independently authored overlapping objects. A single object opacity over a static backdrop has normal source-over semantics and does **not** need an incoming mirror. [D §2; P NB/WB in §1.3]

Predictions below are conditional on the stated **unverified export shape**. They cannot establish current UI→name mapping or native semantics. “None” means no additional fill-less alpha defect follows from that model; it does not claim correct geometry, timing, movie frame, or native effect fidelity.

| Names / case (all non-jC name branches covered) | PREDICTED class and condition | Static basis |
|---|---|---|
| `apple:ca-push`, `apple:ca-swing`, `…BLTSwoosh`, `apple:apple-grid`, `…BLTMosaicFlip`, `apple:3D-cube`, `apple:ca-revolve`, `…BLTReflection`, `apple:revolve`, `…BLTRevolvingDoor`, `apple:doorway`, `apple:fall`, `apple:scale`, `apple:bounce`, `apple:slide`, `apple:pivot`, `apple:FlipThrough`, `apple:ca-isometric`, `…KLNComet`, `…BLTBlinds` | **Pop-in / union frame** if an incoming copy is visible before its intended reveal or under transparent outgoing pixels; **none** from alpha arithmetic if transforms/clips/initial visibility produce the intended disjoint reveals. **Wrong alpha arithmetic** if export tries a replacement with opposing source-over fades. Which condition applies is unknown | §2.1 data-driven geometry; §1.3 separate render/start, hidden and contents rules; D §2. Edge Blinds/Cube/Reflection/revolve/RevolvingDoor explicitly create outgoing-only fade, making pop-in the prediction for a fill-less pair |
| `…BLTFadeThruColor` | **Pop-in / union frame** if incoming is exposed under unfilled outgoing; **none** if an intentional opaque colour veil and timing hide it; **wrong alpha arithmetic** if merely two complementary source-over fades. Whether an opaque colour field is intended on a DSK is an owner question, not an alpha bug established here | §2.1 flags only; export required; D §2 |
| `…KLNSwap` | **Pop-in / union frame** if child 1 is outgoing above a static incoming child; it is explicitly driven to opacity 0 during [0.4T,0.8T]. **Wrong alpha arithmetic** if another overlapping child fades oppositely. **None** if native semantics intentionally show the two transformed objects with source-over | §2.1 Swap adjustment + D §2; texture roles unknown |
| `apple:action-opacity`, `apple:action-blink` | **None** for one existing target whose alpha is intentionally multiplied; **wrong alpha arithmetic / union frame** if an export duplicates the same intended replacement under it. No such duplicate is established on disk | §2.3 opacity wrappers and repetition; D §2 single-object distinction |
| `apple:action-motion-path`, `apple:action-rotation`, `apple:action-bounce`, `apple:action-flip`, `apple:action-jiggle`, `apple:action-pop`, `apple:action-pulse` | **None** from alpha arithmetic for a single transformed target; **union frame** if replacement leaves an old target painted. Movie remount/hand-back and curve fidelity remain separate unknowns | §2.3 current-object routing, §2.2 video handling, §1.3 transforms |
| `apple:action-scale` | **None** for one target plus the stock complementary contents step; **union frame** if old contents remains visible with the new copy; a premature new texture is **pop-in**. A proposed continuous two-opacity contents replacement would have **wrong alpha arithmetic** without proven isolation/weights | §2.3 Scale splice, §1.3 contents halves, D §2 |
| `apple:gallery-dissolve`, any other `smartBuild` | CSS-only single-object motion: **none** under single-target model; two visible copies: **pop-in / union frame**. With contents: mixed GL path, outside pure CSS prediction; fallback GB with second texture full-strength predicts **wrong alpha arithmetic / pop-in** for a replacement blend. IB's actual premultiplication/native fidelity requires separate GL evidence; do not label it broken from the name | §3, P GB @2202984 and IB @2197873; D §2 |
| Generic new CSS `buildIn` / `buildOut` (e.g. owner-authored entrance/exit absent from C) | **None** for a sole object fade/transform; **pop-in** if initial visibility/backwards fill exposes it before animation; **union frame / wrong alpha arithmetic** only for unintended duplicate/replacement layers | §1.3 WB fill/hidden logic, §2.2 routing; D §2 |
| `apple:dissolve character`, buildIn `apple:dissolve`, both Line Draw names | **None** additional alpha defect for the observed single-leaf 0→1 fade. The Line Draw fade is a proven semantic degradation already addressed by L, not an F2 cross-fade defect | C; L §§1–2; D §2 |
| `apple:movie-start`, `renderMovie`, `renderWebVideo`, `apple:audio-start` | **None** as a slide replacement arithmetic claim: service effects, not two-slide blends. Their surrounding effect's movie ownership and visibility still need measurement | §2.2 service dispatch |

**Adjust-time exception / tree corruption (PREDICTED):** a non-transition exported under `apple:scale`, `apple:fall` or `…KLNSwap` meets Chrome-only code that assumes a two-child transition container; expect a thrown `adjustScript` (deck fails to start or advance) or a hidden/missing object. Not alpha-related; it shows on opaque pages too.

This adds a fifth class beside pop-in, union frame, wrong alpha arithmetic and no extra alpha defect. P/P17 @1957308–1957703 call adjustments for every event/hyperlink effect without a type filter. Chrome @1962856–1966272 dereferences child 1 for Fall/Swap; Scale swaps children 0/1 and sets the moved leaf hidden (@1963870 vicinity). On an animated single-leaf `N[N[T]]` shape, that can leave child 0 undefined. Whether any current Scale **build** exports as `apple:scale` is unverified; do not infer an observed failure. Other browsers have related adjustments (§2.1). The first later eye check is that the deck starts and every click advances in Chrome; add one Scale build-in slide only if usage warrants it. Build/action defects require no opaque twin.

Native-alpha evidence is also pending: a native screen recording shows gross motion but cannot establish keyed translucent alpha. For a failing family, try a transparent-background ProRes 4444 QuickTime reference and check No Fill alpha on slide 1 first; codec support is present in [dsk_movie_export.py:85](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/dsk_movie_export.py:85), but alpha preservation is **unverified**. Product-path eye qualification uses default continuity; [README R2/R11](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/README.md:152) already declines build-in/out carries and carries into slides with outgoing transitions outside Magic Move/Dissolve/none. Push/Wipe restart behaviour under that decline is not a new F2 defect. Continuity-off is W1 diagnosis only.

Handled transition `apple:dissolve` / `none` retain D's proven pop-in / union-frame findings and R's shape-limited fix; F2 must not infer that fix applies to a same-shaped tree with another name. Every movie case adds a distinct possible **baked-frame jump** or independent live-video overlay, which is separate from the alpha and adjust-time classes above and must be recorded separately. The existing D4 predicate only admits the two transition names; F2 presently gets no such guarantee. [R lines 67–85, 164–168; D §§1.4, 3.2, 12 decisions 6, 14–15]

## Appendix A. Count-checked names and method anchors

The following inventory exhausts exact quoted `apple:` / `com.apple.` literals in P, plus explicit render services and the observed generic names. It is not a list of every UI effect Keynote can export. Counts are lexical occurrences, **not** registrations or export counts. `none` includes generic CSS/media strings. Each method token listed has count exactly 1 in both players. [P/P17 scan recorded in player_f2_anchors.json]

### A.1 Inventory

Offsets are zero-based UTF-8 bytes; name offsets exclude the opening quote. Exact quoted literals counted. Method tokens include punctuation.

| Token | Count in each | e9b2fad4 | 17c0c938 |
|---|---:|---|---|
| `class yB{` | 1 | 2270532 | 2270532 |
| `class WB{` | 1 | 2271556 | 2271556 |
| `class VB{` | 1 | 2286448 | 2286448 |
| `class NB{` | 1 | 2292342 | 2292342 |
| `class fB{` | 1 | 2262229 | 2262229 |
| `class IB extends` | 1 | 2197873 | 2197873 |
| `class GB extends` | 1 | 2202984 | 2202984 |
| `adjustEffects(A,B){` | 1 | 1957878 | 1957878 |
| `adjustEmphasisBuilds(A,B){` | 1 | 1958525 | 1958525 |
| `adjustEffectsForSafari(A,B){` | 1 | 1960294 | 1960294 |
| `adjustEffectsForChrome(A,B){` | 1 | 1962856 | 1962856 |
| `adjustEffectsForFirefox(A,B){` | 1 | 1966272 | 1966272 |
| `adjustEffectsForEdge(A,B){` | 1 | 1969407 | 1969407 |
| `processEffects(A){` | 1 | 2311135 | 2311135 |
| `renderEffects(A){` | 1 | 2311803 | 2311803 |
| `renderEffect(A,B,g){` | 1 | 2313757 | 2313757 |
| `initRendererFlags(A){` | 1 | 2292945 | 2292945 |
| `addAnimationNode(A,B,g,C){` | 1 | 2294205 | 2294205 |
| `addNode(A,B,g){` | 1 | 2296181 | 2296181 |
| `applyCssAnimation(A,B,g,C){` | 1 | 2303763 | 2303763 |
| `animateContentsWillBegin(A){` | 1 | 2307742 | 2307742 |
| `createTimingFunctionForAction(A){` | 1 | 2282016 | 2282016 |
| `createAnimationRuleForKeyframes(A){` | 1 | 2282473 | 2282473 |
| `createAnimationRuleForKeyframe(A,B,g){` | 1 | 2283702 | 2283702 |
| `vC={` | 1 | 2367654 | 2367692 |
| `jC=[` | 1 | 2368216 | 2368254 |
| `const m=[` | 1 | 1984648 | 1984648 |
| `qC&&-1!==jC.indexOf(C.name)` | 1 | 2312807 | 2312807 |
| `qC&&-1!==jC.indexOf(i)` | 1 | 2314108 | 2314108 |

| Exact name | Count in each | In jC | e9b2fad4 offsets | 17c0c938 offsets |
|---|---:|---|---|---|
| `apple:3D-cube` | 3 | no | 1972011, 2294913, 2305598 | 1972011, 2294913, 2305598 |
| `apple:FlipThrough` | 1 | no | 1973711 | 1973711 |
| `apple:action-blink` | 3 | no | 1958571, 1984698, 2367880 | 1958571, 1984698, 2367918 |
| `apple:action-bounce` | 2 | no | 1984739, 2367913 | 1984739, 2367951 |
| `apple:action-flip` | 2 | no | 1984719, 2368017 | 1984719, 2368055 |
| `apple:action-jiggle` | 3 | no | 1959332, 1984761, 2368083 | 1959332, 1984761, 2368121 |
| `apple:action-motion-path` | 2 | no | 2303553, 2367694 | 2303553, 2367732 |
| `apple:action-opacity` | 1 | no | 2367659 | 2367697 |
| `apple:action-pop` | 2 | no | 1984658, 2368130 | 1984658, 2368168 |
| `apple:action-pulse` | 3 | no | 1958596, 1984677, 2368172 | 1958596, 1984677, 2368210 |
| `apple:action-rotation` | 1 | no | 2367734 | 2367772 |
| `apple:action-scale` | 2 | no | 2314516, 2367783 | 2314516, 2367821 |
| `apple:apple-grid` | 2 | no | 1958081, 2293374 | 1958081, 2293374 |
| `apple:audio-start` | 1 | no | 2311959 | 2311959 |
| `apple:bounce` | 1 | no | 1969453 | 1969453 |
| `apple:ca-isometric` | 1 | no | 2288839 | 2288839 |
| `apple:ca-push` | 1 | no | 2293142 | 2293142 |
| `apple:ca-revolve` | 2 | no | 2294826, 2305555 | 2294826, 2305555 |
| `apple:ca-swing` | 1 | no | 2292990 | 2292990 |
| `apple:ca-text-shimmer` | 3 | yes | 2261867, 2264718, 2368645 | 2261867, 2264718, 2368683 |
| `apple:ca-text-sparkle` | 3 | yes | 2261915, 2264769, 2368669 | 2261915, 2264769, 2368707 |
| `apple:dissolve` | 0 | no | absent | absent |
| `apple:dissolve character` | 0 | no | absent | absent |
| `apple:doorway` | 2 | no | 1971265, 2303848 | 1971265, 2303848 |
| `apple:fall` | 1 | no | 1962904 | 1962904 |
| `apple:gallery-dissolve` | 1 | no | 2265454 | 2265454 |
| `apple:magic-move-implied-motion-path` | 3 | yes | 2264652, 2288776, 2368606 | 2264652, 2288776, 2368644 |
| `apple:movie-start` | 0 | no | absent | absent |
| `apple:pivot` | 1 | no | 1969490 | 1969490 |
| `apple:revolve` | 1 | no | 1972075 | 1972075 |
| `apple:scale` | 4 | no | 1960342, 1963758, 1966321, 1969508 | 1960342, 1963758, 1966321, 1969508 |
| `apple:slide` | 1 | no | 1969472 | 1969472 |
| `apple:wipe-iris` | 5 | yes | 2205006, 2207301, 2264351, 2264898, 2368221 | 2205006, 2207301, 2264351, 2264898, 2368259 |
| `com.apple.iWork.Keynote.BLTBlinds` | 4 | no | 1957917, 1971971, 1972671, 2357138 | 1957917, 1971971, 1972671, 2357176 |
| `com.apple.iWork.Keynote.BLTFadeThruColor` | 1 | no | 2293168 | 2293168 |
| `com.apple.iWork.Keynote.BLTMosaicFlip` | 1 | no | 2293427 | 2293427 |
| `com.apple.iWork.Keynote.BLTReflection` | 1 | no | 1972031 | 1972031 |
| `com.apple.iWork.Keynote.BLTRevolvingDoor` | 1 | no | 1972095 | 1972095 |
| `com.apple.iWork.Keynote.BLTSwoosh` | 3 | no | 1958203, 2293017, 2293503 | 1958203, 2293017, 2293503 |
| `com.apple.iWork.Keynote.BUKAnvil` | 3 | yes | 2224133, 2264943, 2368239 | 2224133, 2264943, 2368277 |
| `com.apple.iWork.Keynote.BUKFlop` | 3 | yes | 2217603, 2264526, 2368309 | 2217603, 2264526, 2368347 |
| `com.apple.iWork.Keynote.BUKTwist` | 3 | yes | 2210530, 2264396, 2368274 | 2210530, 2264396, 2368312 |
| `com.apple.iWork.Keynote.KLNColorPlanes` | 3 | yes | 2215265, 2264458, 2368343 | 2215265, 2264458, 2368381 |
| `com.apple.iWork.Keynote.KLNComet` | 1 | no | 2296584 | 2296584 |
| `com.apple.iWork.Keynote.KLNConfetti` | 5 | yes | 2231800, 2234472, 2264587, 2265132, 2368419 | 2231800, 2234472, 2264587, 2265132, 2368457 |
| `com.apple.iWork.Keynote.KLNDiffuse` | 3 | yes | 2236800, 2265197, 2368457 | 2236800, 2265197, 2368495 |
| `com.apple.iWork.Keynote.KLNFlame` | 3 | yes | 2227406, 2265005, 2368384 | 2227406, 2265005, 2368422 |
| `com.apple.iWork.Keynote.KLNShimmer` | 3 | yes | 2250673, 2265261, 2368532 | 2250673, 2265261, 2368570 |
| `com.apple.iWork.Keynote.KLNSparkle` | 3 | yes | 2256876, 2265325, 2368569 | 2256876, 2265325, 2368607 |
| `com.apple.iWork.Keynote.KLNSwap` | 4 | no | 1962099, 1965515, 1968078, 1972943 | 1962099, 1965515, 1968078, 1972943 |
| `com.apple.iWork.Keynote.KNFireworks` | 3 | yes | 2238679, 2265067, 2368494 | 2238679, 2265067, 2368532 |
| `com.apple.iWork.Keynote.LineDraw` | 0 | no | absent | absent |
| `com.apple.iWork.Keynote.LineDrawForLine` | 0 | no | absent | absent |
| `none` | 33 | no | 94087, 111320, 112355, 113601, 121771, 121802, 121846, 124588, 136421, 140585, 140615, 168601, 168708, 168757, 168976, 169134, 169164, 172666, 230953, 237404, 239268, 253558, 279280, 1979443, 1980670, 1984565, 2269326, 2270474, 2296318, 2306798, 2319738, 2326790, 2327368 | 94087, 111320, 112355, 113601, 121771, 121802, 121846, 124588, 136421, 140585, 140615, 168601, 168708, 168757, 168976, 169134, 169164, 172666, 230953, 237404, 239268, 253558, 279280, 1979443, 1980670, 1984565, 2269326, 2270474, 2296318, 2306798, 2319738, 2326790, 2327368 |
| `renderMovie` | 8 | no | 2288869, 2295388, 2298457, 2300463, 2303116, 2312136, 2312447, 2315736 | 2288869, 2295388, 2298457, 2300463, 2303116, 2312136, 2312447, 2315736 |
| `renderWebVideo` | 6 | no | 2288909, 2298481, 2300501, 2305403, 2312160, 2312485 | 2288909, 2298481, 2300501, 2305403, 2312160, 2312485 |


## Appendix B. Pasted shape and timing table from the census run

These are all 32 distinct `(type, name, shape, effect duration, animation durations, timingFunctions, fillModes)` variants across the 35 roots. Counts include duplicates across roots; individual slide/deck membership is in `census_f2_rows.tsv`. `"<absent>"` records an absent field, not a linear/easing inference. Nested per-keyframe `timingFunctions` and all values are retained in the full animation trees in `census_f2.json`.

### B.1 Variants

| Type / name | Count | Shape | Effect duration (s) | Animation durations (s) | Timing functions | fillMode | First source anchor |
|---|---:|---|---|---|---|---|---|
| `buildIn / apple:dissolve` | 1 | `N[N[T{group,hidden,opacity}]]` | `1` | `["1"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/330155D7-09BF-459C-8604-105C79FF3877/330155D7-09BF-459C-8604-105C79FF3877.json#/events/0/effects/0/effects/0/effects/0` |
| `buildIn / apple:dissolve character` | 48 | `N[N[T{group,hidden,opacity}]]` | `1` | `["1"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/0C652BEB-F445-48CF-BFD0-4194C6B7A438/0C652BEB-F445-48CF-BFD0-4194C6B7A438.json#/events/0/effects/0` |
| `buildIn / apple:movie-start` | 227 | `N[N[T{group,hidden,isPlaying}]]` | `0.001` | `["0.001"]` | `["\"<absent>\""]` | `["\"both\"","\"removed\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D1-html/assets/86517898-AF55-4304-9969-9267638FBA46/86517898-AF55-4304-9969-9267638FBA46.json#/events/0/effects/0` |
| `buildIn / com.apple.iWork.Keynote.LineDraw` | 1 | `N[N[T{group,hidden,opacity}]]` | `0.8` | `["0.8"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/330155D7-09BF-459C-8604-105C79FF3877/330155D7-09BF-459C-8604-105C79FF3877.json#/events/0/effects/0` |
| `buildIn / com.apple.iWork.Keynote.LineDrawForLine` | 1 | `N[N[T{group,hidden,opacity}]]` | `0.7` | `["0.7"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/330155D7-09BF-459C-8604-105C79FF3877/330155D7-09BF-459C-8604-105C79FF3877.json#/events/0/effects/0/effects/0` |
| `buildIn / renderMovie` | 116 | `N[T,TV,T]` | `0` | `[]` | `[]` | `[]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/08C861A1-CB39-4832-B189-6DF95B7F3396/08C861A1-CB39-4832-B189-6DF95B7F3396.json#/events/0/effects/0/effects/0` |
| `buildIn / renderMovie` | 111 | `N[T,TV]` | `0` | `[]` | `[]` | `[]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D1-html/assets/86517898-AF55-4304-9969-9267638FBA46/86517898-AF55-4304-9969-9267638FBA46.json#/events/0/effects/0/effects/0` |
| `transition / apple:dissolve` | 5 | `N[N[T,T{opacity}]]` | `1` | `["1"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D2-across-html/assets/9CF0C1FF-B37E-43A2-A3F0-A91215EAD99B/9CF0C1FF-B37E-43A2-A3F0-A91215EAD99B.json#/events/1/effects/0` |
| `transition / apple:dissolve` | 42 | `N[N[T,T{opacity}]]` | `1.5` | `["1.5"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/08C861A1-CB39-4832-B189-6DF95B7F3396/08C861A1-CB39-4832-B189-6DF95B7F3396.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 3 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T],N{group,zPosition}[T],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T{contents,group,transform.rotation.z}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity,transform.rotation.z}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/5BA2FB02-70A8-4E2C-AFFA-E48661808E8F/5BA2FB02-70A8-4E2C-AFFA-E48661808E8F.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 3 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T],N{group,zPosition}[T]]` | `1.5` | `["1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/E37ABAC7-E88B-4757-BC9D-562C9AC5F097/E37ABAC7-E88B-4757-BC9D-562C9AC5F097.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 13 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/p2-binary/html-disposable/assets/D4D95253-4C37-40CF-A4A4-62D8DE24EF2A/D4D95253-4C37-40CF-A4A4-62D8DE24EF2A.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,transform.rotation.z,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,opacity,zPosition}[T{group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.translation}],N{group,opacity,zPosition}[T{group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity,transform.rotation.z}],N{group,opacity,zPosition}[T{group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/DAC21D01-4C0B-4292-A009-8B511D36F68D/DAC21D01-4C0B-4292-A009-8B511D36F68D.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/271371F9-08BC-4095-A016-B35F3831D11C/271371F9-08BC-4095-A016-B35F3831D11C.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{contents,group,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Positive Control/html/assets/40D1B19D-173E-4E19-9907-100002C8D874/40D1B19D-173E-4E19-9907-100002C8D874.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 4 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T]]` | `1.5` | `["1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/7A851F4D-4648-4545-A491-58838A7CD843/7A851F4D-4648-4545-A491-58838A7CD843.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/D4D95253-4C37-40CF-A4A4-62D8DE24EF2A/D4D95253-4C37-40CF-A4A4-62D8DE24EF2A.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity,transform.rotation.z}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,opacity,zPosition}[T{group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/alpha-dsk-textures/html-unmodified/assets/02FFC05C-BF37-4E96-8E71-33CA86C5D362/02FFC05C-BF37-4E96-8E71-33CA86C5D362.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T],N{group,zPosition}[T],N{group,zPosition}[T],N{group,opacity,zPosition}[T{group,opacity}],N{group,zPosition}[T]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D7-html/assets/EC1B1743-BCCE-459F-9080-E0385E656256/EC1B1743-BCCE-459F-9080-E0385E656256.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D3-html/assets/D4A1DF22-D248-4A45-8125-8C2288F5AB11/D4A1DF22-D248-4A45-8125-8C2288F5AB11.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 4 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D5-html/assets/780DDBAE-C035-42AE-A6E5-A86DC0240E80/780DDBAE-C035-42AE-A6E5-A86DC0240E80.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 13 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D1-html/assets/B1889873-9729-4643-9601-1D7B98EE99F3/B1889873-9729-4643-9601-1D7B98EE99F3.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,opacity,zPosition}[T{contents,group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D7-html/assets/3EF1B8FE-81C6-4735-B016-0CF9B93D61A4/3EF1B8FE-81C6-4735-B016-0CF9B93D61A4.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,opacity,zPosition}[T{contents,group,opacity,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D7s-html/assets/A804185A-6144-40C4-940D-40BF3D4D4B36/A804185A-6144-40C4-940D-40BF3D4D4B36.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D6-html/assets/D4A1DF22-D248-4A45-8125-8C2288F5AB11/D4A1DF22-D248-4A45-8125-8C2288F5AB11.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 18 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D1-html/assets/D4A1DF22-D248-4A45-8125-8C2288F5AB11/D4A1DF22-D248-4A45-8125-8C2288F5AB11.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D3-html/assets/BD6C4118-9129-48A4-BA25-5E4F033A8CE6/BD6C4118-9129-48A4-BA25-5E4F033A8CE6.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 2 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{contents,group,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D4-html/assets/D4A1DF22-D248-4A45-8125-8C2288F5AB11/D4A1DF22-D248-4A45-8125-8C2288F5AB11.json#/events/2/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 16 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T],N{group,opacity,zPosition}[T{group,opacity,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/08C861A1-CB39-4832-B189-6DF95B7F3396/08C861A1-CB39-4832-B189-6DF95B7F3396.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 3 | `N[N[N{group,zPosition}[T{group,hidden,opacity}]],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.0015000000000000568","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Minimal Alpha_DSK/html/assets/3C08AAF8-1D66-467C-B5B1-C2BD25E6E9E8/3C08AAF8-1D66-467C-B5B1-C2BD25E6E9E8.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{group,hidden,opacity}]],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.0015000000000000568","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures/gl-decks/Positive Control/html/assets/8E175DCA-856A-471D-B17E-756A9FA41DB0/8E175DCA-856A-471D-B17E-756A9FA41DB0.json#/events/1/effects/0` |
| `transition / none` | 20 | `N[N[T,T{hidden}]]` | `0.001` | `["0.001"]` | `["\"<absent>\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Continuity/D1-html/assets/86517898-AF55-4304-9969-9267638FBA46/86517898-AF55-4304-9969-9267638FBA46.json#/events/1/effects/0` |

## 6. Rev 3 addendum — usage-selected GL and conversion

2026-10-14, owner D1–D4. **This addendum supersedes rev 2's “source-deck usage unrun”, unresolved OQ-F2-0 and blanket “no GL fixes” scope statements above.** W(−1) was completed by the coordinator: [GW deck census](wall_usage_census.md). This agent did not open/read any `.key`, run a conversion, browser/OBS/Keynote/osascript/pytest/git, or qualify pixels. The original fixture census remains a separate population. Seven increment-1 rows are selected in [rev 3 plan §1](keynote_live_f2_transitions_builds.plan.md); emitted increment-1 HTML remains unknown.

### 6.1 Both-player verification and shared GL state

Re-read P and P17 (§0) as bytes: sizes and full SHA-256 still match. Removing P17's two `,isEvalSupported:!1` insertions produces P exactly. All renderer/shader anchors below are identical in both; the later `jC` and R8 offsets differ as recorded. [Audit script](rev3_static_audit.py), [counts/offsets](rev3_gl_anchors.md), [machine record](rev3_gl_anchors.json). This is lightweight static inspection, not a rendering/test run.

- `jC` remains 14 names. The five selected GL names are present; Iris occurs in both transition and build switches. `PB.renderEffects` @2312807 routes a root replacement; `PB.renderEffect` @2314108 routes an object replacement when `qC` is true. `fB` @2262229 dispatches by **type and name** (§1.2). GL unavailable means the generic exported CSS tree route, not proof of native fidelity.
- `fB` requests `getContext("webgl") || getContext("experimental-webgl")` @2262426 **without options**. There is **no `preserveDrawingBuffer` token** in either player. It requests neither `alpha:false`, `premultipliedAlpha:false` nor preservation here; normal context defaults are expected (alpha/premultipliedAlpha true, preservation false), but actual engine attributes remain a live observation. Every `fB.animate` frame clears **`clearColor(0,0,0,0)`**, then color and depth, @2265918. No selected effect overrides this to opaque. A black-box prediction from an opaque GL clear has no source basis.
- `R.createTexture` @2030871 uploads ordinary slide/object images with **`UNPACK_PREMULTIPLY_ALPHA_WEBGL=true`**, `FLIP_Y=true`, RGBA/UNSIGNED_BYTE, LINEAR and CLAMP_TO_EDGE. `R.bindTextureWithImage` @2031394 uses the same premultiplication with **FLIP_Y=false** for particle sprites. Neither is a straight-alpha upload. All four `UNPACK_PREMULTIPLY_ALPHA_WEBGL` occurrences in the player set true; the other two allocate framebuffer textures (§6.1 anchors).
- Base `aB.setupProgram` @2197336 enables blending and sets **`SRC_ALPHA, ONE_MINUS_SRC_ALPHA`**. Twist/Flop do not override it. Iris transition/build and all three selected build draw loops use **`ONE, ONE_MINUS_SRC_ALPHA`**; the ordinary object helper `sB` also sets ONE at setup. These are regular `blendFunc`, not separately corrected alpha factors.
- Shader locations (each exact dictionary token occurs once per player): `defaultTexture` @1984825 samples unchanged; `defaultTextureAndOpacity` @1985534 multiplies **all RGBA** by Opacity; `iris` @1988364; `twist` @1989786; `flop` @1992710; `anvilsmoke` @1994489; `anvilspeck` @1998066; `sparkle` @2027163. Exact shader arithmetic is below. The base blend literal occurs twice globally (base @2197825; an unselected Confetti path @2232185), not once; audit counts preserve this distinction.

**Build compositing over the rest of the slide:** `PB.renderEffect` @2313757 locates the target object's existing DOM node, appends a slide-sized GL canvas to that node's parent (or reuses this renderer's canvas), remembers `nodeToSwapId` and leaves the other slide DOM in place. `animateEffectWillBegin` @2316844 draws/starts GL, then hides the replaced node. Transparent GL pixels expose the remaining DOM. Multiple effects may share the canvas; `fB` keeps programs by object ID and draws them in its list order after a shared clear. `DB/cB/mB` draw textured descendants of the **effect subtree**, not a whole incoming slide. Nonanimated visible descendants use `sB`; highlighted-bullet descendants have their own opacity branch. The canvas's append order can differ from the object's original sibling order, so foreground/movie occlusion is an eye/W1 concern. It is not justification to add a counterpart texture to a build.

### 6.2 Selected effect implementation, meshes and particles

| Effect / route | Drawing facts in both P/P17 |
|---|---|
| Twist: `fB → hB` @2210480 | Program `twist`; 24×24 vertex grid, 23 row triangle strips (48 indices each), dynamically recomputed positions/normals. Enables face culling. Texture 0 and texture 1 draw on opposite faces with different texture matrices and `FlipNormals`; order reverses at 50%. They are geometric front/back surfaces, **not complementary-opacity slide fades**. Shader returns `(tex.rgb * diffuse + specular, tex.a)`; specular is not multiplied by texture alpha. Uses base SRC_ALPHA blend |
| Flop: `fB → YB` @2217553 | `flop` + `defaultTexture`; 8×8 bending half-slide mesh (7 strips, 16 indices each), chosen orientation from direction. Draws one static quad from texture 1 and another from texture 0 with culling disabled, then bends/draws opposite faces using both textures with culling. Fragment scales RGB by diffuse light and leaves alpha unchanged; static quads sample unchanged. Uses base SRC_ALPHA blend |
| Iris transition: `fB → rB` @2204956 | `iris`, one four-vertex TRIANGLE_STRIP. If texture 1 exists it is drawn full with `PercentForAlpha=0, Mix=0`, then texture 0 with animated radial mask. Shader is `Opacity * sample * abs(Mix - smoothstep(radius², radius²+tolerance, dist))`; mask scales RGBA together. Opacity is 1. Direction/buildOut determines progress and Mix. Source-over ONE blend; no complementary erase of the full underlying texture. Which physical source/destination is texture 0/1 must be resolved from the real export, not variable names |
| Iris build: `fB → DB` @2207240 | `iris` + one `sB/defaultTextureAndOpacity` per texture. Per-leaf four-vertex quad and aspect ratio, initial rotation/scale applied to MVP. Animated leaves get radial mask and `root opacity * leaf initial opacity`; static/highlighted/completed branches draw ordinary leaves. No second full-slide underlay in this class. Build-in/out and direction invert progress; source-over ONE |
| Sparkle: `fB → mB` @2256815 → `HB` @2253177 → `dA` @2167291 | `sparkle` particles plus object shader `defaultTextureAndOpacity` (also `sB` for static/settled leaves). HB progressively changes the object's quad **and UV rectangle** by direction; object draw uses root×leaf opacity. Effect region expands by at least 128 px, clipped to slide. Actual particle count is `parseInt((2-sqrt(t))/2 * 1500 * duration/1000)` where t is clipped region area/slide area; the separate `p_numberOfParticlesForTR` cap of 3276 is **not called by this constructor**. `dA` uses four-vertex 128×128 sprite quads, random starting scatter/speed, direction-dependent staggered life; no per-object alpha mask in the sparkle shader. Sprite uses premultiplied upload. Fragment multiplies sampled RGBA componentwise by `v_Color`; vertex sets `v_Color=(rgb, (1-life²)*Opacity)`. HB sets Color white and calls particles `drawFrame(percent,1)`, without root/leaf opacity |
| Anvil: `fB → cB` @2224072 | `anvilsmoke` + `anvilspeck`, ordinary object `sB/defaultTextureAndOpacity`. Object quad drops from above with quadratic position and randomized decaying camera shake; root×leaf opacity used for the object. Each texture has **300 smoke + 40 speck particles**, initially 16×16 sprites; `GA` @2153836 and `rA extends nA` @2154992 scatter from the lower edge, with randomized speed/scale/lifetime (smoke also rotates). Smoke gets `drawFrame(J,1-J²)`; specks get a clamped fade during J<0.5. Both shaders set **`v_Color=vec4(thisOpacity)`**, scaling RGB and alpha together. Parent/leaf opacity does not multiply those particle calls |

Particle base `nA` @2146165 supplies four vertices and six triangle indices per selected particle, draws `TRIANGLES/UNSIGNED_SHORT`, sets Percent/Opacity and the sprite texture. Sparkle/Anvil pass sprite images, not the object's RGBA as a particle texture; the geometry/placement are based on object dimensions. All these class tokens occur once per player except unrelated minified class-name collisions: the audit deliberately uses **`class rA extends nA`**, not the PDF.js `rA` class near @314151.

### 6.3 What existing MM patches actually confer

Read [live_runtime.py](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/live_runtime.py:219). Each R1–R8 **old literal is present exactly once in P and P17**, with lines/byte offsets in [the audit](rev3_gl_anchors.md). Existing rendering switch/pins remain the contract; the audit does not execute patches or recalculate served pins.

| Patch | Shared location and selected-effect inheritance |
|---|---|
| R1/R2, lines 220/229 | Add opacity/ancestor annotations while `fB.textureInfoFromEffect` traverses **all GL effects**. Selected effects get the metadata, but their custom draws do not consume `obedOpacity` / `obedParentOpacity`. R13 (line 277 onward) passes duration into this traversal for admitted leaf fades; that does not change these custom consumers |
| R3/R4, lines 233/238 | Correct `QB.renderFrameWithContext` animated opacity and `eB` unanimated MM leaves. `pB` (MM) creates `eB`; selected `hB/YB/rB/DB/cB/mB` draw through their own routines/`sB/HB`, so **do not inherit the corrected opacity output** |
| R5, line 242 | Makes DOM hide synchronous after the first GL draw instead of a zero-timeout. **All five selected GL names inherit it**, both root transition and per-object build routes. CSS Revolve does not |
| R6, line 246 | Shared setup hook invokes extra hand-back destination textures **only for exact MM name**; none of these selected names gets them |
| R7, line 252 | `obedMix` selects hand-back texture in QB's contents path. None of these selected custom draws uses it |
| R8, line 256 | Preloads next scene only when next effect is exact MM name. Not selected F2 effects |

No R1–R8 patch changes the selected shaders, texture premultiplication, blend function or transparent clear. MM's good translucent output is not evidence that Twist/Flop/Iris/Sparkle/Anvil are already repaired. Dissolve and Line Draw later additions have their own narrow admission, not permission to capture all CSS/GL effects.

### 6.4 PREDICTIONS from arithmetic (not observed defects)

Let premultiplied sample be `(a*c,a)`. With ONE source-over, result is `Cs + Cd*(1-as)`, `as + ad*(1-as)`. With SRC_ALPHA for **both RGB and alpha**, source contributes `(a²*c,a²)` instead. Thus the actual Twist/Flop risk is **premultiplied input multiplied again**, not the reverse “straight-alpha input with ONE” example. Straight RGB with ONE would over-contribute colour; neither uploader does that.

- **Twist:** double weighting can dim/thin antialiasing/translucency; specular contributes `a*specular` under current blend but would leak colour at zero alpha under a naive ONE-only fix. Native lighting must be distinguished from wrong alpha. No opaque-clear box predicted.
- **Flop:** double weighting on mesh and static halves; source-over overlap with underlying half-surfaces can reveal artwork where a solid native slide face would occlude it. Alpha/underlay/edge seam is predicted, not a generic dissolve union repair.
- **Iris transition:** `mask*T0 over T1` leaves T1 at a hole where T0's alpha is zero, even when the reveal mask covers that pixel. A replacement wipe may need that pixel to become transparent instead. Predict underlay persistence/union if native reference intends replacement; export roles/native eye must settle it.
- **Iris build:** mask and opacity multiply all RGBA with ONE, so no intrinsic double-alpha or opaque-box error. Root×leaf ignores intermediate ancestor opacity in this custom draw, and the appended shared canvas may alter foreground order. These are conditional layout/opacity risks, not proof that every build fails on No Fill.
- **Sparkle:** sprite RGB is not reduced with lifetime alpha (`rgb=white`, opacity passed as 1); ONE adds stronger RGB than remaining alpha implies. Predict bright fringes/residual glow on fill-less composition, subject to native artistic intent. Particle strength also ignores object/ancestor opacity. The object's own reveal shader is premultiplication-consistent. Canvas ordering and nested opacity remain distinct possible symptoms.
- **Anvil:** smoke and speck shaders multiply all channels by fade and use ONE correctly; **no intrinsic fill-less blend defect predicted**. Root/leaf alpha is omitted from particles, and deeper ancestor opacity/foreground order may mismatch. Native smoke is intentional artwork, not automatically an unwanted box.
- **CSS Revolve:** exported 3D plane geometry, alpha, backface and stacking determine overlap/union or seam risk. No supported export yet establishes any failure. It needs a CSS-tree/native comparison if it fails, not a GL shader fix.

Only owner-marked failure starts W1. These mechanisms may also show on opaque pages; “fill-less” describes the intended qualification, not a claim that every symptom is alpha-exclusive.

### 6.5 Revolve name checks and adjust-time exception scope

`"apple:ca-revolve"` occurs **twice per player**, quoted byte @2294825 and @2305554 (name bytes @2294826/@2305555). It is absent from `jC`. `NB.addAnimationNode` excludes anchorPoint/position/zPosition wrappers from certain origin-Z handling when both origin flags exist; `NB.applyCssAnimation` skips anchorPointZ/zPosition application in that same origin case. Generic `VB/WB/NB` render the exported transforms/keyframes. It is **not** the separately named `apple:revolve` build, whose only named adjustment is the old-Edge fallback (§2.1).

The selected six distinct names have **zero byte occurrences in the adjustment region @1957878–1975600 in both players**, including Chrome's @1962856 branch. Rev 2's Scale/Fall/Swap assumed-two-child exception class remains valid as a conditional risk for those other names, **not a diagnosed or specifically predicted exception on these six names**. A degraded export can route elsewhere: Step 0 must record actual names, and eye must verify startup and every click.

### 6.6 Conversion evidence and the faithful deck recommendation

Read-only sources: [README](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/README.md:21), [Obed-Edom skill](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/.agents/skills/obed-edom/SKILL.md), [DSK assembly](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/dsk_assemble.py:6257), [resizer](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/remap_keynote.py:1328), [build planner](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/iwa_builds.py:189).

- DSK Generator makes an editable 1920×1080 copy with live overlays and generated movie clips; the later DSK Exporter flattens per-build images/per-slide movies. Alpha Keynote instead consumes HTML; those flat assets cannot qualify live builds/transitions.
- `dsk_assemble._slide_lines` **unconditionally writes Dissolve on clip-insertion slides**, line 4206. `plan_assembly` refuses movie/mixed slides without supplied clips, line 2724 vicinity. `_verify_builds`, line 5521 onward, verifies effect/type/identity multisets and order but allows missing builds for deleted objects, one supported entrance per inserted clip, and the intended clip Dissolve change (5648–5676). Full-deck conversion does not avoid this loss. Text splits/removed targets are further possible case loss, not a guarantee that the source still survives.
- Resizer copies the wall (line 1633), transforms existing objects and calls **`remap_keynote.restore_source_builds(dest, source, set(), say)`** last (1948). The implementation is at line 1047; `iwa_builds` supplies plan/verify, not a function of that name. Empty set means **no rewriting**, verify all. Nonempty restoration pairs surviving builds by effect/type/identity and chunk order; it keeps `min(source, output)` counts and cannot recreate lost effects. Referenced/no source transitions can be skipped. Missing builds/order outside patched slides warn, source/output read failure can skip, surplus/unsuppressed transition mismatch raises. A successful command is therefore insufficient fidelity evidence.
- No selected-name translation occurs in resizer preservation; retained source objects keep their effect strings. The only proved broad transition rewrite in the compared DSK path is clip Dissolve. Actual chosen objects/names/timeline survival still needs post-conversion readback and native playback, after owner go.

Recommendation: **owner duplicate/prune first → product resizer → owner transparent layout/No Fill**, with explicit paths under `~/Desktop/Convert wall to 16x9 CGs/F2-inc1/`; this avoids reconstructing the selected movie objects and converting the full 155-slide deck. It yields a source-artwork alpha test copy, not an assertion that CG geometry equals DSK Generator lower-third layout. The Generator route is acceptable only for cases its reports and native check preserve. Any lost selected case is conversion-unavailable; source-preserving copy is the fallback. All Keynote/osascript operations are owner-run only; none performed here.

Iris choice: **122** is already the retained destination of Revolve 121, so zero incremental slide cost. W(−1) provides no per-slide Iris tree/attributes, so no verified minimum across its seven source slides is knowable yet. Retain 122 plus the exact smallest additional subset covering exported shape/direction/opacity/timing/target variants; use an 18-slide discovery pool only if no prior export supplies that information. Details, mandatory transition successors and pruning rule are [plan §3](keynote_live_f2_transitions_builds.plan.md).

Movies: W(−1)'s abbreviated `movie-start` list explicitly includes **9 and 51**. Other selected slides' movie presence and which build targets movies are **unknown**. Coordinator must add the per-slide media/effect-target/retained-clip map; no deck access was attempted to fill it during the peer's live window.

### 6.7 Shared replay/Stage B seam

Read [GL replay runtime](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/src/obed_edom/live_gl_replay_js.py:1), [replay tests](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/tests/test_live_gl_replay_js.py:1), [oracle parity contract](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/tests/test_live_gl_replay_oracle_parity.py:1) and [Stage B plan](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808/.agents/plans/keynote_live_continuity_stage_b.plan.md:83); no tests executed.

`live_gl_replay_js.py` separately versions G2, injects only for a `glReplay` plan boundary, captures a settled MM frame and redraws it with a carried movie. It recognises numeric `*-canvas` IDs (line 58), wraps GL methods (285) and `getContext` (1287), records clear-delimited calls and uniforms, and maps uploads with saved flip/premul flags (258–279). `uploadVideo` (341–369) uses those original flags for texSubImage2D and restores binding/unpack state. False-premul marker/raw-pixel upload helpers (383/441) are restored diagnostic/writeback state, **not straight-alpha replacement of the player's ordinary image upload**. It supplies no selected-effect alpha correction and does not establish F2 replay eligibility.

Stage B owns continuity core and its new MM feed. The feed source file **does not exist in this checkout**; its plan specifies hooks chained with G2, ordinal/size/program-uniform binding and flag-preserving decoder uploads. The plan explicitly accounts for R6's extra hand-back textures after ordinary uploads (§1 limit 5). Overlap is therefore concrete: shared `fB` texture setup, MM QB/eB programs, upload/draw order, Opacity/Texture/Texture2/mixFactor, DOM hide timing, hook order and player/test pins. Custom effect-local patches minimise that overlap; changing common upload/blend/shaders/hide/opacity code requires the shared coordinator and appropriate MM/feed/G2 regressions. F2 does not take `live_continuity_js.py` or the feed and does not lift Stage B's R11 restrictions.

### 6.8 Revision result and remaining evidence

Rev 3 static audit passed its size/hash equivalence and **R1–R8 count=1 on both players** assertions; [complete anchors](rev3_gl_anchors.md) are retained for reproduction. W(−1) answers OQ-F2-0 (D2); Fade Through Color is absent/moot. Owner D3 permits selected GL fixes after the eye/W1 gates. New coordination items concern effect-local versus shared GL correction, source-fidelity/Iris/movie mapping and retained-name semantic degradation. No emitted-name result, measured alpha failure, or runtime qualification is inferred from this audit. Step 0 and the product-path eye step remain future owner-run work.
