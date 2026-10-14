# Review live5 fold r3 (Opus 5.5 high), 2026-10-14 — not ready (1 major); r2 findings fixed

Verified: M1 merged-record coverage (live5 A25 with freeze-draw rows → sole problem "4 mid frames < 5" → retry would fire; A25
MATCHes with mid_frames=0); Medium 1 lenient rule exact; Medium 2; four lows; W3 sound; ARMS/profile diff intended only; offline
A30 rescore through placement_gates OK (DSK old-evidence gaps only). Targeted 510 passed + 1 skipped; W3 calibration subset 35/35.

- Major (`managed_obs_qualify.py:2211-2218` → `dissolve_probe.drive` :4466): a retry re-drives forward-only from #17 of 20 scenes
  (loopSlideshow=0, no lifecycle row) → "scene 15 not reached" → record error, images {} — unrecoverable. Hidden risk: hook never
  resets `r.detach` (:584) / rVFC stops (:577) if elements are reused. Reviewer fix: goTo rewind + reset hook state + test.
  Coordinator decision: retry by re-running the WHOLE placement session for the DSK arm (fresh page, calibration, hook) inside the
  same OBS launch instead of re-driving — simpler and free of rewind/stale-state risk; +~71 s only on a coverage shortfall.
- Low 1 (:3220-3222): rescoring writes a stub record.json when runDir exists but record.json does not — write only when loaded.
- Low 2: ownership_aborted ignores cleanup/restored — acceptable by design (W3 persistent-unknown row); gate stays non-PASS.
- Low 3 (dissolve_probe.py:448-449): continuation indentation.
- Low 4: capture_coverage uses default Calibration() — fails closed if cal-dependent; note (use the session calibration if readily available).
