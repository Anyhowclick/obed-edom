---
name: CG resizer
overview: "Read `.agents/skills/obed-edom/SKILL.md` first — every durable Keynote finding lives there. This plan holds only what is still to do plus the reasoning a new agent would otherwise rediscover. DONE (in SKILL / git log, condensed below): Keynote 15.x migration, framing confirmation, badge-affine, structural title detection, the divider, ranges in Keynote's numbering, off-frame hiding, the per-slide side-panel whitelist, the stat number-block (packing + template-taught sizing), and the CG-resizer SPEED work (AppleScript geometry, Stage-A export-fold, no-validate default, BULK-READ inspect — 227s→57s, byte-identical; and geometry `set properties` ~1.25× on the write phase — see the Session-11 AND Session-12 handovers; the geometry WRITE on the heavy slide, not deleteHides/z-order, is the bottleneck). SPEED IS DONE: Stage B, batch z-order, and batch delete were all built + real-deck-tested + ABANDONED (warm-cache open = no gain; multi-select Bring-to-Front unreliable; `delete {list}` throws -1700) — see the Session-12 handover; do not rebuild. STILL TO DO (features only): the in-dashboard outline editor; image cues; stat-drift; recipe library (revisit now badge-affine exists); the propose-pins-paired flag. Cue palette + DSK generator moved to cue_palette_and_dsk_generator.plan.md. Operator/source or won't-fix leftovers: slide 125's grouped church names, the sparkle-overlay-on-words placement, a caption in the 'as it will look' preview, and a verse's wall-authored hard line breaks (a source-deck fix — stripping them by script destroys the un-scriptable superscript numbers and small-caps LORD)."
todos:
  - id: unify-applescript-pass
    content: "Reduce dest opens / write cost per resize. DONE + BANKED: (1) AS-geometry DEFAULT (OBED_AS_GEOMETRY). (2) Stage A (56c104c): preview export folded into the stat-finalize session + template stat-size cached. (3) CLI DEFAULTS to validate=False (d1234e2). (4) Geometry `set properties` (Session 12, 9c32084, OBED_GEOM_PROPS default ON) — folds width+height into one AS command, ~1.25× on the write phase. ABANDONED (Session 12, do NOT rebuild — see the Session-12 handover): Stage B reopen-fold (warm-cache open = no measurable gain; the '17%' was a broken run skipping the stat pass), batch z-order (multi-select Bring-to-Front doesn't reliably raise above the map), batch delete (`delete {list}` throws -1700; the '315×' was a try-hidden fast-failure; JXA per-object is already fastest). Bottleneck was the geometry WRITE on the heavy slide (~70% of run), found via OBED_WRITE_TIMING; not deleteHides/z-order."
    status: completed
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
  - id: iwa-per-run-style
    content: "Offline IWA decode → item[runs] + slide[groupedText] on FINALIZED decks (per-run colour/bold/italic/size/fontName/superscript/smallcaps + grouped text that JXA reports as childCount:0). DONE (feat/iwa-per-run-style, pushed not PR'd; INSPECT_VERSION 3; optional `iwa` extra). Lights up the previously-inert highlight/punctuation/smallcaps consumers + cuts OCR; resizer + deck_slide_digests provably untouched. Full detail in SKILL 'Reading a .key offline (IWA)'. Speed/Keynote-free-inspect NO-GO and offline-whole-deck-write NO-GO both measured — see Session-13 handover + SKILL."
    status: completed
  - id: iwa-surgical-write
    content: "Spike (un-built): surgical IWA write — rewrite ONLY the target slide's IWA, copy every other IWA verbatim — to set cyan superscript verse numbers offline and retire generate's GUI Copy/Paste-Style pass 2 (Accessibility, silent-fail). Whole-deck re-serialize is byte-lossy (corrupts large decks), so surgical is the only viable path and needs per-deck openability testing. High-value for the generator, higher-risk. Pending."
    status: pending
isProject: false
---

# Cue palette and outline editor

Supersedes `keynote_file_format_spike_6b4ae4c2.plan.md`. Everything in that plan
still stands except item 3 (live preview), dropped for the reasons below.

**Read `.agents/skills/obed-edom/SKILL.md` first.** Every durable finding — bundle-id
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

## Handover — Session 12 (2026-08-28, speed dive continued & CLOSED)

Branch `feat/preview-drop-marking` (off main `8fc3dcd`), 3 commits, **NOT merged**.
Continued the speed work: net **one more real win** (geometry `set properties`) plus
**four optimizations tried and ABANDONED**, each for a load-bearing reason. The
measure-first / probe-first / peer-review discipline caught every dead end before it
shipped — nothing broken reached a deck. **Speed is now banked; the reopen-fold /
z-order / delete-batching ideas are closed — do not rebuild them (see reasons).**

**SHIPPED on the branch** (ready to review/merge; splits into two PRs — preview+SKILL,
and geometry+timing):
- **Geometry `set properties`** (`9c32084`; `OBED_GEOM_PROPS` default ON, `=0` legacy).
  The AS-geometry block folds each object's width+height into ONE `set properties
  {width,height}`; **position stays a separate LAST write** (an atomic
  `{w,h,position}` re-anchors ~18px and drifts — verified), and a line's endpoints
  fold atomically. ~1.25× on the dominant phase (real deck: slide 8 124s→101s, slide 3
  67s→54s), validated placement-identical against the pipeline's own run-to-run noise
  floor (Keynote's canvas-shrink already jitters the map ~8px/run, so A/B pixel-diffs
  MUST be read against that floor — two identical runs differ by ~delta-255 over the
  upper region).
- **Write-timing diagnostic** (`9c32084`; `OBED_WRITE_TIMING=1`, default off, zero-cost):
  per-slide/per-phase elapsed + slowest objects, printed by remap. **This is the tool
  that found the real bottleneck** — the geometry WRITE on the heavy constellation slide
  is ~70% of the run (~109s), NOT deleteHides (~4-20s) or z-order. Keep it.
- **Preview drop-marking** (`faa611a`): "where objects land" was drawing ~199 dropped
  church-list boxes as if they'd land. Now threads the real `include_lists` +
  `side_content_slides` into the preview planner and marks each rect `willBeInOutput`;
  dropped objects render ghosted/struck. Real remap path untouched.
- **SKILL doc-bind correction** (`faa611a` + `7a415b4`): see DURABLE FINDINGS.

**ABANDONED — do NOT rebuild (the reasons ARE the finding):**
- **Stage B** (fold the stat-finalize reopen into the geometry session). Built,
  real-deck A/B'd, dropped. The reopen it removes is **warm-cache-cheap** → no measurable
  gain. (The premise was doubly wrong: the plan assumed a ~2min cold open, but even a cold
  open of the ~6.8 GB deck is only ~3–4 s — measured 2026-08-28 — so there was never a
  ~2min open to save.) The "17% faster" first seen was a
  BROKEN run: the attach bind failed (`NO_DEST_DOC`) and SKIPPED the whole stat pass, so
  it did *less* work. Premise wrong. (The Stage-B design section below is retained only
  as the record of a dead end.)
- **Batch z-order** (one multi-selection Bring-to-Front per slide vs N). Built,
  real-deck A/B'd, dropped. **Keynote's Bring-to-Front on a large multi-selection does
  NOT reliably raise all selected above non-selected** — the map blocked the badge/
  "Missions" text again (the exact buried-text bug the pass fixes), even though
  `front=` counted all 36. GUI limitation, unfixable without per-object raises (= the
  cost). Proven per-object z-order stays.
- **Batch delete** (one `delete {list}` vs N JXA deletes). Built, then PROBED and
  dropped. **Keynote's `delete` takes a SINGLE specifier — `delete {list}` (literal OR
  variable) throws -1700 "Can't make {…} into type specifier" and deletes nothing.** The
  "315×" first measured was a `try`-hidden fast-FAILURE (30ms to throw+catch, 0 deleted),
  not a fast delete. No selective batch-delete exists: `delete every X` is too broad,
  a reverse-loop is per-object (N redraws), and **JXA per-object (~20ms/obj, current)
  beats AS per-object (~68ms/obj)**. The one-by-one vanishing is inherent; current JXA
  `deleteHides` is already optimal. **Lesson: verify any batch-op probe by COUNTING
  affected objects, never by timing a `try`-wrapped call.**
- **Shape-read skip** (skip text-property reads on empty-text shapes). Investigated,
  NO-OP: the nested shape reads (`shapes.objectText.size/font/color`) already BULK
  cleanly (probe: 139 shapes ~54ms vs 4693ms per-object), so bulk-read (S11) already
  handles it. The "yellow men read slower" was actually the geometry WRITE, not a read.

**DURABLE KEYNOTE-15 FINDINGS (also folded into SKILL "Driving Keynote by script"):**
- `POSIX path of (file of d)` **throws -1700** without an `as alias` coercion:
  `POSIX path of (file of d as alias)`. And `name of document` **drops the extension**
  ("cg_ON", not "cg_ON.key"). The proven doc-bind is close-by-name → open → `document 1`
  → verify name (the superscript / stat-finalize reopen path). `scripts/diag_doc_bind.applescript`
  (throwaway, deleted) demonstrated it.
- Keynote `delete` accepts ONE specifier only; `delete {list}` throws -1700 (above).
- Bring-to-Front on a big multi-selection does not reliably raise all selected (above).
- Each AppleScript command on a heavy slide **redraws (~100ms/cmd) even off-screen**
  (navigating away measured SLOWER) — so the only geometry-write lever is FEWER commands;
  there is no cross-object bulk WRITE (unlike bulk READ). Confirmed by
  `probe_geom_redraw` (throwaway, deleted).

**NEXT:** speed is done — geometry set-properties + bulk-read (S11) + AS-geometry +
no-validate + Stage-A are the banked wins. The feature backlog is untouched: outline
editor, image cues, stat-drift, recipe library, propose-pins-paired (all below).

## Handover — Session 13 (Sermon Checker features + IWA per-run style)

Two independent bodies of work this session. **Read the SKILL's new
"Reading a `.key` offline (IWA)" section first** — every durable IWA finding lives
there; this is only the pointer + what's parked.

**MERGED to main (PR #39, `feat/checker-shift-merge-punct`):**
- **Default Templates fallback removed** — templates are drag-drop / explicit-flag
  only (`--lw-template`/`--dsk-template`); stripped `fallback_rel`/`allow_fallback`/
  `only_provided`, the dead `/api/templates` endpoint + `getTemplates`, and the
  `masters.yaml` `template:` keys. Folder + gitignore block deleted.
- **Overflow de-noise** (`validate._wrap_line_count`/`_inspect_overflow_flags`,
  `wrap_tolerance`) — trust authored line breaks + a half-line slack, so a
  grown-to-fit multi-line title/verse is no longer false-flagged while a real clip
  still is. The estimator was re-wrapping authored lines with a too-wide char guess.
- **DSK shift buttons** (`DiffResultView.tsx`, reusing `playlist.ts shiftColumn`) —
  per-row "Shift ↑/↓" nudge the DSK column vs the current LW, rows above untouched,
  no `[BLANK]/[BLANK]`, ↑ disabled at the no-gap floor. The `.row-acts` guard was
  widened so the bar shows on every editable row. Shift-up is gap-close only (2-DSK
  stacking stays the existing "Combine next DSK").
- **Merge duplicate findings per pair** (frontend) — a finding raised once per deck
  in one comparison pair renders as one card "LW slide X + DSK slide Y", re-separates
  on split. View-only (flat list / exports unchanged).
- **Punctuation rule `style.punctuation`** — a punctuation-only OUTLINE run that is
  bold/italic/highlighted/accent-coloured, on the `Run` layer (`validate_outline`/
  `_paragraphs`); inspect payload has no per-run style so it can't run on a finalized
  deck (that gap is what IWA below closes for the highlight rule). Blind to
  THEME-applied accents (Word returns those as inherited).
- Row-action button colours: **blue Combine / yellow Split** (pairing structure),
  **green ↑ / red ↓** (DSK movement).

**PUSHED, not PR'd (`feat/iwa-per-run-style`, rebased on the merged main):**
- **IWA per-run style + grouped text + fontName/superscript.** See the SKILL. Net:
  `item["runs"]` and `slide["groupedText"]` now populated offline on finalized decks;
  the inert highlight/punctuation/smallcaps consumers light up; `INSPECT_VERSION`→3;
  optional `iwa` extra. Resizer + saved pairings provably untouched.

**DEAD ENDS this session (do NOT re-chase — reasons in the SKILL):**
- **Keynote-free / IWA-backed inspect for SPEED** — no-go. `kindIndex` not
  reproducible on wall decks (write-unsafe); every path needs pixels or writes so
  Keynote opens regardless; and the real read cost is per-slide round-trips, not the
  property reads bulk-read already collapsed (measured ≤ noise).
- **WIN 1 line endpoints** — dropped; JXA already reads deck line endpoints correctly
  on 15.3.1 (the SKILL's "null" is created-lines only).
- **Offline whole-deck WRITE** — byte-lossy, corrupts large decks.

**PARKED / next candidates:**
- **Surgical IWA write spike** — rewrite one slide's IWA, copy the rest verbatim, to
  set the cyan superscript verse numbers offline and retire generate's GUI
  Copy/Paste-Style pass 2 (Accessibility, silent-fail). High-value for the generator,
  higher-risk (per-deck openability testing). Un-built; needs its own spike.
- **Merge `feat/iwa-per-run-style`** when ready (no PR yet per standing preference).
- Feature backlog still untouched: outline editor, image cues, stat-drift, recipe
  library, propose-pins-paired (all below).

### Stage B — ABANDONED (retained as a dead-end record; see Session-12 handover above)
_Original design kept below for history only; do not implement — warm-cache open = no gain._

### NEXT TODO (SUPERSEDED) — Stage B: fold the stat-finalize reopen into the geometry session (with recovery)
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
- **Payoff bounded to ONE deck open** (only ~3–4 s even on the 6.8 GB deck — measured
  2026-08-28; the "~2min open" this design originally assumed was an exaggeration, which is
  part of why Stage B netted no gain. The stat pass is index-addressed, `group N of slide
  M`, NOT a full walk — measured). Validate: PNG pixel-diff (z-order + stat sizes only show
  there) + `front=N`/`sized=N` count asserts + a manual crash-path test (kill after geometry
  save → deck still valid + placed). Both reviewers: opt-in or stop after Stage A.
- **Order:** build `bulk-read-inspect` FIRST (read-only, lower risk), then Stage B.

## Handover — Session 14 (offline remap READ: kindindex + geometry + the two-tier read)

Branch `feat/iwa-kind-index` (pushed, NOT PR'd). Commits: `1b6d8c8` derive_kind_index +
count-guard; `08c98ca` iwa_geometry (offline composed geometry); `98fdc9d`/earlier SKILL;
`bbe2fb8` offline_inspect (JXA-shaped offline payload) + geometry fixes. Rebased on main
(PR #40 merged). **Goal: replace remap's ~12-min JXA source inspect with an offline read.**

**WHERE IT LANDED — the TWO-TIER read makes it work (proven, code building at handover).**
Pure-offline geometry does NOT reproduce the remap PLAN: autosize text (needs Keynote text
layout) and group frames (union-vs-stored) diverge, and a plan-equivalence gate
(`scratchpad/validate_remap_plan.py`, offline diff of `plan_payload_transforms` +
`plan_slide_reuses`) caught it (started RED 345 Map / 702 Full). Fixes cut it to 42/244, all
guard-detected. **The answer (Fable): TWO-TIER read = offline for everything + one O(slides)
BULK Keynote read of `position`/`size` of every group/image/text per slide, overwriting just
those three classes' frames.** PROVEN offline by splicing the JXA values a bulk read returns →
gate **GREEN (0 write-affecting) on BOTH decks**. The group/image/text frames are top-level
slide properties, so the bulk read never descends into children — O(slides), not O(objects).

**Durable discoveries (in SKILL too):**
- **Keynote returns INTEGER geometry** (verified 0/30k fractional); offline sub-px values drift
  the learned affine — `iwa_geometry` now rounds half-away-from-zero.
- **Line endpoints had a MIRROR-FLIP bug** (opposite diagonal of the right bbox; written
  verbatim so it drew a flipped line) — fixed: R(-θ) about frame centre, order from bezier
  moveTo→lineTo + h/v-flip; 391/391 <0.5px.
- **Masked near-zero (<~1°) rotation**: collapse to the axis-aligned frame+mask box (JXA does),
  killed a ~2× deck-wide cascade.
- **The group residual IS the autosize defect one level down** (Fable's unifying hypothesis —
  11/15 stored-frame groups have autosize children): stale child heights break the union, so
  ONE correct autosize source (the bulk read, or a future font-metric model) fixes text AND
  groups. Not two group rules.
- **The pipeline is ill-conditioned** (a 30px input → 1257px output via `visible_content_union`
  → recipe), but fixing the geometry INPUTS resolved it — `map_remap` UNTOUCHED (empty diff),
  JXA plan provably unchanged; the map→hide role-flip cascade vanished. Robust-recipe (prong 2)
  became moot.
- **Diagnosis trap the pressure-test caught:** ~85% of raw gate divergences looked like
  artifacts, but only `role="hide"` geometry is truly write-dead; lines and group w/h ARE
  written. Verify "is this field written?" against `remap_keynote.js`, never assume.

**Safety model (SHIPPED, Session 15):** `OBED_OFFLINE_READ` = **on (DEFAULT)** — offline two-tier
read + guard + GRANULAR per-slide/-class legacy fallback (whole-deck legacy only on a tier-1
raise or bulk-tier-unavailable); **off** — forces the legacy ~12-min JXA inspect. The old
**`verify`** mode (run both reads, diff at runtime) was **REMOVED**: its check (`_spec_fields_equal`,
itemIndex-only-excluded) was stricter than the validated write-affecting gate, so a re-derived
autoshrink `fontSize` that never lands on write made it ALWAYS fall back on real decks — useless
as an intermediate (a stale `OBED_OFFLINE_READ=verify` now resolves to `on`). The default flip
bar was met and the flip shipped: gate GREEN on both decks with the REAL bulk read AND one
end-to-end `on` write remap placement-identical to a legacy-read run (Session-15 handover above).

**PENDING at handover (pick up here):**
1. ~~Executor building the two-tier code~~ — **DONE**, committed `9ad2ba3` (bulk_geometry.js +
   inspect.bulk_geometry + two_tier splice + granular fallback + remap_keynote wiring).
2. ~~Run ONE real Keynote bulk-read pass~~ — **DONE + GREEN (Session 15, 2026-08-29).** Live
   `bulk_geometry(Map_Extracted_Wall_1st)` single-op, Keynote clean: **51.8s** (0.86 min) vs the
   ~12.6-min JXA inspect (**~14.6×**). All **1636/1636** real frames match the cached JXA frames
   **<0.5px** (0 within-2px-only, 0 >2px, 0 unmatched — the real bulk read == the JXA-double the
   gate was proven against). Real-value two-tier splice: `bulk_ok=True`, 1620 spliced, 0 fallback;
   write-affecting transform diffs **0**, reuse diffs **0** → **plan gate GREEN with live values.**
   Read-only (deck mtime untouched). Bench: `scratchpad/live_bulk_pass.py` (session-local;
   re-derive from `tests/test_offline_inspect.py::test_two_tier_splice_makes_write_affecting_gate_
   green_map_deck`, swapping `_bulk_double_from_jxa` for the real `bulk_geometry`).
3. **STILL TO DO before flipping default to `on`** (the handover's own bar):
   - (a) ~~same live bulk pass on `Full_Report_Card_Wall`~~ — **DONE + GREEN (Session 15).** 155
     slides, live `bulk_geometry` single-op, Keynote clean: **283.7s** (4.73 min) vs ~12.6-min JXA
     (**~2.7×**). All **3123/3123** real frames **<0.5px** vs cached JXA (0 >2px, 0 unmatched).
     Real-value two-tier: `bulk_ok=True`, 2813 spliced, 0 fallback; transform diffs **0**, reuse
     diffs **0** → **plan gate GREEN.** Read-only (deck mtime untouched). **So the gate is GREEN
     on BOTH decks with the REAL bulk read.**
   - (b) ~~one real end-to-end write remap → placement-identical~~ — **DONE + GREEN (Session 15).**
     `OBED_OFFLINE_READ=on` remap of the whole Map deck: log confirms *"Read … two-tier (offline
     IWA + bulk geometry) — skipped the full Keynote source inspect"* (offline used, NO fallback),
     and **every plan-level fact is byte-identical** to a legacy-read run (recipe map transform,
     off-frame counts, 5-slide duplication plan, `Applied 713 missed 0`, collections, stat-finalize
     `111/9/116`, map `{11,18,1067,659}`). Output-deck geometry (bulk_geometry both decks,
     `scratchpad/diff_outputs2.py`): **identical frame multiset for every kind** — set-match
     group 0/174, image 0/249, text 0/24 over-16px, 0 unmatched. The by-INDEX diff showed 142
     group frames "diverging" — a RED HERRING: the stat-finalize **Bring-to-Front GUI pass reorders
     the `groups` collection's kindIndex** run-to-run (read-mode-INDEPENDENT), so groups must be
     compared as a set, not by index. **So the offline-read output is placement-identical to the
     legacy-read output. The full flip bar is MET.** Speed both decks: Map **51.8s** / Full
     **283.7s** — both well under 12.6 min.
   - (c) **verify MODE FALLS BACK on these decks — by design, not a placement bug.** The shipped
     `_plans_equivalent`/`_spec_fields_equal` (remap_keynote.py:108) excludes ONLY `itemIndex`, so
     it is STRICTER than the validated write-affecting gate (`_wa_fields_equal`, which also excludes
     `fontSize/font/color/opacity/matchText`). The offline read re-derives ONE autoshrink `fontSize`
     (Map slide 7 text[1]: 29.4 vs 19.6 — Keynote re-autosizes on write, so it never lands), so
     verify declares divergence and uses legacy. Confirmed: strict `_specs_equivalent`=False on
     exactly that 1 fontSize field, `address-set equal`=True, write-affecting=green. **Consequence:
     `verify` is NOT a useful confidence intermediate on autoshrink decks — it always falls back.**
     OPEN DECISION (Session 15, put to user): align verify's check to the write-affecting field set
     (makes verify usable, but loosens what "verified" asserts) vs leave it strict (conservative,
     documents the fallback). Independent of the default flip, which rests on `on` (write-affecting
     proven), not verify.
   - **NEXT:** flip `offline_read_mode` default `off`→`on` (one line, `remap_keynote.py:70-71`) —
     bar met. Test artifacts left in `output/`: `Map_Extracted_Wall_1st_CG.key` (legacy-read) and
     `…_CG_ON.key` (offline-read), ~1.15 GB each, gitignored — delete when done inspecting.
- **PPTX is NOT needed for the fallback**: it gives image/text exactly but the group `grpSp`
  stored-frame is the WRONG value for union-groups; the bulk read gives all three correctly in
  one pass. PPTX only re-enters if the bulk read measures surprisingly slow — it did not (51.8s).

**CACHE-CORRUPTION LESSON (cost hours this session):** concurrent Keynote access (overlapping
warms, or Keynote re-saving mid-read) corrupts a warm → partial payload (empty tail slides),
cached under a stale digest. Warm ONE deck at a time, force decks CLOSED, keep all agents
OFFLINE. Verify a fresh payload has no empty slides + image count == IWA before trusting it.

## The number block — DONE

The 183/86/14/269 block: packing shipped (#32) and template-taught sizing shipped
(stat-finalize). The open hypotheses (H15/H16/H19 — text scale/reflow) were resolved by the
AS-geometry work (H19's "setting width/height yanks to (0,0)" is exactly what AppleScript
geometry fixed). Nothing to re-investigate here.

## Cue palette + DSK generator → split out (2026-08-28)

Moved to `.agents/plans/cue_palette_and_dsk_generator.plan.md` so this plan stays
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
