**CHANGES REQUIRED**

Reviewed `a377080e` against rev 12 §9–9.2. **209 callable scorer cases passed in memory**; one filesystem-dependent case was excluded. An additional **90 malformed-evidence mutations all returned INCONCLUSIVE**. No full pytest suite or live captures were run; the reported 355 passed / 1 skipped remains implementer evidence.

**Round-one closure**

| R1 | Status | Reproduction result |
|---|---|---|
| 1 — Shared media integrity | **CLOSED** | Missing decoder evidence invalidates reference, engagement and CEF DSK arms, including the shifted `m-snap-frac` and its twin. |
| 2 — Incomplete hide controls | **CLOSED** | Both missing-interval reproductions return arm-level INCONCLUSIVE. |
| 3 — Overwritten tone mask | **CLOSED** | Cells wholly beneath the verified foreground mask produce INCONCLUSIVE. |
| 4 — Reference aliases / crop | **CLOSED** | Duplicate F50 identifiers, aliased perfect captures and the invalid perfect rectangle all produce INCONCLUSIVE. |
| 5 — Timestamp shifts | **CLOSED** | The +64 ms order-preserving shifts invalidate both `life-hide` and its stock control. |
| 6 — Incoming holder parent | **CLOSED** | `layer3-opacity` produces INCONCLUSIVE. |
| 7 — Injection evidence | **NOT CLOSED** | Original `[False]` modal reproduction is rejected; the semantic-evidence bypass below remains. |
| 8 — Reported tone coverage | **CLOSED** | Insufficient coverage invalidates the identity arm. |
| 9 — Launch-specific map | **CLOSED** | CEF rejects both decision-record fallbacks without a launch map. Measured tone-step / identity maps yield `L[128] = 139 / 128`; missing tone session yields no map. |

**Standards:** no substantive findings.

**Spec: two demonstrated remaining findings**

1. **Major — R1 #7 residual: an offscreen navigator qualifies the negative control.**  
   [dissolve_probe.py:2142](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2142)

   ```python
   r, images = media_run("m-raw-nav-open", holder=False)
   r["inject"]["box"] = [0., 10000., 130., 360.]
   ```

   Scoring normally returns **exterior FAIL, arm MATCH, problems=[]**, although the navigator lies entirely below the viewport. The validator checks horizontal placement but never verifies viewport intersection.

   **Fix:** require visible viewport intersection alongside `x ≈ 0`; unsuccessful injection evidence must invalidate the arm.

2. **Major — NEW: reference and engagement captures bypass required spatial classes.**  
   [dissolve_probe.py:2544](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/scripts/dissolve_probe.py:2544)

   §9.1 requires **“required classes ≥ 2 000 px; deviation INCONCLUSIVE.”** These profiles skip `_fade_of`, losing spatial-class validation together with temporal coverage.

   Demonstrated reproductions:

   - For `media_run("m-raw-caption", holder=False)` or `m-geo-scale`, zero both texture images. **Every texture class contains zero pixels**, yet exterior/geometry returns **FAIL, arm MATCH, problems=[]**.
   - For valid `m-snap` and its twin, set both `images["tex-in"][..., 3] = 255`. The required **out-only class becomes zero**, yet holder pixels, reference, mask and geometry all **PASS; arm MATCH; problems=[]**.

   **Fix:** validate required spatial classes independently of temporal coverage, including twins. The reference-profile exemption concerns fade coverage, not spatial completeness.

**Ambiguity resolutions**

- **Accept the `m-hold` parent rule.** The nearest common `layer<id>` matches the splice’s container placement. The valid reproduction remains MATCH with frozen-region FAIL; an incoming-wrapper parent becomes INCONCLUSIVE.
- **Accept measurement from the same launch’s `m-tone` session.** Its holder versus source screenshot, verified twin mask and coverage provide the requested launch-path measurement. The enforced map check and removal of CEF fallback close R1 #9.

**CHANGES REQUIRED**