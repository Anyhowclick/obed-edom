# DSK pure clips — owner decisions (2026-09-16) and planner findings

Process = generate → operator modifies live objects in the DSK deck → export. The Exporter's `.mov` is the deliverable; the Generator's clips are intermediates.

Owner decisions:
1. ONE PURE CLIP PER MOVIE ITEM. Each movie item on an FW mixed/movie slide becomes its own pure-video `.mov` (only that movie item rendered; every other drawable deleted before export, side panels included), cropped to that item's rect clipped to the centre panel (or include_side crop), and inserted in the DSK slide at that item's fitted rect through the SAME affine as every other copied object. A slide with two movies gets two inserted movies.
2. Scale stays PER SLIDE (the source authors different sizes across a magic-move chain). Anchor is CHAIN-SHARED: consecutive FW slides linked by an outgoing `apple:magic-move*` transition form a chain; the auto anchor is computed once on the chain head and applied to every member; an explicit per-slide decision.anchor still wins.
3. Generator intermediates live in `output/<FW stem>/dsk/src/` named `<DSK stem>.NNN.MM.src.mov` (NNN = DSK ordinal, MM = movie item index 1-based) and are DELETED after a successful Exporter run on that deck. The DSK deck is retained.
4. Clip slides get a DISSOLVE transition (the source magic move cannot be kept yet). Note in docs: alpha-Keynote work is in flight and may later retain source transitions.
5. The Exporter NEVER reuses Generator clips: every movie/mixed slide of the DSK deck is re-rendered (live overlays baked on top of the pure clips). The flat asset sequence `<stem>.NNN.SS.png` / `<stem>.NNN.mov` contains only Exporter output. manifest.json keeps deck path + `source_slide`; the Generator writes `srcClips` (relative paths) per slide; `clip` is written only by the Exporter. Drop `published_clips`, `existingClip`, `reusedClips`.

Planner findings (verified offline on ~/Desktop/dsk-d4-work/r15/output/DSK_Gen_Export_Input/dsk/DSK_Gen_Export_Input_DSK.key):
- The copied objects were placed correctly (centre anchor). The CLIP was misplaced: `dsk_assemble.py` ~:3257 uses `plan.fits[number][movie_id]` with `movie_id = min(kindIndex)` (~:2150) while the clip content was the whole centre-panel crop.
- The movie insert is ASPECT-LOCKED: the script writes position, width, height (~:3265-3267); the last write re-derives the other dimension and growth goes rightwards. Write size first, position LAST; the requested rect must match the clip media aspect (guard ±0.5%).
- Inserted clip lands at the FRONT of `drawablesZOrder` (`make new image/movie` appends); nothing raises the copied objects. `_restore_crop_zorder` (~:3938) is the model for an offline post-pass; `iwa_write.read_slide_zorder` reads it back.
- `_derive_delete_ids` (`dsk_movie_export.py` ~:772) keeps overlays in the scratch slide, so they bake into the clip.
- `iwa_builds.deck_builds` gives outgoing transitions: FW 11 and 12 magic-move, 13 dissolve. No code reads transitions for anchoring yet.
- Removing overlays from the scratch slide removes their builds from the clip; those builds must survive on the live copies (`verify_builds` tolerates missing but not surplus).
