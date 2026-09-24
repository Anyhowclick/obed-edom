# OD-2 Opus review r1 (reviewer replaces Codex, owner 2026-09-24) — at `cade59fc`, UNFOLDED

Product diff sound (§7 brief 1–5, 8 yes; G2/core JS diff empty; 301 unit tests pass). Harness findings to fold on resume:

1. MAJOR, new class (product, ungated): build-1 hand-back jumps the carried movie FORWARD 9–13 frames (~0.3–0.43 s) in almost
   every good take, rates 25 and 30 (e.g. g2-230406 hand-back counters 60,61,62,73); native phases never jump > 3–4. M2 gates only
   backward steps. Proposed: gate max forward step ≤ 3 (would FAIL today → owner call); owner to watch build 1 in M7; compare the
   carried `currentTime` at liveEnd vs the decoded counter (does G2 lag ~10 frames?).
2. MAJOR harness: hand-back falls inside the decoder's 2-frame edge trim (marker + advance same instant; build1AfterMarkerS 0.0) —
   fix: hold ~0.5 s after the marker before advance; assert ringDiag.worstSinceFirstS ≥ 0.2.
3. MAJOR harness: hidden-arm session uses the product default ⇒ at rate 30 (default now off) it fails for the wrong reason — pass
   the g2 session's gl_replay; failsafe/soak arms refuse rate ≠ 25.
4. MAJOR post-hoc: M2 redesigned around the single oldbytes take (not caught under the original criteria); oldbytes not re-run on
   the final harness; oldbytes is a LIVE-draw defect, not a hand-back one ⇒ no hand-back-targeted KB; g2-off 2596 is not a null
   (native would FAIL ≤ 200). Fix: re-run oldbytes on HEAD; add a hand-back-only KB (e.g. skip G2 canvas removal at handoff);
   document how 200 was chosen.
5. minor post-hoc: pre-registered reshow ≤ 0.03 failed 4/~18 takes before the relative switch; relative bound admits up to native
   10–13 %. Record the count; consider ≤ 0.5× native or ≤ 0.06.
6. minor: frozen KB moved to the static check ⇒ M1 cadence bound has no readable-but-worse KB; say so.
7. minor vacuous: M0 "1-px poke caught" compares a copy to its source (always 255) — rename or compare to g2-off-S; M1
   preference check can't fail at 30.
8. minor: soak kb_verdict passes vacuously on the non-looping fixture (require fixtureLooping); fail-bogus KB satisfied by any
   failing check (target the zone-reason check); fail-zone fallback can't tell zone from module.
9. minor: lossless guard checks codec only; utvideo/yuv420p is 4:2:0 — allowlist (codec, pix_fmt), fix "lossless" wording.
10. minor: over20.count measured on the max-single-pixel frame, not the max-count frame.
11. minor: cross-take controls (M0 H vs H, M3 τ_O) only with --takes ≥ 2 in one call; final takes ran --takes 1.
12. nits: loop wraps inflate gaps (report-only); settings.json hand-edit could desync host rate vs engine rate (pass launched rate);
    staticMax 4 uncited.
