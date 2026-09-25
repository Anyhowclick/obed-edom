# Magic Move shape identity — plan (decisions taken 2026-09-24; experiments await a Keynote slot)

Goal: make `mmKeys` for shapes (and lines, and groups that contain shapes) pair the way Keynote's
Magic Move actually pairs them. Then let the planner's off-canvas partner keeping
(`map_remap._keep_mm_partners`, #224) and the `mm.zorder_flip` rule (branch
`claude/mm-zorder-validation`, uncommitted in worktree `great-williamson-5138af`) rely on those keys.

## 0. What the offline data already shows (2026-09-24, no Keynote)

Read-only IWA dump of the pristine `Minimal Alpha_DSK.key` (sha1 `15b85f42…` = `fixture.sha1`),
slides 1→2:

| slide | kindIndex | current key | naturalSize | path points (bezier) | style → resolved |
|---|---|---|---|---|---|
| 1 | 0 | `728c` | 260×229 | 174×154 rect | 15336742: black fill, white 4 pt stroke |
| 1 | 1 | `d436` | 174×154 | 174×154 rect | 15336941: green (theme `shape-1`), opacity 0.29 |
| 2 | 0 | `d436` | 174×154 | 174×154 rect | **15336742** (same style object as slide-1 black) |
| 2 | 1–3 | `76ee` | 351×310 | 174×154 rect | 8520/8519/8521: theme yellow/red/pink, opaque |
| 2 | 4 | `76ee` | 351×310 | 174×154 rect | **15336941** (same style object as slide-1 green) |

Findings:
1. **The size bug is not corner radius.** Every shape is a `bezierPathSource` whose path points stay
   in the coordinates they were drawn at (174×154). Only `naturalSize` changes on resize. Dividing
   by `naturalSize` therefore yields a different hash per size. The fix is to normalise by the
   **path's own bounding box**.
2. Only one of the four big slide-2 squares is green: kindIndex 4, which shares the green's style
   object. The other three have theme yellow/red/pink styles. (The brief called all four green; the
   IWA says otherwise. In `fx_sheet.png` the green lands on ki 4 at x≈790. The other three are not
   visible during the transition, probably because they build in later; I have not verified that.)
3. Keynote's observed pairing (green→ki 4, black→ki 0) matches **style identity** exactly. The
   geometry is the same for all six shapes. FX cannot tell apart "shared style object" from "equal
   resolved fill/stroke/opacity" from "fill only".

Proxy count, using key B = bbox-normalised geometry + resolved (fill, stroke, opacity), over the
decks' MM pairs. This counts multiset matches only, not which pairs match:

| deck | MM pairs | shapes | matched now → B | unique-matched now → B | pairs that differ |
|---|---|---|---|---|---|
| Minimal Alpha_DSK | 5 | 9 | 2 → 3 | 2 → 3 | 1 |
| Gold_Wall_Input | 3 | 607 | 279 → 279 | 3 → 5 | 2 |
| Full_Report_Card_Wall | 21 | 748 | 300 → 303 | 22 → 25 | 5 |

Most matched shapes are **repeated** keys (279 matched vs 3 unique on Gold), so the tie-break
decides most of the outcome, not the key.

Housekeeping: `output/evidence/mm-dup-pairing/FX.key` disappeared at about 17:23 today. I did not remove it;
another session probably cleaned up. Keynote was running when I started and had exited by then. I
did not touch it.

## 1. Experiments (live Keynote, needs the owner's go)

### Instrument
- Reuse the `gen.py` pattern. Each variant is a 1920×1080 two-slide deck with a black background,
  a Magic Move of 2 s, and a ProRes 30 fps QuickTime export. One AppleScript file runs a batch. It is
  launched unsandboxed with a per-batch deadline and a `quit` at the end. Guard the quit hang seen
  in run3 by closing documents first and checking `pgrep -x Keynote` afterwards. Everything lives
  under `output/evidence/mm-shape-id/`.
- **Colour-agnostic readout:** take the non-black mask of the **mid-transition frame** (t = 0.5)
  and compute its blob centroids and sizes.
  - A morph appears as one blob at the midpoint of source→target, with interpolated size.
  - A non-match appears as the source fading in place plus the target fading in place.
  - Each variant's geometry is placed so that the outcomes {→A, →B, no match} land on disjoint
    predicted positions. The script reports the verdict against those predictions, not by eye.
    Unexplained blobs are reported as `INCONCLUSIVE`.
- **Controls, run in every batch:**
  - null control: identical slides, so no mid-frame motion is expected.
  - positive control: one plain rect that moves and resizes, so a morph is expected.
  - FX replay: slides 1–2 of a fresh copy of Minimal Alpha_DSK, which must reproduce green→ki 4.
- **Styling limitation:** Keynote's AppleScript cannot set a shape's fill, stroke or preset type. It
  can set size, position, opacity, rotation and text. So the variants start from a **palette
  deck**: one slide of pre-styled shapes at known grid positions. The generator duplicates the
  palette slide, deletes the shapes it does not need (identified by grid position), and places the
  rest. This uses the same duplicate-and-prune pattern as `D0`. The palette is checked offline
  (IWA dump of style, path and preset) before any run. Owner decision **D1** covers who authors it.

### Matrix

"Single" = one source, one target that differs only in X. It asks whether X blocks matching.
"Compete" = one source and two targets: A equals the source, B differs only in X, and **B is
nearer**. It asks whether X outranks position.

| # | attribute X | single | compete | notes |
|---|---|---|---|---|
| E1 | size / aspect (same style) | ✓ | ✓ | expect tolerant (FX); confirms bbox normalisation |
| E2 | fill colour | ✓ | ✓ | the FX case, isolated |
| E3 | stroke on/off, colour, width | ✓ | ✓ | |
| E4 | opacity (value only, AppleScript) | ✓ | ✓ | green's variation is opacity-only |
| E5 | shared style object vs equal values in separate objects | — | ✓ | decides "style id" vs "resolved values" |
| E6 | path type: rect vs oval vs custom bezier vs preset | ✓ | ✓ | |
| E7 | preset corner radius (rounded rect r=0 vs r=20) | ✓ | ✓ | the original hypothesis |
| E8 | text inside (none / "A" / "B") | ✓ | ✓ | today text shapes key as `text:`; check that text wins over the shape |
| E9 | rotation | ✓ | — | expect tolerant (interpolated) |
| E10 | line vs line (length, stroke, arrowheads) | ✓ | ✓ | today every line keys as `"line"` |

**Tie-break** among identical shapes: a direct copy of the media set Z0/Z1/N0/N1/M2/C1/G1 with
identical shapes in place of the image. It separates z-order, duplication identity, greedy nearest,
and optimal total centre distance.

**Cross-kind sanity check** (one run): a unique shape against a unique image. Expect no match.

Size: about 35 variants at roughly 30 s each, so 2–3 batches of ≤ 10 min. Every batch is a
foreground run with a log and one report.

### Stopping rule
Every row must reach a verdict with its controls green. If a result is surprising (for example,
"any shape matches any shape when it is unique"), add a follow-up row before designing anything
around it.

## 2. Results (live, 2026-09-24): 58 decks, 0 INCONCLUSIVE, palette checksum OK after every deck

Evidence lives in `<main>/output/evidence/mm-shape-id/runs/`: `<name>.key`, `<name>.m4v`, batch logs, and
`results.json` in the worktree harness. Every verdict was cross-checked by eye on contact sheets
(TM2, TG1, TG1b, TD0, TD1, TZ1, E2c). An offline audit confirmed that every run deck holds exactly
the specified objects and geometry.

**A. Hard gate: does a shape pair at all?** Tested with one source and one target.

| Pairs (morphs) | Never pairs (the source fades out, the target fades in) |
|---|---|
| size / aspect, fill, stroke on/off/colour/width, opacity, a different style object with equal values, rounded-rect radius 10→60, rotation, the same text | rect → oval, rect → triangle, bezier rect → editable path, bezier rect → preset rounded rect; no text → text, text A → B; shape → image |
| lines: length | lines: arrowhead, width 4→12, colour white→yellow |

So the gate for shapes is the path class plus the **bbox-normalised** geometry (a preset compares
by its type; its radius is ignored) plus the exact text. Shape style never blocks a pair. For lines
the stroke and line ends are part of the gate.

**B. Preference among compatible candidates.** A clean test changes one property on the nearer
candidate B, while A is identical to the source. G_* runs at the normal layout (B 721 px away, A
849 px); XF_* runs at an extreme layout (B 450 px away, A 1450 px).

| B differs only in | normal | extreme | conclusion |
|---|---|---|---|
| fill (and style object) | A | A | beats distance |
| stored raw path (R2 drawn at 100 then scaled; bbox-equal) | A | A | beats distance |
| opacity | A | A | beats distance |
| stroke | A | A | beats distance |

Two-way conflicts measured in E2c, E3c_on and E4c (A differs in raw path, B in something else)
give the order:
**{stroke, opacity} > raw stored path > fill/style object > least total centre distance.**
- E3c_on: stroke outranks raw path.
- E4c: opacity outranks raw path.
- E2c: raw path outranks fill.
- E5c: a style object that differs with equal fill/stroke/opacity still outranks distance.

**C. Ties** (identical candidates):
- The optimal least-total-distance assignment wins (TG1 and TG1b: greedy and slide-duplicate
  identity lose).
- Z-order and duplicate lineage play no part.
- TM2 and TD1, which looked like "identity wins", are explained by the raw-path tier: R and R2
  store different raw paths at their native size. AppleScript resizing rewrites the raw path to the
  new size, which is why TG1 and TZ have none.

**Checked against FX:** all six squares share one raw path (174×154).
- Tier 1 (opacity/stroke) sends green (op 0.29, no stroke) to ki 4, the only other op 0.29 shape.
- Tier 1 sends black (white stroke) to the slide-2 black.
- This matches the live result, even with ki 1–3 taking part.

**Not tested:** the order between stroke and opacity; shadow and reflection; groups; text
styling; whether tiers aggregate lexicographically in assignments with many objects (only 2-way
contests were measured).

## 3. Proposed change

1. **`mmKeys` = the gate key** (hard compatibility), replacing `_mm_shape_key`:
   - `bezierPathSource`: element types plus points normalised to the path's own bbox.
   - `scalarPathSource`: type, plus scalar except the rounded rect's radius (unmeasured for other
     presets).
   - `editableBezierPathSource`: nodes normalised to their bbox.
   - Lines: that key plus the resolved stroke (colour, width, pattern) and line ends.
   - Text shapes stay keyed by text; groups follow through `_mm_group_leaves`, whose line leaves
     use the line key.
   - Style lookups go through one small resolver next to `_path_source` that walks the style
     `parent` chain.
2. **`mmPrefs`** on the same slides: `{kind: {ki: [tier1, tier2, tier3]}}` for shapes and lines.
   - tier1 = digest of the resolved stroke and opacity;
   - tier2 = digest of the raw path source, excluding `naturalSize`;
   - tier3 = style id.
3. **Partner keeping (#224, D3 bucket semantics):** unchanged code. It keeps an off-canvas object
   when any compatible partner survives, so it inherits the gate key. Misses are fixed and extra
   keeps stay harmless. Proxy count of shapes with a possible partner:
   - Minimal Alpha_DSK 2 → 3 (the green FX case);
   - Gold 279 → 279 (no change);
   - FRC 300 → 305 (slide pairs 16→17, 56→57, 102→103, 130→131).
   The golden-plan capture before/after decides whether the golden changes.
4. **`mm.zorder_flip`:** remove the shape/line/shape-group exclusion.
   - Within each gate bucket, pair by the lexicographic assignment (tier mismatches, then total
     centre distance), generalising the zorder branch's media assignment.
   - Skip as ambiguous when the optimum is not unique.
   - Update the rule text in both SKILL.md files.
5. **Tests:**
   - one unit test per measured row in §2 (gate and tiers);
   - a fixture test pinning FX (black 1:0 ↔ 2:0, green 1:1 ↔ 2:4);
   - the full local suites.

### Quantifying (in the PR description)
- `scripts/golden_plan.py capture` on FRC and Gold, before and after, listing changed
  `mm_partners` rows and transforms. A golden re-baseline goes through `update` with the diff shown.
- `mm.zorder_flip` findings on Minimal Alpha_DSK, Gold and FRC, before and after (the shape rows
  are new). Spot-check any new FRC flag against Keynote playback or an export.
- The full local suites (pytest, `test:ui`, `test:maps`), per the no-CI rule.

## 3a. Status 2026-09-24 21:45 (WIP commit on `claude/mm-shape-identity`)
- Implemented: stream A (`iwa_runs.py`: gate key, line keys, text in shape key, `mmPrefs`) and stream B
  (`validate.py`: all keyed kinds; repeated classes pair only for image/movie/shape/line by tiers then
  distance; repeated text/groups skipped; both SKILL.md rows).
  - `test_iwa_runs` + `test_validate`: 148 passed, 2 skipped.
  - Minimal Alpha 1→2 now pairs black↔black and green↔big green.
- Golden plan:
  - Gold is unchanged (`a16046f1…`).
  - FRC `35002fee…` → `e621efe8…`: slide 16 keeps 7 off-canvas 16×16 shapes that now have a partner
    on slide 17.
  - Two tests fail until they are re-baselined: `test_golden_apply_plan_full_report_card_wall`, and
    `test_propose_auto_rects_match_apply_transforms`, whose hard-coded MM address list needs the 7.
- `mm.zorder_flip` on FRC goes from 22 → 53 flags (+31 new, 0 gone), on slide pairs 7, 8, 16, 56, 84,
  102 and 130. Shapes are labelled "shape #N", which may need a better label for operators.
  Minimal Alpha and Gold: 0.
- **Next** (after the Mac restart):
  1. Owner review of the 7 slide-16 keeps and the new flags; spot-check a few against Keynote playback.
  2. Re-baseline the golden plan and the propose/apply list.
  3. Run the full suites.
  4. Codex review.
  5. Open the PR.
- Evidence: `output/evidence/mm-shape-id/golden/` in the worktree holds the before/after captures and
  `zflags_*`.

## 3b. Status 2026-09-24 23:15 (commits 4821f566 and the build-exclusion commit)
- Owner decisions on 2026-09-24/25, after the FRC review:
  - **(b) Overlap filter:** flag an inverted pair only when the straight-line morph boxes overlap at
    some t, checked exactly per axis. Box-based, so the transparent areas of images count; this is
    an accepted false-positive source (FRC 16→17: the yellow map vs the Klang label, owner saw no
    snap).
  - **Builds:** objects that build in on the destination, or build out on the source, never pair
    (owner saw this live on 102→103). `movie-start` and Action builds don't exclude. Applied in
    BOTH `mm.zorder_flip` and partner keeping.
  - **Reviewer for this branch = Opus peer** (Codex quota is low).
- Cuts reviewed live on `<main>/output/evidence/mm-shape-id/review/FRC_review.key` (a Keynote-made copy;
  the FRC source sha1 was verified unchanged):
  - 7→8 and 8→9: invisible inversions (badge vs map), removed by the filter.
  - 16→17: pairing correct; the flags are box false positives.
  - **84→85: a real snap, confirmed** (the shrinking map covers the badge).
  - 102→103: explained by the build-ins.
- FRC flags: 22 before → 53 with shapes → 15 with the overlap filter → **11** with the build
  exclusion (16→17 ×6, 84→85 ×4, 130→131 ×1). Minimal Alpha and Gold: 0.
- Golden plan: FRC is still `e621efe8…`, and the build exclusion doesn't change it (the 7 keeps on
  slide 16 are the off-canvas dots). Gold is unchanged.
- **Next:**
  1. Review 130→131 ("Suntec New 2.png" vs "CHC").
  2. Re-baseline the golden plan, and the propose/apply MM address list in
     `test_propose_auto_rects_match_apply_transforms`.
  3. Run the full suites (pytest, `test:ui`, `test:maps`).
  4. Opus peer review.
  5. Open the PR.
  6. Afterwards, trash the review deck and `runs/`.
- Open questions from the implementer:
  - The partner row's `ambiguous` flag still counts objects excluded by builds.
  - The build-out rule is unobserved live (FRC slide 147 only).
  - One Action (blink) build on an MM slide still pairs.

## 4. Owner decisions (taken)

- **D1 — the palette deck.** (a) The owner hand-authors one slide of ~16 styled shapes to a spec I
  write (about 10 min; most faithful). (b) I derive it from a copy of Minimal Alpha_DSK plus
  theme styles, which covers fill/stroke/opacity but not rounded-rect or oval presets. (c) An
  offline IWA write of style refs (more code, and risky). **Recommend (a).**
- **D2 — sequencing with `mm.zorder_flip`.** It is uncommitted in another session's worktree.
  **Recommend:** that work lands first with shapes excluded, as already chosen, and this work
  follows as its own PR that re-enables shapes.
- **D3 — partner keeping with repeats.** (a) Keep bucket semantics: over-keeps an off-canvas object,
  which is harmless, and never misses. (b) Use the position assignment: exact, but it would have to
  run on the output geometry, which the planner does not have when it runs. **Recommend (a).**
- **D4 — Keynote slot.** About 30 minutes of exclusive Keynote across 2–3 batches, whenever you say
  Keynote is free.

## Harness status (2026-09-24)
- **Palette** (`<main>/output/evidence/mm-shape-id/palette.key`, owner-authored; used only via copies). One
  slide. Offline facts:
  - roles R, R2, OV, TRI, ED and RR10t all use the theme red style directly;
  - RR10v and RR60v share one variation with an identical resolved fill (the E5 pair is RR10v vs
    RR10t);
  - T and T2 are teal; RS4w, RSy and RS12 are outline variations;
  - L1 to L4 are lines, and L2 has an arrowhead.
  - Keynote merges identical variations: a shape drawn fresh with equal values reused the same
    style, and Paste Style snapped back to the theme style. So in real decks "same values, different
    style object" occurs mainly across parent styles.
- **Harness** (`<worktree>/output/evidence/mm-shape-id/`, gitignored):
  - `roles.py`: offline dump and palette contract;
  - `gen.py`: 50 variants, geometry lint, probe → asmap, batches;
  - `read.py`: max-over-frames midpoint coverage;
  - `synth_check.py`: renders every variant × outcome synthetically, and `read.py` recovers all of
    them (0 mismatches);
  - `run.sh`: pgrep refusal, deadline, never addresses Keynote from outside the batch.
- **Changes from §1:**
  - The FX replay is dropped. It would need an 833 MB copy and is already on record; the
    null/positive/base controls cover the instrument.
  - The tie-break set is redesigned for midpoint readability: TZ0–2, TD0–1, TM2, TG1/TG1b. It
    separates nearest, size, identity/z, greedy and optimal.
- **Live order:**
  1. `run.sh probe`, which maps AppleScript indices to roles.
  2. Batches 1–4 of 13 variants each, about 6 min per batch.
  3. `read.py`.
  4. An offline `roles.py runs/<name>.key` audit of the styles in each run deck.

## Review log
- 2026-09-24 owner: D1 (a) — the owner authors ONE palette deck (`output/evidence/mm-shape-id/palette.key`, spec in chat);
  D2 agreed — `mm.zorder_flip` lands first with shapes excluded; D3 (a) bucket semantics; D4 — the owner pings
  when Keynote is free.
- 2026-09-24 live run incident: Keynote's `save doc in <path>` saves a COPY and leaves the open document
  bound to the source, so the first pilot's edits were saved into `palette.key`. The per-deck checksum
  check caught it; the owner restored the palette (content identical, new sha1 `4cc76124…`). The harness
  now opens the palette, saves a copy, closes the palette without saving, opens the copy, asserts the
  open document's path, and re-checks the palette sha1 after every deck. Also: files written from this
  session get `com.apple.quarantine` with no owning app, which Keynote refuses to open ("Operation not
  permitted"), so every run copy is written by Keynote itself.

- 2026-09-25 Opus peer review (standing in for Codex; quota low): no blockers.
  - 1 major, fixed: the overlap filter and centres ignored rotation, and lines are stored horizontal
    plus a rotation. `_mm_box` now uses the drawn AABB.
  - 2 doc drifts, fixed.
  - Nits: group line leaves now use the line key; the plan's scalar-preset wording now matches the
    code; `ambiguous` counting before build exclusion is documented.
  - The overlap math was fuzz-checked exactly: 0 misses.
  - FRC flags stay at 11 and the golden plan is unchanged.
  - Full suites: pytest 7362 passed, `test:ui` 305, `test:maps` 542 + 2 perf, 0 failures.
- 2026-09-25 owner reviewed FRC 130→131 (the Suntec photo and the round CHC badge rising in parallel; the boxes overlap
  by 5 px only at t ≥ 0.96): a false positive from box overlap, accepted like 16→17.
