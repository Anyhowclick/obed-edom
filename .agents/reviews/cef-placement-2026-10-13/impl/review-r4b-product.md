# Code review r4b — off-canvas Studio sequencing (major/blocker only) — Opus 5.5 HIGH

Scope: `git diff 3eae0fde ae1c0f63` (`src/obed_edom/managed_obs.py`, `tests/test_managed_obs.py`), with context from
`W3-live2.md`. Read-only; no pytest. I read the full `_install_calibration` and `_cleanup_calibration` at `ae1c0f63`.

## Verdict: **0 blocker, 0 major.** Nothing to fold.

### Preview path (product runtime) is unchanged
- **Install:** the `placement == "preview"` branch is byte-for-byte the previous behaviour. If Studio was off it is
  enabled, the auto-selected preview is captured, then `SetCurrentPreviewScene(AK-Calibrate)` follows later.
- **Cleanup:** the restore-preview-before-Studio block is now gated on `placement == "preview"`, which is the only
  placement that used it before. The new `SetCurrentPreviewScene` after Studio restore applies only to off-canvas.
- **Unchanged:** the readback (Studio, program name/UUID, program items, preview identity or the 506 when Studio is
  off), absence, identity, persistence and the settle loop.

### Off-canvas Studio toggling (harness qualification only)
- **Effect on the live program.** The new mutations are a single `SetStudioModeEnabled(false)` before `CreateScene`
  (only when Studio was initially on) and `SetStudioModeEnabled(true)` after the reference is removed.
  - Neither is a transition-to-program call.
  - Studio on/off with the default `SceneDuplicationMode=true` is exactly what step 0 measured clean on a moving
    Program: 0 `visibilitychange`, maximum rAF gap 20.1 ms, program `AK` unchanged.
  - The program-identity verification (name and UUID) and the moving-Program guard still bracket the transaction, and
    W6's program-wire recording gates the off-canvas qualification.
  - Product runtime never selects off-canvas, so the toggle has no product exposure.
- **Restoration on every exit path (Studio initially on):**
  - The ordering is: disable the reference → remove the reference → remove input/scene by UUID → absence poll → restore
    the program scene if it changed → re-enable Studio → `SetCurrentPreviewScene(saved preview)` → full readback.
  - `snapshot.preview_name` is always set when Studio was initially on, because the precheck reads it and refuses on a
    506.
  - If the install-time `SetStudioModeEnabled(false)` fails or times out, `studio_changed` is already true. Cleanup then
    sees Studio still on, re-sets the saved preview and verifies.
  - If the cleanup re-enable fails, the preview write in the same `try` is skipped. The readback then reports Studio
    mismatched → `restored=False` and an isolation error. That fails closed and is never reported as clean.
  - A cleanup connection failure remains a cleanup failure (`restored=False`), as before.
- **Studio initially off:** off-canvas sends no Studio mutation at all, matching step 0. If something else enabled
  Studio during the run, the existing preview-snapshot block plus the Studio-off restore return it to the snapshot.
