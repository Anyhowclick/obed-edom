---
name: Checker offline geometry v2 (drop the bulk pass)
overview: "v2 of the checker speedup (v1 shipped e86aaca: offline IWA + O(slides) bulk-geometry, ~3.25x). GOAL: compute autosize TEXT geometry OFFLINE (AppKit NSAttributedString shaping) so the 61s bulk Keynote pass can be dropped -> cold inspect ~= offline(0.8s)+export(32s) ~= 33s, ~9x. PEER-SCOPED + MEASURED (Keynote-free, 2026-08-29). Read the v1 plan (.cursor/plans/checker_offline_inspect.plan.md) + SKILL 'Reading a .key offline (IWA)' first. SEQUENCED to de-risk: build+calibrate the shaper (step 1, Keynote-free, low-regret) BEFORE committing to the group work."
todos:
  - id: shaper
    content: "STEP 1. Mode-aware offline text composer using AppKit NSAttributedString (installed; CoreText pyobjc is NOT — no new dep). Discriminator = TSD.GeometryArchive.flags (empirically: 0x1=fixed-width, 0x2=fixed-height; the current frame.h==0 test conflates flags 0 and 1). Per mode: flags=3 -> frame exact; flags=1 (fixed-W+auto-H, the DOMINANT case, ~91-97% of overflow-eligible boxes) -> w=naturalSize.w (EXACT offline), h=shaper.height(text, w=nw-2*inset), y=TOP (fix: current _autosize_rect wrongly uses y-h/2 for flags=1); flags=0 (auto-W+auto-H center) -> w=shaper.width(text), h=shaper.height, x=anchor-w/2, y=anchor-h/2. Extend iwa_runs.resolve_style to expose paragraph metrics (lineSpacing, paragraphSpacing/spaceBefore, firstLineIndent, tracking). Calibrate 3 constants ONCE: text inset (exteriorTextWrap.margin=12pt), line-height multiplier (per font family), paragraph spacing — raw boundingRect height is already median 0.989 of JXA. ORACLE: the cached JXA v3 GW payload already carries JXA's laid-out w/h (ground truth) -> calibrate + verify Keynote-free; PPTX only needed for DSK (no cache). Pending."
    status: pending
  - id: regroup
    content: "STEP 2. Recompute group frames as the child-UNION over the now-SHAPED text children (+ exact images). Measured residual with STALE text children (upper bound): GW 14/21 groups, Full 46/410 diverge >2px — but images 2/188 (GW) / 6/1548 (Full) and movies 0 are already offline-exact (residual = masked-rotated -> flag). The group residual IS the text residual one level up, so it should collapse once text is shaped. Re-measure after step 1. Pending."
    status: pending
  - id: group-source
    content: "STEP 3 (DATA-DRIVEN, decide after step 2). If the group residual collapses -> drop the Keynote geometry pass ENTIRELY (~9x). If not -> keep a SLIM group-only bulk pass (one kind, O(slides), still ~5-6x). Images/movies go fully offline now (tiny masked-rotated residual -> guard+fallback). Pending."
    status: pending
  - id: guard-version
    content: "Keep v1's granular fallback; add a `font-missing` guard (NSFont.fontWithName_ != nil — else metrics are a substitute font's, FALL BACK; TOP accuracy risk). PPTX content-hash-keyed steady-state fallback (autosize extent = pure fn of text+styles+width+fonts -> re-run only on hash change -> ~zero Keynote steady state), OR v1's scoped-JXA per-slide fallback (simpler). Bump INSPECT_VERSION 4->5. Pending."
    status: pending
  - id: verify
    content: "me + 1 peer verify: overflow-flag AND bounds-flag A/B vs JXA = 0 divergence (GW + DSK); per-box W/H parity <=2px on flags{1,3}, width vs oracle on flags=0; deck_slide_digests identical; end-to-end checker run == full-JXA. Pending."
    status: pending
isProject: false
---

# Checker offline geometry v2 — drop the bulk pass

Full peer draft + analysis probes: session scratchpad `checker_offline_geometry_v2.plan.md`
(+ `survey2.py`/`analyze2.py`/`ytest.py`/`calib.py`). This is the reviewed, sequenced version.

## What step-1 scoping established (the problem is smaller than v1 assumed)

- **`geometry.flags` is the autosize discriminator** (3-way, clean on GW's 99 boxes): flags=3
  fixed both (frame exact), flags=1 fixed-W+auto-H (**dominant**; width EXACT offline, only
  height missing), flags=0 auto-W+auto-H (width stale on 11/32). v1's `frame.h==0` conflates
  flags 0 and 1.
- **"Shuffled" was a myth** — plain stale (the box's own pre-relayout width; no join bug).
  True width-shaping ("B1") is only ~11 boxes on GW, ~2 on DSK.
- **~91-97% of overflow-eligible boxes are fixed-width+auto-height** — the EASY case (wrap at a
  known width -> height). So v2 is mostly a B2 (height) problem, not the B1 "wall" v1 feared.
- **AppKit `NSAttributedString` shapes it** (installed; no new dependency; custom fonts resolve),
  raw height median 0.989 of JXA before a 3-constant calibration.
- **Non-text geometry residual** (measured, pure-offline): images/movies offline-EXACT (GW
  2/188, Full 6/1548 — masked-rotated tail); groups diverge but only because their text children
  are stale — expected to collapse once text is shaped (step 2 re-measures).

## Ceiling & risk

~9x (306s -> ~33s) IF the group residual collapses; else ~5-6x with a slim group-only bulk.
Step 1 is Keynote-free and low-regret (calibrate against the cached JXA oracle). **Top risk:
font substitution** — a machine missing the deck's fonts silently mis-shapes; the `NSFont`
guard + fallback is load-bearing. The floor is the preview export (user-facing PNGs need Keynote).

## KNOWN BUG — FIXED (fd79e88)

DSK slide 17 rendered out of order (between 12 and 13) on a real run. ROOT CAUSE: slide 17's
lower-third photo is FLIPPED vs its LW counterpart; the offline read composes a masked image's
angle from frame+mask (357+357 → 354) where JXA reports 0, and `deck_slide_digests` — the
slide-IDENTITY key that decides PAIRING — included image `rotation`, so the flip churned slide
17's digest and floated it out of sequence. FIX: dropped `rotation` from the digest — orientation
must not drive pairing/order; a flip-vs-LW discrepancy is caught by the paired-image COMPARISON,
not the ordering key. Offline masked-image angle left as v1 composed it (signal preserved for the
comparison). Regression test: `test_deck_slide_digests_ignore_image_rotation`.
