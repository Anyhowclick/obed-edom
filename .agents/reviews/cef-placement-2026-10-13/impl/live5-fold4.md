# live5 fold 4 — review live5 r3 (2026-10-14), W6 only

Read `.agents/reviews/cef-placement-2026-10-13/review-live5-r3.md` fully (its "Coordinator decision" is binding). Build on the
uncommitted diff; do not touch src/.
- Major: replace the in-session re-drive with a session-level retry for the DSK arm only (`counter_strip == "distinct"`): when an
  attempt's sole problem is the mid-frame shortage, run the whole placement session again (fresh host/page, its own calibration
  transaction and recording, fresh hook state) in the same OBS launch, up to 3 attempts total; persist every attempt
  (runs/<arm>/attempt-N, records + images + calibration evidence), score every attempt with coverage disabled and all other checks
  on, arm passes only if every attempt MATCHes; the placement-evidence/control gates must account for each attempt's calibration
  (each must PASS). Remove the now-unused in-session re-drive path. Test with a fake host whose scene position persists and is
  forward-only, proving a second attempt starts from a fresh session (no "scene not reached"), plus the existing retry rules.
- Low 1: write record.json during rescoring only when it was loaded. Low 3: fix the indentation. Low 4: pass the session's
  calibration to capture_coverage if available; otherwise note it in the report.
Run tests/test_dissolve_probe.py tests/test_managed_obs_qualify.py at -n 2.
