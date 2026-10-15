# F2 plan rev 1: critique r1 (Opus 5.5 high, independent plan critic)

**Verdict: CHANGES REQUIRED.** 0 blocker, 5 major, 4 medium, 4 low.

The census facts hold up. Every anchor I spot-checked matched, in both players, and I recounted the effects independently. The plan's weak point is scope. It authors 40 slides and builds 8 new probe profiles before anyone has looked at stock output, and no usage evidence has been checked. The owner's own DSK deck contains none of the F2 effects. Several Q-deck rows also cannot change the design by the plan's own §0 and census §5.

**Verified (no change needed):**
- Both player files: P is 2,369,488 B `e9b2fad4`; P17 is 2,369,526 B `17c0c938`.
- `jC=[` is count 1 at P @2368216 and P17 @2368254. It has 14 names, in the order the census gives.
- `vC={` is count 1 at P @2367654 and P17 @2367692. It has 10 entries, and their property lists are exact.
- Both `qC&&-1!==jC.indexOf(…)` tokens are count 1, at @2312807 and @2314108.
- `renderEffects` is @2311803 and `renderEffect` is @2313757.
- The ordinary `contents` from/to keyframes are 49.999 %/50 % steps (@2282473).
- `initRendererFlags` has the Chrome Push/FadeThruColor exception (@2292945).
- `adjustEffects` handles Blinds, Grid and Swoosh (@1957878).
- The Chrome `KLNSwap` case uses 0.4T/0.4T (@1962856).
- `GB.draw` draws the second texture at opacity 1, then the first at eased α with `ONE, ONE_MINUS_SRC_ALPHA` (@2202984).
- The `smartBuild` `contents` branch creates a nested `fB` (@2306846). The `smartBuild` switch is @2265418, with `apple:gallery-dissolve` → `IB`.
- The `apple:`/`com.apple.` literal inventory has 48 names, matching Appendix A.
- My own walker over `output/fixtures/**/assets/*/*.json` gives:
  - all 26 roots: 45 / 11 / 71 transitions and 407 buildIn;
  - without `alpha-dsk-textures`: 42 / 8 / 67 / 382;
  - types present: only `transition` and `buildIn`.
- The `dissolve_probe.py` line references and arm names exist: 276, 396, 894, 902, 1312, 1395, 1545, 1615, 2912, 3191, `m-paused`, `opaque-on` and the others cited.

---

1. **major · scope · No usage evidence; the owner's real DSK deck uses zero F2 effects.**
   **Evidence:**
   - `census_f2_rows.tsv` deck `Alpha_DSK` (`fixtures/alpha-dsk-textures`) contains only:
     - transitions: `apple:dissolve`, `none`, Magic Move;
     - builds: `apple:dissolve`, LineDraw ×2, plus movie service records.
   - Every other fixture deck is a qualification deck (D1–D7s, Minimal, Positive Control).
   - §2 admits its criteria are "not a measured usage survey".
   - An offline reader that does not open Keynote already exists: `src/obed_edom/iwa_builds.py:83` `deck_builds()` returns each slide's builds (`effect`, `animationType`) and transition. Its docstring says it was measured on 593 source and 1515 output builds.
   - I tried to run it read-only on `~/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key`, and the session's permission guard denied it while the live passes run. It is therefore **not yet run**.

   **Fix, add §1 fact 6:**
   > "Usage: the only real DSK export on disk (Alpha_DSK) contains no F2 effect. Before any authoring, W(−1) runs `iwa_builds.deck_builds` read-only over the owner's source decks in `~/Desktop/Convert wall to 16x9 CGs/*.key` (wall + CG + DSK), at a quiet machine time, and tabulates every transition/build effect. F2's case list = effects found there ∪ effects the owner names in OQ-F2-0."

   **Add OQ-F2-0:**
   > "Which transitions/builds do you actually use or intend to use on DSK decks? Recommendation: answer from the W(−1) table; if none beyond Dissolve/none/Magic Move/Dissolve-build/Line Draw, park F2 with a README limit line and no Q-deck."

2. **major · scope · The 40-slide Q-deck is disproportionate; replace it with an eye-first minimal deck.**
   **Evidence:**
   - §3.3 has six slides per transition family (still, movie, opaque × destination) and two slides per action. Slides 25–35 are 11 action slides.
   - Line Draw, the precedent the plan cites, was found by the owner's eye on a real deck and fixed with one admission (Line Draw plan §1).
   - Owner rules: keep it simple, and instrument scope means catching what the owner's eyes can catch.

   **Fix: replace §3.3 with:**
   > "**Q-deck v1, at most 8 slides (+2 only if OQ-F2-0 names Fade Through Color), No Fill, 1.0 s, manual:**
   > 1 A+M → **Push** R→L → 2 B.
   > 3 A+M → **Wipe** R→L → 4 B.
   > [5 A+M → **Fade Through Color** black → 6 B, only if used.]
   > 5 S+M witness: click 1 **Move In** from left, click 2 **Move Out** to right.
   > 6 S+M witness, still panel visible at arrival: click 1 **Dissolve Out**. Dissolve *In* is already on disk ×49; build-out is the unseen case.
   > 7 still target: **Move action** with one curved path segment.
   > 8 M target, after ≥ 2 s playing: same Move action.
   > Add any effect from W(−1)/OQ-F2-0 as one slide (with M if movies occur there in real use).
   > **Eye step first:** the owner plays the pristine export through the product path (Alpha Keynote, default continuity, HDMI Chrome and the Keyer) beside native Keynote, and marks each slide pass / fail / unavailable.
   > Only a failing family gets a stills/no-movie split, an opaque twin and instrumentation (finding 3). Expansion is per failing family, never pre-emptive."

   The A-only and A+M split is unnecessary at v1. The A+M slide already carries the outgoing-only, incoming-only, overlap, translucent and movie ROIs. Split it only when a failure needs attributing.

3. **major · scope · An 8-profile `f2_probe.py` is premature, and parts are tighter than eyes can see.**
   **Evidence:**
   - §4.2's eight new profiles, `f2-refuse`'s mutation matrix and `f2-life`'s twice-run/cancel/destroy are all specified before any stock pixel exists.
   - §4.3 has "≤1 authored px at independently captured poses".
   - Memory `feedback-instrument-scope.md`, owner 2026-10-12: "just fix what my eyes can catch".
   - §4.2 itself says "do not assume every stock case fails".

   **Fix: replace §4.2's lead and table with:**
   > "W1 is **conditional**: it starts only for a family the owner marks *fail* in the eye step, and builds only the checks that failure needs. If the failure is a two-texture replacement fade, reuse `dissolve_probe.py` arms and `score_fade` with a manifest target (no new profile). If it is a spatial pop-in or union frame, add one profile, `f2-reveal`, that measures early incoming visibility and union area at ≥ 6 poses against the opaque twin, with positive control = the opaque twin and negative = stock fill-less (once shown wrong). Lifecycle, refusal matrices and pose bounds tighter than a visible symptom are brought to the owner with their gate cost rather than built by default. Families that pass the eye step are recorded as 'stock, eye-qualified' with the native reference, and get no instrument."

   Delete the ≤1 px bound unless a measured visible defect needs it.

4. **major · design · Opaque controls on single-object builds and actions cannot decide anything.**
   **Evidence:**
   - Census §5 says: "A single object opacity over a static backdrop has normal source-over semantics and does **not** need an incoming mirror". Its rows for actions and generic builds predict **none** from fill-less.
   - Page fill changes only what shows *behind* the object. Fill-less matters where two slide textures coexist, which means transitions.
   - Yet §3.3 slides 21, 24, 35 and 40 are opaque controls for builds, actions and smart builds.

   **Fix, in §3.2 "O controls":**
   > "Opaque controls exist only for **transitions**, and only once a transition fails the eye step. Author them as a duplicate `.key` with a black page background (same slides, no extra authoring), exported to `F2-Q-opaque-html/`. Build/action cases have no opaque control: their defects, if any, are fill-independent and appear identically on an opaque page."

5. **major · scope · Smart builds (slides 36–40) are out of scope by construction, and are likely not authorable.**
   **Evidence:**
   - The only explicit `smartBuild` name, `apple:gallery-dissolve`, goes to `IB` in the nested `fB` WebGL renderer (@2265418, @2306846). Any other smart name falls to `GB`, which is also GL (@2265418 `default:B=new GB`).
   - §0 excludes "smart-build contents that enter a nested GL renderer".
   - OQ-F2-3 already recommends "stop at diagnosis".
   - The §2 row "fix only CSS portions if separable" contradicts §0: the separable CSS part is generic single-object motion, which finding 4 shows needs no fill-less fix.
   - **Unverified (no web):** I believe current Keynote no longer offers the legacy Smart Builds (Dissolve/Flip/Grid/Spin/Swap/Thumb Through), and that image galleries replaced them. If so, slides 36–40 would come back "unavailable".

   **Fix:** delete slides 36–40 and the §2 "Smart image replacement" row. Move smart builds and galleries into the "out of scope unless the owner adds them" row with this text:
   > "Smart/gallery contents render in nested WebGL (`IB`/`GB`), which is GL scope. Not authored in F2."

   Keep OQ-F2-3 only as the record of that decision.

6. **medium · design · Missing predicted failure class: name-keyed browser adjustments can throw or corrupt the tree for non-transition effects.**
   **Evidence:**
   - `adjustScript` (call @1957308 to @1957703) runs `adjustEffects`, `adjustEmphasisBuilds` and `adjustEffectsFor<UA>` on **every** effect of every event and hyperlink event, with no type filter.
   - The Chrome cases `apple:fall`, `apple:scale` and `KLNSwap` (@1962856–1966272) have no type check. They dereference a transition-shaped tree: `B.baseLayer.layers[0].layers[1].animations[0]…`.
   - `apple:scale` swaps `layers[0]`/`[1]` and sets the moved layer `initialState.hidden=!0`. On the `N[N[T]]` single-leaf build shape seen in the census, that leaves `layers[0]=undefined` and hides the animated leaf.
   - Whether Keynote's Scale (or any other) *build* exports under these names is **unverified**.

   **Fix:** add a fifth class to census §5 and plan §5:
   > "**Adjust-time exception / tree corruption (PREDICTED):** a non-transition exported under `apple:scale`, `apple:fall` or `…KLNSwap` meets Chrome-only code that assumes a two-child transition container; expect a thrown `adjustScript` (deck fails to start or advance) or a hidden/missing object. Not alpha-related; it shows on opaque pages too."

   In §3.4, make the first eye check: "the deck starts and every click advances in Chrome". If the owner uses a Scale build, add one Scale build-in slide.

7. **medium · design · The routing facts for action builds are missing, and they justify collapsing slides 25–35.**
   **Evidence:**
   - `renderEffects` (@2311803 slice) sets the chain flag `Q` when an earlier effect on the same object is an `actionBuild` **or `renderMovie`/`renderWebVideo`**.
   - So an action on a movie target always takes `renderEffect`'s "mutate existing layer" branch (`g` truthy, `B.currentKPFLayer`). A first action on a still target replaces the node instead.
   - The `apple:action-scale` contents splice is skipped for movies (`!l`, @2314516 vicinity).
   - `processEffects` (@2311135) merges same-object actions only **within one event**. It sets the merged `duration` to an end time (`B[g].duration=o.beginTime+o.duration`), a stock quirk for "with previous" chains that start after 0.
   - Census §2.3 already says Move and custom Path probably both export as `apple:action-motion-path`.

   **Fix, add a census §2.3 bullet:**
   > "Two action routes: still target, first action → node replacement; movie target, or later action on the same object → in-place mutation of the existing layer (vC property filter). Same-event actions merge (stock duration quirk noted)."

   In the plan, replace slides 25–35 with v1 slides 7–8 (one curved Move on a still and on M). Add Scale, Rotate or Opacity actions only if W(−1) or OQ-F2-0 shows they are used. Slide 35's five-action chain "relative to its then-current pose" is dropped.

8. **medium · design · The native reference cannot show alpha, and the eye step must use the product path.**
   **Evidence:**
   - §3.4 and §4.3 assume "native reference recordings". A screen recording of native Keynote shows the No Fill page over a display colour. It reveals gross pop-in or union frames, but not translucent-alpha errors as keyed on air.
   - §4.3 orders a "core continuity off" diagnosis first. That suits an instrument, but the owner judges what goes to air.
   - README:150–170: continuity already declines a carry into any outgoing transition other than Magic Move, Dissolve or none (`R11`), and refuses build-in/out of a continuing instance (`R2`).

   **Fix, in §3.4:**
   > "Native reference: a screen recording of native playback (always), plus, for a family that fails, Keynote's QuickTime export in ProRes 4444 with a transparent background, as the native alpha oracle (the repo already uses ProRes 4444 export, `dsk_movie_export.py:85`). Whether No Fill survives that export as alpha is **unverified**, so check it on slide 1 first. The owner's eye step runs the product path with default continuity. The expected movie outcome on Push/Wipe is continuity's existing `R11` decline (the movie restarts as the export plays it), not a new F2 behaviour. Continuity-off runs belong to W1 diagnosis only."

9. **medium · wording/design · The owner questions need reordering, and two recommendations are wrong.**
   - **OQ-F2-1** recommends accepting all 40 slides. Reverse it:
     > "Recommendation: author v1 (finding 2) limited to effects found in W(−1)/OQ-F2-0; append only for a real deck need."
   - **OQ-F2-2:** on fill/key, a black veil is opaque black keyed over program, which is almost certainly unwanted for lower-thirds. Ask before authoring:
     > "Do you use Fade Through Color on DSK? Recommendation: no → not authored, README notes it keys a black frame."
   - **OQ-F2-6** (release ordering against placement/Stage B) is premature, because no implementation is planned until a failure. Fold it into §7 as one line.
   - **Add:**
     > "OQ-F2-7: for a failing effect you do not use, fix or document? Recommendation: document in README as 'plays as the stock export' and do not patch."

10. **low · fact/wording · Imprecise anchors in plan §1.2 and census §3.**
    - Plan §1.2 says "`apple:gallery-dissolve` dispatches to `IB` at @2265454". 2265454 is the case-label name offset, which excludes the quote; the quoted literal is at 2265453 and `IB` itself is at @2197873. Reword:
      > "the `smartBuild` switch (@2265418) maps `apple:gallery-dissolve` (@2265454) to `IB` (@2197873)."
    - Add to census §3: the `smartBuild` `contents` branch (@2306846) constructs `fB` **without a `qC` check**, unlike both `jC` routes, so it is attempted even when startup WebGL failed. The outcome is unverified.

11. **low · wording · The plan's counts are physical copies.**
    - The census states this, but plan §1.3 does not.
    - The 26 fixture roots are about 9 distinct decks: Alpha_DSK, D1–D6, Minimal Alpha_DSK, Minimal Alpha_DSK_Loop and Positive Control. p2-* are copies of Minimal Alpha_DSK.

    **Fix, append to fact 3:**
    > "(physical export occurrences across copied roots; about nine distinct source decks, see census §4)."

12. **low · feasibility · Authoring-sheet details, all unverified because no Keynote was opened.**
    These are from my knowledge of current Keynote:
    - Push and Wipe offer direction options, and Fade Through Color offers a colour. Transitions generally expose no easing control; the plan already records "not exposed".
    - Move In and Move Out builds expose direction. Action Move exposes acceleration.
    - The Move action *is* the custom path: you drag its line into a curve, and there are no numeric handles. AM and AP are one action, which supports finding 7.
    - Builds cannot be scripted (`iwa_builds.py:3–4`: the sdef has no build class), so hand authoring is right. With 8 slides it is cheap.

    **Fix, in §3.2:**
    > "AM and AP are one Keynote action (Move); author one curved Move."

13. **low · wording · The foreground on the A+M slide is ambiguous.**
    - §3.2: A already has a 50 % magenta rectangle at (760,680). A+M adds a second one at (760,420,240,120) over M.
    - **Fix:** "A+M keeps A's magenta at (760,680) and adds a second 50 % foreground over M at (760,420,240,120)."
