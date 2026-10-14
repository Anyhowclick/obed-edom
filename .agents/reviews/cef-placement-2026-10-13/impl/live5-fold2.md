# live5 fold 2 — review live5 r1 (2026-10-14)

Read `.agents/reviews/cef-placement-2026-10-13/review-live5-r1.md` fully. Build on the uncommitted diff.
- W6: B1 (VideoFrame timestamp before/after the native draw inside the existing harness-only wrapper; holder vs
  round(ts/1e6*counter_fps); mismatch before/after → INCONCLUSIVE; rVFC rows diagnostics only; record the take cost; tests with
  Chromium-faithful rows incl. a skipped presentedFrames and expectedDisplayTime ≥ presentationTime), M1, L1, L2, L3, and the W6
  side of D1 (label also the W3 shape once W3 raises the ownership error — coordinate by matching the exact message
  "Calibration engine ownership could not be verified."). Run tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py.
- W3: D1 product side — when the calibration deadline elapses while the last ownership observation was "unknown", raise the same
  ManagedObsError("Calibration engine ownership could not be verified.") instead of the timeout; persistent unknown still fails
  closed; extend the existing matrix row. Run tests/test_managed_obs.py (loopback sockets may be blocked in your sandbox; report
  the socket-free calibration subset counts; the coordinator runs the full file).
