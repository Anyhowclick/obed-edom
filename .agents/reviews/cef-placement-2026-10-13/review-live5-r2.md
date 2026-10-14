# Review live5 fold r2 (Opus 5.5 high), 2026-10-14 — not ready (1 major); B1 and W3 D1 sound

- B1 sound: VideoFrame(video) and drawImage(video) both read the compositor's current frame; timestamp is media µs (live5 #t=5
  clip 7.5333 s ↔ holder 226 = 150+76); exceptions → INCONCLUSIVE; close() in finally; take cost stays ≪ 50 ms.
- M1 major (`managed_obs_qualify.py:2077`): capture_coverage scores only `driven` (no target/served/page/output) → extra problems →
  never "sole shortage" → retry never fires. Fix: score {**base_record, **driven}; one test with the real capture_coverage.
- Medium 1 (`dissolve_probe.py:3250`): a frame change across a decoder's draws (underlay, frac, readback, repairs; ~1–3 ms) voids
  the arm (~5–10% of DSK takes). Fix (coordinator: adopt, consistent with edgefix r1 L1): reference from full-size draws (must agree,
  before == after); a repair draw exactly one frame later is a diagnostic, not a void.
- Medium 2 (`:494`, `:513`): ownership label forces INCONCLUSIVE even with isolation_ok False / program check failed. Fix: also
  require isolation_ok and program_ok is not False; negative row (ownership error + isolation_ok False → FAIL).
- Lows: time-filter recorded draws to [advanceAt, first eff rAF] (`:3230`); coverage only when limit > 1 (`:2077`); freezeDraws
  optional (default []) for non-distinct decoders so old evidence re-scores (`:2846`); placement_gates writes ./record.json when a
  session is missing (`:3203`, `:3217`) — guard on runDir (the stray root `{}` from the 18:12 aborted run was trashed).
