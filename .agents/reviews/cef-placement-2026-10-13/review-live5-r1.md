# Review live5 fold r1 (Opus 5.5 high), 2026-10-14 — not ready; W3 sound

- B1 blocker (`dissolve_probe.py:3209-3223`, used :3379): "latest expectedDisplayTime ≤ freezeDrawAt" is wrong — Chromium's
  drawImage(video) reads the compositor's current frame from presentationTime onward (expectedDisplayTime ≥ one BeginFrame later);
  A25 would FAIL; B25's drawn frame (presentedFrames 75→77) has no rVFC row. Tests build expectedDisplayTime < presentationTime.
  Fix: in the drawImage wrapper read `new VideoFrame(source)` before and after the native draw, record timestamp, close; before ≠
  after → INCONCLUSIVE; holder must equal round(ts/1e6*counter_fps); rVFC rows + rvAt diagnostics only; confirm take cost.
- M1 major (`managed_obs_qualify.py:2068-2083`): recapture keeps only the last attempt; a defect can trigger a retry (0 mid frames
  from malformed capture) and vanish. Fix: retry only when the sole problem is "{n} mid frames < 5"; persist every attempt's record
  + images (runs/<arm>/attempt-N); score every attempt; pass only if every attempt passes every non-coverage check.
- D1 medium: W3 persistent "unknown" ends as `_CalibrationTimeout`, which W6's ownership-abort label (:493) misses → iso FAIL
  again. Fix: on deadline with last observation "unknown", raise the ownership error (same message) or record it; extend test.
- D2 medium: m-fg-cef is a paused-capture arm (static region) — weaker than DX-1's playing m-on; no double counting; acceptable,
  record rationale. Coordinator rationale: CEF has no playing frozen-region PASS arm; m-fg-cef is an independent holder with a
  natural transition and scored region PASS on A30; m-hold-cef stays the FAIL control; m-snap-cef-dsk the moving-video candidate.
- L1 coverage computed for every arm; hard-coded 5 → CEF_PLACEMENT.mid_frames. L2 rename callbackLatenessMs. L3 move recapture
  assertions into their own/placement test.
