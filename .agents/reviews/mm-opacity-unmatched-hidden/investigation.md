# F2 Magic Move 3→4: hidden source leaves painted by the GL renderer

**Investigator: GPT-6 Astra; 2026-10-15. Offline source/data investigation, then fix planning. No implementation or browser reproduction performed.**

## 1. Finding

The two duplicates are source-slide leaves flattened into the Magic Move canvas. The stock renderer loses their zero-opacity wrappers, ignores their constant `opacity 0→0` tracks, and does not implement their `hidden` tracks. It therefore draws each at **Opacity 1 throughout the move, including its final draw**. The shipped opacity patch knows the ancestor product is zero but rejects the leaf's encoding, falling back to that stock draw. The final canvas remains until the next scene replaces it.

**The proposed end-of-animation reversion is falsified by the code.** There is no GL track-removal event changing these leaves from 0 to 1 at 1.5 s. They are already submitted at 1 on the first draw. The owner's observation establishes their visibility after the zoom; it does not establish their first visible frame. The source predicts an earlier onset too. A browser capture remains necessary to assign compositor frame numbers and verify the entire visible interval. This report does not present source arithmetic as a rendered measurement.

This also explains why the artifact exists in both raw and Build Preview HTML, independently of texture repair, movie continuity, or GL replay. Native Keynote's reported clean result is the owner’s observation, not a new native run.

## 2. Inputs and reproducibility

Absolute read roots:

- Repository: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/session-cleanup-review-6b8808`.
- Fixture corpus: `/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures`.
- Evidence root (`TEX` below): `~/Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/` (persisted 2026-10-15; hashes in its `PINS.json`). The session scratchpad paths originally used are gone.
- Old stock: `TEX/F2-html-old-stock`; old repaired/preview-patched: `TEX/F2-html-old-repaired-patched`; edited export (`newexp3`) was the 08:25 re-export of F2.key `6fea812c…`, not kept — re-export the current deck if needed.

`offline_scan.py` and `offline_evidence.json` beside this report retain the census, source paths, fingerprints, byte offsets, relevant layer data, repair diff, and player digests. The script uses only offline Python and writes only beside itself. No git, browser, OBS, Keynote, osascript, pytest, or suites were invoked. In-memory calls to `patch_player`/`patch_rendering` only verified existing pin outputs; no exported player was changed.

Player identities:

| Input | SHA-256 |
|---|---|
| Stock player A | `e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354` |
| Stock player B; both F2 raw exports | `17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91` |
| Immutable old preview-patched B | `7d9eb308cadd02908732575a71e6eff437b63bc4d7ef46418805362905aa68dd` |

**Concurrent source drift:** `live_runtime.py`'s on/rendering pins changed between the first read and the census read. The first read's B rendering pin was the immutable old player's `7d9eb308…`; the later pin was `c0faaa3c…`. The opacity admission/arithmetic relevant here is unchanged in those reads and was checked directly in the immutable old player. `runtime_read_snapshot.py` preserves the later read, SHA-256 `2bb2d08ca22dcfd880c0520b7d9d3cc7a677d85d33e81cf274d5f8272c59d710`. Treat its pins as provenance, not future candidate pins. Rebase/re-pin against the implementation checkout at execution time. No assumption about the cause of that concurrent change is needed.

## 3. Export facts

`header.slideList[2]` is `6B05DE14-37DB-4505-B242-8996669A30BD`; `[3]` is `2C214651-FBDF-4698-B8D4-A16E2D803A56`. Each slide JSON is `assets/<id>/<id>.json`.

Slide 3 event 1 effect 0 is `apple:magic-move-implied-motion-path`, type `transition`, begin 0, duration 1.5 s, no child effects. Event 1 is click-driven. Slide 4 event 0 is automatic, `apple:twist-and-scale`, begin 0, duration 2 s (the owner's “Malaysia” build).

All ordinals below are **zero-based textured-leaf draw ordinals**, not layer IDs.

| Slot | Effect baseLayer path | Authored pixel rect | Texture |
|---|---|---|---|
| 7 | `layers[7].layers[0]` | `[568,510,44,50]` | `C0C026F1A1C5577B04664882E8B35C5D` |
| 8 | `layers[8].layers[0]` | `[652,506,88,59]` | `E7CF3AADFEEDA3217255F36836CDA7A8` |

For each leaf:

- Root opacity 1; immediate wrapper initial opacity 0, hidden false. Its only animated property is `zPosition`, in a 1.5 s `both` group; it does not animate opacity or visibility. The wrapper's opacity is genuinely constant zero.
- Leaf initial opacity 1, hidden false, scale 1; no motion or contents animation. `singleTextureOpacity` is 0, but this field is never read by the stock player.
- Exactly one outer animation group: begin 0, duration 1.5, fill `both`, `removedOnCompletion:false`, additive false, timeOffset/repeatCount 0, autoreverses false.
- First inner track: `opacity 0→0`, begin 0, duration **0.49995**, fill **`forwards`**, `removedOnCompletion:true`, EaseInEaseOut.
- Second inner track: `hidden true→true`, begin **0.49995**, duration **1.0000499999999999**, fill **`forwards`**, `removedOnCompletion:true`.

The wrapper opacity is also 0 in slide 3 event 0 and event 1 bases. Slide 4 has neither these textures nor these leaf rectangles. The old raw and repaired slide-3 MM effects are identical; fingerprint using the existing test normalization is `f2350147870865e13a6a4e588c1d3b06f50ed18204520b4283dc8f67e0717b66`.

The repair diff contains one layer texture-id change, at slide 4 `events[0].baseLayer.layers[5].layers[0].layers[0].texture`, from `DF3DB700…` to `32960D80…`, plus the new texture's asset-table entry. Neither suspect leaf nor the slide-3 MM changes. This independently supports the owner's exclusion of texture repair.

**Edited export:** `newexp3` removes both suspect leaves from slide 3's bases and effect; the MM has 9 leaves instead of 13. It also removes another leaf and changes the large-map fade endpoint from about 0.052985 to 0. Thus the edited export is useful as a real-data absence control, but not a pixel-identical twin obtained by fixing this defect. Its effect fingerprint is `406dff747ffa4193c45d70cbaff103f2538eb37d0b7c8c4279b8e8b9e23d4cd2`.

**Do not hide every leaf whose ancestor's initial opacity is zero.** Old slots 10 and 11 also have such an ancestor, but each wrapper has an opacity `1→1`, fill `both`, making its effective opacity **1**. They are legitimate matched/zooming objects. The patched ancestor products are `[1,1]`, whereas the duplicates' are `[1,0]`. The edited export still contains those legitimate objects (now slots 7 and 8).

## 4. Byte-anchored execution path

All offsets are **zero-based raw byte offsets**, found directly in both SHA-verified players; not character offsets copied from historical plans. A = e9b2fad4, B = 17c0c938. B adds two PDF.js options at 2331091 and 2331362; relevant earlier methods are identical.

| Anchor | A | B | Consequence |
|---|---:|---:|---|
| `QB.renderFrameWithContext` | 2189505 | 2189505 | Evaluates the leaf's first group's tracks only. |
| `case"opacity":if(d=R.scalar` | 2190238 | 2190238 | Reads endpoints and computes progress; never reads fillMode. |
| `var T=i.hidden?0:e.parentOpacity*i.opacity;` | 2190397 | 2190397 | Uses model visibility and root opacity; only unequal endpoints replace T. |
| R3 anchor `d!==U&&(T=...)` | 2190440 | 2190440 | Constant 0→0 does not override model 1. |
| `class eB` / no-animation opacity branch | 2191215 / 2192650 | same | Animated leaves call QB; static leaves use the separate R4 branch. |
| `class pB` (MM) | 2259434 | 2259434 | Builds an eB per flattened texture; draws in texture order. |
| `fB.setupTexture` | 2263021 | 2263021 | Seeds parentOpacity from effect baseLayer's initial opacity. |
| R1 `textureInfoFromEffect` | 2263373 | 2263373 | Flattens the hierarchy; stock parentOpacity is 1. |
| R2 recursive call | 2264160 | 2264160 | Stock passes root opacity unchanged. |
| `fB.animate` | 2265582 | 2265582 | Clears/draws; draws a terminal frame after elapsed exceeds durationMax, then stops scheduling. |
| `VB` / `WB` constructors | 2286448 / 2271556 | same | Layer construction / CSS keyframe construction; not QB animation evaluation. |
| `removeEvent` | 2291872 | 2291872 | Removes old scene children, including the held MM canvas. |
| `PB.renderEffects` | 2311803 | 2311803 | Routes MM into a canvas appended alongside the old scene node. |
| `animateEffectWillBegin` | 2316844 | 2316844 | Draws/starts GL, then hides swapped DOM. |
| R5 deferred hide / hide method | 2317031 / 2317094 | same | Patch makes the hide synchronous; it does not alter GL opacity. |
| `handleEffectDidComplete` | 2317143 | 2317143 | Runs child effects; this MM has none. Not the cause of the held frame. |
| `s(A){setTimeout(A,100)}` | 1977509 | 1977509 | Shared deferred callback, 100 ms. |
| `advanceToNextBuild` | 2349204 | 2349242 | At final state jumps to next scene with play enabled. |
| `jumpToScene` | 2352139 | 2352177 | Preloaded path defers setup through `s`; unloaded path additionally waits for assets. |
| `jumpToScene_partFour` | 2353722 | 2353760 | Calls displayScene before playing destination event. |
| `displayScene` | 2354643 | 2354681 | Deletes CSS animations and renders next event, tearing down old scene. |
| `playCurrentScene` | 2356281 | 2356319 | Schedules completion at effect/event end +100 ms. |
| `currentSceneDidComplete` | 2357464 | 2357502 | Sets final state; automatic next event advances through `s` (+100 ms). |

Relevant immutable **preview-patched B** offsets: QB still starts at 2189505; `__obedNodeOpacity` at 2265238; R6 helper `__obedHandbackTextures` at 2263646; `animateEffectWillBegin` at 2345164; `currentSceneDidComplete` at 2386033. Their snippets are saved in `offline_evidence.json`. Later runtime patch additions move downstream offsets, so do not apply these to a newly generated player.

### The arithmetic, at every draw

```text
Stock setup: parentOpacity = effect root opacity = 1
Leaf model: opacity = 1; hidden = false
Opacity track: d = 0; U = 0
QB: T = hidden ? 0 : parentOpacity * modelOpacity = 1
    d !== U is false, so T stays 1
    hidden is not a switch case in QB
    setGLFloat(1, "Opacity")
```

This holds at progress 0, 0.3333, just before/after 0.49995 s, just before 1.5 s, and progress 1. No branch changes at either track endpoint. `fillMode` and `removedOnCompletion` do not participate in QB. In the CSS path `WB.createAnimationRules` (2276990 both) builds end-value keyframes, and `hidden` becomes opacity keyframes (2284184 both); this is not the active GL path. In particular, neither `forwards` track requests a return to the model value. The constant zero wrapper independently suppresses the whole subtree in a hierarchy-aware renderer.

The shader's premultiplied result uses the Opacity uniform. The two leaf programs draw even when logically hidden; geometry stays at the source rectangles because these leaves have no transform tracks. Later draw slots are a logo and the two moving matched map pieces, not a destination duplicate at those rectangles. The code gives no basis for a special “only reveal at completion” rule or for assuming an occluder hides these leaves during the move.

### Why the existing patches miss

R1/R2 correctly pass effective ancestor product `X=0` to each duplicate. Then:

- `__obedNodeOpacity(leaf)` rejects a `hidden` track (`C=2`), and also would reject the constant opacity track's `forwards` rather than `both` fill. Result: null.
- `__obedChainOpacity(0, leaf)` returns null, **not zero**. Unknown descendants intentionally invalidate the constant-product proof.
- `__obedFade` rejects equal endpoints (`a===I`), and `forwards` with a model opacity different from `from` also fails. Therefore `obedParentOpacity` is null.
- R3 sees neither a proved constant `obedOpacity` nor a proved fade multiplier and keeps stock T=1. R4 is irrelevant because these leaves have animations.

This is a deliberate fail-closed coverage gap, not missing ancestor annotation. Widening every unknown subtree under an initial-zero wrapper would violate the existing admission contract and hide the legitimate matched objects described above. *Superseded by plan rev 2: a **proved** effective zero absorbs; raw initial-zero still does not (F2 slots 10/11 prove 1).*

R5 addresses a different first-frame DOM+GL double image. The duplicate source DOM is already under a zero wrapper; making its hide earlier cannot fix erroneous GL pixels. R6 cannot engage for either duplicate: its animation whitelist rejects `hidden`, and the leaf has no scaling (identity sx/sy is explicitly rejected). Thus it neither uploads a destination texture nor causes their appearance. R7 blending and R8 preloading are not the source of the bad opacity; R8 can affect how promptly the destination is ready. R9–R12 handle Dissolve/cut/freeze, outside this MM. The fade extension's R13 supplies duration but does not admit this constant-hidden pair. CSS cleanup removes the artifact; it does not create it.

## 5. Exact lifecycle window and remaining measurement

Define `D0` as the first actual MM canvas draw; `Dlast` as the final `fB.animate` draw with leaf progress clamped to 1; and `R` as `removeEvent` removing that canvas in destination `displayScene`.

| Interval | What this investigation establishes |
|---|---|
| Before D0 | Source DOM leaf chain opacity is 0. |
| Every draw D0…Dlast | Both leaves are submitted at Opacity 1 in stock and immutable old patched player. This is the defect's full GL draw window. |
| After Dlast, before R | No new ordinary player draw is scheduled. The canvas retains the erroneous terminal image; this is the owner's reported post-MM window. |
| At R | Old scene/canvas is removed; destination base has neither duplicate. |
| Destination pre-build and twist-and-scale | The source duplicate leaves are absent. Destination rendering precedes starting its first build. |

For the ordinary manual-show, automatic-next-event, already-preloaded path, the controller schedules:

1. MM animate task → `currentSceneDidComplete` after **1500+100 ms**.
2. Automatic next event → `s(advanceToNextBuild)` after **100 ms**.
3. `jumpToScene` → `s(jumpToScene_partThree)` after **100 ms**.
4. `partFour` → `displayScene` synchronously removes the old canvas, then calls `playCurrentScene` for the destination build.

Thus removal is nominally about **1800 ms after the MM animate task**, approximately **300 ms after nominal completion**, not an exactly 100 ms hold. The GL clock starts in its own queued task and finishes on rAF; overshoot, timer scheduling and destination loading change the actual interval. A 60 Hz illustration is roughly 18 frames, **not a measured or enforced frame count**. Header autoplay build/transition delays are 2/5 s, but those delays apply to automatic-show mode's separate branch, not ordinary manual playback merely containing an automatic build. The F2 header and event flags are retained in the evidence JSON.

An absolute first/last *painted frame number* cannot be established without running a browser, which this task forbids. The exact source-defined window is `[D0,R)` for erroneous GL content, with `[Dlast,R)` the held endpoint. The gate must measure these boundaries instead of sampling only “after 1.5 seconds” or after the automatic build has already begun.

## 6. Corpus census

Read-only scan of `output/fixtures`, including `alpha-dsk-textures`, all P2 copies, Minimal Alpha_DSK, Positive Control, and D1–D6. 596 JSON paths found; 388 browser-profile/extension JSONs excluded; 208 parsed, no parse errors; 26 export headers. Recursively find the three eB effect names and deduplicate with the same texture/object-id normalization as `tests/test_live_runtime.py`.

| Population | Result |
|---|---:|
| Effect occurrences before deduplication | 71 |
| Distinct Magic Moves | 26 |
| Distinct shimmer / sparkle transitions | 0 / 0 |
| Textured leaves across distinct effects | 122 |
| Any initial-opacity-zero ancestor | 0 |
| Opacity/hidden-only animated leaves | 51 |
| Those with proved ancestor product 1 | 48 |
| Those with proved ancestor product 0.6117682456970215 | 3 |
| Those with proved ancestor product 0 | 0 |
| Constant opacity 0→0 plus hidden true→true | 0 |

The three related Alpha_DSK leaves are 6→7 slot 3 (fingerprint `53b5f2b…`), 7→8 slots 4 and 8 (`4d87c01a…`): **0→1 fades under a translucent wrapper**, not this never-visible class. The existing fade repair must remain engaged and unchanged. A historical “30 distinct effects” in the fade plan scanned all of `output/` plus additional exports; it is not the denominator for this explicitly requested `output/fixtures` scan.

Adding the old F2 export supplies two exact affected leaves in one distinct effect. Raw/repaired copies are one effect, not four separate defects. The edited F2 effect has zero exact matches. Other F2 initial-zero wrappers are not candidates because their animated opacity is 1. This is a newly evidenced class absent from the current fixture corpus, not evidence that Alpha_DSK has the same ghost bug.

## 7. Minimal reproducer and headless measurement

The cheapest offline behavioral reproducer is a small real wrapper/leaf slice from old F2 plus the actual extracted `fB.textureInfoFromEffect` and `QB.renderFrameWithContext` methods, using the existing `tests/test_live_runtime.py` extraction/stub pattern. Check both players at start, 0.49995±epsilon, mid, end, and terminal clamp. Baseline stock and old patched must return Opacity 1, candidate 0. This demonstrates the arithmetic but cannot prove the visible hold or teardown.

For the blocking rendered reproduction, adapt **`scripts/mm_opacity_probe.py`'s `LOGGER_JS`**, not its P2-specific drive sequence/scorer. Its innermost draw logger already records per-program effective Opacity (including cached writes), reads before/after target draws, and can hash the terminal canvas. Start with old F2 slide 3 event 1 through slide 4 event 0, using the supplied immutable files in a scratch copy. Preserve automatic timing. Run plain HTML/preview and one live-host continuity-off, GL-replay-off pass; headless GL must be available (no `--disable-gpu` arm masquerading as GL evidence). Primary diagnostics must identify the two texture/geometry slots and record actual Opacity at every draw; ordinal alone is insufficient if topology changes.

A smaller renderable export can be derived later: a full-slide visible background, two wrappers/leaf groups copied exactly from F2 at disjoint ROIs, a visible matched moving object to show MM progress, destination without those two leaves, and an automatic destination build. Retain real exporter schema/assets or use solid-color textures via the existing export asset format. No Keynote automation is needed. Do not present a bare animation JSON as a complete runnable export.

Measurement requirements:

- Install instrumentation before any GL context/shader is created. Record context/canvas/program/texture identity, effective cached Opacity, MVP/quad and draw sequence at D0, every in-flight draw, Dlast, and subsequent removal.
- Read RGBA inside the draw task (default WebGL buffer preservation is not guaranteed after presentation). At each target draw compare ROI before/after; Opacity 0 must make no contribution. ROIs in GL bottom-up coordinates are `[568,520,44,50]` and `[652,515,88,59]` at 1920×1080.
- Observe canvas connectivity, actual scene index and event type, CSS animation start, and the physical removal timestamp. A slide-number label can already say “4” while the outgoing MM scene still paints. Do not mistake it for destination base state.
- Capture compositor/page frames covering the whole move and at least through the destination build onset; correlate with the GL trace. A DOM opacity census cannot see bad canvas content. During the hold, keep the terminal readback and measure the displayed page/canvas lifetime; do not expect fresh GL calls.
- Assert engagement, decoded nonempty textures, source effect fingerprint, both contexts/players as applicable, all time boundaries and adequate frame coverage. A missing first/terminal frame, a missing hold, missing uniform state or wrong fixture is INCONCLUSIVE and blocks qualification.
- Known-bad controls: immutable old patched player and stock, same old F2 data, must expose both contributions. Fixed-vs-fixed repeat is a noise/null control. A sibling with effective ancestor opacity 1 and a normal visible track must still paint, proving the patch does not indiscriminately blank objects. A second derived export with only these two leaf groups removed is the structural absence oracle; newexp3 is an additional real-data absence control, not the matched pixel oracle.

See `mm_opacity_unmatched_hidden.plan.md` for bounded admission, gates, ownership and owner decision recommendations. No headless, compositor or owner-eye gate is claimed complete by this investigation.
