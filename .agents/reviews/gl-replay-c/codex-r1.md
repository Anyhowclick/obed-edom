No blockers. Four findings survive.

## Spec / correctness

1. **Major — `scripts/p2_recovery_html_adversarial.py:696–715` — CLASSIFY: edge case.**  
   `_gl_probe_array` blindly coerces values to `uint8`, accepts boolean dimensions, and trusts reported `alphaMin`. Malformed bytes can raise and abort P2, wrap into a valid-looking counter, or allow transparent pixels with `alphaMin: 255` to pass clause (f).  
   **Suggested fix:** “Reject boolean dimensions; require every pixel to be a non-boolean integer in `[0,255]`; catch conversion and reshape failures; recompute alpha minimum from the decoded array; return `None` unless both computed and reported alpha minima equal 255.”

2. **Major — `src/obed_edom/p2_verdict.py:1079–1089` — CLASSIFY: edge case.**  
   A7′ counts integer indices without requiring `glProbeMeta.ok is True` and `alphaMin == 255`. Twelve records marked `{ok:false}` can pass if stale indices remain.  
   **Suggested fix:** “Compute `delta` only when `glProbeMeta.ok is True`, `alphaMin == 255`, and both counters are non-boolean integers in `[0,255]`; otherwise record `delta=None`; add failed- and missing-metadata known-bads.”

3. **Minor — `scripts/p2_recovery_html_adversarial.py:455–463` — CLASSIFY: edge case.**  
   Oracle lookup and `typeof h.probe` occur outside the `try`. A throwing oracle/probe getter rejects the evaluated IIFE, aborting P2 instead of producing a failed read and RED clause (f).  
   **Suggested fix:** “Move oracle lookup and probe-method validation inside the `try`, return `{ok:false, reason:'threw'}` for accessor failures, and add a throwing-getter test.”

4. **Minor — `tests/test_live_gl_replay_js.py:794–827` — CLASSIFY: new class.**  
   The fake’s TexImageSource `texSubImage2D` ignores `UNPACK_FLIP_Y_WEBGL`. Tests pin the y-offset argument but cannot detect an actually upside-down movie upload.  
   **Suggested fix:** “Model `UNPACK_FLIP_Y_WEBGL` in the fake’s TexImageSource upload and add an asymmetric top/bottom source test proving the inner texture is upright.”

## Standards

No additional documented-standard violations or correctness-relevant code smells survived. Core/host are unchanged, the flag-off wiring remains isolated, and the production P2 code contains exactly one oracle reference.