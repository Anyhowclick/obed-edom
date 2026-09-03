---
name: CG resizer — optimizations (read + write tracks), bug backlog, features
overview: "ONE plan for the CG resizer (merged 2026-09-03 from cg_resizer.plan.md + resizer_optimizations.plan.md; the umbrella tranche map lives here now). Read `.agents/skills/obed-edom/SKILL.md` first — every durable Keynote/IWA finding lives there; this plan points into it. PRIORITY = the optimization tracks. ORDER: (1) current output-bug fixes (batch 1 in flight, batch 2 next) → (2) clear TRANCHE 1 (W1 offline-write stabilise + default-flip bar; R1 nested-bulk probe) → (3) TRANCHE 2 = the immediate optimization TODO: R2 readback two-tier → propose two-tier, W2 z-order patch (stroke restore lands with batch 1) → (4) R0 leftovers + feature backlog + constellation cluster affine. Shipped work is a compact table at the end; insights are one section. Discipline: measure first, probe before trusting (AppleScript first; COUNT affected objects), 2/1/2 workflow (planners sonnet+opus, fresh sonnet implements, reviewers sonnet+opus; implementers never review their own work), never concurrent Keynote, commits forward-dated ~10:00 UTC, no PRs."
todos:
  - id: output-bugs-batch1
    content: "IN FLIGHT 2026-09-03 (plan: session a0211898 scratchpad probe/plan_bugs_final.md, signed off by both planners). F stat-finalize nits (shipped 90aaa4e); E slide-8 backdrop rides the title-slot ty=28 → pin backdrop y=0; A 'Global Missions' badge = 3 top-level drawables (plate/globe/text) under the map — obedBadgeRaise raised only the last text match and never ran on no-stat slides → badge_raise_report + obedRaiseItem plate→globe→text on every remapped slide, three gates relaxed; C card-photo stroke 3.0→0.25 after the canvas shrink → restore SOURCE width via ONE Index/DocumentStylesheet.iwa patch, unconditional (this IS w-border-stroke-width's production rule), guarded out<src and out≤src·canvas_scale·1.1, pairing by (colour,pattern), no gutter change; B1/D1 caption-bearing groups (≥3-char leaf text, checked in classify_item only, after the PIN_NAME_RE/movie short-circuits) are `other` not `pin` so the pass-2 font pass reaches the 5 column-1 cards and the 27 constellation circles. The '+' marks are Keynote's editor-only clipped-text badge (exports show none; wrap-off captions spill horizontally) — nothing to delete. VERIFY: unit tests, score_resize before/after (baseline banked), ONE live Map remap + export, probe/verify_batch1.py + verify_slide9.py."
    status: in_progress
  - id: card-template-size-reflow
    content: "BATCH 2 (owner ACCEPTED 2026-09-03). Owner's rule: the template dictates SIZE incl. text pt; colour/font/runs/builds from source. Photo cards take the template card rect (120.4×100 vs today's 111.9×93) and captions the template swatch (10pt) with whole-point step-down while the measured string (PIL, Amplitude Bold) exceeds box_w − 2·inset (gold reproduces 71/71 captions; floor 8pt; report every step-down); seed sizes into stat-finalize's exact-text size_map. Consequence: re-pitch the slide-4 grid to gold's 126.9/104.9 and reflow 8×6 → 6×8 (today columns 7–8 sit OFF-CANVAS at x=2064/2187). Land AFTER batch 1 is verified live; re-check the stroke/gutter inequality (≥7pt clear) after the re-pitch."
    status: pending
  - id: w-offline-write-stabilise
    content: "TRANCHE 1 (W1). SHIPPED ec20f4b/a8b27ac/5577e27 (OBED_OFFLINE_WRITE off|on|verify, default OFF = byte-identical production; deck-level patcher, streaming in-place rewrite, reconcile_counts refuse gate, AS fallback, read-back verify, scripts/offline_write_ab.py). The 'pass-2 0.48× group shrink' was an ORACLE ARTIFACT (banked specs_slide9.json + A_prime predate 8a8ef7a); the offline write is correct and survives pass 2. TO CLEAR: (1) re-bank the write-gate oracle — regenerate specs_slide9.json from the CURRENT planner (write_specs_sidecar) and rebuild A′ (one Keynote open); (2) re-run offline_write_ab.py with a HEALTHY A (Accessibility granted; gate must hard-fail on an unhealthy A: pass-2 done/skipped counts, dedup counts), plan-as-oracle for exact classes, identity matching, group children bucketed separately, groups compared as a SET; (3) default-flip bar = gate GREEN on both gold decks with real patches AND one end-to-end `on` run placement-identical to a scripted run. Design points that stand: deleteHides stays in pass 1 and the patcher bridges kindIndex (never both); reuse slides stay fully in Keynote; the JXA attrs pass stays in pass 1; mapReadback assertion moves to the verify. Payoff: replaces the ~100ms/command AS geometry phase (~100–155s Map, multi-minute Full) with seconds."
    status: pending
  - id: r-nested-bulk-probe
    content: "TRANCHE 1 (R1), PROBE only. Whole-deck nested bulk read to collapse the ~61s bulk tier (~10 events/slide × 63 ≈ 630 events, overhead-dominated) to ~12–16 events. Forms: AppleScript `position of every text item of every slide of document 1` (osascript FLATTENS nested lists → in-script serializer) vs JXA `doc.slides.textItems.position()` (may not marshal; probe AppleScript FIRST). Must demonstrate on a REAL deck containing a locked object, a movie, an empty collection and a zero-item slide: (1) outer length == slide count with skipped slides in position; (2) inner order == per-slide order, value-identical to bulk_geometry.js for 4 kinds × 3 props; (3) empty collection → [] in position, never omission; (4) text placeholders at sublist ends; (5) timing on GW (63 slides) and a Map-class dense deck under `with timeout of 3600`; (6) failure semantics: whole-event raise (safe) vs silent partial (the danger). Keep the {slideIndex:{kind:rows}} contract and the plan.slides subset path the checker's edit-loop cache depends on. Payoff if green: bulk 61s → ~10–20s (checker cold ~94s → ~50s; Full remap bulk 283.7s → ~60s; write-track verifier). `r-bulk-counts-plan` (feed offline counts so the JS skips empty/known collections, re-evaluate on guard failure) ONLY if this fails."
    status: pending
  - id: r-readback-two-tier
    content: "TRANCHE 2 (R2) — IMMEDIATE optimization TODO after tranche 1 + current fixes. Switch the resizer readback (remap_and_inspect(validate=True) → inspect_keynote(dest, export_dir, slide_range) at remap_keynote.py ~992; dashboard default validate=True) to the two-tier offline+bulk read. Gate MET (checker machinery shipped, e2e_run_parity green). Own caveats to close first: (a) accuracy evidence covers SOURCE decks — run a field-parity A/B on ≥1 real _CG.key per gold family (offline+bulk vs cached JXA readback, every validate-consumed field + validate_inspect flag parity; compare groups as a SET post-Bring-to-Front); (b) slide_range: a ranged extension must disable the cache like legacy; A/B one ranged run; (c) package-directory save → whole-deck legacy fallback (log it); (d) r-count-guard landed (done); (e) r-readback-nocache-fix landed (done); (f) keep use_cache=False when switching to the checker machinery (it hashes + cache-writes by default). Consumers on this path are only validate_inspect + scalar fields (field audit passed). Payoff: ~8 min per validated resize on report decks (756s → ~290s), ~3.5 min sermon-class. Risk MEDIUM. Files: inspect.py, remap_keynote.py, web/app.py. Sequence with W1 (both edit remap_keynote.py)."
    status: pending
  - id: r-propose-two-tier
    content: "TRANCHE 2 (R2b), after r-readback-two-tier's A/B exists. The resize PROPOSE source read is still full JXA (_run_resize_propose → inspect_keynote at web/app.py ~1468, not acquire_wall_payload): a new deck's first propose pays ~12.6 min although apply reads two-tier. Same consumer audit plus deck_slide_digests parity (pairings/framings key on digests of ALL slides), propose_framings/planner parity, and cache the two-tier propose payload under the digest so propose→apply→re-propose reuse it (cross-serve is then deliberate — verify once). Payoff: first propose 12.6 → ~3 min. Risk MEDIUM (fingerprint churn; worst case a one-time pairing re-align)."
    status: pending
  - id: w-zorder-patch
    content: "TRANCHE 2 (W2). Offline drawablesZOrder+ownedDrawables reorder (patch BOTH identically) at the W1 hook, LAST per slide, replacing pass 2's GUI Bring-to-Front raises (obedRaiseSlide + the badge raise) and the resizer's Accessibility dependency. PROBE LIVE PASS 99771bf (2026-09-02): Keynote 15.3.1 honours a patched order on open, a re-save keeps it, the render changes; permute within the target ids' slots (a fresh deck carries 3 placeholder drawables). Correctness is already handled by the index-guarded descending raise (23de0d2) — this is purely the optimisation: ~0.55s/raise × N GUI clicks + Accessibility + run-to-run group-index churn. Must run after pass 2's font sizing (or recompute stat indices), and the read-back compares reordered kinds AS A SET. Gated on W1 stable. Risk MEDIUM."
    status: pending
  - id: r-cache-quick-wins
    content: "R0 leftovers, Keynote-free, independent: (1) r-propose-from-cache — a ranged propose discards the cached full payload it holds (cached_payload for numbering, then a fresh ranged JXA read that never caches); subset the digest-verified full payload instead; A/B a subsetted propose vs a fresh ranged one on a warmed gold deck. (2) r-acquire-cache-read — acquire_wall_payload (remap_keynote.py ~145-215) never consults the digest cache, so every apply pays the bulk tier (51.8s Map / 283.7s Full) even with a byte-current cached payload; add a cached_payload consult, subject to the cross-serve provenance check (`reader` field). (3) r-digest-sidecar — deck_digest SHA-256 of the GB deck is paid several times per cycle (~6s each on 6.8GB); sidecar under the CACHE ROOT keyed (path, size, mtime_ns), single-file case only. (4) r-misc-cleanups remainders: (1) remove the doomed JXA exportImages attempt in inspect_keynote.js (never produced PNGs; measure its cost first); (5) export_applescript uses the disproven doc-bind (`open POSIX file` with no close-by-name) — align with close-by-name → open → document 1; (2) checker-side export fold into the bulk_geometry session; legacy inspect_keynote cache-hit full re-read on JSON-present/PNGs-evicted (~274s case)."
    status: pending
  - id: r-reuse-photo-placement
    content: "BUG BACKLOG (B). Reuse is KEPT (measured +39% on contiguous map series). (A) REUSE-ADD (0,0) YANK: an add on a reuse target has width/height set first (yanks to (0,0)) and position restored only when spec.x/y are set; a spec-less add rides the paste at its wall coord → off-frame. Bounded reuse-path fix (write order / restore condition / give spec-less adds a placement). (B) FRAMING COVER-FALLBACK OFF-FRAME on dense infographic slides (124/125-class, pairQuality=0) — reuse-INDEPENDENT (identical off-frame counts on/off); a framing item touching all slides, own workstream. Once W1 removes the AS-geometry bottleneck, dropping reuse becomes cheap — revisit then."
    status: pending
  - id: constellation-cluster-affine
    content: "BUG BACKLOG (B) / recipe work, after batch 2. Per-CLUSTER affine with template anchors (section below). Today one uniform fit-to-width (0.48×) leaves the top half empty; gold scales each CHC cluster ~0.82× as a unit and pushes clusters outward to fill the frame. Cluster discovery offline from line incidence; per-object size from the template circle swatches; placement by pairing clusters to template ANCHOR circles at gold positions (angular order around the building); hub lines rewritten by identity; radial frame-fit fallback when anchor count ≠ cluster count. Template needs one anchor circle per cluster + building/people rows/SOT at gold positions. Score offline against gold before any Keynote run."
    status: pending
  - id: builds-follow-source
    content: "BUG BACKLOG (B), bug (f), own workstream: builds/magic-moves must follow the SOURCE slide's per-slide build state (magic move on 1, static on 2, magic move elsewhere on 3) and must NOT be persisted from the reuse donor; may need to copy animations over. Memory reuse-target-builds-match-source. Related operator-visible items: church-name lists kept only per-slide whitelist and never carried by reuse (bug a, memory church-list-keep-side-panel-spec); 1 image tile-removal miss on reuse slide 4; reuse-target z-order operator-adjustable."
    status: pending
  - id: propose-pins-flag
    content: "FEATURE. Surface pins-paired (pairQuality) per template tile in the propose UI so a '0-pin' slide is flagged, not trusted. Image-similarity scores can invert the geometric fit on bespoke slides (Map slide 9: template 4 scored 0.69 but paired 0 → vetoed at remap; template 13 scored 0.06 but paired 34 at the right 0.483 scale)."
    status: pending
  - id: recipe-library
    content: "FEATURE. Recipes as browsable artefacts. Built then reverted: a page needing a borrowed transform usually needs two affines (map + badge). Revisit now badge-affine names groups by role — section below; the cluster affine is a third role."
    status: pending
  - id: stat-drift
    content: "FEATURE. Validation rule slide.stat_drift: a figure that changes between adjacent slides then holds. Ships at warning. Independent; stubbed in validation_rules.yaml."
    status: pending
  - id: outline-editor
    content: "FEATURE. Editable outline view extending OutlineResultView, LibreOffice page-view toggle, in-place surgical writes to the source .docx with timestamped backups. Design below."
    status: pending
  - id: image-cues
    content: "FEATURE. Image cues as an asset slot count + shape per cue. Both capabilities (image place, movie via file-name reassign) probed and present. Taxonomy below."
    status: pending
  - id: iwa-surgical-write-generator
    content: "FEATURE (generator). Use the offline IWA writer (ec20f4b) to set cyan superscript verse numbers offline and retire generate's GUI Copy/Paste-Style pass 2 (Accessibility, silent-fail). Style-table patch = a harder byte class than geometry floats; own spike + per-deck openability test."
    status: pending
isProject: false
---

# CG resizer — optimizations, bug backlog, features

**Read `.agents/skills/obed-edom/SKILL.md` first.** Every durable Keynote/IWA finding —
bundle-id targeting, the verified scripting limits, cache versioning, the template contract,
offline read/write facts — lives there. This plan is the executable delta plus the reasoning
a new agent would otherwise rediscover. Cue palette + DSK generator: their own plan.

## Discipline (applies to every item)

- **Measure first.** Every payoff figure is measured (cited) or marked estimate; never ship on
  an estimate. Say what a change ACTUALLY does (native-res crops, not downscaled previews).
- **Probe before trusting.** Any "Keynote can't do X" is probed in AppleScript first; verify a
  batch-op probe by COUNTING affected objects, never by timing a try-wrapped call. Don't
  inherit "can't" comments (the "JXA cannot scale a group" lore cost a session).
- **2/1/2 workflow** for non-trivial items: planners sonnet + opus agree the plan → ONE fresh
  sonnet implements → reviewers sonnet + opus (planners reusable) verify; implementers never
  review their own work. Trivial one-liners and docs skip it.
- **Never run Keynote concurrently.** One deck warm at a time; agents offline during a live
  read/write. Keynote here is "Keynote Creator Studio.app" = Keynote 15.3.1. Close-by-name →
  open → `document 1`; `with timeout of 3600`. Fast probe: APFS-clone (`cp -c`), mutate, read,
  close saving no. Never `/private/tmp` for `.key` files. Accessibility must be granted or the
  reuse pastes and GUI raises fail silently.
- **After ANY read-path change** re-run `scripts/e2e_run_parity.py` (baseline in its docstring).
- Commits at verified checkpoints, forward-dated ~10:00 UTC (18:00 SGT), never re-date cited
  SHAs; no PRs unless asked. Housekeeping at every landing: todo status here, SKILL, memory.

## Current state (2026-09-03, branch `fix/checker-followups`)

- **Pipeline:** two-tier offline source read (`OBED_OFFLINE_READ` default ON: IWA for
  everything + one bulk Keynote read of group/image/text frames) → pass 1 in Keynote (canvas
  set, layout import/apply, JXA attrs pass, AS geometry with `set properties`, reuse
  duplication, deleteHides, save) → optional offline IWA geometry patch (`OBED_OFFLINE_WRITE`,
  default OFF) → pass 2 stat-finalize (dedup, index-guarded font pass, recorded raises, badge
  raise, export).
- **Owner's contract (2026-09-03):** the template `Base_CG_Assets.key` dictates SIZE (and
  position where appropriate) for matched objects, **including text point sizes**; colour,
  font family/style, run formatting and each slide's builds/animations are always copied from
  the SOURCE (memory `template-size-source-style`, SKILL "Text styling").
- **Just shipped:** stat-finalize index-guarded addressing (`23de0d2`) — the Map slide-9
  collision (53/67 groups share sig "UPG") shrank two pins' text to ~1.3pt and left the 40
  targets unscaled; jobs now resolve by `groupIndex` verified against the cached signature
  census, unique-sig fallback, else skip-and-report; raises from recorded targets, descending.
- **In flight:** output-bugs batch 1 (todo). Then batch 2, then tranche 1 → **tranche 2**.

## Order of work

1. **Current fixes:** batch 1 (F, E, A, C, B1) → one live Map remap → batch 2 (card template
   size + caption step-down + grid reflow).
2. **Tranche 1:** W1 stabilise (re-bank the oracle, healthy-A gate, default-flip bar);
   R1 nested-bulk probe (probe only; `r-bulk-counts-plan` only if it fails).
3. **Tranche 2 — the immediate optimization TODO:** R2 `r-readback-two-tier` →
   `r-propose-two-tier`; W2 `w-zorder-patch` (stroke restore already lands in batch 1).
4. **Then:** R0 quick wins, bug backlog B (reuse yank / framing fallback, constellation cluster
   affine, builds follow source), feature backlog.

### Tranche map

| Tranche | Item | Keynote | Status / depends on |
|---|---|---|---|
| W0.1–W0.4 | tmp-path fix, skipped-slide bulk skip, z-order probe, stroke probe | probes only | DONE (2ac04db, 695199d, 99771bf, c4dc5e5) |
| Fixes | output-bugs batch 1 → batch 2 | one live remap each | IN FLIGHT / next |
| **W1** | `w-offline-write-stabilise` | gate on both gold decks | shipped default OFF; re-bank oracle, healthy-A gate, flip bar |
| **R1** | `r-nested-bulk-probe` | yes | after W1's gate window |
| **R2** | `r-readback-two-tier` → `r-propose-two-tier` | output-deck A/B | R0 done; own caveats (a)–(f) |
| **W2** | `w-zorder-patch` (stroke prod folded into batch 1 C) | yes | W1 stable |
| R0 | `r-cache-quick-wins` | no (A/B on warmed decks) | anytime, Keynote-free |
| B | reuse yank / framing fallback, cluster affine, builds | yes | independent |
| drop | `w-hides-offline` (optin chose the deleteHides bridge), skipped-slide option (2), Stage B / batch z-order / batch delete via their original mechanisms | | closed |

R1/R2 touch `inspect.py` / `bulk_geometry.js` / `remap_and_inspect`; W1 edits
`remap_keynote.py` — sequence, don't interleave. The checker's edit-loop cache wraps
`bulk_geometry_fn` at the inspect.py call site and depends on the `plan.slides` subset path:
any nested-bulk rewrite must preserve it.

## Write track — what stands after the reviews

- Dominant cost was the AS geometry phase (~70% of a heavy-slide run, ~100ms/command redraw
  even off-screen, no cross-object bulk write); surgical IWA float patches are the missing bulk
  write. Byte-risk ladder: float patches < list reorder < object removal.
- Proven: object-level patching of ONE stored member (values clean, snappy churn only);
  locality (every slide's drawables in exactly one member, derived from `id_to_file`, never
  from the slide id); Keynote opens patched decks clean and re-saves them first-class; size
  lives in `bezierPathSource.naturalSize` (patch size AND naturalSize; a line's length is
  `naturalSize.width`); write patched bytes IN PLACE (`com.apple.macl`); masked-image size
  writes 108/108 @0.54px; group-child scaling (`s = spec / REPORTED union`, origin = spec +
  (stored − reported)·s, descendants ×s, masks too) with no double-scale on open; NBSP zip
  member names must be preserved raw; a text box is never a line.
- Group move = DELTA on the stored origin (stored ≠ reported on stale-frame groups); soft
  classes (group/text/masked image) seed from a bulk read of the SAVED deck, never from the
  offline composition alone; refuse a slide whose reconcile counts disagree (fail-safe to the
  scoped AS script). Reuse slides stay fully in Keynote.
- Known cosmetic: AS geometry `set properties {width,height}` renders as two origin snaps; gone
  on offline slides.

## Read track — what stands after the reviews

- Bulk-read inspect (227s → 57s, byte-identical) and the two-tier read (Map 51.8s / Full
  283.7s vs ~12.6 min JXA; plan gate GREEN on both decks with live values) are shipped. The
  bulk tier is Apple-Event-overhead-dominated, hence R1.
- Correctness guards that exist: `reconcile_counts` wired into the splice (text slack [0,2]
  trailing-only, placeholder tail check); array-length guards per bulk array; granular per-
  slide/per-class legacy fallback. Only `role="hide"` geometry is write-dead — lines and group
  w/h ARE written; verify "is this field written?" against `remap_keynote.js`.
- Compare output groups as a SET, never by index (Bring-to-Front reorders kindIndex run to
  run); the canvas shrink jitters the map ~8px/run — read pixel diffs against that floor.
- Cache facts: `deck_slide_digests` hashes no geometry; ranged reads never cache; cross-serve
  (checker-written payloads served to propose) is consumer-compatible but carries a `reader`
  provenance guard — keep it.

## Constellation slide — per-cluster affine with template anchors

The constellation (Map slide 9 = 67 groups / 68 lines; Full 134→127) is not one affine. Gold
scales each CHC cluster (hub circle + UPG satellites + church/book icons + white connector
lines) **~0.82× as a unit**, then pushes clusters outward, keeping their angular order around
the building, until the frame is filled; the yellow hub lines re-anchor to the moved CHC
circles. Today's planner applies one uniform fit-to-width (**0.48×**) and leaves the top half
empty. (The earlier "two-knob" reading — scale nodes in place ~0.85 + pull centres toward the
centroid ~0.5 — was the same observation from the other side.)

1. **Cluster discovery, offline, automatic.** Every circle is a group. Membership comes from
   line incidence: a yellow line from the building to a CHC circle marks a cluster root; white
   lines from that CHC circle to UPG circles and icons mark members. Edges match nodes by
   **identity** (recorded incidence), never proximity; a deleted node's edges are dropped.
2. **Size from the template.** The template's sample CHC/UPG circles give the per-object scale
   (~0.82×), applied uniformly within each cluster; circle text follows the pass-2 font rule.
3. **Placement from template anchors.** The template slide carries one plain CHC-sized circle
   per cluster at its gold position (13 on the Map deck) plus the building, the two people
   rows and the SOT mark at gold positions. Pair wall clusters to anchors by angular order
   around the building; translate each cluster so its CHC circle lands on its anchor; rewrite
   hub lines to the new CHC centres.
4. **Fallback** when anchor count ≠ cluster count: keep each cluster's angle from the building
   and scale its radius anisotropically to fill the frame — never overlapping the building,
   never off-frame.

Template needs: the size swatches it already has, plus the anchor circles and bottom-band
objects at gold positions (thirteen circles placed by hand once). Score offline against gold
(predicted cluster centres/sizes) before any Keynote run. Ask first whether the slide's
content changes yearly — that gates how much automation is worth.

## Recipes as browsable artefacts (revisit)

A template slide only helps if something *pairs*; what transfers instead is the **recipe** —
a portable subset of the learned transform. Built and reverted: a page that cannot learn its
own framing is usually a map-and-badge page that wants **two affines, not one** (report card
slide 94: the badge rode the map's affine off-frame). Now `badge-affine` names groups by role:
`portable_recipe` carries `[{role, s, tx, ty}]`, `apply_portable_recipe` resolves each role on
the page in hand; an orphaned role fits to its own footprint (`visible_content_union` over
the orphan subset, keeping position relative to the frame — fit-to-frame centres today, and
the union is measured against the full 7680). Storage: a tracked `recipes/` folder of small
labelled JSON files; plumbing `recipe_overrides: dict[int, dict]` beside `framing_overrides`.

## Outline editor in the dashboard

Editing surface: HTML rendered from the .docx (`load_paragraphs` returns per-run
bold/highlight/superscript/color; `ListNumberResolver` resolves auto-numbering;
`OutlineResultView` renders cue chips at exact offsets via `segments()` — make it editable).
Page view: LibreOffice `soffice --headless --convert-to pdf`, read-only, cached until the next
save, disabled when absent. Writes go to the source .docx in place (scoped reversal of
SKILL's never-overwrite rule; Sermon Checker stays read-only): timestamped backup per save
under `output/.outline-backups/{stem}/`, **surgical edits only** (operation list against
touched paragraphs, as `_apply_ops`/`_make_run` in `annotate.py`). Semantic cues in, operator
cues out (`annotate_outline` converts at generate time). Validate as you type with what the
parser knows.

## Image cues: design for these, build later

An image places from AppleScript with `position` and `width`; a movie is placed by creating
an image and assigning the video to its `file name` (converts the object, keeps geometry) — no
GUI automation, a template needs only a small image placeholder. Taxonomy: centre-panel photo
set, mirrored single set, full-centre media, design-authored collage (not operator-buildable),
grid cases (count + grid spec). So an image cue is a cue plus an **asset slot count and
shape**, with an optional background asset distinct from the content ones.

## Stat drift across adjacent slides

"11 Renovated Church Buildings" on one page, "44" on every page after. Compare text objects
across adjacent slides, matching on position and on wording with digits removed; flag a page
whose number disagrees with the run either side of it. Ships at `warning`.

## Operator / source-deck items (no code fix) and parked notes

- Slide-124: ~130×11px overlap between two right-side groups; slide-125: church list = 46
  opaque groups (source-deck ungroup); a verse's wall-authored hard line breaks (stripping by
  script destroys superscripts and small-caps LORD); sparkle-overlay placement; a caption in
  the "as it will look" preview.
- Never dedupe images (stacked map layers are coincident on purpose). The first ranged propose
  on a never-read deck cannot translate the range into Keynote's numbering and says so.
  Composite preview text is scaled wall pixels (close, not right). The JXA export has never
  worked (`exportError` carried while `export_slide_images` succeeds). PNG export fidelity
  differs 117px @ ≤2/255 between Keynote versions — keep watching.

## Shipped record (compact)

| Item | Commit(s) | One line |
|---|---|---|
| Keynote 15.x migration, framing confirmation, badge-affine, structural title, off-frame hiding + delete-hides, side-panel whitelist, number-block packing, operator notes, navigator numbering | (git log) | pre-Aug-28 feature work; findings in SKILL |
| AS geometry default, `set properties`, validate=False default, Stage A export fold | 56c104c, d1234e2, 9c32084 | speed banked (slide 8: 9:58 → 4:58) |
| bulk-read inspect | d218350 | 227s → 57s, byte-identical |
| IWA per-run style / grouped text | feat/iwa-per-run-style | offline runs on finalized decks |
| two-tier offline read, default ON | 9ad2ba3 + Session 15 | Map 51.8s / Full 283.7s vs 12.6 min; gate GREEN |
| r-count-guard, r-cache-hit-export-only, r-readback-nocache-fix (f3f19b1), r-reuse-side-content-strip (9f465ba) | — | read-side defects closed |
| w-spike0 (b8c7d68), w-spike1 core (5624eee), iwa_write patcher (5707d4d), write gate + A′ oracle (210b1c6, 233f388), group-child scaling (fe3cd87) | — | write mechanics proven |
| W0: tmp-path (2ac04db), skipped-slide bulk skip (695199d), z-order probe (99771bf), stroke probe (c4dc5e5) | — | Tranche 0 |
| W1 offline write opt-in | ec20f4b, a8b27ac, 5577e27 | default OFF; stabilise = tranche 1 |
| reuse group dedup (292802c), role=other group-child scaling + font pass (8a8ef7a) | — | reuse doubles fixed; group text scales |
| stat-finalize parity audit (7781de8), descending raise (aff1470), index-guarded addressing (23de0d2), nits (90aaa4e) | — | pass-2 addressing correct |

## Insights worth keeping

**Placement model**
- One affine per **role**, not per slide (badge, map, cluster); structural title detection
  beats wording; fill-don't-letterbox (`FILL_MAX_CROP_FRACTION=0.47`) was the one code-side
  gold-closeness win — the rest of the gold distance is editorial crop choice.
- The template is a size/position oracle, not a styling oracle. Content that carries text is
  not a pin (proximity classification skipped the font pass on 5 cards and 27 circles).

**Groups and text in Keynote**
- Setting a group's w/h scales its children (AS and JXA) but NOT their font size — the pass-2
  font pass scales child text by the group's affine; stat numbers take the template size.
- Group children are addressable in place via AppleScript; every JXA "limit" (group children,
  line endpoints, per-char styling, z-order read, masters, export) was JXA-only.
- Content-signature addressing collides; address by index verified against content and skip
  rather than guess. Keynote's clipped-text "+" is editor chrome; wrap-off text spills
  horizontally instead. Never re-assert a verse box's text.

**Speed (closed — do not rebuild)**
- JXA and AppleScript READ at the same speed (~11ms/property); wins come from doing less work.
  Each AS command on a heavy slide redraws (~100ms) even off-screen.
- Abandoned with load-bearing reasons: Stage B reopen-fold (a cold open of the 6.8 GB deck is
  ~3–4 s; the "17%" was a broken run), batch z-order (multi-select Bring-to-Front does not
  reliably raise above the map), batch delete (`delete {list}` throws -1700; the "315×" was a
  try-hidden failure).
- Keynote 15 doc-bind: `POSIX path of (file of d as alias)`; `name of document` drops the
  extension; close-by-name → open → `document 1` → verify name.

**Offline read/write facts**
- Keynote returns INTEGER geometry; line endpoints needed a mirror-flip fix; masked near-zero
  rotation collapses to the axis-aligned box; the group residual IS the autosize defect one
  level down. A no-op Keynote save rewrites the globals (stylesheet compaction, renumbering) —
  byte-level per-slide fingerprints are dead; a saved patch is laundered through Keynote's writer.
- Concurrent Keynote access corrupts warms; verify a fresh payload has no empty slides.
- Banked oracles go stale (the write-gate sidecar + A′ predated the group-scaling change and
  mis-read as a "0.48× shrink"): re-derive the plan from the current planner before comparing
  a deck against "the plan"; any A/B gate must hard-fail on an unhealthy baseline.

**The operator loop**
- Confirmation only bites where the template has a framing worth picking; pages with no
  candidate are the prompt to add template slides. Fit-to-frame still overrules overrides on
  pages the template does not describe — tell the operator per page, never in a footnote.
- **The metric-that-misleads pattern:** framing selection went through five rewrites in one
  session, each fixing a real case and creating the next — a metric asked to infer something
  the data does not contain. When selection needs a sixth exception, *ask* (the Sermon
  Checker's propose/correct/remember-by-digest pattern is the template).
