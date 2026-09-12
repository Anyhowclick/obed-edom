# Plan — mint a retained-object-specific media style (`iwa_write.mint_media_style`)

Worktree `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-gen` @ 1ccefc5.
Decks measured: `~/Desktop/dsk-d4-work/out-r6/Sermon_PK_DSK.key` (OUT), `~/Desktop/dsk-d4-work/Sermon_PK (GW).key` (SRC).

## Facts (measured 2026-09-11)

**F1 — the escape.** In OUT, style `2651144` (`Index/DocumentStylesheet.iwa`) has 21 referrers:
2 retained (`17233774`, `17233775`, both `TSD.ImageArchive`, both in **one** member `Index/Slide-17233776.iwa`,
= kept slide 1 / source slide 8, `path: ["slide:1:top"]` — top-level `drawablesZOrder`, **not** group children,
per `evidence-r5/census_2651144.json`) and 19 in 14 `Index/TemplateSlide*.iwa` members. Hence the global
`patch_media_stroke` is correctly refused by `_escaping_refs` (`src/obed_edom/dsk_assemble.py:1164-1195`).

**F2 — `2651144` is a NAMED root style.** `super = {styleIdentifier: "image-0-imageStyle",
stylesheet: {identifier: "2652388"}}`, no `parent`; `overrideCount: 4`; own `mediaProperties.stroke`
with `pattern.type = "TSDEmptyPattern"`. Archive header: `{identifier, messageInfos: [{type: 3016,
version: [1,0,5]}]}` — no `objectReferences`.

**F3 — Keynote's own precedent for exactly this mint exists in SRC.** `parentToChildrenStyleMap[12]`
of the stylesheet root `2652388` reads `{parent: 2651144, children: [17443837, 17502747]}`. Both are
`TSD.MediaStyleArchive` **in `Index/DocumentStylesheet.iwa`**, referenced only by images on one slide each
(`17443837` ← `17443753`,`17528043` in `Index/Slide-17442890.iwa`; `17502747` ← 4 images in
`Index/Slide-17332778.iwa`). Verbatim shape of `17443837`:

```
header  {"identifier":"17443837","messageInfos":[{"type":3016,"version":[1,0,5],
         "objectReferences":["2651144"]}],"_pbtype":"TSP.ArchiveInfo"}
object  {"super":{"parent":{"identifier":"2651144"},"isVariation":true,
         "stylesheet":{"identifier":"2652388"}},
         "overrideCount":1,
         "mediaProperties":{"stroke":{...solid, width 2.0, frame{...}}},
         "_pbtype":"TSD.MediaStyleArchive"}
```
i.e. a variation carries **only the overridden property** (stroke), not a clone of the parent's properties;
`overrideCount` = 1; header `objectReferences` = `[parent]`.

**F4 — registration footprint of a variation (measured on `17443837` in SRC).**
| place | value |
|---|---|
| `Index/DocumentStylesheet.iwa` | new archive appended (F3 shape) |
| stylesheet root `2652388` `objects[0].styles` | **YES** — appended `{identifier: new}` (577 entries) |
| `objects[0].identifierToStyleMap` | **NO** (460 entries = named styles only) |
| `objects[0].parentToChildrenStyleMap` | **YES** — appended to the parent's `children` (18 parents) |
| stylesheet archive **header** `objectReferences` | **NO**. Measured exactly: that list (487 ids) == the 460 `identifierToStyleMap` styles ∪ the 27 `stylesFor100/101/121` styles; none of the 90 other unnamed styles appear. |
| `Index/Metadata.iwa` component `2652388` `objectUuidMapEntries` | **YES** — `{identifier, uuid:{lower,upper}}`. This map is complete over the member: 572 archives, 571 entries, the only archive absent is the component root `2652388` itself. Same in OUT (535/534). |
| `Index/Metadata.iwa` **referring slide** component `externalReferences` | **YES** — `{"componentIdentifier":"2652388","objectIdentifier":"17443837"}` sits in `Slide-17442890`'s component (14 entries; `2651144` is there too). |
| the referring drawable's **archive header** `objectReferences` | **YES** — `17443753`'s header lists `["17443756","17443757","17443837","17443767"]`; OUT's `17233774` lists `["17233835","17233855","2651144","17233857"]`. The style id occurs exactly once. |

**F5 — id allocation.** `Index/Metadata.iwa` archive `2` is `TSP.PackageMetadata` with
`lastObjectIdentifier` = `17639288` (OUT) / `17636175` (SRC); in both decks that value **equals an existing
archive id** (the `TSP.DataMetadataMap` archive), i.e. it is a true high-water mark. There is no `_next_id`
helper and no archive-creating precedent anywhere in the repo (`iwa_write.py` only mutates existing
archives). Allocation rule: `new_id = int(lastObjectIdentifier) + 1`, then set `lastObjectIdentifier = new_id`,
verified against every archive id in the package before use.

**F6 — chunk/member mechanics.** `keynote_parser.codec.IWACompressedChunk.to_buffer` (codec.py:217) writes
`\x00 + 3-byte length + snappy(64 KiB slices)` — **no object count, no index**; appending an archive to
`chunks[0]["archives"]` is all that is needed structurally. `IWAArchiveSegment.to_buffer` (codec.py:372)
recomputes only `message_info.length`; **headers are written verbatim** — `objectReferences` are never
recomputed, so every header edit in F4 must be authored by hand. `dict_to_message` (codec.py:423) mutates
its input (`del _dict["_pbtype"]`), hence the existing `copy.deepcopy` before `IWAFile.from_dict`
(`iwa_write.py:656`, `:1123`, `:1256`).

**F7 — atomic multi-member write already exists.** `_rewrite_members(deck, {member: bytes})`
(`iwa_write.py:717-762`) writes any number of members in one temp-zip + copy-back-into-the-inode pass,
raising `OfflineWriteCorrupted` only after truncation; `patch_slide_builds` (`iwa_write.py:1326`) is the
precedent for a multi-member edit dict, and `_archive_diff` (`iwa_write.py:1313`) is the
added/removed/changed gate. `patch_deck_geometry`'s `extra_member_edits` (`iwa_write.py:770`) is the
precedent for merging non-slide member bytes into one rewrite.

**F8 — member→component mapping.** Component `locator`/`preferredLocator` equals the member basename:
`Slide-17233776` → component id `17233776`; `DocumentStylesheet` → `2652388`. 27 components in OUT.

**F9 — test fixture gap.** `tests/test_stroke_probe.py:49 _build_deck` builds a 3-member deck with
**no `TSS.StylesheetArchive` root and no `Index/Metadata.iwa`**. The mint needs both, so the fixture must
be extended (below) — the function must not silently skip registration when they are missing.

## Design

New in `src/obed_edom/iwa_write.py`, next to `patch_media_stroke`.

```python
_MEDIA_STYLE_PBTYPE = "TSD.MediaStyleArchive"
_METADATA_MEMBER = "Index/Metadata.iwa"

def mint_media_style(
    deck: Path,
    source_style_id: str,
    drawable_ids: Sequence[str],
    stroke_spec: dict,          # {"width","color",("pattern","rgbspace")} or {"stroke_message": dict}
) -> dict:
    """Mint a Keynote-shaped variation of ``source_style_id`` carrying ``stroke_spec`` as its
    only override, and re-point ``drawable_ids`` at it. Refuses (deck untouched) on any
    precondition failure; never raises except ``OfflineWriteCorrupted``."""
```

Returns
`{"refused": bool, "reason": str|None, "new_id": str, "source_id": str, "drawables": [...],
  "members": [...], "obj_diffs": int, "header_diffs": int, "value_clean": bool}`.

### Data flow (single `_rewrite_members` call over 2 + N members)

1. `objects, id_to_file, _ = _load_deck(deck)`.
2. **Preconditions** (all before any byte is written):
   - `source_style_id` exists, `_pbtype == "TSD.MediaStyleArchive"`, `id_to_file[...] ==
     _STROKE_STYLESHEET_MEMBER`; its `super.stylesheet.identifier` is present and resolves to a
     `TSS.StylesheetArchive` in the same member.
   - `drawable_ids` non-empty; each exists, is `TSD.ImageArchive`/`TSD.MovieArchive`,
     `str(obj["style"]["identifier"]) == source_style_id`, and `id_to_file[d]` is a real member.
   - `_METADATA_MEMBER` present; its `TSP.PackageMetadata` archive found; every owning member of a
     drawable **and** the stylesheet member maps to a component by `locator`/`preferredLocator` (F8).
   - `stroke_spec` validated exactly as `patch_media_stroke` validates (`stroke_message` needs a numeric
     positive `width`).
3. **Allocate** `new_id = int(lastObjectIdentifier) + 1`; refuse if `str(new_id)` is already an archive id
   anywhere in the package (scan `_load_deck`'s `file_ids`) or appears in any component's
   `objectUuidMapEntries`.
4. **Stylesheet member edit** (decode → mutate → re-encode):
   - append the F3-shaped archive: header `{"_pbtype": "TSP.ArchiveInfo", "identifier": new_id,
     "messageInfos": [{"type": <source archive's messageInfos[0].type>, "version": <source's version>,
     "objectReferences": [source_style_id]}]}`; object `{"super": {"parent": {"identifier":
     source_style_id}, "isVariation": True, "stylesheet": {"identifier": <source's stylesheet id>}},
     "overrideCount": 1, "mediaProperties": {"stroke": <spec or _stroke_submessage(spec)>},
     "_pbtype": "TSD.MediaStyleArchive"}`. Type/version are read off the source archive, never hardcoded.
   - stylesheet root: append `{"identifier": new_id}` to `styles`; append `{"identifier": new_id}` to the
     `parentToChildrenStyleMap` entry whose `parent.identifier == source_style_id`, creating that entry if
     absent. **Do not** touch `identifierToStyleMap` or the root archive's header `objectReferences` (F4).
5. **Slide member edits**, one per distinct `id_to_file[d]`: for each drawable set
   `objects[0]["style"]["identifier"] = new_id`, and in its archive header replace the single occurrence
   of `source_style_id` in `messageInfos[*].objectReferences` with `new_id`; refuse if the count is not
   exactly 1 (F4).
6. **Metadata member edit**: `lastObjectIdentifier = str(new_id)`; append
   `{"identifier": new_id, "uuid": {"lower": <u64>, "upper": <u64>}}` to component
   `<stylesheet component>.objectUuidMapEntries` (uuid from `secrets.randbits(64)` twice, re-drawn on
   collision with any existing uuid pair in that component); for each drawable-owning component append
   `{"componentIdentifier": <stylesheet component id>, "objectIdentifier": new_id}` to its
   `externalReferences` if not already present.
7. **Reparse gate**, per edited member: `IWAFile.from_buffer(new_bytes).to_dict()`, then `_archive_diff`
   against the pre-edit decode. Accept only:
   - stylesheet: `added == {new_id}`, `removed == set()`, `changed ⊆ {stylesheet_root_id}`;
   - each slide member: `added == removed == set()`, `changed ⊆ set(drawables in that member)`;
   - metadata: `added == removed == set()`, `changed ⊆ {package metadata archive id}`;
   and the reparsed minted object must equal the authored object **and** its reparsed header
   `objectReferences == [source_style_id]`. Any mismatch → refuse, deck untouched.
8. `_rewrite_members(deck, edits)` once; re-raise `OfflineWriteCorrupted`, convert every other exception
   to `{"refused": True, "reason": f"rewrite failed: {exc}"}` (mirrors `iwa_write.py:1141-1147`).

### Refusal conditions (deck untouched, every one before the write)
empty `drawable_ids`; unknown/mistyped source style; source style outside the stylesheet member; missing
`super.stylesheet` or unresolvable stylesheet root; a drawable that is not image/movie, does not currently
point at `source_style_id`, has no owning member, or whose header does not list `source_style_id` exactly
once; missing `Index/Metadata.iwa` / `TSP.PackageMetadata` / a component for any member involved; a
`lastObjectIdentifier` that is absent, non-numeric, or whose successor is already taken; malformed
`stroke_spec`; any reparse-gate mismatch.

**Multi-member is supported, not refused** — `_rewrite_members` is already atomic across members (F7) and
each extra member costs only one `externalReferences` append. The escape today is single-member anyway (F1).

### `_restore_stroke` integration (`src/obed_edom/dsk_assemble.py:1195-1290`)

`_escaping_refs` already returns `[(ref_id, kind)]` and the retained set is derivable from `media_status`
(`dsk_assemble.py:1069-1091`). Replace the unconditional `_refuse` with:

```python
escapes = _escaping_refs(style["id"])
if escapes:
    retained = _retained_refs(style["id"])          # new: refs whose media_status is (kept, retained=True)
    if retained:
        mint_specs[style["id"]] = (retained, spec)  # spec = the grant OR the width-restore stroke_message
    else:
        _refuse(style["id"], slides, escapes)
    continue
```

- **grant branch** (`pattern in (None, "TSDEmptyPattern")`): `spec = {"width": 5.0,
  "color": (1,1,1,1), "pattern": "TSDSolidPattern"}` — identical to today's `grants` value.
- **width-restore branch** (real pattern, shrunk width): `spec = {"stroke_message": <deepcopy of
  `_resolve_stroke(style_id)` with `width = source_width`>}` — the same message today's inherited branch
  builds, so `leak_widths`/`match["widths"]` entries that escape become mints instead of refusals.
- After the existing `patch_media_stroke` / `patch_stroke_widths` calls, run each mint in turn and record
  `stroke["minted"] = {source_id: {"new_id": ..., "drawables": [...]}}`; a refused mint appends the
  existing-shaped warning `media stroke {id} mint refused: {reason}` and falls back to
  `refused_media`/`stroke["media_refused"]` so nothing silently disappears.
- Keep the refusal when the retained set is empty (nothing to re-point).
- **Group children**: `_collect_stroke_images` (`iwa_write.py:914`) already descends `TSD.GroupArchive`,
  so a nested image is a normal drawable id with its own `style.identifier` and its own archive header —
  re-pointing it needs no group edit. (Measured: the slide-8 pair is top-level anyway, F1.)
- **Inherited-only source style**: the mint reads the source archive only for its message type/version and
  `super.stylesheet`; the resolved stroke comes from `stroke_spec`, so an inherited-only source needs no
  special case. `super.parent` on the minted style points at the *style the drawables referenced*, so the
  rest of the chain still inherits unchanged.

## Steps

1. **`_stylesheet_root(objects, id_to_file)` helper + `mint_media_style` preconditions & allocation**
   (steps 2–3 above), returning refusals only — no writes yet.
   Tests (new `tests/test_iwa_write_mint_media_style.py`, real in-memory decks via the extended
   `_build_deck`, no mocks):
   - `test_refuses_empty_drawables`
   - `test_refuses_unknown_source_style` / `test_refuses_wrong_archive_type` — source id absent /
     pointed at a `TSD.ImageArchive`; assert `refused` and the deck bytes are unchanged.
   - `test_refuses_drawable_not_pointing_at_source` — drawable whose `style.identifier` is the other style.
   - `test_refuses_when_metadata_member_missing` — fixture built without `Index/Metadata.iwa`.
   - `test_refuses_when_new_id_already_taken` — Metadata `lastObjectIdentifier` set to `899` while archive
     `900` exists; assert reason names the collision.

2. **Extend the fixture**: `tests/test_stroke_probe.py::_build_deck(..., stylesheet_root=False,
   metadata=False)` — when set, emit a `TSS.StylesheetArchive` (id `950`) with
   `styles=[{900},{901}]`, `identifierToStyleMap` for both, `parentToChildrenStyleMap=[]`, a header whose
   `objectReferences` list the two named styles, and an `Index/Metadata.iwa` with `TSP.PackageMetadata`
   (`lastObjectIdentifier: "1000"`, components for `DocumentStylesheet`/`Document`/`Slide-100`, the
   stylesheet component's `objectUuidMapEntries` covering `900`,`901`). Styles `900`/`901` gain
   `super.stylesheet = {identifier: 950}`.
   Test: `test_build_deck_stylesheet_root_round_trips` — `_load_deck` sees `950`, `900`'s
   `super.stylesheet.identifier == "950"`, and Metadata decodes with 3 components.

3. **Archive minting + stylesheet registration** (step 4).
   Tests:
   - `test_mints_variation_archive_shaped_like_keynote` — asserts the new object equals, field for field,
     `{"super": {"parent": {"identifier": "900"}, "isVariation": True, "stylesheet": {"identifier": "950"}},
     "overrideCount": 1, "mediaProperties": {"stroke": <the 5pt white solid message>},
     "_pbtype": "TSD.MediaStyleArchive"}` (the F3 shape).
   - `test_minted_archive_header_references_parent` — reparsed header `messageInfos[0]` has
     `type` and `version` copied off style `900` and `objectReferences == ["<new_id>"]`… precisely
     `== ["900"]`.
   - `test_registers_in_styles_and_parent_map_only` — `styles` gained exactly `new_id`;
     `identifierToStyleMap` unchanged (len and contents); `parentToChildrenStyleMap` has one entry
     `{parent: 900, children: [new_id]}`; the stylesheet root's header `objectReferences` is **unchanged**.
   - `test_resolve_stroke_reaches_minted_style` — `_resolve_stroke(new_id, objects)` returns the new
     stroke with `inherited is False`.

4. **Drawable re-pointing incl. header `objectReferences`** (step 5).
   Tests:
   - `test_repoints_only_named_drawables` — `300`,`301` minted; `303` (group child) and `304` still point
     at `900`; then a second test `test_repoints_group_child_drawable` mints `303` and asserts the group
     archive `250` is byte-identical while `303["style"]["identifier"] == new_id`.
   - `test_rewrites_drawable_header_object_references` — the drawable archive's reparsed header
     `objectReferences` contains `new_id` and no longer `900`, with the rest of the list order preserved.
   - `test_refuses_when_header_reference_count_is_not_one` — fixture drawable whose header lists `900`
     twice; assert refusal and unchanged deck.

5. **Metadata updates** (step 6).
   Tests:
   - `test_bumps_last_object_identifier` — `lastObjectIdentifier == new_id` after the mint.
   - `test_adds_uuid_map_entry_for_minted_style` — the stylesheet component gains exactly one entry whose
     `identifier == new_id` and whose `uuid.lower`/`uuid.upper` are non-zero decimal strings distinct from
     every other entry.
   - `test_adds_external_reference_to_each_drawable_component` — `Slide-100`'s component gained
     `{"componentIdentifier": "950-component", "objectIdentifier": new_id}` exactly once; minting twice on
     two drawables in the same member does not duplicate it.

6. **Reparse gate + atomic write** (steps 7–8).
   Tests:
   - `test_only_expected_members_change` — `changed_members(original, deck) ==
     {"Index/DocumentStylesheet.iwa", "Index/Slide-100.iwa", "Index/Metadata.iwa"}`
     (same helper as `tests/test_iwa_write_media_stroke.py:153`).
   - `test_refuses_and_leaves_deck_untouched_when_reparse_adds_extra_archive` — monkeypatch the encode
     step to inject a second archive; assert `refused` and byte-identical deck (mirrors
     `test_refuses_when_reparse_stroke_does_not_match_requested_message`).
   - `test_mint_survives_reload` — after the mint, a fresh `_load_deck` + `card_styles` reports the new
     style with `refs == len(drawables)`, `width == 5.0`, `inherited is False`, and style `900`'s own
     stroke unchanged.

7. **`_restore_stroke` escape branch** (`dsk_assemble.py`): add `_retained_refs`, route escaping styles
   with a non-empty retained set to `mint_media_style`, report `stroke["minted"]`.
   Tests (`tests/test_dsk_assemble_stroke.py`, extending the existing assembly fixtures):
   - `test_escaping_style_with_retained_refs_is_minted_not_refused` — a fixture whose style is also used
     by a template-slide image; assert `stroke["minted"]["900"]["drawables"] == [retained ids]`, the
     template image still points at `900`, and `900`'s stroke is unchanged.
   - `test_escaping_style_with_no_retained_refs_still_refuses` — `stroke["media_refused"]` as today,
     `"minted" not in stroke`.
   - `test_width_restore_escape_is_minted_with_source_width` — real pattern, shrunk width; the minted
     style's stroke equals the resolved source stroke with `width == source_width`, colour/frame preserved.
   - `test_mint_refusal_falls_back_to_refused_media` — monkeypatch `mint_media_style` to refuse; assert
     the warning text and that the style lands in `stroke["media_refused"]`.

## Acceptance

- **Offline**: full `pytest` suite green, including the new modules; plus a one-shot probe (scratchpad,
  not committed) minting on a **copy** of `out-r6/Sermon_PK_DSK.key` for `2651144` /
  `["17233774","17233775"]` that asserts: exactly 3 members changed; the 19 template refs still resolve to
  `2651144` with `TSDEmptyPattern`; `card_styles` reports the new style with `refs == 2`, `slides == [1]`,
  white 5pt solid; `lastObjectIdentifier` bumped by 1; `Slide-17233776`'s component carries the new extref.
- **Live (one round-trip, Accessibility + hands-off Keynote window)**: open the minted copy in Keynote,
  confirm slide 1 shows the white 5pt border on both images and that the template/layout thumbnails are
  unaffected, then Save (⌘S) and close. Re-read the saved deck offline and assert Keynote **kept** the
  minted style: an archive still exists whose `super.parent == 2651144`, `isVariation` true, referenced by
  `17233774`/`17233775`, with the 5pt solid stroke; no `Damaged`/recovery dialog; deck size within ±1 % .
  A Keynote rewrite that re-ids the style is acceptable as long as the stroke and the two referrers survive;
  a style that reverts to `2651144` or a border that disappears fails the gate.

## Open questions (design-changing only)

1. **`saveToken`** — every component in `Index/Metadata.iwa` carries one (e.g. stylesheet `saveToken`),
   and the plan leaves them untouched (we rewrite the whole package, never an incremental save). If the
   live round-trip shows Keynote rejecting or re-writing the package, the mint must also bump the touched
   components' `saveToken`, and that changes step 6. No offline evidence either way.
2. **`TSD.MediaStyleArchive` `frame`** — the grant branch's `_stroke_submessage` emits no `stroke.frame`,
   while the measured Keynote variation `17443837` carries `frame: {frameName: "Formal Shadow",
   assetScale: 1.0}` (inherited from its parent's picture frame). If the house 5pt white border must not
   pick up the parent's frame, the minted stroke needs an explicit frame-clearing field — which the
   protobuf may not permit on a variation. Confirm the intended visual before step 3.
