---
name: Map church labels — scale the PILL with the label's font ratio
overview: >-
  2026-09-19. On a map slide an unpaired church label ("CHC Yangon", Amplitude-Bold) is
  re-sized by `_style_text_box` to `src_size * r` where `r = dst_font / wall_font`, but the red
  rounded-rect PILL under it is an ordinary shape that only rides the map affine. Where r > 1
  the text overflows the pill. Measured on the Gold wall deck: slides 5/8 (Malaysia, 40->40)
  and 17/18 (China, 35->35) have r == 1 and are already correct; slide 13 (Myanmar, 15->25,
  r = 1.6667) has 19/19 labels escaping their pill. Fix: scale each paired pill by the same r
  and re-place the label relative to the grown pill with its original padding scaled by r.
  22px * 1.6667 = 36.7 ~ the template's 36px Myanmar pill, so the template's proportions fall
  out without reading the template pill. r == 1 must be a bit-for-bit no-op.
  MEASUREMENT OVERRULES THE ORIGINAL DIRECTION: the owner asked for growth anchored away from
  the label's map dot. Measured on slide 13, away-from-dot is WORSE than plain centre growth on
  every metric (pill-pill overlaps 19 vs 16, pill-dot 48 vs 40, label-label 20 vs 13 -- and
  today's label-label baseline is 13, so centre growth costs nothing while away-from-dot
  regresses readability). Recommendation: ship CENTRE growth on both axes; keep the dot
  association code out of the increment entirely. Census + scripts:
  `.agents/reviews/pill-census-2026-09-19/`.
todos:
  - id: decide-anchor
    content: >-
      OWNER DECISION, blocking. Present the slide-13 numbers (pill-pill 0 today / 16 centre /
      19 away-dot; pill-dot 2 / 40 / 48; label-label 13 today / 13 centre / 20 away-dot;
      labels escaping their pill 19 today / 0 both grown modes; cluster x-extent 460 -> 537px,
      frame 1920px, nothing clipped) and get a yes to CENTRE-on-both-axes growth. If the owner
      still wants away-from-dot, the dot rule is measured and ready (see `dot-association`
      below) but the increment then ships a measurable readability regression and needs a
      collision pass that this plan explicitly does not design.
    status: pending
  - id: pairing-rule
    content: >-
      Add `label_pill_pair(label, shapes)` to `map_remap.py`. Candidate shape P pairs with
      label L iff: P.x <= L.x + 4 and P.x + P.w >= L.x + L.w - 4 (x-containment, 4px tol);
      P.y - 0.25*L.h <= L.centre_y <= P.y + P.h + 0.25*L.h; 0.6*L.h <= P.h <= 3.0*L.h; and P is
      not a dot (shape with w,h <= 1.6*L.h and |w-h| <= 2). Return the pill only when exactly
      one candidate survives. Gate the whole feature on the label being a single-line
      Amplitude-Bold text box -- measured, that is exactly the 45 real map labels and it
      excludes the 374 Amplitude-Regular roster lines on slides 20-22 and slide 13's 2-line
      Amplitude-Medium "CHC Yangon / Bible School" photo plate (pill/label area 1.77, would
      otherwise mis-pair). DO NOT use z-order or fill colour: the inspect payload's `index` is
      kind-bucketed, not z-order (`iwa_kindindex.derive_kind_index`), and `color` on a shape is
      its TEXT colour, not its fill -- every pill reports white, every dot black. Measured
      result of this rule on Gold slides 5/8/13/17/18: 45/45 labels pair uniquely, 0 misses,
      0 ambiguities. Rect containment alone misses slide-18 "CHC Jiang Shou" (238x46 label in a
      253x41 pill), which is why the vertical test is a centre-in-band test.
    status: pending
  - id: anchor-maths
    content: >-
      In `plan_slide_transforms`, work in DST space. Pd = aff.apply_rect(pill_src);
      Ld = the rect `_style_text_box` already computes for the label (origin
      aff.apply_rect(Rect(lx,ly,1,1)), size src.w*r x src.h*r). Then, with r = dst_font/wall_font:
      SHORT-CIRCUIT `if r == 1.0: leave both transforms exactly as today` -- this is what makes
      Malaysia/China bit-for-bit identical, and it must be an exact float compare on the same r
      `_style_text_box` used, not an epsilon.
      Otherwise: pw' = Pd.w * r, ph' = Pd.h * r;
      px' = Pd.x + (Pd.w - pw')/2, py' = Pd.y + (Pd.h - ph')/2 (CENTRE, both axes);
      padL = Ld.x - Pd.x, padT = Ld.y - Pd.y (dst-space, already carries the affine scale;
      MAY BE NEGATIVE -- measured vertical pads run -3..+2px -- so never clamp to 0);
      lx' = px' + padL * r, ly' = py' + padT * r, size unchanged at Ld.w x Ld.h.
      Algebraically at r == 1 this yields px'=Pd.x, lx'=Ld.x, so the short-circuit and the
      formula agree; the short-circuit exists to guarantee bit-identity through the float ops.
      Relative padding is preserved by construction (every gap scales by r), so (a) holds
      wherever it held at r == 1 -- including the slide-18 case where the label is taller than
      its pill.
      If `decide-anchor` returns away-from-dot instead: replace px' only --
      dot left of the pill => px' = Pd.x + Pd.w - pw'; dot right => px' = Pd.x;
      dot inside the pill's x-range (10 of 41 measured) or no dot within R => centre.
      Keep py' centred regardless: 14 of 41 dots sit inside the pill's y-band, so a vertical
      anchor is undecidable for a third of the population.
    status: pending
  - id: dot-association
    content: >-
      ONLY IF `decide-anchor` chooses away-from-dot. Dot = shape with w,h <= 1.6*label_h and
      |w-h| <= 2 (measured: 25x25 rot 0 on the Malaysia/China maps, 17x17 rot 242 on Myanmar,
      11x11 on the roster maps; colour is NOT usable). Distance = dot centre to the PILL RECT,
      not centre-to-centre (pills are wide; centre distance mis-ranks a dot hugging one end).
      Radius R = 2.5 * pill_h + 30 (85px at 15pt, ~145px at 35pt; measured maxima 23.5 and
      123.2, and it correctly rejects the 2182px no-dot case). Nearest wins; tie-break on lower
      `kindIndex`. 1 of 45 pairs has no dot in radius; 3 dots are claimed by two pairs, which is
      harmless (the dot is read, never moved). Note `is_pin_item` already classifies these
      shapes as pins for the report tally -- reuse its size constants rather than minting new ones.
    status: pending
  - id: write-path
    content: >-
      No new writer code expected. A pill is a rounded rect => `scalarPathSource`, which is in
      `iwa_write._NATURAL_PLAIN_KINDS`, so `_natural_unwritable` does NOT refuse a w+h resize.
      `_shape_fields` writes size_w/size_h and natural_w/natural_h; `_write_natural_size` ->
      `_scale_rect_scalar` multiplies the corner-radius `scalar` by rx when the resize is
      UNIFORM (|rx-ry| <= 1e-3*max) -- ours is exactly (r, r), so the corner radius scales with
      the pill offline, which is what reproduces the template look. Confirm on the real deck
      that slide-13 pills really are `scalarPathSource` (a `callout`/`connectionLine`/
      path-source-less shape would refuse and fall back to AppleScript; acceptable, just report
      it). LIVE DIVERGENCE TO FLAG: Keynote cannot script corner radius -- the repo already
      relies on this (`corner_translate` in `plan_slide_transforms` exists because "a resize
      squares the plate"). The AppleScript arm will therefore draw a 1.667x pill with the OLD
      radius. Decide whether that is acceptable for the fallback path or whether the fallback
      should skip the pill resize (translate-only) and leave the pill unscaled.
    status: pending
  - id: feature-interactions
    content: >-
      Audit and add regression coverage for: `overlay_ids`/body text (its own ratio branch
      overrides `mapped` AFTER `_style_text_box`; a pill-paired label must never be an overlay
      -- assert disjoint); the list-packing path (`_pack_list_transforms` moves role=="list"
      transforms and would tear a label off its pill -- the pairing must only fire on
      role=="other", and slides 20-22's roster text is already excluded by the Amplitude-Bold
      gate); `corner_translate` badge plates (their members are `continue`d before the
      text branch, so untouched -- assert the pill is never a `corner_ids` member);
      hidden/duplicate items (a hidden or off-canvas label must not resize its pill --
      `is_visible` gate first; a shape that is `duplicateOf` a text record must never be a pill
      candidate); `keep_side_panels` (side-panel items are hidden before the branch); stat
      groups on slides 23-26 (no Amplitude-Bold labels, excluded). Golden plan
      (`tests/test_golden_plan.py`, decks Gold_Wall_Input.key + Full_Report_Card_Wall.key):
      the Gold golden CHANGES on slide 13 only (19 pill transforms gain w/h/x/y, 19 label
      transforms change x/y) and must be regenerated deliberately with the diff inspected
      slide-by-slide; slides 5/8/17/18 must show a ZERO diff, and that zero diff is the
      strongest automated no-op proof available. Re-measure Full_Report_Card_Wall for
      Amplitude-Bold labels with r != 1 before regenerating its golden.
    status: pending
  - id: unit-tests
    content: >-
      In `tests/test_map_remap.py`: (1) pairing -- unique pair, the slide-18 short-pill case,
      a dot rejected as a pill candidate, a 2-line/Amplitude-Regular label rejected, a
      >1-candidate case returning None; (2) anchor maths -- r == 1 returns byte-identical
      ItemTransform fields to the current planner (compare the full dataclass), r == 1.6667
      centres the growth and keeps padL/padT ratios, a NEGATIVE vertical pad survives;
      (3) an end-to-end `plan_slide_transforms` test on a synthetic slide reproducing the
      Myanmar geometry, asserting the label rect is inside the pill rect afterwards and was not
      before; (4) a no-op test on synthetic Malaysia geometry asserting the transform list is
      equal to the pre-change one. Also a property test: for any r, label-inside-pill is
      preserved iff it held at r == 1.
    status: pending
  - id: live-gate
    content: >-
      Gold deck, slides 13 (treatment) + 5 and 18 (r == 1 no-op controls), one convert run,
      A/B against the current arm-A output ~/Desktop/ab_pills_A_CG.key.
      PASS requires all four: (a) controls 5 and 18 are transform-identical to arm A (golden
      diff empty) AND their rendered previews are pixel-identical; (b) on slide 13, a preview
      pixel check shows every one of the 19 white glyph runs fully inside its red pill body --
      no white pixel of a label within 1px of the pill's outer edge; (c) the pill corner radius
      is visibly round, not squared (the AppleScript-radius risk); (d) no pill leaves the
      1920x1080 frame (predicted x-extent 537px, so this is a smoke check).
      KILL on any of: a control diff, a label still clipping its pill, a squared pill, or a
      pill-pill overlap that hides a label's text entirely (predicted 16 overlapping pill pairs
      at centre growth -- overlap alone is NOT a kill, the pills already sit in tight stacks
      and today's labels overlap 13 times; the kill bar is TEXT made unreadable).
      Oracle: the AppleScript-rendered CG for slide 13 plus the template base slide 4
      (text 133x34@25 in pill 138x36) as the proportion reference.
    status: pending
  - id: flag-decision
    content: >-
      RECOMMENDATION: default-ON, no env flag. Rationale -- r == 1 is a hard short-circuit, so
      every deck and every slide measured except Myanmar is provably untouched, and the golden
      plan proves it automatically on two decks; the repo's flag pattern
      (OBED_OFFLINE_MASKCROP / _OFFSET) exists for OFFLINE WRITE behaviour whose Keynote-side
      redistribution was unproven, which is not the situation here (this is a planner-geometry
      change on an already-supported write path). The one genuinely unproven bit is the
      corner-radius behaviour on the AppleScript fallback arm; if `write-path` finds that arm
      squares the pill, gate only the FALLBACK's pill resize (skip it, leave the pill at affine
      size), not the whole feature.
    status: pending
---

# Map church labels — scale the PILL with the label's font ratio

Actionable record in the todos above. Measurement first: the pairing rule, the dot rule and
the collision counts were all measured on the Gold wall deck before any code was proposed,
and the measurement reversed the anchoring decision. The census, the numbers and the
reproducible scripts are in `.agents/reviews/pill-census-2026-09-19/`.
