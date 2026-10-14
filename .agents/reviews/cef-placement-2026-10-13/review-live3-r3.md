# Review live3 r3 — W6 fold 2 (Opus 5.5 high), 2026-10-14

Verdict: not ready (2 blockers, 1 medium, 3 low). Targeted 311 passed.

- BL1 blocker: nooffset-y manufactured FAIL — `dissolve_probe.py:3494-3497` overwrites holder_pixels with FAIL whenever the
  "integer-phase backing" attribution PASSes; that branch is geometry-only and compares A0 vs S_live at {0,1}, so a correct holder
  also passes → arm MATCHes for a correct product. Reproduced on nooffx.npz pixels. Test `:1068-1100`, `:1506` locks it in. Fix:
  delete the override; attribution only gates (non-PASS → INCONCLUSIVE); then (a) harness-only slide override moving the near-y
  video so y-displacement < content height, or (b) nooffset-y REPORTED. Add row: correct holder on backing geometry must not FAIL.
- BL2 blocker: DSK seek offsets inert — `_dsk_counter` writes movie.startTime/endTime the player never reads (src + play(), trims
  baked); both decoders show the same frame ±1 → distinct check INCONCLUSIVE live. Offline test models media+5.0. Fix: real 5 s
  start (e.g. `#t=5` media fragment on the second clip URL in the in-memory doc) + fail-closed install check that rVFC mediaTimes
  differ ≈5 s.
- M1 medium: `movies="dsk-counter"` serves non-alias movies unmodified; cef-skip-dsk transcoded them to h264; slide 8 Untitled.mov
  are HEVC → CEF may fail. Route non-alias movies through `h264_copy`.
- L1: cost gate is take time; counter 1920×540 H.264 vs replaced 1922×1080/1282×1080 → cost PASS easier; add to representativeness
  note. L2: underlay-omit inherits edgefg — mention. L3: ARMS diff vs HEAD all intended.
- Verified: B2 bracket discriminates (correct holder → worst 245 FAIL); edgefg geometry on real p2bin (crossing ≈10 device px,
  foreground ≥53 px clear of strip); counter decodes at DSK scales; L3 preconditions; sha pin + slide scoping.

Owner 2026-10-14: rounds r4 and r5 of this live3 review also fold mediums (lows not folded from r4); from r6 only major/blocker.
