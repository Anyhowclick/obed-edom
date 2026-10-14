# Review edge fix r2 (Opus 5.5 high), 2026-10-14 — ready for a live run; 0 blocker/major/medium

All r1 findings fixed (B1 nooffset-x at -80: one holder [301,795,571,268] spliced; nooffset-y at -80: one holder [109,27,952,161];
dropped offset gives an attributable pixel FAIL, correct holder MISMATCH; M1, L3, L4, L5). Node per-arm holders on the recorded
geometry: base [109,795,952,268] with 3 repairs; far-x/far-y/near-x/near-y as expected; DSK 2 holders; underlay-omit passes the
containment guard and is refused by the alpha scan (analysis). Tests: 170; 503 + 1 skipped.
Lows (to fold): (1) L5 overlap census misses movie-group siblings (F6F0, 3231) and slide-level canvases; 3F22 [789,673,353,313]
α.29 overlaps the x holder harmlessly (redrawn + masked) — reword or widen. (2) no offline end-to-end x outcome test; parametrize
nooffset_y_outcomes by axis; roll all four channels. (3) pre-existing: frac quad rounds the letterbox offset (Math.round(cy-r.top));
DSK 43-video drawn at fy=0 with content top 889.599; no arm checks frac pixels with a fractional letterbox offset — note in §11.5 or
add later. (4) r1 L1/M2 residuals stand.
