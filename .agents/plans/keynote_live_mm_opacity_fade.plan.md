# Magic Move: a leaf fade under a translucent wrapper ends at the authored opacity

**APPROVED (owner, 2026-10-13); IMPLEMENTED on `claude/mm-fade-opacity`; gates `.agents/reviews/mm-fade/gates-r1.md` (PF-4 owner eyeball owed).** Rev 5. Rev 1: Opus 5.5. Revs 2–3 and 5 fold Codex GPT-6 Astra (high) critiques r1–r3 (§6). Rev 4 widens scope to fade-outs and partial fades (owner, 2026-10-13); gate approved (owner). Plan only. No product code yet. Builds on `keynote_live_mm_opacity.plan.md`
(merged #233). This plan closes that plan's accepted residual (decision 5: "fades under a translucent constant wrapper keep
today's look (none on disk)"). The owner's deck now has them.

## 1. Finding (owner, Stage T G4, 2026-10-13; reproduced headless)

- **Owner's report.** Alpha_DSK, Chrome screen output, continuity off. On the move from the one-video slide to the
  two-video slide, the **Children's Church** tag box darkens mid-move.
  - That move is export slides 7→8; the owner's "8→9" was a different count.
- **Export encoding** (G4 export, `02FF…` 7→8, slot 4):

  | Node | `initialState.opacity` | Opacity animation |
  |---|---|---|
  | Wrapper | 0.6118 | none |
  | Leaf (`CE49…`, opaque black rounded rect) | 1, `hidden` | 0 → 1 from 1.00005 s for 0.49995 s, `both`; plus a `hidden` animation |

  - Keynote's value is 0.6118 × (0 → 1), so the box ends at **0.6118**.
- **What the patched player does.** The leaf is "unexpressible" (a from ≠ to animation and a `hidden` animation), so its
  whole subtree keeps the stock arithmetic: T = lerp(0, 1) × root 1. The box ramps to **α 1** (solid black) between 1.0 and
  1.5 s. The page then shows it at 0.61 at hand-back, so it pops lighter.
- **Measured** (headless `LiveOutputHost`, G4 export, GL replay off, continuity off): the canvas was read before and after
  each draw, α_eff = 1 − P/B.

  | Slot | Patch on (today) | Patch off (stock) |
  |---|---|---|
  | 7→8 slot 4 | 0 → 0.552 → 0.942 → **1.000** at settle | the same ramp to 1.000 |
  | 7→8 slot 6 (the moving Sunday Service box) | 0.612 on every frame | 1.000 |

  - Probes and raw records: session scratchpad (`probe/pill_alpha.py`, `runs/f78`).
- **Ruled out on 8→9 and the 9→10 dissolve:** in-GL α is 0.6116–0.6118 on every frame for every box, there is no page
  copy above the canvas, and the move edges and hand-back are clean.
- **Census** (offline mirror of the node rule; 30 distinct Magic Move effects: every export under the main checkout's
  `output/` plus the G4 export). The case (a textured leaf that is unexpressible while its ancestor product is constant
  and ≠ 1) occurs **only in Alpha_DSK**:
  - 6→7 slot 3 (a tag box fading in);
  - 7→8 slots 4 and 8. Slot 8 ends over the black background, so it is invisible either way.

## 2. Fix (two edits inside `_MM_OPACITY_REPLACEMENTS`, same `mm_opacity` switch)

- **Player arithmetic** (`renderFrameWithContext`, main.js byte 2190397):
  `var T=i.hidden?0:e.parentOpacity*i.opacity; … d!==U&&(T=d+(U-d)*K)`.
  - The animation loop has no `hidden` case, and an unequal-endpoint lerp overwrites the hidden 0.
  - For the observed encoding this is still right:
    - before `beginTime`, K = 0 and `from` is 0;
    - during the fade, T is the eased animated value;
    - at settle, T = `to` = 1.
  - Multiplying T by the constant ancestor product supplies the missing factor.
- **Scope (owner, 2026-10-13):** every leaf fade under constant translucent ancestors: fade-ins (on disk), fade-outs and
  partial fades (none on disk under a translucent parent). Wrapper fades, multiple opacity animations, other fill modes
  and roots ≠ 1 stay on today's arithmetic until encountered.
- **Keynote's leaf-fade encodings on disk** (survey of all 30 Magic Moves; every one is a single ordinary
  `animations[0].animations` group with one `opacity` animation):

  | Shape | Opacity | `initialState.hidden` | `hidden` animation | Count |
  |---|---|---|---|---|
  | fade-in | 0→1 `both`, 1.0 s + 0.5 s | true | false→false `forwards`, same interval | 29 (+3 with a constant `transform.rotation.z`) |
  | fade-out | 1→0 `forwards`, 0 s + 0.5 s | false | true→true `forwards` from the fade's end (0.5 s + 1.0 s) | 25 |
  | fade-out over the move | 1→0 `forwards`, 0 s + 1.5 s | false | true→true `forwards`, 1.498 s + 0.002 s | 5 |

  Clause (b) below admits the 25 short fade-outs. The five full-move fade-outs hide 1.5 ms before opacity reaches
  zero, so they stay unchanged. For correctly timed animations:
  - `both` supplies `from` before onset;
  - `forwards` matches the model value before onset, because admission requires model opacity equal to `from`;
  - both keep `to` after completion.
- **Admission is resolved at setup, in R1, on the source layer** (`__obedFade(A)`, a `fB` method next to
  `__obedNodeOpacity`). It admits a leaf when all of the following hold:
  - exactly one ordinary `animations[0].animations` group. Flat lists, additional top-level groups and deeper grouping
    stay outside this extension: the player reads `e.animations[0].animations` (byte 2189776). Do not add animation
    normalization;
  - exactly one `opacity` animation, from ≠ to, both finite in [0, 1], with `fillMode` `both` or `forwards`; for
    `forwards`, `initialState.opacity === from`;
  - the leaf's `hidden` state is one of:
    - (a) `initialState.hidden` false and no `hidden` animation;
    - (b) `initialState.hidden` false, `to` 0, and one true→true `forwards` `hidden` animation beginning at or after the
      fade's end (within 1e-9). The fade-out shapes;
    - (c) `initialState.hidden` true, `from` 0, and one false→false `forwards` `hidden` animation over the fade
      interval: same `beginTime`, duration within 1e-9. The fade-in shape. `QB` ignores hidden animations, so (b) and
      (c) are admitted only where the player's lerp already coincides with Keynote's visibility;
  - `beginTime === 0` whenever the opacity animation's duration equals the effect's duration. The player
    (`QB`) uses interval-relative K only when `effectDuration !== 1000 * duration`, and otherwise uses the whole-effect
    eased progress and ignores `beginTime`; it never consults `fillMode`. Otherwise today's arithmetic is kept. This is
    resolved at setup; the player's progress calculation is not modified;
  - other animated properties (transform, `contents`) are allowed: they do not enter the Opacity arithmetic.

- **R1** stores the ancestor product X on the leaf as `e.obedParentOpacity`, only for admitted leaves; otherwise it stores
  null. X is null when any ancestor is unexpressible, and undefined at the root.
- **R3** keeps the existing absolute override. When `obedOpacity` is null, `obedParentOpacity` is non-null and
  `e.parentOpacity===1`, it multiplies T by the stored factor:
  ```
  null!=e.obedOpacity ? T = e.obedOpacity : null!=e.obedParentOpacity && 1===e.parentOpacity && (T *= e.obedParentOpacity)
  ```
  - R3 calls no admission helper.
  - `e` is `g.textureInfo` (byte 2189505), the object R1 built.
- **`1===e.parentOpacity`** is a conservative guard: the non-lerp branch includes the root value, while the lerp branch
  replaces it. The root is 1 in every export on disk; supporting other roots would need a broader argument.
- **Blast radius.** Exactly three existing exported leaves change rendered opacity: 6→7/3, 7→8/4 and 7→8/8. Additional
  admitted leaves (the 25 short fade-outs and the fade-ins, all under ancestor product 1) stay numerically unchanged.
- **Unchanged, inherited paths.** Keep `parentOpacity`, R4, R6/R7 and uniform-cache behaviour unchanged.
  - The three new leaves cannot acquire `obedMix`: R6 rejects unequal opacity endpoints and hidden animations
    (`live_runtime.py:43–48`), and R7 changes only texture selection.
  - Unchanged leaves keep identical proposed Opacity values; nothing reads the local `T` after its Opacity write.
  - Existing composition, pin and hand-back tests cover these inherited paths. No new cache machinery or OBS
    qualification is required.
- **Pins and versions.** Re-pin `SUPPORTED_PLAYERS` (on and rendering) for both stock shas; `off` stays byte-identical.
  `RUNTIME_VERSION` stays 2.
- **Continuity on (G2).** This fixture emits no `glReplay` boundary today: both affected effects fail
  `effect_opacity_overrides` (initially hidden leaves, `live_continuity.py:331`), and fades are excluded from overrides
  (`:619`). So no G2 opacity notes are expected.
  - Verify the corrected fade and hand-back with continuity enabled (PF-2).
  - Keep the existing P2 G2 regression gates and their current expectations; do not extend G2 admission.
  - In admitted G2 sessions, slots without overrides replay their captured rest opacity.

## 3. Gate

Any missing onset, interior or settle evidence makes a run INCONCLUSIVE, never PASS.

| Gate | Pass | Known-bad (must FAIL) | Null / CvC |
|---|---|---|---|
| **PF-0 Node behavioural** (blocking, offline) | the extracted-method test, extended with the 7→8 slot 4 effect and two derived variants of it: a fade-out (the leaf's initial visibility and opacity/`hidden` animations copied from the 25-count short shape) sampled at onset, interior, completion and settle (pre-onset is not applicable), and a partial variant defined as visible, no `hidden` animation, `forwards`, model/from 0.3, to 0.8, begin 0.5 s, duration 0.5 s, sampled at 0.25/0.5/0.75/1.0/1.5 s, expecting ancestor × 0.3/0.3/0.55/0.8/0.8 under the existing linear easing stub. All assert explicit values as well as mirror agreement. Refused variants stay at today's value: a model/from mismatch, a `hidden` animation not paired with the fade, the full-move fade-out shape, and a full-duration animation with `beginTime` > 0. These stay cases in the existing behavioural test; no new harness | today's patch: fade-in settles at 1, fade-out starts at 1 | stock vs stock identical |
| **PF-1 headless Opacity** (blocking; `alpha-dsk-textures` fixture copy; 1920; GL off; continuity off) | the innermost logger records the Opacity in effect at every draw (cached values included) against the player's progress: 7→8 slot 4 and 6→7 slot 3 follow 0.6118 × the stock ramp at the same progress within 0.002; slot 6 stays 0.6118; on a second scratch copy whose 7→8 slot 4 leaf gets the actual short fade-out's initial visibility and opacity/`hidden` animations (keeping its translucent ancestor), current and candidate players run against identical edited data: the candidate reads 0.6118 at onset and follows 0.6118 × the ramp, and both settle at 0. The settle pixel and hand-back checks apply to the original fade-in fixture only (the edited copy's destination slide is untouched); the settle pixel check reads α_eff 0.612 ± 0.003 | today's `main`: fade-in ramps to 1 (settle α 1.000); edited fade-out reads 1 vs 0.6118 at onset | fixed vs fixed compared directly at matched progress (no extra multiplier) within 0.002 |
| **PF-2 blast radius** (blocking) | (a) offline: compare today's rendering patch with the extension, keyed by effect fingerprint and textured-leaf ordinal, over every export under `output/` and all `EB_EFFECTS`; the changed set is exactly {6→7/3, 7→8/4, 7→8/8}; the zero shimmer/sparkle census is recorded explicitly; the existing stock-versus-patched expectations are kept separately. (b) re-run `mm_opacity_probe` (MO-1/MO-5) and `mm_handback_probe` (HB-1/HB-2) green. (c) one headless continuity-on pass on the fixture: 7→8 fades to 0.612 with no pop at hand-back | (a) the stock and today's patch reproduce the old expectations | (b) as in those gates |
| **PF-3 suites** (blocking) | full `pytest` + `npm run test:ui` + `npm run test:maps`, Python 3.10 floor | | |
| **PF-4 owner eyeball** (blocking) | Chrome screen output, 6→7 and 7→8: the box fades in to the same tone it rests at, with no pop at hand-back | | |
| **PF-4b owner eyeball, fade-out** (optional, owner decision 3) | a Q-deck the owner authors (one translucent box fading out across a Magic Move): no pop to solid at the move start | | |

## 4. Work and review

- **One stream:** `src/obed_edom/live_runtime.py` (R1/R3 + `__obedFade` + pins) and `tests/test_live_runtime.py`; PF-1 reuses `scripts/mm_opacity_probe.py`'s innermost logger pattern in a scratch driver.
  - Tests: anchor and pin tests as today; extend the census mirror and the Node behavioural test with the 7→8 slot 4
    effect, committed as a small fixture. Minimal new tests.
- **Roster** (2026-10-13 → 10-27 override): Codex GPT-5.6 Sol high implements, Opus 5.5 high reviews. Coordinator runs
  PF-1/PF-2 headless (one Chrome, announced to peers), then the owner runs PF-4.

## 5. Owner decisions

1. **Scope: ANSWERED** (owner, 2026-10-13): leaf fade-ins, fade-outs and partial fades under constant translucent
   ancestors. Wrapper fades and the other edge encodings wait until encountered.
2. **Gate: APPROVED** (owner, 2026-10-13): PF-0–PF-4, no OBS take.
3. **Fade-out eyeball.** No fade-out under a translucent parent exists on disk, so PF-0/PF-1 cover it on derived
   data only. **ANSWERED** (owner, 2026-10-13): derived-data gate now; the owner authors the Q-deck later, and PF-4b runs then (it does not block this PR).

## 6. Critique log

- **r1, Codex GPT-6 Astra high, 2026-10-13:** 1 blocker, 3 medium, 2 low; all folded.
  - Blocker: the G2 expectation was impossible (no `glReplay` boundary on this fixture). Replaced with the continuity-on
    check in PF-2(c).
  - Medium: admission narrowed to the observed 0→1 `both` encoding, because a constant opacity plus a `hidden`
    animation would have been wrongly admitted.
  - Medium: PF-0/PF-1 now check the ramp (onset, interior, settle) on per-draw Opacity, not only the settle pixel.
  - Medium: PF-2 is incremental (today's patch vs the extension), keyed by effect fingerprint.
  - Low: admission is resolved in R1, and R3 calls no helper.
  - Low: the inherited paths that stay unchanged are documented.
  - Astra reproduced the census: 30 distinct moves, 0 shimmer/sparkle, the same three candidates.
- **r2, Codex GPT-6 Astra high, 2026-10-13:** r1 findings 1, 4, 5 and 6 correctly folded, and 3's setup placement
  confirmed. Two findings (1 medium, 1 low), both folded:
  - Medium: the `hidden` animation must pair with the fade: `forwards`, same interval.
  - Low: flat animation lists are dropped, since the player reads only `animations[0].animations`.
  - Re-confirmed: 30 moves, 0 shimmer/sparkle, the three candidates, and no `glReplay` boundary.
- **r3, Codex GPT-6 Astra high, 2026-10-13 (final round):** 1 major, 3 medium, 1 low; all folded.
  - Major: admission now requires `beginTime` 0 when the animation spans the effect, because the player then ignores
    `beginTime`. Astra reproduced the error with the extracted method: 0.2345 vs 0.1835.
  - Medium: clause (b) covers the 25 short fade-outs only; the 5 full-move fade-outs stay unchanged. The "from = model"
    wording is corrected.
  - Medium: PF-0 samples and the partial variant are concrete.
  - Medium: PF-1's derived fade-out has its own known-bad (onset 1 vs 0.6118), shares data between current and
    candidate, and the fixed-vs-fixed control applies no extra multiplier.
  - Low: confirmed 30 moves, 0 shimmer/sparkle, 25 clause-(b) and 32 clause-(c) admissions, and that the three-leaf
    change set and the round-2 restrictions hold.
