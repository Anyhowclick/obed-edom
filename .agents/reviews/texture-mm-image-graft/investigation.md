# Stage T refusal on F2.key slide 4: investigation (2026-10-14)

Symptom (dashboard prepare, both attempts): `slide 4 (176×205 image) … ; slide 4 (357×235 image): its texture is
mis-mapped and no verified replacement exists`. Native Keynote plays the deck correctly. Reproduced offline on the
owner-run raw export `~/Desktop/Convert wall to 16x9 CGs/F2-html/` (player `17c0c938`); this export collides only the
176×205 object (exports collide differently each time).

## Cause

- Slide 3 → 4 is a Magic Move that zooms into a map. Three PDF images grow:
  - Asia-Pacific map `pasted-image-44131.pdf`: 582×434 → 5847×4366.
  - Peninsular Malaysia map `44137`: 18×21 → 173×202.
  - A third map `44140`: 36×24 → 354×233.
- Slide 3's MM leaf for Malaysia records `contents.to = DF3DB700`. In **slide 3's** table that page is 176×205 and is the Malaysia map: it scores 0.985 against the source PDF.
- On **slide 4** the Malaysia leaf also uses `DF3DB700`, but slide 4's table assigns `DF3DB700` to the Asia map's 5850×4368 page.
- Slide 4's PDF has 19 pages and none of them is the Malaysia map, so the HTML player draws the Asia map squeezed into the Malaysia slot.

## Why Stage T refuses

The detector finds the fault: R1 (size mismatch) and R6 (the MM landing correlates 0.31). The planner's D2 (graft the
previous slide's `contents.to`) finds exactly one donor: slide 3's `DF3DB700`, 176×205.

`_verify` then returns False. For a non-text, non-movie leaf it has no content check: text has OCR and movies have a
poster correlation. This matches the Stage T plan, which says "images are eligible only with independent pixel
agreement". D1 is text-only, D3 is posters only, and D4 needs a same-slide page, which does not exist here.

## Candidate check: the source asset in the `.key` (measured)

Each candidate below is the source PDF from `F2.key`, compared by thumbnail correlation (64×36 over 50 % grey, the
existing `_thumb`).

| Source | True donor | Wrong current page | Best other page |
|---|---|---|---|
| `44137` Malaysia | **0.985** (s3 `DF3DB700`, 176×205) | 0.319 (s4 `DF3DB700`) | 0.908 (s3 44×50 outline) |
| `44140` third map | **0.996** (s3 `B37026D5`, 357×235) | −0.236 (s4 Asia) | 0.944 (s3 88×59 outline) |

Larger renders (128², 256²) lower the true score more than the negatives' (line art, AA), so 64×36 stays.

Line-art maps are self-similar, so correlation alone is a backstop, not identity. Identity stays Keynote's own MM `contents.to`
(D2, as for text) plus the V1 size/mediabox gate, which excludes the 44×50 / 88×59 pages.

Rejected candidates:
- The MM leaf's own start texture: 0.79 for the true donor vs 0.94 for an unrelated page, so it does not separate.
- The flattened-frame oracle: already rejected by Stage T for overlap/build reasons.

## Notes

- `apply_preview` already loads the source `.key` IWA offline (`html_preview.source_slides`), so the source asset is
  available at prepare time without Keynote.
- Ownership: `preview_textures.py` is Stage T (merged #267). Stage B's branch edits `tests/test_preview_textures.py`, so a
  fix must coordinate that test file.

## Exact identity from export metadata (measured, F2-html slides 3–4)

Each event's `accessibility[]` lists every object with a text (the filename for images) and a `targetRectangle`.

- **Accessibility to IWA:** for every top-level image, the `targetRectangle` equals the IWA object's geometry exactly (|Δ| < 1e-3 on all four values). For example, slide 4 Malaysia is `[589.899, 828.828, 172.872, 201.98]`, which is IWA `15348427`, data `44137`.
- **Accessibility to leaf:** every image entry is enclosed by exactly one event-0 base leaf. The leaf is the frame expanded to whole pixels plus a 1 px border (≤ 4 px), for example `[588, 827, 176, 205]`.
- **The donor gets the same identity:** slide 3's MM leaf `54AC5F2D` encloses the accessibility entry `[939.66, 847.31, 17.81, 20.81]`. That entry is IWA `15355064`, which uses the same data `44137`. Its `contents.to` (`DF3DB700`, 176×205) lands on slide 4's Malaysia leaf rect.

So the identity chain is exact: leaf → enclosing accessibility entry → IWA object → image data id, on both slides, with
the MM `contents.to` linking them. The source-asset correlation becomes a backstop, not the identity.

The weak link is leaf ↔ accessibility entry. It is containment, because leaves carry no id. Two same-file objects with
overlapping frames would be ambiguous, and should be refused.

**Injection option:** the IWA has `TSD.DrawableArchive.accessibility_description` (unset in this deck), which the offline
writer could set to a unique token on the scratch copy. This would only disambiguate the accessibility → IWA step, which
is already exact here. It cannot tag leaves. Whether Keynote exports the description into `accessibility[].text` is
unverified, and testing it needs one Keynote export.
