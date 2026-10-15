# Rev 5 — folds Opus 5.5 high critique r3 (final round)

**FINAL for owner review — 2026-10-14.**

Static planning only: no browser/OBS/Keynote/osascript/pytest/git or `.key` access. Only this plan overwritten. Evidence: [critique r3](../reviews/f2/critique-r3.md), [critique r2](../reviews/f2/critique-r2.md), [authoring pre-fill](../reviews/f2/inc1_authoring_data.md), [slide map](../reviews/f2/inc1_slide_map.md), [usage](../reviews/f2/wall_usage_census.md), [both-player anchors](../reviews/f2/rev3_gl_anchors.md), [census §6](../reviews/f2/f2-census.md#6-rev-3-addendum--usage-selected-gl-and-conversion). No live qualification claimed.

## 0. Decisions and boundaries

D1–D4 stand: usage-led increments, eye first, instruments only after owner-marked failure; selected GL effects are in scope. Owner's 32:9-source update governs §3. Other GL names, smart/gallery, Q6, placement/scaled stages and continuity policy stay outside F2. Stage B owns continuity/MM feed; movie freeze coordination is §5.

Repairs: exact admission, SHA-pinned/count-checked in-memory `patch_player`, `patch_rendering` parity, both-player pins and `mm_opacity=off` stock behavior. Never edit exported `main.js`.

## 1. Increment 1: PREDICTED failures, not measurements

Both players share these inspected GL bytes. Uploads premultiply; clear is transparent; blanket opaque-clear diagnosis is unsupported. [Census §6.1–6.5; critique verification]

| Effect / source | Route | Prediction |
|---|---|---|
| BUKTwist / 86, 103 | GL `hB`, `twist`; base SRC_ALPHA blend | Double-alpha weighting; translucent art drops to a² for 1.5 s then snaps back; diffuse up to 1.2 plus specular gives rgb > a on translucent lit pixels, most visibly at antialiased edges. |
| BUKFlop / 6 | GL `YB`, `flop/defaultTexture` | Double-alpha weighting; static halves can remain visible through transparent replacing art. |
| Iris transition / 34 | GL `rB`, `iris` | T0 = incoming (masked, ends full), T1 = outgoing drawn full every frame (static, both directions): outgoing art persists through incoming transparent areas for 4.0 s and pops off at canvas removal — wherever 34's art is not covered by 35's opaque art. |
| Revolve / 121 | CSS `VB/NB/WB` | Possible plane/origin/stacking seam; no demonstrated defect. |
| Sparkle In / 5, 124 | GL `mB/HB/dA` | Particle colour without matching alpha (rgb > a as life ends): additive glow or early-vanishing sparkles depending on how the key path treats premultiplied fill; native intent is additive. |
| Anvil In / 7 | GL `cB` | Smoke/speck premultiplication sound; particle opacity/foreground stacking may differ. |
| Iris In / 122, 101 | GL `DB` | Single-image reveal sound; opacity/stacking mismatch possible. All 26 source targets are image leaves. |

**Twist + movie (PREDICTED):** GL textures are static export images; movies on 103 (outgoing) jump to their baked frame for the 1.5 s Twist, and on 87/104 (incoming) appear as the baked frame until arrival. Eye step records this separately from alpha. If marked fail, the repair candidate is the Dissolve D4 freeze precedent, which is name-gated and continuity-adjacent: bring scope to the coordinator/Stage B owner before W1; no GL shader change addresses it.

Selected names occur zero times in the adjust-time exception block; retained-name degradation or malformed export trees remain conditional checks. Revolve's two exceptions are CSS origin-Z handling. Iris's full T1 draw uses stock `smoothstep(0,0,d)` (undefined by GLSL); note only.

## 2. Later usage queue

D4 order: bc-zoom-big character (20 slides), dropbuild (19), bc-zoom-big (10), zoom (4), twist-and-scale, revolve, keyboard, move in/out, bc-flip, action-pop/pulse/blink, fade and move, zoom character, dissolve character. bc-drop's 138 builds occupy one slide. No later-queue builds authored here; no synthetic Push/Wipe/Move/Fade-Through-Color cases.

### Coordinator pre-authoring step (before handing §3 to the owner)

The [pre-fill](../reviews/f2/inc1_authoring_data.md) supplies effects, durations, source build order and movie settings. Before authoring, the coordinator will read the wall IWA offline and add an artwork appendix **inside §3**, using recognizable object descriptions and inspector labels. **Done 2026-10-14:** [artwork appendix](../reviews/f2/inc1_artwork_appendix.md) (script `inc1_artwork.py`, offline IWA read, no Keynote). It is a separate file because slides 103 and 124 keep 73 and 360 objects. Do not ask the owner to transcribe object IDs or infer missing artwork metadata.

For **every object retained on each slide below**, read these exact fields: drawable identity, object kind, source asset identity/file or exact text, group identity and ordered child identities where applicable, object and enclosing-group opacity, crop/mask presence and definition (including crop transform), front-to-back z-order and overlapping object identities, source geometry/transform for identifying the object, and retained-built/static status. Translate identity into a recognizable description, mask/crop and opacity into owner-readable values, and overlap order into “in front of / behind” instructions in §3; keep archive IDs in the coordinator record. Source geometry identifies overlaps, not fixed 16:9 coordinates. For movies also read Repeat, Play across slides and Trim, including build-less movies. These fields apply separately to every repeated-file object, not just once per filename.

| Wall slide | Objects to cover with all fields above; specific relationship to add to §3 |
|---|---|
| 5 | Each of the three named text boxes and all never-built art; overlapping foreground/background objects and any text grouping. |
| 6 | Every fully built/static object; coverage of each Flop half and gaps against 7's arrival art. |
| 7 | `Report Card.png` and all never-built art; objects in front of/behind the image and particle region. |
| 34 | Every fully built/static object; outgoing art exposed through 35's transparent areas. |
| 35 | Every never-built arrival object; opaque/transparent coverage against 34. |
| 86 | Every fully built/static object; translucent artwork and overlap with 87's movie footprint. |
| 87 | The single MP4 and all never-built art; movie crop/mask, opacity and foreground order. |
| 101 | Three separate `Untitled.001.png` objects, three separate movies and all never-built art; per-object identity and overlap order among the concurrent reveals, movies and static art. Exclude objects belonging only to dropped builds. |
| 103 | Five separate movies, all 55 dropped-build targets retained as built/static art, and never-built art; movie identity, crop/mask, opacity and overlap order within the full composition. |
| 104 | The single MOV and all never-built art; movie crop/mask, opacity and foreground order. |
| 121 | Every fully built/static object, including the build-less `PIN DROP WAVE.mov`; movie identity/settings and revolving-plane composition against 122's never-built art. |
| 122 | The three distinct PDFs at source builds 0–2 and all never-built art; recognizable PDF identities and every never-built object they overlap. Exclude the other 11 Iris targets and targets of the 150 later builds. |
| 124 | Both selected groups, their ordered children and all never-built art; exact child text/assets, group/child opacity and overlap order. Exclude targets belonging only to the seven dropped builds. |
| 57 (optional) | The PDF at source build 1 and all never-built art; recognizable PDF identity and overlaps. Exclude targets belonging only to dropped builds. |

Owner reproduces each wall slide by eye (same objects, same overlaps, same opacity). Coordinator compares opacity, masks, z-order and object identity offline in Step 0a. The owner records only what IWA lacks: text Delivery on 5/124 if not 'All at once'. This applies to the retained composition after §3's object omissions. The separate observation of movies playing at 103's Twist click is recorded during eye review.

## 3. Owner authoring sheet — one sitting in Keynote

Create a **16:9, 1920×1080** deck with **No Fill on the master and every slide**. Make 13 slides in this wall-slide order: **5, 6, 7, 34, 35, 86, 87, 101, 103, 104, 121, 122, 124**. The wall canvas is 7680×1080 points; its content is the centre 32:9 band (x 1920–5760, 3840×1080). **Owner layout (2026-10-14): scale the centre band down to 16:9 and crop the side-panel content**, preserving the retained objects' overlaps and opacity. Use this sheet together with the [artwork appendix](../reviews/f2/inc1_artwork_appendix.md): per slide, which objects to keep or leave out, front-to-back order, opacity ≠ 1, masks, and what overlaps each selected target and movie. The map BG images span the full 7680 width, masked; crop them with the side panels.

Use the **source assets** (the same PDF, PNG, MP4 and MOV files, and the same text), not stand-ins. Do not rasterize PDFs. Repeated filenames identify separate objects: copy each listed object separately and preserve groups and children.

**RECOMMENDED optional import technique:** Copying objects from the wall slide and pasting them into the authored slide keeps the original file, PDF vector, crop/mask, opacity and movie trim; copying files out of the package is the fallback; Step 0a checks either way. Then resize/re-layout at 16:9. Check the copied build list against the table below and remove unselected builds.

A transition source is authored at its fully built state.

Objects whose builds are dropped: on a **transition source** (6, 34, 86, 103, 121) keep them as plain static objects in their built state; on a **build slide** (5, 7, 101, 122, 124, 57) leave them out. Objects with no builds on the wall slide are always kept.

Keep the selected build targets and movie starts listed below. Keep all never-built art on 35, 87 and 104 as well. Reproduce the retained composition by eye: same objects, same overlaps, same opacity. The coordinator checks the artwork; the owner records text **Delivery** on 5/124 only if it is not **All at once**.

**How to read the sheet.** Build numbers are Keynote's Build Order numbers (1, 2, 3…) in the authored slide; the source build number follows in brackets for the coordinator's check only. Start = the Build Order 'Start' menu: On Click, After Transition, After Build N or With Build N; Delay = the Build Order 'Delay' field (seconds). Every build is a Build In with Direction left as on the wall slide (finding 4). 'Start Movie' = Keynote's Start Movie build (no duration to set). Movie settings are in Format › Movie: Repeat None for every movie; 'Play across slides' as listed; Trim start 0, end as listed (usually the whole file — check). Transitions: Start Transition On Click for every slide, selected and incidental; duration as listed.

Direction and other effect options (Twist amount, Revolve options): set them to what the **wall slide's** inspector shows for that effect. Copy the wall inspector's **Direction** for builds and transitions and its **Twist amount** for both Twist transitions; do not assume a new effect's default matches. Set text Delivery to All at once unless the wall inspector shows otherwise; record that exception.

Dropping builds re-anchors the kept ones: a kept build whose source predecessor was dropped starts **After Transition** (keeping its delay) if it is now build 1, otherwise **With/After Build N** of its new predecessor exactly as the source With/After. Source spacing that depended on dropped builds is not reproduced; this is intended. Step 0a checks the flags below.

The table gives the complete Start/Delay settings after those removals. **Every kept build that becomes Build 1 starts After Transition**, except an explicitly retained On Click start such as slide 5. In particular, slide 124's original spacing **cannot be reproduced**: its removed builds supplied that spacing. Use the two starts below. If the Delay field will not hold 0.01 or 0.02 s, enter the nearest value it accepts; Step 0a records it. Read bracketed numbers only as coordinator cross-checks, never as numbers to enter in Build Order.

| Wall slide → new slide | Objects / Build In duration | Build Order: effect, Start, Delay (seconds) |
|---|---|---|
| 5 → 1 | Three named text boxes; Sparkle 1.25 s each | 1 [0] Sparkle “He stood between” On Click, 0 · 2 [1] Sparkle “the living and the dead” After Build 1, 0 · 3 [2] Sparkle “the plague stopped” On Click, 0 |
| 6 → 2 | Fully built wall art | No builds |
| 7 → 3 | `Report Card.png`; Anvil 2.0 s | 1 [0] Anvil `Report Card.png` After Transition, 0 |
| 34 → 4 | Fully built wall art | No builds |
| 35 → 5 | Wall arrival art | No builds |
| 86 → 6 | Fully built wall art | No builds |
| 87 → 7 | `shutterstock_3637941261.mp4` | 1 [0] Start Movie, After Transition, 0 |
| 101 → 8 | Three separate `Untitled.001.png` objects; Iris 1.0 s each; three separate movies | 1 [0] Iris After Transition, 0 · 2 [1] Iris With Build 1, 0 · 3 [2] Iris With Build 2, 0 · 4 [5] Start Movie With Build 3, 0.01 · 5 [8] Start Movie With Build 4, 0.01 · 6 [11] Start Movie With Build 5, 0.01 |
| 103 → 9 | Fully built wall art plus five separate movies | 1 [47] Start Movie After Transition, 0.02 · 2 [50] Start Movie With Build 1, 0.02 · 3 [53] Start Movie With Build 2, 0.02 · 4 [56] Start Movie With Build 3, 0.02 · 5 [59] Start Movie With Build 4, 0.02 |
| 104 → 10 | `shutterstock_17707843.mov` | 1 [0] Start Movie, After Transition, 0 |
| 121 → 11 | Fully built wall art plus `PIN DROP WAVE.mov` | No builds; delete a Start Movie build if Keynote adds one on insert |
| 122 → 12 | Three distinct `pasted-image.pdf` objects; Iris 1.0 s each | 1 [0] Iris After Transition, 0 · 2 [1] Iris With Build 1, 0.01 · 3 [2] Iris With Build 2, 0.01 |
| 124 → 13 | Original groups and children: “183 / CHC Churches”; “Total Churches / 269” | 1 [1] Sparkle “183 / CHC Churches” 1.3 s After Transition, 0 · 2 [6] Sparkle “Total Churches / 269” 1.4 s After Build 1, 0 |
| 57 (optional) | `pasted-image.pdf`; insert between 35 and 86, shifting later slide numbers by one | 1 [1] Iris 1.75 s After Transition, 0 |

Set each slide's exit transition and movie settings as follows. “Incidental” identifies a connecting transition outside this effect review; author it exactly as listed. All transition starts are **On Click**.

| Wall slide | Transition to next wall slide | Format › Movie | Composition to preserve / observation |
|---|---|---|---|
| 5 | Dissolve 0.5 s → 6 (incidental) | None | Text against the never-built art above/below it. |
| 6 | Flop 1.0 s → 7; Direction as on wall | None | Half-slide coverage and transparent gaps between 6 and 7. |
| 7 | Dissolve 0.5 s → 34 (incidental) | None | Report Card and particle area against foreground art. |
| 34 | Iris 4.0 s → 35; Direction as on wall | None | Art on 34 exposed through transparent areas on 35. |
| 35 | Dissolve 0.5 s → 86 (incidental; → 57 if included) | None | Incoming opaque coverage against 34. |
| 86 | Twist 1.5 s → 87; Direction and Twist amount as on wall | None | Translucent edges and incoming movie footprint. |
| 87 | Dissolve 0.5 s → 101 (incidental) | 1× `shutterstock_3637941261.mp4`; Play across slides on; Trim 0–8.76 s | Arrival still frame against the live movie. |
| 101 | Dissolve 0.5 s → 103 (incidental) | 3× `PIN DROP WAVE.mov`; Play across slides off; Trim 0–2.64 s each | Concurrent PNG reveals against movies and never-built art. |
| 103 | Twist 1.5 s → 104; Direction and Twist amount as on wall | 5× `PIN DROP WAVE.mov`; Play across slides off; Trim 0–2.64 s each | Live outgoing frames against transition still frames; during review, record which movies are playing at the Twist click. |
| 104 | Dissolve 0.5 s → 121 (incidental) | 1× `shutterstock_17707843.mov`; Play across slides on; Trim 0–14.875 s | Arrival still frame against the live movie. |
| 121 | Revolve 1.3 s → 122; Direction as on wall, other options as on wall | 1× `PIN DROP WAVE.mov`, **no Start Movie build** (delete one if Keynote adds it on insert); Play across slides off; Trim 0–2.64 s. | Revolving planes vs 122's static (never-built) art. |
| 122 | None → 124 (incidental; no duration to set) | None | Use the PDFs that are wall builds 1–3; keep any never-built object they overlap. |
| 124 | Dissolve 0.5 s (incidental terminal exit) | None | Both groups against never-built art. |
| 57 (optional) | Dissolve 0.5 s → 86 (incidental) | None | PDF against never-built art. |

The required Iris build sample is 122's three PDFs plus 101's three PNGs and three movies. Optional 57 adds the 1.75 s Iris timing only; omit it unless that comparison is wanted. All other builds are omitted under the object rule above.

Save as `~/Desktop/Convert wall to 16x9 CGs/F2-inc1/GW-inc1-DSK.key`. Hand the saved deck to the coordinator for Step 0a before exporting; correct any reported mismatch, then export to `~/Desktop/Convert wall to 16x9 CGs/F2-inc1/GW-inc1-DSK-html/` for Step 0b. Authoring, copying assets and export are owner-run after owner review. This planning revision performs none of them.

## 4. Sheet verification, then eye

Step 0a (offline, coordinator, quiet machine): run `deck_builds` + attribute readout on `GW-inc1-DSK.key` and diff against §3 and the completed artwork appendix: effect, type, duration, direction/options, authored build order, automatic/referent/delay, kind/identity and group children, opacity, masks/crops and overlapping z-order; movies = every movie object on the slide (not only Start Movie targets), with Repeat/Play across slides/Trim; slide size 1920×1080 and No Fill on master and slides. Compare relaid-out overlap relationships, not wall coordinates. Record accepted Delay rounding; ignore transition delay/easing when On Click and Start Movie duration. Owner corrects slips before export.

A direction that is absent on the wall and explicit in the authored deck is resolved by player branch, not by equality: Iris must not be 42; Twist absent ≡ any value ≠ 11; Flop absent ≡ 11; Revolve = 13. Step 0b confirms the exported value. Player constants are `M=11,F=12,d=13,U=14,K=42`; Twist `hB` tests 11, Iris `rB/DB` tests 42, Flop `YB` coerces out-of-range values to 11. This is a branch-equivalence check, not permission to guess the inspector's Direction label. The coordinator's row-121 check is “Revolve 1.3 s, Direction as on wall (IWA 13), other options as on wall”; the raw source has `customBounce=false`. Both Twist sources have `customTwist=3.3`; owners copy the inspector's Twist amount, then the coordinator verifies it offline.

Start flags are relative to the immediately preceding retained build: `(F,T)` = On Click; `(T,T)` at authored chunk 0 = After Transition and later = After Build N; `(T,F)` later = With Build N. First kept builds on 103/124/optional 57 use `(T,T)` instead of an undocumented first-build With encoding. The explicit §3 table governs; 5 retains its original On Click Build 1. On 101, movies follow Iris Build 3 concurrently through the listed With chain. Slide 124 retains order but cannot retain spacing dependent on dropped predecessors. On 103, the five starts are concurrent with small listed offsets; they finish about 2.64 s after arrival unless the owner clicks sooner, so expect the last frame to jump to the baked frame when Twist starts later. Keep that movie-state observation separate from alpha.

Step 0b: export census as now, compared with the sheet, including exported direction branch and actual accepted delay values. Coordinator records source→authored numbering independently of the owner-facing Build Order numbers. Optional direction coverage from 9/51/96/102 remains conditional: add one only if coordinator evidence reveals an Iris direction absent from 122/101, and supply a complete additional owner row before authoring; none is in the baseline.

Conversion (resizer/Generator) is superseded by the owner's authored-deck decision (32:9 source); Generator forces clip Dissolve (`dsk_assemble.py:4206`) — not used. Future artifacts also include `manifest.json`, `native/` and `census/` under `~/Desktop/Convert wall to 16x9 CGs/F2-inc1/`; never main-checkout `output/`.

Coordinator adapts `census_f2.py` to take an export path (or equivalent) when Step 0b runs; no broad fixture rescan.

Record source→authored→export event/JSON pointer, names/type/tree/options/timing/assets and player SHA. Retained plausible data admits eye review, not fidelity. Retained name with flattened semantics flags degradation (Line Draw precedent). Missing/changed effect, target or unsupported player = unavailable/export loss; resolve incomplete census first. A visible degraded failure enters W1 by its actual route. Export remains unverified.

Owner plays the authored deck/export through **Alpha Keynote, default continuity, HDMI Chrome and managed-OBS Keyer**, beside native Keynote. Record pass/fail/unavailable per slide/output, every click, timing/direction, alpha, foreground order and movie state; Twist movie freeze separate from alpha.

For transitions, pass = replacement intent (outgoing never visible where the iris has revealed the incoming), not merely parity with native No Fill playback.

Apply the same criterion to Flop's static halves (Dissolve §0 precedent). Native may share the artifact; parity cannot excuse it. Passing families stop stock/eye-qualified. Missing evidence is unavailable. Keep native recording; alpha-reference capability remains unverified, requested only for failed alpha cases. Continuity-off is diagnostic only.

## 5. Conditional diagnosis/repair

For an rgb>alpha symptom, reuse `premultiply_halo` first, on a capture path a positive control shows it resolves (a straight-alpha PNG can hide rgb>a).

It measures `rgbMaxOnZeroAlpha` (`html_alpha_probe.py:559`). Reuse `score_fade` only for two-texture fades; spatial reveal/particle/stacking checks follow actual symptoms. Opaque controls only for failed transitions. New checks need resolving positive and demonstrated-wrong negative; retain raw evidence; missing controls/frames/SHA ⇒ INCONCLUSIVE. Random particles need region/eye evidence.

Twist movie failure requires coordinator/Stage B scope coordination **before W1**: R11/R12 `__obedFreeze`/`__obedFreezeTake` are gated by `obedDissolve`/`__obedShape` to Dissolve/none, continuity-adjacent; not a shader fix. Do not extend eligibility implicitly.

Prefer exact effect-local admission for demonstrated failures; unknowns stay stock. No prediction-only global `aB` blend/shader/upload change, deck-start block or speculative export reconstruction. Preserve MM/Dissolve/Line Draw gates, cleanup and pin refusal; repeat owner eye after repair.

## 6. OQ record

| OQ | Status / recommendation |
|---|---|
| F2-0 usage | Answered by D2/W(−1). |
| F2-1 acceptance | Answered D1/D4 + owner: 13 authored slides, eye first. |
| F2-2 Fade Through Color | Moot; absent from usage. |
| F2-3 boundary | Selected GL only; smart/gallery excluded. |
| F2-4 / F2-5 / F2-7 | Stock with limits / symptom-only instruments / unused failures deferred. |
| F2-8 shared GL | Effect-local preferred; shared changes and Twist freeze coordinate Stage B. |
| F2-9 fidelity/Iris/movies | Answered: authored deck per sheet; Iris = 122(3) + 101; movies per inc1 map. Pre-fill corrects 121; coordinator completes artwork fields before authoring, owner copies wall inspector Direction/options and records exceptional text Delivery. |
| F2-10 degraded semantics | Unavailable/deferred unless observed failure and sufficient exported information support narrow repair. |

## 7. Streams and ownership

Later implementers GPT-5.6 Sol high; reviewers Opus 5.5 high. No implementation/delegation now; coordinator serializes pins.

| Stream | Gate/deliverable |
|---|---|
| W(−1)/W0 | Usage/pre-fill supplied → coordinator artwork appendix → owner inspector settings/authorship → offline diff → export census → product-path eye. |
| W1 | Failed families only; symptom evidence/instruments, including selected GL runtime area. |
| W2 | Demonstrated used failures only; runtime patches, focused tests, both-player pins; MM/Dissolve/Line Draw/shared replay regressions as affected. |
| W3 | Owner eye; record stock-qualified/repaired/unavailable/deferred; later docs. |

Shared seams: `fB.setupTexture/textureInfoFromEffect`, `R.createTexture`, first GL draw/DOM hide, shader/uniform identities and pins. R1/R2 annotate all GL leaves; selected custom draws do not consume MM opacity annotations. R5 changes all GL hide timing, not CSS Revolve. R3/R4/R7 are MM drawing; R6/R8 MM-only. [Census §6.3]

R9–R12 and the Line Draw hooks are name/shape-gated no-ops on the selected names; incidental Dissolve/none exits (87/104 with movies) exercise #262's freeze and are outside F2 status.

`live_gl_replay_js.py` captures settled MM, preserving upload flip/premultiply flags. Stage B's planned feed shares context hooks/upload ordinals; absent in rev-3-inspected checkout. Stage B owns `live_continuity_js.py`/feed; coordinate replay tests/hook order on shared changes. Do not widen `glReplay` to F2. [Census §6.7]

## 8. Revision log / per-finding disposition

Rev 2 retained eye-first/conditional controls. Rev 3 added D1–D4 and verified GL facts; its subset/conversion decision was superseded. Rev 4 folded r2. **Rev 5, 2026-10-14: FINAL for owner review**, all 11 r3 findings folded; no r3 finding refuted and no live qualification claimed. The r3 critique reports 0 blocker, 0 major, 5 medium and 6 low. Its replacement wording is retained where applicable; raw IWA/enum explanations are placed in coordinator sections to keep §3 in Keynote inspector wording. Expanded 103 rows spell out the critique's Build 2–5 shorthand. Finding 5 additionally follows the owner's instruction to pre-read and append artwork fields before authoring; no values are invented.

| r3 finding | Disposition / evidence |
|---|---|
| 1 · medium · must-fix: inspector wording | Applied §3: exact “How to read the sheet” replacement, 1-based Build Order, Start/Delay, Start Movie without duration, Format › Movie and Start Transition On Click. Source numbers appear only as bracketed coordinator checks. Raw flags/options stay in §4. |
| 2 · medium · must-fix: deterministic re-anchoring | Applied §§3–4: exact re-anchoring replacement and complete per-slide Start/Delay table; 103/124/57 first kept builds use After Transition; 5 retains On Click. 101's movies follow the Iris chain. 124's source spacing cannot be reproduced. Accepted 0.01/0.02 rounding is recorded in Step 0a. Evidence: r3 flag analysis and pre-fill. |
| 3 · medium · must-fix: dropped-build objects | Applied §3: exact rule keeps dropped-build objects built/static on 6/34/86/103/121, omits them on 5/7/101/122/124/57 and keeps never-built objects. Exact 122 overlap replacement uses wall builds 1–3 and never-built overlaps. |
| 4 · medium · must-fix: Direction | Applied §§3–4: exact wall-inspector Direction/options instruction; owner copies Twist amount. Exact branch-equivalence replacement in Step 0a and export confirmation in Step 0b: Iris ≠42, Twist ≠11, Flop equivalent to 11, Revolve 13. Raw row-121 wording is in §4; inspector wording is in §3. Evidence: r3 player constants/branches. |
| 5 · medium: remove owner metadata burden | Applied §§2–4: deleted catch-all and incidental movie-at-exit requests; exact owner/coordinator division retained outside the sheet. Coordinator pre-authoring table lists identities, opacity, masks/crops, z-order/overlaps and group children per slide and requires a readable appendix in §3. Values pending offline readout, not invented. Only exceptional text Delivery and 103's live movie observation require owner records. |
| 6 · low: 121 movie / completeness | Applied §§3–4: exact movie cell, no Start Movie build (delete insertion-added build), Play across slides off, Trim 0–2.64 s. Step 0a counts every movie object and checks 1920×1080 plus No Fill on master/slides. Evidence: pre-fill archive vs map's movie-start-target count. |
| 7 · low: Revolve destination | Applied §3: “Revolving planes vs 122's static (never-built) art.” Iris build-ins are hidden at arrival. |
| 8 · low: Twist rgb > a | Applied §1: exact translucent-lit-pixel replacement, diffuse up to 1.2 plus specular; edges are the most visible location, not the only one. |
| 9 · low: halo capture validity | Applied §5: exact replacement requires a positive control proving the capture resolves rgb>alpha; straight-alpha PNG may hide it. |
| 10 · low: non-settings | Applied §§3–4: no inactive transition delay/easing or Start Movie duration in the sheet; all transitions On Click. Step 0a explicitly ignores transition delay/easing when On Click and Start Movie duration. |
| 11 · low: duplicate columns / import option | Applied §3: duplicate column specification removed; exact copy/paste technique retained and marked RECOMMENDED, package-file extraction fallback, then resize/re-layout at 16:9; Step 0a checks either path. |

Prior r2 dispositions remain folded: authoring sheet; separate Twist movie state and Stage B gate; Iris roles/replacement intent also applied to Flop; rgb>alpha symptom handling; Iris minimum 122(3)+101 and optional 57; explicit incidental exits; offline verification; R9–R12 gating; export-path census adaptation; short conversion supersession. The sole prior partial refutation remains evidence-backed: r2's “121 … none” used a movie-start-target count; the pre-fill's movie archive establishes one `PIN DROP WAVE.mov` without a Start Movie build. No new refutation.

Plan critique closed after r3 (0 blocker/0 major); stop rule.
