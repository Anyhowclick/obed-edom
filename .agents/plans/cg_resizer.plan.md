---
name: CG resizer — active work and retained engineering record
overview: >-
  Consolidated 2026-09-15. W1 offline geometry is shipped and default-on. W2 offline z-order is
  implemented and default-on since 2026-09-15 (PR #133). This file is the single resizer plan;
  the standalone W2 plan was folded into it. Completed feature diaries live in git and the
  Obed-Edom skill, not here.
todos:
  - id: text-mask-default-flip
    content: >-
      Promote the live-validated autosize-text reposition and axis-aligned masked-crop paths from
      opt-in to default-on only after a fresh current-input whole-deck gate. Work branch:
      `codex/resizer-offline-flip-gate`. The gate keeps offline geometry and z-order on in both arms;
      arm A disables `OBED_OFFLINE_TEXT`/`OBED_OFFLINE_MASKCROP`, arm B enables them, and every other
      experimental write flag is forced off. Run records must persist the complete arm configuration
      and bind any reused evidence to the source/output deck digests. Geometry/live-verify bars,
      pass-2 parity, card-border integrity, and z-order health all gate. Geometry cannot prove crop
      correctness or text wrapping, so final GREEN additionally requires a digest-bound visual report:
      per-region crop comparison and per-label text comparison, each with null and positive controls.
      Keynote remains owner-gated; do all runner/tests/oracle preparation first and run both live arms
      serially on unlocked copies, quitting Keynote between them. After GREEN, change the two defaults
      while preserving explicit `off` kill switches, update docs/tests, and run every local suite.
      DONE 2026-09-21: Full Report Card 155-slide A/B ran serially with Keynote quit between arms;
      pass-2, 83/83 card-border refs, 4,658/4,658 scripted operations, offline consistency, z-order
      `FRONT_BLOCK_OK 88/88`, and 100% drawable identity all passed. After independent Opus review,
      the visual oracle was hardened to bind A/B/null preview manifests, use a second arm-A export as
      its real null, score object-local difference support, compare four-direction displacement
      controls, and enforce an alignment-aware 8px phase-correlation translation ceiling. It passed
      339 autosize labels and 130 changed mask regions; 27 labels and 13 masks were wholly off-canvas,
      maximum measured text translation was 7px, and maximum composed crop delta was 1.281px. Both
      banked arms were then inspected independently through Keynote with complete live-verify coverage
      before the final reuse replay. Bank: `output/bank/2026-09-21/text-mask-default-flip/`. Defaults
      flipped on; explicit `off`/`0`/`false`/`no` remain kill switches, and unknown values fail closed.
    status: completed
  - id: w2-final-live-gate
    content: >-
      Re-run the W2 RAISE10 and Gold live gate after PRs #128 and #131. If every eligibility,
      front-block, pixel, counter, and build-order bar is green, flip OBED_ZORDER_WRITE to on.
      DONE 2026-09-15: RAISE10 GREEN; Gold RED only slide 19 (owner-deferred); default flipped
      on (PR #133).
    status: completed
  - id: w2-deletions
    content: >-
      Remove the GUI raise path (`obedRaiseSlide`/`obedBadgeSlide` emission), the Accessibility
      pre-flight, and reuse step B now that the offline z-order write is the default; keeping
      `off` working until then is NOT required — owner decides scope. Piece 1 (GUI raise path
      out of `keynote.py`/`remap_keynote.py`), piece 2 (A/B gate + SKILL.md docs), and piece 3
      (reuse step B) DONE 2026-09-16, integrated on one PR.
    status: completed
  - id: w2-ambiguous-sig-positional
    content: >-
      Resolve shared, non-twin signatures as a cardinality-matched set (`len(groups) ==
      len(jobs)`, membership not position — Keynote's save path can scramble group order within
      a kind, so `groupIndex` is not used here) instead of refusing (Gold slide 19 legend, 66
      jobs). DONE 2026-09-16: Keynote-free, Gold slide 19 resolves 66/66 on both banked arms,
      every other Gold and RAISE10 slide unchanged. Live confirmation is the next Gold gate,
      expected `zorderGui=[]`.
    status: completed
  - id: live-verify-zorder-bridge
    content: >-
      Live verify addressed the saved deck by `(kind, kindIndex)`; the offline z-order patch
      rewrites that per-kind order, so PR #142 excluded z-order-patched slides — a near-vacuous
      oracle (Gold 2/19, RAISE10 0/11) still reporting `liveVerifyPass: true`. Bridge it
      writer-side. DONE 2026-09-17 -> PR #152 (`claude/live-verify-zorder-bridge-0c598b`). Piece 1:
      `run_offline_zorder` returns `kindIndexMap` (pre/post-patch `derive_kind_index`, join on
      `(id, kind)` so a dual emits two records safely); `verify_live_frames` remaps `kindIndex`, a
      mapped-but-missing index is a counted miss. Piece 2: `verify_live_frames_multiset` (membership
      bar for the `group`-on-stat-slide bucket, which has no per-index delete tokens),
      `live_verify_coverage` line, `GATE_VERSION` 3->4 (`COMPATIBLE {3,4}`, v3 absence = not
      measured), `scripts/replay_live_verify.py`, SKILL.md. Two live-run fixes: string-key
      `kindIndexMap` so `write_run_record` round-trips (tests used string keys and hid the int-key
      crash); AppleScript-fallback group buckets routed NOT-GATED per `(slide, kind)` (the
      w2-ambiguous-sig groups the offline `group-missed` line already excludes — offline-verified,
      not gating the bridge). LIVE-ACCEPTED 2026-09-17 both arms GREEN: Gold positional 19 (17
      remapped), set `group Δ0.00 n=67` PASS, not-gated 9, `uncovered []`; RAISE10 11/11, `uncovered
      []`; `zorderGui 0` both. Bank `output/bank/2026-09-17/live-verify-bridge/`. Set bar proves
      membership not assignment; live-gated group coverage is intentionally thin (the fallback
      groups are NOT-GATED, §(d) tradeoff). Optional piece 3 (per-index dedup delete tokens to gate
      the fallback groups too) remains unbuilt. Awaits owner merge + Codex.
    status: completed
  - id: reuse-photo-placement
    content: >-
      Closed by construction: slide reuse removed 2026-09-16 (w2-deletions piece 3). The
      constellation residuals on Full `131,133,134,144` that used to be attributed to this
      workstream now live under `constellation-cluster-affine`.
    status: completed
  - id: constellation-cluster-affine
    content: >-
      Replace the constellation's one-slide affine with per-cluster sizing and template anchors
      if the owner confirms the content changes often enough to justify automation. Residual
      reversals/placements on Full constellation slides `131,133,134,144` belong here.
    status: pending-owner-decision
  - id: gold-6-backdrop-series
    content: >-
      SYMPTOM: Gold output slide 6 China backdrop not aligned with slides 5/8/9 (the owner sees
      them as one series, raised 2026-09-10 and again 2026-09-16 evening). SCOPE NOTE
      (2026-09-16, owner): slide 7 is NOT part of this bug — in the Gold output the magic move
      shifts slide 7's photo right to accommodate its 12 thumbnails, which is intended framing;
      slide 7 must stay untouched by this fix. OWNER CRITERION (stated twice, 2026-09-16): the
      source deck already aligns the series — slide 6's crowd-China photo is authored to sit on
      slide 5's map outline — so the resizer must PRESERVE that source alignment by applying to
      slide 6 the same affine slide 5 received. Frame coverage is not the criterion; the resulting
      ~130px uncovered top band (ty=129.99 from a 2752-tall image on a 1080-tall one) is accepted
      and must be REPORTED, not used to reject the fix. The previously logged "second defect"
      (slide 5's backdrop 100px off 8/9, dest x -743 vs -843) is RETRACTED as a defect: it
      reproduces the source's own inset authoring (map inset at wall x 3158 on 5 vs 3258 on 8/9)
      and is source-faithful, hence correct under the owner's rule. MECHANISM (diagnosed, not a
      regression, identical in every Gold build since 09-15): 6 carries a different asset (`China
      Adjusted.png`, 3840x1080) from 5/8/9 (`pasted-image.pdf`, 3686x2752); 6 has no map/text so
      the recipe pairs by size with template slide 1's cover photo (`_recipe_source` ->
      template-cover, map_remap.py ~1511-1519), while the sibling-affine chain
      (`_recipe_reusing_affine`, `reusedSibling`, PR #74 continuity) is unreachable on an unpinned
      deck (`wanted is None` guard, map_remap.py ~3681). The different backdrop asset on 6 vs
      5/8/9 is irrelevant to the owner's criterion. FIX DIRECTION: make the sibling-affine reuse
      reachable for an unpinned slide whose only pairing is a cover-size photo (source
      `template-cover` by size coincidence) when the previous slide was template-layout framed:
      reuse `prev_affine` (report `reusedSibling: True`, `source: sibling-affine`), warn on any
      uncovered band. Slides 1/2 (legitimate template-cover with no layout-framed predecessor) and
      slide 7 (intentional magic-move framing for its 12 thumbnails, spanning 3561px of wall —
      context only, not a defect) must be unchanged. Options (b) full-bleed template slide and (c)
      source-placement fallback are now secondary/not required. VERIFY Keynote-free: unit test on
      the cached Gold payload asserting slide 6 image-0 affine == slide 5's (s, tx, ty),
      `reusedSibling` True on 6, and slides 1/2, 7, and 10-19 transforms byte-identical to the
      2026-09-16 fresh-gate record; golden plan re-baselined with intent; then one Gold live build
      for the owner's eye. Evidence: fresh-gate/gold/B_flagged.key + .run.json, gold.log decision
      rows, and `output/bank/2026-09-16/gold-6-7-series-diag.md` (note: that diag's coverage-based
      rejection was overruled by the owner's criterion above, and its slide-7 findings are
      context, not part of this bug's scope). DONE 2026-09-17 -> PR #150
      (`fix/gold-6-backdrop-series`): `_is_unpinned_photo_only_backdrop` gate makes sibling-affine
      reuse reachable for an unpinned photo-only cover-size slide after a template-layout sibling,
      and `_recipe_reusing_affine(clamp=False)` carries slide 5's affine onto slide 6 so the ~130px
      band is REPORTED (`uncoveredTopPx`), not closed by the cover-clamp. Slide 7 (12 thumbnails)
      and slides 1/2 (text) fail the predicate and are unchanged; a HEAD-vs-branch `golden_plan`
      capture confirms only slide 6 changed; golden re-baselined; suite green. Awaits owner merge +
      Codex.
    status: completed
  - id: residual-correctness
    content: >-
      Resolve the remaining card-border ref floor, stat-group/template sample, uncompared framing
      fallback, off-slide map-label deletion, and stat bind-name verification items independently.
    status: pending
  - id: cache-and-bank-hygiene
    content: >-
      Decouple durable evidence from inspect-version churn and retain small censuses/run records
      before deleting multi-gigabyte gate decks.
    status: pending
  - id: product-backlog
    content: >-
      Still-unstarted ideas: propose pins flag, portable recipe library, adjacent-slide stat drift,
      outline editor, image cues, and surgical IWA writes for the generator.
    status: pending
isProject: false
---

# CG resizer — active plan

## Current status

W1 is complete. `OBED_OFFLINE_WRITE` defaults to `on`; `off` restores the scripted AppleScript
geometry path. The 2026-09-14 Full RAISE10 strict gate was green, and Gold on/off outputs matched
by identity on all 19 slides. Do not reopen W1 from the older failed-bank narratives.

W2 replaces pass-2 GUI Bring-to-Front work with a surgical offline permutation of both
`drawablesZOrder` and `ownedDrawables`. Pieces 1–3 shipped in PR #127; the A/B gate shipped in
PR #126. Pass 2 no longer raises at all (W2 piece 1): eligible slides are patched offline after
pass 2 closes the deck, export on the later fallback open, then `restore_source_builds` runs
last. Unresolved targets stay on source stacking (`zorderGui`), not a GUI raise. `OBED_ZORDER_WRITE`
default flipped to `on` since 2026-09-15 (PR #133); `off` disables the offline z-order write —
there is no GUI/Accessibility fallback path left to restore.

### W2 evidence through PR #131

- Live gate run 1 passed the core writer bars: `FRONT_BLOCK_OK` 10/10, A/B same order 11/11,
  identity 100%, zero-pixel difference, and zero refused/lost slides.
- PR #128 made coincident sparkle-twin stat groups resolvable only under the planner's existing
  twin proof: every matching job is marked twin, candidate/job counts agree, and every candidate
  is pairwise coincident. It also narrowed the `badgeFallback` parity exemption to genuinely
  offline-patched badge slides.
- PR #131 is merged. Its 2026-09-15 update is retained: reuse-mode records store `statJobs` and
  `badgeRaises` at the record top level, so the gate now reads them through
  `persisted_raise_jobs`; and both W2 arms use the offline geometry tolerance because they differ
  only in `OBED_ZORDER_WRITE`, not geometry mode.
- Keynote-free recompare after PR #131: RAISE10 green with only expected warnings; Gold red only
  on slide 19's by-design legend fallback (`zorderUnresolved=66`, `zorderGui=[19]`). The final
  live gate ran 2026-09-15 — RAISE10 re-gate + A-vs-A control GREEN; final Gold re-compare at
  main 50cb592 (`output/bank/2026-09-15/w2-gate/gold-recompare-flip.log`): every geometry bar
  0.00px, FRONT_BLOCK_OK 16/16, identity 100%, RED only on slide 19's by-design legend fallback
  (`zorderUnresolved=66`, `zorderGui=[19]`), owner-deferred to follow-up
  `w2-ambiguous-sig-positional` and accepted as non-blocking. `OBED_ZORDER_WRITE` default flipped
  to `on` 2026-09-15 (PR #133).

## W2 final gate (run 2026-09-15, passed except Gold slide 19)

Run serially, on copies, with no already-open Keynote documents. Accessibility is no longer
required: pass 2 never raises on either arm.

Gate RAISE10 slides `40,55,56,109,110,123-128` and Gold, piece-2 contract: arm A is unraised
(pre-raise order, `zorderGui` everywhere), arm B is offline-patched. Require:

- `FRONT_BLOCK_OK` on arm B for every eligible slide and the expected `zorderGui` set only;
- zero A/B pixel difference on eligible slides;
- arm B `zorderRefused`, `zorderUnresolved`, and `zorderLost` all zero for eligible slides;
- A-vs-B `SAME_ORDER` is observational only (A is unraised, B is patched — expected to differ);
- an A-vs-A `SAME_ORDER=yes` control on RAISE10 (this one DOES gate);
- identical `restore_source_builds` behavior between arms.

Do not weaken eligibility to make the gate green. A slide that cannot prove a unique safe archive
order stays on the GUI path.

RUN 2026-09-16 19:22–19:53 at main 6bb4aeb (#141 resolver + #142 gate fixes), fresh two-arm Gold +
RAISE10, live verify on: identity 100% every slide; live verify PASS both arms (coverage 9→2
slides on Gold, 1→0 on RAISE10 — see todo live-verify-zorder-bridge); B counters
unresolved/refused/lost 0, zorderGui [] on both; Gold slide 19 raised (17 slides patched, 181 stat
targets); FRONT_BLOCK_OK 17/17 Gold, 11/11 RAISE10 under the arm-B-only bar
(fix/gate-front-block-b-only — arm A is unraised since #136, the gate had still required the block
in both arms). Bank: output/bank/2026-09-16/fresh-gate/. This is the live acceptance of the W2
deletions and the shared-signature resolver.

Gate rule: `FRONT_BLOCK_OK` is measured on arm B only; `SAME_ORDER` A-vs-B stays observational; an
A-vs-A control needs a second same-code A deck.

Live verify now covers every slide: the kindIndex bridge remaps z-order-patched slides and a
group multiset bar handles the one un-addressable bucket (todo id `live-verify-zorder-bridge`,
DONE 2026-09-17, PR #152 — live-accepted GREEN both arms, `output/bank/2026-09-17/live-verify-bridge/`).
Gate arms must share preview-cache provenance:
the banked 2026-09-15 Gold arms were planned WITHOUT the preview cache and are an invalid
baseline for slides 11/12 list placement — the 2026-09-16 build is the correct one.

2026-09-16 post-deletions gate outcome: RAISE10 deck geometry-identical to the 09-15 bank,
`FRONT_BLOCK_OK` 11/11; Gold identical except the roster rows. Both live-verify REDs are this
addressing gap (root cause B below), not the deletions.

## Active correctness backlog

### Constellation

The constellation is not one affine. Each CHC cluster should scale as a unit, then land on a
template anchor while preserving angular order around the central building. Discover membership
from connector-line incidence, not proximity. Pair clusters to anchors by angle; if counts differ,
fall back to an angle-preserving radial fit rather than guessing identities. Confirm with the owner
that yearly content churn justifies this automation before building it.

### Smaller residuals

- Card-border source-reference floor: output refs 10–31 on the Full wall still refuse in the
  residual case. Keep the source-ref census as a damage alarm.
- Stat-group/template sample and stat bind-name verification remain independent correctness work.
- Uncompared framing fallback must report rather than silently claim parity.
- Off-slide map-label deletion stays parked until a current output reproduces it.

## Retained design rules

### Placement and text

- Use one affine per role—map, badge, card grid, constellation cluster—not one per slide.
- The template supplies final geometry and text size; the source supplies font, colour, runs,
  builds, and authored copy.
- A template object supplies size, not pitch. Grid spacing needs two adjacent template examples.
- Text-bearing content is not a pin. A caption's inset is its own shape padding, not a subsystem
  constant.
- Never rewrite verse text to force reflow; doing so can destroy superscript, small caps, mixed
  runs, and authored line breaks.
- Autosize text is moved by visual top-left. Do not reintroduce stored-frame `±h/2` compensation.

### Offline read/write

- Whole-deck IWA decode/re-encode is unsafe. Patch only resolved owning members and preserve every
  untouched ZIP member byte-for-byte.
- Update stored size and `naturalSize` together where required; a zero text dimension is an
  autosize sentinel and must remain zero.
- Soft geometry classes seed from a live bulk read of the saved deck. Refuse a slide when counts
  or addressing do not reconcile.
- Compare groups as sets. Kind indexes change after reordering and are not stable identities.
- Z-order and build order are independent. `buildChunks` is the render timeline; `builds` is an
  owning set that Keynote may reorder. `restore_source_builds` remains last after W2.

### Gates and evidence

- Re-derive plans from the current planner before comparison; stale sidecars once manufactured a
  false 0.48× shrink diagnosis.
- A healthy baseline is a gate precondition. Counters must prove both arms completed the expected
  passes before their geometry or pixels are compared.
- Preview exports cannot prove build order; animation findings require build-chunk inspection or
  owner playback.
- Bank JSON censuses, run records, and logs before large `.key` outputs are removed.
- After planner/driver changes run `scripts/golden_plan.py`; after shared read-path changes run
  `scripts/e2e_run_parity.py` and keep the resizer gold-deck gate green.

## Product backlog

- Propose pins flag: expose pin-role uncertainty during framing rather than burying it in logs.
- Portable recipes: store role-specific affines in small tracked JSON, resolving each role on the
  current slide and fitting only orphaned roles.
- Stat drift: compare adjacent slides after removing digits and warn when a number disagrees with
  the run around it.
- Outline editor: surgical paragraph operations with timestamped backups; never flatten Word runs.
- Image cues: cue plus asset-slot count/shape, with background distinct from content media.
- Generator IWA writes: reuse only the proven surgical-member machinery and explicit gates.
