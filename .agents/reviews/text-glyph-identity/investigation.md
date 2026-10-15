# Text-glyph texture collision: investigation (2026-10-15)

Plan: `.agents/plans/keynote_export_texture_text_identity.plan.md`.

Roster:
- Investigation: Codex GPT-6 Astra high (read-only).
- Critique: Opus 5.5 high, rounds 1–3. Raw rounds are kept in the session scratchpad only.
- Coordinator: spot-checked every load-bearing claim marked ✔.

No repo code was changed. No repair writer, pytest, Keynote, osascript, Chrome or OBS was run.

## Symptom
The owner's G2 live prepare of F2.key `6fea812c…` refused with this message:

> slide 4 (33×135 text): its texture is mis-mapped and no verified replacement exists

That export was not kept. The current F2.key `f99a68ef…` (export tree `c664279e…`) does not reproduce the refusal: the texture step is D2×1 on a map, with no glyph hit.

## Reproducer status
**No kept export reproduces a glyph collision.** The full `_load`/`_detect` survey covered 49 exports:
- F2 current and old;
- `Continuity/*-html` and `q7-fixtures`;
- main-checkout `output/fixtures` (alpha-dsk-textures, qual-decks, gl-decks, minimal-alpha-dsk, the p2-* sets);
- 3b9019 and 59cb previews.

It found no glyph hit, and F2 slide 4 is the only per-letter build anywhere in the corpus. F2 slide 8's `bc-zoom-big character` exports one whole-text texture.

## How Keynote exports a per-letter build (F2 slide 4, "Malaysia", automatic Twist & Scale) ✔
- Each letter is its own type-6 leaf, exported twice:
  - base copy: `events[0].baseLayer.layers[s].layers[0].layers[k]` (s = 3 now, 4 in the old export);
  - effect copy: `events[0].effects[0].baseLayer.layers[k].layers[0]`.
- The base wrapper, the effect and its baseLayer share objectID `E9B8691F…`.
- The 8 twins have identical rects, `initialState` and `texturedRectangle`.
- Glyph leaves carry no objectID or character range.
- Accessibility holds one whole-string "Malaysia" box, in event 1 only. A glyph's IoU against it is 0.03–0.10, so `_text_key` is None.
- Repeated letters get distinct ids and pages: the three a's are three ids.
- k follows Latin left-to-right order here. It is a render-component index, not a proven Unicode offset.
- The source IWA build reads "All at Once" (`kTextDeliveryByObject`), so source delivery labels cannot predict glyph exports.

Glyph sizes: M 103×121, a 77×103, l 28×131, a 76×103, y 76×128, s 61×103, **i 33×135**, a 77×103. The refused leaf is the i.

## Why a glyph can collide ✔
Slide 4 recycles slide 3's texture ids onto its own base-layer objects:

| id | Slide 3 | Slide 4 now | Slide 4 old |
|---|---|---|---|
| `B7E3456D` | 5850×4368 map | 33×135, **base i only** | 8×149 object |
| `9C60C2B5` | — | effect i only (slide-4-unique) | **both** i twins |
| `DF3DB700` | 176×205 | 357×235, two users (live map collision) | 5850×4368, two users |

- The base and effect i pages are pixel-identical: indices 9/16, thumbnail corr 1.0, max diff 0.
- Players resolve ids per slide table. A collision bites when two incompatible users share one local entry: the table keeps the winner's page.
  - Measured across 11 collided slides in 7 exports: pages equal table entries 1:1, with 0 orphan pages, 0 unreferenced ids and 0 shared pages. The victim's content survives only under another leaf's referenced id (D1/D3's routes) or not at all (F2 176×205, Alpha s10 labels). So there is no orphan-page donor route.
- **Inferred:** the lost export most plausibly gave the i's recycled base copy a colliding id, while the effect copy kept its natural id. If both copies shared the bad id (as in the old export's id pattern), no in-export donor exists, and refusal is correct.
- Every collided object in the corpus that has a same-event twin (3 of 3) shares the bad id with that twin. None has a base/effect twin with a different consistent id; only qual-D2's renderMovie poster differs, and D3 already repairs from it.

## Source evidence considered

| Evidence | Verdict |
|---|---|
| Same-event objectID + index-k twin (base ↔ effect) | Independent of the texture id. **Chosen** (D1g). It proves identity, not pixels. |
| IWA text storage | Gives the string and font (`Malaysia`, AmplitudeCond-Bold 180 pt), but no glyph placements. Would need a layout engine; rejected. |
| Accessibility | Whole string only, and absent at build onset. Rejected for glyphs. |
| Single-glyph OCR | Vision returned nothing for i/l/a. Unreliable; rejected. |
| Geometry / order | Consistent with Latin order, but no general Unicode, ligature or bidi mapping. Not used as identity. |
| Orphan PDF page | None exist. Rejected. |
| Pixels | Comparing a donor with itself is circular. Used only to require that the donor is non-flat. |

## How to get a reproducer
All of these are owner-run.
1. Look for any surviving log or manifest from the failed prepare.
2. Export F2.key twice into `~/Desktop/StageT-text-glyph-evidence/<date>/` and compare tree hashes with `c664279e…`:
   - **Identical:** export is deterministic, so restore `6fea812c…` from Keynote version history.
   - **Different:** export up to 10 times, keeping each attempt.
3. Otherwise, the owner authors a small Magic Move + per-letter-build deck.

Offline, the labelled synthetic `F2/synthetic-glyph-i` (base i → `DF3DB700`) is the positive control. A probe of the mutation in memory showed R1 flags it, and D1, D2 and D4 all return None today.

## Side findings
- `~/Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/` was removed from the owner folder at about 14:37 during this session, together with `F2-78.key`, `author` and `live-c155` per the critic. This session did not do it, and it could not be confirmed in the Trash: the coordinator's `ls ~/.Trash` was denied, and the critic's grep found nothing. Its old-export numbers above were read before it left.
- `tc` dropped the `F2/synthetic-357` row at the owner-edited-deck re-pin (`94d3249e`). The gate record still describes it.
- The gate record's "33×135" refusal sits beside a size description of the map hit that reads in reverse. The current R1 is the 176×205 leaf on the 357×235 winner.

## Owner questions (recommendations; details in plan §7)
1. **Scope:** should D1g apply to any same-objectID base/effect per-component build? (Rec: yes. Alternative: Twist & Scale only.)
2. **Donor trust:** is an object/index twin plus a non-flat donor enough proof, on D1's premise, with no pixel or OCR oracle? (Rec: yes.)
3. **Shared-id twins:** keep refusing them, with re-export or a source edit as the remedy? (Rec: yes.)
4. **Reproducer:** run the two-export determinism check first? Is the `6fea812c…` revision restorable from Keynote version history? (Rec: two exports first.)
5. **Acceptance:** implement and qualify on the synthetic row now, and leave "fixes the lost export" unverified until a capture or a waiver? (Rec: yes.)
6. **Evidence:** was removing `F2-evidence-2026-10-14/` (plus `F2-78.key`, `author`, `live-c155`) intentional? Can it be restored read-only?
7. **Go:** approve implementation (Sol high → Opus review → full suites → G1, then owner-run G2/G3)?

## Reproducer captured (2026-10-15, after owner approval)
I ran two serial exports of the unchanged F2.key (`f99a68ef…`, same hash before and after) with `export_html`. Keynote was free and peers had a "need window"; Keynote was quit after each run. Outputs are in `~/Desktop/StageT-text-glyph-evidence/2026-10-15/attempt-0{1,2}`, together with the logs, `tree-hashes.txt` and `detector.txt`.

**Export is nondeterministic**: tree hashes `1c1291ef…` and `c6627004…` both differ from `c664279e…`. The recycled slide-3 ids `B37026D5` and `DF3DB700` land on different **base** letters each time. The effect copies always keep their natural ids.

| Export | Base letter on `B37026D5` (357×235) | Base letter on `DF3DB700` | Hits |
|---|---|---|---|
| F2-html (`c664279e`) | none (base i on `B7E3456D`, fits) | none | map R1 + R6 |
| attempt-01 (`1c1291ef`) | **i, 33×135 → R1** (the owner's refusal) | s (61×103 entry, corr 1.0 to its twin) | i R1; map R1 (176×205 on 61×103) + R6 |
| attempt-02 (`c6627004`) | **s, 61×103 → R1** | i (33×135 entry, corr 1.0 to its twin) | s R1; map R1 (176×205 on 33×135) + R6 |

- Each victim letter's effect twin keeps a natural, slide-unique id: i `9C60C2B5`, s `A7274F8D`. That is D1g's case.
- The letter that wins the shared entry renders correctly.
- The map victim each time is D2's existing route.
- The "inferred" coverage claim in plan §1 is now **measured** on two real exports.
