# GL-replay v1, stage G2 — the wrapper-opacity fix, without touching the player

DRAFT for owner review — rev 2, 2026-09-22 by Opus (read-only; no product code, no git, no Keynote).
Rev 2 folds the Fable peer review (`scratchpad/opacity/fable-review.md`, findings F-1…F-12) and the
re-measurements it forced. Parent: [`keynote_live_gl_replay_arming.plan.md`](keynote_live_gl_replay_arming.plan.md)
(owner answer D2). Prior: [`keynote_live_alternatives_research.md`](keynote_live_alternatives_research.md)
"Opacity disagreement" (~line 151), "P3" (~line 247).
Measurements for this plan (headless Chrome, fixture `output/p2-recovery/html-adversarial`, 1920×1080), all under
`…/scratchpad/opacity/`: offline `m1b_effect.log`, `m1c_slide2.log`, `m3b_anim.log`, `m4_settled.log`; in-page
`m2-s1/`, `m2-s2/`, `m2-s3/result.json` (3 sessions). **s1/s2/s3 are not byte-identical** — s1 lacks the
`writeback` row and s3 adds `remeasure`; the `analyze`, `ablate` and `patch` rows are identical across all three
(F-11).

## 0. Measured facts

**The animation format (F-1, `m3b_anim.log`).** Effect-tree `animations` are GROUPS
(`{additive, animations[], autoreverses, beginTime, duration, fillMode, removedOnCompletion, repeatCount,
timeOffset}`) wrapping leaf animations (`{property, from, to, fillMode, timingFunction, …}`), `from`/`to` being
`{scalar} | {pointX,pointY} | {texture}`. Properties present: `contents, hidden, opacity, transform.scale.x,
transform.scale.y, transform.translation, zPosition`. **My rev-1 dump read `keyPath`/`fromValue`/`toValue` — keys
the export does not use — and printed every animation as null. The reviewer is right; rev 1's "animated opacity
keyPath ⇒ refuse" rule would have refused this fixture.**

**Settled opacity (`m4_settled.log`).** Settled opacity of a node = `to` of its last `opacity` animation with
`fillMode ∈ {both, forwards}`, else `initialState.opacity`; product down the path. Slot 4 (green square): wrapper
`opacity` 1→1 **over** `initialState.opacity 0.29468628764152527`, leaf `opacity` 0.29468628764152527→same over
`initialState.opacity 1` ⇒ **product 0.294686288 == the leaf's `singleTextureOpacity` exactly**. (Rev 1 said
"wrapper 0.2947, leaf 1" — the *product* was right, the *location* was wrong.) Slot 1: leaf `opacity` 1→0
(`fillMode forwards`) then `hidden` true ⇒ product 0.0, `sto` 1 — and the player's measured rest `Opacity` for
that draw is **0**. Slots 0/2/3: product 1.0 == `sto`.

**The settle frame (`m2-s*/result.json`).** 88 calls, **exactly 5 draws** at indices 17, 33, 50, 66, 83, one
**distinct program each**; `Opacity` present via `getActiveUniform` on all five (uniforms:
`MVPMatrix, mixFactor, Opacity, Texture, Texture2`); rest values `1, 0, 1, 1, 1`. Draw order == effect-slot order.

**MVPMatrix decodes exactly (F-4 — rev 1's "not provable" was WRONG).** Under quad `(0,0)–(texW,texH)`, y up,
`m4_settled.log` compares the decode with the settled leaf rect computed offline (wrapper position + leaf
`transform.translation.to`, size × `transform.scale.{x,y}.to`): deltas **≤ 0.32 px on x, ≤ 0.15 px on y, 0.00 px on
w/h for all five draws** (green 789,673,353,313; movie 105,791,960,276). This is a zero-replay geometry check.

**Sampler binding (F-9, `m2-s3.remeasure.perUnit`).** Every draw binds **unit 0 = its own texture, unit 1 = the
shared texture 2**; samplers are `Texture → unit 1`, `Texture2 → unit 0`. `mixFactor` is **1 for draw 17 and 0 for
the other four** — so draw 17's visible texel comes from unit 1 (texture 2), not from the texture rev 1's
size-signature named. The signature must therefore be taken from the *sampler-visible* unit.

**Ablation footprints** (suppress one draw, diff the buffer on a 4-px grid; identical in all three sessions): draw
17 **empty**, draw 33 **empty** (its `Opacity` is 0), draw 50 `[544,720,180,72]`, draw 66 `[108,792,956,272]`,
draw 83 `[792,672,352,312]`. Against the *settled leaf rect* (not the wrapper rect and not slide 2's own tree) the
residual is the shape-path inset (`shapePath` of the green leaf runs 1.63…176.09 × 1.37…155.55 inside 178×157) plus
≤ 4 px of grid quantisation — **not** a 2 % geometry gap (F-3; rev 1's Rec 3 was derived against the wrong rect).

**The patch, non-circularly (F-6, `m2-s3.remeasure`).** Background **read directly** by ablating draw 83 at
(900,830): `(65,62,62)`. `uniform1f(Opacity, 0.29468…)` before draw 83 gives `(54,96,44)` =
`α·(29,177,0) + (1−α)·(65,62,62)` to the byte. **α = 0 identity control: patching with 0 gives a 500×420 region
byte-identical to suppressing the draw** (`alpha0EqualsAblation: true`, equal hashes) — the uniform and the
ablation provably address the same draw. `uniform1f(Opacity, 1.0)` restores `(29,177,0)` exactly.

**Stickiness is per program, and only where the frame does not set it (F-10, refined).** Sentinel test: write 0.5
to `Opacity` on all five programs, replay the frame, read back → `1, 0, 1, 1, **0.5**`. So the frame **does** set
`Opacity` for programs 0–3 and **does not** for program 4 — the green square's value is the sticky one, which is
exactly the program we patch. Write-back is therefore mandatory, and rev 1's blanket "Opacity is never set in the
frame" was an over-read of P3.

**Green ROI over vs off the movie (F-2).** Patched state, drawing-buffer values: the ROI the probe uses today
(`GREEN_AUTHORED` 900,820,100×20, inside the movie rect) has mean `(45,119,67)` with per-pixel spread 9…188 — it
**moves with the movie**. Two ROIs on the square but off the movie are **uniform** (min == max): top band
`(800,690,330×90)` and right strip `(1075,700,60×280)`, both `(29,177,0,255)` clean and `(9,52,0,75)` patched.

## 1. The mapping design

Fail-closed, structural, no minified `main.js` identifiers (`Opacity`/`MVPMatrix`/`mixFactor` are GLSL names read
back with `getActiveUniform`, so a renamed shader fails the assertion instead of mis-patching).

1. **Count + order.** `nDraws` == number of top-level slots of the boundary transition's `effects[0].baseLayer`
   (measured 5 == 5); the i-th draw maps to the i-th slot.
2. **Sampler-visible size signature.** For draw i, take the texture on the unit read by the sampler that
   `mixFactor` selects (`mixFactor == 1` ⇒ `Texture`/unit 1, `== 0` ⇒ `Texture2`/unit 0; anything strictly between
   ⇒ that draw is unproven, F-9), and require its last upload size == slot i's leaf `(width, height)`.
   **Duplicate-size granularity (review answer B):** the boundary is unproven only if a slot with `sto < 1` shares
   its size with another slot; duplicates among `sto == 1` slots are harmless because nobody patches them.
   Same-size candidates may still be resolved by layer 4 when exactly one candidate's rect matches.
3. **MVP geometry cross-check (zero replay).** `MVPMatrix · (0,0)–(texW,texH)` must equal the settled leaf rect
   (§0) within **1 px per edge** (measured worst case 0.32 px). Runs every ARM-POST for every draw.
4. **Ablation footprint**, for patched draws only, at qualification time and at ARM-POST: `readPixels` over the
   candidate settled leaf rect dilated by 8 px, require ≥ 80 % of the inset rect changed and **zero** changed
   pixels outside the dilation; tolerance on the bbox = **grid step + 2 px per edge, no percentage** (F-3). Its
   value is (i) proving the renderer paints where the export says and (ii) resolving same-size candidates — not
   identity, which layers 1–3 already fix.

## 2. Contract additions

**Offline (`live_continuity.py`, G1).** For a `glReplay` boundary, walk the transition effect tree; per slot compute
the **settled** opacity product (§0 rule) and require `product == leaf.singleTextureOpacity` within 1e-6. Emit:

```
{"atScene": N, "action": "glReplay", "movieKey": K, "fallback": "retire",
 "slotSizes": [[1920,1080],[671,195],[266,236],[960,276],[178,157]],
 "slotRects": [ …settled leaf rect per slot… ],
 "opacityOverrides": [{"slot": 4, "opacity": 0.29468628764152527, "texW": 178, "texH": 157}]}
```

A slot gets an override only when `sto < 1 − 1e-6`. A slot is **excluded** (no override, note only) when any
`opacity` animation on its path has `from ≠ to` (a real fade the player animates itself — slot 1), when a `hidden`
animation is present, or when product ≠ `sto`. `opacityOverrides` is always present, possibly `[]`.

**Runtime (`live_gl_replay_js.py`, G2).** At ARM-POST: assert §1.1–§1.3 for all draws and §1.4 for patched ones;
assert `Opacity` is an active uniform of the program; and (F-5) **assert the player's rest `Opacity` for that draw
is exactly 1.0** — anything else means the player already applied some opacity of its own and `sto` is not a safe
override ⇒ `glreplay-opacity-unproven{slot, reason:"rest-opacity"}`. Capture `progOpacityBefore[i]` for every draw.
In LIVE: `uniform1f(loc_i, override_i)` inside the `replaying` counter, immediately before draw i, on every replay
(idempotent; issued after the frame's own `uniform1f` where one exists).
Stand-down write-back: restore `progOpacityBefore` for every touched program. Ordering (F-12, review answer E) —
on the `#0-canvas`-removal path nothing reads the old context again, so order vs the poster restore is free; on a
**LIVE-guard stand-down caused by an unflagged player call on the same context, the write-back must run inside the
wrapper BEFORE that call is forwarded**. On `contextLost` the write-back is **exempt** (assert `isContextLost()`
instead of a failed `uniform1f`); any other failure is a hard `glreplay-standdown` reason.

**Never refuse.** Any §1 failure drops that slot's override, replays the player's opaque look, and emits
`glreplay-opacity-unproven{slot, reason}` as a presenter note. Per-slot granularity. The carry is never refused for
an opacity reason.

**Versions.** `slotSizes`/`slotRects`/`opacityOverrides` change the runtime JSON ⇒ `QUALIFIED_PLAN_SHA256` is
**replaced** with the P2 injected plan and the pinned literal in one commit. `CONTINUITY_VERSION` is untouched here
(G3 owns 4→5). `GL_REPLAY_VERSION` + its `js_sha256` move in this stage.

## 3. Gates

- **Blend exactness, non-circular (F-6).** All of it on the **poster state at ARM-POST**, never over a live
  texture: (i) read the background by ablating the patched draw and assert
  `patched == α·clean + (1−α)·ablated` per channel (measured `(54,96,44)` from `(29,177,0)`, `(65,62,62)`,
  α = 0.29468628764152527); (ii) **α = 0 identity control** — patching with 0 must be byte-identical to suppressing
  the draw (measured true), which is also the negative control for "wrong slot"; (iii) α = 1 restores `(29,177,0)`.
  The slide-1 DOM cross-check of rev 1 is **dropped** — the reviewer is right that it isolates nothing.
- **The green-static rule CHANGES (F-2).** Rev 1 claimed Finding 2 survives untouched; measurement says the
  opposite. Over a live movie the patched square varies with `(1−α) = 0.705` of the grating's band range
  (measured spread 9…188 in the current ROI) and `score_inpage_liveness`'s `INPAGE_GREEN_STATIC_MAX = 1.0` would
  score the slide DEAD. **Adopt Alternative A:** move the green ROI onto the part of the square that is *not* over
  the movie. Numerically, square settled rect 789…1142 × 673…986, movie 105…1065 × 791…1067 ⇒
  **`GREEN_AUTHORED = {x: 800, y: 690, w: 330, h: 90}`** (top band; measured uniform, min == max), with
  `{x: 1075, y: 700, w: 60, h: 280}` (right strip) as the alternate for decks whose movie sits above. Caveat for
  O4: those numbers are *premultiplied drawing-buffer* values `(9,52,0,α75)`; the still-green margins the screenshot
  oracle sees depend on compositing over the page background and must be re-measured before the constant lands.
  Alternative B (plan-derived expectation) is rejected for v1: it touches the frozen scorer thresholds.
- **Null control** (`opacityOverrides == []` ⇒ pixels byte-identical to the un-patched armed run), **write-back
  control** (post-stand-down replay reads `(29,177,0)`, every program back to `progOpacityBefore`).
- `BLACK_BEHIND_ROI` is re-confirmed, never re-tuned. The occluder mask **will change** once the occluder is
  translucent — 20/128 must be re-measured, not asserted equal. Two oracles + three viewports carry over;
  **viewport coverage is waivable with a stated reason** (the canvas backing store is 1920×1080 at every viewport,
  research doc ~line 187), so the opacity numbers do not need re-measuring per viewport.

## 4. Work split (disjoint files, mapped onto G1–G6)

`src/obed_edom/live_gl_replay_js.py` **does not exist yet**; nothing in §2's runtime half can land before
G2-the-module's wrapper/recorder/loop skeleton. Buildable now: O0, O1.

| Item | G | Files | Tests |
|---|---|---|---|
| **O0** second measured vocabulary for the effect tree (F-8): the animation group/leaf keys, `property` values and `from`/`to` variants of §0, alongside `_MOVIE_SUBTREE_KEYS`, with its own "nothing-more" test in this module's style | **G1** | `src/obed_edom/live_continuity.py` | extend `test_the_measured_vocabulary_is_the_real_exports_and_nothing_more`, add `::test_effect_tree_vocabulary_is_closed` |
| **O1** settled-opacity product, `sto` cross-check, `slotSizes`/`slotRects`/`opacityOverrides`, fade/`hidden` exclusions, duplicate-size rule, new allowlist sha | **G1** | same file | `::test_gl_replay_opacity_overrides_from_export`, `::test_faded_slot_is_excluded_not_refused`, `::test_settled_product_must_equal_single_texture_opacity`, `::test_duplicate_size_only_blocks_patched_slots`; extend the existing `test_to_runtime_matches_p2_injected_plan` / `test_only_p2_measured_plans_are_qualified` (rev 1 invented a test name that does not exist) |
| **O2** ARM-POST proofs (count/order, sampler-visible size, MVP decode, ablation), rest-`Opacity == 1.0` precondition, per-draw `uniform1f`, `progOpacityBefore`, write-back incl. the LIVE-guard ordering and the `contextLost` exemption, unproven notes, `GL_REPLAY_VERSION` | **G2** | `src/obed_edom/live_gl_replay_js.py` (new) | `tests/test_live_gl_replay_js.py::test_override_applied_before_mapped_draw`, `::test_rest_opacity_not_one_is_unproven`, `::test_mixfactor_between_zero_and_one_is_unproven`, `::test_mvp_decode_must_match_settled_rect`, `::test_writeback_precedes_forwarded_player_call`, `::test_context_lost_exempts_writeback`, `::test_unproven_slot_replays_opaque_and_notes` |
| **O3** presenter-note channel for `glreplay-opacity-unproven` — **`live_host.py` reads no notes today**, so this is new plumbing, not a field rename | **G4** | `src/obed_edom/live_host.py` | `tests/test_live_host.py::test_gl_replay_opacity_note_surfaced` |
| **O4** green-ROI relocation (§3) in the probe **and** in the arming module's `sample()`, blend/identity/write-back controls, occluder-mask re-measure | **G5** | `scripts/live_continuity_probe.py`, `src/obed_edom/html_alpha_probe.py` | `tests/test_live_continuity_probe.py::test_green_roi_is_off_the_movie_rect` |
| **O5** P2 arm: patched green value, restored value after stand-down | **G6** | `scripts/p2_recovery_html_adversarial.py` | existing P2 assertions |
| **O6** Q1-CEF extension: ARM-POST ablation + MVP-decode cost in OBS CEF (no table row owned this in rev 1) | **G0** | scratch only | — |

**Do NOT touch:** the player's `main.js`; `output/p2-recovery/html-adversarial/html-player/**`;
`output/gate-runner-archive/**` (copy to scratch to run); `src/obed_edom/live_continuity_js.py`;
`CONTINUITY_VERSION`; `BURST_OFFSETS_MS`/A12; `BLACK_BEHIND_ROI` and every existing threshold incl.
`INPAGE_GREEN_STATIC_MAX`; `scripts/p2_recovery_html_adversarial.py` until the freeze-control PR merges.

## 5. Owner decisions

1. **Blend-exactness reference.** *Recommendation: the arithmetic reference over a **directly read** background,
   plus the α = 0 identity control; drop the slide-1 DOM cross-check.* Both are measured
   (`m2-s3.remeasure`: background `(65,62,62)`, identity byte-equal). The DOM cross-check isolates nothing —
   slide 1's square also straddles the movie, and the DOM path's fidelity to α was already settled by code-read.
2. **Patched-vs-player divergence on air.** *Recommendation: patch.* **Correction to rev 1:** the patch **removes**
   a pop, it does not create one. Today the GL-settled square is opaque and the DOM tree that returns at build 1 is
   translucent (research doc pooled-decoder caveat 3) — an opaque→translucent pop. Patched, GL matches DOM and the
   boundary is continuous. The cost is only that our replay is deliberately *more faithful to the deck than the
   player is*, which the capability report must state.
3. **Footprint tolerance.** *Recommendation: reference = the settled leaf rect; MVP decode within **1 px**;
   ablation bbox within **grid step + 2 px**, no percentage.* Rev 1's "2 % + 4 px" was derived against the wrong
   reference and would let a 19-px-wider object pass on a 960-px slot. Measured support: MVP deltas ≤ 0.32 px.
4. **Additive vs gating.** *Recommendation: additive — `OBED_LIVE_GL_REPLAY` stays the single switch and
   `opacityOverrides == []` is a first-class state.* Unchanged from rev 1; the reviewer agrees.
5. **NEW — green-ROI relocation is a probe-contract change.** *Recommendation: approve Alternative A
   (`GREEN_AUTHORED = 800,690,330×90`), re-running the E0/A12 controls, rather than touching
   `INPAGE_GREEN_STATIC_MAX`.* Without it the patched slide scores DEAD in the in-page oracle. The alternative —
   making the green assertion a plan-derived expectation — is stronger but edits frozen thresholds, which the
   parent plan forbids.

## 6. Risks

1. **The mapping rests on a player-internal frame structure**: 5 draws ↔ 5 slots, one program per draw, measured on
   ONE boundary of ONE deck in 3 sessions. A player update that batches draws breaks it — caught by §1.1–1.2 and
   degraded to opaque + a note. Parent §8 risk (4) applies in full.
2. **Coverage holes that are not correctness holes** (review answer A): a slot with two textured leaves, a hidden
   slot the player skips, or a draw whose `mixFactor` is strictly between 0 and 1 ⇒ count/signature mismatch ⇒
   unproven. And a boundary *sourced from slide 2* gets nothing from layer 2: its green square (353×313) duplicates
   slot 4's size (`m1c_slide2.log`), so only layer 4 could disambiguate it, by position.
3. **`Opacity` is sticky exactly where it matters** — the frame sets it for programs 0–3 but **not** for program 4
   (sentinel measurement). A missed write-back leaves the green square translucent in the player's own later frames
   on the same context; hence the LIVE-guard ordering rule and the `contextLost` exemption.
4. **The occluder mask's meaning changes** once the occluder is translucent; 20/128 (headless and CEF) is no longer
   the right number and a gate asserting it will go red for the right reason in the wrong place.
5. **Unmeasured:** OBS CEF for everything in §0 (O6 owns it; a replay already costs 6.9–7.5 ms p50 there), any
   second deck or boundary, and the *composited* (non-premultiplied) green-ROI values the screenshot oracle will
   read (§3 caveat).
6. **Draws 17 and 33 have empty ablation footprints.** Draw 33 is explained (rest `Opacity` 0, settled product 0.0
   from a real fade). Draw 17 is the full-stage background with `mixFactor 1`, reading the shared texture 2, and
   still changes nothing — unexplained. Both carry `sto == 1` so nothing is patched there, but an unexplained draw
   inside a frame we replay is a standing caveat.
