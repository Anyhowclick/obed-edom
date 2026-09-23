---
name: Offline text — grow-height regrow width write (OBED_OFFLINE_TEXT_REGROW)
overview: >-
  2026-09-23. Offline width write for `text-grow-height-width` (88/234 fallback specs on the
  2026-09-23 full-deck run, the largest remaining family). Grow-height = stored w > 0, stored h == 0;
  pass 1 leaves w at 0.25x so the writer misses it (`iwa_write.py:714-721`, PR #169). Prior negative
  result c70540de3 (2026-09-05, "Keynote re-shrink-wraps on open") is CONFOUNDED: that write also used
  an absolute pos_x, wrote size_w onto grow-BOTH w==0 boxes, and went through the fixed-frame
  `_text_fields`; its "width discarded" claim was never isolated, and position-only writes on nh==0
  boxes have since been live-validated (`iwa_write.py:700-709`, 136/136). Whether a written WIDTH
  survives open is the core unknown; the subset gate is the probe that settles it before promotion.
  Two Opus planner passes (extra-high draft, high critique) produced this text. Default OFF. Does
  not remove the fallback session (groups 83 live-bound, masked-media 57 open); shrinks its body.
todos:
  - id: m0-offline-census
    content: >-
      MEASURE, no Keynote. Scratch script under `.agents/reviews/regrow-2026-09-23/` over the
      existing post-fallback deck `output/groups-measure/Full_Report_Card_CG.key`: for every text box
      with stored w > 0, tabulate h (0 vs > 0 — answers whether the fallback's `height:spec.h` write,
      `remap_keynote.py:578-588`, turned grow-height boxes into fixed-height, which would make arm A
      and arm B different box types), `geometry_flags` (`iwa_text_shape.py:32`, width-fixed bit 0x1),
      `_vertical_alignment` incl. None (`iwa_geometry.py:198-205`), paragraph alignment, `_path_source`
      key, rotation. Output `m0.md`.
      DONE 2026-09-23 (`.agents/reviews/regrow-2026-09-23/m0.md`): CG deck 102 h==0 boxes (wall 123), all
      width-fixed (flags 1), none rotated, all bezierPathSource, NO None vertical alignment. The fallback
      did NOT change box type (h==0 before and after) so A and B are the same kind. 14 boxes are nw>0/nh==0
      post-fallback (the half-filled cache DOES occur today; K5 must tolerate it). Anchor mix: 91 MIDDLE +
      centre-aligned, 11 top (5 right, 4 left, 2 centre). Slides 96/103 are 6/7 and 15/16 middle+centre
      single-line 'CHC …' labels. => a top-only v1 converts ≤11 and trips the m1 kill; the middle-anchor
      write (v2-middle) is the real work and m1 must be designed to decide it.
    status: completed
  - id: m1-live-measure
    content: >-
      MEASURE, OWNER-GATED (Keynote). One default full-deck run (`--slides 1-129,135-143,145-155`) with
      `OBED_DEBUG_PASS1_SNAPSHOT=<path>` (`remap_keynote.py:214-225`) and a throwaway, never-committed
      dump hook in the grow-height branch (`iwa_write.py:718-721`, same pattern as the reverted
      `OBED_DUMP_SPECS` hook): slide, obj id, spec (role, x, y, w, h, fontSize), stored xywha, rep,
      nw/nh, flags, vertical + paragraph alignment, path key, text length; plus monotonic time around
      `_run_fallback_scripts` (`offline_write.py:~1105`). Derive offline: (1) EFFECTIVE vertical anchor
      per box from stored[1]−rep[1] vs 0 / rep[3]/2 / rep[3] — do not trust a None style
      (`_autosize_rect` treats None as centre, `iwa_geometry.py:208-218`, but Keynote's real default is
      unconfirmed); (2) b_h = (stored[0]−rep[0])/rep[2] by paragraph alignment × width-fixed bit
      (`_autosize_rect` reads stored x as the left edge; the oracle's `autosize_left`,
      `scripts/text_mask_visual_oracle.py:177-182`, reads it as a centre/right anchor — conflict);
      (3) stored[2] vs rep[2]; (4) how many of the 88 sit on slides whose ONLY fallback family is
      grow-height (slide 103 = 16 can leave; slide 96 cannot, masked-media 1); (5) fallback seconds
      and session count (`build_fallback_scripts`, 300 KB chunking). After m0 the kill is REFRAMED:
      top-only v1 is expected to fail its bar, so m1 must ALSO capture what decides v2-middle: spec.h
      and role per box, the recipe provenance (affine `other` vs slot/translated), fontSize, the SOURCE
      wall box h/nh (join by slide+kindIndex against the wall census), and rep[3] (narrow-wrap height).
      Decide offline whether h_new is predictable for the 91 single-line middle labels (candidate:
      spec.h when the recipe is the wrap-preserving affine, since font and width scale together).
      KILL: if h_new is not predictable for ≥ ~60 of the 88, stop and record.
    status: pending
  - id: impl-writer
    content: >-
      STREAM A (`src/obed_edom/iwa_write.py`, `src/obed_edom/iwa_geometry.py` docstring only,
      `tests/test_iwa_write.py`). Add `text_regrow: bool = False` to `_slide_edits` (:576) and
      `patch_deck_geometry` (:942, threaded at :975). In the grow-height branch, when on, refuse in
      order: `_is_rotated(stored[4])` → "text-regrow-rotated"; `not _natural_writable(obj,
      both_axes=False)` (:112-133; an editableBezier source would otherwise make `_write_natural_size`
      :524-555 silently skip) → "text-regrow-unwritable"; anchor not top per the m1(1) rule
      (kFrameAlignTop, plus None only if m1 shows None boxes behave as top) → "text-regrow-anchor";
      a paragraph-alignment class m1 left unresolved → "text-regrow-halign". Refusals miss with their
      own reason so the fallback histogram (`offline_write.py:189-223`) shows each class; with the
      flag off the miss stays "text-grow-height-width" byte-identical. Otherwise
      `_text_fields(..., position_only=True, regrow=True)` (:279-322) adds
      size_w = stored[2] + (spec.w − rep[2]), natural_w = size_w, and
      pos_x += b_h·(size_w − stored[2]) only for classes where m1 found b_h ≠ 0. NEVER size_h /
      natural_h. No `used_reported` change: the branch is seed-gated (:710-712) so it can never raise
      `soft_fallbacks`. Fix the stale `_drawable_natural_issues` docstring (`iwa_geometry.py:450-454`,
      claims the writer refuses nh==0 boxes outright; already false for position-only).
    status: pending
  - id: impl-plumbing
    content: >-
      STREAM B (`src/obed_edom/remap_keynote.py`, `src/obed_edom/offline_write.py`,
      `tests/test_offline_write.py`). `offline_text_regrow_enabled(explicit=None, *, offline_mode=None,
      text_reposition=True, say=None)` after `offline_maskcrop_enabled` (`remap_keynote.py:~191`),
      same token shape but DEFAULT OFF ("" → False; unknown → say + False); forced off with a say when
      offline mode is off or text reposition is off (the regrow lives inside that branch). Call it
      beside the other flag reads (~:1521) and thread `text_regrow` run_offline_write →
      `_patch_offline_slides` → `patch_deck_geometry`. Add "fallbackSeconds" (monotonic around
      `_run_fallback_scripts`) to the result dict (:1167-1197) — the first real wall-time number for
      the fallback session.
    status: pending
  - id: impl-gate
    content: >-
      STREAM C (`scripts/offline_write_ab.py`, `scripts/text_mask_visual_oracle.py`, their tests).
      Add OBED_OFFLINE_TEXT_REGROW to `_ARM_ENV_KEYS` (:166-177) and pin it "off" in BOTH existing
      axes (:235-246). New axis "text-regrow": A = current defaults, B = A + REGROW on; `--mode
      verify`; allow `--slides`; `feature_scope_reasons` (:285-295) requires whole-deck for promotion
      on this axis too. Regrow verdict row: for each spec A missed as text-grow-height-width
      (`fallbackReasonsBySlide`), B's live w vs spec.w (≤0.5 px), x/top vs spec (≤1 px) — the direct
      "width discarded" detector `verify_live_frames` cannot see (text x/y only,
      `offline_write.py:684-690`) — plus a post-save re-decode: stored w kept, nh refilled or unchanged (14 boxes are
      already nw>0/nh==0 after today's fallback per m0, so nh==0 alone is not a failure). Oracle `autosize_left` (:177): width-fixed
      boxes use the m1-measured b_h rule. Note `offline_write_ab.py:232` pins
      OBED_DEBUG_PASS1_SNAPSHOT to "" — the wrap control snapshot comes from the m1 run.
    status: pending
  - id: live-gate
    content: >-
      OWNER-GATED. (1) SUBSET = the probe: slides 103, 96 + m1-chosen centre-aligned, right-aligned
      and one refused-class slide. Wrap POSITIVE control: the oracle must FAIL the m1 pass-1 snapshot
      export of the same slides (0.25x wrap); NULL: existing A-vs-A-null export; flag-off B must
      reproduce A's `fallbackReasons` exactly. (2) WHOLE DECK, same axis — the promotion evidence.
      Kill, per class (effective anchor × paragraph alignment × path-source × role):
      K1 any regrown |live w − spec.w| > 0.5 → close the plan (c70540de3 reproduced);
      K2 top |dy| > 1 → kill class; K3 |dx| > 1 → kill that paragraph class; K4 oracle label fail
      (controlled pass false or translation > 8 px) → kill class; K5 `naturalConsistencyIssues` > 0
      or nh not refilled after save → kill; K6 B's (grow-height + regrow-*) misses ≠ A's grow-height
      count → kill; K7 `fallbackUnwritable`/`softFallbacks` rise → kill. Any kill ships nothing;
      refused classes stay on AppleScript by construction. Promote (default ON) only after (2).
    status: pending
  - id: v2-middle
    content: >-
      AFTER m0: LIKELY THE MAIN WORK (91 of 102 grow-height boxes are middle-anchored); decide on m1. Middle/bottom anchors need the NEW laid-out height (pos_y = spec.y + a·h_new); the
      delta form is off by a·(rep_h − h_new) where rep_h is the narrow-wrap height. spec.h is NOT a
      safe h_new: role "other" also covers body text (`map_remap.py:2602`), corner-translated text
      (:2534), demoted list (:2554-2555); style-matched boxes use src.h·ratio clamped ≥8 (:2117-2118)
      — so the earlier "restrict to role other" idea (offline_text_middle_anchor.plan
      impl-four-diff-bugs(3)) is unsound. Candidates if m1(1) shows a large share: a planner-emitted
      wrap-preserving provenance bit, or `iwa_text_shape.shaped_height` (:262-266) under its own gate.
    status: pending
---

# Offline text — grow-height regrow width write

## 1. The write (flag on, all gates pass)

Scope: text, stored w > 0, stored h == 0, `seed_ok` (`iwa_write.py:710`), |spec.w − rep.w| >
`_TEXT_WIDTH_KEEP_PX`.

| field | value |
|---|---|
| size_w | stored.w + (spec.w − rep.w) |
| natural_w | size_w (keeps `text-natural-width`, `iwa_geometry.py:465-467`, green) |
| pos_x | stored.x + (spec.x − rep.x) [+ b_h·(size_w − stored.w) per m1] |
| pos_y | stored.y + (spec.y − rep.y), exact for a top anchor whatever the new height |
| size_h, natural_h | never written; the sentinel stays 0 |

Refusals: text-regrow-rotated, -unwritable, -anchor, -halign. Flag off: unchanged miss. The target
matches the fallback's result: width first, then visual top-left (`remap_keynote.py:578-594`).

## 2. Failure modes → detector

| failure | detector |
|---|---|
| Keynote discards / re-derives the written width on open | K1 + post-save re-decode |
| Stored x is a paragraph anchor for centre/right width-fixed boxes | m1(2), K3, flags-aware oracle |
| Wrong effective anchor (None style) | m1(1), K2 |
| Half-filled layout cache (nw set, nh 0) not refilled | K5 |
| Fallback's height write changed A's box type so A ≠ B | m0 |
| Wrong wrap at a correct position | oracle + snapshot positive control |
| Lost / duplicated specs | K6, K7 |

## 3. Unknowns (measure, never assume)

U1 width honoured on open (subset gate). U2 b_h per class (m1). U3 effective anchor incl. None
(m1). U4 fallback box type (m0). U5 fallback seconds and which slides actually leave the session
(m1). U6 scalar path source under a natural_w-only write (`_scale_rect_scalar` scales only when
rx≈ry, :517-519 — add a test).

## 4. Tests

`tests/test_iwa_write.py` (reuse `_grow_height_text_objects` :1878): flag off unchanged
(:1891-1901); flag on top → {pos_x, pos_y, size_w, natural_w}, no size_h/natural_h; one test per
refusal (middle, None-per-rule, bottom, rotated, editable source via `_shape_super(kind="editable")`);
scalar source natural_w-only write leaves the scalar alone; ≤0.5 px still position-only (:1921);
grow-both untouched (:1935). `tests/test_offline_write.py`: flag parse / default off / forced off;
threading reaches `patch_deck_geometry`; `fallbackSeconds` present. Script tests: new axis configs,
REGROW pinned off on the old axes, whole-deck rule, regrow row, `autosize_left`.

## 5. Expected reduction

At most the effective-top share of 88 minus refusals. A slide leaves the fallback only when ALL its
misses convert. The session survives (groups, masked-media); report `fallbackSeconds` A vs B and
claim no wall-time lever until measured.

## 6. Streams and order

A: writer. B: plumbing. C: gate scripts. Contract: `text_regrow` kwarg + the miss-reason strings.
Order: m0 → m1 → A ∥ B ∥ C → subset gate → whole-deck gate → promote.
