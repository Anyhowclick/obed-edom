---
name: CG resizer — active work and retained engineering record
overview: >-
  Consolidated 2026-09-15. W1 offline geometry is shipped and default-on. W2 offline z-order is
  implemented and default-on since 2026-09-15 (PR #133). This file is the single resizer plan;
  the standalone W2 plan was folded into it. Completed feature diaries live in git and the
  Obed-Edom skill, not here.
todos:
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
      Resolve shared, non-twin signatures positionally (groupIndex-1) with a signature verify and
      no two jobs on one id, mirroring the GUI's `obedResolveGroup` path (Gold slide 19 legend,
      66 jobs). Now the ONLY path to a raised Gold slide 19: the GUI raise fallback is gone
      (w2-deletions piece 1), so an unresolved shared signature stays on `zorderGui` (WARNING,
      stack by hand) until this lands.
    status: pending
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

The owner-run live gate after the w2-deletions PR is one default-env build of RAISE10
(`40,55,56,109,110,123-128`) + Gold, re-compared Keynote-free against the banked 2026-09-15
`B_flagged` arms via `--reuse-a`/`--reuse-b` (v2 records load). Bars: identity 100%,
`FRONT_BLOCK_OK` all eligible, 0.00px, `zorderGui=[19]` on Gold / `[]` on RAISE10,
`restore_source_builds` identical.

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
