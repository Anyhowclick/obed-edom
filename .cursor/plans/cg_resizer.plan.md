---
name: CG resizer
overview: "Read `.cursor/skills/obed-edom/SKILL.md` first — every durable Keynote finding lives there. This plan holds only what is still to do plus the reasoning a new agent would otherwise rediscover. DONE (in SKILL / git log, condensed below): Keynote 15.x migration, framing confirmation, badge-affine, structural title detection, the divider, ranges in Keynote's numbering, off-frame hiding, the per-slide side-panel whitelist, the stat number-block (packing + template-taught sizing), and the CG-resizer SPEED work (AppleScript geometry, Stage-A export-fold, no-validate default, and BULK-READ inspect — 227s→57s, byte-identical; slide 8 ~10min→~2min; see the Session-11 handover). STILL TO DO: Stage B (optional speed, opt-in); the in-dashboard outline editor; image cues; stat-drift; recipe library (revisit now badge-affine exists); the propose-pins-paired flag. Cue palette + DSK generator moved to cue_palette_and_dsk_generator.plan.md. Operator/source or won't-fix leftovers: slide 125's grouped church names, the sparkle-overlay-on-words placement, a caption in the 'as it will look' preview, and a verse's wall-authored hard line breaks (a source-deck fix — stripping them by script destroys the un-scriptable superscript numbers and small-caps LORD)."
todos:
  - id: unify-applescript-pass
    content: "Reduce dest opens per resize. PROGRESS (slide 8 constellation: 9:58 → 6:55 → 4:58, ~halved): (1) AS-geometry now DEFAULT (OBED_AS_GEOMETRY, =0 to force JXA) — no (0,0) flick, ~30% faster, validated on a real render. (2) Stage A DONE (56c104c): preview export folded INTO the stat-finalize session (no separate export reopen), + template stat-size read cached by digest. (3) CLI now DEFAULTS to validate=False (d1234e2, --validate to opt in) — skips the read-back per-object walk of the 1.15GB deck, the biggest single cut. REMAINING = Stage B (optional, DECISION PENDING): fold the stat-finalize reopen into the geometry session — _run_jxa leaves the dest OPEN after save (skip close at remap_keynote.js:902-904, keep save :896), Python drives stat AS against the open document 1 (mirror the PROVEN superscript-fix pattern: keep `open theFile` as an idempotent bring-to-front so Phase-2's frontmost-scoped Bring-to-Front hits the right deck; add name guard). Peer-reviewed (scratchpad/stage_b_plan.md): feasible + safe IF built on that pattern + net-new failure handling (Python subprocess timeout, close-on-failure, next-run cleanup of an orphaned open deck) + shipped OPT-IN (default off). Payoff bounded to ONE ~2min open (the stat pass is index-addressed, not a full walk). Both reviewers: opt-in or stop after Stage A — the big wins are banked."
    status: pending
  - id: bulk-read-inspect
    content: "DONE + VALIDATED (d218350). Real-deck A/B (Map_Extracted_Wall_1st slides 1/3/8, 1035 objects, `scripts/bulk_read_ab.py`): legacy 227s → bulk 57s (75% off, ~4x) and BYTE-IDENTICAL — default-ON is safe, the nested-read reorder risk is cleared. `OBED_BULK_READ=0` forces legacy. The uncached ranged source inspect was the run's fattest cost, so this is the biggest single speed win. Design below kept for reference.\n\nSpeed up inspect_keynote by BATCHING reads. Measured (Session 11): per-property Apple Events cost ~11ms REGARDLESS of bridge (JXA 121s ≈ AS 122s — a JXA→AS switch buys NOTHING). Lever = bulk reads (`property of every element`, one event for the whole collection). Speedup ~2.4x flat / ~1.1x group-nested — BUT that 2.4x was measured on `position` (a DIRECT property). Two peer reviews (Session 11) say DON'T build yet — the value hinges on untested assumptions and the risk was mis-stated:\n\nGATE 0 (go/no-go, do FIRST): micro-benchmark the NESTED reads `slide.textItems.objectText.size()` / `.font()` / `.color()` (describeItem reads ~10 props/object incl. these 3 nested ones, L149-158 — they dominate text-heavy flat slides AND are least certain to bulk in JXA), NOT just `position`, on a REAL flat deck AND a real group-heavy deck end-to-end. If nested reads don't bulk cleanly, flat 2.4x collapses to ~1.3x → SKIP as diminishing returns (put effort into Stage B). Also: bulk reads from the UNEVALUATED specifier `slide[name].position()`, NOT the evaluated `col` (a JS array has no .position()).\n\nCORRECTNESS (the real risk, not dedup): read-only but the payload is load-bearing (remap resolves by (collection,kindIndex)) and the default resize runs validate=False → a shifted index ships mis-placed objects to the user's deck with NO catch. Killer = array-length drift: if Keynote drops a missing value (file-less image in images.fileName(), empty objectText), array length ≠ collection count → every later zip index shifts. GUARD: assert array.length === collectionCount per bulk array; PERMANENT per-collection×per-property fallback to the EXISTING per-object fns (positionOf/sizeOf/describeItem) on any throw/mismatch (bulk is all-or-nothing; per-object try/catch each read today). Keep the per-object path as a runtime fallback, not a dev flag. Preserve the single slide[name]() evaluation feeding BOTH records and identity.objs (build-count !== matching, else buildCount breaks). Dedup (markDuplicateShapes) is pure JS post-processing — auto-preserved, low risk. Group childCount is often 0 on real decks (diff_keynotes.py:91) so the group case may be moot.\n\nSCOPE: default resize = ONE ranged uncached inspect (source); full-deck inspects cache (cold-start only). So win is once/run on ranged flat decks. Validate by byte-identical payload diff (per-object vs bulk) on the REAL messy wall deck + group-heavy + file-less-image + locked + empty-text decks. Complementary to Stage B (read vs write path); build bulk-read FIRST if GATE 0 passes."
    status: completed
  - id: text-placement
    content: "CG resizer number block (183/86/14/269) rendered as overlapping fragments — groups all parked at one left margin. DONE (Session 6, PR #32): packed into non-overlapping columns. Sizing the inner text is a separate limit — see gui-ungroup-stats."
    status: completed
  - id: gui-ungroup-stats
    content: "DONE — shipped as the stat-finalize pass (`feat/group-child-resize`): read + resize grouped stat numbers in place via AppleScript (no ungroup; the childCount=0 opacity was JXA-only), and Bring-to-Front the buried badge. Findings in SKILL. Follow-up (not built): style-swatch matching instead of by-content."
    status: completed
  - id: outline-editor
    content: "Editable outline view extending OutlineResultView, LibreOffice page-view toggle, in-place surgical writes to the source .docx with timestamped backups. Pending — design below."
    status: pending
  - id: image-cues
    content: "Image cues as an asset slot count + shape per cue. Both capabilities (image place, movie via file-name reassign) probed and present. Pending — taxonomy below."
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
  - id: propose-pins-flag
    content: "Surface pins-paired (pairQuality) in the propose UI so a '0-pin' slide is flagged, not trusted. The propose thumbnail scores are IMAGE-similarity and can invert the actual geometric fit on bespoke slides. Concrete case (Session 10, Map_Extracted_Wall_1st slide 8, the 67-node constellation): template 4 scored 0.69 (best) with a great-looking 'as it will look' preview but paired 0 objects → 42% on-canvas → correctly vetoed at remap; template 13 scored 0.06 (worst) but paired 34, 100% on-canvas, scale 0.483 (= the measured constellation compression) and was the right pick. The remap-time geometry check saved it, but the propose UI actively misled. Fix: show pins-paired / pairQuality per template tile (and a 'looks-fit-only, 0 pins' warning) so the operator doesn't trust a zero-pairing framing. Pending."
    status: pending
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

## Completed work — key insights, not detail

Everything below shipped. The durable findings are in SKILL.md and the reasoning is
in the commit messages (`git log`); this is only the insight each session left behind
and the pointer to find the rest. Sessions are collapsed — read them as one body of
learned facts, not a timeline.

**Infrastructure & targeting**

- **Keynote 15.x migration** — bundle-id targeting through the single resolver in
  `keynote_app.py`, version-tagged cache, 14.5 deleted after an A/B pass. The one
  place that decides which build; everything else addresses by id. In SKILL.
- **Ranges in Keynote's numbering + out-of-range guard (PR #34).** The dashboard
  translates a typed range from the cached full payload when there is one, else says
  it is taking document positions (CLI always does, and says so). A range past the
  deck's last slide now errors via `_assert_range_within_deck` (ceiling = `slideCount`,
  the whole deck even on a ranged read) instead of leaving a blank framing screen.

**Placement — the affine model**

- **A badge gets its own affine** — plate-to-plate, so a map-and-badge page gets two
  affines. On the report card's 34 such pages the plate went from 117/136 placements
  off-frame to none. `_title_badge`, `badge_plate_members`, `template_badge_slots`,
  `badgePlateDst`. *Insight: one affine per role, not per slide — the same gap the
  reverted recipe library hit from the other side.*
- **Structural title detection** — phrase match first, then the plate (largest shape
  containing a text item's centre) carrying exactly one word. Not by wording.
- **Fill, don't letterbox, in the fallback (`FILL_MAX_CROP_FRACTION=0.47`, PR #31).**
  When no template framing pairs, `fit_to_frame_recipe` used to `min()`-fit the whole
  visible union, shrinking a two-frame panorama to a postage stamp where the human
  cropped one frame at native size. It now biases fit→cover, bounded twice: never crop
  the binding dimension past the cap, never enlarge past 1:1. Offline vs gold: map+pin
  `goldRmse` −15.3% over 72 rows, 14 improved / 0 regressed. Cap tuned by sweep
  (shallow min at 0.47; higher just reaches full cover and overshoots the human crop).
  *Insight: this was the one code-side gold-closeness win in the whole
  resizer-refinement dive — the rest of the gold distance is editorial crop choice
  (SKILL's documented trap) or scoring artefacts on title/badge/list rows, not bugs.*

**Groups can't scale, only move**

- **Pack the left-column number-block groups (PR #32).** On slide 124 the "183/86/14/
  269" stat block lives in groups the map affine throws off the left edge, so
  `plan_slide_transforms` parks each at `x=16` at *wall* size (a group's width does not
  scale its children). Parked at one margin they overlapped; a post-pass
  `_pack_left_groups` / `pack_columns_from_left` (stepping by the column's *max* width)
  now packs them into non-overlapping columns, move-only, map/pin byte-identical.
  *Insight: the opaque-group limit is why this is packing, not sizing — the groups'
  inner numbers can't be read or resized. See the GUI-ungroup TO-explore below.*

**Confirmation, whitelist, hiding — the operator loop**

- **Framing confirmation** — `/api/resize` is two-phase (propose, then apply after the
  operator confirms), reviewed in `FramingReview.tsx` grouped by framing, each
  candidate a real wall preview under the planner's own affine, decisions remembered
  by digest. *Insight: confirmation only bites where the template has a framing worth
  picking; the count of pages with no candidate is the prompt to add template slides.*
- **Per-slide side-panel whitelist (`14ef262`, `7f1fa59`)** — side content dropped by
  default, kept per whitelisted page via `Decision.keep_side_content` (by digest,
  orthogonal to framing). Threads through `plan_payload_transforms`, `remap_keynote`,
  the endpoints, and the review's per-page toggle. CLI `--include-lists` is the global
  override.
- **Off-frame hiding, then deleting the hides (`e7621f8`, PR #33).** The 16:9
  canvas-shrink makes Keynote scale-to-fit every object it owns, dragging *skipped*
  objects back on-frame; `plan_slide_transforms` emits zero-opacity hides for
  off-screen leftovers and magic-move duplicates. But a zero-opacity object still
  catches clicks, so the operator kept selecting a ghost — `deleteHides` now deletes
  every hide after both geometry passes (descending index, falls back to `opacity=0`
  if a delete is refused; `remap_keynote.js` already deleted grouped hides, opacity
  can't hide a group). *Insight: this is why the resizer's Important callout tells the
  operator to delete skipped slides and ungroup side content.*
- **Operator-facing polish (`feat/resize-operator-notes`)** — the Important callout,
  a whitelist filter in the Reviewed tab, pill toggles, hazard-tape warnings. Frontend
  only.

**Real-run review batches** (`23a8dcd..52b13cd`, `cdaf271..ceaff9d`, `feat/side-panel-whitelist`) — text keeps its source font and colour (never re-assert a verse box — it flattens the runs; memory `lw-text-keeps-source-font-colour`), scripture body in the template box, centre-panel 1:1, sparkle overlays, church-list drop over the map, magic-move de-dup, off-screen skip + body fit, corner labels, cover-vs-letterbox, badge colour-reject, LW side-panel drop, verse bold-run preservation, sibling-affine magic-move reuse. Each has its reasoning in its commit; the mechanisms are locked by tests.

**The recurring lesson.** Framing selection went through five rewrites in one session, each fixing a real case and creating the next — the signature of a metric asked to infer something the data doesn't contain (which crop the operator wants is editorial; no pixel area encodes it). When selection needs a sixth exception, *ask* — don't add a metric. The repo already has the asking pattern (the Sermon Checker's propose/correct/remember-by-digest). Full statement in SKILL and in "The metric-that-misleads pattern" below.

## Stat blocks + JXA-limit re-verification — DONE (Sessions 8-9)

The grouped stat numbers ("269"/"183"/…) are read and resized in place by the shipped
**stat-finalize pass** (`keynote.py`): read the template's numeric sizes (grouped + loose,
AppleScript) -> set each matched wall number in place (`269`->200, `183`->150) ->
Bring-to-Front the stat groups + Global Missions badge. The GUI-ungroup track was dropped
once AppleScript proved it reads AND writes group children in place (no ungroup for read or
resize; a group's own width still won't scale children — address the children). All the JXA
"limits" were re-verified as JXA-only (group children, line endpoints, per-char
font/colour/size, z-order READ via `iWork items` stacking order, master slides, export);
durable matrix + "test every limit in AppleScript first" live in SKILL. **Open follow-up
(not built):** match stat numbers to the template by **style-swatch** (font+weight+colour ->
size, slot tiebreak), not by content (current is report-specific).

## Constellation slide — staff hand-down (separate track)

Separate track (`Full_Report_Card` slide 134→127): a connected graph of ~67 figure-nodes
(varied sizes) + 68 edges. Measured: the human scaled nodes **~0.85** and compressed the
footprint to **~0.48** — which is not handwork but a **two-knob transform**: scale each
node in place (~0.85) + pull its centre toward the constellation centroid (~0.5). With
line endpoints now writable (AppleScript), edges re-route to follow. Recommendation
(peer-reviewed):
- **Option A+ (recommended, zero staff input):** the two-knob transform; the `Affine` +
  centroid helpers mostly exist. Caveat: overlaps in dense regions → gentler `c` / local
  de-overlap; tune `s`/`c` once against gold.
- **Edges: match by IDENTITY, never proximity** (the documented pins trap, SKILL:286-291) —
  record edge→node incidence on the wall, re-anchor to the *recorded* node preserving the
  rim offset; a deleted node's edges are dropped, never re-pointed.
- **Bare minimum staff provide:** *nothing* for A+; if A+ falls short, *the finished node
  layout at final size* (no template authoring, no exemplar) and the tool does edges +
  stacking. **Ask first: does the slide's content change yearly?** — that gates whether to
  build A+, fall back to an exported image, or hand-do it. Full write-up in the session
  scratch `constellation_plan.md`.

## Operator / source-deck items (no code fix)

- slide-124: ~130x11px overlap between two right-side groups (`mapped.x >= 16`, not parked).
- slide-125: church list = 46 opaque groups (source-deck ungroup).

(The 2026-08-27 handover's other items shipped: number-block packing #32, delete-hides #33,
the badge z-order lift via the stat-finalize Bring-to-Front. Superseded by the Session-11
handover below.)

## Handover — CG resizer SPEED WORK (2026-08-28, Session 11)

Branch `feat/group-child-resize`, pushed. **Slide 8 constellation: 9:58 → 6:55 → 4:58,
~halved.** The corner-flick (JXA yanks an object to (0,0) when you set its width/height)
is gone. Shipped, all validated on a real render:

- **AS geometry, now DEFAULT** (`OBED_AS_GEOMETRY`, =0 forces legacy JXA). Object
  geometry (position/width/height, line start/end points) is written by a batched
  AppleScript block emitted IN the JXA loop (remap_keynote.py `_build_slide_geometry_script`
  / `_build_as_geometry`; JS `applyNonReuseSlide` picks the AS path per slide when Python
  built a body). No (0,0) yank, drops `setPos`'s readback-verify + the second position
  pass (~30%). Per-slide fallback to JXA for a slide carrying an unaddressable kind
  (table/chart); reuse path stays JXA.
- **Stage A** (56c104c): preview export folded INTO the stat-finalize session (no
  separate export reopen); template stat-size read cached by digest (`baseline.py`
  `template_stat_cache_path`).
- **CLI defaults to `validate=False`** (d1234e2, `--validate` to opt in) — skips the
  read-back per-object walk of the 1.15GB deck. Biggest single cut.
- **A/B tool:** `scripts/ab_geom_diff.py` (content-keyed bounds diff of two output decks).

**Key MEASURED facts (Session 11 micro-benchmarks, synthetic decks):**
- **JXA and AppleScript READ at the same speed** (~11ms/property; 121s vs 122s for 10,890
  reads). A JXA→AS bridge switch buys NOTHING. Wins come from doing LESS work, not the bridge.
- **Bulk reads** (`property of every element`, one Apple Event for the whole collection)
  are ~2.4× on flat single-kind collections, ~1.1× on group-nested (bulk needs one call
  per group). This is the `bulk-read-inspect` TODO — plan+2 reviews were in
  `scratchpad/bulk_read_plan.md` (session-local; re-derive from the TODO if gone).

### NEXT TODO — Stage B: fold the stat-finalize reopen into the geometry session (with recovery)
Removes the LAST avoidable dest open on the validate=False path. Two peer reviews done;
**ship OPT-IN (default off), only after the recovery guards below.** Self-contained design:

- **Mechanic (mirror the PROVEN superscript-fix pattern, keynote.py `_build_superscript_fix_script`
  docstring):** `_run_jxa` saves geometry and returns with the dest LEFT OPEN — gate ONLY
  the `Keynote.close` at remap_keynote.js:902-904 on a new `plan.leaveOpen`; keep the
  `save` at :896; leave the abort-close at :876 UNCONDITIONAL. Then Python runs the stat
  AppleScript against the already-open deck as its own osascript subprocess. In the stat
  preamble, DROP the `close (every document whose name…)` line but **KEEP `activate` +
  `open theFile`** — on an already-open deck that `open` is a cheap bring-to-front, and it
  is what re-fronts the dest so Phase-2's GUI Bring-to-Front (a frontmost-window menu click,
  keynote.py:927-938) acts on the RIGHT deck. Do NOT replace it with a bare `document 1`
  bind (that was the v1 mistake that reintroduced the wrong-doc hazard).
- **Wiring:** `remap_keynote()` has no `validate` param — add `attach`/`leave_open`, set
  from `remap_and_inspect` as `attach = not validate`. One boolean `fold = bool(child_resize)
  and attach` gates BOTH `plan["leaveOpen"]` and `_run_stat_finalize(attach=fold)`, so the
  deck is never left open without an attaching stat pass to close it. validate=True stays
  byte-for-byte (close-then-reopen; its readback reopens anyway).
- **RECOVERY OPTIONS (net-new — the whole reason it's gated):**
  1. **Save-point:** the JXA `save` (:896) runs before control returns open, so any
     stat/export failure loses only stat sizing/z-order/previews, never placement.
  2. **Wrong-doc guard:** before writing, assert `name of document 1` is the dest basename
     (bind `first document whose file is theFile` for path-uniqueness); abort with a clear
     message otherwise. The kept `open theFile` re-fronts it for the GUI raise.
  3. **Killable hang:** add a real Python `subprocess.run(timeout=…)` (today only
     AppleScript's 1-hour `with timeout` bounds it, and that doesn't bound a wedged System
     Events click).
  4. **Close-on-failure:** on stat timeout/non-zero, attempt `close (every document whose
     file is theFile) saving yes`; if that fails, surface "dest left OPEN in Keynote — close
     it before rerunning" (never leave silently open).
  5. **Next-run cleanup:** before `copy_keynote`/open, detect+close an already-open
     same-path doc, so a hang's leftover doesn't collide with the next ditto-copy+open (the
     `pkill`→"Operation not permitted" lock class).
- **Payoff bounded to ONE ~2min open** (the stat pass is index-addressed, `group N of slide
  M`, NOT a full walk — measured). Validate: PNG pixel-diff (z-order + stat sizes only show
  there) + `front=N`/`sized=N` count asserts + a manual crash-path test (kill after geometry
  save → deck still valid + placed). Both reviewers: opt-in or stop after Stage A.
- **Order:** build `bulk-read-inspect` FIRST (read-only, lower risk), then Stage B.

## The number block — DONE

The 183/86/14/269 block: packing shipped (#32) and template-taught sizing shipped
(stat-finalize). The open hypotheses (H15/H16/H19 — text scale/reflow) were resolved by the
AS-geometry work (H19's "setting width/height yanks to (0,0)" is exactly what AppleScript
geometry fixed). Nothing to re-investigate here.

## Cue palette + DSK generator → split out (2026-08-28)

Moved to `.cursor/plans/cue_palette_and_dsk_generator.plan.md` so this plan stays
focused on the CG resizer and its speed work. The cue-first palette design (drop live
preview, invert the cue maps, per-template layout thumbnails cached by digest) and the
DSK generator live there now. The outline editor, image cues, stat-drift, and
recipe-library stay here.

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

Speed track (Session 11, `feat/group-child-resize`): AS-geometry ✓, Stage A ✓,
no-validate ✓. **Next: bulk-read inspect** (ship if it nets a speedup behind the
per-object fallback), then **Stage B** (opt-in, with recovery — see the Session-11
handover). Then the feature backlog: recipes (a badge now carries its own affine),
outline editor, image cues. Stat drift is independent and can land anytime. Cue palette
+ DSK generator moved to their own plan.

## Still parked

- **Badge-to-front — SHIPPED** via the stat-finalize Bring-to-Front (buried badge lifted
  above the map). The general GUI z-order route (`set selection` by reference + Arrange ▸
  Bring to Front) is proven; reuse it for any other buried object.
- **Never dedupe images** — the stacked map layers are coincident on purpose; keep this in
  mind for any future dedupe. (The old "duplicate stat groups" worry was retired: the deck
  has 6 top-level groups, no duplicates.)
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
