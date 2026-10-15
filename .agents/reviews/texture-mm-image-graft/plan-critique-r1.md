# Plan critique r1: keynote_export_texture_identity (Opus 5.5 high)

**Verdict: CHANGES REQUIRED.** 0 blockers, 3 major, 8 medium, 4 low.

The core direction is sound and the key facts hold. D2's own landing plus source-object identity plus source-asset pixel agreement is a correct and sufficient certificate for F2. The changes are about proportion. About half of the proposed guards are already implied by the exact frame rule, size equality and the fail-closed pixel check. At least one guard (stroke via style inheritance) could misfire on F2's 357×235 map. One gate cannot be met, and the test section contradicts the house full-suite rule.

## Facts spot-checked (offline; main venv, worktree src)

All of these hold:

| Claim | Check |
|---|---|
| Floor/ceil frame rule | 31/31 mutually-unique tight F2 pairs obey it. Exactly 31 of 94 entries have one floor/ceil leaf, all type 5. |
| Malaysia chain | Leaf `(588,827,176,205)` = floorceil of acc/IWA `(589.899,828.828,172.872,201.98)`. Witness `1/effects/0/baseLayer/layers/11/layers/0 (938,846,21,24)` = floorceil of `(939.66,847.31,17.81,20.81)`. |
| Opacity-0 sources | 15355064 → style 15346689 and 15355057 → style 15346690, both `mediaProperties.opacity 0.0`. |
| Correlations | 0.98472 / 0.99573 reproduced. Thumbnail std is 49.5/49.1 and 43.9/43.5, so the non-flat guard is safe for F2. Wrong-size scores 0.908 / 0.944 hold (pixel-measurements.json). |
| `_corr` | `pt:352` returns 1.0 on equal arrays before the `FLAT_STD` guard. |
| `_d2` | Donor set collapse at `pt:587–595`. |
| `_groups` | `_same_object` (`pt:434`) never yields a text key for non-text, so it merges across events and effect copies. F2's Malaysia group has **one member** (measured). |
| `source_slides` | Discards objects (`hp:478–494`). |
| `load_cached` | Version gate at `hp:923`. |
| 3b9019 tag boxes | No tight accessibility entry; landings have no contents.to (extra.txt:17–22). Matches `gates-r1.md:37`. |
| Strict decode | `_load_deck_full(F2.key)`: 2758 objects, 0 skipped, 0.5 s. `Data/pasted-image-44137.pdf` and `-44140.pdf` are unique members. |

Anchors are accurate to within ±2 lines. `hp:1086` is the `try` at 1087; the call is at 1088.

## Findings

### 1. major · simplicity/correctness: cut the I1.5 appearance/style guards; they can only refuse, and may refuse F2
**Evidence**
- contents.to is Keynote's own rendering of the MM end state, which is the destination object's appearance. That is why D2 is the identity for text.
- Stroke, shadow, reflection, crop or adjustments can only *lower* the source-PDF-vs-donor correlation, which already fails closed. They cannot create a false pass. The only false-pass story needs all three of:
  - a same-data object;
  - a page of identical size;
  - a different crop on the previous slide whose table collides onto exactly that id.

  That is theoretical, and the owner's eye catches it.
- Implementing the guards needs style-inheritance semantics. F2's 357×235 destination 15348425 uses root style 8527, which has `stroke.width 1.0` with `pattern TSDEmptyPattern` (no visible stroke) and `reflection {}`. A "no enabled stroke" check that misreads this refuses the second map, which the owner's prepare named.
- The plan's "no IWA flip" check needs the `GeometryArchive.flags` bit layout. That field is an undocumented uint32 (no enum in keynote_parser v14_5), and **every F2 image has `flags: 3`**.

**Fix wording:** replace I1.5 with:
> "Eligibility: the object is `TSD.ImageArchive` with no `mask`. Optionally require `geometry.angle == 0` as a one-field allowlist. No style-inheritance, stroke, shadow, reflection, adjustment or flip-bit interpretation: appearance can only lower source-pixel agreement, which fails closed. Visibility and opacity are ignored."

Move "appearance guards" to OQ-1 as a deferred, theoretical tightening with its cost: style resolution code plus the risk of refusing F2.

### 2. major · gates: drop the old-player (e9b2fad4) source-positive requirement
**Evidence**
- The new route reads Keynote's export JSON/PDF and the `.key`. It does not touch `main.js` or the player-facing write path, which stays the existing graft writer.
- `SUPPORTED_PLAYERS` gating is unchanged. Stage T did not qualify text D2 per player.
- None of the 18 fixture exports has a revision-matched source (advisory §2), so the required positive cannot be produced without an old Keynote.
- As written, G1 is INCONCLUSIVE by construction, or it forces a new player-gated code branch.

**Fix wording:** in G1 and OQ-5, replace the bullet with:
> "Both supported players: the existing two-player corpus keeps its Stage T outcomes unchanged (no new fixes, no new refusals). The source-positive is player-independent and is proved on F2 (17c0c938). No player-specific gating of the new route."

### 3. major · tests: the test section contradicts the house rule on full suites
**Evidence:** §5 says "No broad test suite is required… run the targeted changed-module checks". The owner's non-negotiable is: no CI, so run the FULL suites locally (3.12 and the 3.10 floor) for every code PR.

**Fix wording:**
> "Targeted tests during folds; the full suites (3.12 and the 3.10 floor; `test:ui` only if UI is touched) on the final integrated commit once the peer session releases the machine."

### 4. medium · simplicity: one stream, no new module, reuse existing helpers
**Evidence:** after the cuts in 1 and 5–9, the certificate is roughly 100–150 lines in `preview_textures.py` plus a two-kwarg handoff in `hp.apply_preview`. The existing helpers cover every need:

| Need | Existing helper |
|---|---|
| Strict decode | `_load_deck_full(strict=True)` (`ir:225`) |
| Top-level drawables with raw geometry and kind | `derive_kind_index` (`ki:98`) |
| Data-id → member | `offline_inspect.data_member_index` (`oi:58`) |
| Thumbnails of an extracted member | `_Renderer.thumb`, with the member written into `_plan`'s existing `scratch` dir |

A four-stream split with a pre-agreed context/API contract costs more coordination than the code it divides. The plan itself warns against "abstractions solely to maximize parallelism".

**Fix wording:**
> "One implementer stream: `preview_textures.py` (add `slide_id` to `_Slide` from `originalSlideId`; the certificate inside the D2 branch of `_verify`), the `html_preview.py` handoff, both test files (reserve `tests/test_preview_textures.py` with Stage B), and one G1 `EXPECT` row with a `source` key in `scripts/texture_repair_check.py`. No new module."

### 5. medium · simplicity: accessibility is a redundant link; match leaf to IWA directly (planner's call, state the choice)
**Evidence**
- I1.2 plus I1.4 force `accessibility == IWA raw geometry` within 1e-3, so the entry contributes no number the IWA record lacks.
- Direct `leaf == floorceil(IWA raw geometry)`, unique within the 0–4 px envelope over all top-level drawables, resolves 26/57 F2 type-5 base and MM leaves. That includes every map destination (15348425/26/27) and both MM witnesses (15355057/64, effect copies).
- The accessibility route gets 13 on base leaves only.
- Uniqueness over drawablesZOrder (any kind, including groups) is a superset of accessibility. Accessibility omits objects not yet built: the event-0 report card has a leaf but no entry.

**Fix wording:**
> "I1: the leaf frame equals floor/ceil+1 of exactly one top-level drawable's raw geometry within 0.01. That drawable is an eligible ImageArchive, and no other drawable or leaf lies within the 0–4 px envelope (I1.3 domains). Accessibility is not required."

If the planner keeps accessibility, say why it adds evidence, and keep only one of the two equal-geometry links.

### 6. medium · scope: cut guards the frame rule, size equality and pixels already imply
**Evidence**
- An unexplained scale, canvas mismatch, ancestor or sublayer transform, or a wrong `_end_rect` interpretation all break the exact floorceil match or the 0.01 unique landing. Either way the candidate is refused with no extra code.
- The aspect check is meaningless for aspect-normalised 64×36 thumbnails. It would also refuse a legitimately stretched image (`aspectRatioLocked` false), whose contents.to is still correct.
- PDF box origin and `/Rotate` handling only affect the render, which then fails correlation.
- Text D2 already trusts `_end_rect`, validated over 81 landings in Stage T §1.4.

**Fix wording:** delete these:
- from I2: "Validate the MM transform … rotation or unsupported geometric animation";
- from I4: the aspect clause, and the "zero-origin/unrotated media/crop boxes" clause;
- from I1.5: the canvas, affine, ancestor, sublayer and contentsRect bullets.

Keep: single-page source PDF; the existing V1 mediabox check; donor size equals the leaf size within 0.01.

### 7. medium · correctness/simplicity: one source-revision check, not three, and no cross-attempt reuse
**Evidence**
- The pipeline's standard is one `deck_digest` check, then reads: `source_slides` at `hp:1059`, and the export is never re-verified.
- The repair writes only the export copy, so a commit-time re-check adds nothing.
- Recomputing per attempt costs 0.5 s (measured).

**Fix wording:**
> "After reading IWA and the selected member(s), require `deck_digest(path) == manifest.sourceDigest`, else `PreviewStale` (not consumed by the retry; the existing `except` deletes the export). Recompute evidence on each attempt; no cached evidence across attempts."

Delete the "before and after … before committing" and "reuse source evidence only while…" sentences.

### 8. medium · correctness: state the uniqueness domains concretely (groups, masters, placeholders)
**Evidence:** "no unresolved group/master/other drawable competitor that prevents proving uniqueness" is vague. It invites an implementer to build master, placeholder or group-descendant traversal.

**Fix wording:** I1.3 becomes:
> "Uniqueness is over (a) leaves in the candidate's own tree (the event's base tree, or the witness's own effect tree) within the 0–4 px envelope, counting identical duplicates; and (b) the slide's drawablesZOrder records of any kind (via `derive_kind_index`, groups included) within the envelope. Master/layout drawables, placeholders and group descendants are not traversed. Any of them that renders produces a leaf and fails (a). One that does not render cannot be the leaf's content."

### 9. medium · correctness: I3 should refuse, not split
**Evidence:** "If splitting is necessary, partition…, recompute the donor relation" re-opens the grouping surface that took four Stage T review rounds (§7 r1–r4). F2's group has one member.

**Fix wording:**
> "Every member of the proposed group must resolve (I1) to the same IWA object as the target, else the whole group is refused. No partitioning in this increment."

### 10. medium · gates: put the owner's eye on a guaranteed repaired page
**Evidence**
- Exports collide differently each time (investigation; Stage T G4, where the live prepare was clean).
- One live F2 prepare may well be clean, or collide elsewhere, so G3 may never show a grafted map.

**Fix wording:** G3 adds:
> "Owner views the G1-repaired copy of F2-html (real defect, real donor) in the HTML player via the existing host on a temp copy, plus the labelled synthetic 357×235 variant. The live prepare's outcome is recorded separately."

### 11. medium · tests: fewer, existing-test rows; a seam instead of IWA bytes; drop rows already covered
**Evidence**
- About 25 boundary cases are proposed in a new file. Most test guards that findings 1 and 6 cut.
- `load_cached`'s version mismatch is already a parametrized row: `wrong-version` uses `version + 1` (`tests/test_html_preview.py:433,446`).
- There is precedent for a decoded-dict seam: `tests/conftest.py:79` and `tests/test_offline_write.py:1359` monkeypatch `_load_deck`.

**Fix wording:**
> "No new test file. Add rows to `test_repair_picks_the_rule_and_writes_a_consistent_export`:
> (1) D2-image success with an opacity-0 source, asserting the verify keys and the graft;
> (2) a competitor within the envelope → refused;
> (3) the MM-source data id differs → refused;
> (4) a group member resolving to another object, or raw corr 0.8996 via the existing monkeypatched `_corr` row style → refused.
> Source comes from a monkeypatched `iwa_runs._load_deck_full` (decoded dict) plus a zip holding one `Data/…pdf`. Keep the existing no-source refusal at `:386` as the compatibility row. In `test_apply_repairs_textures_before_conversion_with_one_re_export`, extend the `_repair` stub to assert `source_path`/`source_digest` on both attempts. Update `set(entry['verify']) <= {'ocr','corr'}` (`:362`)."

### 12. medium · scope: TEXTURE_REPAIR_VERSION bump is unnecessary and costs a re-export of every cached deck
**Evidence**
- A refused export is deleted (`hp:1102`), so no v1 cache holds a case the new route would change.
- Nothing reads `repaired[].verify`: grep across src and scripts finds only `hp:923` and the writers.
- A bump makes every cached deck (Alpha, F2, …) re-export through Keynote on its next prepare.

**Fix wording:** add an OQ:
> "OQ-6, version bump. Rec: keep `TEXTURE_REPAIR_VERSION = 1`. The new route only accepts cases v1 refused, and refused exports are never cached."

If the owner prefers uniformity, bump and accept the one-time re-exports.

### 13. low · record: shrink the evidence
**Fix wording:**
> "New D2-image fixes record `verify = {"corr": <raw>, "object": <dest IWA id>, "sourceObject": <MM-source IWA id>, "data": <data id>}`."

Drop the nested version, `sourceDigest` (it is already in the manifest), `memberSha256`, `members` (`entry.leaves` exists), `frameRule`, `appearance` and `pixelProfile` (constants).

### 14. low · gates: specify the synthetic 357×235 defect
**Evidence:** a synthetic defect is acceptable, because the chain and donor are real and only the damage is injected. A "captured real failed export" does not exist: refusals are deleted (`hp:1102`).

**Fix wording:**
> "On a temp copy, set slide 4's (939,807,357,235) leaf texture to the winner id `DF3DB700`, as Keynote did for Malaysia. Expect R1+R6, then D2 → slide 3 page 14 `B37026D5`. Label it 'synthetic defect, real chain/donor'."

### 15. low · fact/wording
- "13/47 … including the three zoomed maps": the census counts base leaves only (`measure.py`, `l.is_base`). The MM witnesses were checked individually (advisory §3). Reword to "13/47 base-leaf occurrences; the two small-map MM witnesses verified individually".
- G1 "D2 2 poster groups; D2 across-first-build 1" should read "qual-decks D2 via D3 ×2; across-first-build D3 ×1" (`texture_repair_check.py:58–60`).
- I2 "one eligible MM witness": implement it inside the new branch. Have `_d2` carry its witness leaves on the `_Fix` so the certificate can resolve them, and leave text D2's set semantics unchanged.

## Identity chain: remaining holes
With findings 5, 8 and 9 applied, I found no correctness hole:
- **Group, master and placeholder competitors:** closed by the two uniqueness domains in finding 8.
- **Accessibility from a different build state:** removed with finding 5. If accessibility is kept, it is per-event as the plan says.
- **MM witness in an event with different accessibility:** the effect-leaf rect must still equal floorceil(IWA), so a build that moved the object refuses.
- **Two players:** not relevant to identity (finding 2).
- **File-changing MM:** refused. That is fail-closed but stricter than needed, because contents.to is still the destination's appearance. Acceptable for this increment.

## OQs
- OQ-1: restate after finding 1. Rec: PDF ImageArchive, no mask; appearance and raster deferred.
- OQ-2: OK as written.
- OQ-3: OK as written.
- OQ-4: OK as written.
- OQ-5: drop the player clause (finding 2). Keep the F2 slice local under the main checkout `output/fixtures`, uncommitted.
- Missing: OQ-6, the version bump (finding 12).
- Missing: G3 on the repaired G1 copy (finding 10).
