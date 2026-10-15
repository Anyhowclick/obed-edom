# Keynote export texture repair: text-glyph twin identity (D1g)

Rev 3 — folds Opus 5.5 high critiques r1–r3. Status: APPROVED by the owner 2026-10-15, 2026-10-15. Investigation only; no implementation, tests or owner acceptance.

Anchors: functions in `src/obed_edom/preview_textures.py` (`pt`) by name; `hp` = `html_preview.py`; `tc` = `scripts/texture_repair_check.py`; `tests` = `tests/test_preview_textures.py`. Investigation: `.agents/reviews/text-glyph-identity/investigation.md`. Builds on `keynote_export_texture_repair_stage_t.plan.md` and `keynote_export_texture_identity.plan.md`.

## 1. Problem and measured basis

On 2026-10-15 the owner's G2 live prepare of F2.key `6fea812c…` refused: `slide 4 (33×135 text): its texture is mis-mapped and no verified replacement exists`. That export was not kept. The 33×135 leaf is the "i" of "Malaysia", under an automatic per-character `apple:twist-and-scale` buildIn. The current F2 (`f99a68ef…`, export tree `c664279e…`) does not reproduce: the texture step is D2×1 on a map, with no glyph hit.

**Measured** (current F2-html and the old 2026-10-14 export, both read before the old one left the owner folder):
- The build exports each letter as its own type-6 leaf, twice: a base copy `events[0].baseLayer.layers[s].layers[0].layers[k]` and an effect copy `events[0].effects[0].baseLayer.layers[k].layers[0]`. The base wrapper, the effect and the effect's baseLayer share objectID `E9B8691F…`. The slot `s` moved from 4 to 3 between exports. The twins' rects, `initialState` and `texturedRectangle` are identical.
- Glyph leaves have no objectID, character range or accessibility match. The only "Malaysia" accessibility box is in event 1, and its glyph IoU is 0.03–0.10. So `_text_key` is None: D1 can't bind, D4 excludes text, and D2 needs a Magic Move landing.
- **Collision vector:** slide 4 recycles slide 3's ids onto base-layer objects. Current: the base i uses `B7E3456D`, which is slide 3's 5850×4368 map, while the effect i keeps its natural, slide-4-unique `9C60C2B5`. Their pages (indices 9/16) are pixel-identical. Old: both i twins use `9C60C2B5`, and `B7E3456D` sits on an 8×149 object. `DF3DB700` is double-assigned in both exports, which is the live map collision.
- Players resolve ids per slide table. A collision is harmful when incompatible references share one local entry.
- **No orphan pages:** across 7 collided exports (11 slides), PDF pages equal table entries 1:1. There are no unreferenced ids and no pages shared by two ids. The victim's content survives only under another leaf's referenced id (D1/D3's routes) or not at all (F2 176×205, Alpha s10).
- **Shared-id twins are not repairable:** in every measured collided object with a same-event twin (3 of 3: Alpha s9 event 1, qual-D2 s2/s5 movie-start copies), the twin shares the bad id.
- **Inferred, not measured:** a collision on the i most plausibly hits the recycled base copy, which leaves the effect twin as a natural-id donor. D1g covers that case. When both twins share the bad id, no in-export donor exists. That stays a refusal by design; the remedy is a re-export or a source edit.

## 2. Implementation stream

One **Codex GPT-5.6 Sol high** implementer, then an **Opus 5.5 high** code review, run serially after the machine is free.
- Scope: `preview_textures.py`, `tests/test_preview_textures.py` and `tc`. No new module, no source-deck (IWA) reads, no new `repair_textures` arguments and no player change.
- Add `_glyph_twin(slide, leaf)` and `_d1g(slide, group, bad_keys, bad_textures, repair_members)`, and try D1g right after `_d1` in `_plan` (order D1, D1g, D3, D2, D4).
- Pair glyphs from `_Leaf.path` alone. A base glyph is `("baseLayer","layers",s,"layers",0,"layers",k)` and an effect glyph is `("effects",e,"baseLayer","layers",k,"layers",0)`; any other path length or shape gets no twin. No new walk.

## 3. D1g certificate (all required)

### G-1. Structural twin

Find the leaf's twin:
- In the same event, find exactly one base wrapper `baseLayer.layers[s].layers[0]` and exactly one effect whose non-empty objectID equal each other. Count duplicates before selecting; any duplicate means refuse.
- The wrapper has N ≥ 2 direct leaves. The effect's baseLayer has N wrappers, each holding exactly one leaf.
- Pair base leaf `k` with effect wrapper `k`'s leaf, in both directions.
- Require equal `kind` (type 6) and equal `texturedRectangle`, with rects within `RECT_TOL`.

Accept any effect of this shape, whatever its name or build type. Never pair by texture id, nearest rect, OCR or animation time. Add no wrapper-transform, perspective, contentsRect, mask or container-initialState predicates: repointing is texture-only, and `_walk` rects already carry the offsets.

### G-2. Usable donor

D1g never scans the table; it uses only the twin's own texture. That texture must:
- differ from `group.old`;
- not belong to a detector-hit leaf or a scheduled repair member;
- not be in `bad_textures` (an R1b `contents.to`);
- fit the leaf (`_consistent(slide, twin)`);
- **be used only at the twin's rect:** every slide leaf whose `texture` equals the donor id lies within `GROUP_TOL` of the twin's rect, or refuse.

The last rule matters because letters fall within `SIZE_TOL` of each other (the a's are 77×103, 76×103 and 77×103). A recycled id double-assigned to two letters flags neither leaf, and its page shows whichever letter won.

Cross-slide reuse of the donor id is not disqualifying, because tables are slide-local.

### G-3. Whole group

Every group member must certify to the same `(event, objectID, k)` and donor, or the whole group refuses. Grouping is unchanged:
- `_same_object` needs the same old id and a rect within 0.5, so distinct letters never merge.
- Both twins bad with one id makes one group with no opposite twin, so it refuses.

### G-4. Verify and record

`_d1g` sets `fix.verify = {"objectID": …, "glyph": k, "twin": <donor leaf key>}`. Record no character, because k is a render-component index, not a Unicode offset.

`_verify` adds a D1g branch after the shared `_fits`/`_mediabox_ok` check and before the text branch. It passes when the donor thumbnail is finite with std ≥ `FLAT_STD`. There is no OCR (single-glyph OCR was unreliable) and no sibling correlation. The existing text-branch fallthrough stays as it is for D1 and text D2.

Trust boundary: object/index provenance plus a surviving, table-consistent copy. This is at least D1's premise. It is not independent pixel proof against a same-size wrong page.

## 4. Writes, refusal, cache

- Writes use the existing same-slide repoint (`_repoint`, `_write_slide`). They change only the certified leaves' `texture` and matching `contents.from`, and keep JSON/JSONP in sync. The table, PDF/PDFP, geometry, timing and opacity are unchanged.
- Every group is planned before any write. Aggregate refusal, the `_postcondition` checks and the one re-export in `hp.apply_preview` are unchanged.
- **`TEXTURE_REPAIR_VERSION` stays 1.** D1g turns former refusals into repairs, and refused exports are never cached.

## 5. Tests (minimal)

- Add one builder to `tests`, e.g. `_glyph_slides(bad="base"|"effect", variant=None)`: one slide with a 2-letter build, base and effect twins, and a collided id.
- Add params to the existing `test_repair_picks_the_rule_and_writes_a_consistent_export` and no-write refusal test:
  1. base bad → D1g, effect donor; record and `verify` checked; PDF and table unchanged;
  2. effect bad → D1g, base donor;
  3. both twins share the bad id → refused, snapshot unchanged;
  4. twin rect or `texturedRectangle` mismatch → refused;
  5. donor is itself a hit → refused;
  6. donor id also used by another same-size glyph → refused.
- Targeted tests while folding. Run the full suites (3.13, the 3.10 floor, and the dashboard) locally before the code PR, serially after a "need window".

## 6. Gates

New exports, reports, caches and eye copies go under `~/Desktop/StageT-text-glyph-evidence/<date>/`, never under any `output/`, `tests/fixtures/` or `/private/tmp` (Keynote).

**G1 offline.** Generalise `tc`'s F2 path before adding the row:
- Restore the pattern removed in `94d3249e`, taking `94d3249e^` as the reference: `is_f2 = label in ("F2", "F2/synthetic-glyph-i", "F2/synthetic-glyph-i-both")`, and an `inject_…` helper that asserts the base i is `B7E3456D` and the effect i is `9C60C2B5` before mutating. A mismatch is INCONCLUSIVE.
- Check pins and `f2_manifest_slides` on the original root.
- Apply the mutation to the temp copy right after `copy_minimal`, before the `*_before` snapshots.
- Key expected repairs per label as `(ordinal, rule, to)`. Check the donor page and id only for entries whose `donor` is not None.

Today `f2_checks` indexes `entry["donor"]["page"]`, which raises on D1g's `donor: None`.

Then add `F2/synthetic-glyph-i`:
- Copy the pinned F2 export.
- Set `events[0].baseLayer.layers[3].layers[0].layers[6].texture` from `B7E3456D` to the local winner `DF3DB700`, and sync JSONP.
- Label it **synthetic defect, real object/twin/donor**.
- Expect D2×1 (map) plus D1g×1 → `9C60C2B5`.
- Expect the repair set `{(4,"D2",<graft id>), (4,"D1g","9C60C2B5…")}`. The mutation leaves `B7E3456D` unreferenced, which never happens in a real export, so the row checks D1g picked the twin's id.
- `winnerUnchanged` still holds when computed after the mutation.
- Negative control `F2/synthetic-glyph-i-both`: also set the effect i to `DF3DB700`.
  - Expect `refused` with the exact message `slide 4 (33×135 text): …`; aggregate refusal blocks the map's D2 write too.
  - Snapshot `minimal_tree_sha256(copy)` after injection, immediately before `repair_textures`, and assert it is unchanged after the call.

Every other G1 row keeps its outcome. Missing inputs or pin mismatches are INCONCLUSIVE (exit 3).

**G2 owner-run.**
1. First, look for any surviving record of the failed prepare (log, manifest, source digest).
2. Then the owner exports F2.key twice and compares `minimal_tree_sha256` with `c664279e…`:
   - **Identical:** export is deterministic for this revision, so reproduction needs the historical revision (Keynote version history).
   - **Different:** continue up to 10 serial exports, keep every attempt, and stop at a glyph hit.
3. A captured hit becomes a pinned G1 row before acceptance. Without one, record "real defect not reproduced", not PASS.
4. Then run one normal F2 prepare from the branch, plus the Alpha_DSK regression. Record the texture outcome separately from the slide-8 real-alpha movie refusal.

**G3 owner eye.** Serve the persisted repaired synthetic copy and its unrepaired control. The owner watches all eight letters through the build and the settled slide, especially the i, and checks the map repair is intact.

## 7. Owner questions (recommendations)

**Owner decisions 2026-10-15:**
- OQ-1: any build of this shape, not just Twist & Scale.
- OQ-2: minimal change first, as recommended.
- OQ-3: refuse shared-id twins for now; revisit if it becomes a problem.
- OQ-4: run the two-export check first; restorability of `6fea812c…` is unknown.
  - **Result:** export is nondeterministic. Both new exports (`~/Desktop/StageT-text-glyph-evidence/2026-10-15/attempt-0{1,2}`) carry a real base-glyph collision: attempt-01 on the i (the owner's refusal), attempt-02 on the s. Each victim has a natural-id effect twin. They become pinned G1 rows `F2/attempt-01` and `F2/attempt-02`, each expecting D2×1 + D1g×1. They replace `F2/synthetic-glyph-i` as the positive control; the shared-id negative control `F2/synthetic-glyph-i-both` stays. (Owner, post-merge: the two capture rows were dropped and the captures Trashed; unit tests cover D1g's positive cases.)
- OQ-5: as recommended.
- OQ-6: the removal was intentional; the folder is in the Trash and restorable.
- Go: implement.

- **OQ-1 scope.** Rec: D1g for any same-objectID base/effect per-component build, not just Twist & Scale. Alternative: Twist & Scale only (measured).
- **OQ-2 donor trust.** Rec: accept the object/index twin plus a non-flat donor, on D1's premise, with no OCR or pixel oracle.
- **OQ-3 shared-id twins.** Rec: keep refusing them. There is no donor in the export, and re-export or a source edit is the remedy.
- **OQ-4 reproducer.** Rec: two exports first, then decide (G2). Alternatively, restore the `6fea812c…` revision from Keynote version history.
- **OQ-5 acceptance.** Rec: implement and qualify on the synthetic row now; leave "fixes the lost export" unverified until a capture or an owner waiver.
- **OQ-6 evidence.** `F2-evidence-2026-10-14/` left the owner folder around 14:37 today. Was that intentional? Rec: if it is restorable, keep it read-only as the old-export evidence.

## 8. Revision log

| Rev | Source | Disposition |
|---|---|---|
| r0 | Codex GPT-6 Astra high investigation + plan | Base design |
| r1 | Opus 5.5 high critique r1: 2 major, 4 medium, 4 low | All folded: coverage statement + shared-id refusal (§1, OQ-3); orphan-page route rejected by measurement (§1, G-2, G1); G-1 trimmed to structure, name-agnostic (OQ-1); verify = non-flat donor, record in `_d1g` (G-4); tests cut to 5 params (§5); G2 two-export determinism check first (G2); G-3 one line; fallthrough left as is (G-4); anchors by function name; version 1 kept |
| r2 | Opus 5.5 high critique r2: 1 major, 1 medium, 4 low | All folded: `tc` F2 path generalised for `donor: None` (G1); donor-id-only-at-twin-rect guard + test 6 (G-2, §5); "referenced" replaced by twin's own texture (G-2); `bad_textures` in `_d1g` signature (§2); negative control asserts message + unchanged tree hash (G1); investigation committed at its anchor, `twin` key in `verify` (G-4) |
| r3 | Opus 5.5 high critique r3: 0 blocker/major, 6 low | All folded: victim-content wording (§1); reuse `94d3249e^` synthetic plumbing with pre-mutation asserts (G1); post-injection hash snapshot (G1); write-up corrections (commit, Trash, twin qualifier). Plan critique closed (stop rule). |
