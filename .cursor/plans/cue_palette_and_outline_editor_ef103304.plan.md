---
name: Cue palette and outline editor
overview: "Read `.cursor/skills/obed-edom/SKILL.md` first — every durable Keynote finding lives there. This plan holds only what is still to do plus the reasoning a new agent would otherwise rediscover. DONE (in SKILL / git log, condensed below): Keynote 15.x migration, framing confirmation, badge-affine, structural title detection, the divider, ranges in Keynote's numbering, off-frame hiding, and the per-slide side-panel whitelist. STILL TO DO: the number block in the CG resizer; the cue-first palette; the in-dashboard outline editor; image cues; the DSK generator; stat-drift; recipe library (revisit now badge-affine exists). Operator/source or won't-fix leftovers: slide 125's grouped church names, the sparkle-overlay-on-words placement, a caption in the 'as it will look' preview, and a verse's wall-authored hard line breaks (a source-deck fix — stripping them by script destroys the un-scriptable superscript numbers and small-caps LORD)."
todos:
  - id: text-placement
    content: "CG resizer number block (183/86/14/269) rendered as overlapping fragments — groups all parked at one left margin. DONE (Session 6, PR #32): packed into non-overlapping columns. Sizing the inner text is a separate limit — see gui-ungroup-stats."
    status: completed
  - id: gui-ungroup-stats
    content: "TO-EXPLORE (immediate): the stat blocks (183/269/86/14/44…) are opaque groups (childCount=0), so their inner numbers can't be read or resized to match the template — only moved. Probe GUI-scripting ⇧⌘G ungroup via System Events (like the superscript pass); if it works, needs an ungroup pre-pass + re-inspect, and the template to teach sizes. If not, stays a source-deck ungroup. See 'Immediate TO-explore' below."
    status: pending
  - id: cue-palette
    content: "Cue-first palette in the dashboard, inverting masters.yaml cue maps, with adjacency and context rules enforced. Pending — design below."
    status: pending
  - id: outline-editor
    content: "Editable outline view extending OutlineResultView, LibreOffice page-view toggle, in-place surgical writes to the source .docx with timestamped backups. Pending — design below."
    status: pending
  - id: image-cues
    content: "Image cues as an asset slot count + shape per cue. Both capabilities (image place, movie via file-name reassign) probed and present. Pending — taxonomy below."
    status: pending
  - id: dsk-generator
    content: "DSK generator, unchanged from the superseded plan including its four corrections. Pending."
    status: pending
  - id: stat-drift
    content: "Validation rule slide.stat_drift: a figure that changes between adjacent slides then holds. Ships at warning. Independent of everything; can land anytime. Pending — below."
    status: pending
  - id: recipe-library
    content: "Recipes as browsable artefacts. Built then reverted: a page needing a borrowed transform usually needs two affines, the same gap seen from the other side. Revisit now badge-affine exists. Pending — reasoning below."
    status: pending
  - id: side-panel-whitelist
    content: "Per-slide side-panel whitelist. DONE (feat/side-panel-whitelist). Drop side content by default, keep per whitelisted slide via keepSideContent Decision. See git log."
    status: completed
  - id: operator-notes
    content: "Session 4: operator IMPORTANT callout in the CG resizer + a whitelist view in the Reviewed tab + prettier checkboxes. DONE (feat/resize-operator-notes). Frontend only."
    status: completed
  - id: offscreen-hiding
    content: "Off-frame content hidden not skipped, so the 16:9 canvas-shrink can't scale it back on-frame. DONE. See git log e7621f8."
    status: completed
  - id: badge-affine
    content: "A badge gets its own plate-to-plate affine. DONE and measured. See SKILL + git log."
    status: completed
  - id: title-structural
    content: "Find the title structurally (phrase match, then the one-word plate) not by wording. DONE."
    status: completed
  - id: keynote-15-migration
    content: "Keynote 15.x migration: bundle-id targeting, version-tagged cache, 14.5 deleted. DONE. Findings in SKILL."
    status: completed
  - id: framing-confirm
    content: "Two-phase framing confirmation grouped by framing with projected wall previews, decisions remembered by digest. DONE."
    status: completed
  - id: navigator-numbering
    content: "Dashboard reads a range in Keynote's numbering from the cached full payload; CLI keeps document positions and says so. DONE."
    status: completed
isProject: false
---

# Cue palette and outline editor

Supersedes `keynote_file_format_spike_6b4ae4c2.plan.md`. Everything in that plan
still stands except item 3 (live preview), dropped for the reasons below.

**Read `.cursor/skills/obed-edom/SKILL.md` first.** Every durable finding — bundle-id
targeting, the verified scripting limits, cache versioning, the template contract —
lives there. This plan holds only what is still to be done and the reasoning a new
agent would otherwise have to rediscover.

## Completed work — pointers, not detail

All of the following shipped; the durable findings are in SKILL.md and the
reasoning is in the commit messages (`git log`). Condensed here so this plan stays
about what is left.

- **Keynote 15.x migration** — bundle-id targeting through the single resolver in
  `keynote_app.py`, version-tagged cache, 14.5 deleted after an A/B pass, gold decks
  re-warmed. In SKILL.
- **Framing confirmation** — `/api/resize` is a two-phase job (propose, then apply
  after the operator confirms), reviewed in `FramingReview.tsx` grouped by framing,
  each candidate a real wall preview under the planner's own affine. Decisions
  remembered by digest.
- **A badge gets its own affine** — plate-to-plate, so a page with a map and a badge
  gets two affines. On the report card's 34 map-and-badge pages the plate went from
  117/136 placements off-frame to none. `_title_badge`, `badge_plate_members`,
  `template_badge_slots`, `badgePlateDst`. In SKILL/commits.
- **Structural title detection** — phrase match first, then the plate (largest shape
  containing a text item's centre) where that plate carries exactly one word.
- **Off-frame hiding (`e7621f8`)** — changing the wall copy to 16:9 makes Keynote
  scale-to-fit every object it still owns, so a *skipped* object gets dragged back
  on-frame. `plan_slide_transforms` now emits a zero-opacity hide for off-screen
  leftovers and magic-move duplicates; `remap_keynote.js` deletes `role="hide"`
  groups (opacity can't hide a group). This is why the operator must delete skipped
  slides and ungroup side content — see the resizer's Important callout.
- **Per-slide side-panel whitelist (`14ef262`, fix `7f1fa59`)** — side content dropped
  by default, kept per whitelisted page via `Decision.keep_side_content` (orthogonal
  to framing state, stored by digest). Threads through `plan_payload_transforms`
  (`side_content_slides`), `remap_keynote`, the `/api/resize` endpoints, and the
  framing review's per-page toggle + bulk action. CLI `--include-lists` stays the
  global override.
- **Ranges in Keynote's numbering** — the dashboard translates a typed range from the
  cached full payload when there is one, else says it is taking the range as document
  positions; the CLI keeps document positions and says so in `--help`.
- **The text and framing batch (`23a8dcd..52b13cd`)** and the **Session 2 batch
  (`cdaf271..ceaff9d`)** and **Session 3 batch** (off-frame hiding + whitelist, on
  `feat/side-panel-whitelist`) — real-run review fixes: text keeps its source font
  and colour, scripture body in the template box, centre-panel 1:1, sparkle overlays,
  church-list drop over the map, magic-move de-dup, off-screen skip + body fit,
  corner labels, cover-vs-letterbox, badge colour-reject, LW side-panel drop, verse
  bold-run preservation, sibling-affine magic-move reuse. Each has its reasoning in
  its commit message; the mechanisms are locked by tests.
- **Session 4 (`feat/resize-operator-notes`)** — operator-facing polish, frontend
  only: an Important callout at the top of the CG resizer (delete skipped slides;
  ungroup side content or it reads as centre; close Keynote first; check box edges;
  check text line breaks), a whitelist filter in the framing review's Reviewed tab
  (funnel; kept-only + by-template; green dot on whitelisted chips), pill toggle
  switches replacing every checkbox, and a hazard-tape warning callout style.
- **Session 5 — `fit_to_frame_recipe` fills instead of letterboxing (PR #31).** The
  fallback (used when no template framing pairs) fitted the whole visible union with
  `min()`, so a centre panorama two frames wide shrank to a postage stamp (`s≈0.48`)
  where the human simply cropped it to one frame at native size (`s=1.0`). It now
  biases from fit toward cover, bounded three ways: never crop the binding dimension
  past `FILL_MAX_CROP_FRACTION`, and never enlarge past 1:1 native — so a wide
  panorama fills and a map already small enough to fit is left whole. Measured offline
  against gold: map+pin `goldRmse` −15.3% over 72 rows, **14 improved / 0 regressed**
  (slide 1 map 566→51, pin 334→43); matched-framing slides untouched. The cap was
  tuned by a sweep: shallow minimum at **0.47** (0.46–0.48 within noise), worsening
  past ~0.49 because the native 1:1 cap makes higher values just reach full cover,
  overshooting the human crop — so 0.47, not higher. Two tests in `test_scoring.py`.
  This is the one code-side gold-closeness win found in the resizer-refinement dive;
  the rest of the gold-distance is editorial crop choice (SKILL's documented trap —
  solved by the framing UI + more template slides) or scoring artefacts
  (title/badge/list rows).

- **Session 6 — pack the left-column number-block groups (PR TBD).** On slide 4 of
  `Map_Extracted_Wall_1st` (report card slide 124) the "183/86/14/269" stat block
  lives in 4 groups that the matched template affine (centred on the map art) throws
  off the frame's left edge, so `plan_slide_transforms` parked each individually at
  `Rect(16, mapped.y, wall_w, wall_h)` — groups can't be scaled — and they stacked
  into overlapping fragments. Now a branch-time flag collects the parked-left groups
  and a post-pass `_pack_left_groups` re-places them via a new
  `pack_columns_from_left` (left mirror of `pack_columns_from_right`, stepping to the
  next column by the column's *max* width so unequal-width boxes don't collide),
  sorted by wall reading order. Called unconditionally (not under `pack_lists`),
  moves only (wall size kept), the "roughly right, staff-nudge" contract lists use.
  Verified offline: the 4 groups pack into two non-overlapping columns; map/pin
  placement byte-identical; 324 tests pass (2 new). **Out of scope, still open:**
  slide 124 has a separate ~130×11px overlap between two *right-side* groups
  (`mapped.x ≥ 16`, so not parked/packed); and slide 125's church list is 46 opaque
  groups / 163 overlaps including a full-wall 7123px group — the documented source-deck
  grouping fix (ungroup), not a code fix here.

- **Session 7 — delete hides (PR #33, merged) + out-of-range range guard (PR open).**
  (a) Non-group `role="hide"` objects were left at `opacity=0` — invisible but still
  catching clicks, so the operator kept selecting a zero-opacity ghost instead of the
  text to edit. `deleteGroupHides` → `deleteHides` now deletes every hide after both
  geometry passes (grouped by kind, descending index; falls back to `opacity=0` if a
  delete is refused). Two independent sub-agent reviews confirmed no `applyTransforms`
  path skips a hide without deleting it. (b) A slide range past the deck's last slide
  (slide 124 fed to a 9-slide extract) used to inspect/propose nothing and leave a
  blank framing screen; `_assert_range_within_deck` now errors, using `slideCount`
  (the whole deck's length even on a ranged read) as the ceiling.

## Immediate TO-explore: GUI-script ungrouping the stat blocks

The number-block stats — "183 CHC Churches", "269 Total Churches", "86 Affiliate",
"14 Countries", "44 Renovated Church Buildings" — are each an **opaque group**: the
inspect shows every one with `childCount=0`, `text=""`, no readable `size`. So the
resizer can only *move* them at wall size (Session 6's packing); it cannot read or
resize the inner "269" to match the template. Two limits stack: grouped children are
invisible to Keynote scripting, **and** a group can't be scaled (setting a group's
width does not scale its children). Keynote exposes no ungroup command, so today the
only fix is to ungroup in the source deck (same as slide 125).

**Worth a probe:** GUI-script an **ungroup pass via System Events** — select each stat
group and send **⇧⌘G** (Arrange ▸ Ungroup), the same mechanism the superscript pass
already drives through the Format menu (needs Accessibility; see SKILL `## Later verse
numbers need Accessibility`). If it works, the freed text items become addressable and
resizable, turning a source-deck chore into a code fix.

*Design if it works.* Planning runs off the inspect **before** apply, and ungrouping
changes the object model the plan was built from. So this needs an ungroup **pre-pass**
on the copy, then a **re-inspect** (of at least the affected slides) so the freed text
is planned as real items. And the template must *teach* the freed text's target size —
a swatch per number/label style, or the stats laid out ungrouped at CG size — or the
freed text just rides the ~0.85 crop scale (the same "template must teach it" caveat as
any unpaired text).

*Probe to write* (like `probe_zorder.js` / `probe_corner.js`): build a throwaway deck
with a grouped number+label, drive ⇧⌘G through System Events, and check whether the
children become addressable afterwards (`childCount>0`, text/size readable). If yes,
scope the pre-inspect ungroup pass; if no, it stays a source-deck fix and this note
records that the door was tried.

## Handover — CG resizer state (2026-08-27)

- **Merged:** PR #31 fill fallback (`FILL_MAX_CROP_FRACTION=0.47`), #32 number-block
  packing, #33 delete-hides. **Open PR:** the out-of-range range guard.
- **Source-deck / operator items (no code fix today):** slide-124 ~130×11px overlap
  between two right-side groups (`mapped.x ≥ 16`, not parked); slide-125 church list
  (46 opaque groups); the stat-block *sizes* — ungroup, but see the TO-explore above,
  which could turn the stat-size case into a code fix via GUI ungroup.
- **Next code candidates:** the GUI-ungroup probe above; the recipe library (now that
  a badge carries its own affine); then the cue palette / outline editor / image cues /
  DSK track.

**Known and deliberate, not a bug:** a badge can land correctly and still be buried
by map art that was already above it — the resizer inherits the source deck's
stacking and Keynote exposes no way to change it (z-order is neither readable nor
settable; in SKILL). It reads as a clipping bug; it is a source-deck or template fix.

## The number block in the CG resizer (immediate)

The map geometry is correct as of `cd83162`. Of the three text defects recorded
against `Map_Extracted_Wall_1st.key` slide 4, one remains:

**The 183 / 86 / 14 / 269 number block renders as overlapping fragments.** Not a
text bug. Those figures live in groups, and `plan_slide_transforms` parks every
left-column group at `x = 16` while restoring its *wall* size, because the map affine
would otherwise throw it off the left edge and setting a group's width does not scale
its children. Five groups land in one column with heavily overlapping y ranges —
planned rects `(16, 175, 537x271)`, `(16, 326, 496x383)`, `(16, 388, 199x258)`,
`(16, 584, 237x258)`. This is the negative-space problem: the groups need packing
against each other, not a shared left margin.

**Two hypotheses still open, for loose text only** (not groups). Answerable from one
instrumented planning run — planning the whole deck takes 0.17s off the warm cache.

- **H15 — the `TEXT_DOWN_SCALE` clamp sizes text boxes at a different scale than the
  one that positions them.** In `_style_text_box` (`map_remap.py:1520-1525`) an
  unstyled text item takes `scale = min(aff.s, TEXT_DOWN_SCALE)` (`0.42`, line 37)
  for width/height/font, while its top-left comes from `aff.apply_rect(...)` at the
  full `aff.s` (0.8547 here). *Evidence:* log `aff.s`, the clamped `scale`, and src vs
  mapped rect per text item; check whether the clamp bound.
- **H16 — `match_character_style` finds nothing for these items, so they fall into
  H15's path** instead of using the template's real font size. The styled branch
  (1512-1519) scales by `ratio = dst_size / wall_font`. *Evidence:* log the matched
  style or `None`, plus `dst_size`, per text item.
- **H19 — Keynote reflows text on the size pass and the position pass can't correct
  it.** `applyGeom` runs full-then-position-only because setting width/height yanks an
  object to (0,0), but setting `objectText.size` can trigger autofit and the second
  pass restores position without re-checking size. Needs a real Keynote pass. Worth
  raising up the order — the same shape of defect was real for lines, where endpoint
  writes silently undid the size.

Resolved, do not re-investigate: the badge (was H18 — took the title affine; now
lands on the template's own rects); the badge looking clipped (source-deck stacking,
no code fix); "Oct 2024 – Sep 2025" truncation; H17 (the block is groups sharing a
left margin, not text on one `listDst`).

## Decision: live preview is dropped, cue discovery replaces it

A preview is only worth building if it answers faster than editing the document
does. A Keynote round trip cannot, and a browser overlay would still be an
approximation. Editing the outline and typing a cue is faster, so the preview is cut.

The real problem was never "does this copy fit" — it is that the cue vocabulary is
invisible. Nine semantic cues today, with adjacency rules and context variants, and
it grows. So the work becomes: **show the operator the layouts the template actually
has, and let them insert the cue that produces one.**

## The palette: layout and cue are many-to-many

Mirroring Keynote's "Choose a Layout" panel one-for-one would be wrong.
From `src/obed_edom/masters.yaml`:

- `BLANK` backs `[FILLER-QR]`, `[GIVING-OPTIONS]`, and offering-context `[FILLER]`.
- `VERSES` backs both `[VERSE]` and `[VERSE-CONTINUED]`.
- The four POST layouts have no cue of their own — they come from
  `[VERSE-AFTER-POINT]`, valid only directly after `[POINT]`/`[NUM-POINT]`, which
  also drives the 1s Magic Move.
- `TITLE` backs `[TITLE]` and sermon-context `[FILLER]`.
- DSK adds selection by length, not cue: `Verse 1 Line (Variation 2)` vs
  `Verse Standard (Variation 2)` is decided by `verse_char_one_line`.

So the palette is **cue-first**, each entry carrying the layout thumbnail(s) that cue
can produce, the context that picks between them, and its adjacency rule. That
inverts the existing `lw.cues` / `dsk.cues` maps rather than adding a second source
of truth.

## Layout thumbnails: derive per template, cache by digest

`Default Templates/` is empty and gitignored, so templates are always dropped and
thumbnails cannot be pre-baked. Keynote's `export` works on documents, not layouts:

1. Copy the dropped template to a scratch path (never touch the original).
2. Enumerate layouts — `remap_keynote.js` has the pattern (`doc.slideLayouts()`,
   `layoutNames()`, ~lines 543-567).
3. Append one empty slide per layout with `{base slide: theMaster}`, as
   `keynote.py` ~line 792 does.
4. Export slide images, keep one PNG per layout name, discard the scratch deck.
5. Cache under `<cache root>/layouts/{template_digest}/`, reusing `deck_digest()` and
   the `INSPECT_VERSION` discipline in `baseline.py`. Cache root is `.cache/` at the
   repo root now, not under `output/`.

New endpoint `GET /api/template-layouts` taking a template path, returning layout
names, thumbnail URLs, and the cues each layout is reachable from. Layouts no cue
reaches are returned as unmapped — that list is the honest answer to "what can the
template do that the tool cannot ask for". Both capabilities were probed on 15.3.1
and are present (`doc.slideLayouts()` works; `doc.masterSlides()` raises in JXA but
AppleScript's `master slide` is fine, which is why `keynote_jxa.js` stays unused).

## Outline editor in the dashboard

The operator views and edits the outline in the dashboard, picking cues from the
palette instead of typing them.

**Editing surface: HTML rendered from the .docx.** `load_paragraphs` in
`parse_outline.py` returns per-run `bold`, `highlight`, `superscript`, `color`, and
`ListNumberResolver` (line 365+) resolves Word auto-numbering. `OutlineResultView`
already renders paragraphs with cue chips at exact character offsets via `segments()`
— that component is the starting point, made editable.

**Page view: LibreOffice.** A toggle converts the current file with
`soffice --headless --convert-to pdf` and shows the rendered pages. Read-only, cached
until the next save, disabled (not an error) when LibreOffice is absent.

**Writes go to the source .docx, in place.** This reverses SKILL's "never overwrite
the source outline" rule, scoped to the generator's editor only; the Sermon Checker
stays read-only and the `_CUED.docx` path is unchanged. Two safeguards:

- A timestamped backup per save under `output/.outline-backups/{stem}/`.
- **Surgical edits only** — apply an operation list against the paragraphs the
  operator touched, in the manner of `_apply_ops` / `_make_run` in `annotate.py`.
  Never re-serialise the whole document: tables, images, comments and numbering the
  model does not represent must survive untouched.

**Semantic cues in, operator cues out.** The editor writes `[TITLE]`, `[VERSE]` etc.
Conversion to `[LW]`/`[DSK-…]` stays in `annotate_outline` at generate time.

**Validation as you type.** The palette enforces what the parser knows:
`[VERSE-AFTER-POINT]` only after a point, `[FILLER-QR]`/`[GIVING-OPTIONS]`
offering-only, `[VERSE-FROM-PREVIOUS]` absent (it raises `cue.deprecated_alias`).
This is also where "one cue is one slide advance" is cheapest to hold.

## Image cues: design for these, build later

An image places from AppleScript with `position` and `width` (height follows). A
movie is placed by creating an image and then assigning the video to its `file name`,
which converts the object and keeps the geometry — so video slides are generatable
with no GUI automation, and a template needs only a small image placeholder. (Both in
SKILL.)

Taxonomy, read off `~/Desktop/Diff-Checker/Sermon_PK (GW).key`:

- **Centre-panel photo set** (slide 18): two photos filling the centre 3840x1080.
- **Mirrored single set** (slide 20): one set repeated left and right.
- **Full-centre media** (slides 25/26): one image or movie across the whole centre.
- **Design-authored collage** (slide 1): dozens of cut-outs; not operator-buildable —
  the cue is "drop in the supplied graphic", which `[GIVING-OPTIONS]` already does.
- **Grid cases** (photo wall, missions-map infographic): want a count and a grid
  spec, not N placements.

So an image cue is a cue plus an **asset slot count and shape**; picking it opens a
drop target for that many files, in order, with the frames named. Custom backgrounds
are the norm, so the cue must allow a background asset distinct from the content ones.

## Stat drift across adjacent slides

A missions wall read "11 Renovated Church Buildings" on one page and "44" on every
page after it. No rule fires, because nothing on either page is wrong on its own — it
is only visible reading two pages side by side. The tell: a caption that persists
unchanged across a run of slides changes exactly once. Compare text objects across
adjacent slides, matching on position and on wording with the digits removed, and
flag a page whose number disagrees with the run either side of it. Ships at
`warning`, not `error` (a figure that genuinely steps per slide trips it, and the
operator has said that is the cheaper mistake). Stubbed in `validation_rules.yaml`.

## Recipes as browsable artefacts

The framing review browses **template slides**, and a template slide only helps if
something *pairs*. A chrome-plus-movie slide pairs with nothing, so every candidate
previews identically (all degrade to fit-to-frame). What transfers instead is the
**recipe** — a portable subset of the learned transform, applied to pages that can't
learn a framing of their own.

**Built and reverted.** It worked (a recipe from `Extracted_CG_3rd` slide 2 moved a
movie to the centre 1920 of the wall panel at full size) but did not help the pages
that need help most. A page that cannot learn a framing of its own is usually a page
carrying a map *and* a badge, and that wants **two affines, not one** — the same gap
the single-group v1 limit described from the other side. Report card slide 94 was the
case: the badge rode the map's affine off-frame, dragging `on_canvas_fraction` under
threshold so every framing fell back. A saved single-affine recipe would have carried
the same problem.

So the single-group limit was this gap seen from the other side. **Worth rebuilding
now `badge-affine` produces a named group** — the commits are in the branch history
to lift from. Carrying more than one affine means naming groups by role so the
applying side re-anchors by role (`primary_map_rect` for the map, `title_plate` for
the badge); `portable_recipe` then drops the single-group check and carries
`[{role, s, tx, ty}]`, and `apply_portable_recipe` resolves each role on the page in
hand. When a carried role has no counterpart (a badge affine on a page with no
badge), fit the orphans to their own footprint: run `fit_to_frame_recipe`'s arithmetic
(`visible_content_union`, uniform shrink, 24px margin) over the orphaned subset rather
than the whole slide, keeping their position relative to the frame. Two facts to carry
in: `visible_content_union` is measured against the full 7680 (there is no
"excluding side panels" concept — introduce it if the estimate should be centre-panel
relative), and fit-to-frame centres its result today (keeping relative position is a
change to the arithmetic, not just its input). Storage: a tracked `recipes/` folder of
small labelled JSON files, not `.cache/`. Plumbing is one branch —
`plan_payload_transforms` already re-learns per slide keyed by
`framing_overrides[number]`; add `recipe_overrides: dict[int, dict]` beside it.

## Order of work

1. The number block in the CG resizer (above) — the immediate item.
2. Recipes as browsable artefacts, now a badge carries its own affine.
3. Cue palette and outline editor.
4. Image cues.
5. DSK generator, unchanged from the superseded plan including its four corrections.

Stat drift is independent of all of these and can land whenever.

## Still parked

- **Text in front. Decided 2026-08-25 — do not re-raise without new information.**
  There is no arrange vocabulary, but *pasting* puts an object at the front and
  `applyReuse` already drives cut/paste. The cost is real (a pasted object is new, so
  builds and identity are lost, and it is keystroke-driven). A narrow version (title
  + badge words) was offered and declined: the case it would address is the buried
  badge, which is source-deck stacking no script can reach.
- **Slide 125's church list** — its names live in ~51 opaque groups spanning the
  centre, so neither the list-hide (text only) nor the side-panel drop reaches them.
  Source-deck **grouping** problem — ungroup so they hide like slide 124. (Now also
  surfaced to the operator in the resizer callout.)
- **Duplicate objects in the source deck** — `Map_Extracted_Wall_1st` slide 4 has two
  pairs of coincident groups; the planner places all four. Harmless (each pair lands
  on the same spot), so this is object count, not appearance. Any dedupe must be
  scoped to groups and text and **never** images (the stacked map layers are
  coincident on purpose).
- **The first ranged propose on a deck never read in full** cannot translate the range
  into Keynote's numbering, and says so rather than guessing. A flags-only Keynote
  pass would remove the caveat if it bites.
- **Composite preview text** — the third preview mode draws text as scaled wall
  pixels, so anything the run restyles is close rather than right. Real HTML at the
  template's font size would fix it; occlusion never can.
- **`deck_digest` costs ~6s on a 6.8 GB deck**, and every cache-key lookup pays it.
- **The JXA export has never worked** — every exporting payload carries `exportError`
  while still succeeding, because `export_slide_images()` picks up after
  `exportImages()` fails. Pre-existing. Worth cleaning up, not urgent.
- **PNG export fidelity** — the two Keynote versions' exports differ by 117 pixels on
  one slide at max channel delta 2/255 (renderer rounding). A negative result, not a
  clearance — the original symptom was on a full sermon deck mid-service. Keep
  watching.

## One standing caution about confirmation

Overrides are honoured, but **fit-to-frame still overrules them on pages where nothing
in the template describes the page** — on `Full_Report_Card_Wall` slide 1 all three
candidates fell back with agreement 1. Falling back there is correct, and the operator
must be told per page rather than in a footnote, or the flow lies (the UI does this via
`wouldFallBack` — keep it if that code is touched). The deeper point: confirmation only
bites when the template has a framing worth picking, so the count of pages with no
candidate at all is the prompt to add template slides — the real fix rather than a
per-page override.

## The metric-that-misleads pattern (worth keeping)

Framing selection went through five rewrites in one session, each fixing a real case
and several creating the next (matching points by proximity; scoring content-inside-
frame, maximised by shrinking; measuring fit over everything visible when side lists
run 3x wider than the map; ranking on the raw template score). The pattern matters
more than the instances: a metric asked to infer something the data does not contain
— which crop of a map the operator wants is editorial, and no pixel area encodes it.
So when framing selection needs another exception, a sixth metric is the wrong move;
asking is right. This repo already has the pattern for asking — the Sermon Checker
proposes pairings, shows them, lets the operator correct, and remembers by content
digest (`/api/diff/{id}/slots`, `save_pairing`, the slot remapping in `baseline.py`).
Reuse it. Ask from the inspect alone, before remapping, and keep the fit-to-frame
fallback so an unconfirmed deck degrades instead of breaking.
