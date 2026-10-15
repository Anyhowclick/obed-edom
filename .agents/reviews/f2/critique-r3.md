# F2 plan rev 4: critique r3 (Opus 5.5 high, independent plan critic, final round)

**Verdict: FOLD, THEN OWNER REVIEW.** 0 blocker, 0 major, 5 medium, 6 low. Every sheet value matches the coordinator's pre-fill. No row has a transcription error. The open problems are about authorability. The sheet speaks in source build numbers and IWA terms. It leaves the owner three "unknown anchor" questions that the data already answers, and it does not say what happens to objects whose builds are dropped. **Must-fix before owner review: findings 1–4.** Findings 5–11 are folds of the usual round-3 kind. Under the stop rule nothing here justifies a round 4.

Static only. I read the plan, r1, r2, the pre-fill, the slide map, `rev3_gl_anchors.md` and census §6. I grepped `iwa_movies.py`, `html_alpha_probe.py`, `live_runtime.py` and `.agents/plans/dsk.plan.md`, and sliced P's `main.js` by byte offset. I ran no browser, OBS, Keynote, osascript or pytest, opened no `.key` and made no git writes.

## Verified (no change needed)

**Sheet vs pre-fill, row by row.** All of the following match. Start modes are read from `(automatic, referent)` per `iwa_movies._CLIP_MODE_BY_FLAGS` (`iwa_movies.py:509`).

| Slide | Effects and timing | Movies | Exit |
|---|---|---|---|
| 5 | Sparkle 1.25 s on the three named text boxes: #0 C/0, #1 A/0, #2 C/0 | none | Dissolve 0.5 |
| 6 | Flop 1.0 | none | (Flop is the transition) |
| 7 | Anvil 2.0 on `Report Card.png`, #0 A/0 | none | source MM 1.8, correctly replaced by incidental Dissolve |
| 34 | Iris 4.0 | none | (Iris is the transition) |
| 35 | none | none | source MM 1.0, replaced |
| 86 | Twist 1.5, customTwist 3.3 | none | (Twist is the transition) |
| 87 | M #0 A/0 | `shutterstock_3637941261.mp4`, PA true, 8.76 | Dissolve 0.5 |
| 101 | Iris 1.0 #0 A/0, #1 W/0, #2 W/0 | M #5/#8/#11 W/0.01, PA false, 2.64 | Dissolve 0.5 |
| 103 | Twist 1.5 | M #47/#50/#53/#56/#59 W/0.02, PA false | (Twist is the transition) |
| 104 | M #0 A/0 | `shutterstock_17707843.mov`, PA true, 14.875 | Dissolve 0.5 |
| 121 | Revolve 1.3, direction 13, customBounce false | `PIN DROP WAVE.mov`, PA false, 2.64, no movie-start build | (Revolve is the transition) |
| 122 | Iris #0 A/0, #1 W/0.01, #2 W/0.01 | none | `none`, stored 1.0 |
| 124 | Sparkle #1 1.3 A/0, #6 1.4 A/0 | none | Dissolve 0.5 |
| 57 (optional) | Iris 1.75, #1 W/0 | none | (not stated) |

**Internal consistency.**
- Iris has 26 targets in total: 14 + 5 + 3 + 1 + 1 + 1 + 1.
- 122's Iris orders 0–13 are contiguous, and the 150 other builds come after them. Cutting to builds 0–2 therefore keeps the chain intact.
- Rev 4 correctly refutes r2's "121 has none". The slide map counts only movie-start targets, while the pre-fill lists the movie archive itself.

**Iris T0/T1 roles** (`rB` @2204956 + `iris` shader @1988364):
- T1 is drawn first with `PercentForAlpha=0, Mix=0`. That gives `smoothstep(0,0,d)`, which GLSL leaves undefined, so the plan's "note only" is correct.
- T0 starts invisible and ends full in both branches, so T0 is the incoming slide.

**Twist a²** (`twist` fragment @1989786, base `SRC_ALPHA,ONE_MINUS_SRC_ALPHA` @2197825):
- Output is `(a·(a·c·d+s), a²)` over the transparent clear.
- `d = 0.2 + ndotl ≤ 1.2`.

**Sparkle rgb > a.** r2 verified this and it still holds.

**`premultiply_halo`.** It is at `html_alpha_probe.py:559` and returns `rgbMaxOnZeroAlpha`.

**R11/R12.**
- `__obedFreeze` is gated on `C.obedDissolve` (`live_runtime.py:165`), and its hook sits in the CSS `cssRenderer.draw` path (269).
- `__obedFreezeTake` returns unless `__obedShape(y)` (85), and is hooked into `jumpToScene_partFour` (273).
- The plan's names and gating are therefore exact.

**r1/r2 folds.** All ten r2 dispositions appear in the text. No r1 fold regressed: eye-first, conditional W1, transition-only opaque controls, smart/gallery excluded and the default-continuity product path are all retained.

## Findings

1. **medium · authorability (must-fix) · The sheet speaks source build numbers and IWA flags, but Keynote's Build Order shows 1-based builds and different start labels.**
   **Evidence:**
   - The sheet uses 0-based source `#` ("#0 C/0, #1 A/0") and C/A/W with "after previous".
   - Keynote's Build Order numbers builds from 1. Its Start menu offers On Click, After Transition (for build 1) and After Build N / With Build N. `.agents/plans/dsk.plan.md:385–388` gives the measured encoding: `(T,T)` at chunk 0 = After Transition, at >0 = After Build N; `(T,F)` = With Build N; `(F,T)` = On Click.
   - Example: "#1 A/0" on slide 5 is Keynote's "Build 2: After Build 1". The owner can easily read it as "Build 1: After…".
   - "U", "M", "PA", "T", "referent", "customTwist=3.3" and "direction=13" are not inspector words.

   This is the off-by-one slip class that Step 0a exists to catch. It is cheaper not to cause it.
   **Fix:**
   - Replace the "Sheet key" paragraph with:
     > "**How to read the sheet.** Build numbers are Keynote's Build Order numbers (1, 2, 3…) in the authored slide; the source build number follows in brackets for the coordinator's check only. Start = the Build Order 'Start' menu: On Click, After Transition, After Build N or With Build N; Delay = the Build Order 'Delay' field (seconds). Every build is a Build In with Direction left as on the wall slide (finding 4). 'Start Movie' = Keynote's Start Movie build (no duration to set). Movie settings are in Format › Movie: Repeat None for every movie; 'Play across slides' as listed; Trim start 0, end as listed (usually the whole file — check). Transitions: Start Transition On Click for every slide, selected and incidental; duration as listed."
   - Rewrite the Effect/start cells in those words. The exact text is in finding 2's table.
   - Drop "U" (finding 3).

2. **medium · authorability/correctness (must-fix) · The "unknown retained timing anchors" are not unknown, and "original relative timing" on 124 cannot be kept.**
   **Evidence:**
   - Start flags are relative to the previous build. No anchor ID is stored: the chunk has only `automatic` and `referent` booleans (`iwa_movies.py:509–520`). Removing builds re-anchors each kept build onto the new previous build, deterministically.
   - **101.** Movies #5/#8/#11 (W/0.01) were "with" dropped builds #4/#7/#10. After the drop they start with Iris build 3. All three movies then play concurrently with the reveals, which is useful coverage.
   - **124.** Sparkle #1 followed a dropped #0 and Sparkle #6 followed a dropped #5. Their source spacing depended on the dropped builds' durations and start modes, which the sheet does not have. "Keep … original relative order and timing" (§3 l.68, row 124 "original relative timing") is not achievable.
   - **103 and 57.** The first kept build becomes chunk 0 with `(T,F)`. That encoding is undocumented at position 0 (dsk.plan documents only After Transition there), and "With Transition" would run it during the incoming Dissolve.
   - The plan's "owner records remapping before export; do not silently serialize concurrent starts" gives the owner nothing to act on.

   **Fix:** replace §3 l.68's sentences from "Removed predecessors…" to "…timing." with:
   > "Dropping builds re-anchors the kept ones: a kept build whose source predecessor was dropped starts **After Transition** (keeping its delay) if it is now build 1, otherwise **With/After Build N** of its new predecessor exactly as the source With/After. Source spacing that depended on dropped builds is not reproduced; this is intended. Step 0a checks the flags below."

   Then use these cells (authored build numbers; source number in brackets):

   | Slide | Builds (Start, Delay) |
   |---|---|
   | 5 | 1 [0] Sparkle "He stood between" On Click, 0 · 2 [1] Sparkle "the living and the dead" After Build 1, 0 · 3 [2] Sparkle "the plague stopped" On Click, 0 |
   | 7 | 1 [0] Anvil `Report Card.png` After Transition, 0 |
   | 87, 104 | 1 [0] Start Movie, After Transition, 0 |
   | 101 | 1 [0] Iris After Transition, 0 · 2 [1] Iris With Build 1, 0 · 3 [2] Iris With Build 2, 0 · 4 [5] Start Movie With Build 3, 0.01 · 5 [8] Start Movie With Build 4, 0.01 · 6 [11] Start Movie With Build 5, 0.01 |
   | 103 | 1 [47] Start Movie After Transition, 0.02 · 2–5 [50/53/56/59] Start Movie With Build 1–4, 0.02 each |
   | 122 | 1 [0] Iris After Transition, 0 · 2 [1] Iris With Build 1, 0.01 · 3 [2] Iris With Build 2, 0.01 |
   | 124 | 1 [1] Sparkle "183 / CHC Churches" 1.3 s After Transition, 0 · 2 [6] Sparkle "Total Churches / 269" 1.4 s After Build 1, 0 |
   | 57 (opt.) | 1 [1] Iris 1.75 s After Transition, 0 |

   If the Delay field will not hold 0.01 or 0.02 s, enter the nearest value it accepts; Step 0a records it. Delete "retained movie referent anchors", "retained start anchors" and "original relative timing" from the 101, 103 and 124 cells.

3. **medium · authorability (must-fix) · Objects whose builds are dropped are unspecified.**
   **Evidence:**
   - "Builds outside the selected set are not authored" (§3 l.42) says nothing about their **objects**:
     - 122: 11 Iris PDFs + 138 bc-drop + 12 twist-and-scale targets.
     - 101: 12 objects.
     - 124: 7 objects.
     - 103: 55 objects.
   - Row 122 asks the owner to keep "an overlapping static/later sibling". A "later sibling" is exactly a dropped-build object, and the sheet does not say whether it stays as static.
   - The owner will ask this in the first minute of authoring.
   - Omitting them on build slides is also faithful where it matters. 122 is Revolve's incoming slide, and in its arrival state every build-in target is hidden anyway.

   **Fix, add to §3 after "A transition source is authored at its fully built state.":**
   > "Objects whose builds are dropped: on a **transition source** (6, 34, 86, 103, 121) keep them as plain static objects in their built state; on a **build slide** (5, 7, 101, 122, 124, 57) leave them out. Objects with no builds on the wall slide are always kept."

   Replace row 122's overlap cell with:
   > "Use the PDFs that are wall builds 1–3; keep any never-built object they overlap."

   Delete "if the source has one" / "later sibling" from §3 l.64.

4. **medium · correctness (must-fix) · "Direction absent/default" is not safe to author as "leave default", and the player branches on exact values.**
   **Evidence:** player constants `const M=11,F=12,d=13,U=14,K=42` sit just before the shader dictionary in P's `main.js`.
   - **Twist** `hB` @2212878 bends by `this.direction===M ? n.x : 1-n.x`. An absent direction takes the **non-11** branch, so an explicit 11 written by Keynote flips the twist.
   - **Iris** `rB`/`DB` branch on `direction===K` (42), which flips mix and progress (iris from the centre vs from the edges).
   - **Flop** `YB` @2217756 coerces anything outside 11–14 to 11.

   Keynote may write an explicit direction when the owner applies an effect in a new deck. The pre-fill only knows the wall's field is absent. Revolve's "13" is `d`, an enum value the owner cannot set by number. The eye step compares the authored export against native **authored**, so a direction slip passes both sides unseen.
   **Fix:**
   - Replace "Twist/Flop/Iris direction absent/default" and "Default direction's inspector label is still to record" with:
     > "Direction and other effect options (Twist amount, Revolve options): set them to what the **wall slide's** inspector shows for that effect."
   - Add to Step 0a:
     > "A direction that is absent on the wall and explicit in the authored deck is resolved by player branch, not by equality: Iris must not be 42; Twist absent ≡ any value ≠ 11; Flop absent ≡ 11; Revolve = 13. Step 0b confirms the exported value."
   - In row 121, write "Revolve 1.3 s, Direction as on wall (IWA 13), other options as on wall".

5. **medium · simplicity/owner burden · "U" makes the owner transcribe what the coordinator can read offline.**
   **Evidence:**
   - "U = owner reads remaining inspector options, opacity/masks, source artwork identities and overlapping z-order".
   - Row 122 "U + chosen object IDs". Keynote does not show object IDs.
   - Rows 87/104/121 ask "playing at exit", but those exits are incidental and outside F2 (§7 l.126).
   - Opacity, masks, z-order and drawable identity are all in the wall IWA, beside the data the coordinator already pre-filled. They are also in the authored `.key` for Step 0a.
   - Owner context is "keep it simple".

   **Fix:**
   - Delete the "U" definition and every "U + …" from the sheet.
   - Delete "Unlisted static asset names/geometry/z-order are **unknown**, owner records them."
   - Delete "+ playing at exit" from 87/104/121.
   - Add:
     > "Owner reproduces each wall slide by eye (same objects, same overlaps, same opacity). Coordinator compares opacity, masks, z-order and object identity offline in Step 0a. The owner records only what IWA lacks: text Delivery on 5/124 if not 'All at once'."
   - Keep the 103 "record which movies are playing at the Twist click". It matters, and only the eye can know it. With finding 2's starts, all five end 2.64 s after arrival unless the owner clicks sooner, so expect the last frame to jump to the baked frame.

6. **low · authoring/fact · Slide 121's movie start is not "unknown".**
   **Evidence:**
   - The slide map lists 121 with "other builds: {}", so the slide has no builds at all.
   - The pre-fill shows the movie with no movie-start build and `autoPlay` absent.
   - The slide map's "movies: 0" counts movie-start targets only, so a movie count based on it misses build-less movies.

   **Fix:**
   - Row 121's movie cell becomes:
     > "1× `PIN DROP WAVE.mov`, **no Start Movie build** (delete one if Keynote adds it on insert); Play across slides off; Trim 0–2.64 s."
   - In Step 0a, change "movie count" to:
     > "movies = every movie object on the slide (not only Start Movie targets), with Repeat/Play across slides/Trim".
   - Add "slide size 1920×1080 and No Fill on master and slides" to the same Step 0a list.

7. **low · fact · Row 121→122, "Revolving planes vs 122 PDFs".** 122's Iris PDFs are build-ins and are hidden in 122's arrival state, which is what Revolve composes.
   **Fix:** "Revolving planes vs 122's static (never-built) art."

8. **low · fact · Twist's rgb > a is not confined to edges.** With `d ≤ 1.2` and specular unweighted by alpha, any translucent pixel gives `rgb = a²·c·d + a·s > a²` whenever `c·d > 1` or `s > 0`.
   **Fix, Twist cell:**
   > "…; diffuse up to 1.2 plus specular gives rgb > a on translucent lit pixels, most visibly at antialiased edges."

9. **low · instrument validity · `premultiply_halo` may be blind on the usual capture.** It reads an RGBA array (`html_alpha_probe.py:559–571`; PNG via `save_png`/`load_rgba`). On an un-premultiplied capture, a premultiplied rgb > a pixel saturates, or reads rgb 0 at alpha 0. `rgbMaxOnZeroAlpha` can then pass a real glow.
   **Fix, §5:**
   > "For an rgb>alpha symptom, reuse `premultiply_halo` first, on a capture path a positive control shows it resolves (a straight-alpha PNG can hide rgb>a)."

10. **low · authoring noise · "stored delay 0.5, EaseInEaseOut" and "M … duration 0.5" are not owner settings.** An On Click transition's Delay is inactive, easing is not exposed, and Start Movie has no duration control. The pre-fill also does not state that the **incidental** source exits are manual.
    **Fix:**
    - Delete these from the key; finding 1's wording already says "Start Transition On Click for every slide".
    - In Step 0a:
      > "ignore transition delay/easing when On Click and Start Movie duration".

11. **low · proportion and option · §3's (a)–(e) column specification duplicates the sheet and no longer matches its five columns.**
    **Fix:**
    - Delete "Columns: (a)…(e)…" (§3 l.36–40). Keep the pre-fill sentence, the source-asset paragraph and the sheet.
    - Optional owner technique, one line:
      > "Copying objects from the wall slide and pasting them into the authored slide keeps the original file, PDF vector, crop/mask, opacity and movie trim; copying files out of the package is the fallback; Step 0a checks either way."

      This is a technique, not a design change. Re-layout is still the owner's.

## Not raised

- §1 Iris and Flop wording, the `smoothstep` note, Sparkle, Anvil and Revolve cells, and the §5/§7 gating names are all accurate.
- §4's coordinator-only "event/JSON pointer" record is coordinator jargon, but the owner never reads it.
- D1 proportion holds: instruments stay conditional on owner-marked failure.
