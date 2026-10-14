# live5 fold 3 — review live5 r2 (2026-10-14), W6 only

Read `.agents/reviews/cef-placement-2026-10-13/review-live5-r2.md` fully. Build on the uncommitted diff (W3's managed_obs.py change is
final; do not touch src/). Fold M1, Medium 1 (adopt the lenient option exactly as written there), Medium 2, and all four lows.
M1 needs a test that exercises the real capture_coverage on a complete record (no monkeypatch). Medium 1: record per-draw argument
count; reference = full-size draws (must agree, before == after); repair draws exactly one frame later → diagnostic; anything else
→ INCONCLUSIVE. Also verify the old live4/live5 evidence re-scores without "decoder/rVFC records malformed" for non-DSK arms.
Run tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py at -n 2.
