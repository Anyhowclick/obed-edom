NON-INTERACTIVE, READ-ONLY INVESTIGATION (W6 stream). Do not edit the repo; no OBS/Chrome/Keynote, no pytest. Run any Python
with `nice -n 15` and single-threaded (set OMP_NUM_THREADS=1); another session is using the machine. Your FINAL message is the report.

Repo: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f (branch claude/cef-obs-placement, HEAD 2d64a25e
— frac boundary redraw + nooffset -80 + demix bound). Context: .agents/reviews/cef-placement-2026-10-13/ (review-edgefix-r1/r2,
impl/W1-edgefix*.md, impl/W6-live4*.md, impl/W6-edgefix-fold*.md), plan .agents/plans/keynote_live_cef_placement.plan.md rev 3.3 §5/§11.
SCR=/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad

Evidence (read-only; clone with `cp -cR` under SCR/w6live5/ before any scorer call that writes):
- On 2d64a25e: SCR/live5/out/runs/placement-20261014-{165947 (A 25), 172217 (A 30), 174926 (B 25)}.json + shots/<run>/runs/<arm>/.
- Before the edge fix (dd8c8753): SCR/live4/out/runs/placement-20261014-{123807,130028,132259,134519}.json + shots — DSK MATCHed in all four.

Diagnose and propose minimal fixes (classify PRODUCT / HARNESS / INSTRUMENT; say whether a §5/§11 contract or owner decision changes):
1. m-snap-cef-dsk: INCONCLUSIVE in A25 ("4 mid frames < 5"; "holder 1 frame 225 != decoder 10 frame 226") and B25 ("holder 0 frame
   75 != decoder 9 frame 76", "holder 1 frame 225 != decoder 10 frame 226"); MATCH in A30 and all four live4 takes. Is the holder truly
   one frame behind the last pre-detach presented frame (product: the frozen frame lags → visible 1-frame step back), or is the
   check's "last pre-detach rVFC frame" selection racy (rVFC callback fired for frame N+1 before detach but drawImage in the take
   captured N because the take ran earlier/later)? Compare dump.takes (the live5 failing runs have a last entry ~7 ms at an earlier
   time; live4/A30 last entry 0 ms), per-decoder rv lists (mediaTime/presentedFrames/expectedDisplayTime vs take time vs detach),
   W1's extra boundary draws (DSK holder 0 has one column repair), 25 vs 30 fps cadence. State what the frozen holder should show per
   §5/§11 (the frame on screen at the take) and whether the check or the product is wrong. Mid frames: is 4<5 just cadence (shot
   timing per shot) and what is the faithful remedy (never lower 5)?
2. wrongrule-cef-twin: "placement evidence" FAIL in B25 only. Re-score its placementCalibration offline (managed_obs_qualify
   score_placement_calibration on a clone) and report exactly which sub-gate failed and why (product calibration/isolation vs
   harness vs flake).
3. frozen_region gate: in A30 every arm MATCHes but gate frozen_region is INCONCLUSIVE "control m-snap-cef: missing (must PASS)" —
   CEF_PLACEMENT overrides (`dissolve_probe.py` ~:2720) use m-snap-cef (a paused capture that never produces frozen_region) as the
   positive control; the Chrome profile uses m-on. Propose the faithful positive control: an existing CEF media arm that freezes a
   holder and already produces a scored frozen_region PASS (check m-fg-cef, m-fg-omit-cef, m-hold-cef's twin, m-snap-cef-dsk, etc.
   in the saved details), or a new m-on-cef arm (gate cost +~28 s/rate). Prefer a scorer-only change if faithful, and verify by
   offline re-score of A30 that frozen_region would PASS with it (monkeypatch in scratch only).
Report per item: cause, class, evidence (file:line, numbers), proposed fix, and whether a fresh live run is needed to verify.
