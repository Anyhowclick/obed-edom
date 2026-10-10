---
name: CG resizer — active work and retained engineering record
overview: >-
  Consolidated 2026-09-15. W1 offline geometry is shipped and default-on. W2 offline z-order is
  default-on since 2026-09-15 (PR #133); text/mask-crop writes default-on since 2026-09-21. This
  file is the single resizer plan. Completed feature diaries live in git and the Obed-Edom skill,
  not here.
todos:
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

W1 offline geometry (`OBED_OFFLINE_WRITE`), W2 offline z-order (`OBED_ZORDER_WRITE`, PR #133) and the
autosize-text / masked-crop writes (`OBED_OFFLINE_TEXT`, `OBED_OFFLINE_MASKCROP`, 2026-09-21) are all
default-on; `off` is the kill switch for each. There is no GUI/Accessibility z-order path left: a slide
that cannot prove a unique safe archive order stays on source stacking (`zorderGui`). Gate evidence and
the text/mask acceptance bar live in SKILL.md; do not reopen W1/W2 from older bank narratives.

Closed todos (detail in git history, `git show 0f0a70aa:.agents/plans/cg_resizer.plan.md`):
`text-mask-default-flip` (2026-09-21), `w2-final-live-gate` (#133), `w2-deletions` (2026-09-16),
`w2-ambiguous-sig-positional` (2026-09-16), `live-verify-zorder-bridge` (#152),
`reuse-photo-placement` (slide reuse removed), `gold-6-backdrop-series` (#150).

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
- Live verify routes the AppleScript-fallback group buckets NOT-GATED per `(slide, kind)`; per-index
  dedup delete tokens that would gate them too (live-verify bridge "piece 3") remain unbuilt.
- MM shape identity (#228) open questions: the build-out exclusion rule is observed live only on FRC
  slide 147; one Action (blink) build on an MM slide still pairs; a partner row's `ambiguous` flag
  counts build-excluded objects (documented).

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
- A series keeps its source alignment (owner, 2026-09-16): an unpinned photo-only cover-size slide
  after a template-layout sibling reuses that sibling's affine; any uncovered band is reported
  (`uncoveredTopPx`), never closed by the cover clamp (PR #150, Gold slide 6).

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
- Z-order gate: `FRONT_BLOCK_OK` is measured on arm B only; A-vs-B `SAME_ORDER` is observational;
  an A-vs-A control needs a second same-code A deck. Never weaken eligibility to turn a gate green.
- Gate arms must share preview-cache provenance (an arm planned without the cache is an invalid
  baseline for list placement).
- A healthy baseline is a gate precondition. Counters must prove both arms completed the expected
  passes before their geometry or pixels are compared.
- Preview exports cannot prove build order; animation findings require build-chunk inspection or
  owner playback.
- Bank JSON censuses, run records, and logs before large `.key` outputs are removed.
- After planner/driver changes run `scripts/golden_plan.py`; after shared read-path changes run
  `scripts/e2e_run_parity.py` and keep the resizer gold-deck gate green.

## Product backlog

- Propose pins flag: expose pin-role uncertainty during framing rather than burying it in logs.
- Reviewed-auto framing decision (owner-banked 2026-09-22, option B; A shipped). Confirm in the
  framing review pins `autoTemplateSlide`, which does not reproduce the planner's own framing where
  it carried a sibling affine or fell back to fit-to-frame (Gold 13; Full 23, 32, 58, 75, 93 at
  2026-09-22 deck bytes). Option A disables Confirm and bulk-skips those pages. B adds a saved
  "reviewed, still automatic" decision that emits no override: a new state or `reviewed` flag in
  `framing.STATES`/`Decision`, `normalize_decision`, `save_framings` (today drops `auto` rows),
  `reuse_framings`, `FramingReuse.overrides` and the app's `_overrides_from_result` (must stay
  pin-only), and the review's Reviewed category. Caveat: an older build silently drops the new
  state on load (`normalize_decision` refuses unknown states), so the page falls back to
  unreviewed-auto there. Saved pins keep meaning "pin".
- Portable recipes: store role-specific affines in small tracked JSON, resolving each role on the
  current slide and fitting only orphaned roles.
- Stat drift: compare adjacent slides after removing digits and warn when a number disagrees with
  the run around it.
- Outline editor: surgical paragraph operations with timestamped backups; never flatten Word runs.
- Image cues: cue plus asset-slot count/shape, with background distinct from content media.
- Generator IWA writes: reuse only the proven surgical-member machinery and explicit gates.
