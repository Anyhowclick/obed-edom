# Alpha Keynote continuity: boundary scoping and transition-record pairing

Planner: Codex GPT-6 Astra (high), 2026-10-14. Critique r1: Opus 5.5 (high), folded in §13 — §13 wins where it conflicts with §1–12.

Baseline: `5b09b379`, branch `claude/deck-refusal-rules-alpha-1686c7`. This is a read-only planning deliverable; no files were changed.

## 1. Scope and acceptance criteria

Implement both fixes in one PR:

1. Replace the deck-wide multiple-bridge refusal with refusals confined to that boundary.
2. Replace distance-based Magic Move pairing with validated evidence from the exported transition.

Keep runtime JavaScript, runtime schema, load-time rules, GL replay admission, R4/R9/R10/R11 policy, and all integrity guards unchanged. Preserve `overlap`, the carried instance’s own build exclusion, R7, and R8. Movies cannot be masked in Keynote; this work adds no mask support.

“Never relax a refusal to qualify a deck” remains binding. Fix 1 changes the scope of an existing limitation. Fix 2 replaces an inference with Keynote’s recorded correspondence; missing or ambiguous evidence still refuses.

Acceptance requires:

- Every gate runtime plan remains byte-identical, with existing SHA constants unchanged.
- Every new or changed active refusal code has negative-corpus coverage.
- Refusals are applied before computing the next boundary’s held instances.
- R6 passes on the final runtime entries.
- No JavaScript bytes change.

## 2. Verified current state

| Area | Current behavior and evidence |
|---|---|
| Pairing | `_pair_instances` enumerates minimum-total-centre-distance assignments. It refuses repeated assets for any relevant build, opacity differences, more than 5,040 assignments, or a runner-up within 16 px. [live_continuity.py:1477](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1477) |
| Individual correctness rules | `_carry_refusal` checks R7, R8, attributed and unattributed R2, R9, R4, then destination overlap. [live_continuity.py:1725](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1725) |
| Multiple bridges | `_magic_move_movies` counts bridges still eligible after individual refusals, then raises `_Refuse` when more than one remains. `derive_plan` converts that exception to deck-wide `Unsupported`. [live_continuity.py:1815](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1815), [live_continuity.py:1933](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1933) |
| Refusal translation | A refused movie without GL replay already translates to `retire`, `reason: "refused"`, with a source and no destination. [live_continuity.py:844](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:844) |
| Held state and R6 | `_held_after` includes only admitted carries. `derive_plan` calls it immediately after planning each boundary. `_chain_refusal` subsequently checks final runtime entries. [live_continuity.py:1843](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1843), [live_continuity.py:912](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:912) |
| Transition slot lookup | `_bridge_slot_chain` finds exactly one top-level slot whose starting rect matches `src.layer_rect` within 0.5 px. It deliberately does not use draw-order indexes. [live_continuity.py:1555](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1555) |
| GL replay | Admission requires exactly one structural continuing pair, an overlap-refused pin, a measured transition, and the existing remaining checks. Refusing other bridges must not reduce this admission count. [live_continuity.py:1514](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity.py:1514) |
| Runtime multiplicity | Core lookup and motion are keyed by instance and entry; motion state belongs to each decoder. There is no single boundary-wide bridge variable in this path. [live_continuity_js.py:399](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity_js.py:399), [live_continuity_js.py:1192](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/src/obed_edom/live_continuity_js.py:1192) |
| Pin plus bridge | This is already exercised by D3 and explicitly tested in `test_d3_carries_two_movies_at_one_boundary_by_instance`. Keep supporting it. [test_live_continuity_js.py:4829](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity_js.py:4829) |

The older plan documents the distance assumptions and “extended, never relaxed” contract. This document supersedes its pairing algorithm and multiple-bridge refusal scope, not its correctness rules. [generalisation plan:134](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/.agents/plans/keynote_live_continuity_generalisation.plan.md:134)

The regression contract requires unchanged gate signatures and a negative corpus for emitted refusal codes. The corpus also checks code coverage mechanically. [SKILL.md:706](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/.agents/skills/obed-edom/SKILL.md:706), [test_live_continuity_corpus.py:183](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity_corpus.py:183)

## 3. Independently checked export evidence

I re-read the supplied exports and ran read-only Python probes against their JSON, rather than relying on the coordinator’s summary.

Across D1–D6, D2-across, both GL decks, p2-binary and p2-loop:

- All measured Magic Move names are `apple:magic-move-implied-motion-path`.
- The 43 source movie observations comprise 31 non-fading correspondences, 10 outgoing fades, and two ambiguous stacked sources.
- Every source has one starting slot except Minimal Alpha_DSK player boundary **7→8**: both stacked sources match slots `[1, 2]`.
- Outgoing movie fades carry opacity `1→0`; these also have a `hidden` animation. The fade classifier must accommodate that measured companion.
- D5’s incoming-only movies have separate opacity `0→1` slots.
- No supplied boundary has an attributed movie build-in/out. The attributed destination builds inspected in P2 are artwork: their objects occur in destination draw slots but have no matching transition landing. Do not claim these fixtures empirically prove a movie-build export shape.

A useful correction to the proposed geometry shortcut:

| Comparison | Observed maximum error |
|---|---:|
| Source movie-layer centre + translation versus destination movie-layer centre | 0.611080 px |
| Source movie-layer dimensions × scale versus destination movie-layer dimensions | 2.092654 px |
| Composed transition textured-leaf endpoint versus destination textured draw leaf | 0 px in all 31 readable correspondences |

The final comparison also agreed on texture identity in every case. It accounts for padding and anchors instead of widening authored-rectangle tolerances.

A read-only, in-memory pairing experiment using those correspondences preserved runtime dictionaries for all 11 exports with GL replay both off and on. Only Minimal Alpha_DSK’s two R1 reasons changed. This establishes feasibility; it is not a substitute for the implementation’s validated parser and tests.

## 4. Fix 1: refuse multiple bridges at their boundary

### Decision

Introduce **R12: more than one otherwise admissible bridge at one boundary**.

Use a distinct code because this is a concurrency limitation, not uncertain pairing, bad motion timing, or an unmeasured movie shape.

Keep the existing trigger: count only bridges that would actually carry after individual refusals. If that count exceeds one:

- Refuse **every otherwise admissible bridge** at that boundary with R12.
- Preserve any bridge’s earlier refusal and code; it already retires.
- Keep independently admissible pins.
- Do not choose one bridge by asset order, source order, size, or proximity.
- Leave other boundaries untouched, apart from necessary held-state consequences.

Thus all bridges at the offending boundary retire, while existing specific reasons remain useful.

### Placement and representation

Replace the final raise in `_magic_move_movies` with a final boundary-local transformation.

Retain each movie’s structural `action="bridge"` and source/destination metadata internally, as existing refused bridges do. Set `refusal` and `code="R12"`; ensure no GL replay attachment remains. With GL replay requested, set the explanatory `gl_replay_reason` consistently with other non-overlap refusals.

`_runtime_entry` then emits the existing `retire refused` representation. No serializer or schema change is needed.

### Pins and GL replay

Keep pins: the runtime already supports simultaneous pin and bridge entries, and D3 is an existing oracle.

Keep GL replay’s current structural continuing-count rule. An overlap-refused pin beside two bridges is **not newly eligible** after R12 retires those bridges: the boundary still had three structural continuing pairs. Do not retry GL replay with a reduced count.

A separate boundary containing the sole eligible refused pin remains eligible under current rules. The one-GL-replay-per-plan limit remains unchanged.

### R6 and `held`

Apply R12 before `_magic_move_movies` returns and before `_held_after` runs.

For a chain crossing boundaries N−1, N and N+1:

- A carry from N−1 is ended by its source’s R12 retire entry at N.
- The refused bridge’s destination is not added to `held`.
- If that destination has no continuation at N+1, no artificial `retire ends` is emitted for it.
- If it has a valid continuation at N+1, its native decoder may start a new carry chain.
- Pins preserved at N remain held and must continue or end at N+1.

Leave `_chain_refusal` unchanged and require it to pass on the final entries.

## 5. Fix 2: pair from transition evidence

### Decision

Remove distance assignment completely from this planner:

- No permutation search.
- No 5,040-assignment cap.
- No nearest-neighbour fallback.
- No distance-based override or admission cross-check.
- No singleton exception when slot evidence is missing.

Distances are used only to compare a recorded endpoint with destination geometry and enforce uniqueness.

### 5.1 Source identification

For each shared, measured asset:

1. Resolve every source instance to its own transition slot using `_bridge_slot_chain` and the existing 0.5 px start-rect tolerance.
2. Require a readable, single-child chain ending in one textured leaf.
3. Reject missing slots, multiple starting slots, and reuse of one slot by multiple source instances.
4. Check slot ownership across the boundary, including different assets occupying the same source rect. One slot must not certify two sources.

Do not identify slots by draw-order position. Do not resolve stacked duplicates through texture identity or list order.

An asset with no destination instance needs no pairing search: retain existing held-source retirement behavior.

### 5.2 Read a narrow endpoint descriptor

Add private helpers for validated transition-slot evidence and destination draw descriptors.

Read only the selected chains and the root geometry needed to interpret them. Do not run the whole-transition GL replay validator as a prerequisite: unrelated artwork must not determine ordinary movie pairing.

Validate:

- Required containers, finite numbers, positive dimensions and scales.
- Supported static transforms and anchor coordinates.
- Animation group/leaf structure.
- At most one animation per relevant property.
- Non-additive, non-repeating, non-autoreversing endpoint semantics.
- Translation and per-axis scale on the measured leaf location.
- Readable `contents` texture endpoints.
- Opacity and visibility evidence.
- Supported, bounded perspective/z-position behavior; reject unsupported transforms rather than silently ignoring them.
- Finite arithmetic results, including overflow.

Reuse existing primitive validators where appropriate. Keep timing eligibility in `_bridge_timing_refusal`; do not import GL replay’s EaseInEaseOut requirement into pairing.

For the measured axis-aligned chain, compose each node’s origin from its position and anchor. At the animated leaf:

```text
leaf_origin = parent_origin + position + translation − anchor × size × scale
end_centre  = leaf_origin + size × scale / 2
end_size    = size × scale
```

Compose wrapper offsets rather than assuming centred children. Resolve texture as `contents.to.texture` when present, otherwise the leaf’s texture; validate `contents.from` against the source texture.

These descriptors are private pairing evidence. Runtime rectangles continue to come from `_MovieInstance.rect`.

### 5.3 Outgoing and incoming fades

Classify a validated opacity `1→0` source slot as **unpaired**. Accept its measured hide-at-completion companion as part of that outgoing shape.

- Held source: emit existing `retire ends`.
- Unheld source: emit no entry.
- Do not manufacture an R1 record merely because it fades away.

A `0→1` slot represents incoming content and cannot prove an outgoing correspondence. Incoming-only instances get no carry entry.

Partial fades, contradictory visibility, duplicate opacity animations, or other unsupported evidence fail closed with R1. A non-fading correspondence does not bypass R9: authored translucency still refuses the selected pair.

### 5.4 Destination identity and geometry

Use destination object IDs to locate their draw representations; never assume that destination draw index equals transition slot index.

Read the destination’s initial draw tree for landing evidence. Do not search later builds for a convenient substitute. Preserve existing R11 handling of unreadable destination draw order; additional missing or ambiguous endpoint evidence belongs to R1.

For each candidate:

- It must belong to the same normalized asset.
- Its draw object must name the candidate’s object ID.
- Its textured leaf must have readable geometry and texture evidence.
- Its composed textured-leaf centre and size must match the transition endpoint.

This comparison avoids mixing padded texture geometry with the inner video rectangle. It also avoids increasing the existing movie geometry tolerance.

### 5.5 Tolerance and uniqueness

Use separate, named pairing constants:

- Source-slot start rect: existing **0.5 px per component**.
- Endpoint descriptor: **0.5 px maximum component error** over `(centre_x, centre_y, width, height)`.
- Uniqueness margin: runner-up geometric error must exceed the selected error by **more than 1 px**, twice the endpoint tolerance.

Require exactly one geometrically qualifying destination before applying the texture agreement check. Texture evidence corroborates identity; it does not rescue geometrically ambiguous stacked destinations.

The measured endpoint errors are zero. The 0.5 px allowance accommodates export rounding; the additional margin prevents a barely-outside candidate from becoming an arbitrary choice. Test both threshold edges.

After all sources are resolved, require injective destination claims. Two sources claiming one destination refuse the asset; do not keep the first claim or attempt reassignment.

### 5.6 Failure scope

An R1 evidence failure refuses all outgoing instances of that asset at that boundary, using the existing `_retire` path. Other assets and boundaries continue independently.

Reasons should identify the actual failure: missing slot, duplicate starting slots, unreadable endpoint, no destination, ambiguous destination, texture disagreement, or duplicate destination claim.

Do not fall back to distance pairing after any failure.

### 5.7 Builds and refusal reachability

| Rule | Behavior after replacement |
|---|---|
| R1 distance tie/search cap | Removed. R1 remains active for missing, unsupported, contradictory or ambiguous transition evidence. |
| R1b opacity preference | Retired. Different candidate opacities no longer make correspondence unknowable. The chosen pair still faces R9. |
| Multi-instance R2 blanket refusal | Removed. A sibling’s build alone no longer refuses independently proven correspondences. |
| Unattributed-build R2 | **Retained** for the selected pair (§13 B1). |
| Carried instance’s own R2 | Retained in `_carry_refusal`, before R9, and, per §13 M-a, checked before slot lookup. A selected source explicitly building out, or destination explicitly building in, must never carry—even if synthetic or inconsistent slot data appears to pair it. |
| Actual unpaired built instance | A validated outgoing fade is unpaired. A source that is an attributed build-out target retires R2 before slot lookup (§13 M-a); otherwise missing source-slot evidence is R1. Never infer a replacement pairing from the build list. |
| R7/R8 | Retained. Neither kind nor trim is an identity-selection preference that can bypass the correctness checks. |
| `overlap`, R4/R9/R10/R11, integrity guards | Retained. Pairing proof establishes correspondence only. |

A destination build-in may appear in the destination draw tree while having no transition landing. Its presence in that tree is insufficient evidence of continuation. The inspected P2 artwork demonstrates this distinction; realistic movie-build cases need synthetic coverage without claiming new live measurement.

### 5.8 Other Magic Move variants

Initially admit pairing evidence only for `apple:magic-move-implied-motion-path`, the measured variant.

Other `apple:magic-move*` names produce asset-local R11 when pairing would be required. Do not alter `_unmeasured_transition`, load-time admission, or GL replay’s existing whitelist. Do not assume that a shared name prefix establishes equivalent animation semantics.

## 6. Functions and files to change

Use one implementation stream: both fixes converge in `_magic_move_movies`, and test-fixture changes depend on the final evidence reader.

| Location | Change |
|---|---|
| `live_continuity.py::_pair_instances` | Replace assignment enumeration with transition-evidence pairing; pass transition and destination draw context. |
| New private pairing helpers | Validate selected chains, compose endpoint descriptors, read destination descriptors, classify fades and enforce uniqueness. |
| `_magic_move_movies` | Supply pairing context, remove blanket build input, enforce slot ownership, and apply final R12 scoping before returning. |
| `_carry_refusal` | Unchanged except as §13 M-a/M-c add. Unattributed-build R2 is retained (§13 B1). |
| Module constants/imports/docstrings | Remove obsolete permutation machinery and distance-pairing claims; add pairing tolerances/variant set and R12 documentation. |
| Tests and trimmed fixture JSON | Restore necessary exported evidence and update targeted mutations/assertions. |
| SKILL.md, README, this plan | Update the contract and operator wording. |

Reuse `_bridge_slot_chain` without changing its matching semantics. Leave `_bridge_timing_refusal`, `effect_opacity_overrides`, `_gl_replay_attempt`, `_held_after`, `to_runtime`, `_runtime_entry`, and `_chain_refusal` behavior unchanged.

## 7. Test plan (superseded by §13 M-d)

Extend existing parameterized tests and fixtures; preserve coverage rather than preserving obsolete heuristic expectations.

### Fixture preparation

The trimmed P2 draw slots omit geometry/texture fields needed by the proposed descriptor reader. Restore those fields from the corresponding real exports, preserving numbers and consistent texture identity. Do likewise wherever the trimmed GL fixtures lack required evidence.

Do not synthesize missing evidence in production or weaken validation for trimmed fixtures. Retain fixture-versus-real-export parity checks.

Mutation helpers that add or move a movie must also update its relevant draw representation and transition evidence when the test intends a valid pairing. A destination-only geometry mutation must now be treated as contradictory evidence.

The §7 checklist was removed in favour of §13 M-d.

### Negative corpus

Extend `PER_MOVE` and its existing product-path assertions:

- Replace the old R1 distance-tie case with missing/ambiguous transition evidence.
- Add R12 with complete evidence for both bridges.
- Keep R2’s own-instance build case and add the new positive counterparts to existing parameterization.
- Retire the R1b corpus entry because production no longer emits it; preserve its scenario as a positive pairing test plus R9 protection.
- Keep every other active code covered and keep the emitted-code equality check strict.

The current multiple-bridge test stubs R10 because its clone has no transition motion slot. Replace that synthetic setup with coherent transition evidence so it tests both fixes through the real derivation path. [test_live_continuity.py:438](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity.py:438)

## 8. Expected fixture changes

For both GL replay settings:

| Fixture | Runtime plan | Non-runtime refusals |
|---|---|---|
| D1–D5 and D2-across | Identical | Unchanged, empty |
| D6 | Identical | Existing R4 unchanged |
| Positive Control | Identical | Unchanged, empty |
| p2-binary and p2-loop | Identical | Existing overlap record and GL replay details unchanged |
| Minimal Alpha_DSK | Identical | Only the two R1 reasons at player boundary 7→8 change: distance-tie wording becomes duplicate-starting-slot wording |

The corresponding trimmed Minimal Alpha_DSK fixtures receive the same reason change at their local boundary indexes.

None of these exports exercises R12; `alpha-dsk-textures` 7→8 has two structural bridges, both overlap-refused, and must stay R12-free. Its behavior is established by the synthetic negative corpus and chain tests.

Do not update any runtime SHA constant to accommodate a failure. Relevant pins include P2 off/on, loop off/on, D1–D6, injected-plan equality, and the downstream probe/GL replay tests. [test_live_continuity.py:563](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity.py:563), [test_live_continuity.py:2658](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity.py:2658), [test_live_continuity.py:3076](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity.py:3076), [test_live_continuity_decks.py:386](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/deck-refusal-rules-alpha-1686c7/tests/test_live_continuity_decks.py:386)

## 9. Documentation changes

Update SKILL.md “Refusals” and “Regression oracle”:

> R1 refuses missing or ambiguous Magic Move transition correspondence; there is no distance fallback. R1b is retired. R2 prevents carrying an instance that itself builds in or out. R12 refuses all otherwise admissible bridges when more than one would cross the same boundary; independent pins remain eligible. Scoped refusals are applied before held-state propagation, and R6 still validates final entries.

Remove multiple geometry changes from the deck-wide list. Preserve the regression-oracle requirement.

Update README “Movie continuity”:

- Replace minimum-distance pairing with reading each source movie’s transition slot and matching its recorded endpoint.
- Explain that incoming/outgoing fades are unpaired.
- Replace R1/R1b wording and add R12.
- State that R12 affects the moving instances at that cut while independent pins and other cuts retain continuity.
- Remove multiple moving movies from the `unsupported` examples.
- Explain that unrecognized Magic Move variants or insufficient correspondence evidence decline the affected asset.
- Preserve the existing correctness refusals and named residuals.

Record implementation evidence, exact verification results and any deviations in this plan. Do not rewrite the historical generalisation plan as though its original measurements had used transition-record pairing.

## 10. Verification

### Offline before/after audit

Use a scratch script named `continuity_refusal_audit.py`, outside the product package. It must:

1. Accept `--repo`, `--fixtures`, and optional `--compare BEFORE_JSON`.
2. Import the selected checkout in a fresh Python process.
3. Enumerate exactly these exports:
   - `qual-decks/{D1,D2,D3,D4,D5,D6,D2-across}/html-unmodified`
   - `gl-decks/Minimal Alpha_DSK/html`
   - `gl-decks/Positive Control/html`
   - `{p2-binary,p2-loop}/html-unmodified`
   - `alpha-dsk-textures/html-unmodified`, `p2-soak-loop`, `p2-loop-grey`, `minimal-alpha-dsk-17c0c938`, `p2-recovery/html-adversarial/html-unmodified` (§13 M-f; resolve each export root by its `assets/header.json`)
4. Fail if an export or slide is missing; never skip.
5. Build slide records from each header’s `slideList`, preserving player order.
6. Derive plans with `gl_replay=False` and `True`, using a traversal-safe read-only resolver.
7. Emit, per export/flag:
   - Input JSON hashes.
   - Derivation/runtime status and unsupported reason, if any.
   - Full runtime dictionary.
   - `plan_signature(runtime)`.
   - Full ordered refusal list, including GL replay fields.
8. In compare mode:
   - Require identical input hashes.
   - Require identical runtime dictionaries and signatures for every export/flag.
   - Print a structured refusal-list diff.
   - Permit only the 7→8 R1 reason changes in the Minimal Alpha_DSK family (`gl-decks/Minimal Alpha_DSK`, `p2-soak-loop`, `minimal-alpha-dsk-17c0c938`); all other differences fail.

No evidence mode (§13 M-f); retain results only.

Run the same script against baseline `5b09b379` and the implementation checkout:

```sh
python -B continuity_refusal_audit.py \
  --repo "$BASELINE_REPO" --fixtures "$FIXTURE_ROOT" > before.json

python -B continuity_refusal_audit.py \
  --repo "$IMPLEMENTATION_REPO" --fixtures "$FIXTURE_ROOT" \
  --compare before.json > after.json
```

Do not generate or convert any fixture export during this comparison.

### Automated checks

Run targeted planner/corpus/deck tests during implementation, then the coordinator’s full checks:

```sh
env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal
```

Run the project’s Python 3.10 floor verification, including the changed planner tests under 3.10, and:

```sh
cd dashboard
npm run test:ui
npm run test:maps
```

Confirm runtime JavaScript and its pinned hashes are unchanged.

**No browser gates are needed for this PR:** JavaScript bytes, gate runtime plans and rendering behavior are unchanged. A runtime-plan mismatch is a defect to investigate, not a reason to repin signatures or expand this PR into runtime work.

## 11. Risks and residuals

- Trimmed fixtures currently omit evidence the new matcher needs. Restore it from exports; do not add production defaults.
- Texture geometry and movie geometry describe different rectangles. Keep pairing descriptors separate from runtime placement.
- Shared poster textures do not uniquely identify instances. Geometry uniqueness and injective claims remain mandatory.
- A fade proves no continuation; malformed or missing data does not prove a fade.
- Real movie-build exports are absent from the supplied measurement set. Retain explicit R2 protection and fail closed on unsupported evidence.
- Other Magic Move variants remain unmeasured and locally refused.
- The one-bridge policy remains even though core state is per instance. Supporting concurrent bridges is outside this PR.
- Existing play-across, incoming-clock, opacity, loop, trim and z-order residuals remain unchanged.

## 12. Owner questions

None. The binding decisions resolve the scope; the conservative choices above need no additional owner decision.
## 13. Round-1 critique folds (Opus 5.5 high, 2026-10-14) — binding

The critic re-measured: 0.0 px endpoints with texture agreement on 40 real correspondences (the 11 briefed exports plus
`alpha-dsk-textures`, `p2-soak-loop`, `p2-loop-grey`, `minimal-alpha-dsk-17c0c938`, `p2-recovery/html-adversarial`), and a
monkeypatched slot-pairing derivation kept every runtime sha identical on 16 exports, GL replay off and on.

- **B1 (blocker, owner rule).** Unattributed-build R2 is retained unchanged in `_carry_refusal`, after pairing, for the
  selected pair only. The transition proves correspondence, not that the carried instance has no build; no fixture has a
  movie build, so it costs nothing. Only the multi-instance sibling R2 inside `_pair_instances` is removed.
- **M1.** The destination object-frame vs movie-layer agreement check is deleted (real exports draw the padded texture size,
  up to 3.6 px larger). Identify the destination by the draw object's `objectID` (existing `_draw_slots(dst.events[0])` +
  `_movie_slot_index`) plus the textured-leaf endpoint comparison.
- **M2.** GL replay's `continuing_count` = `Σ min(len(outgoing), len(incoming))` over every shared measured asset, whatever
  the pairing outcome — never the slot-evidence pair count. It is never below today's count, so GL is never newly admitted.
  GL admission is out of scope.
- **M-a.** Before slot lookup, a source instance that is an attributed build-out target retires R2 and is excluded from slot
  pairing; a destination build-in target is excluded as a candidate and refuses R2 if a slot lands on it. Only the
  remaining instances need slot evidence.
- **M-b.** Constant animations (from == to) of opacity, zPosition and `hidden` are neutral. A fade is exactly opacity 1→0 on
  the chain, optionally with the measured `hidden` true→true companion, any duration. Any other opacity change is R1.
  Opacity values themselves stay R9's job.
- **M-c.** A destination candidate whose draw chain at `events[0]` has any `hidden: true` node is not a landing: R2
  ("hidden at its slide's first event, so it builds in"). Check `hidden` only, never opacity. Supplements B1; measured on
  artwork only.
- **M-d (tests, owner minimal-tests rule).** Replace §7's checklist with four groups (~3 new test functions plus edits):
  1. R12: one `PER_MOVE` corpus entry, plus the existing
     `test_only_unrefused_geometry_changes_count_towards_the_one_per_boundary_limit` rewritten with real slot evidence,
     keeping its `overlap_the_clone` parametrization (False: R12 on both bridges; True: the clone is overlap-refused and
     untitled.mov bridges). Derive with `gl_replay=True` as well, asserting P2 1→2 still arms glReplay and `to_runtime()`
     succeeds.
  2. Pairing positives: one parametrized test, rewriting the distance-specific tests (R1 offset `:194`, R1b `:224`, sibling
     R2 `:3836`, `:3859`, `:3886`) into positive cases. Pins/scale/padding/anchors are already covered by the unchanged sha
     tests.
  3. Pairing negatives: one parametrized R1 matrix of small mutations on the P2 tree — missing slot, stacked duplicate slots,
     a slot shared across assets, endpoint 0.5 / 0.6 px, margin 1.4 / 1.6 px, texture mismatch, malformed number, non-leaf
     motion, reordered slots — plus the unknown variant (R11).
  4. Builds: update the existing R2 parametrizations (sibling rows flip to carries; unattributed rows stay R2), add M-a/M-c rows.
  Drop "> 5,040 assignments" and "R6 still rejects hand-built plans". New corpus entries: R12 and the replacement R1 only.
- **M-e (fixtures).** Only the root P2 fixture (`tests/fixtures/live_continuity/assets`) lacks evidence. Restore P2 slides
  1–4's `events[*].baseLayer` subtrees verbatim from `REAL_EXPORT_ROOT` (`p2-recovery/html-adversarial/html-unmodified`),
  relabelling leaf textures to the sanitized label of the slot that lands on them and unique labels otherwise (P2's labels
  are per slide: slide 1 slot 3 and slide 3 slot 1 both say `SANITIZED-TEXTURE-3` for different real textures). Extend
  `test_fixture_bridge_transition_is_the_real_exports_with_textures_sanitized` to compare the restored draw subtrees with
  textures stripped; no new parity test. No GL or qual trimmed fixture changes. Plan-sha constants untouched.
- **M-f (audit).** Add `alpha-dsk-textures/html-unmodified` (a real two-bridge boundary 7→8, both overlap-refused, which
  must NOT become R12), `p2-soak-loop`, `p2-loop-grey`, `minimal-alpha-dsk-17c0c938`, `p2-recovery/html-adversarial/html-unmodified`.
  Allowed refusal diff: the Minimal-DSK-family 7→8 R1 reasons only. No evidence mode.
- **L1.** Unmeasured `apple:magic-move*` variants refuse R11 (unmeasured export shape), not R1.
- **L2 (keep it simple).** Restrict to the measured shape: transition slot = wrapper → textured leaf with motion on the leaf
  only; destination path = root → group → object → leaf. Reuse `_effect_chain`, `_check_effect_node_geometry`,
  `_v_list_of(_v_motion_group)` and the GL validator's leaf-only-motion rule rather than a general composer. Root origin
  (position − anchor×size) must be ≈ 0 (`_root_position_residual_px`). Texture: `contents.from` == leaf `texture`; resolved
  texture (`contents.to`, else leaf `texture`) == candidate draw-leaf `texture`.
- **L3.** The corpus harness hard-codes asset `"untitled.mov"`: give entries a per-entry asset for R12. The literal `"R1b"`
  must vanish from `live_continuity.py` (docstrings included) for the `inspect.getsource` coverage regex.
- **L4.** Edit only the continuity "Refusals" bullet in SKILL.md (line ~745's R1/R1b are Stage T's; `test_live_runtime.py`
  R9–R13 are dissolve/mm-fade). Add a one-line "superseded by keynote_live_continuity_refusal_scoping" pointer at
  generalisation plan §2.2/§2.3; do not rewrite it.
- **L5 (follow-up, not this PR).** The core JS keeps motion/hold state per element (`live_continuity_js.py:405-420,
  1192-1225, 1297-1330, 1376`); only GL's `carriedMemo` is a singleton. Lifting R12 entirely needs a two-bridge gate deck
  (overlay z-order is DOM append order; mid-flight crossings are not covered by `overlap`).

## 14. Implementation evidence (2026-10-14)

Implementer: Codex GPT-5.6 Sol (high). Code review r1: Opus 5.5 (high) — no blocker; 2 majors (R6 tests deleted,
Positive Control fixture drift), 3 mediums, 6 lows, all folded, none refuted.

- Offline audit (`continuity_refusal_audit.py`, scratch): 16 exports × `gl_replay` off/on = 32 comparisons vs baseline
  `5b09b379`. Runtime dicts 32/32 and plan signatures 32/32 identical; input hashes identical. Refusal diffs: 6 export/flag
  results (12 records), all the Minimal-DSK family (`gl-decks/Minimal Alpha_DSK`, `p2-soak-loop`,
  `minimal-alpha-dsk-17c0c938`) 7→8 R1 reason, exact old distance wording → exact new "transition slots [1, 2] all start"
  wording. `alpha-dsk-textures` 7→8 stays R12-free.
- `live_continuity_js.py` byte-identical (sha256 `0fabb4f4…dd94d`); no sha/signature constant changed.
- Review folds that refine the plan: unreadable destination draw order in the pairing path stays R11 (§5.4); fade
  admission tightened beyond §13 M-b to the measured shapes only — constant opacity is neutral only at 1, `hidden`
  true→true only as the companion of an opacity 1→0 fade (zero audit change); the Positive Control trimmed fixture was
  re-sanitised bijectively (12 real textures → 12 labels) so it derives the same clean bridge as its real export, with
  texture-correspondence parity added.
- Targeted tests (single worker, 3.10.10): `tests/test_live_continuity{,_corpus,_decks}.py` 488 passed.
- GL replay rule 1 ("not in the measured WebGL list") is now unreachable: `_PAIRING_TRANSITIONS == _GL_REPLAY_TRANSITIONS`,
  so an unmeasured variant refuses R11 before GL replay is attempted; its test row was dropped.
- Code review r2: Opus 5.5 (high) — approve; three style lows folded by the coordinator.
