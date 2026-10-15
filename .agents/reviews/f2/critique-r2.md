# F2 plan rev 3: critique r2 (Opus 5.5 high, independent plan critic)

**Verdict: CHANGES REQUIRED.** 0 blocker, 2 major, 5 medium, 3 low.

Governing input received mid-round (owner, in chat): the wall deck is 32:9, so the increment-1 deck is **hand-authored** at 16:9 1920×1080 No Fill and reproduces the selected effects and their settings. It is not pruned or converted. Rev 3 §3.1–§3.2 (subset, resizer, Generator, 18-slide discovery pool, successor-preserving pruning) are therefore superseded. The findings below review what replaces them.

Static only: I read text, sliced both `main.js` files by byte offset, and grepped `live_runtime.py`. I ran no browser, OBS, Keynote, osascript or pytest, and opened no `.key`.

## Verified (no change needed)

- **Players.** P is 2,369,488 B (`e9b2fad4`). P17 is 2,369,526 B (`17c0c938`). The byte ranges 2197336–2262229 (all `aB` subclasses through `fB`), 1984825–2030800 (shaders) and 2030871–2031900 (uploads) are identical in both.
- **Routes.** Each of the following is in both players:
  - `fB.draw` transition switch: Iris → `rB`, Twist → `hB`, Flop → `YB`.
  - Build switch @2264904: Iris → `DB`, Anvil → `cB`, Sparkle → `mB`.
  - `jC` holds 14 names. Revolve is absent from it.
- **Twist.** `hB` @2210480 has `mNumPoints=24`, 23 strips and `CULL_FACE`. It has no `blendFunc` of its own, so it inherits the base `aB` blend `SRC_ALPHA, ONE_MINUS_SRC_ALPHA` @2197825. Its shader adds specular after `rgb*diffuse` and leaves alpha unchanged (@1989786).
- **Flop.** `YB` @2217553 uses `flop` + `defaultTexture`, an 8×8 mesh, half-slide by direction, and no blend override. Diffuse is at most 1.0.
- **Iris and particle blends.** All of these set `ONE, ONE_MINUS_SRC_ALPHA`: `rB` @2204956, `DB` @2207240, `cB` @2225390, `mB` @2258571 and `HB` @2255270/@2256640.
- **Sparkle.** `HB` calls `sparkleSystem.drawFrame(A,1)`. The shader writes `v_Color=vec4(rgbColor,(1-p²)*Opacity)` (@2029367), so RGB is **not** reduced by the lifetime fade. The prediction holds.
- **Anvil.** Both particle shaders write `v_Color=vec4(thisOpacity)` (@1997523, @2000264). Fade is consistent with premultiplication.
- **Uploads and clear.** `createTexture` (FLIP_Y true) and `bindTextureWithImage` (FLIP_Y false) both premultiply (@2030871). `clearColor(0,0,0,0)` @2265918. `getContext` has no options. Neither Twist nor Flop enables `DEPTH_TEST`.
- **Revolve.** It is special-cased in the CSS code only, at @2294832 (`NB` origin-Z wrapper list) and @2305561 (skips `anchorPointZ`/`zPosition`).
- **Zero adjust-block occurrences.** I enumerated **every** occurrence of the six names in the whole file. All of them sit at the class constructors, the `fB` switches, `jC` and the two Revolve CSS sites. There are none at 1957878–1975600.
- **§7, R1–R8 (`live_runtime.py:219–258`, plus R13 @275):**
  - **R1/R2:** `setupTexture` passes `X=undefined`. The root leaf gets `obedOpacity=null`, and descendants are annotated through `__obedChainOpacity(undefined,A)=1×node`. That covers "all GL leaves".
  - **R3/R4:** they live inside `QB` @2188896 and `eB` @2191215, which selected classes never call.
  - **R5:** `animateEffectWillBegin` @2316844 is reached only from the `canvasId` (GL) branch, so the claim "every routed GL effect, not CSS Revolve" is exact.
  - **R6/R8:** gated on the MM name.
- **Superseded conversion facts are accurate:** `dsk_assemble.py:4206` (forced clip Dissolve), and `remap_keynote.py:1047` and `:1948` (`restore_source_builds(dest, source, set(), say)`).
- **r1 folds held.** Eye-first and conditional W1, transition-only opaque controls, smart/gallery excluded, adjust-time class kept as conditional, native-alpha limits and the default-continuity eye path are all retained.

## Findings

1. **major · design (owner update) · §3 must become an authoring sheet; rev 3's "original slides … no hand-authored artwork or forced timing" and the whole conversion path no longer apply.**
   **Evidence:**
   - Owner update.
   - `inc1_slide_map.md` gives effect, duration, `chunkAutomatic`, `chunkDelay`, `chunkOrder`, target kind and identity, and movies.
   - It omits `chunkReferent`. `iwa_builds.py:91,110` exposes it, and it is what distinguishes *with* from *after* previous. Without it, `auto=[True]` is ambiguous. Example: the three `delay 0` Iris builds on 101 run concurrently in one shared `fB` canvas if they are *with previous*, and as three events if *after*.
   - It also omits effect attributes. The player reads `effect.attributes.direction` for Twist (`hB` constructor), Flop (four values, default `M`), Iris (`rB`/`DB` branch on `direction===K`, which flips mix and progress) and Sparkle.

   **Fix: replace §3.1–§3.2 and the "Movies" paragraph with:**
   > "§3 Authored deck (owner-built, 16:9 1920×1080, No Fill on master and every slide). One sheet row per source slide, filled by the coordinator **offline from the wall `.key` IWA** (`deck_builds` plus each selected build/transition's `animationAttributes` and the chunk `referent`; no Keynote), then completed by the owner from the inspector only where IWA is silent. Columns:
   > (a) source slide → authored ordinal;
   > (b) transition: effect, duration, direction/options, start (on click / automatic + delay);
   > (c) per selected build: effect, In/Out, duration, direction, delivery (text), order, start (on click / with / after previous), delay, target kind and identity (text box / image file / group and its children);
   > (d) movies: file, count, start (movie-start build order or automatic), loop/repeat, and whether a movie is playing when the selected transition fires;
   > (e) the static artwork the effect composes against: the outgoing and incoming objects for transitions, and objects above or below each build target in z-order where they overlap it.
   >
   > Use the **source assets** (the same PDF, PNG and `.mov` files, and the same text), not stand-ins. PDF and PNG targets export differently (Dissolve plan §1). Builds outside the selected set are not authored. A transition source is authored at its fully built state."

   Movies per the map: **87 (1), 103 (5 PIN DROP WAVE), 104 (1)** in the mandatory set; **9, 51, 102 (1 each) and 101 (3)** among the Iris candidates. Slides 5, 6, 7, 34, 35, 86, 121, 122 and 124 have none.

2. **major · design · Missing predicted class: on Twist, every movie becomes the exported still frame for the whole transition, and the fix is not effect-local.**
   **Evidence:**
   - `fB.setupTexture` @2263021 builds every texture from `this.textureAssets[textureId]` through `R.createTexture`. There is no video path in `fB`/`hB`.
   - So 103's five movies, on the outgoing face, jump to the frame baked into the export at the moment Twist starts.
   - 87 and 104 (incoming) show their baked frame until the DOM swap and movie start.
   - This is the same mechanism as Dissolve plan §0's "movie jumps back to the opening frame baked into the outgoing texture". That fix is the D4 freeze (R11/R12 `__obedFreeze`/`__obedFreezeTake`). It is gated on `C.obedDissolve` and `__obedShape`, which require `apple:dissolve` or `none` (`live_runtime.py`, `__obedShape`), and it sits in continuity-adjacent paint-gate code.
   - Continuity also declines a carry into a non-MM/Dissolve/none transition (README, R11).

   **Fix, add a §1 row note and §4/§5 lines:**
   > "**Twist + movie (PREDICTED):** GL textures are static export images; movies on 103 (outgoing) jump to their baked frame for the 1.5 s Twist, and on 87/104 (incoming) appear as the baked frame until arrival. Eye step records this separately from alpha. If marked fail, the repair candidate is the Dissolve D4 freeze precedent, which is name-gated and continuity-adjacent: bring scope to the coordinator/Stage B owner before W1; no GL shader change addresses it."

   The authoring sheet must therefore record whether 103's movies are playing at the Twist click (finding 1d).

3. **medium · fact · The Iris transition texture roles follow from the code. Pass/fail must be judged against replacement intent, not "looks like native".**
   **Evidence, `rB.draw` @2204956:**
   - T1 is drawn every frame with `PercentForAlpha=0, Mix=0`, including the final frame.
   - T0 is masked. In both direction branches it starts invisible and ends full: the decreasing branch ends at r=0 with Mix=0, which gives gradient 1; the increasing branch ends at r²=1, where dist ≤ 1 with Mix=1. So **T0 is the incoming slide and T1 the outgoing one**.
   - Under No Fill, the outgoing art shows at 100 % through every transparent incoming pixel for the full 4.0 s. It vanishes only when the canvas is removed (a pop at the end).
   - Aside: T1's "full" draw relies on `smoothstep(0,0,d)`, which GLSL leaves undefined. Stock behaviour; note only.
   - Native No Fill playback may show the same union over black (unverified). In that case "matches native" would pass a defect. The Dissolve precedent took replacement semantics as the intent (Dissolve plan §0: "never both at full strength").

   **Fix, replace the Iris-transition prediction cell with:**
   > "T0 = incoming (masked, ends full), T1 = outgoing drawn full every frame (static, both directions): outgoing art persists through incoming transparent areas for 4.0 s and pops off at canvas removal — wherever 34's art is not covered by 35's opaque art."

   **Add to §4:**
   > "For transitions, pass = replacement intent (outgoing never visible where the iris has revealed the incoming), not merely parity with native No Fill playback."

   Apply the same criterion to Flop's static halves.

4. **medium · fact · Sparkle (and the edges of Twist) emit RGB greater than alpha. The visible symptom depends on the key path, and an existing check already measures it.**
   **Evidence:**
   - Sparkle: `rgb = tex.rgb·white` and `a = tex.a·(1−p²)` under ONE (@2029367, @2256640). As a particle ages, alpha goes to 0 while RGB stays.
   - Twist: `rgb' = a·(a·c·d + s)` with d ≤ 1.2 and `a' = a²` (@1989786 plus base blend). At antialiased edges, `s/a` exceeds 1.
   - These are invalid premultiplied pixels. An additive (premultiplied) key shows a glow, as on native over black. A straight-alpha key shows sparkles that dim or vanish early.
   - Twist also gives translucent art a² during the transition (50 % → 25 %), which snaps back at the end.
   - `html_alpha_probe.premultiply_halo` (`html_alpha_probe.py:559`) already measures `rgbMaxOnZeroAlpha`.

   **Fix, Sparkle cell:**
   > "Particle colour without matching alpha (rgb > a as life ends): additive glow or early-vanishing sparkles depending on how the key path treats premultiplied fill; native intent is additive."

   **Twist cell, append:**
   > "translucent art drops to a² for 1.5 s then snaps back; specular/diffuse > 1 gives rgb > a at edges."

   **§5:**
   > "For an rgb>alpha symptom, reuse `premultiply_halo` before any new check."

5. **medium · design · The Iris minimum can now be fixed: 122 collapsed, plus 101. Delete the 18-slide discovery pool and the nested-leaf variant list.**
   **Evidence:**
   - All 26 Iris builds target `kind=image`, so they are single leaves. "Nested vs single leaf, highlighted bullets" cannot occur.
   - Variants that exist:
     - **122:** 14 PDF images, 1.0 s, auto, order 0 at delay 0 then 0.01 s.
     - **96:** the same shape as 122 (5 images).
     - **101:** PNG targets, three delay-0 auto builds, 3 movies on the slide.
     - **9/51/102:** a single PDF image with a movie on the slide.
     - **57:** 1.75 s.
   - Duration only rescales progress (`DB.drawFrame` `t+=A/g`), with no branch.
   - 101 alone adds both PNG-vs-PDF and movie-on-slide coverage.
   - The 14-image chain exercises nothing that 3 images do not, once `referent` is preserved.

   **Fix, §3.1:**
   > "Iris build set = **122 authored with 3 of its PDF images** (order 0 automatic delay 0; two following with delay 0.01 and the source referent; keep one image overlapping a static or later sibling if the source has one) **+ 101** (3 PNG targets, original start/referent, its 3 movies). Add 57 only if the owner wants the 1.75 s timing seen; add any of 9/51/96/102 only if the sheet shows an Iris **direction** not present in 122/101. Deck = 13 slides in source order: 5, 6, 7, 34, 35, 86, 87, 101, 103, 104, 121, 122, 124."

   Also, in the hand-authored deck, drop the later-queue builds:
   - 103: 50 bc-zoom-big character + 5 dropbuild;
   - 122: 138 bc-drop + 12 twist-and-scale;
   - 124: 5 + 1 + 1;
   - 101: 9 + 3.

   On 124, keep both Sparkle groups at their original relative order and timing.

6. **medium · design · The transitions out of the successor slides must be specified, or the authored deck creates spurious Magic Moves.**
   **Evidence:**
   - The source exits of 7 and 35 are `apple:magic-move-implied-motion-path` into slides 8 and 36, which are absent here.
   - Copied literally, 7→34 and 35→86 become MM between unrelated slides. That runs the MM GL path (R6/R8 hand-back and preload) on mismatched partners, which is noise for the eye record (memory: "MM partners lesson").
   - The exits of 87, 101, 104 and 124 (Dissolve 0.5) and of 122 (`none`) are already handled by #262.

   **Fix, sheet rule:**
   > "Exit transitions of 7 and 35 = Dissolve 0.5 s (not source; labelled incidental). Keep the source exit of 5, 87, 101, 104, 122 and 124 (Dissolve/none), labelled incidental, outside F2 pass/fail."

7. **medium · feasibility · The authored deck needs a cheap offline check against the sheet before export. Step 0 should compare against the sheet, not the "source mapping".**
   **Evidence:**
   - `deck_builds` reads IWA without launching Keynote (`iwa_builds.py:83`). It was already used for W(−1) and for the inc1 map.
   - Hand authoring produces slips: wrong direction, *with* instead of *after*, wrong duration, a missing movie.
   - Rev 3 Step 0 compares "selected source occurrences with conversion and export occurrences", and that conversion stage no longer exists.

   **Fix, §4 Step 0 lead:**
   > "Step 0a (offline, coordinator, quiet machine): run `deck_builds` + attribute readout on `GW-inc1-DSK.key` and diff against the sheet (effect, type, duration, direction, start/referent/delay, kind/identity, movie count). Owner corrects slips before export. Step 0b: export census as now, compared with the sheet."

   Remove "ambiguous source mapping" and the conversion-loss labels. Keep "export loss".

8. **low · coordination · §7 lists R1–R8 only.**
   **Evidence:**
   - R9–R12 (Dissolve and freeze) and the Line Draw hooks (`__obedLineDrawAdmit`, `__obedLineDrawComplete`, `__obedLineDrawNode`) run on every effect.
   - They are name- or shape-gated and are no-ops on the six selected names. I checked `__obedShape`, `obedDissolve` and the LineDraw name list.
   - The authored deck's incidental Dissolve exits from 87 and 104, which carry movies, do exercise the Dissolve D4 freeze.

   **Fix, append to §7:**
   > "R9–R12 and the Line Draw hooks are name/shape-gated no-ops on the selected names; incidental Dissolve/none exits (87/104 with movies) exercise #262's freeze and are outside F2 status."

9. **low · proportion · The `runpy` and `main.__globals__` recipe in §4 is implementation detail for a later step.**
   **Fix:**
   > "Coordinator adapts `census_f2.py` to take an export path (or equivalent) when Step 0b runs; no broad fixture rescan."

10. **low · proportion · §3.2 is superseded but long.**
    **Fix:** delete §3.2's three conversion paragraphs and the `restore_source_builds` paragraph, and keep one line:
    > "Conversion (resizer/Generator) superseded by owner's authored-deck decision (32:9 source); Generator forces clip Dissolve (`dsk_assemble.py:4206`) — not used."

    Keep the `F2-inc1/` paths and the owner-run, owner-go-only rule. Update OQ F2-9 to:
    > "Answered: authored deck per sheet; Iris = 122(3) + 101; movies per inc1 map."

    In the §4 eye step, change "converted real-slide deck" to "authored deck".
